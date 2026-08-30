from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
THINK = ROOT / "ui" / "static" / "js" / "think-citations.js"
WORKER = ROOT / "ui" / "static" / "js" / "think-rule-worker.js"
MEMORY_VIEW = ROOT / "ui" / "static" / "js" / "runtime" / "runtime-memory-view.js"
AVATAR = ROOT / "ui" / "static" / "js" / "runtime" / "runtime-avatar.js"
RUNTIME = ROOT / "ui" / "static" / "js" / "runtime" / "runtime.js"
INDEX = ROOT / "ui" / "templates" / "index.html"


class ActiveMemoryCitationMultiSourceClientContractTests(unittest.TestCase):
    def test_active_memory_fast_match_uses_id_key_title_and_value_anchors(self):
        source = THINK.read_text(encoding="utf-8")

        self.assertIn("function parseActiveMemoryCitationRecord(record, index)", source)
        self.assertIn("metadata.get(\"conditions\") || visibleValue", source)
        self.assertIn("metadata.get(\"title\") || \"\"", source)
        self.assertIn("`Active memory #${slotNumber}`", source)
        self.assertIn("add(activeMemoryId, base, true);", source)
        self.assertIn("includeKeyAlias", source)
        self.assertIn("buildActiveMemoryValueAnchors(record.conditions)", source)
        self.assertIn("ACTIVE_MEMORY_VALUE_MIN_RATIO = 0.25", source)
        self.assertIn("customMetadataAliases", source)
        self.assertIn("`active_memory[${slotNumber}]`", source)

    def test_active_memory_key_aliases_do_not_cancel_against_runtime_mirrors(self):
        source = THINK.read_text(encoding="utf-8")

        self.assertIn("getFastCitationTargetIdentity", source)
        self.assertIn("Mirrored runtime/active copies", source)
        self.assertIn("/^active_memory(?:_\\d+)?$/i.test(key)", source)
        self.assertIn("fastCitationSourcePriority", source)

    def test_active_value_final_match_is_exact_contiguous_and_off_main_thread(self):
        source = THINK.read_text(encoding="utf-8")
        worker = WORKER.read_text(encoding="utf-8")

        self.assertIn("activeContiguousRatio: ACTIVE_MEMORY_VALUE_MIN_RATIO", source)
        self.assertIn("function findActiveMemoryContiguousMatches(", worker)
        self.assertIn("Math.ceil(sourceTokens.length * ratio)", worker)
        self.assertIn('fragment.sourceType === "active"', worker)
        self.assertIn("worker.postMessage(", source)

    def test_active_memory_citation_state_is_stable_id_based_and_live_revoked(self):
        source = THINK.read_text(encoding="utf-8")
        runtime = RUNTIME.read_text(encoding="utf-8")
        memory_view = MEMORY_VIEW.read_text(encoding="utf-8")
        avatar = AVATAR.read_text(encoding="utf-8")

        self.assertIn('"jin:active-memory-records-changed"', source)
        self.assertIn('"jin:active-memory-records-changed"', runtime)
        self.assertIn("filterLiveActiveMemoryMatches", source)
        self.assertIn("activeMemoryIds: [...state.activeMemoryIds]", source)
        self.assertIn("activeMemoryKeys: [...state.activeMemoryKeys]", source)
        self.assertIn("activeIdentities.activeMemoryIds.has(activeMemoryId)", memory_view)
        self.assertIn("activeIdentities.activeMemoryKeys.has(lineKey)", memory_view)
        self.assertIn("activeIdentities.activeMemoryIds.has(activeMemoryId)", avatar)
        self.assertIn("activeIdentities.activeMemoryKeys.has(lineKey)", avatar)
        self.assertIn('"data-active-memory-id": options.activeMemoryId || null', avatar)


    def test_final_reasoning_backfills_exact_active_references(self):
        source = THINK.read_text(encoding="utf-8")

        self.assertIn("function findFastExactCitationMatches(", source)
        self.assertIn("function mergeFastCitationMatches(", source)
        self.assertIn("const finalFastMatches =", source)
        self.assertIn("allowTerminalBoundary: true", source)
        self.assertIn("activeMemoryCitationRevision += 1;", source)
        self.assertIn("stream.__jinFastCitationActiveRevision", source)

    def test_stream_rechecks_token_that_ended_on_previous_frame_boundary(self):
        source = THINK.read_text(encoding="utf-8")

        self.assertIn("|| end >= previousLength", source)
        self.assertIn("token that ended exactly at the previous frame boundary", source)

    def test_stream_redispatches_structured_state_when_new_ids_accumulate(self):
        source = THINK.read_text(encoding="utf-8")

        self.assertIn("function buildThinkRuntimeCitationHighlightSignature(state)", source)
        self.assertIn("__jinRuntimeCitationHighlightSignature", source)
        self.assertIn("const stateChanged =", source)
        self.assertIn("if (!activeChanged && !stateChanged)", source)
        self.assertIn("function buildFastCitationMatchesSignature(matches)", source)

    def test_active_memory_key_fallback_keeps_legacy_or_partial_records_citable(self):
        source = THINK.read_text(encoding="utf-8")

        self.assertIn("function normalizeActiveMemoryKey(value)", source)
        self.assertIn("active-key:${normalizedKey}", source)
        self.assertIn("function getCurrentActiveMemoryKeys()", source)
        self.assertIn("function getMatchActiveMemoryKey(match)", source)
        self.assertNotIn("if (!id) {\n      return null;", source)

    def test_avatar_collapses_runtime_active_mirrors_to_canonical_target(self):
        avatar = AVATAR.read_text(encoding="utf-8")

        self.assertIn("extractActiveMemoryId(value)", avatar)
        self.assertIn("orbitGroup.dataset.activeMemoryId", avatar)
        self.assertIn("function getAvatarMemoryReferenceTargetIdentity(node)", avatar)
        self.assertIn("targets.add(targetIdentity);", avatar)
        self.assertIn("canonicalActiveMemoryIds", avatar)
        self.assertIn("mirroredActiveRuntimeNode", avatar)

    def test_reference_boundaries_accept_sentence_punctuation_but_reject_joined_tokens(self):
        think = THINK.read_text(encoding="utf-8")
        memory_view = MEMORY_VIEW.read_text(encoding="utf-8")

        self.assertIn("function isFastCitationBoundaryBlocked(", think)
        self.assertIn("Sentence punctuation after an id", think)
        self.assertIn("function isMemoryReferenceBoundaryBlocked(", memory_view)
        self.assertIn('character === "." || character === "-"', memory_view)

    def test_client_cache_keys_include_active_citation_revision(self):
        source = INDEX.read_text(encoding="utf-8")

        self.assertIn("runtime-memory-view.js?v=context-card-chevronless-1&delayed-fact-paste=2&numeric-fact-order=1&amp;lt-fact-age=1&hold-delete-1&modal-title-editor=1&active-citations=4", source)
        self.assertIn("runtime-avatar.js?v=memory-layers-dormant-1&reasoning-whisper=3&stable-render=2&active-citations=4", source)
        self.assertIn("think-citations.js?v=think-citations-8&stream-exact-citations=4&active-citations=4", source)


if __name__ == "__main__":
    unittest.main()
