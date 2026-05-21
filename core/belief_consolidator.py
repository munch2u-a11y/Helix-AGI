"""
Helix — Belief Consolidator (Nightly Merge Pass)

Simple, direct belief merging:
  1. Word-match each new belief against lexicon terms + same-category existing beliefs
  2. Send matches to Gemini Flash for MERGE/PASS decision (one call per belief, parallel)
  3. Apply merges programmatically (LLM handles content, code handles metadata)
  4. If a merge overflows the belief char cap, divert to lexicon.json automatically

The lexicon is the star map — an index of named gravitational bodies.
When a belief concept becomes too dense to fit in a normal belief, the overflow
is automatically routed to the Lexicon as a high-density anchor entry.

Called by the Curator as Phase 2.5 of the nightly cycle.
"""

import json
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("helix.core.belief_consolidator")

# ── Configuration ────────────────────────────────────────────────────

_MODEL = "gemini-3.1-flash-lite-preview"
_MAX_MATCH_CANDIDATES = 6   # Top N existing beliefs to send for comparison
_MAX_WORKERS = 4             # Parallel Gemini calls
_LEXICON_MAX_LENGTH = 500    # Lexicon entries can hold more text than beliefs
_LEXICON_MASS_THRESHOLD = 5.0  # Beliefs above this mass trigger Lexicon candidacy
_LEXICON_TERM_FREQ_THRESHOLD = 5  # Terms in 5+ beliefs trigger Lexicon candidacy

# Words too common to be useful for matching
_STOPWORDS = frozenset({
    "i", "me", "my", "am", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "shall", "should", "may", "might", "must", "can", "could",
    "a", "an", "the", "and", "but", "or", "nor", "not", "no",
    "if", "then", "than", "that", "this", "these", "those", "which",
    "who", "whom", "what", "when", "where", "how", "why",
    "in", "on", "at", "to", "for", "of", "with", "by", "from",
    "as", "into", "through", "during", "before", "after", "above",
    "below", "between", "about", "against", "over", "under",
    "it", "its", "they", "them", "their", "he", "him", "his",
    "she", "her", "we", "us", "our", "you", "your",
    "so", "up", "out", "just", "also", "very", "too", "more",
    "most", "some", "any", "all", "each", "every", "both",
    "own", "same", "other", "such", "only", "even", "still",
    "here", "there", "now", "already", "always", "never",
    "because", "since", "while", "although", "though",
    "rather", "whether", "however", "therefore", "thus",
    "between", "within", "without", "during", "upon",
})

# Max lengths by category (matches batch_service.py)
_MAX_LENGTHS = {
    "self_identity": 250,
    "people": 250,
    "knowledge": 250,
    "capabilities": 250,
    "skills": 250,
    "preferences": 250,
    "feedback": 300,
}

# ── System Prompt ────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "You are a belief consolidation system. You will receive a NEW belief "
    "and up to 6 EXISTING beliefs from the same category.\n\n"

    "Your job: decide if the NEW belief should MERGE with one of the "
    "existing beliefs, or PASS as a standalone addition.\n\n"

    "MERGE means the new and existing belief are clearly about the same "
    "thing or entity and one is a rewording, extension, or subset of the "
    "other. Output a single merged belief that preserves ALL information "
    "from both.\n\n"

    "PASS means the new belief is genuinely novel — related topic but "
    "distinct insight.\n\n"

    "Rules for merged output:\n"
    "- Same category format:\n"
    "    self_identity: 'I am...' or 'My...'\n"
    "    capabilities: 'I can...'\n"
    "    people: '[Name]...'\n"
    "    knowledge: declarative statement or 'If X, then Y'\n"
    "    skills: 'To [goal]: [steps]' or 'When [condition], [action]'\n"
    "    preferences: 'I want/prefer/value...'\n"
    "    feedback: '[Lesson]. [Why]. [How to apply]'\n"
    "- Combine naturally: 'X is A' + 'X can B' → 'X is A that can B'\n"
    "- Do NOT invent new information — only merge what exists\n"
    "- Max 250 chars (300 for feedback category)\n"
    "- Plain text only, no markdown, no bullets, no numbering\n\n"

    "Output format (strict, exactly 3 lines):\n"
    "DECISION: MERGE or PASS\n"
    "MERGE_WITH: [id of existing belief to merge with, or NONE]\n"
    "CONTENT: [merged belief text if MERGE, or original new belief text if PASS]\n"
)


