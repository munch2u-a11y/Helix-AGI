"""Helix — Semantic Retrieval Lane (Lane A)

Vendored from Micro-RAG's PreGenerativeInjector
(``mrag/core/pre_generative_injection.py``), reduced to its retrieval body.

What was kept, unchanged in behaviour:
  - Multi-head search: one embedding query per extracted concept angle, so a
    question that mixes an entity, a topic and an abstraction gets a separate
    shot at each rather than one averaged midpoint seed.
  - Rarity-weighted (idf) keyword scoring, so a rare exact term outranks a
    ubiquitous topic word instead of both counting as "one match".
  - Conceptual-tag fusion over the spaCy tagger.
  - Concept expansion: abstract query wording ("achievement") reaches concrete
    memory phrasing ("finished her screenplay").
  - Lexicon priority: a Tier-2 belief whose term/alias literally appears in the
    trigger jumps ahead of the fused ranking — an exact anchor beats an
    estimate.

What was dropped, and why:
  - ``inject()`` / ``inject_message()`` string formatting. This lane returns
    ranked candidates; assembling them into an injection is the caller's job
    (see core/unified_retrieval.py, and Preconscious for the render).
  - ``_suppress_merged_constituents`` and ``_purge_near_duplicates``. Both now
    run in the merge layer, which sees BOTH lanes' candidates — purging inside
    this lane would leave cross-lane duplicates untouched.
  - Adjacency expansion, for the same reason: it should expand around whatever
    actually survived the merge, not around this lane's pre-merge ranking. The
    index and the ``adjacent_chunks()`` helper live here; the merge layer calls
    them.

The thresholds carried over from mRAG are calibration results, not style
choices — the comments explaining them are kept deliberately.
"""

import logging
import math
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from memory.mrag.token_counting import count_text_tokens

logger = logging.getLogger("helix.memory.mrag.semantic_lane")

# Beliefs and memories are stored with a leading "[2026-05-25 13:14] " or
# "[13:14:02] " timestamp prefix for the model's own temporal grounding. That
# prefix is noise for semantic matching — the timestamp isn't part of the fact
# — so it's stripped before embedding and before any similarity comparison.
_TIMESTAMP_PREFIX = re.compile(r'^\[([\d\-: ]+)\]\s*')


def strip_timestamp_prefix(text: str) -> str:
    return _TIMESTAMP_PREFIX.sub("", text)


STOPWORDS = {
    "about", "above", "after", "again", "against", "along", "around",
    "before", "behind", "below", "beneath", "beside", "between", "beyond",
    "during", "under", "within", "without", "would", "could", "should",
    "their", "there", "these", "those", "other", "another", "through",
    "first", "second", "third", "since", "until", "while", "where",
    "which", "whose", "what", "when", "with", "from", "that", "this",
    "then", "here", "there", "have", "been", "were", "was", "is", "are",
    "did", "does", "do", "has", "had", "being", "will", "shall",
    "you", "your", "and", "for",
}

# Interrogative pronouns are excluded from single-word/noun-phrase heads
# separately from STOPWORDS since they're meaningful for other NLP purposes.
_QUESTION_WORDS = {"what", "when", "where", "which", "who", "whom", "whose", "why", "how"}

# Generic words that pass the single-word head filter (length >= 3, not a
# stopword) but carry almost no discriminating signal on their own — as a
# search head their embedding pulls in whatever's topically nearby rather
# than anything specific to the query, inflating match counts for otherwise
# irrelevant items. Excluded from single-word head generation only; they're
# still valid content elsewhere (bigrams, raw query text).
GENERIC_FILLER_WORDS = {
    "kinds", "kind", "things", "thing", "type", "types", "sort", "sorts",
    "way", "ways", "item", "items", "stuff", "some", "any", "many", "much",
    "both", "done", "have", "had",
}

# Bounds on how many parallel embedding queries a single retrieve() call fires.
# Keeps worst-case latency bounded as more head-generation strategies stack up.
MAX_SEARCH_HEADS = 16
MAX_CONCEPT_EXPANSION_HEADS = 8
MAX_RELATION_EXPANSION_HEADS = 6

