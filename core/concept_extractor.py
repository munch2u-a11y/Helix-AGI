"""
Helix — Concept Extractor (RAKE-Style Keyphrase Extraction)

A lightweight, zero-latency natural language concept extractor for the
preconscious injection pipeline. Uses basic regex tokenization and
word co-occurrence scoring (RAKE algorithm) to identify substantive
noun phrases from trigger text.

This module serves two roles:
  1. Concept extraction — pulls 1-5 key concepts from trigger text,
     scaled dynamically by input richness (word count / density).
  2. Lexicon backend — scans extracted concepts against the lexicon
     term lookup to separate known entities from general concepts.

Each extracted concept becomes an independent gravity query center
in the preconscious, replacing the previous single-centroid approach
that caused "midway point junk" injection.

Zero API calls. Zero dependencies beyond stdlib. ~2ms per call.
"""

import re
import logging
from typing import Optional, Set, Dict, List

logger = logging.getLogger("helix.core.concept_extractor")


class ConceptExtractor:
    """Extracts key concepts from natural language text.

    Uses RAKE-style scoring (Rapid Automatic Keyword Extraction):
      1. Tokenize text using regex word boundaries
      2. Split into candidate phrases at stop-word boundaries
      3. Score words by degree/frequency ratio
      4. Score phrases by sum of word scores
      5. Separate lexicon matches from general concepts

    The number of concepts returned scales dynamically with input
    richness — short inputs yield 1-2 concepts, dense paragraphs
    yield up to the hard cap.
    """

    # ── Stop Words ────────────────────────────────────────────────────
    # Comprehensive English stop words including conversational fillers.
    # These act as phrase boundary markers — everything between stop
    # words becomes a candidate concept phrase.
    STOP_WORDS = frozenset([
        'i', 'me', 'my', 'myself', 'we', 'our', 'ours', 'ourselves', 'you', 'your', 'yours',
        'yourself', 'yourselves', 'he', 'him', 'his', 'himself', 'she', 'her', 'hers',
        'herself', 'it', 'its', 'itself', 'they', 'them', 'their', 'theirs', 'themselves',
        'what', 'which', 'who', 'whom', 'this', 'that', 'these', 'those', 'am', 'is', 'are',
        'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'having', 'do', 'does',
        'did', 'doing', 'a', 'an', 'the', 'and', 'but', 'if', 'or', 'because', 'as', 'until',
        'while', 'of', 'at', 'by', 'for', 'with', 'about', 'against', 'between', 'into',
        'through', 'during', 'before', 'after', 'above', 'below', 'to', 'from', 'up', 'down',
        'in', 'out', 'on', 'off', 'over', 'under', 'again', 'further', 'then', 'once', 'here',
        'there', 'when', 'where', 'why', 'how', 'all', 'any', 'both', 'each', 'few', 'more',
        'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so',
        'than', 'too', 'very', 's', 't', 'can', 'will', 'just', 'don', 'should', 'now',
        'could', 'would', 'also', 'really', 'might', 'must', 'even', 'like', 'much', 'many',
        'well', 'us', 'yes', 'no', 'ok', 'okay', 'hey', 'hi', 'hello', 'thanks', 'thank',
        'please', 'need', 'want', 'make', 'sure', 'let', 'lets', 'going', 'think', 'thought',
        'know', 'see', 'look', 'find', 'tell', 'say', 'said',
    ])

    # ── Dynamic Scaling ───────────────────────────────────────────────
    # Input richness → concept budget mapping.
    # Approximately 1 concept per 15 substantive words.
    WORDS_PER_CONCEPT = 15
    MIN_CONCEPTS = 1
    MAX_CONCEPTS = 5

    # Minimum RAKE score for a phrase to be considered a real concept.
    # Filters out low-value single words like "check" or "optimize".
    MIN_PHRASE_SCORE = 1.5

    def __init__(self, lexicon_keys: Optional[Set[str]] = None):
        """Initialize the concept extractor.

        Args:
            lexicon_keys: Set of known lexicon terms (will be lowercased).
                          If provided, matching concepts are separated into
                          a priority lexicon_matches list.
        """
        self.lexicon_keys = set(k.lower() for k in (lexicon_keys or []))

    def update_lexicon_keys(self, lexicon_keys: Set[str]):
        """Update the lexicon key set (e.g., after lexicon.json reload)."""
        self.lexicon_keys = set(k.lower() for k in lexicon_keys)

    # ── Tokenizer ─────────────────────────────────────────────────────

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """Basic regex tokenization.

        Extracts words including internal apostrophes (e.g., "don't",
        "geordi's") and treats everything else as a boundary.
        """
        return re.findall(r"\b[a-zA-Z0-9]+(?:'[a-zA-Z0-9]+)?\b", text.lower())

    # ── Dynamic Budget ────────────────────────────────────────────────

    def _compute_budget(self, text: str) -> int:
        """Compute concept budget based on input richness.

        Short inputs ("OK, I'll check that") → 1 concept.
        Medium inputs (3-sentence thought) → 2-3 concepts.
        Dense paragraphs → up to MAX_CONCEPTS.
        """
        # Count substantive words (non-stopwords)
        tokens = self._tokenize(text)
        substantive = [t for t in tokens if t not in self.STOP_WORDS]
        count = len(substantive)

        budget = max(self.MIN_CONCEPTS, count // self.WORDS_PER_CONCEPT)
        return min(budget, self.MAX_CONCEPTS)

    # ── Main Extraction ───────────────────────────────────────────────

    def extract(self, text: str, max_concepts: Optional[int] = None) -> Dict[str, list]:
        """Extract the highest-scoring concepts from the text.

        Args:
            text: Input text (thought output, incoming events, etc.)
            max_concepts: Override for dynamic budget. If None, budget
                          is computed from input richness.

        Returns:
            Dict with:
              - "lexicon_matches": list of matched lexicon terms (priority)
              - "concepts": list of extracted concept phrases (general)
              - "budget": int, the concept budget used
        """
        if not text or not text.strip():
            return {"lexicon_matches": [], "concepts": [], "budget": 0}

        # Compute dynamic budget if not overridden
        budget = max_concepts if max_concepts is not None else self._compute_budget(text)

        # 1. Split text into phrase boundaries at punctuation
        clean_text = re.sub(r'[.,!?;\n\r\t]+', '|', text.lower())
        raw_phrases = [p.strip() for p in clean_text.split('|') if p.strip()]

        # 2. Split phrases by stop words using tokenization
        candidate_phrases = []
        for phrase in raw_phrases:
            words = self._tokenize(phrase)
            current_phrase = []
            for word in words:
                if word in self.STOP_WORDS:
                    if current_phrase:
                        candidate_phrases.append(' '.join(current_phrase))
                        current_phrase = []
                else:
                    current_phrase.append(word)
            if current_phrase:
                candidate_phrases.append(' '.join(current_phrase))

        if not candidate_phrases:
            return {"lexicon_matches": [], "concepts": [], "budget": budget}

        # 3. Word scoring (Frequency and Degree)
        word_freq: Dict[str, int] = {}
        word_degree: Dict[str, int] = {}

        for phrase in candidate_phrases:
            words = phrase.split()
            length = len(words)
            for word in words:
                word_freq[word] = word_freq.get(word, 0) + 1
                word_degree[word] = word_degree.get(word, 0) + length

        # Word score = degree / frequency
        # Favors words that appear in long, multi-word phrases
        word_scores: Dict[str, float] = {}
        for word in word_freq:
            word_scores[word] = word_degree[word] / word_freq[word]

        # 4. Score candidate phrases
        phrase_scores: Dict[str, float] = {}
        for phrase in candidate_phrases:
            if phrase not in phrase_scores:
                words = phrase.split()
                score = sum(word_scores[word] for word in words)
                phrase_scores[phrase] = score

        # 5. Separate lexicon matches from general concepts
        lexicon_matches = []
        general_concepts = []

        # Sort phrases by score, highest first
        sorted_phrases = sorted(
            phrase_scores.items(), key=lambda x: x[1], reverse=True
        )

        for phrase, score in sorted_phrases:
            # Filter out single characters and pure numbers
            if len(phrase) <= 1 or phrase.isnumeric():
                continue

            # Check if this phrase is an exact lexicon term
            if phrase in self.lexicon_keys:
                if phrase not in lexicon_matches:
                    lexicon_matches.append(phrase)
                continue

            # Check if any word in the phrase is a lexicon term
            words = phrase.split()
            phrase_has_lexicon = False
            for w in words:
                if w in self.lexicon_keys:
                    if w not in lexicon_matches:
                        lexicon_matches.append(w)
                    phrase_has_lexicon = True

            # Check for multi-word lexicon terms contained in the phrase
            for lex_term in self.lexicon_keys:
                if " " in lex_term and lex_term in phrase:
                    if lex_term not in lexicon_matches:
                        lexicon_matches.append(lex_term)
                    phrase_has_lexicon = True

            # Add to general concepts if it passes the score gate
            if not phrase_has_lexicon and score >= self.MIN_PHRASE_SCORE:
                if len(general_concepts) < budget:
                    general_concepts.append(phrase)

        logger.debug(
            "Extracted %d lexicon + %d concepts (budget=%d) from %d chars",
            len(lexicon_matches), len(general_concepts), budget, len(text),
        )

        return {
            "lexicon_matches": lexicon_matches,
            "concepts": general_concepts[:budget],
            "budget": budget,
        }
