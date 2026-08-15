"""Small, branch-oriented planner for Helix actions.

The planner sees toolset *briefs*, never the complete schema catalog.  It can
either ask one material clarification question or emit a few outcome-oriented
legs.  Each worker later receives one leg and one toolset manifest.

The wire format is deliberately plain and line based.  Local models are much
more reliable at emitting ``LEG | ...`` than nested JSON, and the system owns
all parsing, IDs, limits, and persistence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional
from uuid import uuid4


DEFAULT_MAX_LEGS = 4
DEFAULT_CONTEXT_TOKENS = 400
DEFAULT_LESSON_TOKENS = 150


def _approx_tokens(text: str) -> int:
    try:
        from memory.mrag.token_counting import count_text_tokens
        return count_text_tokens(text or "")
    except Exception:
        return max(1, len(text or "") // 4)


def _clamp(text: Any, limit: int) -> str:
    value = str(text or "").strip()
    if _approx_tokens(value) <= limit:
        return value
    return value[: max(0, int(limit)) * 4].rstrip() + "\n[...truncated...]"


@dataclass(frozen=True)
class ActionLeg:
    toolset: str
    objective: str
    success_check: str
    leg_id: str = field(default_factory=lambda: f"leg_{uuid4().hex[:10]}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ActionPlan:
    request: str
    legs: List[ActionLeg] = field(default_factory=list)
    question: str = ""
    error: str = ""
    prompt_tokens: int = 0

    @property
    def waiting_for_input(self) -> bool:
        return bool(self.question)

    @property
    def ready(self) -> bool:
        return bool(self.legs) and not self.question and not self.error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request": self.request,
            "legs": [leg.to_dict() for leg in self.legs],
            "question": self.question,
            "error": self.error,
            "prompt_tokens": self.prompt_tokens,
        }


_PROMPT = """Split this request into a compact action plan, or ask for one missing detail.

AVAILABLE TOOLSETS
{toolsets}
{lessons}{context}
REQUEST
{request}

If a material recipient, target, content, choice, or authorization is missing
or ambiguous, output exactly one line:
ASK | <one concise question>

Otherwise output 1 to {max_legs} ordered lines:
LEG | <toolset> | <outcome this leg must achieve> | <evidence that proves it>

Rules:
- Use only listed toolsets.
- Prefer fewer legs; add one only when a different toolset is needed.
- Gather needed information before mutation.
- Describe outcomes, not individual button presses or tool calls.
- A model statement is never completion evidence.
- Output only ASK or LEG lines."""


class ActionPlanner:
    """Compile a bounded action plan through one fresh model call."""

    def __init__(
        self,
        model_call: Callable[[str], str],
        *,
        max_legs: int = DEFAULT_MAX_LEGS,
        context_tokens: int = DEFAULT_CONTEXT_TOKENS,
        lesson_tokens: int = DEFAULT_LESSON_TOKENS,
    ):
        self.model_call = model_call
        self.max_legs = max(1, int(max_legs))
        self.context_tokens = max(0, int(context_tokens))
        self.lesson_tokens = max(0, int(lesson_tokens))
        self.last_prompt = ""
        self.last_output = ""

    def plan(
        self,
        request: str,
        toolsets: Mapping[str, str] | Iterable[str],
        *,
        context: str = "",
        lessons: str = "",
    ) -> ActionPlan:
        request = " ".join(str(request or "").split()).strip()
        available = self._toolsets(toolsets)
        if not request:
            return ActionPlan(request, error="No action request was provided.")
        if not available:
            return ActionPlan(request, error="No toolsets are currently available.")

        tool_lines = "\n".join(
            f"- {name}: {description}" if description else f"- {name}"
            for name, description in available.items()
        )
        lesson_block = _clamp(lessons, self.lesson_tokens)
        context_block = _clamp(context, self.context_tokens)
        prompt = _PROMPT.format(
            toolsets=tool_lines,
            lessons=("\nPRIOR VERIFIED OR FAILED ROUTES\n" + lesson_block + "\n")
            if lesson_block else "",
            context=("\nSCOPED RELEVANT CONTEXT\n" + context_block + "\n")
            if context_block else "",
            request=request,
            max_legs=self.max_legs,
        )
        self.last_prompt = prompt
        try:
            output = self.model_call(prompt)
            self.last_output = str(output or "")
        except Exception as exc:
            return ActionPlan(
                request,
                error=f"Action planning failed: {type(exc).__name__}: {exc}",
                prompt_tokens=_approx_tokens(prompt),
            )
        return self.parse(
            request,
            output,
            available,
            prompt_tokens=_approx_tokens(prompt),
        )

    def parse(
        self,
        request: str,
        output: Any,
        available: Mapping[str, str] | Iterable[str],
        *,
        prompt_tokens: int = 0,
    ) -> ActionPlan:
        names = set(self._toolsets(available))
        lines = [line.strip() for line in str(output or "").splitlines() if line.strip()]
        questions: List[str] = []
        legs: List[ActionLeg] = []
        invalid: List[str] = []
        for line in lines:
            parts = [part.strip() for part in line.split("|")]
            kind = parts[0].upper() if parts else ""
            if kind == "ASK" and len(parts) >= 2:
                question = " | ".join(parts[1:]).strip()
                if question:
                    questions.append(question)
                continue
            if kind == "LEG" and len(parts) == 4:
                toolset, objective, check = parts[1:]
                if toolset not in names or not objective or not check:
                    invalid.append(line)
                    continue
                legs.append(ActionLeg(toolset, objective, check))
                continue
            invalid.append(line)

        if questions:
            return ActionPlan(
                request,
                question=questions[0],
                prompt_tokens=prompt_tokens,
            )
        if not legs:
            detail = "" if not invalid else f" Invalid output: {invalid[0][:160]}"
            return ActionPlan(
                request,
                error="Planner produced no usable action legs." + detail,
                prompt_tokens=prompt_tokens,
            )
        return ActionPlan(
            request,
            legs=legs[: self.max_legs],
            prompt_tokens=prompt_tokens,
        )

    @staticmethod
    def _toolsets(
        toolsets: Mapping[str, str] | Iterable[str],
    ) -> Dict[str, str]:
        if isinstance(toolsets, Mapping):
            return {
                str(name).strip(): " ".join(str(description or "").split())
                for name, description in toolsets.items()
                if str(name).strip()
            }
        return {
            str(name).strip(): ""
            for name in toolsets
            if str(name).strip()
        }
