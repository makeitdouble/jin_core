from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
AVATAR_JS = ROOT / "ui" / "static" / "js" / "runtime" / "runtime-avatar.js"
AVATAR_CSS = ROOT / "ui" / "static" / "css" / "runtime-avatar.css"
CHAT_JS = ROOT / "ui" / "static" / "js" / "chat.js"
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class RuntimeAvatarReasoningMotionClientContractTests(unittest.TestCase):

    def test_reasoning_stream_switches_avatar_motion_mode_at_visible_boundaries(self):
        source = CHAT_JS.read_text(encoding="utf-8")

        self.assertIn("function startStreamRuntimeAvatarReasoning(", source)
        self.assertIn("function stopStreamRuntimeAvatarReasoning(", source)
        self.assertIn("avatar.beginReasoning(\n      stream.messageId", source)
        self.assertIn("avatar.endReasoning(\n      stream.messageId", source)

        thinking_pos = source.index("stream.thinking += chunk;")
        thinking_start = source.rfind("startStreamRuntimeAvatarReasoning(", 0, thinking_pos)
        self.assertGreater(thinking_start, 0)

        answer_pos = source.index("stream.answer += chunk;")
        answer_stop = source.rfind("stopStreamRuntimeAvatarReasoning(", 0, answer_pos)
        self.assertGreater(answer_stop, thinking_pos)

        finish_start = source.index("function finishStreamMessage(")
        finish_end = source.index("window.normalizeJinLoopInput", finish_start)
        self.assertIn(
            "stopStreamRuntimeAvatarReasoning(\n      stream",
            source[finish_start:finish_end],
        )

    def test_repeated_snapshot_render_keeps_existing_avatar_svg(self):
        source = AVATAR_JS.read_text(encoding="utf-8")

        self.assertIn("function buildRuntimeRenderSignature(", source)
        self.assertIn("const runtimeGeometryUnchanged =", source)
        self.assertIn("runtimeSignature === lastRuntimeRenderSignature", source)
        self.assertIn("function syncAuxiliaryAvatarLayers(", source)
        self.assertIn("syncMemorySignalLayer(kind, { applyGlows: false })", source)

        render_start = source.index("function renderAvatar(snapshot, options = {})")
        render_end = source.index("function applyCenterColor(color)", render_start)
        render_body = source[render_start:render_end]
        guard_pos = render_body.index("if (runtimeGeometryUnchanged)")
        replace_pos = render_body.index("avatarRoot.replaceChildren(svg);")
        self.assertLess(guard_pos, replace_pos)
        self.assertIn("return;", render_body[guard_pos:replace_pos])

        repaint_start = source.index("function repaintAvatar()")
        repaint_end = source.index("function getLatestSnapshot()", repaint_start)
        self.assertIn("forceRebuild: true", source[repaint_start:repaint_end])

    def test_avatar_reasoning_mode_decelerates_to_a_full_stop_and_resumes_softly(self):
        source = AVATAR_JS.read_text(encoding="utf-8")

        self.assertIn('const REASONING_MOTION_CLASS = "is-reasoning";', source)
        self.assertIn("REASONING_ROTATION_STOP_MS = 1080", source)
        self.assertIn("REASONING_ROTATION_RESUME_MS = 1480", source)
        self.assertNotIn("REASONING_ROTATION_THINKING_RATE", source)
        self.assertNotIn("REASONING_ROTATION_SLOW_MS", source)
        self.assertIn("function rampAvatarRotationPlaybackRate(", source)
        self.assertIn("rampAvatarRotationPlaybackRate(\n      0,", source)
        self.assertIn("rampAvatarRotationPlaybackRate(\n      1,", source)
        self.assertIn("beginReasoning: beginReasoningMotion", source)
        self.assertIn("endReasoning: endReasoningMotion", source)
        self.assertIn("clearReasoning: clearReasoningMotion", source)

    def test_reasoning_rotation_rate_changes_preserve_visual_phase(self):
        source = AVATAR_JS.read_text(encoding="utf-8")

        rate_start = source.index("function setAnimationPlaybackRate(")
        rate_end = source.index("function getAvatarRotationAnimation(", rate_start)
        rate_body = source[rate_start:rate_end]

        self.assertIn('typeof animation.updatePlaybackRate === "function"', rate_body)
        self.assertIn("animation.updatePlaybackRate(nextRate);", rate_body)
        self.assertIn("animation.playbackRate = nextRate;", rate_body)

    def test_reasoning_rerender_preserves_in_flight_rotation_ramp(self):
        source = AVATAR_JS.read_text(encoding="utf-8")

        keep_start = source.index("function keepReasoningMotionApplied()")
        keep_end = source.index("function renderAvatar(", keep_start)
        keep_body = source[keep_start:keep_end]

        self.assertIn('avatarShell.classList.add(REASONING_MOTION_CLASS);', keep_body)
        self.assertNotIn("setAvatarRotationPlaybackRateImmediate", keep_body)
        self.assertNotIn("avatarRotationPlaybackRate = 0", keep_body)
        self.assertNotIn("function setAvatarRotationPlaybackRateImmediate(", source)

    def test_reasoning_motion_is_layered_inside_rotating_rings(self):
        source = AVATAR_JS.read_text(encoding="utf-8")

        self.assertIn("function createReasoningMotionLayer(", source)
        self.assertIn('class: "jin-avatar-reasoning-motion"', source)
        self.assertIn('class: "jin-avatar-reasoning-twitch"', source)
        self.assertIn("reasoningMotion.content.appendChild(orbitGroup);", source)
        self.assertIn("reasoningMotion.content.appendChild(dotGroup);", source)
        self.assertIn("scaffoldContent.appendChild(createSvgElement", source)
        self.assertIn("runReasoningUncertaintyMutation()", source)
        self.assertIn("temporaryRate = 0.76 + Math.random() * 0.54", source)
        self.assertIn("twitch.animate(", source)

    def test_reasoning_css_uses_depth_whisper_instead_of_a_second_rotation(self):
        source = AVATAR_CSS.read_text(encoding="utf-8")

        self.assertIn(
            ".jin-runtime-avatar-shell.is-reasoning-whispering .jin-avatar-reasoning-motion",
            source,
        )
        self.assertIn("@keyframes jin-avatar-reasoning-whisper", source)
        self.assertIn(
            "animation-delay: var(--jin-avatar-whisper-delay, 0.2s);",
            source,
        )
        self.assertIn("scaleX(var(--jin-avatar-whisper-front-x", source)
        self.assertIn("scaleY(var(--jin-avatar-whisper-back-y", source)
        self.assertIn("@keyframes jin-avatar-reasoning-core-whisper", source)
        self.assertIn(".jin-avatar-reasoning-motion,", source)


    def test_reasoning_whisper_starts_only_after_rotation_reaches_full_stop(self):
        source = AVATAR_JS.read_text(encoding="utf-8")
        css = AVATAR_CSS.read_text(encoding="utf-8")

        self.assertIn('const REASONING_WHISPER_CLASS = "is-reasoning-whispering";', source)
        self.assertIn("let reasoningWhisperActive = false;", source)
        self.assertNotIn("reasoningWhisperHandoffFrame", source)
        self.assertNotIn("function scheduleReasoningWhisperHandoff()", source)

        activate_start = source.index("function activateReasoningMotion()")
        activate_end = source.index("function deactivateReasoningMotion()", activate_start)
        activate_body = source[activate_start:activate_end]
        ramp_pos = activate_body.index("rampAvatarRotationPlaybackRate(")
        whisper_pos = activate_body.index("setReasoningWhisperActive(true);")
        mutation_pos = activate_body.index("scheduleReasoningUncertaintyMutation();")
        self.assertLess(ramp_pos, whisper_pos)
        self.assertLess(whisper_pos, mutation_pos)
        self.assertNotIn("scheduleReasoningWhisperHandoff();", activate_body)

        self.assertIn(
            ".jin-runtime-avatar-shell.is-reasoning-whispering .jin-avatar-reasoning-motion",
            css,
        )
        self.assertNotIn(
            ".jin-runtime-avatar-shell.is-reasoning .jin-avatar-reasoning-motion",
            css,
        )

    def test_reasoning_motion_survives_hidden_layer_recreation(self):
        source = AVATAR_JS.read_text(encoding="utf-8")

        self.assertIn("let avatarRotationPlaybackRate = 1;", source)
        self.assertIn("function syncAvatarRotationPlaybackRate()", source)
        self.assertIn("avatarRotationPlaybackRate =\n        startRate + (target - startRate) * eased;", source)

        show_start = source.index("function setMemoryLayersHidden(hidden)")
        show_end = source.index("function toggleMemoryLayers()", show_start)
        show_body = source[show_start:show_end]
        dormant_off = show_body.index("setMemoryLayersDormant(false);")
        rate_sync = show_body.index("syncAvatarRotationPlaybackRate();")
        hidden_toggle = show_body.index("avatarRoot.classList.toggle(")
        self.assertLess(dormant_off, rate_sync)
        self.assertLess(rate_sync, hidden_toggle)

    def test_avatar_rebuild_preserves_rotation_phase_during_reasoning(self):
        source = AVATAR_JS.read_text(encoding="utf-8")

        self.assertIn("function captureAvatarRotationPhases(", source)
        self.assertIn("function restoreAvatarRotationPhases(", source)
        self.assertIn('"data-avatar-rotation-key": `memory:${kind}`', source)
        self.assertIn('"data-avatar-rotation-key": "files"', source)
        self.assertIn('"data-avatar-rotation-key": rotationKey', source)

        render_start = source.index("function renderAvatar(snapshot, options = {})")
        render_end = source.index("function applyCenterColor(color)", render_start)
        render_body = source[render_start:render_end]
        capture_pos = render_body.index("captureAvatarRotationPhases()")
        replace_pos = render_body.index("avatarRoot.replaceChildren(svg);")
        restore_pos = render_body.index("restoreAvatarRotationPhases(previousRotationPhases);")
        rate_sync_pos = render_body.index("syncAvatarRotationPlaybackRate();", restore_pos)
        self.assertLess(capture_pos, replace_pos)
        self.assertLess(replace_pos, restore_pos)
        self.assertLess(restore_pos, rate_sync_pos)
        self.assertIn(
            "const shouldAnimate =\n      !reasoningMotionActive",
            render_body,
        )

        memory_start = source.index("function syncMemorySignalLayer(")
        memory_end = source.index("function setDelayedMemoryDashPinned(", memory_start)
        memory_body = source[memory_start:memory_end]
        self.assertIn("captureAvatarRotationPhase(previousRing)", memory_body)
        self.assertIn("restoreAvatarRotationPhase(", memory_body)

        files_start = source.index("function syncFilesState(")
        files_end = source.index("function appendMemorySignalRings(", files_start)
        files_body = source[files_start:files_end]
        self.assertIn("captureAvatarRotationPhase(", files_body)
        self.assertIn("restoreAvatarRotationPhase(", files_body)

    def test_runtime_markers_end_reasoning_before_visible_answer_text(self):
        chat_source = CHAT_JS.read_text(encoding="utf-8")
        action_source = (
            ROOT / "ui" / "static" / "js" / "socket" / "runtime-actions.js"
        ).read_text(encoding="utf-8")
        event_source = (
            ROOT / "ui" / "static" / "js" / "socket" / "event-handlers.js"
        ).read_text(encoding="utf-8")

        self.assertIn("function markStreamAnswerPhase(", chat_source)
        self.assertIn("window.markStreamAnswerPhase =", chat_source)
        self.assertIn("runtimeMessageId && window.markStreamAnswerPhase", action_source)

        chunk_start = event_source.index("function handleMessageChunk(")
        chunk_end = event_source.index("function handleMessageEnd(", chunk_start)
        chunk_body = event_source[chunk_start:chunk_end]
        boundary_pos = chunk_body.index("window.markStreamAnswerPhase(")
        filter_pos = chunk_body.index("filterDelayedMemoryContentFromChunk(")
        self.assertLess(boundary_pos, filter_pos)

    def test_reasoning_entry_ramp_is_frame_aligned_and_skips_noop_rate_updates(self):
        source = AVATAR_JS.read_text(encoding="utf-8")

        self.assertIn("const requestedAnimationPlaybackRates = new WeakMap();", source)
        self.assertIn("Math.abs(previousRate - nextRate) < 0.0005", source)
        self.assertIn("window.requestAnimationFrame(apply)", source)
        self.assertIn("window.cancelAnimationFrame(reasoningRotationRampTimer);", source)
        self.assertNotIn("reasoningRotationRampTimer = setInterval(apply, 24);", source)

    def test_reasoning_rotation_ramp_reuses_cached_animation_handles(self):
        source = AVATAR_JS.read_text(encoding="utf-8")

        self.assertIn("let avatarRotationAnimationsCache = null;", source)
        self.assertIn("function invalidateAvatarRotationAnimationsCache()", source)
        self.assertIn("avatarRotationAnimationsCache = animations;", source)
        self.assertIn("return avatarRotationAnimationsCache;", source)

        ramp_start = source.index("function rampAvatarRotationPlaybackRate(")
        ramp_end = source.index("function clearReasoningLayerSettleStyles()", ramp_start)
        ramp_body = source[ramp_start:ramp_end]
        self.assertIn("syncAvatarRotationPlaybackRate();", ramp_body)
        self.assertNotIn("querySelectorAll(", ramp_body)
        self.assertNotIn("getAnimations()", ramp_body)

        render_start = source.index("function renderAvatar(snapshot, options = {})")
        render_end = source.index("function applyCenterColor(color)", render_start)
        render_body = source[render_start:render_end]
        invalidate_pos = render_body.index("invalidateAvatarRotationAnimationsCache();")
        replace_pos = render_body.index("avatarRoot.replaceChildren(svg);")
        self.assertLess(invalidate_pos, replace_pos)

        dormant_start = source.index("function setMemoryLayersDormant(dormant)")
        dormant_end = source.index("function setMemoryLayersHidden(hidden)", dormant_start)
        dormant_body = source[dormant_start:dormant_end]
        self.assertIn("invalidateAvatarRotationAnimationsCache();", dormant_body)

    def test_reasoning_twitch_layer_is_precomposited_like_original_animation(self):
        source = AVATAR_CSS.read_text(encoding="utf-8")

        self.assertIn(
            ".jin-avatar-reasoning-twitch {\n    will-change: transform;",
            source,
        )
        self.assertIn(
            ".jin-runtime-avatar.is-memory-layers-dormant .jin-avatar-reasoning-twitch",
            source,
        )
        self.assertIn("will-change: auto !important;", source)

    def test_reasoning_settle_cleanup_is_a_noop_when_idle(self):
        source = AVATAR_JS.read_text(encoding="utf-8")

        self.assertIn("let reasoningLayerSettleActive = false;", source)
        self.assertIn(
            "if (!reasoningLayerSettleActive && !reasoningLayerSettleTimer)",
            source,
        )
        self.assertIn("reasoningLayerSettleActive = true;", source)

    def test_reasoning_motion_assets_are_cache_busted(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn("runtime-avatar.css?v=memory-layers-dormant-1&reasoning-whisper=3", source)
        self.assertIn("runtime-avatar.js?v=memory-layers-dormant-1&reasoning-whisper=3&stable-render=2", source)
        self.assertIn("avatar-reasoning-motion=2", source)
        self.assertIn("avatar-answer-boundary=1", source)
        self.assertIn("rotation-phase=2", source)
        self.assertIn("rotation-stop=2", source)
        self.assertIn("transition-precompose=1", source)
        self.assertIn("transition-ramp=2", source)
        self.assertIn("rotation-cache=1", source)
        self.assertIn("rotation-cache=1&reasoning-handoff=2", source)
        self.assertNotIn("rotation-floor=1", source)


if __name__ == "__main__":
    unittest.main()
