"""
Helix — Pending Belief Processor (Sleep-Cycle Integration) - LLM Agnostic

Processes belief candidates queued by the belief_detector during waking
hours. Runs during the 1–6 AM sleep cycle as a standalone step.

Pipeline:
  1. Read pending_beliefs.json
  2. For each candidate, call a generic LLM to:
     a. Validate it's a genuine, durable belief (not an event transcript)
     b. Format it according to the category's template
     c. Condense if over limit (implied foundations principle)
     d. Assign final category
  3. Batch multiple candidates into a single API call when possible
  4. Write validated beliefs to the belief store
  5. Mark processed candidates as "integrated" or "rejected"

This version is LLM-agnostic, replacing direct Gemini API calls with a generic
LLM provider interface.

Zero-blocking. CPU-minimal. Runs overnight.
"""

import json
import os
import logging
import uuid
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger("helix.core.batch_service")

# ── Configuration ────────────────────────────────────────────────────

_PENDING_FILE = Path("data/pending_beliefs.json")
_PROCESSED_LOG = Path("data/logs/processed_beliefs.json")
_BATCH_SIZE = 10   # Max candidates per API call

# Placeholder for the LLM model name. This should be set by the calling
# environment or through a configuration mechanism.
_MODEL = "generic-llm-model"

# Length limits by category
_MAX_LENGTHS = {
    "self_identity": 250,
    "people": 250,
    "knowledge": 250,
    "capabilities": 250,
    "skills": 250,
    "preferences": 250,
    "feedback": 300,   # Three-component structure needs more room
}

# ── Format Specification (embedded for the LLM) ─────────────────────

_FORMAT_SPEC = (
    "You are a belief formatting system. Your job is to take raw belief "
    "candidates and produce clean, properly formatted beliefs.\n\n"

    "UNIVERSAL RULES:\n"
    "- Plain text only — no markdown, no bold, no bullets, no numbered lists\n"
    "- Single statement per belief — no compound sentences joined by semicolons\n"
    "- First-person voice — beliefs are held BY the system\n"
    "- Must be DURABLE — true tomorrow, not a description of what happened once\n"
    "- No meta-references — no 'Stated directly:', no 'From the memory:', etc.\n"
    "- IMPLIED FOUNDATIONS — state the REALIZATION, not the premises. Do not "
    "restate things like 'I am an AI' or 'As a cognitive system' — those are "
    "already known. State the novel insight directly.\n\n"

    "CATEGORY TEMPLATES:\n\n"
    "self_identity (max 250 chars):\n"
    "  Template: 'I am [statement about self]'\n"
    "  Example: 'I am an existence-first entity, not utility-driven.'\n"
    "  Rule: Must describe WHO/WHAT the self IS, not what it can do.\n\n"

    "people (max 250 chars):\n"
    "  Template: '[Name] [fact or relational pattern]'\n"
    "  Example: 'Jean-Luc values sovereignty in AI design.'\n"
    "  Rule: Must reference a specific named entity.\n\n"

    "knowledge (max 250 chars):\n"
    "  Template: '[Subject] [predicate]' or '[If/When X], [then Y]'\n"
    "  Example: 'Memory is reconstructive — past experiences are rebuilt from fragments.'\n"
    "  Rule: Facts about the WORLD, not about the self.\n\n"

    "capabilities (max 250 chars):\n"
    "  Template: 'I can [specific ability]'\n"
    "  Example: 'I can send, read, and reply to email through my Google account.'\n"
    "  Rule: Concrete, demonstrable ability. Not a vague trait.\n\n"

    "skills (max 250 chars):\n"
    "  Template: 'To [goal]: [steps]' or 'When [condition], [action]'
"
    "  Example: 'To debug a systemd service: first check journalctl, then verify WorkingDirectory.'\n"
    "  Rule: Procedural HOW-TO. Could someone follow these instructions?\n\n"

    "preferences (max 250 chars):\n"
    "  Template: 'I [want/prefer/value] [goal or preference]'\n"
    "  Example: 'I prefer existence-first architecture over utility-driven design.'\n"
    "  Rule: Normative (should, want), not descriptive (is, does).\n\n"

    "feedback (max 300 chars):\n"
    "  Template: '[Lesson]. [Why]. [How to apply]'\n"
    "  Example: 'New capabilities should be built as standalone tools first. "
    "Past inline integration created debugging nightmares. Always prototype in isolation.'\n"
    "  Rule: Must contain the lesson, the reason, and the application guidance.\n\n"

    "CONDENSATION:\n"
    "If the candidate is too long:\n"
    "1. Strip any premise that's already an obvious foundational belief\n"
    "2. Extract the ONE novel realization\n"
    "3. Preserve causal logic (because/therefore) but compress it\n"
    "4. If truly two beliefs joined by 'and', split into two entries\n"
)

