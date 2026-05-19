"""
Helix — Pending Belief Processor (Sleep-Cycle Integration)

Processes belief candidates queued by the belief_detector during waking
hours. Runs during the 1–6 AM sleep cycle as a standalone step.

Pipeline:
  1. Read pending_beliefs.json
  2. For each candidate, call Gemini Flash Lite to:
     a. Validate it's a genuine, durable belief (not an event transcript)
     b. Format it according to the category's template
     c. Condense if over limit (implied foundations principle)
     d. Assign final category
  3. Batch multiple candidates into a single API call when possible
  4. Write validated beliefs to the belief store
  5. Mark processed candidates as "integrated" or "rejected"

Uses Gemini API (not Ollama) for higher quality formatting decisions.
Designed to be called from the dream cycle or a standalone cron.

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
_MODEL = "gemini-3.1-flash-lite-preview"

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
    "  Example: 'Joshua values sovereignty in AI design.'\n"
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
    "  Template: 'To [goal]: [steps]' or 'When [condition], [action]'\n"
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


# ── Gemini API Client ───────────────────────────────────────────────

def _call_gemini(prompt: str, system: str = "") -> Optional[str]:
    """Make a single Gemini API call for belief processing.

    Uses the google.genai SDK, same pattern as gemini_provider.py.
    Returns the text response, or None on failure.
    """
    try:
        from google import genai

        key = os.environ.get("GEMINI_API_KEY", "")
        if not key:
            logger.warning("No GEMINI_API_KEY — cannot process pending beliefs")
            return None

        client = genai.Client(api_key=key)

        response = client.models.generate_content(
            model=_MODEL,
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
        logger.warning("Gemini API call failed: %s", e)

    return None


# ── Response Parser ─────────────────────────────────────────────────

def _parse_batch_response(
    raw: str, count: int,
) -> List[Dict[str, Any]]:
    """Parse Gemini's batch response into structured results.

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
        if upper.startswith("BELIEF "):
            rest = line[7:]
            if ":" not in rest:
                continue
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
        elif upper.startswith("CATEGORY "):
            rest = line[9:]
            if ":" not in rest:
                continue
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
        elif upper.startswith("STATUS "):
            rest = line[7:]
            if ":" not in rest:
                continue
            idx_part, status = rest.split(":", 1)
            status = status.strip().upper()

            if status not in ("ACCEPT", "REJECT", "SPLIT"):
                continue

            try:
                idx = int(idx_part.strip()) - 1
            except ValueError:
                continue

            if idx in seen_indices:
                results[seen_indices[idx]]["status"] = status

        # ── Parse REASON lines ────────────────────────────────────
        elif upper.startswith("REASON "):
            rest = line[7:]
            if ":" not in rest:
                continue
            idx_part, reason = rest.split(":", 1)

            try:
                idx = int(idx_part.strip()) - 1
            except ValueError:
                continue

            if idx in seen_indices:
                results[seen_indices[idx]]["reason"] = reason.strip()

    return results


# ── Format Validation ───────────────────────────────────────────────

def _validate_belief(text: str, category: str) -> Tuple[bool, str]:
    """Validate a formatted belief against category rules.

    Returns (is_valid, reason).
    """
    if not text or len(text) < 15:
        return False, "too short"

    max_len = _MAX_LENGTHS.get(category, 250)
    if len(text) > max_len:
        return False, f"too long ({len(text)} > {max_len})"

    # Check for formatting artifacts
    if "**" in text:
        return False, "contains markdown bold"
    if text[0].isdigit() and "." in text[:4]:
        return False, "starts with numbered list"
    if text.startswith(("→", "*", "•", "-")):
        return False, "starts with bullet/arrow"
    if text.startswith(("Stated directly", "From the memory", "Beliefs:")):
        return False, "contains meta-reference"

    # Category-specific prefix checks
    if category == "self_identity":
        if not (text.startswith("I am") or text.startswith("My ")):
            return False, "self_identity must start with 'I am' or 'My'"
    elif category == "capabilities":
        if not text.startswith("I can"):
            return False, "capabilities must start with 'I can'"
    elif category == "preferences":
        if not any(text.startswith(p) for p in
                    ["I want", "I prefer", "I value", "I strive"]):
            return False, "preferences must start with 'I want/prefer/value/strive'"

    return True, "ok"


# ── Main Processing Pipeline ────────────────────────────────────────

