"""
Helix — Grammar-Constrained Tool Decoding

Local models are the only route where Helix can constrain generation at the
logit level rather than asking politely in a prompt. An API provider validates
a tool call after the fact; here a malformed or nonexistent call simply cannot
be emitted, because every token that would produce one is masked to -inf.

That guarantee is what lets a 3-4B local model use tools reliably. It is also
why the allowed tool set is a runtime property rather than a constructor
constant: a directed tool pass narrows the grammar to the one toolset it was
given (see ToolRegistry.subagent_manifest), so the model physically cannot
reach for a tool outside the group it is currently working in.

Grammar:

    IN_MONOLOGUE   anything, optionally opening the start tag `{[((`
    IN_ACTION      NAME "(" KWARGS ")" then the end tag `))]}`

Inside IN_ACTION every token is validated as a *prefix* of some legal call.
String literals accept any character — file paths, URLs and prose arguments
were previously rejected by a narrow charset, which silently made the whole
files/web/browser surface unreachable from local mode.
"""

import ast
import logging
import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Union

try:
    import numpy as np
except ImportError:
    pass

try:
    import torch
except ImportError:
    pass

logger = logging.getLogger("helix.llm.constrained_decoding")

# The boundary tags the grammar emits. Defined here so the parser and the
# logits processor can never drift apart.
ACTION_START = "{[(("
ACTION_END = "))]}"

_ACTION_RE = re.compile(
    r"\{\[\(\(\s*([a-zA-Z0-9_]+)\s*\((.*?)\)\s*\)\)\]\}",
    re.DOTALL,
)


def parse_action_tags(text: str) -> List[Tuple[str, Dict[str, Any]]]:
    """Extract `(tool_name, kwargs)` pairs from grammar-tagged output.

    Arguments are parsed with `ast.literal_eval` per keyword, so only
    literals cross the boundary — never arbitrary expressions. A keyword
    that fails to evaluate is dropped rather than failing the whole call,
    since a small model will occasionally emit one bad argument alongside
    several good ones.
    """
    actions: List[Tuple[str, Dict[str, Any]]] = []
    for match in _ACTION_RE.finditer(text or ""):
        tool_name = match.group(1)
        args_str = (match.group(2) or "").strip()
        args: Dict[str, Any] = {}
        if args_str:
            try:
                tree = ast.parse(f"f({args_str})", mode="eval")
                for keyword in tree.body.keywords:
                    if keyword.arg is None:
                        continue
                    try:
                        args[keyword.arg] = ast.literal_eval(keyword.value)
                    except (ValueError, SyntaxError):
                        logger.debug(
                            "Dropped non-literal argument %s for %s",
                            keyword.arg, tool_name,
                        )
            except (SyntaxError, ValueError, AttributeError) as e:
                logger.warning(
                    "Failed to parse arguments for %s: %r (%s)",
                    tool_name, args_str[:120], e,
                )
        actions.append((tool_name, args))
    return actions


def strip_action_tags(text: str) -> str:
    """Remove action blocks, leaving the surrounding prose."""
    return _ACTION_RE.sub("", text or "").strip()

# Candidate tokens considered per step. The mask only ever needs the tokens
# the model was actually likely to pick; scanning the full vocabulary per
# token would dominate generation time on consumer hardware.
DEFAULT_TOP_K = 100

