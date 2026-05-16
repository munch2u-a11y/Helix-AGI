"""
Helix — Context Compressor (Rolling Context Window Management)

Adapted from Hermes's ContextCompressor. Replaces hard context resets
with rolling compression that preserves conversational continuity.

Algorithm:
  Phase 1 — Cheap pre-pass (no API call):
    - Replace old tool results with 1-line summaries
    - Truncate large tool_call arguments
    - Deduplicate identical tool results
  Phase 2 — LLM summarization (1 cheap API call):
    - Serialize middle turns into structured text
    - Send to auxiliary model with Helix-specific template
    - On re-compression, iteratively update previous summary
  Phase 3 — Session reassembly:
    - Head (system + first exchange) + Summary + Tail (recent context)
    - Sanitize orphaned tool_call / result pairs
    - Anti-thrashing protection

Trigger conditions:
  - Primary: prompt_token_count > 50% of context limit
  - Secondary: focus_drift > 1.5 (replaces hard reset)
  - Emergency: prompt_token_count > 80% of context limit
"""

import json
import hashlib
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("helix.core.context_compressor")

# Prefix for compaction summaries — tells the model this is a chronological continuation
SUMMARY_PREFIX = (
    "[COGNITIVE CONTINUITY] The following is a seamless continuation of your "
    "recent thoughts, actions, and experiences, compacted for memory efficiency. "
    "You have already experienced everything described here in exactly this order. "
    "Resume your train of thought naturally from the final events described. "
    "Respond ONLY to events that occur AFTER this narrative."
)

# Chars per token estimate
_CHARS_PER_TOKEN = 4
# Minimum summary tokens
_MIN_SUMMARY_TOKENS = 1500
# Summary ratio (proportion of compressed content)
_SUMMARY_RATIO = 0.20
# Max summary tokens
_SUMMARY_TOKENS_CEILING = 8000
# Placeholder for pruned tool results
_PRUNED_TOOL_PLACEHOLDER = "[Old tool output cleared to save context space]"


def _content_length(content: Any) -> int:
    """Return effective char-length of message content."""
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for p in content:
            if isinstance(p, str):
                total += len(p)
            elif isinstance(p, dict):
                total += len(p.get("text", "") or "")
        return total
    return len(str(content or ""))


