from contracts.rules_assembler import (
    RUNTIME_ACTION_LOAD_SKILL,
    RUNTIME_ACTION_JIN_COLOR,
    RUNTIME_ACTION_JIN_SIZE,
    RUNTIME_ACTION_JIN_POSITION,
    RUNTIME_ACTION_JIN_SPEED,
    RUNTIME_ACTION_UNLOAD_SKILL,
    RUNTIME_ACTION_WEB_SEARCH,
    RUNTIME_ACTION_POSTING_BOARD,
    RUNTIME_ACTION_CALL_MCP,
)
from utils.actions import (
    extract_search_query,
    normalize_jin_color_payload,
    normalize_jin_position_payload,
    normalize_jin_speed_payload,
    normalize_jin_size_payload,
)
from utils.skills_asset_utils import normalize_skill_name
from utils.actions.posting_board_actions import canonical_posting_board_payload
from utils.actions.mcp_actions import canonical_call_mcp_payload


_PAYLOAD_IDENTITIES = {
    RUNTIME_ACTION_WEB_SEARCH: extract_search_query,
    RUNTIME_ACTION_JIN_COLOR: normalize_jin_color_payload,
    RUNTIME_ACTION_JIN_SIZE: normalize_jin_size_payload,
    RUNTIME_ACTION_JIN_POSITION: normalize_jin_position_payload,
    RUNTIME_ACTION_JIN_SPEED: normalize_jin_speed_payload,
    RUNTIME_ACTION_LOAD_SKILL: normalize_skill_name,
    RUNTIME_ACTION_UNLOAD_SKILL: normalize_skill_name,
    RUNTIME_ACTION_POSTING_BOARD: canonical_posting_board_payload,
    RUNTIME_ACTION_CALL_MCP: canonical_call_mcp_payload,
}


class ActionDedup:
    """Message-local identities and adjacent visual no-ops, backed by RuntimeContext."""

    def __init__(self, context, message_id, turn_id):
        self.scope = message_id
        self.seen = set()
        self.by_message = {}
        if message_id:
            state = getattr(context, "runtime_action_apply_dedup_state", None)
            if not isinstance(state, dict) or state.get("turn_id") != turn_id:
                state = {"turn_id": turn_id, "seen_by_message": {}}
                context.runtime_action_apply_dedup_state = state
            elif not isinstance(state.get("seen_by_message"), dict):
                state["seen_by_message"] = {}
            self.by_message = state["seen_by_message"]
            self.seen = set(self.by_message.get(message_id, []) or [])
        # Alternation is meaningful: visual dedup remembers only the last value.
        self.visual_scope = message_id or "__unscoped__"
        self.colors = self._visual_state(context, turn_id, "color", normalize_jin_color_payload)
        self.sizes = self._visual_state(context, turn_id, "size", normalize_jin_size_payload)
        self.color = normalize_jin_color_payload(self.colors.get(self.visual_scope, ""))
        self.size = normalize_jin_size_payload(self.sizes.get(self.visual_scope, ""))

    @staticmethod
    def _visual_state(context, turn_id, kind, normalize):
        attribute = f"runtime_jin_{kind}_apply_dedup_state"
        key = f"last_{kind}_by_message"
        state = getattr(context, attribute, None)
        if not isinstance(state, dict) or state.get("turn_id") != turn_id:
            state = {"turn_id": turn_id, key: {}}
            setattr(context, attribute, state)
        elif not isinstance(state.get(key), dict):
            legacy = normalize(state.get(f"last_{kind}", ""))
            state[key] = {"__unscoped__": legacy} if legacy else {}
        return state[key]

    def key(self, action, payload_identity=None):
        name = str(action.name or "").strip().upper()
        if payload_identity is None:
            normalize = _PAYLOAD_IDENTITIES.get(name)
            payload_identity = normalize(action.payload) if normalize else str(action.payload or "")
        return f"{name}\x00{str(payload_identity or '').strip()}"

    def accept(self, action, payload_identity=None):
        key = self.key(action, payload_identity)
        if key in self.seen:
            return False
        self.seen.add(key)
        if self.scope:
            self.by_message[self.scope] = sorted(self.seen)
        return True