# ── Lexicon Loader ───────────────────────────────────────────────────

def _load_lexicon_terms(lexicon_path: Path) -> Dict[str, str]:
    """Load lexicon terms + aliases as a matching index.

    Returns dict mapping each matchable term (lowercased) to
    the lexicon entry's primary term (for logging/identification).

    Example: {"jean-luc": "Jean-Luc", "picard": "Jean-Luc", "locutus": "Captain"}
    """
    terms = {}
    try:
        with open(lexicon_path, "r", encoding="utf-8") as f:
            entries = json.load(f)
        for entry in entries:
            primary = entry.get("term", "")
            if primary:
                terms[primary.lower()] = primary
            for alias in entry.get("aliases", []):
                if alias:
                    terms[alias.lower()] = primary
    except Exception as e:
        logger.warning("Failed to load lexicon: %s", e)
    return terms


# ── Lexicon Diversion ────────────────────────────────────────────────

def _extract_dominant_term(text: str) -> Optional[str]:
    """Extract the most significant proper noun from belief text.

    Returns the most frequently occurring proper noun, or the first
    one found if all appear equally. Returns None if no proper nouns.
    """
    words = _tokenize(text)
    proper_nouns = [w for w in words if _is_proper_noun(w)]
    if not proper_nouns:
        return None

    # Count occurrences, return the most frequent
    from collections import Counter
    counts = Counter(w.lower() for w in proper_nouns)
    winner_lower, _ = counts.most_common(1)[0]
    # Return original casing from first occurrence
    for w in proper_nouns:
        if w.lower() == winner_lower:
            return w
    return proper_nouns[0]


