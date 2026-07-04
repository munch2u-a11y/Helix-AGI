# Preconscious Audit

**Scope:** `core/preconscious.py`

## Runtime role

- `Preconscious` assembles the per-pulse first-person annotations and somatic/affect ambient notes that get woven directly into the event stream of the pulse. The live pipeline combines Layer 2 lexicon matches, spatial neighborhood recall, gravity-ranked beliefs, recent memory, scratchpad state, contact context, somatic state, affect state, ambient spatial cues, and trail flashes. `core/preconscious.py:312-481`
- The module docstring outlines the general design, but the live code also handles Hebbian plasticity nudges, local model reflection, and writes dashboard-side JSON state on every injection. `core/preconscious.py:1-25` (docstring), `core/preconscious.py:747-802` (`_reflect_on_cluster`), `core/preconscious.py:2002-2099` (`_save_injection_state`)

## Construction and cached state

- The constructor stores references to memory, beliefs, physics, scratchpad, channel router, and sentinel; shares the pulse loop's active toolset set; initializes rolling tool history and repetition/cooldown guards; loads Layer 2 anchors; and builds the lexicon search helper. `core/preconscious.py:83-180`
- Belief retrieval is cached in `_belief_cache`, `_belief_emb_matrix`, and `_galaxy_map`; those structures are rebuilt when belief count or total mass changes. `core/preconscious.py:97-128`, `core/preconscious.py:990-1168`

## Layer 2 anchors

- `_load_layer2_anchors()` reads `people`, `concepts`, `skills`, and `desires` from the belief store and indexes each `term` plus aliases for case-insensitive lookup. `core/preconscious.py:188-232`
- `_pull_lexicon_matches()` performs boundary-aware regex matching against the trigger text, formats entity facets up to `LEXICON_FACETS_PER_TERM`, and adds matched IDs to the blacklist so they do not immediately repeat. `core/preconscious.py:485-560`
- `reset_lexicon_blacklist()` is the reset point used after context compression or explicit session reset. `core/preconscious.py:561-572`, `core/pulse_loop.py:291-304`, `core/pulse_loop.py:673-731`

## Focus budget and tool-aware narrowing

- `record_tool_usage()` stores the last five pulses of tool-call names. `core/preconscious.py:236-247`
- `_compute_focus_budget()` inspects the last three pulses, uses `tools.tool_registry` focus metadata when available, and then narrows or widens the belief budget again using the sentinel's temperature `_spatial_T` value. `core/preconscious.py:248-310`
- The current focus tiers are `FOCUS_BUDGET_DEEP=(1, 1)`, `FOCUS_BUDGET_WORKING=(2, 1)`, and `FOCUS_BUDGET_OPEN=(3, 2)` where each tuple is `(total_budget, max_skills)`. `core/preconscious.py:78-80`

## Injection pipeline

- `inject()` builds the combined trigger from incoming events plus the previous thought, falling back to tool-result text only when there is no other context. `core/preconscious.py:312-329`
- The assembly order is: lexicon anchors, spatial neighborhood, toolset hints, belief grounding, recent memory, scratchpad summary, optional contact context, somatic state, affect state, ambient spatial cues, and trail flashes. `core/preconscious.py:330-464`
- The method returns four values: annotations (list of strings), ambient (somatic + affect + spatial status string), surfaced belief IDs, and the weighted centroid of the selected belief clusters for spatial steering. `core/preconscious.py:319-320`, `core/preconscious.py:477-481`

## Spatial neighborhood path

- `_compute_dynamic_k()` uses the number of active gravity-field anchors as a density proxy and scales the neighborhood size between `NEIGHBORHOOD_K_MIN` and `NEIGHBORHOOD_K_MAX`. `core/preconscious.py:805-828`
- `_pull_spatial_neighborhood()` delegates to `PhysicsEngine.query_neighborhood(..., exclude_trails=True)`, labels memories as `vivid recall`, `related`, or `faint` by relevance score, and pulls a short temporal chain for strong matches. `core/preconscious.py:829-943`, `core/physics_engine.py:317-392`, `core/physics_engine.py:393-420`
- If the retrieved cluster is dense enough, `_reflect_on_cluster()` sends a short synthesis prompt to a local Ollama endpoint at `http://localhost:11434/api/generate`. `core/preconscious.py:747-802`

## Belief retrieval path

- `_ensure_belief_cache()` builds two parallel caches: an 8D belief-position cache and a belief-only 384D matrix derived from the live `SemanticIndex` plus any just-added beliefs that have to be embedded on the fly. `core/preconscious.py:990-1168`
- `_gravity_query()` is two-stage: it first narrows candidates with 384D cosine search over the cached belief matrix, then re-ranks those candidates by `temperature * mass / distance^2` inside the live belief space. `core/preconscious.py:1174-1426`
- `_pull_relevant_beliefs()` extracts 1..N concepts from the trigger text, runs one gravity query per concept, de-duplicates overlapping beliefs, computes a weighted centroid, performs Hebbian plasticity nudging, and formats the final lines. `core/preconscious.py:1608-1907`
- Tool-result-only fallback queries are deliberately damped by multiplying their belief gravity by `0.1`. `core/preconscious.py:1680-1685`, `core/preconscious.py:1720-1725`

## Other injected signals

- `_pull_somatic_state()` formats sentinel omega, total instability, entropy, severity-derived label, and generation mode. `core/preconscious.py:575-605`
- `_pull_affect_state()` reads the latest `InterferenceResult` from the affect hook, injects dominant affect and novelty, and resolves surfaced memory IDs back to short text. `core/preconscious.py:606-657`, `core/preconscious.py:658-686`
- `_toolset_awareness()` scans the neighborhood text for keywords associated with available-but-disabled toolsets, including short names whitelisted in `SHORT_TOOL_WHITELIST`. `core/preconscious.py:64-67`, `core/preconscious.py:687-746`
- `_pull_recent_memory()` uses `MemoryManager.get_recent(limit=3, pulses_back=CHAIN_WINDOW)` and condenses each entry for continuity. `core/preconscious.py:1911-1953`
- `_pull_contact_context()` surfaces the default channel and last-contact time when a known contact name appears in the trigger. `core/preconscious.py:1957-1969`

## Side effects

- `_save_injection_state()` writes `data/spatial/spatial_injection.json` plus a rolling history file, including concepts, surfaced memories, surfaced beliefs, somatic data, affect data, and the trigger preview. `core/preconscious.py:2002-2099`
- Because the injection state is written on every call to `inject()`, this module is not purely read-only even when it is only preparing prompt context. `core/preconscious.py:477`, `core/preconscious.py:2002-2099`

