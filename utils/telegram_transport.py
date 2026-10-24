from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

import httpx

from config_loader import ROOT, config


TELEGRAM_TEXT_LIMIT = 4096
TELEGRAM_ALBUM_BUFFER_SECONDS = 0.8
TELEGRAM_LONG_POLL_SECONDS = 25
TELEGRAM_MAX_PHOTO_BYTES = 20 * 1024 * 1024
TELEGRAM_MAX_PHOTO_SET_BYTES = 40 * 1024 * 1024
TELEGRAM_MAX_PHOTOS = 5
TELEGRAM_RUNTIME_DIR = ROOT / ".jin_runtime"


def _configured_token() -> str:
    return str(getattr(config, "TELEGRAM_BOT_TOKEN", "") or "").strip()


def _configured_chat_id() -> str:
    return str(getattr(config, "TELEGRAM_CHAT_ID", "") or "").strip()


def telegram_enabled() -> bool:
    return bool(getattr(config, "TELEGRAM_ENABLED", False))


def _safe_detail(value: Any) -> str:
    detail = str(value or "").strip()
    token = _configured_token()
    if token:
        detail = detail.replace(token, "<redacted>")
    return detail[:500]


def _error(action: str, error: str, detail: Any) -> dict:
    return {
        "ok": False,
        "action": action,
        "error": error,
        "detail": _safe_detail(detail),
    }


def _api_url(method: str) -> str:
    return f"https://api.telegram.org/bot{_configured_token()}/{method}"


async def _telegram_api_call(
    method: str,
    payload: dict,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float | httpx.Timeout = 20.0,
) -> dict:
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(http2=False)
    try:
        response = await client.post(
            _api_url(method),
            json=payload,
            timeout=timeout,
        )
        try:
            body = response.json()
        except (TypeError, ValueError):
            body = {}
        if response.status_code != 200 or not isinstance(body, dict) or body.get("ok") is not True:
            description = body.get("description") if isinstance(body, dict) else ""
            return _error(
                method,
                "telegram_api_error",
                description or f"Telegram returned HTTP {response.status_code}",
            )
        return body
    except httpx.TimeoutException as error:
        return _error(method, "telegram_timeout", error)
    except httpx.HTTPError as error:
        return _error(method, "telegram_network_error", error)
    except Exception as error:
        return _error(method, "telegram_network_error", error)
    finally:
        if owns_client:
            await client.aclose()