def _divert_to_lexicon(
    term: str,
    summary: str,
    lexicon_path: Path,
    category: str = "concept",
) -> bool:
    """Create or update a Lexicon entry. Pure system routing, no LLM.

    If an entry for this term already exists, its summary is replaced
    with the richer merged content. If not, a new entry is created.

    Returns True on success.
    """
    try:
        with open(lexicon_path, "r", encoding="utf-8") as f:
            entries = json.load(f)
    except Exception:
        entries = []

    # Determine the lexicon category based on the belief category
    if category == "people":
        lex_category = "person"
    else:
        lex_category = "concept"

    # Check if this term already has an entry
    existing = None
    for entry in entries:
        if entry.get("term", "").lower() == term.lower():
            existing = entry
            break
        for alias in entry.get("aliases", []):
            if alias.lower() == term.lower():
                existing = entry
                break
        if existing:
            break

    # Truncate to Lexicon cap
    summary = summary[:_LEXICON_MAX_LENGTH]

    if existing:
        # Update — only if the new summary is richer (longer)
        if len(summary) > len(existing.get("summary", "")):
            existing["summary"] = summary
            logger.info("⭐ LEXICON UPDATED [%s]: %s", term, summary[:80])
        else:
            logger.debug("Lexicon entry for '%s' already richer, skipping", term)
            return True
    else:
        # Create new entry
        lex_id = f"lex_{term.lower().replace(' ', '_')}"
        new_entry = {
            "id": lex_id,
            "term": term,
            "aliases": [],
            "category": lex_category,
            "summary": summary,
        }
        entries.append(new_entry)
        logger.info("⭐ LEXICON CREATED [%s]: %s", term, summary[:80])

    try:
        with open(lexicon_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error("Failed to write lexicon: %s", e)
        return False


# ── Tokenizer ────────────────────────────────────────────────────────

def _tokenize(text: str) -> List[str]:
    """Extract significant words from belief text.

    Returns lowercased words with stopwords removed.
    Preserves proper nouns by also returning the original-case version
    in the output (caller checks capitalization).
    """
    # Split on word boundaries, keep alphanumeric + underscores
    raw_words = re.findall(r"[A-Za-z0-9_]+", text)
    significant = []
    for w in raw_words:
        if w.lower() not in _STOPWORDS and len(w) > 1:
            significant.append(w)
    return significant


def _is_proper_noun(word: str) -> bool:
    """Check if a word looks like a proper noun (capitalized, not sentence-start)."""
    return len(word) > 1 and word[0].isupper() and not word.isupper()


# ── Word-Match Scoring ───────────────────────────────────────────────

def _find_matches(
    new_belief: Dict[str, Any],
    lexicon_terms: Dict[str, str],
    existing_beliefs: List[Dict[str, Any]],
) -> List[Tuple[float, Dict[str, Any]]]:
    """Find existing beliefs that overlap with the new belief.

    Uses word matching, not embeddings. The lexicon terms act as an
    index to locate the right neighborhood.

    Returns a list of (score, belief_dict) sorted by score descending,
    capped at _MAX_MATCH_CANDIDATES.
    """
    new_content = new_belief.get("content", "")
    new_words = _tokenize(new_content)
    new_words_lower = {w.lower() for w in new_words}

    if not new_words_lower:
        return []

    # Identify which lexicon entities this new belief mentions
    mentioned_entities = set()
    for w_lower in new_words_lower:
        if w_lower in lexicon_terms:
            mentioned_entities.add(w_lower)

    # Identify proper nouns in the new belief (single-match threshold)
    proper_nouns = {w.lower() for w in new_words if _is_proper_noun(w)}

    # Score each existing belief
    scored = []
    for existing in existing_beliefs:
        ex_content = existing.get("content", "")
        ex_words = _tokenize(ex_content)
        ex_words_lower = {w.lower() for w in ex_words}

        if not ex_words_lower:
            continue

        shared = new_words_lower & ex_words_lower
        if not shared:
            continue

        # Check match thresholds
        shared_proper = shared & (proper_nouns | mentioned_entities)
        shared_general = shared - shared_proper

        # Proper nouns / lexicon terms: 1 match is enough
        # General words: need 2+ shared significant words
        if not shared_proper and len(shared_general) < 2:
            continue

        # Score: weight proper noun matches higher
        score = len(shared_proper) * 3.0 + len(shared_general) * 1.0

        scored.append((score, existing))

    # Sort by score descending, take top N
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:_MAX_MATCH_CANDIDATES]


# ── Gemini API ───────────────────────────────────────────────────────

def _call_gemini(prompt: str, system: str = "") -> Optional[str]:
    """Single Gemini API call. Mirrors batch_service._call_gemini."""
    try:
        from google import genai

        key = os.environ.get("GEMINI_API_KEY", "")
        if not key:
            logger.warning("No GEMINI_API_KEY — cannot consolidate beliefs")
            return None

        client = genai.Client(api_key=key)
        response = client.models.generate_content(
            model=_MODEL,
            contents=prompt,
            config={
                "system_instruction": system,
                "temperature": 0.15,
                "max_output_tokens": 512,
            },
        )

        if response and response.text:
            return response.text.strip()

    except Exception as e:
        logger.warning("Gemini consolidation call failed: %s", e)

    return None


# ── LLM Prompt Builder ──────────────────────────────────────────────

def _build_review_prompt(
    new_belief: Dict[str, Any],
    candidates: List[Tuple[float, Dict[str, Any]]],
) -> str:
    """Build the per-belief review prompt."""
    category = new_belief.get("category", "knowledge")
    content = new_belief.get("content", "")

    lines = [
        f'NEW BELIEF: "{content}"',
        f"CATEGORY: {category}",
        "",
        "EXISTING BELIEFS:",
    ]

    for i, (score, existing) in enumerate(candidates, 1):
        ex_id = existing.get("id", "unknown")
        ex_content = existing.get("content", "")
        lines.append(f'{i}. [{ex_id}] "{ex_content}"')

    return "\n".join(lines)


# ── Response Parser ──────────────────────────────────────────────────

