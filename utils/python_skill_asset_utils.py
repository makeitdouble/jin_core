from __future__ import annotations

import asyncio
import base64
import json
from math import ceil
import os
import re
import sys
import tempfile
from pathlib import Path
from time import monotonic

from config_loader import config
from utils import assets_utils as assets_common
from utils.skills_asset_utils import normalize_skill_name
from utils.tokens import estimate_tokens


DEFAULT_READER_MODE = "plain-mode.md"
READER_MODE_SUFFIX = "-mode.md"


def _available_reader_modes(
    skill_directory: Path,
) -> list[str]:

    return [
        path.name
        for path in sorted(
            skill_directory.iterdir(),
            key=lambda value: value.name.casefold(),
        )
        if path.is_file()
        and path.name.casefold().endswith(
            READER_MODE_SUFFIX
        )
    ]


def _resolve_reader_mode(
    skill_directory: Path,
    requested_mode: str,
) -> tuple[str, str]:

    requested = str(
        requested_mode
        or DEFAULT_READER_MODE
    ).strip()
    available_modes = _available_reader_modes(
        skill_directory
    )

    if (
        not requested
        or Path(requested).name != requested
        or "/" in requested
        or "\\" in requested
        or not requested.casefold().endswith(
            READER_MODE_SUFFIX
        )
    ):
        raise ValueError(
            "mode must be the exact name of a *-mode.md instruction file"
        )

    actual_name = next(
        (
            mode
            for mode in available_modes
            if mode.casefold() == requested.casefold()
        ),
        "",
    )

    if not actual_name:
        available_label = (
            ", ".join(available_modes)
            if available_modes
            else "none"
        )
        raise FileNotFoundError(
            f"reader mode '{requested}' was not found; available modes: {available_label}"
        )

    instruction = (
        skill_directory / actual_name
    ).read_text(
        encoding="utf-8",
        errors="replace",
    ).strip()

    if not instruction:
        raise ValueError(
            f"reader mode '{actual_name}' is empty"
        )

    return actual_name, instruction


def _requested_reader_modes(
    payload: dict,
) -> list[str]:

    raw_modes = payload.get(
        "modes"
    )

    if raw_modes is None:
        raw_modes = [
            payload.get(
                "mode",
                DEFAULT_READER_MODE,
            )
        ]
    elif not isinstance(
        raw_modes,
        list,
    ):
        raise ValueError(
            "modes must be a list of *-mode.md filenames"
        )

    modes = []
    seen = set()

    for raw_mode in raw_modes:
        mode = str(
            raw_mode
            or ""
        ).strip()
        key = mode.casefold()

        if not mode or key in seen:
            continue

        seen.add(key)
        modes.append(mode)

    if not modes:
        raise ValueError(
            "at least one reader mode is required"
        )

    return modes


def _estimate_reader_tokens(
    text: str,
) -> int:

    value = str(
        text
        or ""
    )

    if not value:
        return 0

    return max(
        estimate_tokens(
            value
        ),
        ceil(
            len(value) / 3
        ),
    )


def _extract_model_content(
    response: dict,
) -> str:

    content = ""

    if isinstance(response, dict):
        choices = response.get(
            "choices",
            [],
        )

        if isinstance(choices, list) and choices:
            choice = choices[0]

            if isinstance(choice, dict):
                delta = choice.get("delta") or {}
                message = choice.get("message") or {}
                raw_content = (
                    (
                        delta.get("content")
                        or delta.get("text")
                    )
                    if isinstance(delta, dict)
                    else ""
                ) or choice.get("text") or (
                    message.get("content")
                    if isinstance(message, dict)
                    else ""
                )

                if isinstance(raw_content, list):
                    raw_content = "".join(
                        str(item.get("text", ""))
                        for item in raw_content
                        if isinstance(item, dict)
                    )

                if isinstance(raw_content, str):
                    content = raw_content

    return content.strip()


def _extract_finish_reason(
    response: dict,
) -> str:

    if not isinstance(response, dict):
        return ""

    choices = response.get(
        "choices",
        [],
    )

    if not isinstance(choices, list) or not choices:
        return ""

    choice = choices[0]

    if not isinstance(choice, dict):
        return ""

    return str(
        choice.get(
            "finish_reason",
            "",
        )
        or ""
    ).strip().casefold()


def _looks_like_process_reasoning(
    result: str,
) -> bool:

    text = str(result or "")
    signals = (
        "Input: Chunk",
        "Task: Apply",
        "Goal: Extract",
        "Wait, I need",
        "Self-Correction:",
        "Final Review of",
        "I must output",
    )

    return sum(
        signal.casefold() in text.casefold()
        for signal in signals
    ) >= 2