async def telegram_send(payload: dict) -> dict:
    action = "telegram_send"
    if not telegram_enabled() or not _configured_token():
        return _error(action, "telegram_not_configured", "Telegram is disabled or the bot token is missing")

    allowed_chat_id = _configured_chat_id()
    if not allowed_chat_id:
        return _error(action, "telegram_recipient_not_configured", "TELEGRAM_CHAT_ID is missing")

    text = str(payload.get("text", "") or "")
    if not text.strip():
        return _error(action, "telegram_empty_text", "text must be non-empty")
    if len(text) > TELEGRAM_TEXT_LIMIT:
        return _error(action, "telegram_text_too_long", f"text exceeds {TELEGRAM_TEXT_LIMIT} characters")

    requested_chat_id = str(payload.get("chat_id", "") or "").strip()
    chat_id = requested_chat_id or allowed_chat_id
    if chat_id != allowed_chat_id:
        return _error(action, "telegram_chat_not_allowed", "chat_id is not an allowed recipient")

    response = await _telegram_api_call("sendMessage", {"chat_id": chat_id, "text": text})
    if response.get("ok") is not True:
        return {
            **response,
            "action": action,
        }

    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    return {
        "ok": True,
        "action": action,
        "chat_id": chat_id,
        "message_id": result.get("message_id"),
    }


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        # os.kill(pid, 0) is not a reliable existence probe on Windows:
        # some Python versions raise SystemError (not just OSError).
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        open_process.restype = wintypes.HANDLE
        get_exit_code = kernel32.GetExitCodeProcess
        get_exit_code.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        get_exit_code.restype = wintypes.BOOL
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL

        # QUERY_LIMITED_INFORMATION is sufficient; no termination rights needed.
        handle = open_process(0x1000, False, pid)
        if not handle:
            # Access denied means a process can exist but is protected.
            # Treat it as alive to avoid two Telegram polling workers.
            return ctypes.get_last_error() == 5
        try:
            exit_code = wintypes.DWORD()
            if not get_exit_code(handle, ctypes.byref(exit_code)):
                return True  # Unknown state: keep the lock instead of racing.
            return exit_code.value == 259  # STILL_ACTIVE
        finally:
            close_handle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class TelegramPollingService:
    def __init__(self, app_state):
        self.app_state = app_state
        self.client = httpx.AsyncClient(http2=False)
        token_hash = hashlib.sha256(_configured_token().encode("utf-8")).hexdigest()[:16]
        self.offset_path = TELEGRAM_RUNTIME_DIR / f"telegram-{token_hash}.offset.json"
        self.lock_path = TELEGRAM_RUNTIME_DIR / f"telegram-{token_hash}.lock"
        self.lock_nonce = secrets.token_hex(12)
        self.lock_acquired = False
        self.confirmed_offset = self._load_offset()
        self.fetch_offset = self.confirmed_offset
        self.pending: list[dict] = []
        self.last_error = ""

    def _load_offset(self) -> int:
        try:
            payload = json.loads(self.offset_path.read_text(encoding="utf-8"))
            return max(0, int(payload.get("offset", 0)))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return 0

    def _save_offset(self, offset: int) -> None:
        TELEGRAM_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        temporary = self.offset_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"offset": int(offset), "updated_at": time.time()}),
            encoding="utf-8",
        )
        temporary.replace(self.offset_path)

    def acquire_lock(self) -> bool:
        TELEGRAM_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        for _attempt in range(2):
            try:
                descriptor = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    existing = json.loads(self.lock_path.read_text(encoding="utf-8"))
                    existing_pid = int(existing.get("pid", 0))
                except (OSError, TypeError, ValueError, json.JSONDecodeError):
                    existing_pid = 0
                if _pid_is_alive(existing_pid):
                    return False
                try:
                    self.lock_path.unlink()
                except OSError:
                    return False
                continue
            else:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump({"pid": os.getpid(), "nonce": self.lock_nonce}, handle)
                self.lock_acquired = True
                return True
        return False

    def release_lock(self) -> None:
        if not self.lock_acquired:
            return
        try:
            payload = json.loads(self.lock_path.read_text(encoding="utf-8"))
            if payload.get("nonce") == self.lock_nonce:
                self.lock_path.unlink(missing_ok=True)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
        self.lock_acquired = False

    def _active_context(self):
        contexts = getattr(self.app_state, "websocket_runtime_contexts", {})
        candidates = []
        for context in list(contexts.values()) if isinstance(contexts, dict) else []:
            if bool(getattr(context, "runtime_anonymous_mode", False)):
                continue
            transport = getattr(context, "runtime_transport", None)
            enqueue = getattr(context, "runtime_external_user_enqueue", None)
            if (
                transport is None
                or getattr(transport, "stopping", False)
                or getattr(transport, "socket", None) is None
                or not callable(enqueue)
            ):
                continue
            candidates.append(context)
        return max(
            candidates,
            key=lambda item: float(getattr(item, "runtime_tab_opened_at", 0.0) or 0.0),
            default=None,
        )

    @staticmethod
    def _authorized(message: dict) -> bool:
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        sender = message.get("from") if isinstance(message.get("from"), dict) else {}
        allowed = _configured_chat_id()
        return bool(
            allowed
            and chat.get("type") == "private"
            and str(chat.get("id", "")) == allowed
            and str(sender.get("id", "")) == allowed
        )

    async def _reply_error(self, detail: str) -> None:
        chat_id = _configured_chat_id()
        if not chat_id:
            return
        await _telegram_api_call(
            "sendMessage",
            {"chat_id": chat_id, "text": f"JIN: {detail}"},
            client=self.client,
        )

    async def _download_photo(self, message: dict, position: int) -> tuple[dict, bytes]:
        variants = message.get("photo") if isinstance(message.get("photo"), list) else []
        variants = [item for item in variants if isinstance(item, dict) and item.get("file_id")]
        if not variants:
            raise ValueError("Telegram photo has no downloadable variant")
        photo = max(
            variants,
            key=lambda item: (
                int(item.get("file_size", 0) or 0),
                int(item.get("width", 0) or 0) * int(item.get("height", 0) or 0),
            ),
        )
        announced_size = int(photo.get("file_size", 0) or 0)
        if announced_size > TELEGRAM_MAX_PHOTO_BYTES:
            raise ValueError("Photo exceeds the 20 MiB attachment limit")

        result = await _telegram_api_call(
            "getFile",
            {"file_id": str(photo["file_id"])},
            client=self.client,
        )
        if result.get("ok") is not True:
            raise RuntimeError(result.get("detail") or result.get("error") or "Telegram getFile failed")
        file_result = result.get("result") if isinstance(result.get("result"), dict) else {}
        file_path = str(file_result.get("file_path", "") or "").strip()
        if not file_path:
            raise RuntimeError("Telegram getFile returned no file_path")

        url = f"https://api.telegram.org/file/bot{_configured_token()}/{file_path.lstrip('/')}"
        payload = bytearray()
        try:
            async with self.client.stream("GET", url, timeout=20.0) as response:
                if response.status_code != 200:
                    raise RuntimeError(f"Telegram file download returned HTTP {response.status_code}")
                content_length = int(response.headers.get("content-length", 0) or 0)
                if content_length > TELEGRAM_MAX_PHOTO_BYTES:
                    raise ValueError("Photo exceeds the 20 MiB attachment limit")
                async for chunk in response.aiter_bytes():
                    payload.extend(chunk)
                    if len(payload) > TELEGRAM_MAX_PHOTO_BYTES:
                        raise ValueError("Photo exceeds the 20 MiB attachment limit")
        except httpx.TimeoutException as error:
            raise RuntimeError("Telegram photo download timed out") from error
        except httpx.HTTPError as error:
            raise RuntimeError(_safe_detail(error)) from error

        if not payload:
            raise ValueError("Telegram returned an empty photo")
        if not payload.startswith(b"\xff\xd8\xff"):
            raise ValueError("Telegram returned unsupported photo data; JPEG required")
        unique = str(photo.get("file_unique_id", "") or message.get("message_id", "photo"))
        metadata = {
            "name": f"telegram_{unique}_{position}.jpg",
            "mime_type": "image/jpeg",
            "width": photo.get("width"),
            "height": photo.get("height"),
        }
        return metadata, bytes(payload)

    async def _handle_messages(self, messages: list[dict]) -> None:
        if not messages or not all(self._authorized(message) for message in messages):
            return

        photos = [message for message in messages if isinstance(message.get("photo"), list)]
        if photos and len(photos) != len(messages):
            await self._reply_error("альбом отклонён: поддерживаются только фотографии")
            return
        if len(photos) > TELEGRAM_MAX_PHOTOS:
            await self._reply_error("альбом отклонён: допускается не более 5 фотографий")
            return

        text = ""
        for message in messages:
            candidate = message.get("caption") if photos else message.get("text")
            if isinstance(candidate, str) and candidate.strip():
                text = candidate
                break

        if not photos and not text.strip():
            await self._reply_error("поддерживаются только текст и фотографии")
            return

        context = self._active_context()
        if context is None:
            await self._reply_error("нет активной обычной вкладки JIN")
            return

        downloaded: list[tuple[dict, bytes]] = []
        total_bytes = 0
        try:
            for index, message in enumerate(photos, start=1):
                metadata, content = await self._download_photo(message, index)
                total_bytes += len(content)
                if total_bytes > TELEGRAM_MAX_PHOTO_SET_BYTES:
                    raise ValueError("Photo set exceeds the 40 MiB attachment limit")
                downloaded.append((metadata, content))
        except (ValueError, RuntimeError) as error:
            await self._reply_error(_safe_detail(error))
            return

        from utils.attached_files_store import delete_file_record, store_uploaded_file

        file_ids = []
        created_ids = []
        try:
            for metadata, content in downloaded:
                record, created, _pin_error = store_uploaded_file(
                    name=metadata["name"],
                    content=content,
                    mime_type=metadata["mime_type"],
                    width=metadata["width"],
                    height=metadata["height"],
                    pin=False,
                )
                file_ids.append(record["id"])
                if created:
                    created_ids.append(record["id"])

            enqueue = getattr(context, "runtime_external_user_enqueue", None)
            if not callable(enqueue):
                raise RuntimeError("target JIN tab is no longer active")
            result = await enqueue({
                "type": "message",
                "text": text,
                "attachments": [{"id": file_id} for file_id in file_ids],
                "external_source": "telegram",
            })
            if not isinstance(result, dict) or result.get("ok") is not True:
                raise RuntimeError(
                    (result or {}).get("detail")
                    if isinstance(result, dict)
                    else "JIN rejected the Telegram message"
                )
        except Exception as error:
            for file_id in created_ids:
                delete_file_record(file_id)
            await self._reply_error(_safe_detail(error) or "не удалось передать сообщение в JIN")
            return

    def _ingest_update(self, update: dict, now: float) -> None:
        try:
            update_id = int(update.get("update_id"))
        except (TypeError, ValueError):
            return
        if update_id < self.fetch_offset:
            return
        self.fetch_offset = update_id + 1
        message = update.get("message") if isinstance(update.get("message"), dict) else {}
        media_group_id = str(message.get("media_group_id", "") or "").strip()
        if media_group_id:
            existing = next(
                (entry for entry in self.pending if entry.get("media_group_id") == media_group_id),
                None,
            )
            if existing is not None:
                existing["updates"].append(update)
                existing["last_update_id"] = update_id
                existing["deadline"] = now + TELEGRAM_ALBUM_BUFFER_SECONDS
                return
            self.pending.append({
                "first_update_id": update_id,
                "last_update_id": update_id,
                "media_group_id": media_group_id,
                "deadline": now + TELEGRAM_ALBUM_BUFFER_SECONDS,
                "updates": [update],
            })
            return
        self.pending.append({
            "first_update_id": update_id,
            "last_update_id": update_id,
            "media_group_id": "",
            "deadline": now,
            "updates": [update],
        })

    async def _drain_ready(self) -> None:
        loop = asyncio.get_running_loop()
        while self.pending:
            entry = self.pending[0]
            if entry.get("media_group_id") and loop.time() < float(entry["deadline"]):
                return
            messages = [
                update.get("message")
                for update in entry["updates"]
                if isinstance(update.get("message"), dict)
            ]
            try:
                await self._handle_messages(messages)
            finally:
                offset = int(entry["last_update_id"]) + 1
                self._save_offset(offset)
                self.confirmed_offset = offset
                self.pending.pop(0)

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            while True:
                await self._drain_ready()
                poll_timeout = 0 if self.pending else TELEGRAM_LONG_POLL_SECONDS
                previous_fetch_offset = self.fetch_offset
                response = await _telegram_api_call(
                    "getUpdates",
                    {
                        # Do not acknowledge a buffered album at Telegram until
                        # its complete USER turn has been accepted and its
                        # durable offset is committed. Repeated rows are
                        # filtered by fetch_offset while later album elements
                        # can still arrive in the same getUpdates result.
                        "offset": self.confirmed_offset,
                        "timeout": poll_timeout,
                        "allowed_updates": ["message"],
                    },
                    client=self.client,
                    timeout=httpx.Timeout(TELEGRAM_LONG_POLL_SECONDS + 10.0),
                )
                if response.get("ok") is not True:
                    self.last_error = _safe_detail(response.get("detail") or response.get("error"))
                    self.app_state.telegram_polling_error = self.last_error
                    await asyncio.sleep(2.0)
                    continue

                updates = response.get("result") if isinstance(response.get("result"), list) else []
                now = loop.time()
                for update in updates:
                    if isinstance(update, dict):
                        self._ingest_update(update, now)
                if self.pending and self.fetch_offset == previous_fetch_offset:
                    delay = max(0.0, float(self.pending[0]["deadline"]) - loop.time())
                    if delay:
                        await asyncio.sleep(min(delay, TELEGRAM_ALBUM_BUFFER_SECONDS))
        finally:
            await self.client.aclose()
            self.release_lock()


def start_telegram_polling(app_state):
    if not telegram_enabled() or not _configured_token() or not _configured_chat_id():
        app_state.telegram_polling_task = None
        return None
    service = TelegramPollingService(app_state)
    if not service.acquire_lock():
        app_state.telegram_polling_error = "telegram_poller_already_running"
        app_state.telegram_polling_task = None
        asyncio.create_task(service.client.aclose())
        return None
    app_state.telegram_polling_service = service
    task = asyncio.create_task(service.run())

    def record_terminal_error(completed):
        if completed.cancelled():
            return
        try:
            error = completed.exception()
        except (asyncio.CancelledError, Exception):
            return
        if error is not None:
            app_state.telegram_polling_error = _safe_detail(error)

    task.add_done_callback(record_terminal_error)
    app_state.telegram_polling_task = task
    return task


async def stop_telegram_polling(app_state) -> None:
    task = getattr(app_state, "telegram_polling_task", None)
    service = getattr(app_state, "telegram_polling_service", None)
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    elif service is not None:
        await service.client.aclose()
        service.release_lock()
    app_state.telegram_polling_task = None
    app_state.telegram_polling_service = None
