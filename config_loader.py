from importlib import import_module
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

        try:
            return apply_env_overrides(
                import_module(
                    "config"
                )
            )

        except ModuleNotFoundError as error:

            if error.name != "config":
                raise

    else:

        if config_path.exists():
            return apply_env_overrides(
                load_config_from_path(
                    config_path
                )
            )

    fallback_path = (
        example_path
        or ROOT / "config.example.py"
    )

    return apply_env_overrides(
        load_config_from_path(
            fallback_path
        )
    )


config = load_config_module()
