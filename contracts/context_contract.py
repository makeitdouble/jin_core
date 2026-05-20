from dataclasses import dataclass, field, asdict
from datetime import datetime
from xml.sax.saxutils import escape

@dataclass(frozen=True)
class ContextContract:
    user_input: str
    original_user_input: str = ""
    compressed_history: str = ""
    system_state: str = "ACTIVE"

    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

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
