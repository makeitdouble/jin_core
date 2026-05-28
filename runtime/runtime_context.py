from dataclasses import dataclass, field

from websocket_logger import WebSocketLogger

from emitter.runtime_emitter import (
    RuntimeEmitter,
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

    runtime_memory: str = (
        "User and JIN just started interacting."
    )

    runtime_memory_updates: int = 0

    background_tasks: set = field(
        default_factory=set
    )

    runtime_turn_user_message: str = ""

    runtime_turn_assistant_response: str = ""

    runtime_turn_interrupted: bool = False
