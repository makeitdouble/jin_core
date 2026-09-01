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
    HTMLResponse,
)

from fastapi.staticfiles import (
    StaticFiles,
)

from fastapi.templating import (
    Jinja2Templates,
)

import asyncio
import ast
import httpx
import json
from pathlib import Path

from config_loader import (
    config,
    ROOT as CONFIG_ROOT,
)
from app_settings import (
    settings,
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
from runtime.model_switch import (
    RuntimeModelSwitchError,
    initialize_runtime_model,
)
from runtime.LT_memory import (
    start_lt_memory_server_scheduler,
    stop_lt_memory_server_scheduler,
)

from runtime.registry import runtime_state
from runtime.state import (
    BRAIN_RUNTIME_ID,
    SERVICE_RUNTIME_ID,
)
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

    start_lt_memory_server_scheduler(
        application.state
    )

    yield

    # -----------------------------------------------------
    # SHUTDOWN
    # -----------------------------------------------------

    await stop_lt_memory_server_scheduler(
        application.state
    )
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


# ---------------------------------------------------------
# INDEX PAGE
# ---------------------------------------------------------

def _runtime_status_context_window(status: dict | None) -> int:
    try:
        value = int((status or {}).get("context_window") or 0)
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0


def build_runtime_config(
    *,
    brain_status: dict | None = None,
    service_status: dict | None = None,
):
    brain_context_window = _runtime_status_context_window(
        brain_status
    )
    service_context_window = _runtime_status_context_window(
        service_status
    )
    if not settings.SERVICE_CONFIGURED:
        service_context_window = brain_context_window

    return {
        "service": {
            "label": "service",
            "api_base": config.SERVICE_API_BASE,
            "model": config.SERVICE_MODEL_UID,
            "used_tokens": 0,
            "context_tokens": 0,
            "total_tokens": 0,
            "max_tokens": service_context_window,
        },
        "brain": {
            "label": "brain",
            "api_base": config.BRAIN_API_BASE,
            "model": config.BRAIN_MODEL_UID,
            "used_tokens": 0,
            "context_tokens": 0,
            "total_tokens": 0,
            "max_tokens": brain_context_window,
        },
    }


RUNTIME_CONFIG_WRITE_FIELDS = {
    "service": {
        "model": "SERVICE_MODEL_UID",
    },
    "brain": {
        "model": "BRAIN_MODEL_UID",
    },
}

RUNTIME_CONFIG_API_BASE_FIELDS = {
    "service": "SERVICE_API_BASE",
    "brain": "BRAIN_API_BASE",
}

def normalize_runtime_endpoint_base(base_url: object) -> str:
    return str(base_url or "").strip().rstrip("/")


def _format_config_literal(value):

    if isinstance(value, str):
        return repr(value)

    if isinstance(value, bool):
        return "True" if value else "False"

    return str(value)


def write_runtime_config_values(updates: dict[str, object]) -> None:

    config_path = CONFIG_ROOT / "config.py"

    if not config_path.exists():
        raise FileNotFoundError(
            f"config.py not found at {config_path}"
        )

    text = config_path.read_text(
        encoding="utf-8"
    )
    tree = ast.parse(
        text
    )
    lines = text.splitlines()
    replaced: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue

        for target in node.targets:
            if (
                not isinstance(target, ast.Name)
                or target.id not in updates
            ):
                continue

            if (
                getattr(node, "end_lineno", node.lineno)
                != node.lineno
            ):
                raise ValueError(
                    f"Cannot rewrite multiline config value {target.id}"
                )

            line_index = node.lineno - 1
            current_line = lines[line_index]
            indent = current_line[
                :len(current_line) - len(current_line.lstrip())
            ]
            lines[line_index] = (
                f"{indent}{target.id} = "
                f"{_format_config_literal(updates[target.id])}"
            )
            replaced.add(target.id)

    missing = [
        name
        for name in updates
        if name not in replaced
    ]

    if missing and lines and lines[-1].strip():
        lines.append("")

    for name in missing:
        lines.append(
            f"{name} = {_format_config_literal(updates[name])}"
        )

    config_path.write_text(
        "\n".join(lines).rstrip() + "\n",
        encoding="utf-8",
    )


def apply_runtime_config_values(
    updates: dict[str, object],
    application: FastAPI | None = None,
) -> None:

    for name, value in updates.items():
        setattr(
            config,
            name,
            value,
        )

        if hasattr(settings, name):
            object.__setattr__(
                settings,
                name,
                value,
            )

    if not settings.SERVICE_CONFIGURED:
        fallback_pairs = {
            "SERVICE_API_BASE": "BRAIN_API_BASE",
            "SERVICE_MODEL_UID": "BRAIN_MODEL_UID",
            "SERVICE_REQUEST_TIMEOUT": "BRAIN_REQUEST_TIMEOUT",
        }
        for service_name, brain_name in fallback_pairs.items():
            value = getattr(
                config,
                brain_name,
            )
            setattr(
                config,
                service_name,
                value,
            )
            object.__setattr__(
                settings,
                service_name,
                value,
            )

    runtime_state.update_runtime_state(
        BRAIN_RUNTIME_ID,
        model=settings.BRAIN_MODEL_UID,
        max_tokens=0,
    )
    runtime_state.update_runtime_state(
        SERVICE_RUNTIME_ID,
        model=settings.SERVICE_MODEL_UID,
        max_tokens=0,
    )

    if (
        application is None
        or not hasattr(application.state, "http_client")
    ):
        return

    next_clients = build_clients(
        application.state.http_client
    )
    current_clients = getattr(
        application.state,
        "clients",
        None,
    )

    if isinstance(current_clients, dict):
        current_clients.clear()
        current_clients.update(
            next_clients
        )
    else:
        application.state.clients = next_clients


def compact_runtime_model_options(models: list[dict]) -> list[dict]:

    options = []
    seen = set()

    for model in models:
        model_type = str(
            model.get("type")
            or model.get("model_type")
            or ""
        ).strip().casefold()
        if model_type in {
            "embedding",
            "embeddings",
        }:
            continue

        model_id = (
            model.get("id")
            or model.get("key")
            or model.get("model")
            or model.get("name")
        )
        model_id = str(model_id or "").strip()

        if not model_id or model_id in seen:
            continue

        display_name = (
            model.get("display_name")
            or model.get("name")
            or model.get("label")
            or model_id
        )
        options.append({
            "id": model_id,
            "name": str(display_name or model_id).strip(),
        })
        seen.add(model_id)

    return options


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
            "runtime_config": (
                status_snapshot[
                    "runtime_config"
                ]
            ),
            "runtime_status": {
                "brain": status_snapshot["brain"],
                "service": status_snapshot["service"],
                "service_configured": (
                    status_snapshot[
                        "service_configured"
                    ]
                ),
            },
            "format_response": (
                status_snapshot["format_response"]
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
):

    runtime = RuntimeClient(
        api_base=base_url,
        model_uid=model_uid,
        timeout=STATUS_CHECK_TIMEOUT,
        client=client,
    )

    online = False
    attempted_url = ""
    detected_url = ""
    detected_source = ""
    available_models = []
    best_status = None

    for endpoint in runtime.model_limits_detection_endpoints():
        request_url = join_url(base_url, endpoint)

        if not attempted_url:
            attempted_url = request_url

        try:
            response = await client.get(
                request_url,
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
        detected_url = request_url
        detected_source = (
            "openai"
            if endpoint == config.MODELS_ENDPOINT
            else "native"
        )

        try:
            models = runtime.extract_model_list(
                response.json()
            )
        except ValueError:
            continue

        available_models = compact_runtime_model_options(
            models
        )
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
        context_window = runtime.extract_context_window_from_model(
            loaded_model
        )

        candidate_status = {
            "online": True,
            "source": detected_source,
            "url": detected_url,
            "available_models": available_models,
            "loaded": loaded,
            "model": model,
            "loaded_model": loaded_model or {},
            "context_window": context_window or 0,
        }
        if best_status is None:
            best_status = candidate_status

        # A catalog entry without a live context window is not enough for the
        # panel. Keep probing the remaining provider endpoints until one of
        # them reports the actual loaded n_ctx/context_length.
        if context_window:
            return candidate_status

    if best_status is not None:
        return best_status

    return {
        "online": online,
        "source": detected_source,
        "url": detected_url or attempted_url,
        "available_models": available_models,
        "loaded": None,
        "model": {},
        "loaded_model": {},
        "context_window": 0,
    }


async def build_status_snapshot(
    client: httpx.AsyncClient,
):

    brain_request = fetch_runtime_model_status(
        client,
        base_url=config.BRAIN_API_BASE,
        model_uid=config.BRAIN_MODEL_UID,
    )

    if settings.SERVICE_CONFIGURED:
        brain_status, service_status = await asyncio.gather(
            brain_request,
            fetch_runtime_model_status(
                client,
                base_url=config.SERVICE_API_BASE,
                model_uid=config.SERVICE_MODEL_UID,
            ),
        )
    else:
        brain_status = await brain_request
        service_status = {
            "online": False,
            "source": "",
            "url": "",
            "available_models": [],
            "loaded": None,
            "model": {},
            "loaded_model": {},
            "context_window": 0,
        }

    brain_online = bool(brain_status.get("online"))
    service_online = bool(service_status.get("online"))

    brain_context_window = _runtime_status_context_window(
        brain_status
    )
    service_context_window = (
        _runtime_status_context_window(service_status)
        if settings.SERVICE_CONFIGURED
        else brain_context_window
    )
    runtime_state.update_runtime_state(
        BRAIN_RUNTIME_ID,
        model=settings.BRAIN_MODEL_UID,
        max_tokens=brain_context_window,
        status="online" if brain_online else "offline",
    )
    runtime_state.update_runtime_state(
        SERVICE_RUNTIME_ID,
        model=settings.SERVICE_MODEL_UID,
        max_tokens=service_context_window,
        status=(
            "online"
            if settings.SERVICE_CONFIGURED and service_online
            else "offline"
        ),
    )

    runtime_config = build_runtime_config(
        brain_status=brain_status,
        service_status=service_status,
    )
    runtime_config["service"]["lm_studio"] = service_status
    runtime_config["brain"]["lm_studio"] = brain_status

    return {
        "brain": brain_online,
        "service": service_online,
        "service_configured": settings.SERVICE_CONFIGURED,
        "service_route": (
            "dedicated"
            if settings.SERVICE_CONFIGURED
            else "brain_fallback"
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




@app.post("/api/runtime-model/switch")
async def api_switch_runtime_model(request: Request):

    try:
        payload = await request.json()
    except json.JSONDecodeError as error:
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON",
        ) from error

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400,
            detail="Invalid payload",
        )

    role = str(
        payload.get("role") or ""
    ).strip().lower()
    role_fields = RUNTIME_CONFIG_WRITE_FIELDS.get(
        role
    )

    if role_fields is None:
        raise HTTPException(
            status_code=400,
            detail="Invalid runtime role",
        )

    if (
        role == "service"
        and not settings.SERVICE_CONFIGURED
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Dedicated Service runtime is not configured"
            ),
        )

    model = str(
        payload.get("model") or ""
    ).strip()
    if not model:
        raise HTTPException(
            status_code=400,
            detail="Model is required",
        )

    current_base = normalize_runtime_endpoint_base(
        getattr(
            settings,
            RUNTIME_CONFIG_API_BASE_FIELDS[role],
        )
    )
    requested_base = normalize_runtime_endpoint_base(
        payload.get("base_url") or current_base
    )
    if not current_base:
        raise HTTPException(
            status_code=400,
            detail="Runtime endpoint is not configured",
        )
    if requested_base != current_base:
        raise HTTPException(
            status_code=400,
            detail="Runtime endpoint cannot be switched here",
        )

    try:
        switch_result = await initialize_runtime_model(
            app.state.http_client,
            role=role,
            model_uid=model,
            base_url=current_base,
            cached_load_config=payload.get("load_config"),
        )
    except RuntimeModelSwitchError as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        ) from error

    updates: dict[str, object] = {
        role_fields["model"]: model,
    }

    try:
        write_runtime_config_values(updates)
        apply_runtime_config_values(
            updates,
            app,
        )
    except Exception as error:
        # LM Studio has already completed the load at this point. Keep a local
        # sync failure distinct from a model-load failure in the modal.
        raise HTTPException(
            status_code=500,
            detail=(
                "Model loaded in LM Studio, but JIN failed to sync "
                f"runtime config: {error}"
            ),
        ) from error

    try:
        snapshot = await build_status_snapshot(
            app.state.http_client
        )
    except Exception as error:
        # Status metadata is presentation data. A failed refresh must not turn
        # an already completed model switch into a false HTTP 500.
        switch_result["status_refresh_error"] = (
            f"{type(error).__name__}: {error}"
        )
        fallback_status = {
            "online": True,
            "source": "native",
            "url": current_base,
            "available_models": [],
            "loaded": True,
            "model": {
                "key": model,
                "id": model,
            },
            "loaded_model": {
                "id": switch_result.get("instance_id") or model,
                "config": switch_result.get("load_config") or {},
            },
        }
        fallback_status["context_window"] = (
            RuntimeClient.extract_context_window_from_model(
                fallback_status["loaded_model"]
            )
            or 0
        )
        brain_fallback_status = (
            fallback_status
            if role == "brain"
            else None
        )
        service_fallback_status = (
            fallback_status
            if role == "service"
            else None
        )
        runtime_config = build_runtime_config(
            brain_status=brain_fallback_status,
            service_status=service_fallback_status,
        )
        runtime_config[role]["lm_studio"] = fallback_status
        snapshot = {
            "brain": (
                role == "brain"
                or runtime_state.get_runtime_state(
                    BRAIN_RUNTIME_ID
                ).get("status") == "online"
            ),
            "service": (
                settings.SERVICE_CONFIGURED
                and (
                    role == "service"
                    or runtime_state.get_runtime_state(
                        SERVICE_RUNTIME_ID
                    ).get("status") == "online"
                )
            ),
            "service_configured": settings.SERVICE_CONFIGURED,
            "service_route": (
                "dedicated"
                if settings.SERVICE_CONFIGURED
                else "brain_fallback"
            ),
            "format_response": bool(
                getattr(config, "FORMAT_RESPONSE", True)
            ),
            "runtime_config": runtime_config,
        }

    snapshot["model_switch"] = switch_result
    return snapshot