async def _resolve_reader_output_limit(
    client,
    context_window: int,
) -> int:

    configured = getattr(
        client,
        "configured_max_tokens",
        None,
    )
    detected = getattr(
        client,
        "detected_max_tokens",
        None,
    )
    prefer_server_limit = bool(
        getattr(
            config,
            "RUNTIME_MAX_TOKENS_FALLBACK_TO_SERVER",
            False,
        )
    )

    if configured and not prefer_server_limit:
        return max(
            128,
            min(
                int(configured),
                int(context_window),
            ),
        )

    if detected:
        return max(
            128,
            min(
                int(detected),
                int(context_window),
            ),
        )

    detector = getattr(
        client,
        "detect_max_tokens",
        None,
    )

    if callable(detector):
        try:
            resolved = await detector()
        except Exception:
            resolved = None

        if resolved:
            return max(
                128,
                min(
                    int(resolved),
                    int(context_window),
                ),
            )

    if configured:
        return max(
            128,
            min(
                int(configured),
                int(context_window),
            ),
        )

    return max(
        128,
        min(
            int(context_window),
            int(
                getattr(
                    config,
                    "SERVICE_MAX_TOKENS",
                    4096,
                )
                or 4096
            ),
        ),
    )


async def _emit_document_reader_progress(
    context,
    *,
    attachment_name: str,
    mode: str,
    chunk_index: int,
    estimated_chunks: int,
    processed_words: int,
    total_words: int,
    target_words: int | None = None,
    pages_label: str = "",
    stage: str = "reading",
    elapsed_seconds: int | None = None,
    request_index: int = 0,
) -> None:

    action_id = str(
        getattr(
            context,
            "runtime_active_asset_action_id",
            "",
        )
        or ""
    ).strip()
    emitter = getattr(
        context,
        "emitter",
        None,
    )
    emit = getattr(
        emitter,
        "emit",
        None,
    )

    if not action_id or emit is None:
        return

    total_words = max(
        0,
        int(total_words or 0),
    )
    processed_words = max(
        0,
        min(
            int(processed_words or 0),
            total_words,
        ),
    )
    normalized_target_words = (
        processed_words
        if target_words is None
        else max(
            processed_words,
            min(
                int(target_words or 0),
                total_words,
            ),
        )
    )
    percent = (
        int(
            round(
                processed_words
                * 100
                / total_words
            )
        )
        if total_words
        else 0
    )
    target_percent = (
        int(
            round(
                normalized_target_words
                * 100
                / total_words
            )
        )
        if total_words
        else 0
    )
    progress_label = (
        f"{percent}→{target_percent}%"
        if (
            stage == "processing"
            and target_percent > percent
        )
        else f"{percent}%"
    )
    chunk_label = (
        "preparing"
        if chunk_index <= 0
        else f"chunk {chunk_index}"
    )
    page_suffix = (
        f" · pages {pages_label}"
        if pages_label
        else ""
    )
    mode_suffix = (
        f" · {mode}"
        if mode
        else ""
    )
    stage_label = (
        "preparing"
        if chunk_index <= 0
        else "processing"
    )
    normalized_elapsed_seconds = (
        max(0, int(elapsed_seconds or 0))
        if elapsed_seconds is not None
        else None
    )
    elapsed_suffix = (
        f" · {_format_document_reader_elapsed(normalized_elapsed_seconds)}"
        if normalized_elapsed_seconds is not None
        else ""
    )
    text = (
        f"{stage_label.capitalize()} document iteratively"
        f" · {progress_label} · {chunk_label}"
        f"{page_suffix}{mode_suffix}"
        f"{elapsed_suffix}"
    )

    try:
        await emit({
            "type": "runtime_action",
            "action": "asset_action",
            "id": action_id,
            "status": "running",
            "text": text,
            "detail": (
                f"{attachment_name}: {processed_words}/{total_words} words committed"
                + (
                    f"; current target {normalized_target_words}/{total_words} words"
                    if normalized_target_words > processed_words
                    else ""
                )
                + (
                    f"; model request {max(1, int(request_index))}"
                    if request_index > 0
                    else ""
                )
                + (
                    f"; estimated chunks ~{estimated_chunks}"
                    if estimated_chunks > 0
                    else ""
                )
            ),
            "progress": {
                "processed_words": processed_words,
                "target_words": normalized_target_words,
                "total_words": total_words,
                "percent": percent,
                "target_percent": target_percent,
                "chunk": chunk_index,
                "estimated_chunks": estimated_chunks,
                "pages": pages_label,
                "mode": mode,
                "stage": stage,
                "elapsed_seconds": normalized_elapsed_seconds,
                "request": max(
                    0,
                    int(request_index or 0),
                ),
            },
        })
    except Exception:
        return


def _format_document_reader_elapsed(
    elapsed_seconds: int,
) -> str:

    total_seconds = max(
        0,
        int(elapsed_seconds or 0),
    )
    hours, remaining = divmod(
        total_seconds,
        3600,
    )
    minutes, seconds = divmod(
        remaining,
        60,
    )

    if hours:
        return f"{hours}h {minutes}m {seconds}s"

    if minutes:
        return f"{minutes}m {seconds}s"

    return f"{seconds}s"


def _document_reader_elapsed_seconds(
    started_at: float,
) -> int:

    return max(
        0,
        int(monotonic() - started_at),
    )


def _document_reader_heartbeat_seconds() -> float:

    configured = getattr(
        config,
        "DOCUMENT_READER_PROGRESS_HEARTBEAT_SECONDS",
        1.0,
    )

    try:
        interval = float(configured or 1.0)
    except (TypeError, ValueError):
        interval = 1.0

    return max(
        0.25,
        interval,
    )


