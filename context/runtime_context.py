from dataclasses import dataclass

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