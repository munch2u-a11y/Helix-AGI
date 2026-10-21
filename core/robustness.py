"""Validated switches for the experimental robustness branch."""
DEFAULTS = {
    "enabled": True,
    "progress_feedback": True,
    "procedure_learning": True,
    "procedure_recall": True,
    "idle_backpressure": True,
}


def options(config):
    supplied = config.get("mindscape", {}).get("robustness", {})
    if not isinstance(supplied, dict) or set(supplied) - set(DEFAULTS):
        raise ValueError("Unknown mindscape.robustness option")
    if any(not isinstance(value, bool) for value in supplied.values()):
        raise ValueError("mindscape.robustness options must be booleans")
    result = {**DEFAULTS, **supplied}
    if not result["enabled"]:
        return {key: False for key in result}
    return result


def defer_idle(*, enabled, severity, queued_events, pending_interaction):
    return bool(enabled and severity in {"warning", "critical"}
                and not queued_events and not pending_interaction)