async def _ask_document_reader_with_progress(
    client,
    *,
    context,
    attachment_name: str,
    mode: str,
    chunk_index: int,
    estimated_chunks: int,
    processed_words: int,
    target_words: int,
    total_words: int,
    pages_label: str,
    stage: str,
    progress_started_at: float,
    request_index: int,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    timeout: float,
):

    request_task = asyncio.create_task(
        client.ask(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
    )
    interval = _document_reader_heartbeat_seconds()

    try:
        while True:
            done, _ = await asyncio.wait(
                {request_task},
                timeout=interval,
            )

            if request_task in done:
                return await request_task

            await _emit_document_reader_progress(
                context,
                attachment_name=attachment_name,
                mode=mode,
                chunk_index=chunk_index,
                estimated_chunks=estimated_chunks,
                processed_words=processed_words,
                target_words=target_words,
                total_words=total_words,
                pages_label=pages_label,
                stage=stage,
                elapsed_seconds=_document_reader_elapsed_seconds(
                    progress_started_at
                ),
                request_index=request_index,
            )
    except BaseException:
        if not request_task.done():
            request_task.cancel()

        await asyncio.gather(
            request_task,
            return_exceptions=True,
        )
        raise


def _parse_payload(
    payload_text: str,
) -> dict:

    try:
        payload = json.loads(
            str(
                payload_text
                or ""
            ).strip()
        )
    except json.JSONDecodeError:
        payload = assets_common._parse_lenient_asset_payload(
            payload_text
        )

    if not isinstance(
        payload,
        dict,
    ):
        return {}

    return assets_common._normalize_action_payload(
        payload
    )


def _safe_attachment_name(
    name: str,
) -> str:

    filename = Path(
        str(
            name
            or "attachment"
        )
    ).name
    filename = re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        filename,
    ).strip(
        "._"
    )

    return filename or "attachment"


def _select_attachment(
    context,
    requested_name: str = "",
) -> dict:

    attachments = [
        attachment
        for attachment in (
            getattr(
                context,
                "runtime_turn_attachments",
                [],
            )
            or []
        )
        if isinstance(
            attachment,
            dict,
        )
    ]

    requested = str(
        requested_name
        or ""
    ).strip().casefold()

    if requested:
        for attachment in attachments:
            name = str(
                attachment.get(
                    "name",
                    "",
                )
                or ""
            ).strip()
            if name.casefold() == requested:
                return attachment

        raise ValueError(
            "requested attachment was not found in the current turn"
        )

    compatible = [
        attachment
        for attachment in attachments
        if attachment.get(
            "text_content"
        ) is not None
        or str(
            attachment.get(
                "data_url",
                "",
            )
            or ""
        ).startswith(
            "data:"
        )
    ]

    if len(compatible) == 1:
        return compatible[0]

    if not compatible:
        raise ValueError(
            "no readable attachment was provided in the current turn"
        )

    raise ValueError(
        "multiple readable attachments were provided; pass the exact attachment name"
    )


def _decode_data_url(
    data_url: str,
) -> bytes:

    header, separator, encoded = str(
        data_url
        or ""
    ).partition(
        ","
    )

    if not separator:
        raise ValueError(
            "attachment data URL is invalid"
        )

    if ";base64" not in header.casefold():
        return encoded.encode(
            "utf-8"
        )

    return base64.b64decode(
        encoded,
        validate=True,
    )


def _materialize_attachment(
    attachment: dict,
    directory: Path,
) -> Path:

    filename = _safe_attachment_name(
        str(
            attachment.get(
                "name",
                "attachment",
            )
            or "attachment"
        )
    )
    path = directory / filename
    text_content = attachment.get(
        "text_content"
    )

    if text_content is not None:
        path.write_text(
            str(
                text_content
            ),
            encoding="utf-8",
        )
        return path

    data_url = str(
        attachment.get(
            "data_url",
            "",
        )
        or ""
    )

    if data_url:
        path.write_bytes(
            _decode_data_url(
                data_url
            )
        )
        return path

    raise ValueError(
        "attachment contains neither text_content nor data_url"
    )


def _require_appended_skill(
    context,
    skill: str,
) -> str:

    requested = normalize_skill_name(
        skill
    )
    appended_names = {
        normalize_skill_name(
            item.get(
                "name",
                "",
            )
            if isinstance(
                item,
                dict,
            )
            else item
        )
        for item in (
            getattr(
                context,
                "runtime_appended_skills",
                [],
            )
            or []
        )
    }
    appended_names.discard(
        ""
    )

    if requested not in appended_names:
        raise PermissionError(
            f"skill must be appended before execution: {requested}"
        )

    return requested


def _find_skill_directory(
    skill: str,
) -> Path:

    requested = normalize_skill_name(
        skill
    )

    if not requested:
        raise ValueError(
            "skill is required"
        )

    for path in assets_common.SKILLS_ROOT.iterdir():
        if not path.is_dir():
            continue

        if normalize_skill_name(
            path.name
        ) == requested:
            return path.resolve()

    raise FileNotFoundError(
        f"directory skill not found: {requested}"
    )


