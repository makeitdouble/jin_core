from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app_settings import settings
from utils.urls import join_url


LM_STUDIO_NATIVE_V1_MODELS_ENDPOINT = "/api/v1/models"
MODEL_LOAD_CONFIG_FIELDS = (
    "context_length",
    "eval_batch_size",
    "flash_attention",
    "num_experts",
    "offload_kv_cache_to_gpu",
)

_model_load_config_cache: dict[
    tuple[str, str],
    dict[str, object],
] = {}
_model_switch_lock = asyncio.Lock()


class RuntimeModelSwitchError(RuntimeError):
    pass


def normalize_model_load_config(value: Any) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}

    normalized: dict[str, object] = {}

    for name in MODEL_LOAD_CONFIG_FIELDS:
        if name not in value:
            continue

        raw_value = value.get(name)

        if name in {
            "flash_attention",
            "offload_kv_cache_to_gpu",
        }:
            if isinstance(raw_value, bool):
                normalized[name] = raw_value
            continue

        try:
            number = int(raw_value)
        except (TypeError, ValueError):
            continue

        if number > 0:
            normalized[name] = number

    return normalized


def _runtime_values(role: str) -> tuple[str, str, int, float]:
    normalized_role = str(role or "").strip().lower()

    if normalized_role == "brain":
        return (
            settings.BRAIN_API_BASE,
            settings.BRAIN_MODEL_UID,
            settings.BRAIN_CONTEXT_WINDOW,
            settings.BRAIN_REQUEST_TIMEOUT,
        )

    if normalized_role == "service" and settings.SERVICE_CONFIGURED:
        return (
            settings.SERVICE_API_BASE,
            settings.SERVICE_MODEL_UID,
            settings.SERVICE_CONTEXT_WINDOW,
            settings.SERVICE_REQUEST_TIMEOUT,
        )

    raise RuntimeModelSwitchError(
        f"Runtime role {normalized_role or '<empty>'} is not configured"
    )


def _cache_key(base_url: str, model_uid: str) -> tuple[str, str]:
    return (
        str(base_url or "").strip().rstrip("/"),
        str(model_uid or "").strip(),
    )


def _remember_load_config(
    base_url: str,
    model_uid: str,
    load_config: Any,
) -> dict[str, object]:
    normalized = normalize_model_load_config(load_config)
    if normalized:
        _model_load_config_cache[
            _cache_key(base_url, model_uid)
        ] = normalized.copy()
    return normalized


def _cached_load_config(
    base_url: str,
    model_uid: str,
) -> dict[str, object]:
    return _model_load_config_cache.get(
        _cache_key(base_url, model_uid),
        {},
    ).copy()


def _native_models_endpoint() -> str:
    configured = str(
        getattr(
            settings,
            "NATIVE_MODELS_ENDPOINT",
            "",
        )
        or ""
    ).strip()

    if "/api/v1/models" in configured:
        return configured.rstrip("/")

    return LM_STUDIO_NATIVE_V1_MODELS_ENDPOINT


def _model_id(model: dict) -> str:
    return str(
        model.get("id")
        or model.get("key")
        or model.get("model")
        or model.get("name")
        or ""
    ).strip()


def _find_model(models: list[dict], model_uid: str) -> dict | None:
    wanted = str(model_uid or "").strip()
    for model in models:
        if _model_id(model) == wanted:
            return model
    return None


def _loaded_instances(model: dict | None) -> list[dict]:
    if not isinstance(model, dict):
        return []

    instances = model.get("loaded_instances")
    if not isinstance(instances, list):
        return []

    return [
        instance
        for instance in instances
        if isinstance(instance, dict)
    ]


def _first_loaded_instance(model: dict | None) -> dict | None:
    instances = _loaded_instances(model)
    return instances[0] if instances else None


def _instance_id(instance: dict | None) -> str:
    if not isinstance(instance, dict):
        return ""
    return str(
        instance.get("id")
        or instance.get("key")
        or instance.get("model")
        or ""
    ).strip()


def _instance_load_config(instance: dict | None) -> dict[str, object]:
    if not isinstance(instance, dict):
        return {}

    config_value = instance.get("config")
    if isinstance(config_value, dict):
        return normalize_model_load_config(config_value)

    return normalize_model_load_config(instance)


def _model_max_context(model: dict | None) -> int:
    if not isinstance(model, dict):
        return 0

    try:
        value = int(
            model.get("max_context_length")
            or model.get("max_context_window")
            or 0
        )
    except (TypeError, ValueError):
        return 0

    return value if value > 0 else 0


def _model_is_embedding(model: dict) -> bool:
    model_type = str(
        model.get("type")
        or model.get("model_type")
        or ""
    ).strip().casefold()
    return model_type in {"embedding", "embeddings"}


def _load_timeout(request_timeout: float) -> float:
    try:
        timeout = float(request_timeout)
    except (TypeError, ValueError):
        timeout = 0.0

    if timeout <= 0:
        timeout = 120.0

    return max(30.0, min(timeout, 1000.0))