def _content_text(content: Any) -> str:
    """Best-effort text view of content for substring checks."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return str(content)


class ContextCompressor:
    """Rolling context compressor for Helix's Gemini chat sessions.

    Monitors token count and focus drift, triggering compression when
    thresholds are exceeded. Replaces the hard context reset with
    smooth rolling summarization.
    """

    def __init__(
        self,
        context_length: int = 1_000_000,
        threshold_percent: float = 0.50,
        emergency_percent: float = 0.80,
        protect_first_n: int = 2,
        summary_target_ratio: float = 0.20,
        auxiliary_model: str = "gemini-3.1-flash-lite-preview",
    ):
        self.context_length = context_length
        self.threshold_percent = threshold_percent
        self.emergency_percent = emergency_percent
        self.protect_first_n = protect_first_n
        self.summary_target_ratio = max(0.10, min(summary_target_ratio, 0.80))
        self.auxiliary_model = auxiliary_model

        # Computed thresholds
        self.threshold_tokens = int(context_length * threshold_percent)
        self.emergency_tokens = int(context_length * emergency_percent)

        # Tail budget: how many tokens of recent context to protect
        self.tail_token_budget = int(
            self.threshold_tokens * self.summary_target_ratio
        )
        self.max_summary_tokens = min(
            int(context_length * 0.05), _SUMMARY_TOKENS_CEILING
        )

        # State
        self.compression_count = 0
        self._previous_summary: Optional[str] = None
        self._last_compression_savings_pct: float = 100.0
        self._ineffective_compression_count: int = 0

        logger.info(
            "ContextCompressor initialized: context=%d threshold=%d (%.0f%%) "
            "emergency=%d tail_budget=%d aux_model=%s",
            context_length, self.threshold_tokens,
            threshold_percent * 100, self.emergency_tokens,
            self.tail_token_budget, auxiliary_model,
        )

    def should_compress(self, prompt_tokens: int) -> bool:
        """Check if compression should fire.

        Includes anti-thrashing: skips if 2+ consecutive compressions
        each saved less than 10%.
        """
        if prompt_tokens < self.threshold_tokens:
            return False
        if self._ineffective_compression_count >= 2:
            # Only override anti-thrash for emergency
            if prompt_tokens >= self.emergency_tokens:
                logger.warning(
                    "Emergency compression override — %d tokens > emergency %d",
                    prompt_tokens, self.emergency_tokens,
                )
                return True
            logger.warning(
                "Compression skipped — last %d compressions saved <10%% each",
                self._ineffective_compression_count,
            )
            return False
        return True

    def reset(self):
        """Reset compressor state (e.g., on full session restart)."""
        self._previous_summary = None
        self._last_compression_savings_pct = 100.0
        self._ineffective_compression_count = 0

    # ── Phase 1: Tool Result Pruning (no API call) ───────────────────

    def _prune_tool_results(
        self,
        messages: List[Dict[str, Any]],
        tail_start_idx: int,
    ) -> tuple:
        """Replace old tool results with informative 1-line summaries.

        Only prunes messages BEFORE tail_start_idx (the protected tail).
        Returns (pruned_messages, prune_count).
        """
        result = [m.copy() for m in messages]
        pruned = 0

        # Build function_call name index from the model's responses
        # In Gemini format, function calls are parts with function_call attr
        # and results are parts with function_response attr.
        # For our purposes, we look for content that looks like tool results.
        #
        # Gemini history format:
        #   {"role": "user", "parts": [{"text": "..."}]}
        #   {"role": "model", "parts": [{"function_call": {"name": "...", "args": {...}}}]}
        #   {"role": "user", "parts": [{"function_response": {"name": "...", "response": {...}}}]}

        # Pass 1: Deduplicate identical content
        content_hashes: Dict[str, int] = {}  # hash -> newest index
        for i in range(len(result) - 1, -1, -1):
            if i >= tail_start_idx:
                continue  # Don't touch protected tail
            msg = result[i]
            content_str = self._extract_text_content(msg)
            if not content_str or len(content_str) < 200:
                continue
            h = hashlib.md5(content_str.encode("utf-8", errors="replace")).hexdigest()[:12]
            if h in content_hashes:
                # This is an older duplicate — replace
                self._set_text_content(
                    result[i],
                    "[Duplicate content — same as a more recent message]",
                )
                pruned += 1
            else:
                content_hashes[h] = i

        # Pass 2: Summarize old function responses
        for i in range(tail_start_idx):
            msg = result[i]
            parts = msg.get("parts", [])
            new_parts = []
            modified = False

            for part in parts:
                if isinstance(part, dict) and "function_response" in part:
                    fr = part["function_response"]
                    name = fr.get("name", "unknown")
                    response = fr.get("response", {})
                    result_str = str(response.get("result", ""))

                    if len(result_str) > 200:
                        summary = self._summarize_tool_result(name, result_str)
                        new_parts.append({
                            "function_response": {
                                "name": name,
                                "response": {"result": summary},
                            }
                        })
                        if "id" in fr:
                            new_parts[-1]["function_response"]["id"] = fr["id"]
                        pruned += 1
                        modified = True
                        continue

                new_parts.append(part)

            if modified:
                result[i] = {**msg, "parts": new_parts}

        # Pass 3: Truncate large function_call arguments
        for i in range(tail_start_idx):
            msg = result[i]
            parts = msg.get("parts", [])
            new_parts = []
            modified = False

            for part in parts:
                if isinstance(part, dict) and "function_call" in part:
                    fc = part["function_call"]
                    args = fc.get("args", {})
                    args_str = json.dumps(args, default=str)
                    if len(args_str) > 500:
                        # Truncate large string values in args
                        truncated_args = self._truncate_args(args)
                        new_parts.append({
                            "function_call": {
                                "name": fc.get("name", ""),
                                "args": truncated_args,
                            }
                        })
                        if "id" in fc:
                            new_parts[-1]["function_call"]["id"] = fc["id"]
                        modified = True
                        continue

                new_parts.append(part)

            if modified:
                result[i] = {**msg, "parts": new_parts}

        return result, pruned

    def _summarize_tool_result(self, tool_name: str, result_str: str) -> str:
        """Create a 1-line summary of a tool result."""
        content_len = len(result_str)

        summaries = {
            "reply": f"[reply] delivered message ({content_len} chars)",
            "send_message": f"[send_message] sent message ({content_len} chars)",
            "memory_recall": f"[memory_recall] returned {content_len} chars of memories",
            "memory_store": "[memory_store] stored memory successfully",
            "duckduckgo_search": f"[search] returned {content_len} chars of results",
            "read_url": f"[read_url] fetched page ({content_len} chars)",
            "read_file": f"[read_file] read file ({content_len} chars)",
            "journal": "[journal] entry saved",
            "note": "[note] saved to scratchpad",
            "list_notes": f"[list_notes] returned {content_len} chars",
        }

        if tool_name in summaries:
            return summaries[tool_name]

        # Fallback: generic summary with preview
        preview = result_str[:100].replace("\n", " ")
        return f"[{tool_name}] {preview}... ({content_len} chars total)"

    def _truncate_args(self, args: Dict[str, Any], max_str_len: int = 200) -> Dict[str, Any]:
        """Truncate long string values in tool call arguments."""
        result = {}
        for k, v in args.items():
            if isinstance(v, str) and len(v) > max_str_len:
                result[k] = v[:max_str_len] + "...[truncated]"
            elif isinstance(v, dict):
                result[k] = self._truncate_args(v, max_str_len)
            else:
                result[k] = v
        return result

    # ── Phase 2: LLM Summarization ───────────────────────────────────

    def _compute_summary_budget(self, turns: List[Dict[str, Any]]) -> int:
        """Scale summary token budget with content being compressed."""
        content_tokens = self._estimate_tokens(turns)
        budget = int(content_tokens * _SUMMARY_RATIO)
        return max(_MIN_SUMMARY_TOKENS, min(budget, self.max_summary_tokens))

    def _serialize_for_summary(self, turns: List[Dict[str, Any]]) -> str:
        """Serialize Gemini-format turns into labeled text for summarizer."""
        parts_out = []

        for msg in turns:
            role = msg.get("role", "unknown")
            parts = msg.get("parts", [])

            for part in parts:
                if isinstance(part, dict):
                    if "text" in part:
                        text = part["text"]
                        if len(text) > 4000:
                            text = text[:3000] + "\n...[truncated]...\n" + text[-800:]
                        label = "MODEL" if role == "model" else "USER"
                        parts_out.append(f"[{label}]: {text}")

                    elif "function_call" in part:
                        fc = part["function_call"]
                        name = fc.get("name", "?")
                        args = fc.get("args", {})
                        args_str = json.dumps(args, default=str)
                        if len(args_str) > 500:
                            args_str = args_str[:500] + "..."
                        parts_out.append(f"[TOOL CALL]: {name}({args_str})")

                    elif "function_response" in part:
                        fr = part["function_response"]
                        name = fr.get("name", "?")
                        response = fr.get("response", {})
                        result_str = str(response.get("result", ""))
                        if len(result_str) > 4000:
                            result_str = result_str[:3000] + "\n...[truncated]...\n" + result_str[-800:]
                        parts_out.append(f"[TOOL RESULT {name}]: {result_str}")

                elif isinstance(part, str):
                    label = "MODEL" if role == "model" else "USER"
                    text = part
                    if len(text) > 4000:
                        text = text[:3000] + "\n...[truncated]...\n" + text[-800:]
                    parts_out.append(f"[{label}]: {text}")

        return "\n\n".join(parts_out)

    def _generate_summary(
        self,
        turns: List[Dict[str, Any]],
        spatial_state: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Generate a structured summary of conversation turns.

        Uses a Helix-specific template that captures spatial state,
        conversation threads, and cognitive tensions.
        """
        summary_budget = self._compute_summary_budget(turns)
        content = self._serialize_for_summary(turns)

        # Natural recollection template — compression should read like
        # how you'd actually think back on what just happened.
        template = f"""Compress these conversation turns into natural first-person recollection \
— the way someone would think back on what just happened.
- Use direct quotes for what people said: '<name> asked "what are you up to?"'
- Include responses and thoughts naturally: 'I told him about the migration, \
then started thinking about...'
- Maintain strict chronological order with timestamps where they appeared.
- Preserve specific facts, names, and unresolved threads exactly.
- This should read like natural recall of a recent conversation, not a report.
- Do not add commentary, analysis, or anything that wasn't in the original turns.

Target ~{summary_budget} tokens. Only output the recollection, no preamble."""

        _preamble = (
            "You are compressing a conversation history for cognitive continuity. "
            "Write as the speaker naturally recalling what just happened. "
            "Use direct quotes. Maintain chronological flow. "
            "Do not add commentary, analysis, or anything that wasn't in the "
            "original turns."
        )

        if self._previous_summary:
            prompt = (
                f"{_preamble}\n\n"
                f"You are UPDATING a previous recollection. Preserve existing "
                f"content, add new events.\n\n"
                f"PREVIOUS RECOLLECTION:\n{self._previous_summary}\n\n"
                f"NEW TURNS TO INCORPORATE:\n{content}\n\n"
                f"Continue with:\n{template}"
            )
        else:
            prompt = (
                f"{_preamble}\n\n"
                f"TURNS TO COMPRESS:\n{content}\n\n"
                f"{template}"
            )

        # Add spatial state if available
        if spatial_state:
            gamma = spatial_state.get("gamma", "?")
            vel = spatial_state.get("velocity_mag", "?")
            id_dist = spatial_state.get("identity_dist", "?")
            prompt += (
                f"\n\nCurrent spatial state for the summary: "
                f"gamma={gamma}, velocity={vel}, identity_distance={id_dist}"
            )

        try:
            from google import genai
            import os

            key = os.environ.get("GEMINI_API_KEY", "")
            if not key:
                logger.warning("No GEMINI_API_KEY — cannot generate summary")
                return None

            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model=self.auxiliary_model,
                contents=prompt,
            )

            summary_text = response.text.strip()
            self._previous_summary = summary_text
            return f"{SUMMARY_PREFIX}\n\n{summary_text}"

        except Exception as e:
            logger.warning("Summary generation failed: %s", e)
            return None

    # ── Phase 3: Compression ─────────────────────────────────────────

    def compress(
        self,
        messages: List[Dict[str, Any]],
        current_tokens: int = 0,
        spatial_state: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Compress conversation messages by summarizing middle turns.

        Args:
            messages: Gemini-format message history (list of Content dicts)
            current_tokens: Current prompt token count
            spatial_state: Current physics engine spatial state

        Returns:
            Compressed message list ready for new session creation.
        """
        n_messages = len(messages)
        min_for_compress = self.protect_first_n + 4
        if n_messages <= min_for_compress:
            logger.warning(
                "Cannot compress: only %d messages (need > %d)",
                n_messages, min_for_compress,
            )
            return messages

        display_tokens = current_tokens or self._estimate_tokens(messages)

        # Phase 1: Find tail boundary by token budget
        tail_start = self._find_tail_cut(messages)
        compress_start = self.protect_first_n

        if compress_start >= tail_start:
            logger.info("Nothing to compress — all messages in head/tail")
            return messages

        # Phase 1b: Prune old tool results
        messages, pruned = self._prune_tool_results(messages, tail_start)
        if pruned:
            logger.info("Pre-compression: pruned %d old tool result(s)", pruned)

        # Phase 2: Summarize middle turns
        turns_to_summarize = messages[compress_start:tail_start]

        logger.info(
            "Context compression triggered (%d tokens >= %d threshold). "
            "Summarizing turns %d-%d (%d turns), protecting %d head + %d tail",
            display_tokens, self.threshold_tokens,
            compress_start + 1, tail_start, len(turns_to_summarize),
            compress_start, n_messages - tail_start,
        )

        summary = self._generate_summary(turns_to_summarize, spatial_state)

        # Phase 3: Assemble compressed history
        compressed = []

        # Head (protected)
        for i in range(compress_start):
            compressed.append(messages[i])

        # Summary message (as a user message so model treats it as context)
        if summary:
            compressed.append({
                "role": "user",
                "parts": [{"text": summary}],
            })
        else:
            # Fallback: static marker if summary generation failed
            n_dropped = tail_start - compress_start
            fallback = (
                f"{SUMMARY_PREFIX}\n\n"
                f"Summary generation was unavailable. {n_dropped} message(s) "
                f"were removed to free context space. Continue based on "
                f"recent messages below."
            )
            compressed.append({
                "role": "user",
                "parts": [{"text": fallback}],
            })
            logger.warning(
                "Summary generation failed — inserted static fallback "
                "(%d turns dropped)", n_dropped,
            )

        # Tail (protected recent context)
        for i in range(tail_start, n_messages):
            compressed.append(messages[i])

        self.compression_count += 1

        # Track effectiveness
        new_estimate = self._estimate_tokens(compressed)
        saved = display_tokens - new_estimate
        savings_pct = (saved / display_tokens * 100) if display_tokens > 0 else 0
        self._last_compression_savings_pct = savings_pct
        if savings_pct < 10:
            self._ineffective_compression_count += 1
        else:
            self._ineffective_compression_count = 0

        logger.info(
            "Compressed: %d -> %d messages (~%d tokens saved, %.0f%%)",
            n_messages, len(compressed), saved, savings_pct,
        )

        return compressed

    # ── Helpers ───────────────────────────────────────────────────────

    def _find_tail_cut(self, messages: List[Dict[str, Any]]) -> int:
        """Walk backward, accumulating tokens until tail budget is reached.

        Returns the index where the protected tail starts.
        """
        n = len(messages)
        head_end = self.protect_first_n
        min_tail = min(3, n - head_end - 1) if n - head_end > 1 else 0
        soft_ceiling = int(self.tail_token_budget * 1.5)
        accumulated = 0
        cut_idx = n

        for i in range(n - 1, head_end - 1, -1):
            msg_tokens = self._estimate_message_tokens(messages[i])
            if accumulated + msg_tokens > soft_ceiling and (n - i) >= min_tail:
                break
            accumulated += msg_tokens
            cut_idx = i

        # Ensure minimum tail protection
        fallback_cut = n - min_tail
        if cut_idx > fallback_cut:
            cut_idx = fallback_cut

        # Don't cut into the head
        if cut_idx <= head_end:
            cut_idx = max(fallback_cut, head_end + 1)

        return max(cut_idx, head_end + 1)

    def _estimate_message_tokens(self, message: Dict[str, Any]) -> int:
        """Rough token estimate for a single Gemini message."""
        total = 10  # role/metadata overhead
        for part in message.get("parts", []):
            if isinstance(part, dict):
                if "text" in part:
                    total += len(part["text"]) // _CHARS_PER_TOKEN
                elif "function_call" in part:
                    fc = part["function_call"]
                    total += len(json.dumps(fc.get("args", {}), default=str)) // _CHARS_PER_TOKEN + 20
                elif "function_response" in part:
                    fr = part["function_response"]
                    total += len(str(fr.get("response", {}))) // _CHARS_PER_TOKEN + 20
            elif isinstance(part, str):
                total += len(part) // _CHARS_PER_TOKEN
        return total

    def _estimate_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """Rough token estimate for a list of messages."""
        return sum(self._estimate_message_tokens(m) for m in messages)

    def _extract_text_content(self, message: Dict[str, Any]) -> str:
        """Extract all text content from a Gemini message."""
        texts = []
        for part in message.get("parts", []):
            if isinstance(part, dict) and "text" in part:
                texts.append(part["text"])
            elif isinstance(part, str):
                texts.append(part)
        return "\n".join(texts)

    def _set_text_content(self, message: Dict[str, Any], new_text: str):
        """Replace all text parts in a message with new_text."""
        message["parts"] = [{"text": new_text}]
