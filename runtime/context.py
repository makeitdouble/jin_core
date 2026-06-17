from dataclasses import dataclass, field

from websocket_logger import WebSocketLogger

from runtime.L1_memory_rules import (
    DEFAULT_RUNTIME_MEMORY,
)


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

    runtime_remember_session_armed: bool = False

    runtime_remember_session_requested: bool = False

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

    runtime_previous_think_raw: str = ""

    runtime_previous_think_payload_log: dict | None = None
