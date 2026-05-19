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

        raw_data = asdict(self)

        data = {k: escape(str(v)) for k, v in raw_data.items()}

        return f"""
<CONTEXT_INTERFACE>
    <RUNTIME_STATE>{data['system_state']}</RUNTIME_STATE>
    <TIMESTAMP>{data['timestamp']}</TIMESTAMP>
    <COMPRESSED_HISTORY>{data['compressed_history']}</COMPRESSED_HISTORY>
    <ACTIVE_USER_INPUT>{data['user_input']}</ACTIVE_USER_INPUT>
    <ORIGINAL_USER_INPUT>{data['original_user_input']}</ORIGINAL_USER_INPUT>
</CONTEXT_INTERFACE>
""".strip()