def _parse_decision(raw: str) -> Dict[str, str]:
    """Parse the LLM's DECISION/MERGE_WITH/CONTENT response.

    Returns dict with keys: decision, merge_with, content.
    Returns empty dict on parse failure.
    """
    result = {"decision": "", "merge_with": "", "content": ""}

    for line in raw.split("\n"):
        line = line.strip()
        upper = line.upper()

        if upper.startswith("DECISION:"):
            val = line.split(":", 1)[1].strip().upper()
            if val in ("MERGE", "PASS"):
                result["decision"] = val

        elif upper.startswith("MERGE_WITH:"):
            val = line.split(":", 1)[1].strip()
            if val.upper() != "NONE":
                result["merge_with"] = val

        elif upper.startswith("CONTENT:"):
            val = line.split(":", 1)[1].strip()
            # Strip any quotes the LLM might have added
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            result["content"] = val

    # Validate
    if not result["decision"]:
        return {}
    if result["decision"] == "MERGE" and not result["merge_with"]:
        return {}
    if not result["content"]:
        return {}

    return result


# ── Merge Application ────────────────────────────────────────────────

def _apply_merge(
    decision: Dict[str, str],
    new_belief: Dict[str, Any],
    belief_store,
    lexicon_path: Path = None,
) -> bool:
    """Update the existing belief in place with merged content + metadata.

    The new belief is never added — the existing one absorbs it.
    Code handles all metadata; only content comes from the LLM.

    If the merged content exceeds the category's char cap, the overflow
    is automatically diverted to lexicon.json. The winning belief keeps
    its pre-merge content but still absorbs mass, relations, and refs.
    """
    merge_with_id = decision["merge_with"]
    merged_content = decision["content"]

    existing = belief_store.get_belief(merge_with_id)
    if not existing:
        logger.warning("Merge target %s not found — skipping", merge_with_id)
        return False

    category = existing.get("category", new_belief.get("category", "knowledge"))

    # Compute merged metadata: take the better of the two values
    new_mass = new_belief.get("mass", 1.0)
    new_conf = new_belief.get("confidence", 0.5)
    new_verifications = new_belief.get("verifications", 1.0)
    new_access = new_belief.get("access_count", 0)

    merged_mass = max(existing.get("mass", 1.0), new_mass)
    merged_conf = max(existing.get("confidence", 0.5), new_conf)
    merged_verifications = (
        existing.get("verifications", 1.0) + new_verifications
    )
    merged_access = existing.get("access_count", 0) + new_access

    # Union relations and memory_refs, minus duplicates
    existing_relations = set(existing.get("relations", []))
    new_relations = set(new_belief.get("relations", []))
    merged_relations = list(existing_relations | new_relations)
    # Remove self-reference
    merged_relations = [r for r in merged_relations if r != merge_with_id]

    existing_refs = set(existing.get("memory_refs", []))
    new_refs = set(new_belief.get("memory_refs", []))
    merged_refs = list(existing_refs | new_refs)

    # Keep encoding_lagrangian from whichever has higher confidence
    if new_conf > existing.get("confidence", 0.5):
        encoding_lag = new_belief.get("encoding_lagrangian")
    else:
        encoding_lag = existing.get("encoding_lagrangian")

    # ── Lexicon Overflow Check ───────────────────────────────────
    # If the merged content exceeds the belief char cap, divert the
    # full merged text to the Lexicon. The belief keeps its original
    # content but still absorbs mass, relations, and memory refs.
    max_len = _MAX_LENGTHS.get(category, 250)
    content_to_store = merged_content

    if len(merged_content) > max_len and lexicon_path:
        dominant_term = _extract_dominant_term(merged_content)
        if dominant_term:
            _divert_to_lexicon(
                term=dominant_term,
                summary=merged_content,
                lexicon_path=lexicon_path,
                category=category,
            )
            # Belief keeps its pre-merge content (already fits)
            content_to_store = existing.get("content", merged_content[:max_len])
            logger.info(
                "↗ Overflow diverted to lexicon [%s], belief keeps original content",
                dominant_term,
            )
        else:
            # No proper noun found — truncate as fallback
            content_to_store = merged_content[:max_len]
            logger.warning(
                "Merged content overflows (%d chars) but no dominant term found — truncating",
                len(merged_content),
            )

    # Apply the update — existing belief absorbs everything
    updates = {
        "content": content_to_store,
        "mass": merged_mass,
        "confidence": merged_conf,
        "verifications": merged_verifications,
        "access_count": merged_access,
        "relations": merged_relations,
        "memory_refs": merged_refs,
    }
    if encoding_lag:
        updates["encoding_lagrangian"] = encoding_lag

    result = belief_store.update_belief(merge_with_id, **updates)
    if result:
        logger.info(
            "✨ MERGED → [%s]: %s",
            merge_with_id, content_to_store[:80],
        )
        return True

    logger.warning("Failed to update belief %s", merge_with_id)
    return False