def _resolve_python_script(
    skill_directory: Path,
    script: str,
) -> Path:

    relative_script = Path(
        str(
            script
            or ""
        ).strip()
    )

    if (
        not relative_script.name
        or relative_script.is_absolute()
        or relative_script.suffix.lower() != ".py"
    ):
        raise ValueError(
            "script must be a relative .py path"
        )

    script_path = (
        skill_directory
        / relative_script
    ).resolve()

    if (
        script_path != skill_directory
        and skill_directory not in script_path.parents
    ):
        raise ValueError(
            "script must stay inside the selected skill directory"
        )

    if not script_path.is_file():
        raise FileNotFoundError(
            str(script_path)
        )

    return script_path


async def _run_subprocess_json(
    *args: str,
    cwd: Path,
    timeout_seconds: float,
) -> dict:

    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(
            cwd
        ),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={
            **os.environ,
            "PYTHONUTF8": "1",
        },
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        raise TimeoutError(
            f"python skill exceeded {timeout_seconds:g}s timeout"
        )

    stdout_text = stdout.decode(
        "utf-8",
        errors="replace",
    ).strip()
    stderr_text = stderr.decode(
        "utf-8",
        errors="replace",
    ).strip()

    if process.returncode != 0:
        raise RuntimeError(
            stderr_text
            or stdout_text
            or f"python skill exited with code {process.returncode}"
        )

    try:
        result = json.loads(
            stdout_text
        )
    except json.JSONDecodeError as error:
        raise RuntimeError(
            "python skill did not return one JSON object"
        ) from error

    if not isinstance(
        result,
        dict,
    ):
        raise RuntimeError(
            "python skill JSON result must be an object"
        )

    return result


async def run_python_skill_action(
    context,
    payload: dict,
) -> dict:

    skill_name = str(
        payload.get(
            "skill",
            "",
        )
        or ""
    ).strip()
    script_name = str(
        payload.get(
            "script",
            "",
        )
        or ""
    ).strip()
    raw_args = payload.get(
        "args",
        [],
    )

    if not isinstance(
        raw_args,
        list,
    ):
        raise ValueError(
            "args must be a list"
        )

    _require_appended_skill(
        context,
        skill_name,
    )
    skill_directory = _find_skill_directory(
        skill_name
    )
    script_path = _resolve_python_script(
        skill_directory,
        script_name,
    )
    timeout_seconds = max(
        1.0,
        min(
            float(
                payload.get(
                    "timeout_seconds",
                    getattr(
                        config,
                        "PYTHON_SKILL_TIMEOUT_SECONDS",
                        120,
                    ),
                )
                or 120
            ),
            600.0,
        ),
    )

    with tempfile.TemporaryDirectory(
        prefix="jin_python_skill_"
    ) as temp_dir:
        temporary_directory = Path(
            temp_dir
        )
        attachment_path = None

        if (
            "$ATTACHMENT" in {
                str(argument)
                for argument in raw_args
            }
            or payload.get(
                "attachment"
            )
        ):
            attachment = _select_attachment(
                context,
                str(
                    payload.get(
                        "attachment",
                        "",
                    )
                    or ""
                ),
            )
            attachment_path = _materialize_attachment(
                attachment,
                temporary_directory,
            )

        resolved_args = [
            (
                str(
                    attachment_path
                )
                if str(argument) == "$ATTACHMENT"
                and attachment_path is not None
                else str(argument)
            )
            for argument in raw_args[:64]
        ]
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(
                script_path
            ),
            *resolved_args,
            cwd=str(
                skill_directory
            ),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={
                **os.environ,
                "PYTHONUTF8": "1",
            },
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            raise TimeoutError(
                f"python skill exceeded {timeout_seconds:g}s timeout"
            )

        output_limit = max(
            1000,
            int(
                getattr(
                    config,
                    "PYTHON_SKILL_OUTPUT_MAX_CHARS",
                    60000,
                )
                or 60000
            ),
        )
        stdout_text = stdout.decode(
            "utf-8",
            errors="replace",
        )[:output_limit]
        stderr_text = stderr.decode(
            "utf-8",
            errors="replace",
        )[:output_limit]

        return {
            "ok": process.returncode == 0,
            "action": "run_python_skill",
            "skill": normalize_skill_name(
                skill_name
            ),
            "script": str(
                script_path.relative_to(
                    skill_directory
                )
            ).replace(
                "\\",
                "/",
            ),
            "returncode": process.returncode,
            "stdout": stdout_text,
            "stderr": stderr_text,
            "stdout_truncated": len(stdout) > output_limit,
            "stderr_truncated": len(stderr) > output_limit,
        }


def _get_document_reader_client(
    context,
):

    clients = getattr(
        context,
        "clients",
        {},
    )

    if not isinstance(
        clients,
        dict,
    ):
        raise RuntimeError(
            "runtime clients are unavailable"
        )

    client = clients.get(
        "service"
    )

    if client is None:
        raise RuntimeError(
            "service runtime client is unavailable"
        )

    return client


