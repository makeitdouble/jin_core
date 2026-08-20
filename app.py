from contextlib import asynccontextmanager

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
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
import json
from pathlib import Path

from config_loader import (
    config,
)

from utils.urls import (
    join_url,
)
from utils.chat_log import (
    migrate_legacy_chat_logs,
)
from utils.session_restore import (
    build_archived_session_restore_payload,
)

from websocket import (
    websocket_router,
)

from clients.registry import build_clients
from runtime.client import RuntimeClient

from runtime.state import RUNTIME_MEMORY_SUMMARIZER_LABEL
from runtime.behavior_contract import (
    get_behavior_contract,
)
from utils.rule_citations import (
    get_rule_citation_registry,
)
from utils.file_manager_asset_utils import (
    read_asset_text_preview,
)
from utils.attached_files_store import (
    FILES_DIR,
    delete_file_record,
    ensure_files_dir,
    get_file_record,
    public_file_snapshot,
    restore_file_record,
    set_file_pinned,
    store_uploaded_file,
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

    ensure_files_dir()
    migrate_legacy_chat_logs()

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

ensure_files_dir()
app.mount(
    "/assets/files",
    StaticFiles(directory=str(FILES_DIR)),
    name="attached_files",
)

app.include_router(
    websocket_router
)


@app.get("/api/sessions/{session_id}/restore")
async def api_restore_archived_session(session_id: str):
    payload = build_archived_session_restore_payload(
        session_id
    )

    if payload is None:
        raise HTTPException(
            status_code=404,
            detail="Archived session not found",
        )

    return payload


@app.get("/api/files")
async def api_list_files():
    return public_file_snapshot()


@app.post("/api/files/upload")
async def api_upload_file(
    file: UploadFile = File(...),
    width: str = Form(""),
    height: str = Form(""),
):
    content = await file.read()

    def parse_dimension(value):
        try:
            number = int(str(value or "").strip())
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    record, created, pin_error = store_uploaded_file(
        name=file.filename or "attachment",
        content=content,
        mime_type=file.content_type or "",
        width=parse_dimension(width),
        height=parse_dimension(height),
        pin=True,
    )
    return {
        "file": record,
        "created": created,
        "pin_error": pin_error,
        **public_file_snapshot(),
    }


@app.post("/api/files/{file_id}/pin")
async def api_pin_file(
    file_id: str,
    pinned: bool = Query(True),
):
    record, error = set_file_pinned(file_id, pinned)
    if record is None:
        raise HTTPException(status_code=404, detail="File not found")
    if error == "max_attached_files":
        raise HTTPException(status_code=409, detail="Maximum 5 attached files")
    return {
        "file": record,
        **public_file_snapshot(),
    }


@app.delete("/api/files/{file_id}")
async def api_delete_file(file_id: str):
    if not delete_file_record(file_id):
        raise HTTPException(status_code=404, detail="File not found")
    return public_file_snapshot()


@app.post("/api/files/{file_id}/restore")
async def api_restore_file(
    file_id: str,
    file: UploadFile = File(...),
    record: str = Form("{}"),
):
    try:
        metadata = json.loads(record or "{}")
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=400, detail="Invalid file restore metadata") from error

    if not isinstance(metadata, dict):
        raise HTTPException(status_code=400, detail="Invalid file restore metadata")

    restored, error = restore_file_record(
        file_id,
        record=metadata,
        content=await file.read(),
    )
    if restored is None:
        status = 409 if error == "id_exists" else 400
        raise HTTPException(status_code=status, detail=error or "File restore failed")

    return {
        "file": restored,
        **public_file_snapshot(),
    }


@app.get("/api/files/{file_id}/preview")
async def api_preview_file(file_id: str):
    record = get_file_record(file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="File not found")
    payload = {"file": record}
    if record.get("kind") == "text":
        path = FILES_DIR / record["stored_name"]
        try:
            payload["text_content"] = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            payload["text_content"] = ""
    return payload


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

