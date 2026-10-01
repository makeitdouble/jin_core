from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from utils.mcp_skill_utils import (
    build_stdio_environment,
    get_skill_mcp_config,
    public_mcp_config,
)
from utils.skills_asset_utils import normalize_skill_name


def _jsonable(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {
            str(key): _jsonable(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _jsonable(model_dump(mode="json", by_alias=True))
        except TypeError:
            return _jsonable(model_dump())

    return str(value)


def _tool_definition(tool) -> dict:
    return {
        "name": str(getattr(tool, "name", "") or ""),
        "title": str(getattr(tool, "title", "") or ""),
        "description": str(getattr(tool, "description", "") or ""),
        "input_schema": _jsonable(getattr(tool, "input_schema", None) or {}),
    }


def _content_block(block) -> dict:
    payload = _jsonable(block)
    if isinstance(payload, dict):
        return payload
    return {
        "type": str(getattr(block, "type", "unknown") or "unknown"),
        "value": payload,
    }


def _server_identity(client) -> dict:
    server_info = getattr(client, "server_info", None)
    return {
        "protocol_version": str(getattr(client, "protocol_version", "") or ""),
        "server_name": str(getattr(server_info, "name", "") or ""),
        "server_version": str(getattr(server_info, "version", "") or ""),
        "instructions": str(getattr(client, "instructions", "") or ""),
    }


@dataclass
class _MCPRequest:
    operation: str
    tool_name: str = ""
    arguments: dict = field(default_factory=dict)
    future: asyncio.Future | None = None


@dataclass
class _MCPConnection:
    """One persistent MCP connection owned by one asyncio worker task.

    MCP transports use async context managers backed by AnyIO task groups. Keeping
    the enter/use/exit lifecycle inside one dedicated task avoids cross-task cancel
    scope errors while still preserving a server process/session across JIN follow-ups.
    """

    skill_name: str
    config: dict[str, Any]
    _task: asyncio.Task | None = None
    _queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    _start_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _ready: asyncio.Future | None = None

    def fingerprint(self) -> str:
        return json.dumps(
            self.config,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _build_client(self):
        try:
            from mcp import Client, StdioServerParameters
        except ImportError as exc:
            raise RuntimeError(
                "MCP Python SDK is not installed. Install project requirements first."
            ) from exc

        transport = str(self.config.get("transport") or "").casefold()
        read_timeout = self.config.get("read_timeout_seconds")

        if transport == "stdio":
            params = StdioServerParameters(
                command=str(self.config["command"]),
                args=list(self.config.get("args") or []),
                env=build_stdio_environment(self.config),
                cwd=self.config.get("cwd") or None,
            )
            return Client(
                params,
                read_timeout_seconds=read_timeout,
            )

        if transport == "streamable_http":
            return Client(
                str(self.config["url"]),
                read_timeout_seconds=read_timeout,
            )

        if transport == "sse":
            from mcp.client.sse import sse_client

            return Client(
                sse_client(str(self.config["url"])),
                read_timeout_seconds=read_timeout,
            )

        raise RuntimeError(f"Unsupported MCP transport: {transport}")

    async def _list_tools(self, client) -> dict:
        tools = []
        cursor = None
        while True:
            if cursor:
                result = await client.list_tools(cursor=cursor)
            else:
                result = await client.list_tools()
            tools.extend(
                _tool_definition(tool)
                for tool in (getattr(result, "tools", None) or [])
            )
            cursor = getattr(result, "next_cursor", None)
            if not cursor:
                break

        return {
            "ok": True,
            "skill": self.skill_name,
            "server": _server_identity(client),
            "config": public_mcp_config(self.config),
            "tools": tools,
        }

    async def _call_tool(self, client, tool_name: str, arguments: dict) -> dict:
        result = await client.call_tool(tool_name, arguments)
        is_error = bool(getattr(result, "is_error", False))
        return {
            "ok": not is_error,
            "skill": self.skill_name,
            "tool": tool_name,
            "arguments": _jsonable(arguments),
            # Server identity/instructions belong to the MCP initialize handshake.
            # Discovery keeps them once in the loaded skill context; repeating the
            # same static metadata in every tool result only bloats follow-ups.
            "is_error": is_error,
            "content": [
                _content_block(block)
                for block in (getattr(result, "content", None) or [])
            ],
            "structured_content": _jsonable(
                getattr(result, "structured_content", None)
            ),
        }

    async def _worker(self, ready: asyncio.Future) -> None:
        try:
            client = self._build_client()
            async with client:
                if not ready.done():
                    ready.set_result(True)

                while True:
                    request = await self._queue.get()
                    if request is None:
                        return
                    if not isinstance(request, _MCPRequest) or request.future is None:
                        continue
                    if request.future.cancelled():
                        continue

                    try:
                        if request.operation == "list_tools":
                            value = await self._list_tools(client)
                        elif request.operation == "call_tool":
                            value = await self._call_tool(
                                client,
                                request.tool_name,
                                request.arguments,
                            )
                        else:
                            raise RuntimeError(
                                f"Unknown MCP operation: {request.operation}"
                            )
                    except Exception as exc:
                        if not request.future.done():
                            request.future.set_exception(exc)
                    else:
                        if not request.future.done():
                            request.future.set_result(value)
        except asyncio.CancelledError:
            if not ready.done():
                ready.cancel()
            raise
        except Exception as exc:
            if not ready.done():
                ready.set_exception(exc)
        finally:
            while True:
                try:
                    pending = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if isinstance(pending, _MCPRequest) and pending.future is not None and not pending.future.done():
                    pending.future.set_exception(
                        RuntimeError("MCP connection closed before request completed")
                    )

    async def _ensure_worker(self) -> None:
        async with self._start_lock:
            if self._task is not None and not self._task.done() and self._ready is not None:
                ready = self._ready
            else:
                loop = asyncio.get_running_loop()
                ready = loop.create_future()
                self._ready = ready
                self._task = asyncio.create_task(
                    self._worker(ready),
                    name=f"jin-mcp-{self.skill_name}",
                )
        await ready

    async def request(
        self,
        operation: str,
        *,
        tool_name: str = "",
        arguments: dict | None = None,
    ):
        await self._ensure_worker()
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        await self._queue.put(_MCPRequest(
            operation=operation,
            tool_name=tool_name,
            arguments=dict(arguments or {}),
            future=future,
        ))
        return await future

    async def list_tools(self) -> dict:
        return await self.request("list_tools")

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        return await self.request(
            "call_tool",
            tool_name=tool_name,
            arguments=arguments,
        )

    async def close(self) -> None:
        task = self._task
        if task is None:
            return
        if not task.done():
            await self._queue.put(None)
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except asyncio.TimeoutError:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        except (asyncio.CancelledError, Exception):
            pass
        finally:
            self._task = None
            self._ready = None


class MCPClientManager:
    def __init__(self):
        self._connections: dict[str, _MCPConnection] = {}
        self._lock = asyncio.Lock()

    async def _connection_for_skill(self, skill: dict) -> _MCPConnection:
        skill_name = normalize_skill_name(skill.get("name", ""))
        config = get_skill_mcp_config(skill)
        if not skill_name:
            raise RuntimeError("MCP skill has no name")
        if not isinstance(config, dict):
            raise RuntimeError(f"Skill {skill_name} has no MCP_SERVER config")
        if config.get("_invalid"):
            raise RuntimeError(
                str(config.get("detail") or config.get("error") or "Invalid MCP config")
            )

        fingerprint = json.dumps(
            config,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        stale = None
        async with self._lock:
            connection = self._connections.get(skill_name)
            if connection is not None and connection.fingerprint() != fingerprint:
                stale = connection
                connection = None
                self._connections.pop(skill_name, None)
            if connection is None:
                connection = _MCPConnection(
                    skill_name=skill_name,
                    config=config,
                )
                self._connections[skill_name] = connection

        if stale is not None:
            await stale.close()
        return connection

    async def list_tools(self, skill: dict) -> dict:
        connection = await self._connection_for_skill(skill)
        return await connection.list_tools()

    async def call_tool(self, skill: dict, tool_name: str, arguments: dict) -> dict:
        connection = await self._connection_for_skill(skill)
        return await connection.call_tool(tool_name, arguments)

    async def close_skill(self, skill_name: str) -> None:
        normalized = normalize_skill_name(skill_name)
        if not normalized:
            return
        async with self._lock:
            connection = self._connections.pop(normalized, None)
        if connection is not None:
            await connection.close()

    async def close(self) -> None:
        async with self._lock:
            connections = list(self._connections.values())
            self._connections.clear()
        for connection in connections:
            await connection.close()


def get_context_mcp_manager(context) -> MCPClientManager:
    manager = getattr(context, "runtime_mcp_manager", None)
    if not isinstance(manager, MCPClientManager):
        manager = MCPClientManager()
        context.runtime_mcp_manager = manager
    return manager


async def discover_mcp_skill_tools(context, skill: dict) -> dict:
    manager = get_context_mcp_manager(context)
    return await manager.list_tools(skill)


async def call_mcp_tool(context, skill: dict, tool_name: str, arguments: dict) -> dict:
    manager = get_context_mcp_manager(context)
    return await manager.call_tool(skill, tool_name, arguments)


async def close_mcp_skill(context, skill_name: str) -> None:
    manager = getattr(context, "runtime_mcp_manager", None)
    if isinstance(manager, MCPClientManager):
        await manager.close_skill(skill_name)


async def close_context_mcp_manager(context) -> None:
    manager = getattr(context, "runtime_mcp_manager", None)
    if isinstance(manager, MCPClientManager):
        await manager.close()
        context.runtime_mcp_manager = None
