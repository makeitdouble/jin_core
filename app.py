from fastapi import (
    FastAPI,
    Request,
    WebSocket,
    WebSocketDisconnect,
)

from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import httpx
import json

import config

from clients.url_utils import join_url

from logger import WebSocketLogger

from pipelines.chat_pipeline import (
    process_chat_message,
    send_telemetry,
)

app = FastAPI()

templates = Jinja2Templates(
    directory="templates"
)

app.mount(
    "/static",
    StaticFiles(directory="static"),
    name="static",
)


# ---------------------------------------------------------
# INDEX PAGE
# ---------------------------------------------------------

@app.get(
    "/",
    response_class=HTMLResponse,
)
async def index(request: Request):

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
        },
    )


# ---------------------------------------------------------
# API STATUS
# ---------------------------------------------------------

@app.get("/api/status")
async def api_status():

    async def check(base_url):

        try:

            async with httpx.AsyncClient(
                timeout=2.5
            ) as client:

                response = await client.get(
                    join_url(
                        base_url,
                        config.MODELS_ENDPOINT,
                    )
                )

                return response.status_code == 200

        except Exception:

            return False

    return {
        "brain": await check(
            config.BRAIN_API_BASE
        ),
        "service": await check(
            config.SERVICE_API_BASE
        ),
    }


# ---------------------------------------------------------
# WEBSOCKET CHAT
# ---------------------------------------------------------

@app.websocket("/ws/chat")
async def websocket_endpoint(
    websocket: WebSocket,
):

    await websocket.accept()

    logger = WebSocketLogger(
        websocket
    )

    await logger.log_system(
        "WebSocket connected."
    )

    await send_telemetry(
        websocket
    )

    try:

        while True:

            raw_data = (
                await websocket.receive_text()
            )

            message_data = json.loads(
                raw_data
            )

            await process_chat_message(
                websocket=websocket,
                logger=logger,
                message_data=message_data,
            )

    except WebSocketDisconnect:

        await logger.log_system(
            "Client disconnected."
        )

    except Exception as e:

        await logger.log_error(
            f"WebSocket session error: {e}"
        )


# ---------------------------------------------------------
# DEV ENTRYPOINT
# ---------------------------------------------------------

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
    )
