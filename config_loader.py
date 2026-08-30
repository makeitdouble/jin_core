from importlib import util
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ENV_PREFIX = "JIN_"


def parse_env_value(
    *,
    name: str,
    raw_value: str,
    current_value,
):

    if isinstance(current_value, bool):

        normalized = (
            raw_value
            .strip()
            .lower()
        )

        if normalized in {
            "1",
            "true",
            "yes",
            "on",
        }:
            return True

        if normalized in {
            "0",
            "false",
            "no",
            "off",
        }:
            return False

        raise ValueError(
            f"Invalid boolean env value for {name}: {raw_value!r}"
        )

    if isinstance(current_value, int):
        return int(
            raw_value
        )

    if isinstance(current_value, float):
        return float(
            raw_value
        )

    return raw_value


def get_env_override(
    name: str,
) -> str | None:

    if name in os.environ:
        return os.environ[name]

    prefixed_name = f"{ENV_PREFIX}{name}"

    return os.environ.get(
        prefixed_name
    )


def apply_env_overrides(
    config_module,
):

    for name in dir(config_module):

        if not name.isupper():
            continue

        raw_value = get_env_override(
            name
        )

        if raw_value is None:
            continue

        current_value = getattr(
            config_module,
            name,
        )

        setattr(
            config_module,
            name,
            parse_env_value(
                name=name,
                raw_value=raw_value,
                current_value=current_value,
            ),
        )

    return config_module


def normalize_model_role_config(
    config_module,
):
    """Resolve the optional Service role onto the required Brain runtime.

    ``USE_SERVICE_AS_BRAIN`` is accepted only as a legacy config adapter. It
    is deliberately removed from the normalized module so no runtime path can
    branch on the old topology.
    """

    legacy_service_as_brain = getattr(
        config_module,
        "USE_SERVICE_AS_BRAIN",
        None,
    )

    if legacy_service_as_brain is True:
        for suffix in (
            "API_BASE",
            "MODEL_UID",
            "REQUEST_TIMEOUT",
        ):
            service_name = f"SERVICE_{suffix}"
            brain_name = f"BRAIN_{suffix}"
            service_value = getattr(
                config_module,
                service_name,
                None,
            )
            if service_value not in (
                None,
                "",
                0,
                0.0,
            ):
                setattr(
                    config_module,
                    brain_name,
                    service_value,
                )

        # The legacy Service endpoint becomes the canonical Brain endpoint;
        # background work therefore falls back to it instead of activating a
        # second physical runtime accidentally.
        setattr(
            config_module,
            "SERVICE_API_BASE",
            "",
        )

    if hasattr(
        config_module,
        "USE_SERVICE_AS_BRAIN",
    ):
        delattr(
            config_module,
            "USE_SERVICE_AS_BRAIN",
        )

    raw_service_api_base = str(
        getattr(
            config_module,
            "SERVICE_API_BASE",
            "",
        )
        or ""
    ).strip()
    service_configured = bool(
        raw_service_api_base
    )

    setattr(
        config_module,
        "SERVICE_CONFIGURED",
        service_configured,
    )

    brain_fallbacks = {
        "SERVICE_API_BASE": getattr(
            config_module,
            "BRAIN_API_BASE",
        ),
        "SERVICE_MODEL_UID": getattr(
            config_module,
            "BRAIN_MODEL_UID",
        ),
        "SERVICE_REQUEST_TIMEOUT": getattr(
            config_module,
            "BRAIN_REQUEST_TIMEOUT",
        ),
    }

    for name, fallback in brain_fallbacks.items():
        value = getattr(
            config_module,
            name,
            None,
        )
        if (
            not service_configured
            or value in (
                None,
                "",
                0,
                0.0,
            )
        ):
            setattr(
                config_module,
                name,
                fallback,
            )

    return config_module


def load_config_from_path(
    path: Path,
):

    spec = util.spec_from_file_location(
        path.stem,
        path,
    )

    if (
        spec is None
        or spec.loader is None
    ):
        raise RuntimeError(
            f"Unable to load config from {path}"
        )

    module = util.module_from_spec(
        spec
    )

    spec.loader.exec_module(
        module
    )

    return module


def load_config_module(
    *,
    config_path: Path | None = None,
    example_path: Path | None = None,
):

    if config_path is None:
        config_path = ROOT / "config.py"

    if example_path is None:
        example_path = ROOT / "config.example.py"

    if config_path.exists():
        return normalize_model_role_config(
            apply_env_overrides(
                load_config_from_path(
                    config_path
                )
            )
        )

    if example_path.exists():
        return normalize_model_role_config(
            apply_env_overrides(
                load_config_from_path(
                    example_path
                )
            )
        )

    raise FileNotFoundError(
        f"config not found at {config_path} "
        f"or {example_path}"
    )


config = load_config_module()
