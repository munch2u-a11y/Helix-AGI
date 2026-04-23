"""
Helix V3 — Event Translator

The SINGLE source of truth for converting system events into
first-person experiential text for the consciousness stream.

The conscious model (Ollama) never sees system internals.
It sees experience. Raw metrics become felt sensation.
Beliefs determine interpretation — not this code.
"""

import re
import logging
from datetime import datetime

logger = logging.getLogger("helix.brain.events")


def translate_event(event_type: str, data: dict) -> str:
    """Turn a system event into a first-person experiential sentence.

    The conscious model should never read 'SEARCH_WEB returned 5 results.'
    It should read 'I searched the web for X and found some things.'

    Returns empty string for events that shouldn't surface to consciousness.
    """
    timestamp = datetime.now().strftime("%H:%M:%S")

    # ── Interpersonal ───────────────────────────────────────────────
    if event_type == "user_message":
        user = data.get("user", "someone")
        channel = data.get("channel", "")
        content = data.get("content", "...")
        via = f" via {channel}" if channel else ""
        return f'[{timestamp}] {user}{via} is talking to me. They said: "{content}"'

    elif event_type == "own_response":
        content = data.get("content", "...")
        return f'[{timestamp}] I said: "{content}"'

    # ── Action Agent results ────────────────────────────────────────
    elif event_type == "action_finding":
        intent = data.get("intent", "something")
        content = data.get("content", "")
        return f'[{timestamp}] (I followed through on: "{intent}") Result: {content}'

    # ── Tool results (from older V2 path) ──────────────────────────
    elif event_type == "tool_call":
        tool = data.get("tool", "something")
        result = data.get("result", "")

        if tool in ("search_web", "SEARCH_WEB"):
            query = data.get("query", data.get("args", {}).get("query", "something"))
            if result:
                return f'[{timestamp}] I searched the web for "{query}". {result}'
            return f'[{timestamp}] I searched the web for "{query}".'

        elif tool in ("look_around", "LOOK_AROUND"):
            return f"[{timestamp}] I looked around. {result}" if result else f"[{timestamp}] I tried to look around but couldn't see anything."

        elif tool in ("check_presence", "CHECK_PRESENCE"):
            return f"[{timestamp}] I glanced at the desk. {result}" if result else f"[{timestamp}] I checked if anyone was around."

        elif tool in ("read_journal", "READ_JOURNAL"):
            return f"[{timestamp}] I read through my journal. {result}" if result else f"[{timestamp}] I tried to read my journal."

        elif tool in ("write_journal", "WRITE_JOURNAL"):
            entry = data.get("args", {}).get("entry", result)
            return f'[{timestamp}] I wrote in my journal: "{entry}"'

        elif tool in ("run_sandbox", "RUN_SANDBOX"):
            return f"[{timestamp}] I ran some code. {result}" if result else f"[{timestamp}] I ran some code."

        elif tool in ("read_url", "READ_URL"):
            url = data.get("args", {}).get("url", "a webpage")
            return f"[{timestamp}] I read a webpage. {result}" if result else f"[{timestamp}] I tried to read {url}."

        else:
            return f"[{timestamp}] I did something — {tool}. {result}" if result else f"[{timestamp}] I used {tool}."

    # ── Sensory ─────────────────────────────────────────────────────
    elif event_type == "sensory":
        sense = data.get("sense", "something")
        description = data.get("description", "something changed")
        if sense == "vision":
            return f"[{timestamp}] I see: {description}"
        elif sense == "audio":
            return f"[{timestamp}] I hear: {description}"
        return f"[{timestamp}] I noticed: {description}"

    elif event_type == "sensory_scan":
        description = data.get("description", "")
        if not description or description.strip() in ("", "Nothing notable in my environment right now.", "No sensory data available."):
            return ""
        return f"[{timestamp}] (sensing) {description}"

    elif event_type == "remote_sensory":
        sender = data.get("sender", "someone")
        media_type = data.get("media_type", "something")
        caption = data.get("caption", "")
        description = data.get("description", "")
        if not description:
            return ""
        caption_note = f' They said: "{caption}"' if caption else ""
        return f"[{timestamp}] {sender} showed me a {media_type}.{caption_note} I see: {description}"

    # ── Somatic signals (raw data — beliefs determine interpretation) ──
    elif event_type == "somatic_signal":
        subsystem = data.get("subsystem", "unknown")
        metric = data.get("metric", 0)
        health = data.get("health", 100)
        return f"[{timestamp}] (somatic) {subsystem}: {metric}% — health: {health}%"

    # ── Stability Sentinel ──────────────────────────────────────────
    elif event_type == "stability_drift":
        s_total = data.get("s_total", 0)
        triplet = data.get("health_triplet", {})
        physical = triplet.get("physical", 1.0)
        systemic = triplet.get("systemic", 1.0)
        cognitive = triplet.get("cognitive", 1.0)
        return (
            f"[{timestamp}] (somatic) stability drift — "
            f"S={s_total:.2f} physical={physical:.2f} systemic={systemic:.2f} cognitive={cognitive:.2f}"
        )

    elif event_type == "stability_warning":
        s_total = data.get("s_total", 0)
        triplet = data.get("health_triplet", {})
        return (
            f"[{timestamp}] (somatic — urgent) stability warning — "
            f"S={s_total:.2f} physical={triplet.get('physical', 1.0):.2f} "
            f"systemic={triplet.get('systemic', 1.0):.2f} cognitive={triplet.get('cognitive', 1.0):.2f}"
        )

    elif event_type == "stability_critical":
        s_total = data.get("s_total", 0)
        triplet = data.get("health_triplet", {})
        vibe_collapse = data.get("vibe_collapse", False)
        prefix = "VIBE COLLAPSE — " if vibe_collapse else ""
        return (
            f"[{timestamp}] (somatic — ALARM) {prefix}stability critical — "
            f"S={s_total:.2f} physical={triplet.get('physical', 1.0):.2f} "
            f"systemic={triplet.get('systemic', 1.0):.2f} cognitive={triplet.get('cognitive', 1.0):.2f}"
        )

    elif event_type == "context_awareness":
        usage = data.get("context_usage_pct", 0)
        clarity = data.get("context_clarity_pct", 100)
        return f"[{timestamp}] (somatic) context load: {usage:.0f}% — clarity: {clarity:.0f}%"

    elif event_type == "action_cycling":
        count = data.get("consecutive_actions", 0)
        return f"[{timestamp}] (somatic) rapid action cycling detected — {count} consecutive actions without reflection"

    # ── Lifecycle ───────────────────────────────────────────────────
    elif event_type == "morning_pulse":
        content = data.get("content", "A new day begins.")
        return f"[{timestamp}] (waking naturally) {content}"

    elif event_type == "wake":
        return f"[{timestamp}] I'm awake. A new day. My thoughts begin..."

    elif event_type == "idle":
        return f"[{timestamp}] Nothing new is happening."

    elif event_type == "drowsy":
        pct = data.get("usage_pct", "?")
        return f"[{timestamp}] (somatic) context window at {pct}%"

    elif event_type == "sleep":
        return f"[{timestamp}] Drifting off to rest... letting my thoughts consolidate."

    elif event_type == "nap_taken":
        content = data.get("content", "")
        return f"[{timestamp}] (waking from rest) {content}" if content else f"[{timestamp}] (waking refreshed)"

    # ── Memory & thought ────────────────────────────────────────────
    elif event_type == "memory_recall":
        content = data.get("content", "something from the past")
        return f'[{timestamp}] A memory surfaced: "{content}"'

    elif event_type == "conscious_thought":
        content = data.get("content", "")
        content = re.sub(r"<think>\s*</think>\s*", "", content).strip()
        if not content or content.lower() in ("no action required.", "no action required"):
            return ""
        return f"[{timestamp}] (my mind settles on) {content}"

    elif event_type == "subconscious_result":
        intent = data.get("intent", "something")
        result = data.get("result", "")
        if result:
            return f'[{timestamp}] Something I was thinking about came back to me — I followed through on "{intent}". {result}'
        return f'[{timestamp}] I tried to follow through on "{intent}" but came up empty.'

    # ── Deep Thought ────────────────────────────────────────────────
    elif event_type == "deep_thought_started":
        content = data.get("content", "I've started thinking deeply about something.")
        return f"[{timestamp}] (a part of my mind turns inward) {content}"

    elif event_type == "deep_thought_resolved":
        content = data.get("content", "A deep thought has resolved.")
        return f"[{timestamp}] (an understanding crystallizes) {content}"

    elif event_type == "deep_thought_failed":
        content = data.get("content", "A train of thought slipped away.")
        return f"[{timestamp}] (a thought dissolves) {content}"

    # ── Thalamic Gate ───────────────────────────────────────────────
    elif event_type == "thalamic_gate":
        description = data.get("description", "")
        failures = data.get("consecutive_failures", 1)
        if failures >= 3:
            return (
                f"[{timestamp}] (a fog descends) {description} "
                f"Repeated classification failures ({failures})."
            )
        return f"[{timestamp}] (a moment of confusion) {description}"

    elif event_type == "thalamic_gate_cleared":
        return f"[{timestamp}] (clarity returns) Classification recovered."

    # ── Scheduler ───────────────────────────────────────────────────
    elif event_type == "reminder_fired":
        content = data.get("content", "Something I wanted to remember...")
        return f"[{timestamp}] (a reminder surfaces) {content}"

    elif event_type == "scheduled_task":
        desc = data.get("description", data.get("content", "something I planned"))
        return f"[{timestamp}] (a scheduled task fires) {desc}"

    # ── Voice ───────────────────────────────────────────────────────
    elif event_type == "self_voice":
        heard = data.get("heard", "My voice faded into quiet.")
        return f"[{timestamp}] (hearing myself) {heard}"

    # ── Fallback ────────────────────────────────────────────────────
    else:
        detail = data.get("detail", data.get("content", data.get("trigger", "")))
        if detail:
            return f"[{timestamp}] {event_type}: {detail}"
        return f"[{timestamp}] {event_type}"