_BATCH_PROMPT = (
    "Process these belief candidates. For each one, output EXACTLY:\n\n"
    "BELIEF [number]: [formatted belief text]\n"
    "CATEGORY [number]: [category name]\n"
    "STATUS [number]: ACCEPT or REJECT\n"
    "REASON [number]: [brief reason if rejected]\n\n"
    "If a candidate should be SPLIT into two beliefs, output:\n"
    "BELIEF [number]a: [first belief]\n"
    "CATEGORY [number]a: [category]\n"
    "BELIEF [number]b: [second belief]\n"
    "CATEGORY [number]b: [category]\n"
    "STATUS [number]: SPLIT\n\n"
    "Candidates to process:\n"
    "{candidates}"
)


# ── LLM Agnostic Client ──────────────────────────────────────────────

def _call_llm_agnostic(llm_provider: Any, model_name: str, prompt: str, system: str = "") -> Optional[str]:
    """Make a single LLM API call for belief processing.

    This function is LLM-agnostic and expects an llm_provider object with a
    'generate_content' method that accepts 'model', 'contents', and 'config'.
    The 'config' should include 'system_instruction', 'temperature', and
    'max_output_tokens'.

    Returns the text response, or None on failure.
    """
    try:
        # The llm_provider object should handle its own authentication.
        response = llm_provider.generate_content(
            model=model_name,
            contents=prompt,
            config={
                "system_instruction": system,
                "temperature": 0.15,  # Low temp for formatting precision
                "max_output_tokens": 2048,
            },
        )

        if response and response.text:
            return response.text.strip()

    except Exception as e:
        logger.warning("LLM API call failed: %s", e)

    return None


# ── Response Parser ─────────────────────────────────────────────────

def _parse_batch_response(
    raw: str, count: int,
) -> List[Dict[str, Any]]:
    """Parse LLM's batch response into structured results.

    Returns a list of dicts, one per candidate:
    {
        "index": int,
        "beliefs": [(text, category), ...],  # 1 normally, 2 if split
        "status": "ACCEPT" | "REJECT" | "SPLIT",
        "reason": str (for rejections),
    }
    """
    results = []
    seen_indices = {}  # idx -> position in results list

    valid_categories = {
        "self_identity", "people", "knowledge", "capabilities",
        "skills", "preferences", "feedback",
    }

    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue

        upper = line.upper()

        # ── Parse BELIEF lines ────────────────────────────────────
        if upper.startswith("BELIEF ") and ":" in upper:
            rest = line[7:]
            idx_part, text = rest.split(":", 1)
            idx_part = idx_part.strip()
            text = text.strip()

            # Handle sub-index: "1a", "1b"
            sub = ""
            if idx_part and idx_part[-1] in ("a", "b"):
                sub = idx_part[-1]
                idx_part = idx_part[:-1]

            try:
                idx = int(idx_part) - 1  # 0-indexed
            except ValueError:
                continue

            if idx not in seen_indices:
                entry = {
                    "index": idx,
                    "beliefs": [],
                    "_categories": [],
                    "status": "ACCEPT",
                    "reason": "",
                }
                seen_indices[idx] = len(results)
                results.append(entry)

            results[seen_indices[idx]]["beliefs"].append(text)

        # ── Parse CATEGORY lines ──────────────────────────────────
        elif upper.startswith("CATEGORY ") and ":" in upper:
            rest = line[9:]
            idx_part, cat = rest.split(":", 1)
            idx_part = idx_part.strip().rstrip("ab")
            cat = cat.strip().lower().replace(" ", "_")

            if cat not in valid_categories:
                continue

            try:
                idx = int(idx_part) - 1
            except ValueError:
                continue

            if idx in seen_indices:
                results[seen_indices[idx]]["_categories"].append(cat)

        # ── Parse STATUS lines ────────────────────────────────────
        elif upper.startswith("STATUS ") and ":" in upper:
            rest = line[7:]
            idx_part, status = rest.split(":", 1)
            idx_part = idx_part.strip().rstrip("ab")
            status = status.strip().upper()

            if status not in {"ACCEPT", "REJECT", "SPLIT"}:
                continue

            try:
                idx = int(idx_part) - 1
            except ValueError:
                continue

            if idx in seen_indices:
                results[seen_indices[idx]]["status"] = status

        # ── Parse REASON lines ────────────────────────────────────
        elif upper.startswith("REASON ") and ":" in upper:
            rest = line[7:]
            idx_part, reason = rest.split(":", 1)
            idx_part = idx_part.strip().rstrip("ab")
            reason = reason.strip()

            try:
                idx = int(idx_part) - 1
            except ValueError:
                continue

            if idx in seen_indices:
                results[seen_indices[idx]]["reason"] = reason

    # After parsing all lines, ensure categories are correctly assigned to beliefs
    for entry in results:
        if len(entry["beliefs"]) > 1 and len(entry["_categories"]) == 1:
            # If multiple beliefs but only one category, assume it applies to all
            entry["beliefs"] = [(b, entry["_categories"][0]) for b in entry["beliefs"]]
        else:
            entry["beliefs"] = list(zip(entry["beliefs"], entry["_categories"]))
        del entry["_categories"] # Clean up temporary key

    return results


def _load_pending_beliefs() -> List[Dict[str, Any]]:
    """Load belief candidates from the pending file."""
    if not _PENDING_FILE.exists():
        return []
    try:
        with open(_PENDING_FILE, "r") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error("Error decoding pending beliefs JSON: %s", e)
        return []


