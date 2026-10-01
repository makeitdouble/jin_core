import unittest
import httpx
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnect

import websocket as ws
from websocket.origin import has_same_origin


class OriginTests(unittest.TestCase):
    def test_page_close_beacon_requires_origin_and_exact_transport_epoch(self):
        app = FastAPI()
        app.include_router(ws.websocket_router)
        transport = SimpleNamespace(epoch="current", stop=AsyncMock())
        app.state.websocket_runtime_contexts = {
            "page": SimpleNamespace(runtime_transport=transport),
        }
        with TestClient(app) as client:
            payload = {"client_id": "page", "epoch": "current"}
            for headers in ({}, {"origin": "null"}, {"origin": "http://evil.example"}):
                self.assertEqual(client.post("/ws/chat/close", json=payload, headers=headers).status_code, 403)
            headers = {"origin": "http://testserver"}
            self.assertEqual(client.post("/ws/chat/close", json={**payload, "epoch": "old"}, headers=headers).status_code, 204)
            self.assertEqual(client.post("/ws/chat/close", json={**payload, "client_id": "other"}, headers=headers).status_code, 204)
            transport.stop.assert_not_called()
            self.assertEqual(client.post("/ws/chat/close", json=payload, headers=headers).status_code, 204)
            transport.stop.assert_awaited_once()

    def test_origin_matrix(self):
        cases = [
            ("http://localhost:8000", "localhost:8000", "ws", True),
            ("http://127.0.0.1:8000", "127.0.0.1:8000", "ws", True),
            ("http://[::1]:8000", "[::1]:8000", "ws", True),
            ("http://LOCALHOST:80", "localhost", "ws", True),
            ("https://jin.example", "jin.example:443", "wss", True),
            ("http://evil.example", "127.0.0.1:8000", "ws", False),
            ("http://localhost:8001", "localhost:8000", "ws", False),
            ("https://localhost:8000", "localhost:8000", "ws", False),
            ("http://localhost:8000.evil.example", "localhost:8000", "ws", False),
            ("http://evil.example@localhost:8000", "localhost:8000", "ws", False),
        ]
        for origin in (None, "null", "", "http://[", "http://localhost:8000/",
                       "http://localhost:8000?", "http://localhost:8000#",
                       "http://localhost:8000\n", "http://localhost:bad",
                       "http://localhost:8000 http://evil.example"):
            cases.append((origin, "localhost:8000", "ws", False))
        for origin, host, scheme, expected in cases:
            with self.subTest(origin=origin, host=host, scheme=scheme):
                headers = [(b"host", host.encode())]
                if origin is not None:
                    headers.append((b"origin", origin.encode()))
                socket = WebSocket({"type": "websocket", "scheme": scheme, "headers": headers}, None, None)
                self.assertEqual(has_same_origin(socket), expected)

    def test_rejected_handshake_never_touches_runtime(self):
        app = FastAPI()
        app.include_router(ws.websocket_router)
        with TestClient(app) as client, patch.object(ws, "get_resume_context_store") as store, \
                patch.object(ws, "get_or_create_connection_context") as create, \
                patch.object(ws, "run_runtime_session") as run:
            for suffix in ("", "?client_id=existing&resume=soft", "?anonymous=1"):
                for headers in ({}, {"origin": "null"}, {"origin": "http://evil.example"},
                                httpx.Headers([("origin", "http://testserver"), ("origin", "http://evil.example")]),
                                {"origin": "http://evil.example", "x-forwarded-host": "evil.example"}):
                    with self.subTest(suffix=suffix, headers=headers):
                        with self.assertRaises(WebSocketDisconnect) as caught:
                            with client.websocket_connect("/ws/chat" + suffix, headers=headers):
                                self.fail("Untrusted handshake was accepted")
                        self.assertEqual(caught.exception.code, 1008)
            store.assert_not_called()
            create.assert_not_called()
            run.assert_not_called()

    def test_same_origin_reaches_runtime_after_accept(self):
        app = FastAPI()
        app.include_router(ws.websocket_router)
        # Stop at runtime creation, before any real memory/log/model side effects.
        with TestClient(app) as client, patch.object(
            ws, "get_or_create_connection_context", side_effect=RuntimeError("runtime reached")
        ) as create:
            with self.assertRaisesRegex(RuntimeError, "runtime reached"):
                with client.websocket_connect("/ws/chat", headers={"origin": "http://testserver"}):
                    pass
            create.assert_called_once()


if __name__ == "__main__":
    unittest.main()