async def _resolve_context_window(
    client,
) -> int:

    resolver = getattr(
        client,
        "resolve_request_context_window",
        None,
    )

    if callable(
        resolver
    ):
        try:
            resolved = await resolver(
                force_refresh=True,
            )
        except TypeError:
            resolved = await resolver()

        if resolved:
            return int(
                resolved
            )

    configured = getattr(
        client,
        "configured_context_window",
        None,
    )

    if configured:
        return int(
            configured
        )

    return int(
        getattr(
            config,
            "SERVICE_CONTEXT_WINDOW",
            4096,
        )
        or 4096
    )


def _resolve_reader_budgets(
    *,
    context_window: int,
    output_token_limit: int,
    instruction: str,
    question: str,
    current_result: str,
) -> dict:

    context_window = max(
        512,
        int(
            context_window
            or 0
        ),
    )
    configured_result_cap = int(
        getattr(
            config,
            "DOCUMENT_READER_RESULT_MAX_TOKENS",
            0,
        )
        or 0
    )
    automatic_result_cap = min(
        max(
            2048,
            context_window // 16,
        ),
        max(
            2048,
            int(output_token_limit or 0),
        ),
        16384,
    )
    desired_result_cap = (
        configured_result_cap
        if configured_result_cap > 0
        else automatic_result_cap
    )
    result_cap = max(
        128,
        min(
            desired_result_cap,
            max(
                128,
                int(output_token_limit or 0),
            ),
            max(
                128,
                context_window // 3,
            ),
        ),
    )
    configured_reserve = max(
        0,
        int(
            getattr(
                config,
                "RUNTIME_OUTPUT_TOKEN_RESERVE",
                256,
            )
            or 0
        ),
    )
    reserve = min(
        configured_reserve,
        max(
            0,
            context_window // 8,
        ),
    )
    fixed_prompt = (
        "You are one internal document-processing pass. "
        "The runtime already selected the next chunk; do not call tools. "
        "Return only the complete updated document result.\n"
        f"Question: {question}\n"
        f"Current result:\n{current_result}\n"
    )
    occupied_tokens = _estimate_reader_tokens(
        instruction
        + "\n"
        + fixed_prompt
    )
    available_tokens = (
        context_window
        - occupied_tokens
        - reserve
    )
    hard_minimum_chunk_tokens = 64
    hard_minimum_output_tokens = 128
    minimum_chunk_tokens = max(
        hard_minimum_chunk_tokens,
        int(
            getattr(
                config,
                "DOCUMENT_READER_MIN_CHUNK_TOKENS",
                256,
            )
            or 256
        ),
    )
    configured_maximum_chunk_tokens = int(
        getattr(
            config,
            "DOCUMENT_READER_MAX_CHUNK_TOKENS",
            0,
        )
        or 0
    )
    automatic_maximum_chunk_tokens = min(
        32768,
        max(
            4096,
            context_window // 4,
        ),
    )
    maximum_chunk_tokens = max(
        minimum_chunk_tokens,
        (
            configured_maximum_chunk_tokens
            if configured_maximum_chunk_tokens > 0
            else automatic_maximum_chunk_tokens
        ),
    )
    fits = available_tokens >= (
        hard_minimum_chunk_tokens
        + hard_minimum_output_tokens
    )

    if fits:
        # `max_tokens` includes hidden/model reasoning on several local
        # reasoning-capable models. Keep the visible accumulated result compact,
        # but reserve up to one extra result-sized allowance so the very first
        # request can actually reach its answer instead of hitting `length` and
        # entering a retry/split loop.
        reasoning_allowance = max(
            256,
            result_cap,
        )
        desired_generation_budget = min(
            max(
                hard_minimum_output_tokens,
                int(output_token_limit or 0),
            ),
            result_cap + reasoning_allowance,
        )
        balanced_generation_budget = max(
            result_cap,
            int(available_tokens * 0.55),
        )
        output_budget = max(
            hard_minimum_output_tokens,
            min(
                desired_generation_budget,
                balanced_generation_budget,
                available_tokens - minimum_chunk_tokens,
            ),
        )
        chunk_room = available_tokens - output_budget
        chunk_tokens = min(
            maximum_chunk_tokens,
            max(
                hard_minimum_chunk_tokens,
                chunk_room,
            ),
        )
        chunk_words = max(
            32,
            int(
                chunk_tokens
                * 0.65
            ),
        )
    else:
        reasoning_allowance = 0
        output_budget = max(
            1,
            min(
                int(output_token_limit or 0),
                max(
                    1,
                    available_tokens,
                ),
            ),
        )
        chunk_tokens = 0
        chunk_words = 0

    return {
        "context_window": context_window,
        "result_token_cap": result_cap,
        "output_tokens": output_budget,
        "reasoning_allowance_tokens": reasoning_allowance,
        "chunk_tokens": chunk_tokens,
        "chunk_words": chunk_words,
        "free_tokens_before_chunk": available_tokens - output_budget,
        "occupied_tokens": occupied_tokens,
        "reserve_tokens": reserve,
        "fits": fits,
    }

