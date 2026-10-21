"""Inspectable attention preferences, not action authorization or learned skill.

These bootstrap profiles change admission priority, never truncate a source or
reserve empty token slots. The selected model context remains the boundary.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from collections.abc import Mapping


DEFAULT_PROFILES = {
    "conversation": {"personal": 2.0, "prior_user": 2.0, "prior_assistant": 2.0, "work": 2.0, "task": 2.0},
    "action": {"procedures": 3.0, "observations": 2.5, "work": 2.5, "task": 2.0},
    "writing": {"procedures": 2.0, "recalled": 2.0, "personal": 1.5},
    "inquiry": {"recalled": 3.0, "observations": 2.0, "associations": 1.5, "work": 2.0},
    "reflection": {"thinking": 2.5, "recalled_thought": 2.5, "work": 2.0, "task": 2.0, "personal": 1.5},
    "environment": {"environment": 2.5},
    "module": {"module": 4.0, "work": 2.5, "environment": 0.25},
}


def resolve_profiles(overrides=None):
    profiles = {name: dict(values) for name, values in DEFAULT_PROFILES.items()}
    if overrides is not None and not isinstance(overrides, Mapping):
        raise ValueError("Context focus profiles must map activities to section priorities")
    for name, values in (overrides or {}).items():
        if name not in profiles:
            raise ValueError(f"Unknown context focus: {name}")
        if not isinstance(values, Mapping):
            raise ValueError(f"Context focus {name} must map sections to priorities")
        for section, weight in values.items():
            from core.pulse_context import SECTION_TITLES
            if section not in SECTION_TITLES:
                raise ValueError(f"Unknown focus section: {section}")
            if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(weight) or weight <= 0:
                raise ValueError("Context priorities must be finite positive numbers")
            profiles[name][section] = float(weight)
    return profiles


@dataclass(frozen=True)
class ContextFocus:
    weights: dict[str, float]
    source: str

    def priority(self, section, profiles):
        return sum(weight * profiles[name].get(section, 1.0)
                   for name, weight in self.weights.items()) / sum(self.weights.values())

    def receipt(self, profiles):
        return {"weights": dict(self.weights), "source": self.source,
                "profiles": profiles, "policy": "soft priority; no section quotas",
                "learning_status": "bootstrap heuristic, not a trained RWKV focus decoder"}


def infer_focus(query: str, query_source: str) -> ContextFocus:
    # Fresh input only. Recalled prose, ability descriptions and telemetry must
    # not drive the next pulse's activity classification. Mixed activities stay
    # mixed; these lexical hints cannot authorize an action or establish truth.
    words = set(re.findall(r"[a-z]+", query.casefold()))
    weights = {"reflection" if query_source != "fresh_events" else "conversation": 1.0}
    cues = {
        "action": {"open", "read", "move", "touch", "inspect", "run", "execute", "create", "edit", "write", "save"},
        "writing": {"write", "writing", "draft", "rewrite", "script", "code", "compose"},
        "inquiry": {"research", "investigate", "find", "search", "why", "compare", "check", "verify", "read"},
    }
    for name, terms in cues.items():
        if words & terms:
            weights[name] = 1.0
    return ContextFocus(weights, query_source)
