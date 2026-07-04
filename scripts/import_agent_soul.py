#!/usr/bin/env python3
"""
Helix — Agent Soul Importer

Convert another agent framework's identity / soul / skill / memory files into a
Helix belief graph + episodic journal. This is an *alternative to the generic
bootstrap seed* (``bootstrap.seed_builder.write_seed_data`` /
``scripts/build_bootstrap_seed.py``): instead of seeding a fresh mind with
generic starter beliefs, it seeds one with a mature agent's accumulated self.

Supported inputs (auto-detected only for provenance tagging — any Markdown /
text / JSON / YAML works):
    - Hermes           soul.md, identity.md, .hermes/, memories/, skills/
    - Claude Code      CLAUDE.md, .claude/
    - Codex            AGENTS.md
    - OpenClaude / etc. any *.md / *.txt with headed sections
    - JSON / YAML      lists of {content, ...} or key/value maps

Pipeline:
    ingest  ->  heuristic segment + classify   (always, offline, deterministic)
            ->  optional LLM refinement pass    (--mode api | local, stateless per item)
            ->  embed content to 8D             (real MiniLM->JL projection, or fallback)
            ->  assign physics                  (bounded mass, verifications, weight)
            ->  merge/write beliefs + memories  (dry-run report by default)

The LLM refinement runs ONE stateless call per item. For local providers the
underlying ``AuxiliaryLLM`` builds a fresh session every call
(``core/auxiliary_llm.py``), so the context window is reset for each pass and a
small local model cannot drift into gibberish across items.

Usage:
    # Preview what would be imported (writes a review report, mutates nothing):
    python scripts/import_agent_soul.py ~/hermes_agent/

    # Commit as the bootstrap seed for a fresh Helix (replaces empty seed files):
    python scripts/import_agent_soul.py ~/hermes_agent/ --apply --overwrite-bootstrap

    # Refine with a local model, then commit (merging into an existing store):
    python scripts/import_agent_soul.py ~/hermes/soul.md --mode local --apply
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import logging
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger("helix.import_agent_soul")

# Make the repo root importable when run as a script.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# Category model
# ─────────────────────────────────────────────────────────────────────────────

# Mirrors memory/belief_store.py:BELIEF_CATEGORIES. Kept local so the importer
# runs even in a minimal environment.
CATEGORIES = (
    "premises",      # foundational self / identity axioms
    "propositions",  # learned facts, rules, knowledge
    "preferences",   # values, style, behavioral norms
    "people",        # entity profiles
    "skills",        # proven procedures / tool workflows
    "desires",       # long-term goals / aspirations
    "concepts",      # consolidated conceptual understanding
)

ID_PREFIX = {
    "premises": "pre",
    "propositions": "pro",
    "preferences": "pref",
    "people": "peo",
    "skills": "skl",
    "desires": "des",
    "concepts": "con",
}

# Mass band per category. Kept strictly below the core bootstrap identity mass
# (~1.95) so imported knowledge is findable without creating runaway gravity
# attractors that crowd out task-relevant beliefs (see focus-drift Loop A).
MASS_BAND: Dict[str, Tuple[float, float]] = {
    "premises": (1.25, 1.75),
    "preferences": (1.15, 1.65),
    "desires": (1.10, 1.60),
    "people": (1.15, 1.60),
    "skills": (1.05, 1.55),
    "propositions": (1.00, 1.50),
    "concepts": (1.00, 1.50),
}

# Heading keyword -> category. First match wins; order matters.
HEADING_RULES: List[Tuple[Tuple[str, ...], str]] = [
    (("history", "journal", "log", "diary", "session", "conversation",
      "timeline", "changelog", "memories", "memory", "episode"), "@memory"),
    (("identity", "soul", "who i am", "about me", "self", "persona",
      "origin", "backstory", "biography"), "premises"),
    (("value", "principle", "belief", "ethos", "tone", "voice", "style",
      "personality", "temperament", "manner", "guardrail"), "preferences"),
    (("skill", "how to", "how-to", "workflow", "procedure", "playbook",
      "recipe", "capability", "command", "tool", "ability", "routine"), "skills"),
    (("goal", "mission", "objective", "aspiration", "purpose", "drive",
      "vision", "want", "ambition", "roadmap"), "desires"),
    (("concept", "glossary", "definition", "define", "term", "ontology",
      "vocabulary"), "concepts"),
    (("person", "people", "contact", "relationship", "team", "user"), "people"),
    (("fact", "knowledge", "rule", "policy", "guideline", "note", "lesson",
      "learning", "reference", "context", "instruction"), "propositions"),
]

DEFAULT_CATEGORY = "propositions"

# Filename / path fragment -> (framework, default_category_hint)
FRAMEWORK_HINTS: List[Tuple[str, str]] = [
    ("claude.md", "claude_code"),
    (".claude", "claude_code"),
    ("agents.md", "codex"),
    ("soul", "hermes"),
    ("identity", "hermes"),
    (".hermes", "hermes"),
    ("hermes", "hermes"),
    ("openclau", "openclaude"),
]

SOURCE_EXTS = {".md", ".markdown", ".txt", ".json", ".yaml", ".yml", ".mdx"}


# ─────────────────────────────────────────────────────────────────────────────
# Item model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Item:
    kind: str               # "belief" | "memory"
    category: str           # belief category (memories use "@memory")
    content: str
    confidence: float = 0.7
    importance: float = 0.7
    term: str = ""
    aliases: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    source_file: str = ""
    framework: str = "generic"
    heading: str = ""

    def content_key(self) -> str:
        norm = re.sub(r"\s+", " ", self.content.strip().lower())
        return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────────────────────
# Ingest
# ─────────────────────────────────────────────────────────────────────────────

def detect_framework(path: Path) -> str:
    low = str(path).lower()
    for fragment, framework in FRAMEWORK_HINTS:
        if fragment in low:
            return framework
    return "generic"


def iter_source_files(paths: Iterable[Path]) -> List[Path]:
    files: List[Path] = []
    seen: set = set()
    for p in paths:
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix.lower() in SOURCE_EXTS:
                    if f.resolve() not in seen:
                        seen.add(f.resolve())
                        files.append(f)
        elif p.is_file():
            if p.resolve() not in seen:
                seen.add(p.resolve())
                files.append(p)
        else:
            logger.warning("Path not found, skipping: %s", p)
    return files


@dataclass
class Section:
    heading: str
    body: str


def _split_markdown_sections(text: str) -> List[Section]:
    """Split Markdown into (heading, body) sections by ATX headings."""
    sections: List[Section] = []
    current_heading = ""
    buf: List[str] = []

    def flush():
        body = "\n".join(buf).strip()
        if body or current_heading:
            sections.append(Section(current_heading, body))

    for line in text.splitlines():
        m = re.match(r"^\s{0,3}(#{1,6})\s+(.*)$", line)
        if m:
            flush()
            current_heading = m.group(2).strip().strip("#").strip()
            buf = []
        else:
            buf.append(line)
    flush()
    return [s for s in sections if s.body or s.heading]


def _atomic_statements(body: str) -> List[str]:
    """Break a section body into atomic statements (bullets / sentences)."""
    statements: List[str] = []
    # Collapse fenced code blocks into single opaque units so we don't shred them.
    body = re.sub(r"```.*?```", lambda m: m.group(0).replace("\n", " "), body,
                  flags=re.DOTALL)

    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        # Strip list / quote markers.
        line = re.sub(r"^([-*+]|\d+[.)]|>)\s+", "", line).strip()
        line = re.sub(r"^\*\*(.+?)\*\*:?\s*", r"\1: ", line)  # bold "key:" labels
        if not line or line in {"---", "***"}:
            continue
        if len(line) <= 3:
            continue
        # Long prose paragraphs -> sentence split; keep short lines whole.
        if len(line) > 220 and "." in line:
            for sent in re.split(r"(?<=[.!?])\s+", line):
                sent = sent.strip()
                if len(sent) > 3:
                    statements.append(sent)
        else:
            statements.append(line)
    return statements


def classify_heading(heading: str, framework: str) -> str:
    """Return a category ('@memory' for episodic) from a section heading."""
    h = heading.lower()
    for keywords, category in HEADING_RULES:
        if any(k in h for k in keywords):
            return category
    # Framework fallbacks: a Hermes soul/identity file with no headings is self.
    if framework == "hermes" and not heading:
        return "premises"
    return DEFAULT_CATEGORY


def parse_structured(path: Path, framework: str) -> List[Item]:
    """Parse JSON / YAML sources into items."""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.warning("Could not read %s: %s", path, e)
        return []

    data = None
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(raw)
        except Exception as e:
            logger.warning("Bad JSON in %s (%s) — treating as text", path, e)
            return parse_markdown(path, framework, raw_override=raw)
    else:  # yaml
        try:
            import yaml  # optional dependency
            data = yaml.safe_load(raw)
        except Exception:
            return parse_markdown(path, framework, raw_override=raw)

    items: List[Item] = []

    def add(content: str, category: str, heading: str = "", conf: float = 0.72):
        content = str(content).strip()
        if len(content) > 3:
            kind = "memory" if category == "@memory" else "belief"
            items.append(Item(
                kind=kind, category=category, content=content,
                confidence=conf, importance=conf,
                source_file=str(path), framework=framework, heading=heading,
            ))

    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict):
                content = entry.get("content") or entry.get("text") or entry.get("belief")
                cat = entry.get("category")
                if content:
                    category = cat if cat in CATEGORIES else classify_heading(str(cat or ""), framework)
                    add(content, category, str(cat or ""), float(entry.get("confidence", 0.72)))
            elif isinstance(entry, str):
                add(entry, DEFAULT_CATEGORY)
    elif isinstance(data, dict):
        for key, value in data.items():
            category = classify_heading(str(key), framework)
            if isinstance(value, (list, tuple)):
                for v in value:
                    add(str(v), category, str(key))
            elif isinstance(value, (str, int, float, bool)):
                add(f"{key}: {value}" if not str(key).isdigit() else str(value),
                    category, str(key))
    return items


def parse_markdown(path: Path, framework: str, raw_override: Optional[str] = None) -> List[Item]:
    """Parse a Markdown / text source into heuristic items."""
    if raw_override is not None:
        text = raw_override
    else:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.warning("Could not read %s: %s", path, e)
            return []

    items: List[Item] = []
    for section in _split_markdown_sections(text):
        category = classify_heading(section.heading, framework)
        kind = "memory" if category == "@memory" else "belief"
        for statement in _atomic_statements(section.body):
            items.append(Item(
                kind=kind,
                category=category,
                content=statement,
                confidence=0.7,
                importance=0.72 if kind == "memory" else 0.7,
                source_file=str(path),
                framework=framework,
                heading=section.heading,
            ))
    return items


def parse_file(path: Path) -> List[Item]:
    framework = detect_framework(path)
    if path.suffix.lower() in {".json", ".yaml", ".yml"}:
        return parse_structured(path, framework)
    return parse_markdown(path, framework)


# ─────────────────────────────────────────────────────────────────────────────
# LLM refinement (optional, stateless per item)
# ─────────────────────────────────────────────────────────────────────────────

REFINE_SYSTEM = (
    "You convert fragments from another AI agent's identity, soul, skill, and "
    "memory files into clean, atomic, first-person belief statements for a new "
    "agent that is adopting this history. Respond with STRICT JSON only."
)

REFINE_PROMPT = """\
Rewrite the fragment below as one atomic, self-contained, first-person statement
and classify it. Categories:
- premises: foundational identity / self / nature
- propositions: a learned fact, rule, or piece of knowledge
- preferences: a value, principle, tone, or behavioral norm
- desires: a long-term goal or aspiration
- concepts: a definition or conceptual understanding
- skills: a proven procedure, workflow, or tool usage
- people: a fact about a specific person/entity
- memory: a past event/experience (episodic), NOT a durable belief

