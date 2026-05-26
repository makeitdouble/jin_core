from dataclasses import dataclass, field, asdict
from datetime import datetime
from xml.sax.saxutils import escape

DEEP_THOUGHT_ACTION = "<RUNTIME_ACTION:DEEP_THOUGHT/>"


@dataclass(frozen=True)
class ContextContract:
    user_input: str
    original_user_input: str = ""
    compressed_history: str = ""
    system_state: str = "ACTIVE"
    deep_thought_count: int = 0

    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    current_date: str = field(default_factory=lambda: datetime.now().date().isoformat())
    current_time: str = field(
        default_factory=lambda: datetime.now().strftime("%H:%M:%S")
    )
    weekday: str = field(default_factory=lambda: datetime.now().strftime("%A"))
    year: int = field(default_factory=lambda: datetime.now().year)

    def build_initial_state(self) -> str:

        fields = {
            "CURRENT_DATE": self.current_date,
            "CURRENT_TIME": self.current_time,
            "WEEKDAY": self.weekday,
            "YEAR": self.year,
            "DEEP_THOUGHT_COUNTER": self.deep_thought_count,
            "DEEP_THOUGHT_ACTION": DEEP_THOUGHT_ACTION,
        }

        state_fields = [
            f"<{tag}>{escape(str(value))}</{tag}>"
            for tag, value
            in fields.items()
        ]

        fields_xml = "\n        ".join(
            state_fields
        )

        return (
            "<INITIAL_STATE>\n"
            f"        {fields_xml}\n"
            "    </INITIAL_STATE>"
        )

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
            "system_state": "RUNTIME_STATE",
            "timestamp": "TIMESTAMP",
            "compressed_history": "COMPRESSED_HISTORY",
            "user_input": "ACTIVE_USER_INPUT",
            "original_user_input": "ORIGINAL_USER_INPUT",
        }

        fields.append(
            self.build_initial_state()
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
            self.build_initial_state()
        ]

        field_mapping = {
            "system_state": "RUNTIME_STATE",
            "timestamp": "TIMESTAMP",
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
