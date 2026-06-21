from dataclasses import dataclass, field, asdict
from datetime import datetime
from xml.sax.saxutils import escape

RUNTIME_ACTION_DEEP_THOUGHT = "DEEP_THOUGHT"
RUNTIME_ACTION_WEB_SEARCH = "WEB_SEARCH"
RUNTIME_ACTION_REMEMBER_SESSION = "REMEMBER_SESSION"
RUNTIME_ACTION_REMEMBER_EVENT = "REMEMBER_EVENT"

DEEP_THOUGHT_REQUEST = "<INTERNAL_ACTION_DEEP_THOUGHT>"
WEB_SEARCH_REQUEST_TEMPLATE = "<INTERNAL_ACTION_WEB_SEARCH:plain text query>"
REMEMBER_SESSION_REQUEST = "<INTERNAL_ACTION_REMEMBER_SESSION>"
REMEMBER_EVENT_REQUEST = "<INTERNAL_ACTION_REMEMBER_EVENT>"


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
    deep_thought_count: int = 0
    can_deep_thought: bool = False
    can_web_search: bool = True
    can_remember_session: bool = False
    can_remember_event: bool = False

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

        available_actions = []

        if self.can_deep_thought:
            fields["DEEP_THOUGHT_COUNTER"] = str(self.deep_thought_count)
            available_actions.append(
                (
                    RUNTIME_ACTION_DEEP_THOUGHT,
                    DEEP_THOUGHT_REQUEST,
                )
            )

        if self.can_web_search:
            available_actions.append(
                (
                    RUNTIME_ACTION_WEB_SEARCH,
                    WEB_SEARCH_REQUEST_TEMPLATE,
                )
            )

        if self.can_remember_session:
            available_actions.append(
                (
                    RUNTIME_ACTION_REMEMBER_SESSION,
                    REMEMBER_SESSION_REQUEST,
                )
            )

        if self.can_remember_event:
            available_actions.append(
                (
                    RUNTIME_ACTION_REMEMBER_EVENT,
                    REMEMBER_EVENT_REQUEST,
                )
            )

        state_fields = [
            format_xml_field(
                tag,
                value,
            )
            for tag, value
            in fields.items()
        ]

        available_actions_xml = format_available_actions(
            available_actions
        )

        if available_actions_xml:
            state_fields.append(
                available_actions_xml
            )

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
