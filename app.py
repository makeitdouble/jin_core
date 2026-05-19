from fastapi import (
    FastAPI,
    Request,
    WebSocket,
    WebSocketDisconnect,
)

from fastapi.responses import (
    HTMLResponse,
)

from fastapi.staticfiles import (
    StaticFiles,
)

from fastapi.templating import (
    Jinja2Templates,
)

import asyncio
import httpx
import json

import config

from utils.urls import (
    join_url,
)

from logger import (
    WebSocketLogger,
)

from pipelines.pipeline_factory import (
    get_pipeline,
)

from utils.telemetry import (
    send_telemetry,
)

app = FastAPI()

templates = Jinja2Templates(
    directory="templates"
)

app.mount(
    "/static",
    StaticFiles(
        directory="static"
    ),
    name="static",
)


# ---------------------------------------------------------
# INDEX PAGE
# ---------------------------------------------------------

@app.get(
    "/",
    response_class=HTMLResponse,
)
async def index(
    request: Request,
):

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

    async def check(
        base_url,
    ):

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

                return (
                    response.status_code
                    == 200
                )

        except Exception:

            return False

    (
        brain_status,
        service_status,
        translator_status,
    ) = await asyncio.gather(

        check(
            config.BRAIN_API_BASE
        ),

        check(
            config.SERVICE_API_BASE
        ),

        check(
            config.TRANSLATOR_API_BASE
        ),
    )

    return {
        "brain": brain_status,
        "service": service_status,
        "translator": translator_status,
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

            try:

                message_data = json.loads(
                    raw_data
                )

            except json.JSONDecodeError:

                await logger.log_error(
                    "Invalid JSON payload."
                )

                continue

            user_text = (
                message_data.get(
                    "text",
                    ""
                )
            )

            pipeline = get_pipeline(
                user_text
            )

            await pipeline.run(
                websocket=websocket,
                logger=logger,
                message_data=message_data,
            )

    except WebSocketDisconnect:

        await logger.log_system(
            "Client disconnected."
        )

    except Exception as error:

        await logger.log_error(
            "WebSocket session error: "
            f"{error}"
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
