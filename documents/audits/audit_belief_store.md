# Belief Store Audit

**Scope:** `memory/belief_store.py`

## Runtime role

- `BeliefStore` acts as the persistent database layer for Helix's belief system. It manages categorized, structured files under three domains: core beliefs, propositions (including lessons), and entities (persons and profiles). `memory/belief_store.py:108-1420`
- It is journal-backed. Modifications are saved to Category JSON files and appended to the `CognitiveJournal` as historical log events. `memory/belief_store.py:167-204` (`_append_belief_snapshot`)
- When a `PhysicsEngine` is registered, the store forwards structural updates to synchronize positions on the 8D manifold and 384D index. `memory/belief_store.py:115-121` (`set_runtime`), `memory/belief_store.py:205-224` (`_sync_runtime`)

## Normalization and ID generation

- `_normalize_belief()` guarantees that all schema fields (such as `mass`, `confidence`, `stability_index`, `verifications`, and `tool_bindings`) are formatted and clamped. `memory/belief_store.py:122-166`
- `generate_id()` creates unique identifiers prefixed by category names (like `skills_123` or `prop_456`) and checks them for uniqueness against existing categories. `memory/belief_store.py:232-258`

## Category I/O operations

- Category operations are locked with Python standard locks to prevent thread contention during hooks or tool invocation. `memory/belief_store.py:267-287` (`_read_category`), `memory/belief_store.py:288-313` (`_write_category`)
- Storage files are saved in JSON format under the configured data directory (e.g. `data/beliefs_core.json`, `data/beliefs_propositions.json`, `data/beliefs_skills.json`, `data/beliefs_entities.json`). `memory/belief_store.py:259-266`

## Mutation path

- `add_belief()` normalizes fields, generates IDs, writes snapshots to the cognitive journal, syncs coordinates with runtime, and saves the updated category list. `memory/belief_store.py:314-411`
- `update_belief()` updates metadata in place (e.g. text content, parent IDs, or stability parameters) and reserializes category state. `memory/belief_store.py:529-573`
- Stability updates are routed through `update_stability_index()`, which triggers positive/negative delta checks, recalculates confidence boundaries, and resyncs spatial gravity mass. `memory/belief_store.py:472-514`

## Diagnostics, query, and merge operations

- `get_all_beliefs_flat()` returns a list of all active beliefs across all categories. `memory/belief_store.py:978-992`
- `get_beliefs_by_tool()` finds beliefs bound to a specific tool or toolset for the preconscious express lane. `memory/belief_store.py:574-599`
- `merge_beliefs()` merges near-duplicate nodes, remapping reliance references and recomputing compound cognitive mass. `memory/belief_store.py:776-871`
- `compute_cognitive_mass()` implements the structural equation combining baseline confidence with a logarithmic reliance factor:
  $$\text{mass} = \text{confidence} \times (1.0 + \log(1.0 + \text{relations\_count}))$$
  `memory/belief_store.py:1199-1228`
