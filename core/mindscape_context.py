"""Helix's presentation of native Loom packets, with conditional source labels.

Import after activating the configured MightyMem package. Native lanes and
trust rules stay in ContextCompiler. Helix supplies typed recollections and
focus preferences to whole-item admission. _render counts the actual packet.
"""
from dataclasses import replace
from collections import defaultdict, deque
import hashlib
import re
from context_loom.compiler import ContextCompiler
from context_loom.models import Candidate
from core.context_focus import infer_focus, resolve_profiles
from core.pulse_context import PulseContext, SECTION_TITLES, PULSE_SECTION_ORDER


class ContextItemBudgetExceeded(ValueError):
    """Required current experience cannot fit the configured attention budget."""


class MindscapeContextCompiler(ContextCompiler):
    _pulse_context = None
    optional_selection_policy = "independent memory-role streams; focus-weighted space allocation; no cross-module relevance score"
    optional_admission_reason = "selected within a memory role and producer; fits shared physical context"

    def __init__(self, *args, focus_profiles=None, item_limit=None, **kwargs):
        if not hasattr(ContextCompiler, "_order_optional_candidates") or not hasattr(ContextCompiler, "_candidate_admitted"):
            raise RuntimeError("Configured MightyMem compiler lacks role-composition hooks")
        super().__init__(*args, **kwargs)
        self.focus_profiles = resolve_profiles(focus_profiles)
        self._supplied_candidates = {}
        self._covered_source_hashes = set()
        self.canonical_roles = {}
        if item_limit is not None and (type(item_limit) is not int or item_limit < 1):
            raise ValueError("context_item_limit must be a positive integer or null")
        self.item_limit = item_limit

    def _optional(self, item):
        if self.item_limit is not None:
            return item.section not in {"thinking", "messages", "tool_observations", "task"}
        return item.section in {
            "recalled_thought", "personal", "associations", "recalled", "prior_user",
            "prior_assistant", "observations", "procedures", "summary", "topical",
            "environment", "module",
        }

    def _merge_nominations(self, nominations):
        candidates = super()._merge_nominations(nominations)
        if self._pulse_context is None:
            return candidates
        from context_loom.retrieval import section_for
        for candidate in candidates.values():
            roles = set()
            for rid in candidate.source_record_ids:
                record = self.store.get_record(rid)
                if record is not None:
                    role = getattr(self, "canonical_roles", {}).get(rid) or record.metadata.get("context_role")
                    roles.add(role or next(iter(self._present_sections({section_for(record): [candidate.text]}))))
            # Native Candidate.merge can choose a section by comparing scores
            # from different lanes. Here record type owns the role instead.
            if roles:
                candidate.section = next(iter(roles)) if len(roles) == 1 else "associations"
        # Supply whole Helix recollections for the same physical admission
        # boundary as Loom. Never compare mRAG's raw similarity with Loom's.
        # Each producer's existing order is retained as a rank preference.
        ranks = {}
        for item in self._pulse_context.selected()[0] if self._pulse_context else ():
            if not self._optional(item):
                continue
            key = (item.section, item.text)
            cid = "helix_context:" + hashlib.sha256(repr(key).encode()).hexdigest()
            if cid in self._supplied_candidates:
                self._supplied_candidates[cid].append(item)
                continue
            self._supplied_candidates[cid] = [item]
            ranks[item.producer] = ranks.get(item.producer, 0) + 1
            candidates[cid] = Candidate(
                id=cid, text=item.text, section=item.section, source_record_ids=(),
                metadata={"helix_context": True, "producer": item.producer,
                          "source_ids": list(item.source_ids), "producer_rank": ranks[item.producer]},
            )
        return candidates

    def _utility(self, candidate):
        if self._pulse_context is None:
            return super()._utility(candidate)
        # No scalar makes subjective familiarity, factual relevance and
        # procedural support interchangeable. Per-lane ranks remain in receipts.
        return 0.0

    def _order_optional_candidates(self, candidates):
        if self._pulse_context is None:
            yield from super()._order_optional_candidates(candidates)
            return
        if self.config.minimum_utility is not None:
            raise ValueError("A global utility threshold is incompatible with independent memory roles")
        streams = defaultdict(list)
        for candidate in candidates:
            role = next(iter(self._present_sections({candidate.section: [candidate.text]})))
            if candidate.id in self._supplied_candidates:
                streams[(role, candidate.metadata["producer"])].append(
                    (candidate.metadata["producer_rank"], candidate))
            else:
                for lane, rank in candidate.lane_ranks.items():
                    streams[(role, lane)].append((rank, candidate))
                if not candidate.lane_ranks:
                    streams[(role, "native")].append((1, candidate))
        queues = {key: deque(c for _, c in sorted(values, key=lambda item: (item[0], item[1].id)))
                  for key, values in streams.items()}
        offered = set()
        while queues:
            for key in list(queues):
                while queues[key] and queues[key][0].id in offered:
                    queues[key].popleft()
                if not queues[key]:
                    del queues[key]
            if not queues:
                break
            roles = {role for role, _ in queues}
            priorities = {role: self._pulse_context.focus.priority(role, self.focus_profiles) for role in roles}
            role = min(roles, key=lambda r: (self._role_usage[r] / priorities[r], -priorities[r], r))
            stream = min((key for key in queues if key[0] == role),
                         key=lambda key: (self._producer_usage[key], key[1]))
            candidate = queues[stream].popleft()
            offered.add(candidate.id)
            self._offered_roles[candidate.id] = stream
            if self.item_limit is not None and self._used_items + self._item_cost(candidate) > self.item_limit:
                self._item_deferred.append({
                    "candidate_id": candidate.id, "source_ids": list(dict.fromkeys([
                        *candidate.source_record_ids,
                        *(source for item in self._supplied_candidates.get(candidate.id, ()) for source in item.source_ids)])),
                    "section": candidate.section, "text": candidate.text,
                    "item_cost": self._item_cost(candidate), "admitted": False,
                    "reason": "pulse item budget; retained in source memory for later retrieval"})
                continue
            # The native compiler checks the complete rendering and calls the
            # admission observer only if this whole contribution actually fits.
            yield candidate

    def _candidate_admitted(self, candidate, added_tokens):
        if self._pulse_context is not None:
            cost = self._item_cost(candidate)
            if self.item_limit is not None and self._used_items + cost > self.item_limit:
                raise ContextItemBudgetExceeded(
                    f"Required current experience needs {self._used_items + cost} items; "
                    f"mindscape.context_item_limit is {self.item_limit}; no partial pulse was returned")
            self._used_items += cost
        stream = self._offered_roles.get(candidate.id) if self._pulse_context else None
        if stream is not None:
            self._role_usage[stream[0]] += added_tokens
            self._producer_usage[stream] += added_tokens

    def _item_cost(self, candidate):
        if candidate.id in self._supplied_candidates:
            return len(self._supplied_candidates[candidate.id])
        # A grouped graph nomination cannot hide multiple source records in a
        # single slot. Metadata and headings alone do not constitute new items.
        return max(1, len(set(candidate.source_record_ids)))

    def _assembled(self, sections):
        if self._pulse_context is None:
            raise RuntimeError("No pulse under compilation")
        retained = [item for item in self._pulse_context.contributions if not self._optional(item)]
        presented = {}
        supplied_by_key = {
            (items[0].section, items[0].text): items
            for items in self._supplied_candidates.values()
        }
        for section, values in sections.items():
            for text in values:
                supplied = supplied_by_key.get((section, text))
                if supplied:
                    retained.extend(supplied)
                else:
                    presented.setdefault(section, []).append(text)
        return replace(self._pulse_context, contributions=tuple(retained)), self._present_sections(presented)

    def compile_pulse(self, context: PulseContext, *, scope="helix", input_allowance=None, covered_source_hashes=()):
        """Keep fresh search text separate from every retrieved contribution.

        The native compiler counts the complete assembly on each admission.
        Its immutable packet includes the exact rendering; the additional
        receipt accounts for sources supplied by Helix outside Loom's lanes.
        This method runs only on Mindscape's owning worker thread.
        """
        if self._pulse_context is not None:
            raise RuntimeError("Cannot overlap pulse context compilations")
        self._pulse_context = replace(context, focus=context.focus or infer_focus(context.query, context.query_source))
        self._supplied_candidates = {}
        self._covered_source_hashes = set(covered_source_hashes)
        self._role_usage = defaultdict(int)
        self._producer_usage = defaultdict(int)
        self._offered_roles = {}
        self._item_deferred = []
        # One fixed identity item in the lean system prompt; all other
        # information is admitted here, including recalled dialogue/beliefs.
        self._used_items = 1 + len([item for item in context.selected()[0] if not self._optional(item)])
        self.last_assembly_receipt = None
        original_config = self.config
        try:
            if self.item_limit is not None and self._used_items > self.item_limit:
                raise ContextItemBudgetExceeded(
                    f"Required current experience needs {self._used_items} items including identity; "
                    f"mindscape.context_item_limit is {self.item_limit}; no input or thought was clipped")
            if input_allowance is not None:
                if input_allowance <= 0:
                    raise ValueError("No physical provider context remains for this pulse")
                self.config = replace(self.config, model_context_tokens=min(
                    self.config.model_context_tokens, input_allowance + self.config.reserved_output_tokens))
            packet = self.compile(context.query, scope=scope, mode="pulse")
            assembled, additional = self._assembled(packet.sections)
            sections = assembled.grouped(additional)
            self.last_assembly_receipt = {
                **assembled.receipt(), "loom_packet_id": packet.id,
                "duplicates": context.selected()[1],
                "sections": sections,
                "presentation_order": [key for key in PULSE_SECTION_ORDER if sections.get(key)],
                "item_budget": {"limit": self.item_limit,
                                "admitted": self._used_items if self.item_limit is not None else None,
                                "fixed_identity_items": 1 if self.item_limit is not None else None,
                                "reason": "user-requested cognitive breadth across pulses, independent of token size",
                                "overflow": "explicit failure if required current experience cannot fit",
                                "deferred": self._item_deferred},
                "policy": self.optional_selection_policy,
                "admitted_role_tokens": dict(self._role_usage),
                "admitted_producer_tokens": {f"{role}/{producer}": tokens for (role, producer), tokens
                                             in self._producer_usage.items()},
                "attention": self._pulse_context.focus.receipt(self.focus_profiles),
                "supplied_admission": [
                    {"candidate_id": entry.candidate_id, "admitted": entry.admitted,
                     "reason": entry.reason,
                     "sources": [item.receipt() for item in self._supplied_candidates[entry.candidate_id]]}
                    for entry in packet.manifest if entry.candidate_id in self._supplied_candidates
                ] + [{**entry, "sources": [item.receipt() for item in self._supplied_candidates[entry["candidate_id"]]]}
                     for entry in self._item_deferred if entry["candidate_id"] in self._supplied_candidates],
                "section_tokens": {key: self.token_counter.count(
                    f"[{SECTION_TITLES[key]}]\n" + "\n".join(values)) for key, values in sections.items()},
                "packet_tokens": packet.token_count,
                "input_token_boundary": packet.max_input_tokens,
                "token_counter": type(self.token_counter).__name__,
                "token_accounting": "section counts are standalone; packet uses installed model tokens; allowance excludes provider system/history/template",
                "private_policy": "cognitive context only, never evidence of external action",
            }
            return packet
        finally:
            self.config = original_config
            self._pulse_context = None
            self._supplied_candidates = {}
            self._covered_source_hashes = set()

    def _trust_allowed(self, candidate):
        if self._pulse_context is not None:
            if candidate.section == "prior_assistant" and self.item_limit is None:
                request = "\n".join(item.text for item in self._pulse_context.contributions
                                    if item.section in {"messages", "task"}) or self._pulse_context.query
                requested = re.search(
                    r"\b(?:you|we)\b.*\b(?:say|said|told|wrote|discussed|answered|suggested|recommended)\b"
                    r"|\bwhat\s+(?:was|had\s+been)\s+(?:said|written|discussed|suggested|recommended)\b"
                    r"|\b(?:previous|earlier|past|last|your)\s+(?:answer|reply|response|suggestion|statement)\b"
                    r"|\bquote\b|\bmem_\w+\b", request, re.I | re.S)
                if not requested:
                    return False, "earlier model statements are not requested; actual dialogue remains in provider history"
            if candidate.id in self._supplied_candidates:
                if any(item.kind in {"inbound_message", "outbound_message"}
                       and item.source_content_sha256 in self._covered_source_hashes
                       for item in self._supplied_candidates[candidate.id]):
                    return False, "identical source content is already present in actual provider dialogue"
                return True, "Helix recollection retains its original evidence label; admission does not verify it"
            supplied = {
                (source, item.source_content_sha256)
                for item in self._pulse_context.selected()[0]
                for source in item.source_ids if item.source_content_sha256
            }
            for rid in candidate.source_record_ids:
                record = self.store.get_record(rid)
                if (record and record.kind in {"user", "assistant"}
                        and record.metadata.get("source_sha256") in self._covered_source_hashes):
                    return False, "identical dialogue source is already present in the provider history"
                if record and (record.metadata.get("helix_source_id"),
                               record.metadata.get("source_sha256")) in supplied:
                    return False, "same canonical source and content supplied by Helix context; see assembly receipt"
            if candidate.metadata.get("kind") == "thought":
                candidate.section = "recalled_thought"
                return True, "private thought admitted only as cognitive context, not external evidence"
        # The native trust rule calls labeled assistant history "continuity".
        # Preserve that rule while our renderer uses the explicit role name.
        trusted_view = replace(candidate, section="continuity") if candidate.section == "prior_assistant" else candidate
        return super()._trust_allowed(trusted_view)

    @staticmethod
    def _present_sections(sections):
        mapping = {"evidence": "recalled", "multi_hop": "associations",
                   "continuity": "recalled", "private": "recalled_thought"}
        presented = {}
        for native_key, values in sections.items():
            for value in values:
                key = mapping.get(native_key, native_key)
                if native_key == "continuity":
                    if value.startswith("- Earlier assistant statement (unverified):"):
                        key = "prior_assistant"
                    elif value.startswith("- Conversation:"):
                        key = "prior_user"
                presented.setdefault(key, []).append(value)
        return presented

    SECTION_TITLES = {
        **ContextCompiler.SECTION_TITLES,
        "environment": "In my digital workspace (filesystem):",
        "module": "The operational module in my focus:",
        "work": "What I am working on:",
        "evidence": "I remember (direct evidence):",
        "multi_hop": "I associate (related memories):",
        "topical": "My topic orientation:",
        "summary": "A summary I recall:",
        "personal": "I prefer / value:",
        "procedures": "Procedures I recall:",
        "observations": "I observed / read:",
        "continuity": "What was previously discussed:",
        "prior_assistant": "I previously said:",
        "prior_user": "What was said to me before:",
        "recalled": "I remember:",
        "recalled_thought": "I was thinking:",
        "thinking": "What I am thinking now:",
        "state": "I feel:",
        "senses": "I sense now (live hardware):",
        "task": "I want to:",
    }
    SECTION_ORDER = ContextCompiler.SECTION_ORDER + ("observations", "prior_user", "prior_assistant", "environment", "module")

    def _render(self, *, mode, sections, capabilities, current_input):
        if self._pulse_context is not None:
            # Preserve the native mode/capability/response contract. Render all
            # populated sources together, instead of nesting an already
            # retrieved packet inside the next retriever's current input.
            wrapper = super()._render(mode=mode, sections={}, capabilities=capabilities,
                                      current_input="")
            suffix = "[CURRENT INPUT]\n"
            if not wrapper.endswith(suffix):
                raise RuntimeError("Loom input wrapper changed; review Helix context rendering")
            assembled, additional = self._assembled(sections)
            return wrapper[:-len(suffix)] + assembled.render(additional)

        # Native render_record supplies these prefixes from record kinds, not
        # from substring matches in their bodies. Retain each complete entry,
        # including source IDs, evidence status, timestamps and version labels.
        presented = {key: list(values) for key, values in sections.items()}
        presented["continuity"] = []
        for value in sections.get("continuity", ()):
            if value.startswith("- Earlier assistant statement (unverified):"):
                key = "prior_assistant"
            elif value.startswith("- Conversation:"):
                key = "prior_user"
            else:
                key = "continuity"
            presented.setdefault(key, []).append(value)

        # Keep native mode/capability/response-contract rendering. Supply an
        # empty input to replace only its final wrapper, never user content.
        rendered = super()._render(
            mode=mode, sections=presented, capabilities=capabilities, current_input=""
        )
        suffix = "[CURRENT INPUT]\n"
        if not rendered.endswith(suffix):
            raise RuntimeError("Loom input wrapper changed; review Helix context rendering")
        return rendered[:-len(suffix)] + "[This pulse]\n" + current_input