# Characters legal in argument position outside a string literal. Inside a
# string literal everything is legal — see _scan_call.
_BARE_ARG_CHARS = set("abcdefghijklmnopqrstuvwxyz"
                      "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                      "0123456789_=,. +-[]{}:")

_NAME_CHARS = set("abcdefghijklmnopqrstuvwxyz"
                  "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                  "0123456789_")


class FSMLogitsProcessor:
    """Masks logits so generated tool calls are well-formed by construction.

    Args:
        tokenizer_decode: Callable(List[int]) -> str.
        tokenizer_vocab_size: Vocabulary size.
        allowed_tool_names: Tool names the grammar will accept. Empty means
            "any syntactically valid name", which is only appropriate when no
            registry is available — a live Helix always passes a real set.
        top_k: Candidate tokens evaluated per step.
    """

    def __init__(
        self,
        tokenizer_decode: Callable[[List[int]], str],
        tokenizer_vocab_size: int,
        allowed_tool_names: Optional[Iterable[str]] = None,
        top_k: int = DEFAULT_TOP_K,
    ):
        self.tokenizer_decode = tokenizer_decode
        self.vocab_size = tokenizer_vocab_size
        self.allowed_tool_names: List[str] = sorted(set(allowed_tool_names or []))
        self.top_k = max(1, int(top_k))

        self.start_tag = "{[(("
        self.end_tag = "))]}"

        # Single-token decodes are pure functions of the tokenizer, so they
        # are cached for the life of the process. Without this the top-k scan
        # costs `top_k` detokenizer calls on every generated token.
        self._token_text: Dict[int, str] = {}

        # Incremental decode of the running sequence. Generation is
        # sequential, so each call usually extends the previous one by a
        # single token; re-decoding the whole prefix each time is wasteful.
        self._cache_len: int = 0
        self._cache_text: str = ""

    # ── Runtime configuration ────────────────────────────────────────

    def set_allowed_tools(self, names: Optional[Iterable[str]]) -> None:
        """Narrow (or widen) the grammar to a specific set of tool names.

        Called when entering a directed tool pass so the grammar matches the
        Layer B manifest the model was just given.
        """
        self.allowed_tool_names = sorted(set(names or []))

    # ── Decoding helpers ─────────────────────────────────────────────

    def _decode_token(self, token_id: int) -> str:
        text = self._token_text.get(token_id)
        if text is None:
            try:
                text = self.tokenizer_decode([token_id])
            except Exception:
                text = ""
            self._token_text[token_id] = text
        return text

    def _decode_sequence(self, ids: List[int]) -> str:
        """Decode `ids`, reusing the previous decode when it is a prefix."""
        n = len(ids)
        if n >= self._cache_len and self._cache_len > 0:
            try:
                tail = self.tokenizer_decode(ids[self._cache_len:])
                text = self._cache_text + tail
            except Exception:
                text = self._full_decode(ids)
        else:
            # Shorter than the cache means a new generation started.
            text = self._full_decode(ids)
        self._cache_len = n
        self._cache_text = text
        return text

    def _full_decode(self, ids: List[int]) -> str:
        try:
            return self.tokenizer_decode(ids)
        except Exception:
            return ""

    def _get_current_state_and_text(self, input_ids: List[int]) -> Tuple[str, str]:
        """Return ("IN_ACTION", content_after_start_tag) or ("IN_MONOLOGUE", "")."""
        text = self._decode_sequence(input_ids)

        last_start = text.rfind(self.start_tag)
        last_end = text.rfind(self.end_tag)

        if last_start != -1 and last_start > last_end:
            return "IN_ACTION", text[last_start + len(self.start_tag):]

        return "IN_MONOLOGUE", ""

    # ── Grammar ──────────────────────────────────────────────────────

    def _scan_call(self, content: str) -> Optional[Dict[str, Any]]:
        """Scan a partial call body, returning its parse state or None.

        `content` is everything after the start tag. Returns None when the
        text can no longer become a legal call. Otherwise returns a dict with
        `phase` ("name", "args", "done"), `name` scanned so far, and whether
        parentheses are balanced.
        """
        i = 0
        n = len(content)

        # Leading whitespace before the tool name is tolerated.
        while i < n and content[i] in " \t":
            i += 1

        name_start = i
        while i < n and content[i] in _NAME_CHARS:
            i += 1
        name = content[name_start:i]

        if i >= n:
            return {"phase": "name", "name": name, "closed": False}

        while i < n and content[i] in " \t":
            i += 1
        if i >= n:
            return {"phase": "name", "name": name, "closed": False}

        if content[i] != "(":
            return None
        i += 1

        # Argument body: track string state and paren depth.
        depth = 1
        in_string: Optional[str] = None
        escaped = False
        while i < n:
            ch = content[i]
            if in_string is not None:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == in_string:
                    in_string = None
                # Any other character is legal inside a literal.
            else:
                if ch in ("'", '"'):
                    in_string = ch
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                elif ch not in _BARE_ARG_CHARS:
                    return None
            i += 1

        if depth > 0:
            return {"phase": "args", "name": name, "closed": False}

        # Past the closing paren only the end tag may follow.
        trailer = content[i:]
        if trailer and not self.end_tag.startswith(trailer):
            return None
        return {"phase": "done", "name": name, "closed": True}

    def _is_valid_prefix(self, proposed_content: str) -> bool:
        """True when `proposed_content` can still become a legal tool call."""
        if not proposed_content:
            return True

        state = self._scan_call(proposed_content)
        if state is None:
            return False

        if not self.allowed_tool_names:
            return True

        name = state["name"]
        if state["phase"] == "name":
            # Still typing: must remain a prefix of something real.
            return any(
                candidate.startswith(name)
                for candidate in self.allowed_tool_names
            )
        return name in self.allowed_tool_names

    # ── Masking ──────────────────────────────────────────────────────

    @staticmethod
    def _mask_logits_numpy(scores: Any, valid_indices: List[int]):
        mask = np.full(scores.shape, -np.inf, dtype=scores.dtype)
        mask[valid_indices] = scores[valid_indices]
        np.copyto(scores, mask)

    @staticmethod
    def _mask_logits_torch(scores: Any, valid_indices: List[int]):
        import torch
        mask = torch.full_like(scores, float("-inf"))
        if len(scores.shape) == 2:
            mask[:, valid_indices] = scores[:, valid_indices]
        else:
            mask[valid_indices] = scores[valid_indices]
        scores.copy_(mask)

    def _top_k_indices(self, scores: Any, is_numpy: bool) -> List[int]:
        k = min(self.top_k, int(scores.shape[-1]))
        if is_numpy:
            return np.argpartition(scores, -k)[-k:].tolist()
        top_k = torch.topk(scores, k).indices
        if len(top_k.shape) == 2:
            top_k = top_k[0]
        return top_k.tolist()

    def __call__(self, input_ids: Union[List[int], Any], scores: Any) -> Any:
        """Apply the FSM constraints to `scores` in place."""
        if hasattr(input_ids, "tolist"):
            ids_list = input_ids.tolist()
            if ids_list and isinstance(ids_list[0], list):
                ids_list = ids_list[0]
        else:
            ids_list = list(input_ids)

        ids_list = [t for t in ids_list if t >= 0]

        state, content_so_far = self._get_current_state_and_text(ids_list)
        if state == "IN_MONOLOGUE":
            return scores

        is_numpy = not hasattr(scores, "copy_")
        valid_indices: List[int] = []

        for token_id in self._top_k_indices(scores, is_numpy):
            token_str = self._decode_token(token_id)
            if not token_str:
                continue
            proposed = content_so_far + token_str

            if proposed.endswith(self.end_tag):
                body = proposed[: -len(self.end_tag)]
                parsed = self._scan_call(body)
                if parsed is not None and parsed["closed"]:
                    if (not self.allowed_tool_names
                            or parsed["name"] in self.allowed_tool_names):
                        valid_indices.append(token_id)
                continue

            if self._is_valid_prefix(proposed):
                valid_indices.append(token_id)

        # An empty candidate set means every likely token was illegal. Masking
        # to all -inf would make the sampler degenerate, so leave the scores
        # untouched and let the parser reject the call instead of producing
        # garbage.
        if not valid_indices:
            logger.debug(
                "No valid continuation among top-%d for action content %r",
                self.top_k, content_so_far[-80:],
            )
            return scores

        if is_numpy:
            self._mask_logits_numpy(scores, valid_indices)
        else:
            self._mask_logits_torch(scores, valid_indices)

        return scores
