from dataclasses import dataclass, field

from websocket_logger import WebSocketLogger

from emitter.runtime_emitter import (
    RuntimeEmitter,
)

from memory.message_memory import (
    DEFAULT_RUNTIME_MEMORY,
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

    runtime_usage_events: list[dict] = field(
        default_factory=list
    )

    runtime_memory: str = DEFAULT_RUNTIME_MEMORY

    runtime_memory_stable: str = DEFAULT_RUNTIME_MEMORY

    runtime_memory_updates: int = 0

    turn_number: int = 0

    user_message_count: int = 0

    assistant_message_count: int = 0

    runtime_memory_pending_turns: list[dict] = field(
        default_factory=list
    )

    runtime_memory_update_task: object | None = None

    background_tasks: set = field(
        default_factory=set
    )

    runtime_turn_user_message: str = ""

    runtime_turn_assistant_response: str = ""

    runtime_turn_interrupted: bool = False
