import logging
import re
from typing import List, Dict

try:
    import spacy
except ImportError:  # Optional enhancement; vector retrieval still works.
    spacy = None

logger = logging.getLogger("helix.memory.mrag.tagger")

_nlp = None
_nlp_attempted = False

def get_nlp():
    global _nlp, _nlp_attempted
    if _nlp_attempted:
        return _nlp
    _nlp_attempted = True
    if spacy is None:
        logger.warning("spaCy unavailable; mRAG keyword fallback active")
        return None
    try:
        _nlp = spacy.load("en_core_web_sm")
    except (OSError, IOError) as exc:
        # The 384D multi-head vector lane remains fully operational. Regex
        # keywords are preferable to dropping the entire mRAG pipeline back
        # to legacy gravity because an optional linguistic model is absent.
        logger.warning("spaCy English model unavailable; mRAG keyword fallback active: %s", exc)
        _nlp = None
    return _nlp

RELATIONAL_VERBS = {
    "love", "like", "hate", "dislike", "marry", "divorce", "date", "meet",
    "know", "own", "prefer", "work", "live", "employ", "boss", "visit", "help",
    "support", "befriend", "care", "trust"
}

RELATIONAL_NOUNS = {
    "friend", "wife", "husband", "boyfriend", "girlfriend", "partner", "spouse",
    "parent", "mother", "father", "child", "son", "daughter", "sibling", "brother",
    "sister", "roommate", "colleague", "coworker", "boss", "employer", "employee",
    "kids", "children", "family", "relative"
}

EVENT_WORDS = {
    "camp", "camping", "hike", "hiking", "travel", "trip", "vacation", "wedding",
    "party", "concert", "meeting", "sport", "game", "play", "run", "marathon",
    "race", "graduation", "fair", "festival", "show", "exhibition", "event",
    "anniversary", "birthday", "funeral", "celebration", "ceremony"
}

CONCEPT_WORDS = {
    "achievement", "accomplishment", "hobby", "interest", "occupation", "career",
    "volunteering", "health", "feeling", "mood", "conflict", "plan", "education",
    "situation", "status", "lifestyle", "belief", "goal", "dream", "success", "failure"
}

def extract_tags(text: str) -> List[str]:
    nlp = get_nlp()
    if nlp is None:
        return _fallback_tags(text)
    doc = nlp(text)

    token_tags = [None] * len(doc)

    # Step 1: Identify entities and assign tags
    for ent in doc.ents:
        tag = None
        if ent.label_ == "PERSON":
            tag = "[person]"
        elif ent.label_ in ("GPE", "LOC", "FAC"):
            tag = "[location]"
        elif ent.label_ in ("DATE", "TIME"):
            tag = "[time]"
        elif ent.label_ == "EVENT":
            tag = "[event]"

        if tag:
            for i in range(ent.start, ent.end):
                token_tags[i] = tag

    # Step 2: Traverse tokens, mapping entities and matching heuristic lemmas
    tags = []
    i = 0
    while i < len(doc):
        if token_tags[i] is not None:
            tag = token_tags[i]
            tags.append(tag)
            # Skip the rest of this entity's tokens
            while i < len(doc) and token_tags[i] == tag:
                i += 1
            continue

        token = doc[i]
        # Ignore punctuation/stopwords for heuristics
        if token.is_punct or token.is_space:
            i += 1
            continue

        lemma = token.lemma_.lower()
        pos = token.pos_

        # Heuristics
        if pos == "VERB" and lemma in RELATIONAL_VERBS:
            tags.append("[relation]")
        elif pos == "NOUN" and lemma in RELATIONAL_NOUNS:
            # Check if this relational noun is followed by a PERSON entity,
            # if so, we can skip it to avoid redundant [relation] tags
            # (e.g. "friends, Joel and Terry" -> Joel/Terry already represent the relationship).
            # We look ahead up to 3 tokens for a [person] tag.
            has_following_person = False
            for j in range(i + 1, min(i + 4, len(doc))):
                if token_tags[j] == "[person]":
                    has_following_person = True
                    break
            if not has_following_person:
                tags.append("[relation]")
        elif pos in ("NOUN", "VERB") and lemma in EVENT_WORDS:
            tags.append("[event]")
        elif pos == "NOUN" and lemma in CONCEPT_WORDS:
            tags.append("[concept]")

        i += 1

    return tags

def get_tag_counts(text: str) -> Dict[str, int]:
    tags = extract_tags(text)
    counts = {}
    for t in tags:
        counts[t] = counts.get(t, 0) + 1
    return counts

def extract_keywords_and_phrases(text: str, limit: int = 4) -> List[str]:
    nlp = get_nlp()
    if nlp is None:
        return _fallback_keywords(text, limit)
    doc = nlp(text)

    phrases = []
    # 1. Grab noun chunks (keyphrases)
    for chunk in doc.noun_chunks:
        # Clean up chunk text (remove determiners, pronouns, etc.)
        clean_chunk = " ".join([t.text for t in chunk if not t.is_stop and t.pos_ in ("NOUN", "PROPN", "ADJ")])
        if clean_chunk and len(clean_chunk.split()) > 1:
            phrases.append(clean_chunk)

    # 2. Grab individual nouns, proper nouns, adjectives
    singles = []
    for token in doc:
        if not token.is_stop and not token.is_punct and token.pos_ in ("NOUN", "PROPN", "ADJ"):
            singles.append(token.text)

    # Combine them, prioritizing phrases, keeping up to limit unique terms
    results = []
    for p in phrases:
        if p.lower() not in [r.lower() for r in results]:
            results.append(p)
    for s in singles:
        if s.lower() not in [r.lower() for r in results] and len(results) < limit:
            results.append(s)

    return results[:limit]


_FALLBACK_STOPWORDS = {
    "about", "after", "again", "also", "and", "are", "because", "been",
    "before", "being", "but", "can", "could", "did", "does", "for",
    "from", "had", "has", "have", "her", "him", "his", "how", "into",
    "its", "just", "more", "not", "our", "she", "should", "that", "the",
    "their", "them", "then", "there", "these", "they", "this", "those",
    "was", "were", "what", "when", "where", "which", "who", "why", "will",
    "with", "would", "you", "your",
}


def _fallback_keywords(text: str, limit: int) -> List[str]:
    """Deterministic keyword heads when the optional spaCy model is absent."""
    words = re.findall(r"[A-Za-z][A-Za-z0-9_'-]{2,}", text or "")
    results = []
    for word in words:
        lowered = word.lower()
        if lowered in _FALLBACK_STOPWORDS or lowered in {r.lower() for r in results}:
            continue
        results.append(word)
        if len(results) >= limit:
            break
    return results


def _fallback_tags(text: str) -> List[str]:
    lowered = (text or "").lower()
    tags: List[str] = []
    tokens = set(re.findall(r"[a-z]+", lowered))
    if tokens & (RELATIONAL_VERBS | RELATIONAL_NOUNS):
        tags.append("[relation]")
    if tokens & EVENT_WORDS:
        tags.append("[event]")
    if tokens & CONCEPT_WORDS:
        tags.append("[concept]")
    return tags