@app.post("/api/runtime-config")
async def api_update_runtime_config(request: Request):

    try:
        payload = await request.json()
    except json.JSONDecodeError as error:
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON",
        ) from error

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400,
            detail="Invalid payload",
        )

    role = str(
        payload.get("role") or ""
    ).strip().lower()
    role_fields = RUNTIME_CONFIG_WRITE_FIELDS.get(
        role
    )

    if role_fields is None:
        raise HTTPException(
            status_code=400,
            detail="Invalid runtime role",
        )

    if (
        role == "service"
        and not settings.SERVICE_CONFIGURED
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Dedicated Service runtime is not configured"
            ),
        )

    updates: dict[str, object] = {}

    if "model" in payload:
        model = str(
            payload.get("model") or ""
        ).strip()

        if not model:
            raise HTTPException(
                status_code=400,
                detail="Model is required",
            )

        updates[role_fields["model"]] = model

    if not updates:
        raise HTTPException(
            status_code=400,
            detail="No runtime config changes",
        )

    try:
        write_runtime_config_values(
            updates
        )
        apply_runtime_config_values(
            updates,
            app,
        )
    except (
        FileNotFoundError,
        ValueError,
        OSError,
    ) as error:
        raise HTTPException(
            status_code=500,
            detail=str(error),
        ) from error

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