def _build_iteration_system_prompt(
    instruction: str,
    result_token_cap: int,
) -> str:

    return (
        "You are one internal document-processing pass. The runtime already "
        "selected the next ordered chunk, so do not call tools and do not "
        "describe the loop, your plan, checks, or private reasoning. Follow "
        "the selected mode instruction below. Update the accumulated result "
        "from the current result and the new source chunk. Return only the "
        "complete updated result, never a diff or a continuation. "
        f"Keep it within approximately {result_token_cap} tokens.\n"
        "Preserve useful earlier content unless the source explicitly corrects "
        "it or the selected mode instructs otherwise. Never replace prior "
        "content with ellipses, 'handled previously', 'see above', or another "
        "placeholder.\n\n"
        "SELECTED MODE INSTRUCTION:\n"
        f"{instruction}"
    )


def _build_iteration_user_prompt(
    *,
    attachment_name: str,
    question: str,
    chunk_index: int,
    chunk: dict,
    current_result: str,
) -> str:

    pages = chunk.get(
        "pages_in_chunk",
        [],
    )
    pages_label = (
        ", ".join(
            str(page)
            for page in pages
        )
        if isinstance(
            pages,
            list,
        )
        else ""
    )

    return (
        f"DOCUMENT: {attachment_name}\n"
        f"USER QUESTION: {question or 'Build a complete usable document result.'}\n"
        f"CHUNK: c{chunk_index}\n"
        f"WORD OFFSET: {chunk.get('offset', 0)}\n"
        f"PAGES IN CHUNK: {pages_label or 'unknown'}\n"
        f"EOF: {bool(chunk.get('eof'))}\n\n"
        "CURRENT RESULT:\n"
        f"{current_result or '— empty —'}\n\n"
        "NEXT SOURCE CHUNK:\n"
        f"{chunk.get('text', '')}\n\n"
        "Update and return the complete result now."
    )