def _safe_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0

    return number if number >= 0 else 0.0


def _response_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        candidate = payload.get("error") or payload.get("detail")
        if isinstance(candidate, dict):
            candidate = (
                candidate.get("message")
                or candidate.get("detail")
                or candidate.get("error")
            )
        if candidate:
            return str(candidate).strip()

    try:
        text = str(response.text or "").strip()
    except Exception:
        text = ""

    return text[:1200]


async def _fetch_native_models(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    timeout: float,
) -> list[dict]:
    url = join_url(
        base_url,
        _native_models_endpoint(),
    )

    try:
        response = await client.get(
            url,
            timeout=min(timeout, 10.0),
        )
    except (httpx.HTTPError, asyncio.TimeoutError) as error:
        raise RuntimeModelSwitchError(
            f"LM Studio model catalog is unavailable: {error}"
        ) from error

    if response.status_code != 200:
        detail = _response_error(response)
        suffix = f": {detail}" if detail else ""
        raise RuntimeModelSwitchError(
            f"LM Studio model catalog failed (HTTP {response.status_code}){suffix}"
        )

    try:
        payload = response.json()
    except ValueError as error:
        raise RuntimeModelSwitchError(
            "LM Studio model catalog returned invalid JSON"
        ) from error

    if isinstance(payload, dict):
        models = payload.get("models", payload.get("data", []))
    else:
        models = payload

    if not isinstance(models, list):
        return []

    return [
        model
        for model in models
        if isinstance(model, dict)
    ]


async def _post_model_management(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    suffix: str,
    payload: dict,
    timeout: float,
) -> dict:
    endpoint = f"{_native_models_endpoint()}/{suffix.lstrip('/')}"
    url = join_url(base_url, endpoint)

    try:
        response = await client.post(
            url,
            json=payload,
            timeout=timeout,
        )
    except (httpx.HTTPError, asyncio.TimeoutError) as error:
        raise RuntimeModelSwitchError(
            f"LM Studio model {suffix} request failed: {error}"
        ) from error

    if response.status_code < 200 or response.status_code >= 300:
        detail = _response_error(response)
        suffix_text = f": {detail}" if detail else ""
        raise RuntimeModelSwitchError(
            f"LM Studio model {suffix} failed (HTTP {response.status_code}){suffix_text}"
        )

    try:
        result = response.json()
    except ValueError:
        result = {}

    return result if isinstance(result, dict) else {}


def _other_runtime_uses_model(
    role: str,
    *,
    base_url: str,
    model_uid: str,
) -> bool:
    normalized_base = str(base_url or "").strip().rstrip("/")
    normalized_model = str(model_uid or "").strip()

    if role == "brain":
        if not settings.SERVICE_CONFIGURED:
            return False
        return (
            str(settings.SERVICE_API_BASE or "").strip().rstrip("/")
            == normalized_base
            and str(settings.SERVICE_MODEL_UID or "").strip()
            == normalized_model
        )

    return (
        str(settings.BRAIN_API_BASE or "").strip().rstrip("/")
        == normalized_base
        and str(settings.BRAIN_MODEL_UID or "").strip()
        == normalized_model
    )


async def _load_model(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    model_uid: str,
    load_config: dict[str, object],
    timeout: float,
) -> dict:
    payload = {
        "model": model_uid,
        **normalize_model_load_config(load_config),
        "echo_load_config": True,
    }
    return await _post_model_management(
        client,
        base_url=base_url,
        suffix="load",
        payload=payload,
        timeout=timeout,
    )