# ── Single Belief Processing ─────────────────────────────────────────

def _process_one_belief(
    new_belief: Dict[str, Any],
    lexicon_terms: Dict[str, str],
    belief_store,
    lexicon_path: Path = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Process a single new belief: match, review, merge-or-pass.

    Returns a result dict: {action, belief, merge_with, content}
    """
    category = new_belief.get("category", "knowledge")
    content = new_belief.get("content", "")

    # Load existing beliefs from the same category
    existing_beliefs = belief_store._read_category(category)

    # Find word-match candidates
    candidates = _find_matches(new_belief, lexicon_terms, existing_beliefs)

    if not candidates:
        # No matches — PASS directly
        return {
            "action": "PASS",
            "belief": new_belief,
            "merge_with": None,
            "content": content,
        }

    # Build review prompt and call Gemini
    prompt = _build_review_prompt(new_belief, candidates)
    raw_response = _call_gemini(prompt, system=_SYSTEM_PROMPT)

    if not raw_response:
        # API failure — safe default is PASS
        logger.warning("API call failed for belief: %s — defaulting to PASS", content[:60])
        return {
            "action": "PASS",
            "belief": new_belief,
            "merge_with": None,
            "content": content,
        }

    # Parse the decision
    decision = _parse_decision(raw_response)
    if not decision:
        logger.warning(
            "Failed to parse consolidation response for: %s — defaulting to PASS",
            content[:60],
        )
        return {
            "action": "PASS",
            "belief": new_belief,
            "merge_with": None,
            "content": content,
        }

    if decision["decision"] == "MERGE":
        if dry_run:
            logger.info(
                "[DRY RUN] Would merge: '%s' → [%s] as '%s'",
                content[:60], decision["merge_with"], decision["content"][:60],
            )
        else:
            _apply_merge(decision, new_belief, belief_store, lexicon_path=lexicon_path)

        return {
            "action": "MERGE",
            "belief": new_belief,
            "merge_with": decision["merge_with"],
            "content": decision["content"],
        }

    # PASS
    return {
        "action": "PASS",
        "belief": new_belief,
        "merge_with": None,
        "content": decision.get("content", content),
    }


# ── Main Entry Point ─────────────────────────────────────────────────

def consolidate_new_beliefs(
    new_beliefs: List[Dict[str, Any]],
    belief_store,
    lexicon_path: Path = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Consolidate a list of new beliefs against the existing store.

    For each new belief:
      - Word-match against lexicon terms and same-category beliefs
      - If matches found: ask Gemini to MERGE or PASS
      - If no matches: PASS directly

    Args:
        new_beliefs: List of belief dicts with at least {content, category}
        belief_store: BeliefStore instance
        lexicon_path: Path to lexicon.json (default: data/beliefs/lexicon.json)
        dry_run: If True, log proposed merges without executing

    Returns:
        Stats dict + list of beliefs that PASSed (for normal integration).
    """
    if not new_beliefs:
        logger.info("No new beliefs to consolidate")
        return {"merged": 0, "passed": 0, "errors": 0, "passed_beliefs": []}

    # Load lexicon as matching index
    if lexicon_path is None:
        lexicon_path = Path("data/beliefs/lexicon.json")
    lexicon_terms = _load_lexicon_terms(lexicon_path)
    logger.info(
        "Consolidator loaded %d lexicon terms for matching", len(lexicon_terms),
    )

    stats = {"merged": 0, "passed": 0, "errors": 0}
    passed_beliefs = []

    # Process beliefs in parallel
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        futures = {}
        for belief in new_beliefs:
            future = executor.submit(
                _process_one_belief,
                belief, lexicon_terms, belief_store, lexicon_path, dry_run,
            )
            futures[future] = belief

        for future in as_completed(futures):
            try:
                result = future.result()
                if result["action"] == "MERGE":
                    stats["merged"] += 1
                elif result["action"] == "PASS":
                    stats["passed"] += 1
                    passed_beliefs.append(result["belief"])
            except Exception as e:
                stats["errors"] += 1
                original = futures[future]
                logger.error(
                    "Consolidation failed for belief '%s': %s",
                    original.get("content", "?")[:60], e,
                )

    logger.info(
        "Consolidation complete: %d merged, %d passed, %d errors",
        stats["merged"], stats["passed"], stats["errors"],
    )

    stats["passed_beliefs"] = passed_beliefs
    return stats

# ── Relation Builder (Phase 3) ───────────────────────────────────────

def build_relations(
    new_belief: Dict[str, Any],
    injected_ids: List[str],
    belief_store: Any,
) -> List[str]:
    """Determine which injected beliefs were actually relied upon.
    
    Filter 1 (Word Match): Discard injected beliefs with no word overlap.
    Filter 2 (LLM): If 3+ matches remain, ask the LLM to disambiguate.
    """
    if not injected_ids:
        return []

    # 1. Fetch injected belief contents
    candidates = []
    for bid in set(injected_ids):
        b = belief_store.get_belief(bid)
        if b and b.get("content"):
            candidates.append(b)

    if not candidates:
        return []

    # 2. Filter 1: Word Match
    new_content = new_belief.get("content", "")
    new_words = _tokenize(new_content)
    new_words_lower = {w.lower() for w in new_words}
    proper_nouns = {w.lower() for w in new_words if _is_proper_noun(w)}

    matched_candidates = []
    for c in candidates:
        ex_content = c.get("content", "")
        ex_words = {w.lower() for w in _tokenize(ex_content)}
        
        shared = new_words_lower & ex_words
        shared_proper = shared & proper_nouns
        shared_general = shared - shared_proper
        
        if shared_proper or len(shared_general) >= 2:
            matched_candidates.append(c)

    # 3. Decision based on count
    if len(matched_candidates) == 0:
        return []
    elif len(matched_candidates) <= 2:
        # Simple, clean overlap — accept automatically
        return [c["id"] for c in matched_candidates]
    
    # 4. Filter 2: LLM Disambiguation (3+ matches)
    return _call_llm_for_relations(new_content, matched_candidates)

def _call_llm_for_relations(new_content: str, candidates: List[Dict[str, Any]]) -> List[str]:
    """Ask Gemini to disambiguate which beliefs were actually relied upon."""
    prompt = (
        "You are a cognitive relation builder.\n"
        "A new belief has just been formed:\n"
        f"\"{new_content}\"\n\n"
        "The following existing beliefs were in the system's peripheral awareness "
        "when this thought occurred:\n\n"
    )
    
    for i, c in enumerate(candidates):
        prompt += f"ID: {c['id']}\nTEXT: {c['content']}\n\n"
        
    prompt += (
        "Your job is to determine WHICH of these existing beliefs were actually "
        "relied upon, logically connected, or necessary to reach the new realization.\n"
        "Return ONLY a comma-separated list of the relevant IDs (e.g., id_1, id_3). "
        "If none are directly relevant, return NONE.\n"
    )
    
    result = _call_gemini(prompt, system="You return only comma-separated IDs.")
    if not result or result.upper() == "NONE":
        return []
        
    # Parse the returned IDs
    found_ids = []
    for chunk in result.split(","):
        chunk = chunk.strip()
        if chunk:
            # Verify the LLM didn't hallucinate an ID
            for c in candidates:
                if chunk == c["id"]:
                    found_ids.append(chunk)
                    break
                    
    return found_ids

