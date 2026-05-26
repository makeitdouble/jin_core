from importlib import import_module
from importlib import util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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
            return import_module(
                "config"
            )

        except ModuleNotFoundError as error:

            if error.name != "config":
                raise

    else:

        if config_path.exists():
            return load_config_from_path(
                config_path
            )

    fallback_path = (
        example_path
        or ROOT / "config.example.py"
    )

    return load_config_from_path(
        fallback_path
    )


config = load_config_module()
