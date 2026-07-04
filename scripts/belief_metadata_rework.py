#!/usr/bin/env python3
"""Belief & Memory Metadata Rework — 2026-07-02

One-time migration to optimize months of accumulated beliefs (many from
older Helix versions and weeks of silently-failing night cycles) for the
current retrieval systems. PROTECTIVE by design: nothing is deleted —
every removed entry is archived, with relations rewired to survivors.

Phases:
  1. Metadata backfill      — position_8d (unscaled JL), lagrangian
                              structure, verifications/stability defaults,
                              Layer-2 term extraction, tool_bindings.
  2. Term quality           — strip anchor terms that are stopwords or
                              generic non-proper-noun words appearing in
                              >5% of all beliefs (they anchor-match on
                              nearly every pulse and inject noise).
  3. Exact + semantic dedup — same-category merges (cosine >= 0.93),
                              winner absorbs verifications/refs/relations,
                              loser archived.
  4. Entity profiles (LLM)  — for fragmented entities (>=4 same-term
                              Layer-2 entries), synthesize ONE dense
                              consolidated profile entry (high mass, top
                              anchor facet). Source entries are KEPT —
                              they still contribute via gravity.
  5. Staleness sweep (LLM)  — present-tense/"then-present sense" beliefs
                              older than 30d never reaffirmed: LLM votes
                              KEEP / DEMOTE / ARCHIVE.
  6. Relation rewiring      — pointers to archived ids → their survivor.
  7. Spatial state prune    — archived ids removed from
                              belief_space_state.json.

Usage:
    python scripts/belief_metadata_rework.py            # dry run
    python scripts/belief_metadata_rework.py --apply
    python scripts/belief_metadata_rework.py --apply --no-llm
"""

import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BELIEF_DIR = Path("data/beliefs")
SPATIAL_STATE = Path("data/spatial/belief_space_state.json")
PROJECTION = Path("data/spatial/cognitive_projection.npy")
ARCHIVE_PATH = BELIEF_DIR / "backups" / f"archived_rework_{datetime.now():%Y%m%d_%H%M}.json"

CATS = ["premises", "propositions", "preferences", "people", "skills", "desires", "concepts"]
LAYER2 = {"people", "concepts", "skills", "desires"}

DEDUP_COSINE = 0.93
PROFILE_MIN_ENTRIES = 4
STALE_MIN_AGE_DAYS = 30

# Terms that must never be lexicon anchors regardless of frequency
HARD_STOP_TERMS = {
    "if", "the", "a", "an", "and", "or", "but", "it", "this", "that",
    "these", "those", "other", "self", "true", "false", "now", "when",
    "how", "what", "why", "where", "i", "he", "she", "they", "we", "my",
}

# Explicit tool/toolset names for binding detection (word-boundary)
TOOL_NAMES = [
    "run_command", "read_file", "write_file", "append_file", "read_url",
    "web_search", "email_send", "email_get", "email_read", "email_reply",
    "moltbook_post", "moltbook_comment", "moltbook_notifications",
    "moltbook_read_feed", "memory_recall", "send_message", "verbalize",
    "enable_toolset", "disable_toolset",
]
TOOLSET_WORDS = ["terminal", "email", "moltbook", "browser", "github", "calendar"]
TOOL_CONTEXT_RE = re.compile(
    r"\b(tool|command|flag|api|call|returns?|fails?|error|output)\b", re.I,
)

PRESENT_TENSE_RE = re.compile(
    r"\b(currently|right now|at the moment|at present|as of now|for now|"
    r"this morning|this afternoon|this evening|tonight|today|just now|"
    r"is about to|in progress|is (?:now|still) \w+ing)\b", re.I,
)


# ── Helpers ──────────────────────────────────────────────────────────

def load_all():
    data = {}
    for cat in CATS:
        p = BELIEF_DIR / f"{cat}.json"
        data[cat] = json.loads(p.read_text()) if p.exists() else []
    return data


def save_cat(cat, beliefs):
    p = BELIEF_DIR / f"{cat}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(beliefs, indent=2))
    tmp.replace(p)