# Derived heads widen recall, while the full query remains the most precise
# representation of intent. Their cosine can win, but with a small discount
# that prevents a one-word head from overpowering an already-good full-query
# match.
DERIVED_HEAD_SIMILARITY_WEIGHT = 0.92

# Lexicon pre-filter (Tier 2): a belief whose `term` (or an alias) appears in
# the trigger text ranks ahead of the fused ranking — it's an exact anchor
# match, not a similarity estimate. Capped so a query naming several known
# terms can't fill the whole budget with Tier-2 entries and crowd out the raw
# memory evidence they summarize.
MAX_LEXICON_PRIORITY_BELIEFS = 5

# How many salient content words one Tier-2 belief contributes to the
# concept-expansion vocabulary under its term/alias triggers.
MAX_LEXICON_EXPANSION_WORDS = 8

# A keyword-group match reached only through concept-expansion vocabulary
# counts a fraction of a match on the query's own keyword. Expansion exists
# for recall (abstract wording -> concrete memory phrasing); letting its
# co-occurrence vocabulary count at full weight erased the precision signal
# of a literal match — with per-term rarity weighting, a generic expansion
# word ("business") contributes ~nothing while a rare direct term ("ideal")
# dominates, so expansion pollution self-neutralizes.
EXPANDED_MATCH_WEIGHT = 0.3


def _term_pattern(term: str) -> "re.Pattern":
    """Word/phrase-boundary pattern for a keyword term. Multi-word terms
    match as a bounded phrase; single words never match inside longer
    words ("dance" does not fire on "dancer")."""
    return re.compile(r'\b' + re.escape(term) + r'\b')


# Lightweight concept -> concrete-vocabulary expansion map. Abstract question
# wording ("achievement", "relationship status") sits far from concrete memory
# phrasing ("finished her screenplay", "single parent") in embedding space.
# Each trigger adds its concrete synonyms as extra search heads so at least one
# head lands near the concrete memory.
DEFAULT_CONCEPT_EXPANSIONS: Dict[str, List[str]] = {
    "achievement": ["finished", "completed", "accomplished", "won", "succeeded", "milestone", "proud"],
    "accomplishment": ["finished", "completed", "accomplished", "won", "succeeded", "milestone"],
    "relationship status": ["single", "married", "dating", "divorced", "engaged", "widowed", "partner", "boyfriend", "girlfriend", "husband", "wife"],
    "interest": ["hobby", "enjoys", "passionate", "likes", "loves"],
    "hobby": ["enjoys", "passionate about", "likes", "spends time"],
    "occupation": ["works as", "job", "career", "profession", "employed"],
    "career path": ["works as", "job", "profession", "wants to become", "studying"],
    "volunteering": ["volunteers", "shelter", "charity", "donates", "helps out"],
    "health": ["sick", "diagnosed", "illness", "recovering", "therapy", "doctor"],
    "feeling": ["happy", "sad", "excited", "anxious", "proud", "stressed", "grateful"],
    "mood": ["happy", "sad", "excited", "anxious", "stressed"],
    "conflict": ["argument", "disagreement", "fight", "struggle", "tension"],
    "plan": ["going to", "intends to", "upcoming", "planning to"],
    "living situation": ["lives", "moved", "apartment", "house", "roommate"],
    "education": ["studies", "degree", "school", "college", "university", "enrolled"],
}