Return STRICT JSON, no prose, no code fence:
{{"category": "<one of the above>", "content": "<first-person statement>",
  "term": "<key term or empty>", "confidence": <0.0-1.0>}}

Heading context: {heading}
Fragment: {fragment}
"""


def build_llm_client(mode: str):
    """Construct an AuxiliaryLLM for 'api' or 'local' refinement, or None."""
    try:
        from core.auxiliary_llm import AuxiliaryLLM
        from llm.providers.base import ProviderConfig
    except Exception as e:
        logger.warning("Auxiliary LLM unavailable (%s) — refinement disabled", e)
        return None

    if mode == "api":
        # provider_config=None => Gemini Flash Lite path (needs GEMINI_API_KEY).
        return AuxiliaryLLM(None)

    if mode == "local":
        cfg = _load_runtime_config()
        provider = cfg.get("local_provider", "ollama")
        model = cfg.get("local_model", "granite4.1:3b")
        ctx = int(cfg.get("local_context_window", 8192))
        try:
            pc = ProviderConfig(
                provider_type=provider,
                model=model,
                context_window=ctx,
            )
        except Exception as e:
            logger.warning("Could not build local ProviderConfig: %s", e)
            return None
        return AuxiliaryLLM(pc)

    return None


def _load_runtime_config() -> dict:
    cfg_path = REPO_ROOT / "config" / "config.json"
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return None


def refine_item(item: Item, client) -> Item:
    """Refine a single item with one stateless LLM call. Falls back on failure."""
    prompt = REFINE_PROMPT.format(heading=item.heading or "(none)", fragment=item.content)
    try:
        # One call == one fresh session for local providers (context reset).
        out = client.generate(prompt, system_instruction=REFINE_SYSTEM,
                              temperature=0.1, max_output_tokens=400)
    except Exception as e:
        logger.debug("Refine call failed for one item: %s", e)
        return item

    parsed = _extract_json(out or "")
    if not parsed:
        return item  # never let gibberish poison the store

    content = str(parsed.get("content", "")).strip()
    if len(content) < 4:
        return item

    raw_cat = str(parsed.get("category", "")).strip().lower()
    if raw_cat in ("memory", "@memory"):
        item.kind, item.category = "memory", "@memory"
    elif raw_cat in CATEGORIES:
        item.kind, item.category = "belief", raw_cat
    # else keep heuristic category

    item.content = content
    term = str(parsed.get("term", "")).strip()
    if term:
        item.term = term
    try:
        item.confidence = max(0.3, min(0.95, float(parsed.get("confidence", item.confidence))))
    except (TypeError, ValueError):
        pass
    item.tags = list(dict.fromkeys(item.tags + ["llm_refined"]))
    return item


# ─────────────────────────────────────────────────────────────────────────────
# Embedding -> 8D position
# ─────────────────────────────────────────────────────────────────────────────

class Positioner:
    """Compute real 8D belief positions, with a deterministic fallback.

    Uses the same MiniLM embedder + JL projection the running system uses so
    imported beliefs land near their semantic neighbours and are retrievable by
    the gravity query. Falls back to a stable pseudo-position if the embedder or
    projection matrix is unavailable.
    """

    def __init__(self, data_dir: Path):
        self._embedder = None
        self._projection = None
        self._np = None
        self._compute_position = None
        self._ok = False
        try:
            import numpy as np
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
            from core.cognitive_space import CognitiveProjection
            from core.belief_cosmology import compute_position
            self._np = np
            self._embedder = DefaultEmbeddingFunction()
            self._projection = CognitiveProjection.load(
                data_dir / "cognitive_projection.npy", in_dim=384, out_dim=8,
            )
            self._compute_position = compute_position
            self._ok = True
            logger.info("Positioner: real MiniLM->8D projection active")
        except Exception as e:
            logger.warning("Positioner: falling back to pseudo positions (%s)", e)

    def position(self, text: str, order: int) -> List[float]:
        if self._ok:
            try:
                emb = self._embedder([text])[0]
                emb = self._np.asarray(emb, dtype=self._np.float32)
                pos = self._compute_position(emb, self._projection)
                return [round(float(x), 6) for x in pos]
            except Exception as e:
                logger.debug("Embed failed, pseudo-position: %s", e)
        return _pseudo_position(text, order)


def _pseudo_position(text: str, order: int) -> List[float]:
    """Deterministic stand-in position (mirrors build_bootstrap_seed.make_position)."""
    import math
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16) % 100000 + order
    return [round(math.sin(seed * 0.73 + a * 0.41) * 0.12
                  + math.cos(seed * 0.29 + a * 0.67) * 0.05, 6) for a in range(8)]


# ─────────────────────────────────────────────────────────────────────────────
# Physics assignment -> belief / memory records
# ─────────────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _slug(text: str) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return "_".join(words[:5])[:48] or "item"


def make_belief_record(item: Item, position: List[float], now: str,
                       identity_weight: float) -> dict:
    lo, hi = MASS_BAND.get(item.category, (1.0, 1.5))
    mass = round(lo + (hi - lo) * item.confidence, 4)
    # Identity/self beliefs may be nudged up (they replace the bootstrap self).
    if item.category in ("premises", "preferences"):
        mass = round(min(hi, mass * identity_weight), 4)

    conf = round(max(0.05, min(0.98, item.confidence)), 3)
    tags = list(dict.fromkeys(
        item.tags + ["imported_soul", f"import:{item.framework}"]
    ))

    prefix = ID_PREFIX.get(item.category, "pro")
    belief_id = f"{prefix}_imp_{_slug(item.content)}_{item.content_key()[:6]}"

    record = {
        "id": belief_id,
        "content": item.content,
        "mass": mass,
        "confidence": conf,
        "source": f"agent_import:{item.framework}",
        "created_at": now,
        "last_accessed": now,
        "access_count": 0,
        "position_8d": position,
        "verifications": round(1.0 + 2.0 * item.confidence, 4),
        "stability_index": round(0.6 + 0.25 * item.confidence, 3),
        "relations": [],
        "memory_refs": [],
        "encoding_lagrangian": {"omega": 0.55, "s_total": 0.15, "H": 0.16, "D_KL": 0.01},
        "last_verified": now,
        "formation_type": "agent_import",
        "formation_source": f"agent_import:{item.framework}",
        "category": item.category,
        "somatic_imprint": 0.0,
        "tags": tags,
        "weight": "core" if conf >= 0.85 else "deep",
    }
    if item.term:
        record["term"] = item.term
        record["aliases"] = list(item.aliases)
    return record


def make_memory_record(item: Item, position: List[float], now: str) -> dict:
    mem_id = f"mem_imp_{item.content_key()}"
    tags = list(dict.fromkeys(
        item.tags + ["imported_soul", f"import:{item.framework}"]
    ))
    return {
        "id": mem_id,
        "type": "memory",
        "content": item.content,
        "position_8d": position,
        "pulse_id": 0,
        "lagrangian": {},
        "metadata": {
            "memory_type": "imported_history",
            "source": f"agent_import:{item.framework}",
            "importance": round(max(0.1, min(0.95, item.importance)), 3),
            "tags": tags,
            "belief_ids": [],
            "created_at": now,
        },
        "timestamp": now,
    }


def belief_to_journal_entry(record: dict, now: str) -> dict:
    """Mirror a belief into a type='belief' journal entry (see build_bootstrap_seed)."""
    return {
        "id": record["id"],
        "type": "belief",
        "content": record["content"],
        "position_8d": copy.deepcopy(record["position_8d"]),
        "pulse_id": 0,
        "lagrangian": copy.deepcopy(record["encoding_lagrangian"]),
        "metadata": {
            "category": record["category"],
            "mass": record["mass"],
            "confidence": record["confidence"],
            "weight": record["weight"],
            "source": record["source"],
            "verifications": record["verifications"],
            "stability_index": record["stability_index"],
            "relations": [],
            "memory_refs": [],
            "created_at": record["created_at"],
            "last_accessed": record["last_accessed"],
            "access_count": 0,
            "tags": copy.deepcopy(record["tags"]),
            "formation_type": record["formation_type"],
            "term": record.get("term", ""),
            "aliases": copy.deepcopy(record.get("aliases", [])),
            "volatile_mass": 0.0,
        },
        "timestamp": now,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Writers
# ─────────────────────────────────────────────────────────────────────────────

def _checksum(entry: dict) -> str:
    payload = json.dumps(entry, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _read_json_list(path: Path) -> List[dict]:
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if raw in ("", "[]", "{}"):
            return []
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def backup_data_dir(data_dir: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = data_dir.parent / f"data_backup_{ts}_import"
    shutil.copytree(data_dir, dest, dirs_exist_ok=True)
    return dest


def write_beliefs(data_dir: Path, by_category: Dict[str, List[dict]],
                  overwrite_bootstrap: bool) -> Dict[str, int]:
    beliefs_dir = data_dir / "beliefs"
    beliefs_dir.mkdir(parents=True, exist_ok=True)
    counts: Dict[str, int] = {}

    for category, new_records in by_category.items():
        path = beliefs_dir / f"{category}.json"
        existing = [] if overwrite_bootstrap else _read_json_list(path)
        seen_ids = {b.get("id") for b in existing}
        seen_content = {
            hashlib.sha256(re.sub(r"\s+", " ", str(b.get("content", "")).strip().lower())
                           .encode()).hexdigest()[:16]
            for b in existing
        }
        added = 0
        for rec in new_records:
            ckey = hashlib.sha256(re.sub(r"\s+", " ", rec["content"].strip().lower())
                                  .encode()).hexdigest()[:16]
            if rec["id"] in seen_ids or ckey in seen_content:
                continue
            existing.append(rec)
            seen_ids.add(rec["id"])
            seen_content.add(ckey)
            added += 1
        path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
        counts[category] = added
    return counts


def _existing_journal_ids(journal: Path) -> set:
    """Collect ids already present so re-imports stay idempotent (append-only log)."""
    ids: set = set()
    if not journal.exists():
        return ids
    try:
        with open(journal, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ids.add(json.loads(line).get("id"))
                except Exception:
                    continue
    except Exception:
        pass
    return ids


def append_journal(data_dir: Path, entries: List[dict]) -> int:
    if not entries:
        return 0

    total_written = 0
    for journal in (data_dir / "memory" / "cognitive_journal.jsonl",
                    data_dir / "cognitive_journal.jsonl"):
        journal.parent.mkdir(parents=True, exist_ok=True)
        present = _existing_journal_ids(journal)
        lines = []
        for entry in entries:
            if entry.get("id") in present:
                continue
            present.add(entry.get("id"))
            payload = copy.deepcopy(entry)
            payload["checksum"] = _checksum(entry)
            lines.append(json.dumps(payload, separators=(",", ":")))
        if lines:
            with open(journal, "a", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
        total_written = max(total_written, len(lines))
    return total_written


def write_report(report_path: Path, items: List[Item], by_category: Dict[str, List[dict]],
                 memories: List[dict], args) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Agent Soul Import — Review Report",
        "",
        f"- Generated: {_now_iso()}",
        f"- Mode: `{args.mode}`  |  Apply: `{args.apply}`  |  "
        f"Overwrite bootstrap: `{args.overwrite_bootstrap}`",
        f"- Sources: {', '.join(args.paths)}",
        f"- Total items: {len(items)}  "
        f"(beliefs: {sum(len(v) for v in by_category.values())}, memories: {len(memories)})",
        "",
        "## Beliefs by category",
        "",
    ]
    for category in CATEGORIES:
        recs = by_category.get(category, [])
        if not recs:
            continue
        lines.append(f"### {category} ({len(recs)})")
        lines.append("")
        for r in recs:
            lines.append(f"- **[{r['mass']:.2f}m / {r['confidence']:.2f}c]** {r['content']}")
        lines.append("")
    if memories:
        lines.append(f"## Episodic memories ({len(memories)})")
        lines.append("")
        for m in memories:
            lines.append(f"- {m['content']}")
        lines.append("")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────────────

def run_import(
    paths: List[Path],
    data_dir: Path,
    *,
    mode: str = "heuristic",
    apply: bool = False,
    overwrite_bootstrap: bool = False,
    max_beliefs: int = 400,
    max_memories: int = 400,
    identity_weight: float = 1.1,
    backup: bool = True,
    report_path: Optional[Path] = None,
    args=None,
) -> dict:
    # 1. Ingest + heuristic segment/classify.
    files = iter_source_files(paths)
    if not files:
        raise SystemExit("No readable source files found.")
    logger.info("Ingesting %d file(s)", len(files))
    items: List[Item] = []
    for f in files:
        items.extend(parse_file(f))
    logger.info("Heuristic pass produced %d candidate items", len(items))

    # 2. Optional LLM refinement (one stateless call per item).
    if mode in ("api", "local"):
        client = build_llm_client(mode)
        if client is None:
            logger.warning("Refinement requested (%s) but no client — using heuristics only", mode)
        else:
            logger.info("Refining %d items via %s LLM (fresh session per item)", len(items), mode)
            for i, it in enumerate(items):
                items[i] = refine_item(it, client)
                if (i + 1) % 25 == 0:
                    logger.info("  refined %d/%d", i + 1, len(items))

    # 3. Dedup + split beliefs/memories, honoring caps.
    positioner = Positioner(data_dir)
    now = _now_iso()
    by_category: Dict[str, List[dict]] = {c: [] for c in CATEGORIES}
    belief_journal: List[dict] = []
    memory_entries: List[dict] = []
    seen_keys: set = set()
    n_belief = n_mem = 0

    for order, it in enumerate(items):
        if not it.content or len(it.content.strip()) < 4:
            continue
        key = (it.kind, it.content_key())
        if key in seen_keys:
            continue
        seen_keys.add(key)

        if it.kind == "memory":
            if n_mem >= max_memories:
                continue
            pos = positioner.position(it.content, order)
            memory_entries.append(make_memory_record(it, pos, now))
            n_mem += 1
        else:
            if n_belief >= max_beliefs:
                continue
            category = it.category if it.category in CATEGORIES else DEFAULT_CATEGORY
            it.category = category
            pos = positioner.position(it.content, order)
            rec = make_belief_record(it, pos, now, identity_weight)
            by_category[category].append(rec)
            belief_journal.append(belief_to_journal_entry(rec, now))
            n_belief += 1

    by_category = {c: v for c, v in by_category.items() if v}
    summary = {
        "files": len(files),
        "belief_count": n_belief,
        "memory_count": n_mem,
        "by_category": {c: len(v) for c, v in by_category.items()},
        "applied": False,
    }

    # 4. Report (always) + write (only on --apply).
    if report_path is None:
        report_path = data_dir / "imports" / f"import_review_{datetime.now():%Y%m%d_%H%M%S}.md"
    write_report(report_path, items, by_category, memory_entries, args)
    manifest = report_path.with_suffix(".json")
    manifest.write_text(json.dumps({
        "summary": summary,
        "beliefs": by_category,
        "memories": memory_entries,
    }, indent=2) + "\n", encoding="utf-8")
    summary["report"] = str(report_path)
    summary["manifest"] = str(manifest)

    if not apply:
        logger.info("DRY RUN — nothing written. Review: %s", report_path)
        return summary

    if backup:
        dest = backup_data_dir(data_dir)
        summary["backup"] = str(dest)
        logger.info("Backed up data dir -> %s", dest)

    written = write_beliefs(data_dir, by_category, overwrite_bootstrap)
    journal_written = append_journal(data_dir, belief_journal + memory_entries)
    summary["applied"] = True
    summary["written_by_category"] = written
    summary["journal_entries_written"] = journal_written
    logger.info("Applied: %s beliefs, %d journal entries", written, journal_written)
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Import an existing agent's identity/soul/skill/memory files "
                    "into a Helix belief graph.",
    )
    p.add_argument("paths", nargs="+", help="File(s) or directory(ies) to import.")
    p.add_argument("--data-dir", default=str(REPO_ROOT / "data"),
                   help="Helix data directory (default: ./data).")
    p.add_argument("--mode", choices=("heuristic", "api", "local"), default="heuristic",
                   help="Classification engine. heuristic=offline (default); "
                        "api=Gemini batch refine; local=local LLM refine (context "
                        "reset per item).")
    p.add_argument("--apply", action="store_true",
                   help="Write to the belief store (default is a dry-run review).")
    p.add_argument("--overwrite-bootstrap", action="store_true",
                   help="Replace existing seed belief files instead of merging "
                        "(use when importing as the bootstrap seed for a fresh agent).")
    p.add_argument("--max-beliefs", type=int, default=400)
    p.add_argument("--max-memories", type=int, default=400)
    p.add_argument("--identity-weight", type=float, default=1.1,
                   help="Mass multiplier for premises/preferences (self/identity).")
    p.add_argument("--no-backup", action="store_true",
                   help="Skip the automatic data-dir backup on --apply.")
    p.add_argument("--report", default=None, help="Path for the review report (.md).")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    summary = run_import(
        [Path(p).expanduser() for p in args.paths],
        Path(args.data_dir).expanduser(),
        mode=args.mode,
        apply=args.apply,
        overwrite_bootstrap=args.overwrite_bootstrap,
        max_beliefs=args.max_beliefs,
        max_memories=args.max_memories,
        identity_weight=args.identity_weight,
        backup=not args.no_backup,
        report_path=Path(args.report).expanduser() if args.report else None,
        args=args,
    )

    print("\n── Agent Soul Import ─────────────────────────────")
    print(f"  Files scanned    : {summary['files']}")
    print(f"  Beliefs          : {summary['belief_count']}  {summary['by_category']}")
    print(f"  Memories         : {summary['memory_count']}")
    print(f"  Review report    : {summary['report']}")
    if summary["applied"]:
        print(f"  ✓ Written        : {summary.get('written_by_category')}")
        print(f"  ✓ Journal entries: {summary.get('journal_entries_written')}")
        if summary.get("backup"):
            print(f"  Backup           : {summary['backup']}")
    else:
        print("  (dry run — nothing written; re-run with --apply to commit)")
    print("──────────────────────────────────────────────────")


if __name__ == "__main__":
    main()
