from contextlib import asynccontextmanager

from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    Request,
)

from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    Response,
)

from fastapi.staticfiles import (
    StaticFiles,
)

from fastapi.templating import (
    Jinja2Templates,
)

import asyncio
import httpx
from pathlib import Path

from config_loader import (
    config,
)

from utils.urls import (
    join_url,
)

from websocket import (
    websocket_router,
)

from clients import (
    build_clients,
)

from runtime import (
    RUNTIME_MEMORY_SUMMARIZER_LABEL,
)
from runtime.behavior_contract import (
    get_behavior_contract,
)
from utils.rule_citations import (
    get_rule_citation_registry,
)
from utils.assets_service import (
    read_asset_text_preview,
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
    directory="ui/templates",
)

app.mount(
    "/static",
    StaticFiles(directory="ui/static"),
    name="static",
)

app.include_router(
    websocket_router
)


@app.get(
    "/saved_runtime.txt",
)
async def saved_runtime_file():

    saved_runtime_path = Path(
        "saved_runtime.txt"
    )

    if not saved_runtime_path.is_file():
        return Response(
            status_code=404
        )

    return FileResponse(
        saved_runtime_path,
        media_type="text/plain; charset=utf-8",
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
            "context_tokens": 0,
            "total_tokens": 0,
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
            "context_tokens": 0,
            "total_tokens": 0,
            "max_tokens": (
                config.SERVICE_CONTEXT_WINDOW
                if effective_use_service_as_brain
                else config.BRAIN_CONTEXT_WINDOW
            ),
        },
        RUNTIME_MEMORY_SUMMARIZER_LABEL: {
            "label": RUNTIME_MEMORY_SUMMARIZER_LABEL,
            "model": config.SERVICE_MODEL_UID,
            "used_tokens": 0,
            "context_tokens": 0,
            "total_tokens": 0,
            "max_tokens": config.SERVICE_CONTEXT_WINDOW,
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


@app.get("/api/behavior-contract")
async def api_behavior_contract():

    return get_behavior_contract()


@app.get("/api/assets/text-preview")
async def api_asset_text_preview(
    path: str = Query(...),
    max_chars: int = Query(60000),
):

    try:
        return read_asset_text_preview({
            "path": path,
            "max_chars": max_chars,
        })
    except FileNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error
    except UnicodeDecodeError as error:
        raise HTTPException(
            status_code=415,
            detail="asset is not readable as utf-8 text",
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error


@app.get("/api/debug/rule-citations")
async def api_debug_rule_citations():

    enabled = bool(
        getattr(
            config,
            "DEBUG_RULE_CITATIONS",
            True,
        )
    )

    if not enabled:
        return {
            "enabled": False,
            "version": "disabled",
            "fragmentCount": 0,
            "fragments": [],
        }

    registry = get_rule_citation_registry()

    return {
        "enabled": True,
        **registry,
    }


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