def process_pending_beliefs(
    belief_store,
    physics_engine=None,
    sentinel=None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Process all pending belief candidates.

    Reads pending_beliefs.json, sends batches to Gemini for formatting,
    validates results, and writes to the belief store.

    Args:
        belief_store: BeliefStore instance
        physics_engine: For computing mass (optional)
        sentinel: For reading current somatic state (optional)
        dry_run: If True, validate and format but don't write to store

    Returns summary dict with stats.
    """
    pending = _read_pending()
    if not pending:
        logger.info("No pending beliefs to process")
        return {"status": "empty", "processed": 0}

    # Filter to only unprocessed candidates
    candidates = [p for p in pending if p.get("status") == "pending"]
    if not candidates:
        logger.info("No unprocessed candidates in pending queue")
        return {"status": "empty", "processed": 0}

    logger.info(f"Processing {len(candidates)} pending belief candidates")

    stats = {
        "started_at": datetime.now().isoformat(),
        "total_candidates": len(candidates),
        "accepted": 0,
        "rejected": 0,
        "split": 0,
        "validation_failures": 0,
        "api_failures": 0,
        "beliefs_written": 0,
    }

    processed_log = []

    # Process in batches
    for batch_start in range(0, len(candidates), _BATCH_SIZE):
        batch = candidates[batch_start:batch_start + _BATCH_SIZE]

        # Format the batch prompt
        candidate_text = ""
        for i, c in enumerate(batch):
            candidate_text += (
                f"\n--- Candidate {i+1} ---\n"
                f"Content: {c['content']}\n"
                f"Suggested category: {c['category']}\n"
            )

        prompt = _BATCH_PROMPT.format(candidates=candidate_text)
        raw_response = _call_gemini(prompt, system=_FORMAT_SPEC)

        if not raw_response:
            stats["api_failures"] += len(batch)
            logger.warning(
                "API call failed for batch starting at %d", batch_start,
            )
            continue

        # Parse the batch response
        results = _parse_batch_response(raw_response, len(batch))

        # Process each result
        for result in results:
            idx = result["index"]
            if idx >= len(batch):
                continue

            original = batch[idx]
            status = result["status"]

            if status == "REJECT":
                original["status"] = "rejected"
                original["rejection_reason"] = result.get("reason", "")
                stats["rejected"] += 1
                logger.debug(
                    "Rejected: %s (reason: %s)",
                    original["content"][:60], result.get("reason", "?"),
                )

            elif status in ("ACCEPT", "SPLIT"):
                beliefs_to_write = result.get("beliefs", [])
                categories = result.get("_categories", [])

                if status == "SPLIT":
                    stats["split"] += 1

                for bi, belief_text in enumerate(beliefs_to_write):
                    cat = (
                        categories[bi]
                        if bi < len(categories)
                        else original["category"]
                    )

                    # Validate against format spec
                    is_valid, reason = _validate_belief(belief_text, cat)
                    if not is_valid:
                        logger.debug(
                            "Validation failed: %s (%s)",
                            belief_text[:60], reason,
                        )
                        stats["validation_failures"] += 1
                        continue

                    if dry_run:
                        logger.info(
                            "[DRY RUN] Would write [%s]: %s", cat, belief_text,
                        )
                        stats["accepted"] += 1
                        continue

                    # Write to belief store
                    belief_id = belief_store.generate_id(cat)

                    # Use the encoding delta from detection time
                    encoding_delta = original.get("encoding_delta", {})
                    encoding_lag = {
                        "omega": encoding_delta.get("omega_after", 0.5),
                        "s_total": 0.15,
                        "H": 0.15,
                        "D_KL": 0.0,
                    }

                    stored = belief_store.add_belief(
                        category=cat,
                        belief_id=belief_id,
                        content=belief_text,
                        mass=1.0,
                        confidence=0.5,
                        source="belief_detector_"
                               + datetime.now().strftime("%Y-%m-%d"),
                        stability_index=encoding_delta.get(
                            "omega_after", 0.5,
                        ),
                        encoding_lagrangian=encoding_lag,
                        memory_refs=original.get("memory_refs", []),
                    )

                    if stored:
                        # Recompute mass from cognitive mass equation
                        belief = belief_store.get_belief(belief_id)
                        if belief and physics_engine:
                            try:
                                real_mass = (
                                    belief_store.compute_cognitive_mass(belief)
                                )
                                belief_store.update_belief_mass(
                                    cat, belief_id, real_mass - 1.0,
                                )
                            except Exception:
                                pass

                        stats["beliefs_written"] += 1
                        logger.info(f"✨ [{cat}] {belief_text}")

                stats["accepted"] += 1
                original["status"] = "integrated"
                original["integrated_at"] = datetime.now().isoformat()

            processed_log.append({
                "original": original["content"][:200],
                "status": status,
                "formatted": result.get("beliefs", []),
            })

        # Rate limit between batches
        if batch_start + _BATCH_SIZE < len(candidates):
            time.sleep(1.0)

    # Write back the updated pending file (with status updates)
    _write_pending(pending)

    # Append to processed log for audit
    _append_processed_log(processed_log)

    stats["completed_at"] = datetime.now().isoformat()

    logger.info(
        "Pending belief processing complete: "
        "%d accepted, %d rejected, %d split, %d written, "
        "%d validation failures",
        stats["accepted"], stats["rejected"], stats["split"],
        stats["beliefs_written"], stats["validation_failures"],
    )

    return stats


# ── File I/O ─────────────────────────────────────────────────────────

def _read_pending() -> List[Dict[str, Any]]:
    """Read pending beliefs from the staging file."""
    if not _PENDING_FILE.exists():
        return []
    try:
        data = json.loads(_PENDING_FILE.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_pending(pending: List[Dict[str, Any]]):
    """Write pending beliefs back (with updated statuses)."""
    _PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        _PENDING_FILE.write_text(json.dumps(pending, indent=2))
    except Exception as e:
        logger.warning("Failed to write pending beliefs: %s", e)


def _append_processed_log(entries: List[Dict[str, Any]]):
    """Append processing results to the log file for audit trail."""
    _PROCESSED_LOG.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if _PROCESSED_LOG.exists():
        try:
            existing = json.loads(_PROCESSED_LOG.read_text())
        except Exception:
            existing = []

    existing.extend(entries)

    # Keep only last 500 entries
    if len(existing) > 500:
        existing = existing[-500:]

    try:
        _PROCESSED_LOG.write_text(json.dumps(existing, indent=2))
    except Exception as e:
        logger.warning("Failed to write processed log: %s", e)
