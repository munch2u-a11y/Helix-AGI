# Context Architecture Fork Comparison

**Status:** experimental comparison · **Exam date:** 2026-08-08

Both branches start from `e5c33b5` and keep the Helix journal, belief stores,
1024D semantic index, and 8D associative state canonical. Neither copies
memory into RAGOffice markdown libraries or a second belief database.

| Design | Branch | Answerable | Controls | Gold support | Non-gold ratio | Answer/refusal warnings |
|---|---|---:|---:|---:|---:|---:|
| Pre-experiment Helix | shared baseline | 50/100 | 9/10 | 63.2% | — | not measured |
| Helix-native task compiler | `experiment/hybrid-context-compiler` at `c48c35a` | 100/100 | 10/10 | 100% | 74.2% | 4 |
| Canonical Context Office | `experiment/ragoffice-context-office` at `8030818` plus result-doc commit | 100/100 | 10/10 | 100% | 74.2% | 1 |

The two experimental runs used the same frozen 110-item RAGOffice exam, all
220 source turns in one isolated Helix mind, local `granite4.1:8b`, the same
reader prompt and accepted-answer rules, and no subscription calls. Generated
details and manual-review pages live under
`benchmark_results/ragoffice_parity_hybrid_110_v2/` and
`benchmark_results/ragoffice_parity_context_office_110/`.

## What differs

The hybrid compiler is the smaller conceptual change. mRAG remains the named
foreground, and one task-aware compiler binds its result to a complete episode,
orders state, closes relation/list/aggregation evidence, and emits stance
implications.

The Context Office makes prompt assembly an explicit subsystem. mRAG is a
semantic advisor; Facts, State, Relations, Catalog, Beliefs, and Causality
desks construct one evidence brief over the canonical corpus. The 8D and
learned-transition lanes appear as a separate lateral desk and cannot certify
task evidence. The desks are deterministic views, not separate identities or
LLM agents, so every accepted result still belongs to the single Helix mind.

## Interpretation

Accuracy and retrieval are tied on this synthetic exam. The office run had
fewer reader-format warnings (one versus four), but that is a prompt-quality
signal rather than proof of a statistically stable advantage from one run.
The Context Office is the stronger long-term extension seam for situational
habits, tool-use practices, persona views, and deeper `/remember` work because
each can become a scoped identity-shared desk without adding a memory silo.
The hybrid compiler remains the simpler fallback if operational complexity is
the primary constraint.

Before either design becomes the default, run the progressive indirect-
association benchmark and a natural long-dialogue suite. This exam strongly
tests deterministic scope closure but does not establish that learned 8D
associations, affect, or user mannerisms improve behavior. The 74.2% non-gold
ratio is mostly the deliberately retained lateral/recent context and should be
evaluated for usefulness, not optimized away from this score alone.

## Office-first runtime vertical slice

The branch now also contains an opt-in inversion behind
`HELIX_OFFICE_FIRST=1`. It is intentionally separate from the scored Context
Office experiment above; those benchmark numbers do not measure this new
runtime path.

The vertical slice preserves typed events and chooses a deterministic source
profile before retrieval. A thin relay makes one call to the existing
`UnifiedRetrieval` pipeline; mRAG, Context Office, case routing, beliefs, affect,
and the 8D complement keep their existing ownership and are not reimplemented.
The relay adds recent exact turns and action receipts, compiles the shared
capsule, and closes the fresh schema-free speaking session after one turn.
Ordinary capsules do not carry a standing identity preamble, and
file/search/email/social text is marked as data.

The storage side now favors redundant, inspectable read views over additional
query-time reasoning. Nightly maintenance copies exact input and output records
into chronological, session, subject, topic, and relation Markdown logs. Every
copy carries the same canonical memory ID; folder routing unions candidates and
deduplicates that ID set before top-K. Source-linked summaries provide an
overture and key details without replacing the exact logs or journal.

This stage validates prompt construction and truth boundaries. It does not yet
replace the focus-task executor, and local Ollama remains unable to run active
task cognition under the current provider rules. The next comparison should
therefore score both response quality and task completion, report capsule
contents, and distinguish retrieval failure from missing action execution.

## Natural-dialogue diagnostic protocol

Long-dialogue retries use a fixed conversation and question slice. Retrieval
recall is computed from exact event IDs parsed from the context actually sent
to the answering model. The harness no longer performs a second stateful
unified retrieval and calls that diagnostic result “injected context.” Direct
contextual, semantic, and spatial searches remain separate diagnostics.

Between-session maintenance is evaluated as a reusable workflow rather than a
test-key patch: typed entity roles prevent vocatives from becoming facts,
workers must return source IDs, malformed output is surfaced, and person
profiles are case-local. Question-time intake generates the same subject,
facet, exactness, chronology, and relational work order for arbitrary runtime
messages and benchmark probes.
