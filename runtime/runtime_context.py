from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape

from runtime.L1_memory_rules import (
    DEFAULT_RUNTIME_MEMORY,
)


if TYPE_CHECKING:
    from websocket.logger import WebSocketLogger


RECENT_MESSAGES_MAX_PAIRS = 3
DEFAULT_JIN_COLOR = "#1f4f8f"
DEFAULT_JIN_SIZE_TEXT = "120px"
DEFAULT_JIN_SPEED_TEXT = "900px/s"


class RuntimeEmitter:

    def __init__(
            self,
            websocket,
    ):

        self.websocket = websocket

    async def emit(
            self,
            payload: dict,
    ):

        await self.websocket.send_json(
            payload
        )


@dataclass
class RuntimeContext:

    websocket: object

    emitter: RuntimeEmitter

    logger: "WebSocketLogger"

    clients: dict

    active_streams: dict = field(
        default_factory=dict
    )

    deep_thought_count: int = 0

    runtime_deep_search_calls: list[dict] = field(
        default_factory=list
    )

    runtime_deep_search_result: str = ""

    runtime_deep_search_result_id: str = ""

    runtime_deep_search_query_sequence: int = 0

    runtime_search_queries: list[str] = field(
        default_factory=list
    )

    runtime_search_calls: list[dict] = field(
        default_factory=list
    )

    runtime_search_result: str = ""

    runtime_search_result_id: str = ""

    runtime_tool_results: list[dict] = field(
        default_factory=list
    )

    runtime_tool_results_turn_count: int = 0

    runtime_tool_results_generation: int = 0

    runtime_asset_results: list[dict] = field(
        default_factory=list
    )

    runtime_active_asset_action_id: str = ""

    runtime_asset_retry_results: list[dict] = field(
        default_factory=list
    )

    runtime_asset_retry_context: list[dict] = field(
        default_factory=list
    )

    runtime_delayed_memory_results: list[dict] = field(
        default_factory=list
    )

    runtime_pending_delayed_memory_action_ids: list[str] = field(
        default_factory=list
    )

    runtime_delayed_memory_action_sequence: int = 0

    runtime_loaded_delayed_memory: dict = field(
        default_factory=dict
    )

    runtime_loaded_delayed_memory_ids: list[str] = field(
        default_factory=list
    )

    runtime_suppressed_delayed_memory_auto_load_ids: list[str] = field(
        default_factory=list
    )

    runtime_pinned_delayed_memory_turns: dict[str, str] = field(
        default_factory=dict
    )

    runtime_delayed_memory_file_warnings: list[str] = field(
        default_factory=list
    )

    delayed_memory_file_store_enabled: bool = True

    runtime_anonymous_mode: bool = False

    runtime_persistent_writes_restricted: bool = False

    runtime_loaded_skills: list[dict] = field(
        default_factory=list
    )

    runtime_action_events: list[dict] = field(
        default_factory=list
    )

    runtime_active_action_markers: list[dict] = field(
        default_factory=list
    )

    runtime_turn_aborted_actions: list[dict] = field(
        default_factory=list
    )

    runtime_turn_abort_requested: bool = False

    runtime_turn_discard_requested: bool = False

    runtime_turn_interrupted_memory_update_scheduled: bool = False

    runtime_action_guard_confirmations: dict[str, object] = field(
        default_factory=dict
    )

    runtime_action_guard_retry: dict[str, object] = field(
        default_factory=dict
    )

    runtime_action_guard_retry_consumed: bool = False

    runtime_suppress_chat_content: bool = False

    runtime_pending_requests_queue: object | None = None

    runtime_session_action_history: list[dict] = field(
        default_factory=list
    )

    runtime_action_sequence_turn_ids: list[str] = field(
        default_factory=list
    )

    runtime_todo: list[dict] = field(
        default_factory=list
    )

    active_memory_records: list[str] = field(
        default_factory=list
    )

    runtime_active_memory_refresh_tick: int = 0

    delayed_memory_reports: dict = field(
        default_factory=dict
    )

    runtime_facts_memory_records: list[dict] = field(
        default_factory=list
    )

    runtime_long_term_memory_store: dict = field(
        default_factory=dict
    )

    runtime_l4_archived_fact_ids: set[str] = field(
        default_factory=set
    )

    runtime_l4_explicit_edit_turn_id: str = ""

    runtime_l4_explicit_edit_fact_ids: set[str] = field(
        default_factory=set
    )

    runtime_l4_memory_update_task: object | None = None

    # Transient merge recovery state. A reasoning-heavy service model can
    # consume the shared generation budget before emitting final L4 JSON; the
    # runtime learns a smaller FIFO batch and backs off instead of hammering
    # the identical pending queue on every idle tick.
    runtime_l4_merge_batch_limit: int = 0
    runtime_l4_merge_last_success_batch_limit: int = 0
    runtime_l4_merge_batch_locked: bool = False
    runtime_l4_merge_context_window_tokens: int = 0
    runtime_l4_merge_existing_batch_mode: str = ""
    runtime_l4_merge_paused_signature: str = ""
    runtime_l4_merge_truncation_streak: int = 0
    runtime_l4_merge_retry_not_before: float = 0.0
    runtime_l4_merge_deferred_pending_until: dict[str, float] = field(
        default_factory=dict
    )
    runtime_l4_merge_single_retry_pending_ids: set[str] = field(
        default_factory=set
    )
    runtime_l4_merge_force_single_batch_once: bool = False
    runtime_l4_memory_update_kind: str = ""
    runtime_l4_idle_last_started_at: float = 0.0
    runtime_l4_profile_sync_at: float = 0.0
    runtime_l4_websocket_connected: bool = False
    runtime_l4_app_state: object | None = None
    runtime_foreground_turn_running: bool = False

    runtime_usage_events: list[dict] = field(
        default_factory=list
    )

    runtime_token_estimate_scales: dict[str, float] = field(
        default_factory=dict
    )

    runtime_current_context_window: dict = field(
        default_factory=dict
    )

    runtime_current_context_window_text: str = ""

    runtime_previous_answer_context_window: dict = field(
        default_factory=dict
    )

    runtime_memory: str = DEFAULT_RUNTIME_MEMORY

    runtime_memory_stable: str = DEFAULT_RUNTIME_MEMORY

    runtime_memory_updates: int = 0

    # Offset that maps the server snapshot index to the FRAME number shown in
    # the right-panel UI. Fresh sessions start at 0; restored baselines can
    # start at 1, and soft reconnects can resume at any visible FRAME number.
    runtime_memory_display_index_offset: int = 0

    runtime_pattern_counter: int = 0

    runtime_repeated_input_count: int = 0

    runtime_l1_diff_history: list[dict] = field(
        default_factory=list
    )

    runtime_zero_diff_alert: dict | None = None

    runtime_conversation_activity_diff: float | None = None

    turn_number: int = 0

    runtime_turn_counter: int = 0

    runtime_current_turn_id: str = ""

    runtime_current_sequence_turn_id: str = ""

    runtime_turn_started_at: float = 0.0

    runtime_user_waiting_for_jin_answer_session_id: str = ""

    runtime_user_waiting_for_jin_answer_started_at: float = 0.0

    runtime_user_waiting_for_jin_answer_last_seconds: float | None = None

    runtime_user_waiting_for_jin_answer_total_seconds: float = 0.0

    runtime_user_waiting_for_jin_answer_count: int = 0

    runtime_user_waiting_for_jin_answer_tracking_enabled: bool = False

    runtime_current_sequence_started_at: float = 0.0

    runtime_current_sequence_attachments: list[dict] = field(
        default_factory=list
    )

    runtime_current_sequence_attachments_turn_id: str = ""

    user_message_count: int = 0

    assistant_message_count: int = 0

    # CURRENT_SESSION_STATE is scoped to this live runtime session. The
    # counters above remain monotonic across predecessor bootstrap because
    # Active Memory lifecycle metadata uses that message scale.
    current_session_user_message_count: int = 0

    current_session_assistant_message_count: int = 0

    runtime_memory_pending_turns: list[dict] = field(
        default_factory=list
    )

    runtime_memory_pending_base_updates: int = 0

    runtime_recent_turns: list[dict] = field(
        default_factory=list
    )

    # The last real user request is retained only in the live runtime so the
    # latest completed JIN answer can be replaced in-place by a user retry.
    # It is intentionally not part of bootstrap/history state.
    runtime_last_retryable_request: dict = field(
        default_factory=dict
    )

    runtime_user_retry_active: bool = False

    runtime_user_retry_count: int = 0

    runtime_restored_session_dialog: str = ""

    runtime_restored_session_source_id: str = ""

    runtime_archived_session_id: str = ""

    runtime_session_restore_priming: bool = False

    runtime_session_restore_reasoning_dump: str = ""

    runtime_session_restore_l4_fact_ids: list[str] = field(
        default_factory=list
    )

    runtime_session_restore_delayed_memory_metadata: list[dict] = field(
        default_factory=list
    )

    runtime_session_restore_attached_file_metadata: list[dict] = field(
        default_factory=list
    )

    # Delayed reports that were loaded in an archived session are staged during
    # the hidden restore turn. Their bodies stay out of the first restore prompt
    # and become normally loaded only after JIN has produced the restore greeting.
    runtime_session_restore_pending_loaded_memory_ids: list[str] = field(
        default_factory=list
    )

    # Persistent files from an archived session follow the same one-shot
    # restore contract as delayed memory: metadata is visible to the hidden
    # restore turn, while the real ATTACH_FILE actions are replayed only after
    # JIN has completed that first response.
    runtime_session_restore_pending_attached_file_ids: list[str] = field(
        default_factory=list
    )

    runtime_memory_update_task: object | None = None

    fact_check_idle_task: object | None = None

    runtime_memory_snapshots: list[dict] = field(
        default_factory=list
    )

    runtime_memory_quote_history: dict = field(
        default_factory=dict
    )

    runtime_memory_pending_quote_identities: set = field(
        default_factory=set
    )

    runtime_memory_snapshot_index: int = 0

    identity_details: str = ""

    session_id: str = ""

    previous_session_id: str = ""

    background_tasks: set = field(
        default_factory=set
    )

    runtime_turn_user_message: str = ""

    runtime_turn_memory_user_message: str = ""

    runtime_attached_file_ids: list[str] = field(
        default_factory=list
    )

    runtime_turn_attachments: list[dict] = field(
        default_factory=list
    )

    runtime_turn_assistant_response: str = ""

    runtime_turn_reasoning_content: str = ""

    runtime_previous_reasoning_content: str = ""

    runtime_previous_reasoning_loop_contents: list[str] = field(
        default_factory=list
    )

    runtime_turn_interrupted: bool = False

    runtime_turn_interruption_reason: str = ""

    runtime_turn_interruption_quote: str = ""

    runtime_reasoning_recovery_pending: bool = False

    runtime_delayed_memory_save_rejected_pending: bool = False

    runtime_delayed_memory_save_rejected_title: str = ""

    runtime_active_memory_delete_failures_pending: list[dict] = field(
        default_factory=list
    )

    runtime_context_limit_recovery_pending: bool = False

    runtime_context_limit_stage: str = ""

    runtime_context_limit_kind: str = ""

    runtime_context_limit_finish_reason: str = ""

    runtime_user_idle_seconds: int | None = None

    runtime_user_idle_text: str = ""

    runtime_user_idle_paused: bool = False

    runtime_last_response_feedback: dict | None = None

    runtime_memory_attention_l4_focus_ids: list[str] = field(
        default_factory=list
    )

    runtime_avatar_panel_collapsed: bool = False

    runtime_avatar_current_size: dict = field(
        default_factory=dict
    )

    runtime_avatar_current_position: dict = field(
        default_factory=dict
    )

    runtime_avatar_window_size: dict = field(
        default_factory=dict
    )

    runtime_avatar_move_speed: int = 900


