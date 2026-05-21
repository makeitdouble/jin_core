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

import config

from utils.urls import (
    join_url,
)

from websocket import (
    websocket_router,
)

from clients.clients_registry import (
    build_clients,
)


# ---------------------------------------------------------
# APP LIFESPAN
# ---------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):

    # -----------------------------------------------------
    # SHARED HTTP CLIENT
    # -----------------------------------------------------

    app.state.http_client = httpx.AsyncClient(

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

    app.state.clients = build_clients(
        app.state.http_client
    )

    yield

    # -----------------------------------------------------
    # SHUTDOWN
    # -----------------------------------------------------

    await app.state.http_client.aclose()


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

async def check_api_status(
    client: httpx.AsyncClient,
    base_url: str,
) -> bool:

    try:

        response = await client.get(
            join_url(
                base_url,
                config.MODELS_ENDPOINT,
            )
        )

        return response.status_code == 200

    except (
        httpx.HTTPError,
        asyncio.TimeoutError,
    ):

        return False


@app.get("/api/status")
async def api_status():

    client = app.state.http_client

    (
        brain_status,
        service_status,
        translator_status,
    ) = await asyncio.gather(
        check_api_status(
            client,
            config.BRAIN_API_BASE,
        ),
        check_api_status(
            client,
            config.SERVICE_API_BASE,
        ),
        check_api_status(
            client,
            config.TRANSLATOR_API_BASE,
        ),
    )

    return {
        "brain": brain_status,
        "service": service_status,
        "translator": translator_status,
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