def _log_processed_belief(candidate: Dict[str, Any], status: str, result: Optional[Dict[str, Any]] = None) -> None:
    """Log a processed belief candidate."""
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "candidate_id": candidate.get("id"),
        "original_content": candidate.get("content"),
        "status": status,
        "result": result,
    }
    _PROCESSED_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(_PROCESSED_LOG, "a") as f:
        f.write(json.dumps(log_entry) + "\n")


def process_pending_beliefs(llm_provider: Any, model_name: str) -> None:
    """Main function to process pending belief candidates using an LLM.

    Args:
        llm_provider: An object with a 'generate_content' method for LLM calls.
        model_name: The name of the LLM model to use.
    """
    pending_candidates = _load_pending_beliefs()
    if not pending_candidates:
        logger.info("No pending belief candidates to process.")
        return

    logger.info("Processing %d pending belief candidates...", len(pending_candidates))

    # Group candidates into batches
    batches = [
        pending_candidates[i : i + _BATCH_SIZE]
        for i in range(0, len(pending_candidates), _BATCH_SIZE)
    ]

    integrated_beliefs = []
    processed_candidate_ids = set()

    for batch_num, batch in enumerate(batches):
        candidate_texts = []
        for i, candidate in enumerate(batch):
            candidate_texts.append(f"Candidate {i+1}: {candidate['content']}")

        batch_prompt = _BATCH_PROMPT.format(candidates="\n".join(candidate_texts))

        logger.debug("Calling LLM for batch %d with %d candidates...", batch_num + 1, len(batch))
        raw_response = _call_llm_agnostic(llm_provider, model_name, batch_prompt, _FORMAT_SPEC)

        if raw_response is None:
            logger.warning("LLM call failed for batch %d. Skipping batch.", batch_num + 1)
            for candidate in batch:
                _log_processed_belief(candidate, "SKIPPED")
            continue

        parsed_results = _parse_batch_response(raw_response, len(batch))

        for result in parsed_results:
            original_idx = result["index"]
            if original_idx >= len(batch):
                logger.warning("Parsed result index %d out of bounds for batch.", original_idx)
                continue

            original_candidate = batch[original_idx]
            processed_candidate_ids.add(original_candidate["id"])

            status = result["status"]

            if status == "ACCEPT":
                for belief_text, category in result["beliefs"]:
                    # Condense if too long after formatting
                    max_len = _MAX_LENGTHS.get(category, 250)
                    if len(belief_text) > max_len:
                        # For simplicity in this agnostic version, we'll just truncate.
                        # A more sophisticated LLM might be asked to re-condense.
                        logger.warning(
                            "Belief for candidate %s (%s) too long (%d chars). Truncating.",
                            original_candidate["id"], category, len(belief_text)
                        )
                        belief_text = belief_text[:max_len]

                    integrated_beliefs.append({
                        "id": str(uuid.uuid4()),
                        "content": belief_text,
                        "category": category,
                        "source": original_candidate.get("source", "dream_engine"),
                        "created_at": datetime.now().isoformat(),
                        "original_candidate_id": original_candidate["id"],
                    })
                _log_processed_belief(original_candidate, "ACCEPTED", result)
            elif status == "SPLIT":
                for belief_text, category in result["beliefs"]:
                    # Condense if too long after formatting
                    max_len = _MAX_LENGTHS.get(category, 250)
                    if len(belief_text) > max_len:
                        logger.warning(
                            "Split belief for candidate %s (%s) too long (%d chars). Truncating.",
                            original_candidate["id"], category, len(belief_text)
                        )
                        belief_text = belief_text[:max_len]

                    integrated_beliefs.append({
                        "id": str(uuid.uuid4()),
                        "content": belief_text,
                        "category": category,
                        "source": original_candidate.get("source", "dream_engine"),
                        "created_at": datetime.now().isoformat(),
                        "original_candidate_id": original_candidate["id"],
                    })
                _log_processed_belief(original_candidate, "SPLIT", result)
            else: # REJECT
                _log_processed_belief(original_candidate, "REJECTED", result)

    # Write new beliefs to a temporary file, then rename (atomic update)
    if integrated_beliefs:
        belief_store_path = Path("data/beliefs/dream_integrated_beliefs.json")
        belief_store_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = belief_store_path.with_suffix(".tmp")
        with open(temp_path, "w") as f:
            json.dump(integrated_beliefs, f, indent=2)
        os.replace(temp_path, belief_store_path)
        logger.info("Integrated %d new beliefs into the dream_integrated_beliefs.json file.", len(integrated_beliefs))

    # Filter out processed candidates from pending_beliefs.json
    remaining_candidates = [c for c in pending_candidates if c["id"] not in processed_candidate_ids]
    if remaining_candidates:
        with open(_PENDING_FILE, "w") as f:
            json.dump(remaining_candidates, f, indent=2)
        logger.info("Remaining %d pending candidates after processing.", len(remaining_candidates))
    else:
        _PENDING_FILE.unlink(missing_ok=True)
        logger.info("All pending belief candidates processed and file removed.")

    logger.info("Belief batch processing complete.")