async def initialize_runtime_model(
    client: httpx.AsyncClient,
    *,
    role: str,
    model_uid: str,
    base_url: str | None = None,
    cached_load_config: Any = None,
) -> dict[str, object]:
    normalized_role = str(role or "").strip().lower()
    target_model_uid = str(model_uid or "").strip()
    if not target_model_uid:
        raise RuntimeModelSwitchError("Model is required")

    async with _model_switch_lock:
        (
            current_base_url,
            current_model_uid,
            configured_context_window,
            request_timeout,
        ) = _runtime_values(normalized_role)
        target_base_url = (
            str(base_url or current_base_url).strip().rstrip("/")
        )
        if not target_base_url:
            raise RuntimeModelSwitchError("Runtime endpoint is required")

        same_runtime_endpoint = (
            str(current_base_url or "").strip().rstrip("/")
            == target_base_url
        )
        base_url = target_base_url
        timeout = _load_timeout(request_timeout)
        models = await _fetch_native_models(
            client,
            base_url=base_url,
            timeout=timeout,
        )
        target_model = _find_model(models, target_model_uid)

        if target_model is None:
            raise RuntimeModelSwitchError(
                f"Model {target_model_uid} is not available in LM Studio"
            )

        if _model_is_embedding(target_model):
            raise RuntimeModelSwitchError(
                f"Model {target_model_uid} is an embedding model, not a Brain runtime"
            )

        current_model = (
            _find_model(models, current_model_uid)
            if same_runtime_endpoint
            else None
        )
        current_instance = _first_loaded_instance(current_model)
        current_instance_id = _instance_id(current_instance)
        current_load_config = _instance_load_config(current_instance)
        if current_instance is not None:
            if not current_load_config and configured_context_window > 0:
                current_load_config = {
                    "context_length": configured_context_window,
                }
            _remember_load_config(
                base_url,
                current_model_uid,
                current_load_config,
            )

        unloaded_current = False
        if (
            same_runtime_endpoint
            and current_model_uid != target_model_uid
            and current_instance_id
            and not _other_runtime_uses_model(
                normalized_role,
                base_url=base_url,
                model_uid=current_model_uid,
            )
        ):
            await _post_model_management(
                client,
                base_url=base_url,
                suffix="unload",
                payload={
                    "instance_id": current_instance_id,
                },
                timeout=min(timeout, 30.0),
            )
            unloaded_current = True

        target_instance = _first_loaded_instance(target_model)
        if target_instance is not None:
            load_config = _instance_load_config(target_instance)
            if not load_config:
                load_config = _cached_load_config(
                    base_url,
                    target_model_uid,
                )
            if not load_config and configured_context_window > 0:
                load_config = {
                    "context_length": configured_context_window,
                }
            _remember_load_config(
                base_url,
                target_model_uid,
                load_config,
            )
            return {
                "role": normalized_role,
                "base_url": base_url,
                "model": target_model_uid,
                "instance_id": _instance_id(target_instance),
                "load_config": load_config,
                "cache_hit": True,
                "load_time_seconds": 0.0,
            }

        requested_load_config = normalize_model_load_config(
            cached_load_config
        )
        if not requested_load_config:
            requested_load_config = _cached_load_config(
                base_url,
                target_model_uid,
            )
        if not requested_load_config and configured_context_window > 0:
            requested_load_config = {
                "context_length": configured_context_window,
            }

        max_context = _model_max_context(target_model)
        requested_context = int(
            requested_load_config.get("context_length", 0)
            or 0
        )
        if max_context > 0 and requested_context > max_context:
            requested_load_config["context_length"] = max_context

        try:
            load_result = await _load_model(
                client,
                base_url=base_url,
                model_uid=target_model_uid,
                load_config=requested_load_config,
                timeout=timeout,
            )
        except RuntimeModelSwitchError as load_error:
            # LM Studio can complete the load side effect even when the
            # request fails late. Reconcile against the native catalog before
            # reporting failure or rolling the previous model back.
            recovered_instance = None
            recovered_load_config: dict[str, object] = {}
            try:
                refreshed_models = await _fetch_native_models(
                    client,
                    base_url=base_url,
                    timeout=timeout,
                )
                recovered_model = _find_model(
                    refreshed_models,
                    target_model_uid,
                )
                recovered_instance = _first_loaded_instance(
                    recovered_model
                )
                recovered_load_config = _instance_load_config(
                    recovered_instance
                )
            except RuntimeModelSwitchError:
                recovered_instance = None

            if recovered_instance is not None:
                if not recovered_load_config:
                    recovered_load_config = requested_load_config
                _remember_load_config(
                    base_url,
                    target_model_uid,
                    recovered_load_config,
                )
                return {
                    "role": normalized_role,
                    "base_url": base_url,
                    "model": target_model_uid,
                    "instance_id": _instance_id(recovered_instance),
                    "load_config": recovered_load_config,
                    "cache_hit": False,
                    "load_time_seconds": 0.0,
                    "recovered_after_load_error": True,
                }

            if not unloaded_current or not current_model_uid:
                raise

            rollback_error = None
            rollback_config = (
                current_load_config
                or _cached_load_config(
                    base_url,
                    current_model_uid,
                )
            )
            try:
                await _load_model(
                    client,
                    base_url=base_url,
                    model_uid=current_model_uid,
                    load_config=rollback_config,
                    timeout=timeout,
                )
            except RuntimeModelSwitchError as error:
                rollback_error = error

            rollback_suffix = (
                f"; rollback failed: {rollback_error}"
                if rollback_error is not None
                else "; previous model restored"
            )
            raise RuntimeModelSwitchError(
                f"Model load failed after unloading "
                f"{current_model_uid}: {load_error}"
                f"{rollback_suffix}"
            ) from load_error

        load_config = normalize_model_load_config(
            load_result.get("load_config")
        )
        if not load_config:
            load_config = requested_load_config

        _remember_load_config(
            base_url,
            target_model_uid,
            load_config,
        )

        return {
            "role": normalized_role,
            "base_url": base_url,
            "model": target_model_uid,
            "instance_id": str(
                load_result.get("instance_id")
                or load_result.get("model_instance_id")
                or target_model_uid
            ).strip(),
            "load_config": load_config,
            "cache_hit": False,
            "load_time_seconds": _safe_float(
                load_result.get("load_time_seconds")
            ),
        }