async def _run_document_pass(
    *,
    context,
    client,
    skill_directory: Path,
    source_path: Path,
    cache_path: Path,
    attachment_name: str,
    question: str,
    mode: str,
    instruction: str,
    context_window: int,
    output_token_limit: int,
) -> dict:

    script_path = _resolve_python_script(
        skill_directory,
        "chunk_reader.py",
    )
    timeout_seconds = float(
        getattr(
            config,
            "DOCUMENT_READER_SCRIPT_TIMEOUT_SECONDS",
            120,
        )
        or 120
    )
    info = await _run_subprocess_json(
        sys.executable,
        str(script_path),
        "--source",
        str(source_path),
        "--cache",
        str(cache_path),
        "info",
        cwd=skill_directory,
        timeout_seconds=timeout_seconds,
    )
    total_words = int(
        info.get(
            "total_words",
            0,
        )
        or 0
    )
    page_count = int(
        info.get(
            "pages",
            0,
        )
        or 0
    )
    extraction_warning = ""

    if (
        page_count >= 5
        and total_words / page_count < 25
    ):
        extraction_warning = (
            "PDF text extraction is very sparse; the source may be image-only "
            "or have a broken text layer, so OCR may be required."
        )

    if total_words <= 0:
        return {
            "ok": False,
            "mode": mode,
            "error": "document_has_no_extractable_text",
            "detail": (
                "The reader extracted no text. The PDF may be image-only and require OCR."
            ),
            "total_words": total_words,
            "pages": page_count,
            "extraction_warning": (
                extraction_warning
                or "The reader extracted no text. OCR is required."
            ),
            "result": "",
            "chunks": 0,
        }

    max_iterations = max(
        1,
        int(
            getattr(
                config,
                "DOCUMENT_READER_MAX_ITERATIONS",
                128,
            )
            or 128
        ),
    )
    offset = 0
    chunk_index = 0
    current_result = ""
    previous_chunk_text = ""
    requested_chunk_words = []
    actual_chunk_words = []
    free_token_samples = []
    length_limited_chunks = 0
    eof = False
    estimated_chunks = 0
    model_request_index = 0
    progress_started_at = monotonic()

    await _emit_document_reader_progress(
        context,
        attachment_name=attachment_name,
        mode=mode,
        chunk_index=0,
        estimated_chunks=0,
        processed_words=0,
        total_words=total_words,
        stage="reading",
        elapsed_seconds=0,
    )

    while not eof and chunk_index < max_iterations:
        budgets = _resolve_reader_budgets(
            context_window=context_window,
            output_token_limit=output_token_limit,
            instruction=instruction,
            question=question,
            current_result=current_result,
        )

        if not budgets["fits"]:
            return {
                "ok": False,
                "mode": mode,
                "error": "document_reader_context_exhausted",
                "detail": (
                    "The active model context window is too small for the "
                    "reader instruction, accumulated result, one source chunk, "
                    "and a new result output."
                ),
                "total_words": total_words,
                "pages": page_count,
                "extraction_warning": extraction_warning,
                "chunks": chunk_index,
                "processed_words": min(offset, total_words),
                "context_window": context_window,
                "occupied_tokens": budgets["occupied_tokens"],
                "reserve_tokens": budgets["reserve_tokens"],
                "result": current_result,
            }

        chunk = await _run_subprocess_json(
            sys.executable,
            str(script_path),
            "--source",
            str(source_path),
            "--cache",
            str(cache_path),
            "read",
            str(offset),
            str(budgets["chunk_words"]),
            cwd=skill_directory,
            timeout_seconds=timeout_seconds,
        )
        text = str(
            chunk.get(
                "text",
                "",
            )
            or ""
        )
        words_read = int(
            chunk.get(
                "words_read",
                0,
            )
            or 0
        )
        next_offset = int(
            chunk.get(
                "next_offset",
                offset,
            )
            or offset
        )

        if (
            words_read <= 0
            or next_offset <= offset
            or text == previous_chunk_text
        ):
            eof = True
            break

        chunk_index += 1
        estimated_chunks = (
            chunk_index
            + ceil(
                max(
                    0,
                    total_words - next_offset,
                )
                / max(
                    1,
                    words_read,
                )
            )
        )
        requested_chunk_words.append(
            budgets["chunk_words"]
        )
        actual_chunk_words.append(
            words_read
        )
        free_token_samples.append(
            budgets["free_tokens_before_chunk"]
        )
        system_prompt = _build_iteration_system_prompt(
            instruction,
            budgets["result_token_cap"],
        )
        user_prompt = _build_iteration_user_prompt(
            attachment_name=attachment_name,
            question=question,
            chunk_index=chunk_index,
            chunk=chunk,
            current_result=current_result,
        )
        pages = chunk.get(
            "pages_in_chunk",
            [],
        )
        pages_label = (
            "-".join(
                [
                    str(pages[0]),
                    str(pages[-1]),
                ]
            )
            if isinstance(pages, list)
            and len(pages) > 1
            else (
                str(pages[0])
                if isinstance(pages, list)
                and pages
                else ""
            )
        )
        model_request_index += 1
        await _emit_document_reader_progress(
            context,
            attachment_name=attachment_name,
            mode=mode,
            chunk_index=chunk_index,
            estimated_chunks=estimated_chunks,
            processed_words=offset,
            target_words=next_offset,
            total_words=total_words,
            pages_label=pages_label,
            stage="processing",
            elapsed_seconds=_document_reader_elapsed_seconds(
                progress_started_at
            ),
            request_index=model_request_index,
        )
        raw_result = await _ask_document_reader_with_progress(
            client,
            context=context,
            attachment_name=attachment_name,
            mode=mode,
            chunk_index=chunk_index,
            estimated_chunks=estimated_chunks,
            processed_words=offset,
            target_words=next_offset,
            total_words=total_words,
            pages_label=pages_label,
            stage="processing",
            progress_started_at=progress_started_at,
            request_index=model_request_index,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=float(
                getattr(
                    config,
                    "DOCUMENT_READER_TEMPERATURE",
                    0.1,
                )
                or 0.1
            ),
            max_tokens=budgets["output_tokens"],
            timeout=float(
                getattr(
                    config,
                    "DOCUMENT_READER_MODEL_TIMEOUT_SECONDS",
                    getattr(
                        config,
                        "SERVICE_REQUEST_TIMEOUT",
                        1000.0,
                    ),
                )
                or 1000.0
            ),
        )
        updated_result = _extract_model_content(
            raw_result
        )
        finish_reason = _extract_finish_reason(
            raw_result
        )

        # One model request means one committed chunk. A `length` finish reason
        # is telemetry, not a reason to replay the same pages forever: local
        # reasoning models may spend part of max_tokens on hidden reasoning and
        # still return a usable visible result. Only genuinely empty/process
        # output fails, and it fails immediately instead of launching retries.
        if (
            not updated_result
            or _looks_like_process_reasoning(
                updated_result
            )
        ):
            return {
                "ok": False,
                "mode": mode,
                "error": "invalid_model_output",
                "detail": (
                    "The internal model returned no usable document result "
                    f"for chunk {chunk_index}. No automatic retry was made."
                ),
                "total_words": total_words,
                "pages": page_count,
                "extraction_warning": extraction_warning,
                "chunks": chunk_index,
                "processed_words": min(offset, total_words),
                "finish_reason": finish_reason,
                "result": current_result,
            }

        if finish_reason == "length":
            length_limited_chunks += 1

        current_result = updated_result
        previous_chunk_text = text
        offset = next_offset
        eof = bool(
            chunk.get(
                "eof",
                False,
            )
        )
        await _emit_document_reader_progress(
            context,
            attachment_name=attachment_name,
            mode=mode,
            chunk_index=chunk_index,
            estimated_chunks=estimated_chunks,
            processed_words=offset,
            target_words=offset,
            total_words=total_words,
            pages_label=pages_label,
            stage="reading",
            elapsed_seconds=_document_reader_elapsed_seconds(
                progress_started_at
            ),
            request_index=model_request_index,
        )

    completed = eof or offset >= total_words

    return {
        "ok": completed,
        "mode": mode,
        "error": (
            ""
            if completed
            else "document_reader_max_iterations"
        ),
        "total_words": total_words,
        "pages": page_count,
        "extraction_warning": extraction_warning,
        "chunks": chunk_index,
        "processed_words": min(
            offset,
            total_words,
        ),
        "context_window": context_window,
        "output_token_limit": output_token_limit,
        "result_tokens": (
            _estimate_reader_tokens(
                current_result
            )
            if current_result
            else 0
        ),
        "length_limited_chunks": length_limited_chunks,
        "reasoning_fallback_used": False,
        "chunk_budget": {
            "requested_words_first": (
                requested_chunk_words[0]
                if requested_chunk_words
                else 0
            ),
            "requested_words_last": (
                requested_chunk_words[-1]
                if requested_chunk_words
                else 0
            ),
            "requested_words_min": (
                min(requested_chunk_words)
                if requested_chunk_words
                else 0
            ),
            "requested_words_max": (
                max(requested_chunk_words)
                if requested_chunk_words
                else 0
            ),
            "actual_words_min": (
                min(actual_chunk_words)
                if actual_chunk_words
                else 0
            ),
            "actual_words_max": (
                max(actual_chunk_words)
                if actual_chunk_words
                else 0
            ),
            "free_tokens_first": (
                free_token_samples[0]
                if free_token_samples
                else 0
            ),
            "free_tokens_last": (
                free_token_samples[-1]
                if free_token_samples
                else 0
            ),
        },
        "result": current_result,
    }


