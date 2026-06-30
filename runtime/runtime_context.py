from dataclasses import asdict, dataclass, field
from datetime import datetime
from xml.sax.saxutils import escape

from websocket_logger import WebSocketLogger

from runtime.L1_memory_rules import (
    DEFAULT_RUNTIME_MEMORY,
)


RECENT_MESSAGES_MAX_PAIRS = 3
RECENT_MESSAGE_MAX_CHARS = 220


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

    logger: WebSocketLogger

    clients: dict

    active_streams: dict = field(
        default_factory=dict
    )

    deep_thought_count: int = 0

    runtime_search_queries: list[str] = field(
        default_factory=list
    )

    runtime_search_calls: list[dict] = field(
        default_factory=list
    )

    runtime_search_result: str = ""

    runtime_search_result_id: str = ""

    runtime_action_events: list[dict] = field(
        default_factory=list
    )

    active_memory_records: list[str] = field(
        default_factory=list
    )

    delayed_memory_reports: dict = field(
        default_factory=dict
    )

    runtime_usage_events: list[dict] = field(
        default_factory=list
    )

    runtime_memory: str = DEFAULT_RUNTIME_MEMORY

    runtime_memory_stable: str = DEFAULT_RUNTIME_MEMORY

    runtime_memory_updates: int = 0

    runtime_l2_memory: str = ""

    runtime_pattern_counter: int = 0

    runtime_repeated_input_count: int = 0

    session_memory: str = ""

    session_memory_source: str = ""

    runtime_l3_session_memory: str = ""

    runtime_session_memory_updates: int = 0

    runtime_l3_session_first_turn: int | None = None

    runtime_l3_session_last_turn: int | None = None

    runtime_l3_saved_runtime_snapshot_index: int | None = None

    runtime_session_memory_update_task: object | None = None

    runtime_session_event_snapshots: list[dict] = field(
        default_factory=list
    )

    runtime_save_session_armed: bool = False

    runtime_save_session_requested: bool = False

    runtime_l1_diff_history: list[dict] = field(
        default_factory=list
    )

    runtime_l2_pending_patches: list[dict] = field(
        default_factory=list
    )

    runtime_l2_last_turn: int = 0

    runtime_zero_diff_alert: dict | None = None

    runtime_conversation_activity_diff: float | None = None

    turn_number: int = 0

    user_message_count: int = 0

    assistant_message_count: int = 0

    runtime_memory_pending_turns: list[dict] = field(
        default_factory=list
    )

    runtime_recent_turns: list[dict] = field(
        default_factory=list
    )

    runtime_memory_update_task: object | None = None

    fact_check_idle_task: object | None = None

    runtime_memory_snapshots: list[dict] = field(
        default_factory=list
    )

    runtime_memory_snapshot_index: int = 0

    identity_details: str = ""

    session_id: str = ""

    background_tasks: set = field(
        default_factory=set
    )

    runtime_turn_user_message: str = ""

    runtime_turn_assistant_response: str = ""

    runtime_turn_interrupted: bool = False

    runtime_user_idle_seconds: int | None = None

    runtime_user_idle_text: str = ""

    runtime_user_idle_paused: bool = False

    runtime_last_response_feedback: dict | None = None


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

    return "\n".join([
        "<CURRENT_SESSION_STATE>",
        f"    Total turns count:      {turn_number if turn_number is not None else 0}",
        f"    User messages count:    {user_message_count if user_message_count is not None else 0}",
        f"    JIN messages count:     {assistant_message_count if assistant_message_count is not None else 0}",
        "</CURRENT_SESSION_STATE>",
    ])


@dataclass(frozen=True)
class ContextContract:
    user_input: str
    original_user_input: str = ""
    compressed_history: str = ""
    system_state: str = "ACTIVE"
    runtime_mode: str = ""
    service_model_uid: str = ""
    can_web_search: bool = True
    can_save_session: bool = False
    can_create_active_memory: bool = False

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

        if self.runtime_mode:
            fields["MODE"] = self.runtime_mode

        if self.service_model_uid:
            fields["SERVICE_MODEL_UID"] = self.service_model_uid

        fields["USER_DATETIME"] = format_user_datetime(
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
