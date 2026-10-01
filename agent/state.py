from dataclasses import (
    dataclass,
    field,
)


@dataclass
class AgentState:

    user_input: str

    brain_response: str = ""

    metadata: dict = field(default_factory=dict)

    visible_response_role: str = ""

    visible_response_context: dict = field(default_factory=dict)
