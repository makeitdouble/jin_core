import json
import time
import unittest

from runtime.deep_web_search import (
    build_deep_search_current_sequence,
    DeepSearchPool,
    DeepSearchWorker,
    parse_deep_search_worker_response,
    run_deep_web_search,
)
from runtime.runtime_context import RuntimeContext, RuntimeEmitter
from utils.context.session_actions import build_session_actions_history_context
from utils.session_actions_history import record_session_action_history


class FakeWebSocket:
    def __init__(self):
        self.messages = []

    async def send_json(self, payload):
        self.messages.append(payload)


class FakeEmitter(RuntimeEmitter):
    def __init__(self, websocket):
        super().__init__(websocket)
        self.payloads = []

    async def emit(self, payload):
        self.payloads.append(payload)


class FakeLogger:
    def __init__(self):
        self.messages = []

    async def log_service(self, message):
        self.messages.append(("service", message))

    async def log_runtime(self, message):
        self.messages.append(("runtime", message))

    async def log_error(self, message, details=None):
        self.messages.append(("error", message, details))


class FakeServiceClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    async def ask(
        self,
        *,
        system_prompt,
        user_prompt,
        temperature,
        max_tokens,
    ):
        self.prompts.append({
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
        })
        if self.responses:
            content = self.responses.pop(0)
        else:
            content = json.dumps({
                "queries": [],
                "spawn": [],
                "report": "final synthesis",
                "done": True,
            })
        return {
            "choices": [{
                "message": {
                    "content": content,
                }
            }]
        }


class FakeSearchProvider:
    def __init__(self):
        self.queries = []

    async def __call__(self, query):
        self.queries.append(query)
        return [{
            "title": f"Result for {query}",
            "source": "example.test",
            "url": f"https://example.test/{len(self.queries)}",
            "quote": f"Evidence for {query}",
            "excerpt": "",
        }]


def worker_response(queries, *, report="", done=False, spawn=None):
    return json.dumps({
        "queries": queries,
        "spawn": spawn or [],
        "report": report,
        "done": done,
    })


def make_context(service_client, search_provider):
    websocket = FakeWebSocket()
    context = RuntimeContext(
        websocket=websocket,
        emitter=FakeEmitter(websocket),
        logger=FakeLogger(),
        clients={
            "service": service_client,
            "brain": service_client,
        },
    )
    context.search_provider = search_provider
    context.runtime_current_turn_id = "turn-deep-search"
    context.runtime_current_sequence_turn_id = "turn-deep-search"
    context.runtime_current_sequence_started_at = time.time() - 1
    return context


class DeepWebSearchFlowTests(unittest.IsolatedAsyncioTestCase):
    def test_worker_response_parser_accepts_fenced_json(self):
        parsed = parse_deep_search_worker_response(
            "```json\n"
            '{"queries":["one","two"],"spawn":["branch"],'
            '"report":"ok","done":false}'
            "\n```"
        )
        self.assertEqual(parsed["queries"], ["one", "two"])
        self.assertEqual(parsed["spawn"], ["branch"])
        self.assertEqual(parsed["report"], "ok")
        self.assertFalse(parsed["done"])

    def test_current_sequence_contains_shared_budget_and_previous_steps(self):
        pool = DeepSearchPool(
            objective="find similar music",
            max_queries=10,
            queries_per_worker=3,
        )
        pool.searches.append({
            "id": "web_search_001",
            "query": "hitman soundtrack style",
            "compact": "status=FOUND; source evidence",
            "result": "",
        })
        worker = DeepSearchWorker(
            worker_id=2,
            task="albums",
            last_note="2 queries remaining",
        )
        prompt = build_deep_search_current_sequence(pool, worker)
        self.assertIn("research_objective: find similar music", prompt)
        self.assertIn("current_task: albums", prompt)
        self.assertIn("1/10 used; 9 remaining", prompt)
        self.assertIn("hitman soundtrack style", prompt)
        self.assertIn("runtime_note: 2 queries remaining", prompt)

    async def test_runtime_caps_actual_web_searches_at_ten(self):
        service = FakeServiceClient([
            worker_response(["q1", "q2", "q3"]),
            worker_response(["q4", "q5", "q6"]),
            worker_response(["q7", "q8", "q9"]),
            worker_response(["q10", "q11", "q12"]),
            worker_response([], report="cap-aware report", done=True),
            worker_response([], report="final report", done=True),
        ])
        provider = FakeSearchProvider()
        context = make_context(service, provider)

        result = await run_deep_web_search(
            context=context,
            objective="research something difficult",
        )

        self.assertEqual(
            provider.queries,
            [f"q{i}" for i in range(1, 11)],
        )
        self.assertNotIn("q11", provider.queries)
        self.assertNotIn("q12", provider.queries)
        self.assertIn('used="10" max="10" remaining="0"', result)
        self.assertIn("final report", result)

        runtime_messages = [
            payload
            for payload in context.websocket.messages
            if payload.get("type") == "runtime_action"
            and payload.get("action") == "web_search"
        ]
        started = [
            payload for payload in runtime_messages
            if payload.get("status") == "started"
        ]
        completed = [
            payload for payload in runtime_messages
            if payload.get("status") == "completed"
        ]
        self.assertEqual(len(started), 10)
        self.assertEqual(len(completed), 10)
        self.assertEqual(
            [payload["query"] for payload in started],
            [f"q{i}" for i in range(1, 11)],
        )
        self.assertTrue(
            all(
                payload.get("deep_search_child") is True
                for payload in started
            )
        )
        self.assertEqual(
            [payload["query"] for payload in completed],
            [f"q{i}" for i in range(1, 11)],
        )
        self.assertTrue(
            all(
                payload.get("deep_search_child") is True
                for payload in completed
            )
        )

        # The worker that requested three searches with one slot left is called
        # again after q10 and sees both the results and the deterministic cap note.
        cap_prompt = service.prompts[4]["user_prompt"]
        self.assertIn("10/10 used; 0 remaining", cap_prompt)
        self.assertIn("3 new queries requested; 1 executed", cap_prompt)
        self.assertIn("global search cap 10 reached", cap_prompt)
        self.assertIn("q10", cap_prompt)

    async def test_current_sequence_ui_log_keeps_queries_separate_without_counts(self):
        service = FakeServiceClient([
            worker_response(["blue tomato varieties", "blue tomato anthocyanins"], done=True),
            worker_response([], report="done", done=True),
        ])
        provider = FakeSearchProvider()
        context = make_context(service, provider)

        await run_deep_web_search(
            context=context,
            objective="blue tomato research",
        )

        current_sequence = build_session_actions_history_context(
            context,
            current_sequence=True,
            sequence_user_message="research blue tomatoes",
        )
        self.assertIn("WEB_SEARCH: blue tomato varieties", current_sequence)
        self.assertIn("WEB_SEARCH: blue tomato anthocyanins", current_sequence)
        self.assertNotIn("WEB_SEARCH ×", current_sequence)

    def test_plain_sequence_history_does_not_use_jin_message_wording(self):
        service = FakeServiceClient([])
        provider = FakeSearchProvider()
        context = make_context(service, provider)
        record_session_action_history(
            context,
            "WEB_SEARCH: albums hitman",
            preserve_separate=True,
            plain_sequence=True,
        )
        block = build_session_actions_history_context(
            context,
            current_sequence=True,
            sequence_user_message="find music",
        )
        self.assertIn("1. WEB_SEARCH: albums hitman", block)
        self.assertNotIn("JIN message 1 executed", block)


if __name__ == "__main__":
    unittest.main()