def belief_age_days(b):
    try:
        created = b.get("created_at", "")
        if created:
            return (datetime.now() - datetime.fromisoformat(created.split("T")[0])).days
    except Exception:
        pass
    return 9999


def norm_text(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def get_llm():
    """Gemini client wrapper (same pattern as the Curator's)."""
    try:
        cred = Path.home() / ".config/helix/credentials.env"
        for line in cred.read_text().splitlines():
            if line.startswith("GEMINI_API_KEY="):
                os.environ.setdefault("GEMINI_API_KEY", line.split("=", 1)[1].strip().strip('"'))
        from google import genai
        from google.genai import types as gtypes
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

        def generate(prompt, system=""):
            cfg = gtypes.GenerateContentConfig(
                system_instruction=system or None,
                temperature=0.2, max_output_tokens=4096,
            )
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[gtypes.Content(role="user", parts=[gtypes.Part(text=prompt)])],
                config=cfg,
            )
            return (resp.text or "").strip()
        return generate
    except Exception as e:
        print(f"  LLM unavailable ({e}) — LLM phases will be skipped")
        return None


def main():
    apply = "--apply" in sys.argv
    use_llm = "--no-llm" not in sys.argv
    mode = "APPLY" if apply else "DRY RUN"
    print(f"=== Belief metadata rework — {mode} ===\n")

    import numpy as np
    data = load_all()
    all_flat = [(cat, b) for cat in CATS for b in data[cat]]
    total = len(all_flat)
    print(f"Loaded {total} beliefs across {len(CATS)} categories")

    report = Counter()
    archived = []          # (cat, belief, reason)
    id_redirect = {}       # archived id → surviving id ("" = none)

    # ── Embedder + projection (shared by several phases) ─────────────
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
    embedder = DefaultEmbeddingFunction()
    W = np.load(str(PROJECTION)).astype(np.float32)

    def embed_batch(texts):
        out = []
        for i in range(0, len(texts), 128):
            out.extend(embedder(texts[i:i + 128]))
        return np.array(out, dtype=np.float32)

    print("Embedding all belief contents (one pass, reused everywhere)…")
    contents = [(b.get("content") or "")[:800] for _, b in all_flat]
    emb = embed_batch(contents)
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    emb_n = emb / np.maximum(norms, 1e-8)

    # Word document-frequency for term quality checks
    doc_words = [set(re.findall(r"[a-z']+", c.lower())) for c in contents]
    word_df = Counter(w for ws in doc_words for w in ws)

    from core.belief_consolidator import _extract_dominant_term

    # ── Phase 0: archive empty-content beliefs ────────────────────────
    for cat in CATS:
        keep = []
        for b in data[cat]:
            if len((b.get("content") or "").strip()) < 5:
                archived.append((cat, b, "empty_content"))
                id_redirect[b.get("id", "")] = ""
                report["archived_empty"] += 1
            else:
                keep.append(b)
        data[cat] = keep

    # ── Phase 1: metadata backfill ────────────────────────────────────
    idx_of = {}  # belief id → row in emb_n
    for row, (cat, b) in enumerate(all_flat):
        if b.get("id"):
            idx_of[b["id"]] = row

    now_iso = datetime.now().astimezone().isoformat(timespec="seconds")
    for cat in CATS:
        for b in data[cat]:
            row = idx_of.get(b.get("id", ""))
            pos = b.get("position_8d")
            if not (isinstance(pos, list) and len(pos) == 8):
                if row is not None:
                    p8 = emb[row] @ W  # unscaled JL — current convention
                    b["position_8d"] = [round(float(x), 6) for x in p8]
                    report["position_backfilled"] += 1
            lag = b.get("encoding_lagrangian")
            if not isinstance(lag, dict):
                b["encoding_lagrangian"] = {
                    "omega": 0.5, "delta_omega": 0.0,
                    "s_total": 0.15, "H": 0.15, "D_KL": 0.0,
                }
                report["lagrangian_backfilled"] += 1
            if "verifications" not in b:
                b["verifications"] = 1.0
                report["verifications_backfilled"] += 1
            if "stability_index" not in b:
                b["stability_index"] = 0.5
                report["stability_backfilled"] += 1
            if not b.get("created_at"):
                b["created_at"] = now_iso
                report["created_at_backfilled"] += 1

            # Layer-2 term extraction for entries without one
            if cat in LAYER2 and not b.get("term"):
                t = _extract_dominant_term(b.get("content", ""))
                if t and len(t) >= 3 and t.lower() not in HARD_STOP_TERMS:
                    b["term"] = t
                    report["term_backfilled"] += 1

            # Tool bindings (high-precision heuristics)
            if not b.get("tool_bindings"):
                content = b.get("content", "")
                bindings = [t for t in TOOL_NAMES
                            if re.search(r"\b" + re.escape(t) + r"\b", content)]
                if not bindings and TOOL_CONTEXT_RE.search(content):
                    bindings = [w for w in TOOLSET_WORDS
                                if re.search(r"\b" + w + r"\b", content, re.I)]
                if bindings:
                    b["tool_bindings"] = bindings[:2]
                    report["tool_bindings_added"] += 1

    # ── Phase 2: term quality ─────────────────────────────────────────
    #    Strip anchor terms that are stopwords or generic words. A real
    #    name ('Ada') appears capitalized wherever it is used; a
    #    generic word ('cognitive') appears mostly lowercase — the term
    #    extractor only saw it capitalized at sentence starts.
    df_threshold = 0.05 * total
    all_text = " ".join(contents)

    def cap_ratio(word):
        cap = len(re.findall(r"\b" + word[0].upper() + re.escape(word[1:].lower()) + r"\b", all_text))
        low = len(re.findall(r"\b" + re.escape(word.lower()) + r"\b", all_text))
        seen = cap + low
        return (cap / seen) if seen else 1.0, seen

    for cat in LAYER2:
        for b in data[cat]:
            term = b.get("term")
            if not term:
                continue
            tl = term.lower()
            ratio, seen = cap_ratio(term) if len(term) >= 2 else (1.0, 0)
            generic = (
                tl in HARD_STOP_TERMS
                or len(tl) < 3
                or (word_df.get(tl, 0) > df_threshold and ratio < 0.7)
                or (seen >= 8 and ratio < 0.5)
            )
            if generic:
                b.pop("term", None)
                report["generic_terms_stripped"] += 1

    # ── Phase 3: dedup (exact + semantic, same category) ─────────────
    def merge_into(winner, loser):
        winner["verifications"] = float(winner.get("verifications", 1.0)) + float(loser.get("verifications", 1.0))
        winner["access_count"] = int(winner.get("access_count", 0)) + int(loser.get("access_count", 0))
        winner["mass"] = min(20.0, float(winner.get("mass", 1.0)) + 0.25 * float(loser.get("mass", 1.0)))
        for field in ("relations", "memory_refs"):
            merged = list(dict.fromkeys(
                (winner.get(field) or []) + (loser.get(field) or [])
            ))
            winner[field] = [x for x in merged if x != winner.get("id")]
        tb = list(dict.fromkeys(
            (winner.get("tool_bindings") or []) + (loser.get("tool_bindings") or [])
        ))
        if tb:
            winner["tool_bindings"] = tb

    for cat in CATS:
        beliefs = data[cat]
        if len(beliefs) < 2:
            continue
        rows = [idx_of.get(b.get("id", "")) for b in beliefs]
        drop = set()
        for i in range(len(beliefs)):
            if i in drop or rows[i] is None:
                continue
            for j in range(i + 1, len(beliefs)):
                if j in drop or rows[j] is None:
                    continue
                bi, bj = beliefs[i], beliefs[j]
                # Never merge Layer-2 entries anchored to different terms
                if cat in LAYER2 and (bi.get("term", "") or "").lower() != (bj.get("term", "") or "").lower():
                    continue
                exact = norm_text(bi.get("content")) == norm_text(bj.get("content"))
                cos = float(emb_n[rows[i]] @ emb_n[rows[j]])
                if exact or cos >= DEDUP_COSINE:
                    wi, li = (i, j) if bi.get("mass", 1.0) >= bj.get("mass", 1.0) else (j, i)
                    merge_into(beliefs[wi], beliefs[li])
                    id_redirect[beliefs[li].get("id", "")] = beliefs[wi].get("id", "")
                    archived.append((cat, beliefs[li], f"dup_of:{beliefs[wi].get('id')} cos={cos:.3f}"))
                    drop.add(li)
                    report["dedup_archived"] += 1
        data[cat] = [b for k, b in enumerate(beliefs) if k not in drop]

    # ── Phase 4 + 5: LLM phases ───────────────────────────────────────
    llm = get_llm() if use_llm else None

    # Phase 4: consolidated entity profiles
    groups = defaultdict(list)
    for cat in ("people", "concepts"):
        for b in data[cat]:
            t = (b.get("term") or "").strip()
            if t and t[0].isupper():
                groups[t.lower()].append((cat, b))
    big = {t: es for t, es in groups.items() if len(es) >= PROFILE_MIN_ENTRIES}
    print(f"\nEntity profile candidates: { {t: len(es) for t, es in big.items()} }")

    if llm:
        for term, entries in sorted(big.items(), key=lambda kv: -len(kv[1])):
            # Skip if a consolidated profile already exists
            if any(b.get("formation_type") == "profile_consolidation" for _, b in entries):
                continue
            facts = [b.get("content", "")[:200] for _, b in entries][:60]
            prompt = (
                f"These are my accumulated beliefs about '{entries[0][1].get('term')}'. "
                "Synthesize ONE dense profile (max 480 chars, plain text, "
                "first person where natural) capturing who/what this is, "
                "our relationship, and the most important durable facts. "
                "No markdown.\n\nBELIEFS:\n" + "\n".join(f"- {f}" for f in facts)
            )
            if not apply:
                report["profiles_planned"] += 1
                continue
            try:
                profile = llm(prompt, system="You consolidate belief fragments into one dense entity profile. Output only the profile text.")
                profile = profile.strip().strip('"')[:500]
                if len(profile) < 40:
                    raise ValueError("profile too short")
            except Exception as e:
                print(f"  profile LLM failed for {term}: {e}")
                report["profiles_failed"] += 1
                continue
            cat = entries[0][0]
            total_mass = min(20.0, sum(float(b.get("mass", 1.0)) for _, b in entries))
            refs = list(dict.fromkeys(r for _, b in entries for r in (b.get("memory_refs") or [])))[:60]
            comp = [b.get("id", "") for _, b in entries]
            new_id = f"profile_{term}_{datetime.now():%Y%m%d}"
            row_emb = embed_batch([profile])[0]
            pos = (row_emb @ W)
            profile_entry = {
                "id": new_id,
                "content": profile,
                "term": entries[0][1].get("term"),
                "aliases": list(dict.fromkeys(a for _, b in entries for a in (b.get("aliases") or []))),
                "mass": total_mass,
                "confidence": 0.8,
                "verifications": float(len(entries)),
                "stability_index": 0.7,
                "relations": comp[:40],
                "memory_refs": refs,
                "position_8d": [round(float(x), 6) for x in pos],
                "encoding_lagrangian": {"omega": 0.6, "delta_omega": 0.0, "s_total": 0.15, "H": 0.15, "D_KL": 0.0},
                "created_at": now_iso,
                "last_accessed": now_iso,
                "access_count": 0,
                "source": "metadata_rework_profile",
                "formation_type": "profile_consolidation",
                "component_ids": comp,
            }
            data[cat].append(profile_entry)
            report["profiles_created"] += 1
            print(f"  ⭐ profile[{term}] ({len(entries)} facets): {profile[:90]}…")

    # Phase 5: staleness sweep
    stale_candidates = []
    for cat in ("premises", "propositions", "people"):
        for b in data[cat]:
            if b.get("formation_type") == "profile_consolidation":
                continue
            content = b.get("content", "")
            old = belief_age_days(b) > STALE_MIN_AGE_DAYS
            weak = float(b.get("verifications", 1.0)) <= 1.0
            if old and (PRESENT_TENSE_RE.search(content) or (weak and float(b.get("confidence", 0.5)) < 0.45)):
                stale_candidates.append((cat, b))
    print(f"Staleness sweep candidates: {len(stale_candidates)}")

    if llm and stale_candidates:
        BATCH = 30
        for start in range(0, len(stale_candidates), BATCH):
            batch = stale_candidates[start:start + BATCH]
            listing = "\n".join(
                f"{k}. [{belief_age_days(b)}d old] {b.get('content','')[:180]}"
                for k, (_, b) in enumerate(batch)
            )
            prompt = (
                "These are old beliefs from my store. For EACH, judge whether it "
                "is still a durable, useful belief:\n"
                "- KEEP: durable fact/insight, still true\n"
                "- DEMOTE: possibly stale, or a snapshot of a past moment phrased "
                "as if current (present-tense states, transient situations)\n"
                "- ARCHIVE: clearly transient/obsolete status observation with no "
                "durable value\n\n"
                f"{listing}\n\nOutput EXACTLY one line per item: '<index>: KEEP|DEMOTE|ARCHIVE'"
            )
            if not apply:
                report["stale_planned"] += len(batch)
                continue
            try:
                out = llm(prompt, system="You audit belief durability. Output only index: VERDICT lines.")
            except Exception as e:
                print(f"  staleness LLM failed: {e}")
                continue
            verdicts = {}
            for line in out.splitlines():
                m = re.match(r"\s*(\d+)\s*[:.]\s*(KEEP|DEMOTE|ARCHIVE)", line.strip(), re.I)
                if m:
                    verdicts[int(m.group(1))] = m.group(2).upper()
            for k, (cat, b) in enumerate(batch):
                v = verdicts.get(k, "KEEP")
                if v == "DEMOTE":
                    b["confidence"] = round(max(0.15, float(b.get("confidence", 0.5)) * 0.6), 3)
                    b["stability_index"] = round(max(0.1, float(b.get("stability_index", 0.5)) - 0.15), 3)
                    tags = b.get("tags", [])
                    if "stale_present_tense" not in tags:
                        tags.append("stale_present_tense")
                    b["tags"] = tags
                    report["stale_demoted"] += 1
                elif v == "ARCHIVE":
                    id_redirect[b.get("id", "")] = ""
                    archived.append((cat, b, "stale_llm_archive"))
                    data[cat] = [x for x in data[cat] if x.get("id") != b.get("id")]
                    report["stale_archived"] += 1
            time.sleep(0.5)

    # ── Phase 6: rewire relations to survivors ────────────────────────
    for cat in CATS:
        for b in data[cat]:
            rels = b.get("relations") or []
            if not rels:
                continue
            new_rels = []
            changed = False
            for r in rels:
                if r in id_redirect:
                    tgt = id_redirect[r]
                    changed = True
                    if tgt and tgt != b.get("id") and tgt not in new_rels:
                        new_rels.append(tgt)
                elif r not in new_rels:
                    new_rels.append(r)
            if changed:
                b["relations"] = new_rels
                report["relations_rewired"] += 1

    # ── Write back ────────────────────────────────────────────────────
    if apply:
        ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
        ARCHIVE_PATH.write_text(json.dumps(
            [{"category": c, "reason": r, "belief": b} for c, b, r in archived],
            indent=2,
        ))
        for cat in CATS:
            save_cat(cat, data[cat])

        # Phase 7: prune spatial state of archived ids
        if SPATIAL_STATE.exists():
            state = json.loads(SPATIAL_STATE.read_text())
            removed = 0
            for aid in id_redirect:
                if aid and aid in state:
                    del state[aid]
                    removed += 1
            tmp = SPATIAL_STATE.with_suffix(".tmp")
            tmp.write_text(json.dumps(state))
            tmp.replace(SPATIAL_STATE)
            report["spatial_points_pruned"] = removed

    # ── Report ────────────────────────────────────────────────────────
    print(f"\n=== {mode} REPORT ===")
    for k in sorted(report):
        print(f"  {k}: {report[k]}")
    print(f"  archived total: {len(archived)}  → {ARCHIVE_PATH if apply else '(dry run)'}")
    final_total = sum(len(data[c]) for c in CATS)
    print(f"  beliefs: {total} → {final_total}")


if __name__ == "__main__":
    main()
