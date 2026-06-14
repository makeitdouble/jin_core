from dataclasses import (
    dataclass,
    field,
)


@dataclass
class AgentState:

    user_input: str

    current_plan: list[str] = field(default_factory=list)

    translate_input: bool = False

    translated_input: str = ""

    brain_response: str = ""

    translated_text: str = ""

    validation_error: str = ""

    iteration: int = 0

    max_iterations: int = 3

    # -----------------------------------------
    # ORIGINAL JIN FLOW FLAG
    # -----------------------------------------

    translate_response: bool = False

    metadata: dict = field(default_factory=dict)

    final_answer: str = ""

    visible_response_role: str = ""

    visible_response_context: dict = field(default_factory=dict)