def format_xml_field(
    tag: str,
    value,
) -> str:

    if tag == "CURRENT_SESSION_STATE":
        return str(value)

    rendered_value = escape(
        str(value)
    )

    return f"<{tag}>{rendered_value}</{tag}>"


def format_available_actions(
    actions: list[tuple[str, str]],
) -> str:

    if not actions:
        return ""

    action_fields = [
        (
            "        "
            f"<ACTION name=\"{escape(name)}\">"
            f"{template}"
            "</ACTION>"
        )
        for name, template
        in actions
    ]

    actions_xml = "\n".join(
        action_fields
    )

    return (
        "<AVAILABLE_ACTIONS>\n"
        f"{actions_xml}\n"
        "    </AVAILABLE_ACTIONS>"
    )


def format_user_datetime(
    current_date: str,
    current_time: str,
    weekday: str,
) -> str:

    time_value = str(
        current_time
        or ""
    )
    time_minutes = (
        time_value[:5]
        if len(time_value) >= 5
        else time_value
    )

    return (
        f"{current_date} {time_minutes}, {weekday}"
        .strip()
    )


def format_session_state(
    *,
    turn_number: int | None,
    user_message_count: int | None,
    assistant_message_count: int | None,
) -> str:

    lines = [
        "<CURRENT_SESSION_STATE>",
    ]

    lines.extend([
        f"    User messages count:          {user_message_count or 0}",
        f"    JIN messages count:           {assistant_message_count or 0}",
        f"    Total messages count:         {(user_message_count or 0) + (assistant_message_count or 0)}",
        "</CURRENT_SESSION_STATE>",
    ])

    return "\n".join(lines)


