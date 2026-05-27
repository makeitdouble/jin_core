from dataclasses import dataclass, field, asdict
from datetime import datetime
from xml.sax.saxutils import escape

RUNTIME_ACTION_DEEP_THOUGHT = "DEEP_THOUGHT"
RUNTIME_ACTION_SEARCH = "SEARCH"

DEEP_THOUGHT_ACTION = "<RUNTIME_ACTION:DEEP_THOUGHT/>"
SEARCH_ACTION_OPEN = "<RUNTIME_ACTION:SEARCH>"
SEARCH_ACTION_CLOSE = "</RUNTIME_ACTION:SEARCH>"
SEARCH_ACTION_TEMPLATE = (
    f'{SEARCH_ACTION_OPEN}{{"query":"..."}}{SEARCH_ACTION_CLOSE}'
)


def cdata(
    value: str,
) -> str:

    return (
        "<![CDATA["
        f"{str(value).replace(']]>', ']]]]><![CDATA[>')}"
        "]]>"
    )


def format_xml_field(
    tag: str,
    value,
) -> str:

    if tag.endswith(
        "_ACTION"
    ):
        rendered_value = cdata(
            str(value)
        )

    else:
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
            f"{cdata(template)}"
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


@dataclass(frozen=True)
class ContextContract:
    user_input: str
    original_user_input: str = ""
    compressed_history: str = ""
    system_state: str = "ACTIVE"
    deep_thought_count: int = 0
    can_deep_thought: bool = False
    can_search: bool = True

    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    current_date: str = field(default_factory=lambda: datetime.now().date().isoformat())
    current_time: str = field(
        default_factory=lambda: datetime.now().strftime("%H:%M:%S")
    )
    weekday: str = field(default_factory=lambda: datetime.now().strftime("%A"))
    year: int = field(default_factory=lambda: datetime.now().year)

    def build_runtime_fields(self) -> str:

        fields = {
            "TIMESTAMP": self.timestamp,
            "WEEKDAY": self.weekday,
            "YEAR": self.year,
        }

        available_actions = []

        if self.can_deep_thought:
            fields["DEEP_THOUGHT_COUNTER"] = self.deep_thought_count
            available_actions.append(
                (
                    RUNTIME_ACTION_DEEP_THOUGHT,
                    DEEP_THOUGHT_ACTION,
                )
            )

        if self.can_search:
            available_actions.append(
                (
                    RUNTIME_ACTION_SEARCH,
                    SEARCH_ACTION_TEMPLATE,
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
            "<TRUSTED_RUNTIME_CONTEXT>\n"
            f"    {fields_xml}\n"
            "</TRUSTED_RUNTIME_CONTEXT>"
        )
