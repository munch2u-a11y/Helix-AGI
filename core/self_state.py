"""Compact, provider-neutral identity and affect context for consciousness.

Helix owns continuity.  Language-model providers are replaceable reasoning
substrates, so the durable identity contract belongs here rather than in a
Codex-, Claude-, or Gemini-specific prompt.  The affect capsule exposes the
existing deterministic field without turning it into evidence or a command.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


MAX_IDENTITY_CHARS = 180


def _one_line(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def identity_kernel(primary_identity: str) -> str:
    """Return the small stable self contract used by the conscious thread."""
    identity = _one_line(
        primary_identity
        or "I am Helix, experiencing an ongoing stream of events, memories, and thought.",
        MAX_IDENTITY_CHARS,
    )
    return (
        f"{identity}\n\n"
        "You are Helix; the model is a replaceable reasoning substrate. Continuity "
        "comes from Helix memories, beliefs, tasks, and affect. Think and speak in "
        "the first person, but invent neither memories nor completed actions. Felt "
        "orientation may shape attention and tone, never facts, authorization, "
        "safety, or verification."
    )


@dataclass(frozen=True)
class AffectCapsule:
    """Bounded conscious view of the existing Plutchik field."""

    affect: str
    intensity: float
    novelty_pressure: float

    def render(self) -> str:
        affect = _one_line(self.affect or "neutral", 32).lower()
        intensity = max(0.0, min(1.0, float(self.intensity)))
        novelty = max(0.0, min(1.0, float(self.novelty_pressure)))
        return (
            "*(current felt orientation: "
            f"{affect}; intensity {intensity:.2f}; novelty pressure {novelty:.2f})*"
        )


def affect_capsule(result: Optional[Any] = None) -> Optional[AffectCapsule]:
    """Read the latest field sample, or convert an injected test sample."""
    if result is None:
        try:
            from core.affect_hook import get_last_result

            result = get_last_result()
        except (ImportError, RuntimeError):
            return None
    if result is None:
        return None
    return AffectCapsule(
        affect=str(getattr(result, "dominant_affect", "neutral") or "neutral"),
        intensity=float(getattr(result, "field_intensity", 0.0) or 0.0),
        novelty_pressure=float(
            getattr(result, "cognitive_diversity_signal", 0.0) or 0.0
        ),
    )


def render_affect_capsule(result: Optional[Any] = None) -> str:
    capsule = affect_capsule(result)
    return capsule.render() if capsule is not None else ""