def format_user_feedback(
    user_feedback: str,
) -> str:

    return (
        "<LATEST_USER_FEEDBACK priority=HIGH_PRIORITY>\n"
        f"{escape(str(user_feedback))}\n"
        "</LATEST_USER_FEEDBACK>"
    )


@dataclass(frozen=True)
class ContextContract:
    user_input: str
    original_user_input: str = ""
    compressed_history: str = ""
    system_state: str = "ACTIVE"
    current_session_id: str = ""
    current_model_uid: str = ""
    current_context_window: str = ""
    jin_color: str = DEFAULT_JIN_COLOR
    jin_size_context: str = ""
    jin_position_context: str = ""
    jin_speed_context: str = DEFAULT_JIN_SPEED_TEXT
    window_size_context: str = ""
    can_web_search: bool = True
    can_use_assets: bool = False
    can_save_active_memory: bool = False

    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    current_date: str = field(default_factory=lambda: datetime.now().date().isoformat())
    current_time: str = field(
        default_factory=lambda: datetime.now().strftime("%H:%M:%S")
    )
    weekday: str = field(default_factory=lambda: datetime.now().strftime("%A"))
    year: int = field(default_factory=lambda: datetime.now().year)
    conversation_activity_instruction: str = ""

    turn_number: int | None = None
    user_message_count: int | None = None
    assistant_message_count: int | None = None

    def build_runtime_fields(self) -> str:

        fields = {}

        if self.current_session_id:
            fields["CURRENT_SESSION_ID"] = self.current_session_id

        if self.current_model_uid:
            fields["CURRENT_MODEL_UID"] = self.current_model_uid

        if self.current_context_window:
            fields["CURRENT_CONTEXT_WINDOW"] = (
                self.current_context_window
            )

        if self.jin_color:
            fields["CURRENT_JIN_COLOR"] = self.jin_color

        if self.jin_size_context:
            fields["CURRENT_JIN_SIZE"] = self.jin_size_context

        if self.jin_position_context:
            fields["CURRENT_JIN_POSITION"] = self.jin_position_context

        if self.jin_speed_context:
            fields["CURRENT_JIN_SPEED"] = self.jin_speed_context

        if self.window_size_context:
            fields["CURRENT_WINDOW_SIZE"] = self.window_size_context

        fields["CURRENT_USER_DATETIME"] = format_user_datetime(
            self.current_date,
            self.current_time,
            self.weekday,
        )

        if self.conversation_activity_instruction:
            fields["CONVERSATION_ACTIVITY"] = (
                self.conversation_activity_instruction
            )

        has_session_counts = any(
            value is not None
            for value in (
                self.turn_number,
                self.user_message_count,
                self.assistant_message_count,
            )
        )

        if has_session_counts:
            fields["CURRENT_SESSION_STATE"] = format_session_state(
                turn_number=self.turn_number,
                user_message_count=self.user_message_count,
                assistant_message_count=self.assistant_message_count,
            )

        state_fields = [
            format_xml_field(
                tag,
                value,
            )
            for tag, value
            in fields.items()
        ]

        fields_xml = "\n    ".join(
            state_fields
        )

        return fields_xml

    def to_xml(self) -> str:

        raw_data = asdict(
            self
        )

        data = {
            key: escape(str(value))
            for key, value
            in raw_data.items()
            if value not in (
                "",
                None,
            )
        }

        fields = []

        field_mapping = {
            "compressed_history": "COMPRESSED_HISTORY",
            "user_input": "ACTIVE_USER_INPUT",
            "original_user_input": "ORIGINAL_USER_INPUT",
        }

        fields.append(
            self.build_runtime_fields()
        )

        for key, xml_tag in field_mapping.items():

            value = data.get(key)

            if not value:
                continue

            fields.append(
                f"<{xml_tag}>{value}</{xml_tag}>"
            )

        fields_xml = "\n    ".join(
            fields
        )

        return (
            "<CONTEXT_INTERFACE>\n"
            f"    {fields_xml}\n"
            "</CONTEXT_INTERFACE>"
        )

    def to_runtime_xml(self) -> str:

        raw_data = asdict(
            self
        )

        data = {
            key: escape(str(value))
            for key, value
            in raw_data.items()
            if value not in (
                "",
                None,
            )
        }

        fields = [
            self.build_runtime_fields()
        ]

        field_mapping = {
            "compressed_history": "COMPRESSED_HISTORY",
        }

        for key, xml_tag in field_mapping.items():

            value = data.get(key)

            if not value:
                continue

            fields.append(
                f"<{xml_tag}>{value}</{xml_tag}>"
            )

        fields_xml = "\n    ".join(
            fields
        )

        return (
            "<CURRENT_TRUSTED_RUNTIME_VARIABLES>\n"
            f"    {fields_xml}\n"
            "</CURRENT_TRUSTED_RUNTIME_VARIABLES>"
        )