async def run_document_reader_action(
    context,
    payload: dict,
) -> dict:

    skill_name = str(
        payload.get(
            "skill",
            "chunk_reader",
        )
        or "chunk_reader"
    ).strip()

    _require_appended_skill(
        context,
        skill_name,
    )
    skill_directory = _find_skill_directory(
        skill_name
    )
    available_modes = _available_reader_modes(
        skill_directory
    )
    resolved_modes = []
    resolved_names = set()

    for requested_mode in _requested_reader_modes(
        payload
    ):
        mode_name, instruction = _resolve_reader_mode(
            skill_directory,
            requested_mode,
        )
        mode_key = mode_name.casefold()

        if mode_key in resolved_names:
            continue

        resolved_names.add(mode_key)
        resolved_modes.append((
            mode_name,
            instruction,
        ))

    attachment = _select_attachment(
        context,
        str(
            payload.get(
                "attachment",
                "",
            )
            or ""
        ),
    )
    attachment_name = str(
        attachment.get(
            "name",
            "attachment",
        )
        or "attachment"
    )
    question = str(
        payload.get(
            "question",
            "",
        )
        or ""
    ).strip()
    client = _get_document_reader_client(
        context
    )
    context_window = await _resolve_context_window(
        client
    )
    output_token_limit = await _resolve_reader_output_limit(
        client,
        context_window,
    )
    common_result = {
        "action": "run_document_reader",
        "skill": normalize_skill_name(
            skill_name
        ),
        "attachment": attachment_name,
        "question": question,
        "available_modes": available_modes,
        "context_window": context_window,
        "output_token_limit": output_token_limit,
    }

    with tempfile.TemporaryDirectory(
        prefix="jin_document_reader_"
    ) as temp_dir:
        temporary_directory = Path(
            temp_dir
        )
        source_path = _materialize_attachment(
            attachment,
            temporary_directory,
        )
        cache_path = temporary_directory / "extracted_text.txt"

        if len(resolved_modes) == 1:
            mode_name, instruction = resolved_modes[0]
            result = await _run_document_pass(
                context=context,
                client=client,
                skill_directory=skill_directory,
                source_path=source_path,
                cache_path=cache_path,
                attachment_name=attachment_name,
                question=question,
                mode=mode_name,
                instruction=instruction,
                context_window=context_window,
                output_token_limit=output_token_limit,
            )

            return {
                **common_result,
                "ok": bool(
                    result.get(
                        "ok"
                    )
                ),
                "mode": mode_name,
                **result,
            }

        results = {}

        for mode_name, instruction in resolved_modes:
            results[mode_name] = await _run_document_pass(
                context=context,
                client=client,
                skill_directory=skill_directory,
                source_path=source_path,
                cache_path=cache_path,
                attachment_name=attachment_name,
                question=question,
                mode=mode_name,
                instruction=instruction,
                context_window=context_window,
                output_token_limit=output_token_limit,
            )

        return {
            **common_result,
            "ok": all(
                bool(result.get("ok"))
                for result in results.values()
            ),
            "modes": [
                mode_name
                for mode_name, _instruction in resolved_modes
            ],
            "results": results,
        }


async def run_context_asset_action(
    payload_text: str,
    *,
    context=None,
) -> dict:

    payload = _parse_payload(
        payload_text
    )

    if not payload:
        return assets_common.run_asset_action(
            payload_text
        )

    action = str(
        payload.get(
            "action",
            "",
        )
        or ""
    ).strip()

    try:
        if action == "run_document_reader":
            return await run_document_reader_action(
                context,
                payload,
            )

        if action == "run_python_skill":
            return await run_python_skill_action(
                context,
                payload,
            )

        return assets_common.run_asset_action(
            payload_text
        )

    except Exception as error:
        return {
            "ok": False,
            "action": action or "asset_action",
            "error": error.__class__.__name__,
            "detail": str(error),
        }
