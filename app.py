from contextlib import asynccontextmanager

from fastapi import (
    FastAPI,
    Request,
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

from settings.config_loader import (
    config,
)

from utils.urls import (
    join_url,
)

from websocket import (
    websocket_router,
)

from clients.clients_registry import (
    build_clients,
)

STATUS_CHECK_TIMEOUT = getattr(
    config,
    "STATUS_CHECK_TIMEOUT",
    0.5,
)


# ---------------------------------------------------------
# APP LIFESPAN
# ---------------------------------------------------------

@asynccontextmanager
async def lifespan(application: FastAPI):

    # -----------------------------------------------------
    # SHARED HTTP CLIENT
    # -----------------------------------------------------

    application.state.http_client = httpx.AsyncClient(

        timeout=None,

        limits=httpx.Limits(
            max_connections=100,
            max_keepalive_connections=20,
        ),

        http2=False,
    )

    # -----------------------------------------------------
    # RUNTIME CLIENTS
    # -----------------------------------------------------

    application.state.clients = build_clients(
        application.state.http_client
    )

    yield

    # -----------------------------------------------------
    # SHUTDOWN
    # -----------------------------------------------------

    await application.state.http_client.aclose()


app = FastAPI(
    lifespan=lifespan,
)

templates = Jinja2Templates(
    directory="templates",
)

app.mount(
    "/static",
    StaticFiles(directory="static"),
    name="static",
)

app.include_router(
    websocket_router
)


# ---------------------------------------------------------
# INDEX PAGE
# ---------------------------------------------------------

def build_runtime_config(
    use_service_as_brain=None,
):

    effective_use_service_as_brain = (
        config.USE_SERVICE_AS_BRAIN
        if use_service_as_brain is None
        else use_service_as_brain
    )

    return {
        "service": {
            "label": "service",
            "model": config.SERVICE_MODEL_UID,
            "used_tokens": 0,
            "max_tokens": config.SERVICE_CONTEXT_WINDOW,
        },
        "brain": {
            "label": "brain",
            "model": (
                config.SERVICE_MODEL_UID
                if effective_use_service_as_brain
                else config.BRAIN_MODEL_UID
            ),
            "used_tokens": 0,
            "max_tokens": (
                config.SERVICE_CONTEXT_WINDOW
                if effective_use_service_as_brain
                else config.BRAIN_CONTEXT_WINDOW
            ),
        },
    }


@app.get(
    "/",
    response_class=HTMLResponse,
)
async def index(
    request: Request,
):

    status_snapshot = await build_status_snapshot(
        request.app.state.http_client
    )

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "use_service_as_brain": (
                status_snapshot[
                    "use_service_as_brain"
                ]
            ),
            "runtime_config": (
                status_snapshot[
                    "runtime_config"
                ]
            ),
            "runtime_status": {
                "brain": status_snapshot["brain"],
                "service": status_snapshot["service"],
            },
        },
    )


# ---------------------------------------------------------
# API STATUS
# ---------------------------------------------------------

async def check_api_status(
    client: httpx.AsyncClient,
    base_url: str,
) -> bool:

    try:

        response = await client.get(
            join_url(
                base_url,
                config.MODELS_ENDPOINT,
            ),
            timeout=STATUS_CHECK_TIMEOUT,
        )

        return response.status_code == 200

    except (
        httpx.HTTPError,
        asyncio.TimeoutError,
    ):

        return False


async def build_status_snapshot(
    client: httpx.AsyncClient,
):

    (
        brain_status,
        service_status,
    ) = await asyncio.gather(
        check_api_status(
            client,
            config.BRAIN_API_BASE,
        ),
        check_api_status(
            client,
            config.SERVICE_API_BASE,
        ),
    )

    effective_use_service_as_brain = (
        config.USE_SERVICE_AS_BRAIN
        and service_status
    )

    return {
        "brain": brain_status,
        "service": service_status,
        "translator": None,
        "use_service_as_brain": (
            effective_use_service_as_brain
        ),
        "runtime_config": build_runtime_config(
            use_service_as_brain=(
                effective_use_service_as_brain
            ),
        ),
    }


@app.get("/api/status")
async def api_status():

    return await build_status_snapshot(
        app.state.http_client
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
