# Preconscious Audit

**Scope:** `core/preconscious.py`

## Runtime role

- `Preconscious` assembles the per-pulse `<spatial-awareness>` block that is injected into the pulse message. The live pipeline combines Layer 2 lexicon anchors, spatial neighborhood recall, gravity-ranked beliefs, recent memory, scratchpad state, contact context, somatic state, affect state, and ambient spatial cues. `core/preconscious.py:260-426`
- The module header comment is older than the implementation. The live code does more than concept extraction and can also make a local HTTP call to Ollama for cluster reflection and write dashboard-side JSON state on every injection. `core/preconscious.py:1-26`, `core/preconscious.py:678-732`, `core/preconscious.py:1545-1640`

## Construction and cached state

- The constructor stores references to memory, beliefs, physics, scratchpad, channel router, and sentinel; shares the pulse loop's active toolset set; initializes rolling tool history and belief-repetition guards; loads Layer 2 anchors; and builds the `ConceptExtractor` from those lexicon keys. `core/preconscious.py:75-140`
- Belief retrieval is cached in `_belief_cache`, `_belief_emb_matrix`, and `_galaxy_map`; those structures are refreshed when belief count or total mass changes. `core/preconscious.py:97-128`, `core/preconscious.py:859-1007`

## Layer 2 anchors

- `_load_layer2_anchors()` reads `people`, `concepts`, `skills`, and `desires` from the belief store and indexes each `term` plus aliases for case-insensitive lookup. `core/preconscious.py:142-180`
- `_pull_lexicon_matches()` performs boundary-aware regex matching against the trigger text, injects summaries before any 8D query, and adds matched IDs to `_lexicon_blacklist` so they do not immediately repeat. `core/preconscious.py:430-478`
- `reset_lexicon_blacklist()` is the reset point used after context compression or explicit session reset. `core/preconscious.py:480-490`, `core/pulse_loop.py:296`, `core/pulse_loop.py:737-739`

## Focus budget and tool-aware narrowing

- `record_tool_usage()` stores the last five pulses of tool-call names. `core/preconscious.py:184-195`
- `_compute_focus_budget()` inspects the last three pulses, uses `tools.tool_registry` focus metadata when available, and then narrows or widens the belief budget again using the sentinel's `_spatial_T` value. `core/preconscious.py:196-256`
- The current focus tiers are `DEEP=(2,2)`, `WORKING=(5,2)`, and `OPEN=(10,3)` where each tuple is `(total_budget, max_skills)`. `core/preconscious.py:69-73`

## Injection pipeline

- `inject()` builds the combined trigger from non-tool events plus the previous thought, falling back to tool-result text only when there is no other context. `core/preconscious.py:301-325`
- The assembly order is: lexicon anchors, spatial neighborhood, toolset hint, belief grounding, recent memory, scratchpad summary, optional contact context, somatic state, affect state, ambient spatial cues, and trail flashes. `core/preconscious.py:326-409`
- The method returns three values: the fenced context string, surfaced belief IDs, and the weighted centroid of the selected belief clusters for spatial steering. `core/preconscious.py:420-426`

## Spatial neighborhood path

- `_compute_dynamic_k()` uses the number of active gravity-field anchors as a density proxy and scales the neighborhood size between `NEIGHBORHOOD_K_MIN` and `NEIGHBORHOOD_K_MAX`. `core/preconscious.py:736-759`
- `_pull_spatial_neighborhood()` delegates to `PhysicsEngine.query_neighborhood(..., exclude_trails=True)`, labels memories as `vivid recall`, `related`, or `faint` by relevance score, and pulls a short temporal chain for strong matches. `core/preconscious.py:761-857`, `core/physics_engine.py:269-345`, `core/physics_engine.py:346-373`
- If the retrieved cluster is dense enough, `_reflect_on_cluster()` sends a short synthesis prompt to a local Ollama endpoint at `http://localhost:11434/api/generate`. `core/preconscious.py:675-732`

## Belief retrieval path

- `_ensure_belief_cache()` builds two parallel caches: an 8D belief-position cache and a belief-only 384D matrix derived from the live `SemanticIndex` plus any just-added beliefs that have to be embedded on the fly. `core/preconscious.py:859-1007`
- `_gravity_query()` is two-stage: it first narrows candidates with 384D cosine search over the cached belief matrix, then re-ranks those candidates by `temperature * mass / distance^2` inside the live belief space. `core/preconscious.py:1012-1156`
- `_pull_relevant_beliefs()` extracts 1..N concepts from the trigger text, runs one gravity query per concept, de-duplicates overlapping beliefs, optionally groups them by galaxy center, reserves skill slots, updates access counts for selected beliefs, computes a weighted centroid, and formats the final lines by belief category. `core/preconscious.py:1195-1459`
- Tool-result-only fallback queries are deliberately damped by multiplying their belief gravity by `0.1`. `core/preconscious.py:1249-1255`, `core/preconscious.py:1289-1293`

## Other injected signals

- `_pull_somatic_state()` formats sentinel omega, total instability, entropy, severity-derived label, and generation mode. `core/preconscious.py:494-537`
- `_pull_affect_state()` reads the latest `InterferenceResult` from `core.affect_hook`, injects dominant affect and novelty, and resolves surfaced memory IDs back to short text through the belief store or journal. `core/preconscious.py:541-618`, `core/affect_hook.py:111-158`
- `_toolset_awareness()` scans the neighborhood text for keywords associated with available-but-disabled toolsets, including short whitelisted names such as `git`, `ssh`, `npm`, and `api`. `core/preconscious.py:61-63`, `core/preconscious.py:622-671`
- `_pull_recent_memory()` uses `MemoryManager.get_recent(limit=3, minutes_back=10)` and condenses each entry for continuity. `_pull_contact_context()` surfaces the default channel and last-contact time when a known contact name appears in the trigger. `core/preconscious.py:1463-1512`

## Side effects

- `_save_injection_state()` writes `data/spatial/spatial_injection.json` plus a rolling history file, including concepts, surfaced memories, surfaced beliefs, somatic data, affect data, and the trigger preview. `core/preconscious.py:1545-1640`
- Because the injection state is written on every call to `inject()`, this module is not purely read-only even when it is only preparing prompt context. `core/preconscious.py:411-416`, `core/preconscious.py:1545-1640`