def _stem_word(word: str) -> str:
    word = word.lower().strip()
    if word.endswith("ing"):
        return word[:-3]
    if word.endswith("ed"):
        return word[:-2]
    # "es" only marks a genuine inserted-vowel plural/conjugation after a
    # sibilant ("boxes"->"box", "watches"->"watch", "buses"->"bus"). Any
    # other "...es" word ("loves", "hikes", "moves") is a plain silent-e word
    # + "s" and must fall through to the general "s" branch below
    # ("loves"->"love", not "lov").
    if word.endswith(("ses", "xes", "zes", "ches", "shes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    # Deliberately no blanket "er"/"est" comparative stripping: far more
    # common English words simply end in "er" as part of the root (prefer,
    # offer, consider, remember, deliver, cover) than are comparatives.
    return word


# Accepts bare numbers and short alpha-prefixed forms: "7", "t7" (chat turns),
# "p12" (pulse ids), "turn3". Helix passes pulse ids here.
_TURN_ID_RE = re.compile(r'^[a-z]{0,4}[_-]?(\d+)$', re.IGNORECASE)


def turn_number(turn_id: Any) -> Optional[int]:
    if turn_id is None:
        return None
    if isinstance(turn_id, int):
        return turn_id
    m = _TURN_ID_RE.match(str(turn_id).strip())
    return int(m.group(1)) if m else None


def estimate_tokens(text: str) -> int:
    return count_text_tokens(text)


class SemanticLane:
    """Cosine + keyword + tag retrieval over the unified Helix corpus.

    Consumes a corpus adapter (see memory/mrag/corpus.py) and a vector store
    (see memory/mrag/vector_store.py); owns no storage of its own.
    """

    def __init__(
        self,
        corpus,
        vector_store,
        top_k_candidates: int = 30,
        concept_expansions: Optional[Dict[str, List[str]]] = None,
        blacklist_memory_size: int = 15,
    ):
        self._corpus = corpus
        self._vector_store = vector_store
        self.top_k_candidates = top_k_candidates

        # Three layers, increasing priority: built-in defaults, expansions
        # learned from consolidated facts, and explicit user overrides.
        # Defaults and learned entries are additive (unioned per category); an
        # explicit user override for a category replaces it outright.
        self._user_concept_expansions = concept_expansions or {}
        self._learned_concept_expansions: Dict[str, List[str]] = {}
        self._lexicon_terms: Dict[str, List[str]] = {}
        self._lexicon_concept_expansions: Dict[str, List[str]] = {}
        self._concept_expansions = self._compute_concept_expansions()
        self._learned_relation_expansions: Dict[str, Dict[str, List[str]]] = {}

        # Conversational-position indexes over Tier-0 memories, for adjacency
        # expansion driven by the merge layer.
        self._memory_turn_index: Dict[Tuple[Any, int], List[Dict[str, Any]]] = {}
        self._memory_event_index: Dict[str, List[Dict[str, Any]]] = {}

        # Rolling blacklist. Unlike Helix's hard exclusion sets this only
        # DEMOTES: a recently injected item sorts to the back rather than
        # being removed, so a still-relevant anchor can resurface rather than
        # vanishing for a fixed window.
        self._blacklist_memory_size = blacklist_memory_size
        self._recent_injections: List[str] = []

        # Set by retrieve(): ids that matched a lexicon term directly, for the
        # caller's reliance telemetry.
        self.last_lexicon_matches: set = set()

        self._last_synced_version: Optional[int] = None
        # Cached lowercase, timestamp-stripped content per item id, plus its
        # inverted token index. Rebuilding these per query dominated keyword
        # scoring cost on large stores.
        self._content_index: List[Tuple[str, str]] = []
        self._token_index: Dict[str, set] = {}

    # ── Sync ─────────────────────────────────────────────────────────

    def sync(self):
        """Refresh the lexicon, adjacency and content indexes when the corpus
        has changed. Embeddings need no sync — they already live in Helix's
        SemanticIndex, which is written on the ingest path."""
        # Refresh stores before reading the version. Reading version first
        # made every actual corpus mutation visible one query late and forced
        # an unnecessary second rebuild on the following query.
        self._corpus.all_items()
        version = getattr(self._corpus, "version", None)
        if version is not None and version == self._last_synced_version:
            return

        learned = self._corpus.get_all_concept_expansions()
        if learned != self._learned_concept_expansions:
            self._learned_concept_expansions = learned
            self._concept_expansions = self._compute_concept_expansions()

        learned_relations = self._corpus.get_all_relation_expansions()
        if learned_relations != self._learned_relation_expansions:
            self._learned_relation_expansions = learned_relations

        self._rebuild_lexicon()
        self._rebuild_memory_adjacency()
        self._rebuild_content_index()
        self._last_synced_version = version

    def _compute_concept_expansions(self) -> Dict[str, List[str]]:
        """Merges the three concept-expansion layers: built-in defaults and
        learned instances are additive (unioned per category); an explicit
        user override for a category replaces it outright."""
        merged: Dict[str, List[str]] = {k: list(v) for k, v in DEFAULT_CONCEPT_EXPANSIONS.items()}
        for source in (self._learned_concept_expansions, self._lexicon_concept_expansions):
            for category, instances in source.items():
                bucket = merged.setdefault(category, [])
                for instance in instances:
                    if instance not in bucket:
                        bucket.append(instance)
        for category, instances in self._user_concept_expansions.items():
            merged[category] = list(instances)
        return merged

    def _rebuild_lexicon(self):
        """Rebuild the Tier-2 term lexicon from the corpus.

        Every belief carrying a `term` becomes a lexicon entry: the term and
        each alias map to the belief's id (for the priority pre-filter) and to
        the belief's salient content words (merged into the concept-expansion
        map, so a query phrased with the alias vocabulary reaches items phrased
        with the concrete vocabulary).

        Diverges from mRAG in one place: mRAG gated on ``layer == 2``, a field
        Helix does not write. Helix marks Tier 2 by the presence of `term`
        itself (see Curator._precipitate_layer2), so that is the gate here.
        """
        terms: Dict[str, List[str]] = {}
        expansions: Dict[str, List[str]] = {}
        for item in self._corpus.all_items():
            term = str(item.get("term", "") or "").strip().lower()
            if not term:
                continue
            aliases = [
                str(a).strip().lower() for a in (item.get("aliases") or [])
                if a and str(a).strip()
            ]
            content = strip_timestamp_prefix(item.get("content", "")).lower()
            salient = []
            for word in re.findall(r"[a-z]{4,}", content):
                if word in STOPWORDS or word in GENERIC_FILLER_WORDS:
                    continue
                if word not in salient:
                    salient.append(word)
            salient = salient[:MAX_LEXICON_EXPANSION_WORDS]

            bid = item.get("id")
            for key in dict.fromkeys([term] + aliases):
                if bid:
                    terms.setdefault(key, []).append(bid)
                bucket = expansions.setdefault(key, [])
                for word in [term] + salient:
                    if word != key and word not in bucket:
                        bucket.append(word)

        self._lexicon_terms = terms
        if expansions != self._lexicon_concept_expansions:
            self._lexicon_concept_expansions = expansions
            self._concept_expansions = self._compute_concept_expansions()

    def _rebuild_memory_adjacency(self):
        """Rebuild conversational-position indexes over Tier-0 memories.

        Helix has no session concept, so the corpus adapter supplies the
        creation date as session_id and the pulse id as turn_id — adjacent
        pulses within a day are the conversational neighbours.
        """
        turn_index: Dict[Tuple[Any, int], List[Dict[str, Any]]] = {}
        event_index: Dict[str, List[Dict[str, Any]]] = {}
        for item in self._corpus.all_items():
            if item.get("tier") != 0:
                continue
            turn_num = turn_number(item.get("turn_id"))
            session_id = item.get("session_id")
            if session_id is not None and turn_num is not None:
                turn_index.setdefault((session_id, turn_num), []).append(item)
            event_id = item.get("event_id")
            if event_id:
                event_index.setdefault(event_id, []).append(item)
        for chunks in turn_index.values():
            chunks.sort(key=lambda b: b.get("chunk_index") or 0)
        for chunks in event_index.values():
            chunks.sort(key=lambda b: b.get("chunk_index") or 0)
        self._memory_turn_index = turn_index
        self._memory_event_index = event_index

    def _rebuild_content_index(self):
        """Rebuild the lowercase content list and its inverted token index.

        mRAG regex-scanned every stored item for every query term. That was
        fine over a benchmark-sized store, but Helix's pool includes the whole
        journal and grows every pulse, so the scan became the dominant cost.
        The inverted index gives exact document frequencies and exact matches
        for single-word terms by dict lookup instead; multi-word phrases still
        need a scan, but only over the items containing the phrase's rarest
        token. Match semantics are unchanged — splitting on non-word
        characters produces the same boundaries `\\b` does.
        """
        self._content_index = [
            (item["id"], strip_timestamp_prefix(item.get("content", "")).lower())
            for item in self._corpus.all_items()
        ]
        token_index: Dict[str, set] = {}
        for item_id, content in self._content_index:
            for token in set(re.findall(r'\w+', content)):
                token_index.setdefault(token, set()).add(item_id)
        self._token_index = token_index

    def adjacent_chunks(self, anchor: Dict[str, Any], turn_window: int) -> List[Dict[str, Any]]:
        """The anchor memory's immediate conversational neighbours, nearest
        first: same-event siblings (chunk_index ±1), then same-session turns at
        distance 1, 2, ... up to turn_window.

        Retrieval often lands on the lead-in turn ("Any fun plans?") while the
        payload is the reply one turn away, which is what this recovers.
        """
        neighbors: List[Dict[str, Any]] = []
        seen = {anchor.get("id")}

        anchor_index = anchor.get("chunk_index")
        event_id = anchor.get("event_id")
        if event_id and isinstance(anchor_index, int):
            for sibling in self._memory_event_index.get(event_id, []):
                sib_index = sibling.get("chunk_index")
                if isinstance(sib_index, int) and abs(sib_index - anchor_index) == 1 and sibling.get("id") not in seen:
                    neighbors.append(sibling)
                    seen.add(sibling.get("id"))

        session_id = anchor.get("session_id")
        turn_num = turn_number(anchor.get("turn_id"))
        if session_id is not None and turn_num is not None:
            for distance in range(1, turn_window + 1):
                for adjacent_turn in (turn_num - distance, turn_num + distance):
                    for chunk in self._memory_turn_index.get((session_id, adjacent_turn), []):
                        if chunk.get("id") not in seen:
                            neighbors.append(chunk)
                            seen.add(chunk.get("id"))
        return neighbors

    # ── Search heads ─────────────────────────────────────────────────

    def _generate_search_heads(self, text: str) -> List[str]:
        """Build the set of parallel embedding queries (multi-head retrieval).

        Priority order (highest-value heads first, since the total is capped
        at MAX_SEARCH_HEADS):
          1. The raw query text itself.
          2. Capitalized words (proper nouns: names, places).
          3. Consecutive-noun-phrase bigrams ("charity race").
          4. Individual significant single words — a bigram extractor alone
             misses key nouns that appear alone ("school" in "give a speech at
             a school").
          5. Concept-expansion vocabulary — when the query uses abstract
             language, add the concrete synonyms a memory would be phrased with.
          6. Named-entity relation expansion — when the query mentions both a
             known subject ("John") and one of that subject's learned relation
             words ("friends"), add the specific named entities from that
             relation so the query never has to name them itself.
        """
        heads = [text]
        words = text.split()
        clean_words = [re.sub(r'[^\w]', '', w) for w in words]
        lowered_words = [w.lower() for w in clean_words]

        if len(words) > 1:
            for w_clean in clean_words[1:]:
                if w_clean and w_clean[0].isupper() and w_clean.lower() not in STOPWORDS:
                    heads.append(w_clean)

            noun_phrases = []
            for i in range(len(clean_words) - 1):
                w1, w2 = lowered_words[i], lowered_words[i + 1]
                if w1 not in STOPWORDS and w2 not in STOPWORDS and len(w1) > 2 and len(w2) > 2:
                    if w1 not in _QUESTION_WORDS:
                        noun_phrases.append(f"{clean_words[i]} {clean_words[i + 1]}")
            if noun_phrases:
                heads.extend(noun_phrases[:2])

            for w_clean, w_lower in zip(clean_words, lowered_words):
                if (
                    len(w_lower) >= 3
                    and w_lower not in STOPWORDS
                    and w_lower not in _QUESTION_WORDS
                    and w_lower not in GENERIC_FILLER_WORDS
                    and w_lower.isalpha()
                ):
                    heads.append(w_lower)

        # Word/phrase-boundary matching only — a substring trigger let a common
        # lexicon term ("dance") fire from inside unrelated phrases and flood
        # the heads with its co-occurrence vocabulary.
        text_lower = text.lower()
        expansion_heads: List[str] = []
        for trigger, expansions in self._concept_expansions.items():
            if _term_pattern(trigger).search(text_lower):
                expansion_heads.extend(expansions)
        expansion_heads = list(dict.fromkeys(expansion_heads))[:MAX_CONCEPT_EXPANSION_HEADS]

        # Requires BOTH the subject and one of its tagged relation words —
        # matching on the subject alone would fire on every mention of "John"
        # regardless of topic. Stemmed comparison handles number/tense
        # variation ("friend" vs "friends").
        relation_heads: List[str] = []
        if self._learned_relation_expansions:
            query_word_stems = {_stem_word(w) for w in lowered_words if w}
            for subj, relations in self._learned_relation_expansions.items():
                if subj not in text_lower:
                    continue
                for rel_type, entities in relations.items():
                    if _stem_word(rel_type) in query_word_stems or rel_type in text_lower:
                        relation_heads.extend(entities)
        relation_heads = list(dict.fromkeys(relation_heads))[:MAX_RELATION_EXPANSION_HEADS]

        # Reserve room for expansion/relation heads so a long question's
        # single-word heads can't crowd out these targeted fixes at the final
        # cap — both are the highest-value additions and must survive
        # truncation.
        priority_heads = list(dict.fromkeys(expansion_heads + relation_heads))
        heads = list(dict.fromkeys(heads))
        base_budget = max(1, MAX_SEARCH_HEADS - len(priority_heads))
        heads = heads[:base_budget]

        return list(dict.fromkeys(heads + priority_heads))[:MAX_SEARCH_HEADS]

    def _match_lexicon_terms(self, text: str) -> List[str]:
        """Item ids whose term/alias appears in the trigger text — multi-word
        keys as a bounded phrase, single-word keys by stemmed word match."""
        if not self._lexicon_terms:
            return []
        text_lower = text.lower()
        word_stems = {
            _stem_word(re.sub(r'[^\w]', '', w))
            for w in text_lower.split() if re.sub(r'[^\w]', '', w)
        }
        matched: List[str] = []
        for key, bids in self._lexicon_terms.items():
            if " " in key:
                if _term_pattern(key).search(text_lower):
                    matched.extend(bids)
            elif _stem_word(key) in word_stems:
                matched.extend(bids)
        return list(dict.fromkeys(matched))

    # ── Scoring ──────────────────────────────────────────────────────

    def _score_keyword_matches(
        self,
        keyword_search_groups: List[List[Tuple[str, bool]]],
    ) -> Dict[str, float]:
        """Rarity-weighted keyword scoring.

        For each item and each keyword group, the group's contribution is the
        best-scoring matching term: idf(term) x 1.0 for the query's own
        keyword, x EXPANDED_MATCH_WEIGHT for expansion vocabulary. idf is
        normalized to [~0, 1] over this corpus, so a term appearing in one
        memory out of hundreds ("ideal") scores near 1.0 while a term half the
        corpus contains ("dance") scores near 0 — a match's value scales with
        how much it actually narrows the corpus, with no fixed constants to
        tune. Replaces a flat count, where an exact rare match and a ubiquitous
        topic word were worth the same.
        """
        unique_terms = {t for group in keyword_search_groups for t, _ in group}
        if not unique_terms:
            return {}

        n = max(1, len(self._content_index))
        doc_freq = {t: 0 for t in unique_terms}
        matches: Dict[str, set] = {}

        content_by_id = None
        for term in unique_terms:
            if " " in term:
                # Multi-word phrase: narrow to items containing its rarest
                # token, then confirm the full phrase by regex.
                tokens = re.findall(r'\w+', term)
                if not tokens:
                    continue
                candidate_ids = min(
                    (self._token_index.get(tok, set()) for tok in tokens),
                    key=len,
                    default=set(),
                )
                if not candidate_ids:
                    continue
                if content_by_id is None:
                    content_by_id = dict(self._content_index)
                pattern = _term_pattern(term)
                hits = {
                    bid for bid in candidate_ids
                    if pattern.search(content_by_id.get(bid, ""))
                }
            else:
                hits = self._token_index.get(term, set())

            doc_freq[term] = len(hits)
            for bid in hits:
                matches.setdefault(bid, set()).add(term)

        log_n = math.log(1 + n)
        idf = {
            t: (math.log(1 + n / doc_freq[t]) / log_n) if doc_freq[t] else 0.0
            for t in unique_terms
        }

        scores: Dict[str, float] = {}
        for bid, hit in matches.items():
            total = 0.0
            for group in keyword_search_groups:
                best = 0.0
                for term, direct in group:
                    if term in hit:
                        weight = idf[term] * (1.0 if direct else EXPANDED_MATCH_WEIGHT)
                        if weight > best:
                            best = weight
                total += best
            if total:
                scores[bid] = total
        return scores

    # ── Retrieval ────────────────────────────────────────────────────

    def retrieve(self, text: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Rank corpus items against the trigger text.

        Hybrid union candidate selection (keyword top-k ∪ vector top-k)
        followed by three-way soft-score fusion (cosine + rarity-weighted
        keyword + conceptual tag), then the Tier-2 lexicon priority pass.

        Returns candidate dicts (the corpus's own item dicts, not copies)
        each carrying ``lane_a_score`` and ``lane_a_rank``. No deduplication,
        suppression or budgeting happens here — the merge layer owns all of
        that, because it is the only place that sees both lanes.
        """
        self.sync()
        self.last_lexicon_matches = set()

        text = (text or "").strip()
        if not text:
            return []

        from memory.mrag.tagger import extract_keywords_and_phrases, get_tag_counts

        all_items = self._corpus.all_items()
        if not all_items:
            return []

        # 1. Parse the trigger for up to 4 keyword/keyphrase search terms.
        query_keywords = extract_keywords_and_phrases(text, limit=4)
        query_tag_counts = get_tag_counts(text)

        # 2. Split keywords into conceptually similar terms via the expansion
        #    map. Each group keeps provenance: the query's own keyword is a
        #    "direct" term; vocabulary reached through expansion is not, and
        #    counts at EXPANDED_MATCH_WEIGHT in scoring.
        keyword_search_groups: List[List[Tuple[str, bool]]] = []
        for kw in query_keywords:
            kw_lower = kw.lower()
            terms: List[Tuple[str, bool]] = [(kw_lower, True)]
            seen_terms = {kw_lower}
            for trigger, expansions in self._concept_expansions.items():
                if _term_pattern(trigger).search(kw_lower):
                    for exp in expansions:
                        e = exp.lower()
                        if e not in seen_terms:
                            terms.append((e, False))
                            seen_terms.add(e)
            keyword_search_groups.append(terms)

        dynamic_top_k = max(30, min(60, int(len(all_items) * 0.10)))

        # 3. Rarity-weighted keyword scores. Conceptual tags are evaluated
        # after the vector/keyword union is known; parsing the entire lifetime
        # corpus with spaCy on every query would erase FAISS's scaling gain.
        keyword_scores = self._score_keyword_matches(keyword_search_groups)

        # 4. Hybrid union candidate selection.
        by_id = {item["id"]: item for item in all_items}

        keyword_top = sorted(
            keyword_scores.items(),
            key=lambda kv: (kv[1], by_id[kv[0]].get("relevance", 0.0) if kv[0] in by_id else 0.0),
            reverse=True,
        )[:dynamic_top_k]
        union: Dict[str, Dict[str, Any]] = {}
        for bid, _score in keyword_top:
            item = by_id.get(bid)
            if item is not None:
                union[bid] = item

        # Multi-head vector retrieval: every head contributes its own top-k,
        # so a query mixing an entity with an abstraction reaches both.
        heads = self._generate_search_heads(text)
        per_head_k = max(5, dynamic_top_k // max(1, len(heads)))
        query_embedding = self._vector_store.embed_text(text)
        multi_head_similarities: Dict[str, float] = {}
        for head in heads:
            head_emb = query_embedding if head == text else self._vector_store.embed_text(head)
            head_weight = 1.0 if head == text else DERIVED_HEAD_SIMILARITY_WEIGHT
            for bid, similarity in self._vector_store.query_top_k(head_emb, k=per_head_k):
                item = by_id.get(bid)
                if item is not None:
                    union[bid] = item
                    weighted_similarity = float(similarity) * head_weight
                    if weighted_similarity > multi_head_similarities.get(bid, -1.0):
                        multi_head_similarities[bid] = weighted_similarity

        candidates = list(union.values())
        if not candidates:
            candidates = all_items[:dynamic_top_k]

        # Tag overlap is a late semantic nudge over at most ~80 union
        # candidates, never a full-corpus scan.
        tag_scores: Dict[str, float] = {}
        if query_tag_counts:
            for item in candidates:
                item_tags = self._corpus.conceptual_tags(item)
                if not item_tags:
                    continue
                tag_matches = 0
                for tag, q_count in query_tag_counts.items():
                    tag_matches += min(q_count, item_tags.count(tag))
                if tag_matches:
                    tag_scores[item["id"]] = tag_matches

        # 5. Three-way soft-score fusion. The keyword and tag terms are a
        #    NUDGE on top of cosine, scaled to the local score gradient so the
        #    bump is always meaningful relative to how tightly packed the
        #    candidates are, but never overpowering.
        cosine_similarities: Dict[str, float] = {}
        for item in candidates:
            emb = self._corpus.embedding(item)
            full_query_similarity = (
                self._vector_store.cosine_similarity(query_embedding, emb)
                if emb is not None else 0.0
            )
            # Candidate generation and scoring are both genuinely multi-head:
            # the old port used extra FAISS heads only to enter the pool, then
            # discarded their scores and re-ranked solely against the full
            # query, which buried the very recall those heads recovered.
            cosine_similarities[item["id"]] = max(
                full_query_similarity,
                multi_head_similarities.get(item["id"], 0.0),
            )

        cos_sims = list(cosine_similarities.values())
        sim_std = float(np.std(cos_sims)) if cos_sims else 0.05
        nudge_weight = max(0.01, min(0.10, sim_std * 1.5))

        fused: List[Tuple[Dict[str, Any], float]] = []
        for item in candidates:
            bid = item["id"]
            cos_sim = cosine_similarities[bid]
            kw_boost = nudge_weight * math.log(1 + keyword_scores.get(bid, 0.0))
            tag_boost = nudge_weight * 0.5 * math.log(1 + tag_scores.get(bid, 0.0))
            fused.append((item, cos_sim + kw_boost + tag_boost))

        # 6. Repetition demotion, then rank.
        fused.sort(key=lambda x: (
            x[0]["id"] in self._recent_injections,
            -x[1],
            -x[0].get("relevance", 0.0),
        ))
        scores_by_id = {item["id"]: score for item, score in fused}
        ranked = [item for item, _ in fused]

        # 7. Lexicon pre-filter (Tier 2): items whose term/alias literally
        #    appears in the query jump ahead of the fused ranking — an exact
        #    anchor match outranks any similarity estimate. Matches absent
        #    from the union pool are pulled in from the corpus.
        lexicon_ids = self._match_lexicon_terms(text)
        self.last_lexicon_matches = set(lexicon_ids)
        if lexicon_ids:
            lexicon_id_set = set(lexicon_ids)
            in_pool = {item["id"] for item in ranked}
            priority: List[Dict[str, Any]] = []
            for bid in lexicon_ids:
                if bid in in_pool or bid in self._recent_injections:
                    continue
                fetched = by_id.get(bid)
                if fetched is not None:
                    priority.append(fetched)
            rest: List[Dict[str, Any]] = []
            for item in ranked:
                if (item["id"] in lexicon_id_set
                        and item["id"] not in self._recent_injections
                        and len(priority) < MAX_LEXICON_PRIORITY_BELIEFS):
                    priority.append(item)
                else:
                    rest.append(item)
            ranked = priority[:MAX_LEXICON_PRIORITY_BELIEFS] + rest

        for rank, item in enumerate(ranked):
            item["lane_a_score"] = scores_by_id.get(item["id"], 0.0)
            item["lane_a_rank"] = rank

        logger.debug(
            "Lane A: %d candidates from %d items (%d heads, %d lexicon hits)",
            len(ranked), len(all_items), len(heads), len(lexicon_ids),
        )

        return ranked[:limit] if limit is not None else ranked

    # ── Blacklist ────────────────────────────────────────────────────

    def note_injected(self, ids: List[str]):
        """Record ids that reached an injection, for repetition demotion."""
        for bid in ids:
            if bid and bid not in self._recent_injections:
                self._recent_injections.append(bid)
        if len(self._recent_injections) > self._blacklist_memory_size:
            self._recent_injections = self._recent_injections[-self._blacklist_memory_size:]

    def clear_blacklist(self):
        self._recent_injections.clear()
