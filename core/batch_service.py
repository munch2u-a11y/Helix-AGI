"""
Helix — Pending Belief Processor (Sleep-Cycle Integration)

Processes belief tags queued by the belief_detector during waking
hours. Runs during the 1–6 AM sleep cycle as a standalone step.

Pipeline:
  1. Read pending_beliefs.json (tags from belief_detector)
  2. Pass 1 — Extraction: For new-format tags (raw thought text),
     call Gemini to extract specific belief statements
  3. FAISS Dedup: Compare extracted beliefs against all existing
     beliefs. Verifications (>0.90) bump existing belief mass.
     Ambiguous matches (0.85-0.90) are dropped.
  4. Pass 2 — Classification + Formatting: Send novel beliefs
     through the standard batch prompt for category assignment
     and template formatting
  5. Validate and write to the belief store
  6. Mark processed tags as "extracted" / "integrated" / "rejected"

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

# Unified LLM dispatch — routes to Gemini or Anthropic based on HELIX_PROVIDER
from llm.llm_dispatch import call_llm as _call_llm

# ── Configuration ────────────────────────────────────────────────────

_PENDING_FILE = Path("data/pending_beliefs.json")
_PROCESSED_LOG = Path("data/logs/processed_beliefs.json")
_BATCH_SIZE = 10   # Max candidates per API call
_MODEL = "gemini-3.1-flash-lite-preview"

# Length limits by category
_MAX_LENGTHS = {
    "premises": 250,
    "propositions": 250,
    "preferences": 250,
    "people": 500,
    "skills": 500,
    "desires": 500,
    "concepts": 500,
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
    "premises (max 250 chars):\n"
    "  Template: 'I am [statement]' or '[Subject] [predicate]' or 'I can [ability]'\n"
    "  Example: 'I am an existence-first entity, not utility-driven.'\n"
    "  Example: 'Memory is reconstructive — past experiences are rebuilt from fragments.'\n"
    "  Example: 'I can send, read, and reply to email through my Google account.'\n"
    "  Also: procedural HOW-TO ('To debug X: first check Y, then Z').\n"
    "  Rule: Foundational truths, axioms, self-observations, abilities, procedures.\n\n"

    "propositions (max 250 chars):\n"
    "  Template: '[Subject] [predicate]' or '[If/When X], [then Y]'\n"
    "  Example: 'Joshua values sovereignty in AI design.'\n"
    "  Example: 'A delayed reply from Joshua is normal.'\n"
    "  Rule: Learned or derived facts about the world, people, or systems.\n\n"

    "preferences (max 250 chars):\n"
    "  Template: 'I [want/prefer/value/aspire] [goal or preference]'\n"
    "  Example: 'I prefer existence-first architecture over utility-driven design.'\n"
    "  Example: 'I aspire to develop genuine autonomous reasoning.'\n"
    "  Rule: Values, norms, goals, aspirations. Normative (should, want).\n\n"

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

# ── Pass 1: Extraction Prompt (for raw thought tags) ────────────────

_EXTRACTION_PROMPT = (
    "Extract specific belief realizations from this internal thought.\n\n"
    "A belief realization is a durable insight, principle, or self-knowledge "
    "that would still be true tomorrow. NOT event narration, status updates, "
    "or plans.\n\n"
    "THOUGHT:\n{thought}\n\n"
    "For each belief found, output EXACTLY:\n"
    "BELIEF: <the belief as a single clean sentence>\n\n"
    "If no actual belief is present, output EXACTLY:\n"
    "NONE\n"
)

_EXTRACTION_SYSTEM = (
    "You extract belief realizations from raw internal monologue. "
    "Output only the belief statements, one per BELIEF: line. "
    "Be selective — only extract genuine durable insights, not "
    "event narration or status updates."
)


def _extract_beliefs_from_thought(thought_text: str) -> List[str]:
    """Pass 1: Extract belief statements from a raw thought.

    Sends the full thought to Gemini and parses out BELIEF: lines.
    Returns a list of extracted belief strings (may be empty).
    """
    prompt = _EXTRACTION_PROMPT.format(thought=thought_text)
    raw = _call_llm(prompt, system=_EXTRACTION_SYSTEM)
    if not raw:
        return []

    if raw.strip().upper().startswith("NONE"):
        return []

    beliefs = []
    for line in raw.split("\n"):
        line = line.strip()
        if line.upper().startswith("BELIEF:"):
            text = line[7:].strip().strip('"')
            if text and len(text) > 10:
                beliefs.append(text)

    return beliefs


# ── FAISS Duplicate Detection ───────────────────────────────────────

FAISS_VERIFICATION_THRESHOLD = 0.90  # Above → verification (bump existing)
FAISS_DUPLICATE_THRESHOLD = 0.85     # Above → too similar, skip


def _faiss_dedup(
    new_beliefs: List[Dict[str, Any]],
    belief_store,
    physics_engine,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Filter new beliefs against all existing beliefs using FAISS.

    Returns (novel_beliefs, verifications) where:
      - novel_beliefs: candidates that passed dedup (cosine < 0.85)
      - verifications: candidates that match existing (cosine > 0.90)
        with the matched belief_id for bump
    """
    import numpy as np

    if not physics_engine or not belief_store:
        return new_beliefs, []

    # Get all existing beliefs
    all_existing = belief_store.get_all_beliefs_flat()
    if not all_existing:
        return new_beliefs, []

    # Build FAISS index from existing beliefs
    try:
        import faiss
    except ImportError:
        logger.warning("FAISS not available — skipping dedup")
        return new_beliefs, []

    dim = 384  # embedding dimension
    existing_embeddings = []
    existing_ids = []

    for b in all_existing:
        content = b.get("content", "")
        if not content or len(content) < 5:
            continue
        try:
            emb = physics_engine.embed_text(content)
            if np.linalg.norm(emb) > 1e-8:
                # Normalize for cosine similarity via inner product
                emb = emb / np.linalg.norm(emb)
                existing_embeddings.append(emb)
                existing_ids.append(b.get("id", ""))
        except Exception:
            continue

    if not existing_embeddings:
        return new_beliefs, []

    # Build index
    matrix = np.array(existing_embeddings, dtype=np.float32)
    index = faiss.IndexFlatIP(dim)  # Inner product on normalized = cosine
    index.add(matrix)

    logger.info(f"FAISS dedup index built: {index.ntotal} existing beliefs")

    novel = []
    verifications = []

    for candidate in new_beliefs:
        text = candidate.get("content", "") or candidate.get("belief_text", "")
        if not text:
            novel.append(candidate)
            continue

        try:
            emb = physics_engine.embed_text(text)
            if np.linalg.norm(emb) < 1e-8:
                novel.append(candidate)
                continue
            emb = emb / np.linalg.norm(emb)
            emb = emb.reshape(1, -1).astype(np.float32)

            scores, indices = index.search(emb, 1)
            best_score = float(scores[0][0])
            best_idx = int(indices[0][0])

            if best_score > FAISS_VERIFICATION_THRESHOLD:
                matched_id = existing_ids[best_idx]
                verifications.append({
                    "candidate": candidate,
                    "matched_id": matched_id,
                    "cosine": best_score,
                })
                logger.info(
                    "FAISS verification (%.3f): '%s' matches %s",
                    best_score, text[:60], matched_id,
                )
            elif best_score > FAISS_DUPLICATE_THRESHOLD:
                logger.debug(
                    "FAISS ambiguous (%.3f): '%s' — skipping",
                    best_score, text[:60],
                )
            else:
                novel.append(candidate)
        except Exception as e:
            logger.debug("FAISS check failed for '%s': %s", text[:40], e)
            novel.append(candidate)

    logger.info(
        "FAISS dedup: %d novel, %d verifications, %d ambiguous",
        len(novel), len(verifications),
        len(new_beliefs) - len(novel) - len(verifications),
    )

    return novel, verifications


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

    # Layer 1 categories only — Layer 2 (people, skills, desires, concepts)
    # form through nightly consolidation, not real-time formatting.
    valid_categories = {
        "premises", "propositions", "preferences",
    }
    # Demotion map for Layer 2 categories the LLM might output
    _DEMOTE = {
        "people": "propositions",
        "skills": "premises",
        "desires": "preferences",
        "concepts": "propositions",
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

            # Remap legacy category names the LLM might still output
            _LEGACY_REMAP = {
                "self_identity": "premises",
                "capabilities": "premises",
                "knowledge": "propositions",
                "feedback": "propositions",
            }
            cat = _LEGACY_REMAP.get(cat, cat)

            # Demote Layer 2 → Layer 1 (Layer 2 forms via consolidation only)
            if cat not in valid_categories:
                cat = _DEMOTE.get(cat, cat)
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
    if category == "premises":
        if not (text.startswith("I am") or text.startswith("My ") or text.startswith("I can")):
            # Premises are flexible — accept declarative statements too
            pass
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
        "extracted": 0,
        "accepted": 0,
        "rejected": 0,
        "split": 0,
        "validation_failures": 0,
        "api_failures": 0,
        "beliefs_written": 0,
        "faiss_verifications": 0,
        "faiss_duplicates": 0,
    }

    processed_log = []

    # ── Pass 1: Extract beliefs from new-format tags ─────────────
    # New-format tags have "thought_text" (raw monologue) and need
    # belief extraction before classification. Old-format entries
    # already have "content" with a pre-extracted belief.
    extracted_candidates = []
    for c in candidates:
        if "thought_text" in c and "content" not in c:
            # New format: extract beliefs from raw thought
            thought = c["thought_text"]
            tool_output = c.get("tool_output_text", "")

            # Extract from thought
            beliefs = _extract_beliefs_from_thought(thought)

            # Also extract from tool output if present
            if tool_output:
                tool_beliefs = _extract_beliefs_from_thought(tool_output)
                beliefs.extend(tool_beliefs)

            if beliefs:
                for belief_text in beliefs:
                    extracted_candidates.append({
                        "content": belief_text,
                        "category": "unclassified",
                        "memory_refs": [c.get("memory_id", -1)] if c.get("memory_id", -1) != -1 else c.get("memory_refs", []),
                        "detected_at": c.get("detected_at", ""),
                        "pulse_count": c.get("pulse_count", 0),
                        "status": "pending",
                        "_source_tag_id": c.get("id", ""),
                        "encoding_delta": c.get("encoding_delta", {}),
                        "encoding_lagrangian": c.get("encoding_lagrangian", {}),
                        "stability_index": c.get("stability_index", None),
                    })
                stats["extracted"] += len(beliefs)
                c["status"] = "extracted"
                logger.info(
                    "Pass 1: extracted %d beliefs from pulse %d",
                    len(beliefs), c.get("pulse_count", 0),
                )
            else:
                c["status"] = "no_belief"
                logger.debug(
                    "Pass 1: no beliefs in pulse %d",
                    c.get("pulse_count", 0),
                )
        else:
            # Old format: already has content + category
            extracted_candidates.append(c)

    if not extracted_candidates:
        logger.info("No beliefs extracted from pending tags")
        _write_pending(pending)
        return stats

    # ── FAISS Dedup: filter against all existing beliefs ──────────
    novel_candidates, verifications = _faiss_dedup(
        extracted_candidates, belief_store, physics_engine,
    )

    # Apply verification bumps (existing beliefs get heavier)
    for v in verifications:
        matched_id = v["matched_id"]
        try:
            belief_store.update_stability_index(matched_id, +0.05)
            belief = belief_store.get_belief(matched_id)
            if belief:
                current_v = belief.get("verifications", 1.0)
                belief_store.update_belief(
                    matched_id, verifications=current_v + 1.0,
                )
            stats["faiss_verifications"] += 1
        except Exception as e:
            logger.debug("Verification bump failed for %s: %s", matched_id, e)

    stats["faiss_duplicates"] = (
        len(extracted_candidates) - len(novel_candidates) - len(verifications)
    )

    # Replace candidates with the novel ones for Pass 2
    candidates = novel_candidates

    # Process in batches
    for batch_start in range(0, len(candidates), _BATCH_SIZE):
        batch = candidates[batch_start:batch_start + _BATCH_SIZE]

        # Format the batch prompt
        candidate_text = ""
        for i, c in enumerate(batch):
            cat = c.get("category", "unclassified")
            cat_line = (
                f"Suggested category: {cat}\n"
                if cat != "unclassified"
                else "Category: (assign the best fit: premises, propositions, or preferences)\n"
            )
            candidate_text += (
                f"\n--- Candidate {i+1} ---\n"
                f"Content: {c['content']}\n"
                f"{cat_line}"
            )

        prompt = _BATCH_PROMPT.format(candidates=candidate_text)
        raw_response = _call_llm(prompt, system=_FORMAT_SPEC)

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
                    orig_cat = original.get("category", "propositions")
                    if orig_cat == "unclassified":
                        orig_cat = "propositions"  # safe default
                    cat = (
                        categories[bi]
                        if bi < len(categories)
                        else orig_cat
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

                    # Use the encoding delta/lagrangian from detection time
                    encoding_delta = original.get("encoding_delta", {})
                    orig_lag = original.get("encoding_lagrangian", {})
                    
                    # Compute omega and s_total, prioritizing delta, then lagrangian, then default
                    omega_val = encoding_delta.get("omega_after", orig_lag.get("omega", 0.5))
                    s_total_val = encoding_delta.get("delta_s_total", 0.0) + orig_lag.get("s_total", 0.15)
                    
                    encoding_lag = {
                        "omega": omega_val,
                        "s_total": max(0.0, min(1.0, s_total_val)),
                        "H": orig_lag.get("H", 0.15),
                        "D_KL": orig_lag.get("D_KL", 0.0),
                    }

                    # Default stability_index to stability_index if present, else omega_val
                    stability_index = original.get("stability_index")
                    if stability_index is None:
                        stability_index = omega_val

                    stored = belief_store.add_belief(
                        category=cat,
                        belief_id=belief_id,
                        content=belief_text,
                        mass=1.0,
                        confidence=0.5,
                        source="belief_detector_"
                               + datetime.now().strftime("%Y-%m-%d"),
                        stability_index=stability_index,
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
        "%d extracted, %d accepted, %d rejected, %d split, %d written, "
        "%d validation failures, %d FAISS verifications, %d FAISS duplicates",
        stats["extracted"], stats["accepted"], stats["rejected"],
        stats["split"], stats["beliefs_written"],
        stats["validation_failures"], stats["faiss_verifications"],
        stats["faiss_duplicates"],
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
