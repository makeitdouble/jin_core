"""Isolated real-WebSocket fixture: no model calls or persistent memory writes."""
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
import uvicorn

import websocket as ws
from runtime.runtime_context import RuntimeContext
from runtime.stream import RuntimeStream


app = FastAPI()
app.state.clients = {}
app.state.websocket_runtime_contexts = {}
events = []
ROOT = Path(__file__).resolve().parents[1]


def create_context(transport, logger):
    client_id = transport.query_params["client_id"]
    context = RuntimeContext(transport, None, logger, {}, session_id=client_id)
    app.state.websocket_runtime_contexts[client_id] = context
    return context, False


async def process(context, message):
    if message.get("_interrupt_before_brain"):
        return
    session_id = context.session_id
    events.append([session_id, "started"])
    context.runtime_turn_user_message = "hello"

    async def chunks():
        if message["text"] == "guard":
            yield {"type": "content", "content": '<SAVE_DELAYED_MEMORY>' + json.dumps({
                "title": "test", "summary": "test", "tags": [], "body": "test",
            }) + '</SAVE_DELAYED_MEMORY>'}
        else:
            while True:
                await context.websocket.send_json({"type": "test_chunk"})
                await asyncio.sleep(.05)
                yield {"type": "content", "content": "test "}

    stream = RuntimeStream(
        context=context, runtime_id="brain", role="brain", context_window=8192,
        log_method=context.logger.log_service,
        runtime_actions={"CAN_SAVE_DELAYED_MEMORY": True},
    )
    try:
        await stream.run(chunks())
        events.append([session_id, "completed"])
    except asyncio.CancelledError:
        events.append([session_id, "cancelled"])
        raise


ws.get_or_create_connection_context = create_context
ws.initialize_connection = AsyncMock()
ws.ensure_initial_runtime_snapshot = lambda context: None
ws.refresh_pending_brain_usage = AsyncMock()
ws.reject_when_all_models_offline = AsyncMock(return_value=False)
ws.process_message = process
app.include_router(ws.websocket_router)


@app.get("/", response_class=HTMLResponse)
def page():
    return '''<form id="chat-form"><input id="user-input"><button type="submit"></button></form>
    <div id="stop-indicator"></div><script>
    window.jinRuntimeSessionId = crypto.randomUUID();
    window.appendLog = () => {};
    window.syncDelayedMemoryReportsToRuntime = () => {};
    window.seen = [];
    </script><script src="/socket.js"></script><script>
    registerSocketMessageHandler('test_chunk', data => seen.push(data));
    registerSocketMessageHandler('runtime_action_guard_confirmation', data => seen.push(data));
    </script>'''


@app.get("/socket.js")
def script():
    return Response((ROOT / "ui/static/js/socket.js").read_text(encoding="utf-8"), media_type="text/javascript")


@app.get("/state")
def state():
    return {"ids": list(app.state.websocket_runtime_contexts), "events": events}


if __name__ == "__main__":
    import sys
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="error")
