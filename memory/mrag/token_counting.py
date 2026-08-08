"""Token counting — vendored from Micro-RAG (mrag/core/token_counting.py).

Ported unchanged apart from the HELIX_* environment aliases below. tiktoken
stays optional; without it the counter falls back to a chars/4 heuristic.
"""

import os
from typing import Any, Dict, List, Optional

try:
    import tiktoken  # type: ignore
except ImportError:
    tiktoken = None


DEFAULT_TIKTOKEN_ENCODING = "cl100k_base"
CHAT_TOKENS_PER_MESSAGE = 3
CHAT_TOKENS_PER_NAME = 1
CHAT_REPLY_PRIMER_TOKENS = 3
_ENCODING_CACHE = {}
_TIKTOKEN_FAILED = False


def _resolve_tokenizer_config(
    model_name: Optional[str] = None,
    encoding_name: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    return {
        "model_name": (
            model_name
            or os.environ.get("HELIX_TOKENIZER_MODEL")
            or os.environ.get("MRAG_TOKENIZER_MODEL")
            or os.environ.get("MRAG_MODEL_NAME")
        ),
        "encoding_name": (
            encoding_name
            or os.environ.get("HELIX_TOKENIZER_ENCODING")
            or os.environ.get("MRAG_TOKENIZER_ENCODING")
            or DEFAULT_TIKTOKEN_ENCODING
        ),
    }


def _get_tiktoken_encoding(
    model_name: Optional[str] = None,
    encoding_name: Optional[str] = None,
):
    global _TIKTOKEN_FAILED

    if tiktoken is None or _TIKTOKEN_FAILED:
        return None, "heuristic"

    cfg = _resolve_tokenizer_config(model_name, encoding_name)
    resolved_model = cfg["model_name"]
    resolved_encoding = cfg["encoding_name"] or DEFAULT_TIKTOKEN_ENCODING
    cache_key = (resolved_model or "", resolved_encoding)

    if cache_key in _ENCODING_CACHE:
        return _ENCODING_CACHE[cache_key]

    try:
        if resolved_model:
            encoding = tiktoken.encoding_for_model(resolved_model)
            result = (encoding, f"tiktoken:model:{resolved_model}")
            _ENCODING_CACHE[cache_key] = result
            return result

        encoding = tiktoken.get_encoding(resolved_encoding)
        result = (encoding, f"tiktoken:encoding:{encoding.name}")
        _ENCODING_CACHE[cache_key] = result
        return result
    except Exception:
        _TIKTOKEN_FAILED = True
        return None, "heuristic"


def count_text_tokens(
    text: str,
    *,
    model_name: Optional[str] = None,
    encoding_name: Optional[str] = None,
) -> int:
    if not text:
        return 0

    encoding, _ = _get_tiktoken_encoding(model_name, encoding_name)
    if encoding is not None:
        return len(encoding.encode(text))

    return max(1, len(text) // 4)


def count_chat_tokens(
    messages: List[Dict[str, Any]],
    *,
    model_name: Optional[str] = None,
    encoding_name: Optional[str] = None,
    include_reply_primer: bool = True,
) -> int:
    total = CHAT_REPLY_PRIMER_TOKENS if include_reply_primer else 0
    for message in messages:
        total += CHAT_TOKENS_PER_MESSAGE
        total += count_text_tokens(
            str(message.get("role", "")),
            model_name=model_name,
            encoding_name=encoding_name,
        )
        total += count_text_tokens(
            str(message.get("content", "")),
            model_name=model_name,
            encoding_name=encoding_name,
        )
        if "name" in message:
            total += CHAT_TOKENS_PER_NAME
            total += count_text_tokens(
                str(message.get("name", "")),
                model_name=model_name,
                encoding_name=encoding_name,
            )
    return total


def describe_token_counter(
    *,
    model_name: Optional[str] = None,
    encoding_name: Optional[str] = None,
) -> Dict[str, str]:
    cfg = _resolve_tokenizer_config(model_name, encoding_name)
    encoding, source = _get_tiktoken_encoding(model_name, encoding_name)
    if encoding is not None:
        return {
            "backend": "tiktoken",
            "source": source,
            "encoding": getattr(encoding, "name", cfg["encoding_name"] or DEFAULT_TIKTOKEN_ENCODING),
            "model_name": cfg["model_name"] or "",
            "chat_scheme": "OpenAI-style message framing (3 tokens/message + 3 reply primer)",
        }

    return {
        "backend": "heuristic",
        "source": "chars/4 fallback",
        "encoding": "",
        "model_name": cfg["model_name"] or "",
        "chat_scheme": "OpenAI-style message framing with heuristic text counts",
    }