def build_anonymous_mode_config():
    return {
        "ENABLE_DEFAULT_ANONYMOUS_MODE": bool(
            getattr(
                config,
                "ENABLE_DEFAULT_ANONYMOUS_MODE",
                True,
            )
        ),
        "ENABLE_GLOBAL_ANONYMOUS_MODE": bool(
            getattr(
                config,
                "ENABLE_GLOBAL_ANONYMOUS_MODE",
                False,
            )
        ),
    }


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
            "format_response": (
                status_snapshot["format_response"]
            ),
            "anonymous_mode_config": (
                build_anonymous_mode_config()
            ),
        },
    )


# ---------------------------------------------------------
# API STATUS
# ---------------------------------------------------------

async def fetch_runtime_model_status(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    model_uid: str,
    configured_context_window: int,
):

    runtime = RuntimeClient(
        api_base=base_url,
        model_uid=model_uid,
        timeout=STATUS_CHECK_TIMEOUT,
        configured_context_window=configured_context_window,
        client=client,
    )

    online = False

    for endpoint in runtime.model_limits_detection_endpoints():

        try:
            response = await client.get(
                join_url(base_url, endpoint),
                timeout=STATUS_CHECK_TIMEOUT,
            )
        except (
            httpx.HTTPError,
            asyncio.TimeoutError,
        ):
            continue

        if response.status_code != 200:
            continue

        online = True

        try:
            models = runtime.extract_model_list(
                response.json()
            )
        except ValueError:
            continue

        model = runtime.select_model_metadata(models)

        if model is None:
            continue

        loaded_model = runtime.select_loaded_model_metadata(
            model
        )
        loaded_instances = model.get("loaded_instances")
        loaded = (
            loaded_model is not None
            if isinstance(loaded_instances, list)
            else None
        )

        return {
            "online": True,
            "source": (
                "openai"
                if endpoint == config.MODELS_ENDPOINT
                else "native"
            ),
            "loaded": loaded,
            "model": model,
            "loaded_model": loaded_model or {},
        }

    return {
        "online": online,
        "source": "",
        "loaded": None,
        "model": {},
        "loaded_model": {},
    }


async def build_status_snapshot(
    client: httpx.AsyncClient,
):

    service_request = fetch_runtime_model_status(
        client,
        base_url=config.SERVICE_API_BASE,
        model_uid=config.SERVICE_MODEL_UID,
        configured_context_window=(
            config.SERVICE_CONTEXT_WINDOW
        ),
    )

    if config.USE_SERVICE_AS_BRAIN:
        service_status = await service_request
        brain_status = service_status
    else:
        (
            brain_status,
            service_status,
        ) = await asyncio.gather(
            fetch_runtime_model_status(
                client,
                base_url=config.BRAIN_API_BASE,
                model_uid=config.BRAIN_MODEL_UID,
                configured_context_window=(
                    config.BRAIN_CONTEXT_WINDOW
                ),
            ),
            service_request,
        )

    brain_online = bool(brain_status.get("online"))
    service_online = bool(service_status.get("online"))

    effective_use_service_as_brain = (
        config.USE_SERVICE_AS_BRAIN
        and service_online
    )

    runtime_config = build_runtime_config(
        use_service_as_brain=(
            effective_use_service_as_brain
        ),
    )
    runtime_config["service"]["lm_studio"] = service_status
    runtime_config["brain"]["lm_studio"] = brain_status

    return {
        "brain": brain_online,
        "service": service_online,
        "translator": None,
        "use_service_as_brain": (
            effective_use_service_as_brain
        ),
        "format_response": bool(
            getattr(
                config,
                "FORMAT_RESPONSE",
                True,
            )
        ),
        "runtime_config": runtime_config,
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
        ws_max_size=int(
            getattr(
                config,
                "WEBSOCKET_MAX_MESSAGE_BYTES",
                64 * 1024 * 1024,
            )
            or 64 * 1024 * 1024
        ),
    )
