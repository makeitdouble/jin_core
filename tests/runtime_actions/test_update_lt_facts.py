import asyncio
import json
import unittest

from contracts.rules_assembler import (
    RUNTIME_ACTION_UPDATE_LT_FACTS,
    build_runtime_action_contract_instructions,
    runtime_action_emits_followup,
)
from runtime.LT_memory_utils import normalize_lt_store
from runtime.LT_lane import (
    begin_lt_attempt,
    bind_lt_attempt_task,
    get_current_lt_attempt,
    lt_attempt_can_commit,
    release_lt_attempt,
    seal_lt_attempt,
)
from runtime.runtime_context import RuntimeContext
from tests.helpers.memory import FakeLogger, FakeServiceClient
from utils.actions import RuntimeActionCall, extract_runtime_actions
from utils.actions.dispatcher import apply_runtime_action_calls
from utils.actions.update_lt_facts_actions import (
    _resolve_update_lt_fact_sources,
    preempt_update_lt_facts_actions,
    schedule_pending_update_lt_facts_actions,
)


class FakeEmitter:

    def __init__(self):
        self.events = []

    async def emit(self, payload):
        self.events.append(payload)


class RuntimeUpdateLTFactsTests(unittest.IsolatedAsyncioTestCase):

    def test_marker_parses_focused_note_and_has_no_followup(self):
        result = extract_runtime_actions(
            (
                "Memory clarified.\n"
                "<UPDATE_LT_FACTS>\n"
                "Merge F1 and F2 into one durable fact: both describe the same residence.\n"
                "</UPDATE_LT_FACTS>"
            ),
            enabled_actions=(RUNTIME_ACTION_UPDATE_LT_FACTS,),
        )

        self.assertEqual(result.text, "Memory clarified.")
        self.assertEqual(len(result.actions), 1)
        self.assertEqual(result.actions[0].name, RUNTIME_ACTION_UPDATE_LT_FACTS)
        self.assertEqual(
            json.loads(result.actions[0].payload),
            {
                "fact_ids": ["F1", "F2"],
                "message": (
                    "Merge F1 and F2 into one durable fact: both describe "
                    "the same residence."
                ),
            },
        )
        self.assertFalse(
            runtime_action_emits_followup(RUNTIME_ACTION_UPDATE_LT_FACTS)
        )

        instructions = build_runtime_action_contract_instructions(
            RUNTIME_ACTION_UPDATE_LT_FACTS
        )
        self.assertIn("ask one brief natural question", instructions)
        self.assertIn("harmless repetition", instructions)
        self.assertIn("plain English text", instructions)
        self.assertIn("update, merge, or create", instructions)
        self.assertNotIn("delete", instructions.casefold())

    def test_marker_accepts_create_note_without_fact_ids(self):
        result = extract_runtime_actions(
            (
                "Memory clarified.\n"
                "<UPDATE_LT_FACTS>\n"
                "Create a new durable fact: the user prefers Russian replies.\n"
                "</UPDATE_LT_FACTS>"
            ),
            enabled_actions=(RUNTIME_ACTION_UPDATE_LT_FACTS,),
        )

        self.assertEqual(result.text, "Memory clarified.")
        self.assertEqual(len(result.actions), 1)
        self.assertEqual(
            json.loads(result.actions[0].payload),
            {
                "fact_ids": [],
                "message": (
                    "Create a new durable fact: the user prefers Russian "
                    "replies."
                ),
            },
        )

    def test_restore_priming_sources_explicit_lt_note_from_archived_user_turn(self):
        context = RuntimeContext(
            websocket=None,
            emitter=None,
            logger=None,
            clients={},
        )
        context.session_id = "new-session"
        context.runtime_current_turn_id = "turn_000028"
        context.runtime_session_restore_priming = True
        context.runtime_archived_session_id = "source-session"

        from unittest.mock import patch

        archived = {
            "messages": [
                {
                    "role": "user",
                    "turn_id": "turn_000027",
                    "text": "create a test fact",
                },
                {
                    "role": "jin",
                    "turn_id": "turn_000027",
                    "text": "",
                },
            ],
        }
        with patch(
            "utils.session_restore.build_archived_session_restore_payload",
            return_value=archived,
        ):
            sources = _resolve_update_lt_fact_sources(context)

        self.assertEqual(sources, [{
            "session_id": "source-session",
            "turn_id": "turn_000027",
        }])

    def test_marker_rejects_destructive_plain_text_note(self):
        result = extract_runtime_actions(
            (
                "before\n"
                "<UPDATE_LT_FACTS>\n"
                "Delete F1 from long-term memory.\n"
                "</UPDATE_LT_FACTS>\n"
                "after"
            ),
            enabled_actions=(RUNTIME_ACTION_UPDATE_LT_FACTS,),
        )

        self.assertEqual(result.text, "before\nafter")
        self.assertEqual(result.actions, ())

    def test_marker_allows_removing_content_from_existing_fact(self):
        result = extract_runtime_actions(
            (
                "<UPDATE_LT_FACTS>\n"
                "Update F305: Remove white bonfire with cutout from the "
                "description. Keep coffee, bong, and bricks.\n"
                "</UPDATE_LT_FACTS>"
            ),
            enabled_actions=(RUNTIME_ACTION_UPDATE_LT_FACTS,),
        )

        self.assertEqual(len(result.actions), 1)
        payload = json.loads(result.actions[0].payload)
        self.assertEqual(payload["fact_ids"], ["F305"])
        self.assertIn("Remove white bonfire", payload["message"])

    def test_invalid_note_marker_is_removed_without_action(self):
        result = extract_runtime_actions(
            (
                "before\n"
                "<UPDATE_LT_FACTS>\n"
                '{"fact_ids":["F1"],"message":""}\n'
                "</UPDATE_LT_FACTS>\n"
                "after"
            ),
            enabled_actions=(RUNTIME_ACTION_UPDATE_LT_FACTS,),
        )

        self.assertEqual(result.text, "before\nafter")
        self.assertEqual(result.actions, ())

    async def test_runtime_action_updates_lt_in_background(self):
        emitter = FakeEmitter()
        logger = FakeLogger()
        service_client = FakeServiceClient(json.dumps({
            "action": "replace",
            "replacement_facts": [
                {
                    "key": "user.relationship.taras",
                    "value": (
                        "Taras is both a close friend and an active "
                        "technical stakeholder."
                    ),
                    "category": "user_fact",
                },
            ],
        }))
        context = RuntimeContext(
            websocket=None,
            emitter=emitter,
            logger=logger,
            clients={"service": service_client},
        )
        context.runtime_lt_file_store_enabled = False
        context.delayed_memory_file_store_enabled = False
        context.runtime_long_term_memory_store = normalize_lt_store({
            "facts": [
                {
                    "id": "F1",
                    "key": "user.social_connections",
                    "value": "Taras is a close friend.",
                    "category": "user_fact",
                },
                {
                    "id": "F2",
                    "key": "user.stakeholder_profile",
                    "value": "Taras is a key technical stakeholder.",
                    "category": "project_fact",
                },
            ],
        })
        context.delayed_memory_reports = {
            "abc123": {
                "title": "Social and project context",
                "long_term_facts_ids": [
                    "F1",
                    "F2",
                ],
            },
        }
        action = RuntimeActionCall(
            name=RUNTIME_ACTION_UPDATE_LT_FACTS,
            payload=json.dumps({
                "fact_ids": ["F1", "F2"],
                "message": (
                    "Taras is both a close friend and an active technical "
                    "stakeholder."
                ),
            }),
        )

        applied = await apply_runtime_action_calls(
            context,
            (action,),
            action_display_ids={id(action): "update_lt_facts_001"},
        )

        self.assertEqual(applied, 1)
        tasks = list(getattr(context, "background_tasks", set()))
        self.assertEqual(len(tasks), 1)
        await asyncio.gather(*tasks)

        facts = context.runtime_long_term_memory_store["facts"]
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["id"], "F3")
        self.assertEqual(facts[0]["key"], "user.relationship.taras")
        self.assertIn("close friend", facts[0]["value"])
        self.assertEqual(facts[0]["source_fact_ids"], ["F1", "F2"])
        self.assertEqual(
            context.runtime_long_term_memory_store["deleted_fact_ids"],
            ["F1", "F2"],
        )

        self.assertEqual(
            context.delayed_memory_reports["abc123"]["facts_ids"],
            ["F3"],
        )
        self.assertNotIn(
            "absorbed_fact_ids",
            context.delayed_memory_reports["abc123"],
        )
        self.assertNotIn(
            "long_term_facts_ids",
            context.delayed_memory_reports["abc123"],
        )

        lifecycle = [
            event
            for event in emitter.events
            if event.get("type") == "runtime_action"
            and event.get("action") == "update_lt_facts"
        ]
        self.assertTrue(any(event.get("status") == "completed" for event in lifecycle))
        completed_event = next(
            event
            for event in lifecycle
            if event.get("status") == "completed"
        )
        self.assertEqual(completed_event.get("text"), "UPDATE_LT_FACTS")
        self.assertTrue(completed_event.get("lt_queued"))
        self.assertEqual(
            completed_event.get("detail"),
            "Queued for L-T update.",
        )
        self.assertFalse(any("lt_result" in event for event in lifecycle))
        self.assertFalse(
            any(event.get("status") == "failed" for event in lifecycle)
        )

    async def test_foreground_action_retires_marker_then_runs_after_frame_request(self):
        emitter = FakeEmitter()
        logger = FakeLogger()
        context = RuntimeContext(
            websocket=None,
            emitter=emitter,
            logger=logger,
            clients={},
        )
        context.runtime_foreground_turn_running = True
        note_started = asyncio.Event()
        release_note = asyncio.Event()

        async def fake_run_lt_jin_note(*, context, note):
            del context, note
            note_started.set()
            await release_note.wait()
            return {
                "phase": "jin_note",
                "status": "completed",
                "changed": False,
                "change": {},
            }

        action = RuntimeActionCall(
            name=RUNTIME_ACTION_UPDATE_LT_FACTS,
            payload=json.dumps({
                "fact_ids": ["F1"],
                "message": "Update F1 with the clarified wording.",
            }),
        )

        from unittest.mock import patch

        with patch(
            "utils.actions.update_lt_facts_actions.run_lt_jin_note",
            new=fake_run_lt_jin_note,
        ):
            applied = await apply_runtime_action_calls(
                context,
                (action,),
                action_display_ids={id(action): "update_lt_facts_001"},
            )

            self.assertEqual(applied, 1)
            self.assertEqual(len(context.runtime_lt_explicit_note_queue), 1)
            self.assertIsNone(context.runtime_lt_active_attempt)
            completed = [
                event
                for event in emitter.events
                if event.get("type") == "runtime_action"
                and event.get("action") == "update_lt_facts"
                and event.get("status") == "completed"
            ]
            self.assertEqual(len(completed), 1)
            self.assertTrue(completed[0].get("lt_queued"))

            frame_request_started = asyncio.Event()
            frame_release = asyncio.Event()

            async def fake_frame_task():
                await frame_release.wait()

            frame_task = asyncio.create_task(fake_frame_task())
            lt_task = schedule_pending_update_lt_facts_actions(
                context,
                frame_task=frame_task,
                frame_request_event=frame_request_started,
            )
            await asyncio.sleep(0)
            self.assertFalse(note_started.is_set())

            frame_request_started.set()
            await asyncio.wait_for(note_started.wait(), timeout=0.2)

            # A real next USER message preempts only the attempt, not the
            # queued instruction. It is retried after the next FRAME request.
            self.assertTrue(await preempt_update_lt_facts_actions(
                context,
                reason="user_message",
            ))
            self.assertEqual(len(context.runtime_lt_explicit_note_queue), 1)
            await asyncio.gather(lt_task, return_exceptions=True)

            note_started.clear()
            release_note.set()
            next_frame_request_started = asyncio.Event()
            next_frame_request_started.set()
            retry_task = schedule_pending_update_lt_facts_actions(
                context,
                frame_task=frame_task,
                frame_request_event=next_frame_request_started,
            )
            await asyncio.wait_for(note_started.wait(), timeout=0.2)
            await retry_task
            self.assertEqual(context.runtime_lt_explicit_note_queue, [])

            frame_release.set()
            await frame_task

    async def test_sealed_explicit_tail_cannot_start_next_note_under_new_foreground_turn(self):
        context = RuntimeContext(
            websocket=None,
            emitter=FakeEmitter(),
            logger=FakeLogger(),
            clients={},
        )
        context.runtime_foreground_turn_running = True
        first_committed = asyncio.Event()
        release_first_tail = asyncio.Event()
        second_started = asyncio.Event()
        seen = []

        async def fake_run_lt_jin_note(*, context, note):
            message = note["message"]
            seen.append(message)
            if message == "first":
                seal_lt_attempt(get_current_lt_attempt(context))
                first_committed.set()
                await release_first_tail.wait()
            else:
                second_started.set()
            return {
                "phase": "jin_note",
                "status": "completed",
                "changed": False,
                "change": {},
            }

        actions = (
            RuntimeActionCall(
                name=RUNTIME_ACTION_UPDATE_LT_FACTS,
                payload=json.dumps({"fact_ids": ["F1"], "message": "first"}),
            ),
            RuntimeActionCall(
                name=RUNTIME_ACTION_UPDATE_LT_FACTS,
                payload=json.dumps({"fact_ids": ["F2"], "message": "second"}),
            ),
        )

        from unittest.mock import patch

        with patch(
            "utils.actions.update_lt_facts_actions.run_lt_jin_note",
            new=fake_run_lt_jin_note,
        ):
            applied = await apply_runtime_action_calls(
                context,
                actions,
                action_display_ids={
                    id(actions[0]): "update_lt_facts_001",
                    id(actions[1]): "update_lt_facts_002",
                },
            )
            self.assertEqual(applied, 2)

            first_frame = asyncio.Event()
            first_frame.set()
            task = schedule_pending_update_lt_facts_actions(
                context,
                frame_request_event=first_frame,
            )
            await asyncio.wait_for(first_committed.wait(), timeout=0.2)

            # The current note has already crossed its commit boundary, so it
            # is not cancelled. Pending notes are nevertheless detached from
            # the old FRAME gate and must not begin under the new Brain turn.
            self.assertFalse(await preempt_update_lt_facts_actions(
                context,
                reason="user_message",
            ))
            release_first_tail.set()
            await asyncio.wait_for(task, timeout=0.2)
            self.assertFalse(second_started.is_set())
            self.assertEqual(len(context.runtime_lt_explicit_note_queue), 1)
            self.assertEqual(seen, ["first"])

            next_frame = asyncio.Event()
            retry_task = schedule_pending_update_lt_facts_actions(
                context,
                frame_request_event=next_frame,
            )
            await asyncio.sleep(0)
            self.assertFalse(second_started.is_set())
            next_frame.set()
            await asyncio.wait_for(second_started.wait(), timeout=0.2)
            await retry_task

        self.assertEqual(seen, ["first", "second"])
        self.assertEqual(context.runtime_lt_explicit_note_queue, [])

    async def test_sealed_auto_tail_does_not_resume_explicit_note_after_new_turn_clears_frame_gate(self):
        context = RuntimeContext(
            websocket=None,
            emitter=FakeEmitter(),
            logger=FakeLogger(),
            clients={},
        )
        context.runtime_foreground_turn_running = True
        release_auto_tail = asyncio.Event()
        note_started = asyncio.Event()

        async def sealed_auto_tail():
            try:
                await release_auto_tail.wait()
            finally:
                release_lt_attempt(context, get_current_lt_attempt(context))

        async def fake_run_lt_jin_note(*, context, note):
            del context, note
            note_started.set()
            return {
                "phase": "jin_note",
                "status": "completed",
                "changed": False,
                "change": {},
            }

        action = RuntimeActionCall(
            name=RUNTIME_ACTION_UPDATE_LT_FACTS,
            payload=json.dumps({
                "fact_ids": ["F1"],
                "message": "Update F1 with the clarified wording.",
            }),
        )

        from unittest.mock import patch

        with patch(
            "utils.actions.update_lt_facts_actions.run_lt_jin_note",
            new=fake_run_lt_jin_note,
        ):
            applied = await apply_runtime_action_calls(
                context,
                (action,),
                action_display_ids={id(action): "update_lt_facts_001"},
            )
            self.assertEqual(applied, 1)

            auto_task = asyncio.create_task(sealed_auto_tail())
            auto_attempt = begin_lt_attempt(
                context,
                kind="auto",
                phase="merge",
            )
            bind_lt_attempt_task(auto_attempt, auto_task)
            seal_lt_attempt(auto_attempt)

            old_frame = asyncio.Event()
            old_frame.set()
            self.assertIs(
                schedule_pending_update_lt_facts_actions(
                    context,
                    frame_request_event=old_frame,
                ),
                auto_task,
            )
            self.assertTrue(
                context.runtime_lt_explicit_note_queue[0][
                    "_lt_frame_gate_bound"
                ]
            )

            # A new USER turn clears the old FRAME ownership. The sealed auto
            # tail is allowed to finish, but its done-callback must not rebind
            # the queued explicit note as an immediate/no-FRAME request.
            self.assertFalse(await preempt_update_lt_facts_actions(
                context,
                reason="user_message",
            ))
            self.assertFalse(
                context.runtime_lt_explicit_note_queue[0][
                    "_lt_frame_gate_bound"
                ]
            )

            release_auto_tail.set()
            await asyncio.wait_for(auto_task, timeout=0.2)
            await asyncio.sleep(0)
            await asyncio.sleep(0)

            self.assertFalse(note_started.is_set())
            self.assertIsNone(context.runtime_lt_active_attempt)
            self.assertEqual(len(context.runtime_lt_explicit_note_queue), 1)

            next_frame = asyncio.Event()
            retry_task = schedule_pending_update_lt_facts_actions(
                context,
                frame_request_event=next_frame,
            )
            await asyncio.sleep(0)
            self.assertFalse(note_started.is_set())
            next_frame.set()
            await asyncio.wait_for(note_started.wait(), timeout=0.2)
            await retry_task

        self.assertEqual(context.runtime_lt_explicit_note_queue, [])

    async def test_runtime_action_does_not_wait_for_cancelled_idle_lt_task(self):
        emitter = FakeEmitter()
        logger = FakeLogger()
        context = RuntimeContext(
            websocket=None,
            emitter=emitter,
            logger=logger,
            clients={},
        )
        release_idle = asyncio.Event()
        note_started = asyncio.Event()

        async def stubborn_idle_task():
            try:
                await release_idle.wait()
            except asyncio.CancelledError:
                # Simulate a provider request that takes time to unwind after
                # local cancellation. Foreground L-T must not wait for it.
                await release_idle.wait()

        async def fake_run_lt_jin_note(*, context, note):
            del note
            attempt = get_current_lt_attempt(context)
            explicit_attempt_ids.append(attempt.id)
            note_started.set()
            return {
                "phase": "jin_note",
                "status": "completed",
                "changed": False,
                "change": {},
            }

        idle_task = asyncio.create_task(stubborn_idle_task())
        idle_attempt = begin_lt_attempt(
            context,
            kind="auto",
            phase="extraction",
        )
        bind_lt_attempt_task(idle_attempt, idle_task)
        explicit_attempt_ids = []
        action = RuntimeActionCall(
            name=RUNTIME_ACTION_UPDATE_LT_FACTS,
            payload=json.dumps({
                "fact_ids": ["F1"],
                "message": "Update F1: keep the clarified wording.",
            }),
        )

        try:
            from unittest.mock import patch

            with patch(
                "utils.actions.update_lt_facts_actions.run_lt_jin_note",
                new=fake_run_lt_jin_note,
            ):
                applied = await apply_runtime_action_calls(
                    context,
                    (action,),
                    action_display_ids={id(action): "update_lt_facts_001"},
                )

                self.assertEqual(applied, 1)
                await asyncio.wait_for(note_started.wait(), timeout=0.2)
                self.assertTrue(idle_attempt.cancelled)
                self.assertFalse(lt_attempt_can_commit(context, idle_attempt))
                self.assertEqual(len(explicit_attempt_ids), 1)
                self.assertNotEqual(explicit_attempt_ids[0], idle_attempt.id)
                tasks = list(getattr(context, "background_tasks", set()))
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=0.2)
        finally:
            release_idle.set()
            await asyncio.gather(idle_task, return_exceptions=True)

    async def test_transient_store_conflict_preserves_explicit_note_for_retry(self):
        context = RuntimeContext(
            websocket=None,
            emitter=FakeEmitter(),
            logger=FakeLogger(),
            clients={},
        )
        attempts = 0

        async def fake_run_lt_jin_note(*, context, note):
            nonlocal attempts
            del context, note
            attempts += 1
            return {
                "phase": "jin_note",
                "status": "skipped",
                "reason": "store_changed_during_jin_note",
            }

        action = RuntimeActionCall(
            name=RUNTIME_ACTION_UPDATE_LT_FACTS,
            payload=json.dumps({
                "fact_ids": ["F1"],
                "message": "Update F1 with the clarified wording.",
            }),
        )

        from unittest.mock import patch

        with patch(
            "utils.actions.update_lt_facts_actions.run_lt_jin_note",
            new=fake_run_lt_jin_note,
        ):
            applied = await apply_runtime_action_calls(
                context,
                (action,),
                action_display_ids={id(action): "update_lt_facts_001"},
            )
            self.assertEqual(applied, 1)
            tasks = list(getattr(context, "background_tasks", set()))
            await asyncio.gather(*tasks, return_exceptions=True)

        self.assertEqual(attempts, 1)
        self.assertEqual(len(context.runtime_lt_explicit_note_queue), 1)
        entry = context.runtime_lt_explicit_note_queue[0]
        self.assertFalse(entry.get("_lt_frame_gate_bound"))
        self.assertIsNone(context.runtime_lt_active_attempt)

    async def test_runtime_action_can_create_lt_without_selected_facts(self):
        emitter = FakeEmitter()
        logger = FakeLogger()
        service_client = FakeServiceClient(json.dumps({
            "action": "create",
            "replacement_facts": [],
            "new_facts": [
                {
                    "key": "user.preference.response_language",
                    "value": "The user prefers Russian replies.",
                    "category": "user_preference",
                },
            ],
        }))
        context = RuntimeContext(
            websocket=None,
            emitter=emitter,
            logger=logger,
            clients={"service": service_client},
        )
        context.runtime_lt_file_store_enabled = False
        context.delayed_memory_file_store_enabled = False
        context.runtime_long_term_memory_store = normalize_lt_store({"facts": []})
        action = RuntimeActionCall(
            name=RUNTIME_ACTION_UPDATE_LT_FACTS,
            payload=json.dumps({
                "fact_ids": [],
                "message": "Create a new durable fact: the user prefers Russian replies.",
            }),
        )

        applied = await apply_runtime_action_calls(
            context,
            (action,),
            action_display_ids={id(action): "update_lt_facts_001"},
        )

        self.assertEqual(applied, 1)
        tasks = list(getattr(context, "background_tasks", set()))
        self.assertEqual(len(tasks), 1)
        await asyncio.gather(*tasks)

        facts = context.runtime_long_term_memory_store["facts"]
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["key"], "user.preference.response_language")
        self.assertEqual(facts[0]["value"], "The user prefers Russian replies.")

        lifecycle = [
            event
            for event in emitter.events
            if event.get("type") == "runtime_action"
            and event.get("action") == "update_lt_facts"
        ]
        self.assertTrue(any(
            event.get("status") == "completed"
            and event.get("lt_queued") is True
            and event.get("detail") == "Queued for L-T update."
            for event in lifecycle
        ))

    async def test_runtime_action_can_update_and_create_in_one_explicit_note(self):
        emitter = FakeEmitter()
        logger = FakeLogger()
        service_client = FakeServiceClient(json.dumps({
            "action": "update",
            "replacement_facts": [
                {
                    "key": "project_fact.jin_architecture",
                    "value": (
                        "Gemma 26B A4B is the current active brain and "
                        "Qwen 3.8 27B is the night brain model."
                    ),
                    "category": "project_fact",
                },
            ],
            "new_facts": [
                {
                    "key": "project_fact.model_test_goal",
                    "value": "The current goal is to test Qwen 3.6 27B.",
                    "category": "project_fact",
                },
            ],
        }))
        context = RuntimeContext(
            websocket=None,
            emitter=emitter,
            logger=logger,
            clients={"service": service_client},
        )
        context.runtime_lt_file_store_enabled = False
        context.delayed_memory_file_store_enabled = False
        context.runtime_long_term_memory_store = normalize_lt_store({
            "facts": [
                {
                    "id": "F96",
                    "key": "project_fact.jin_architecture",
                    "value": "Qwen 3.8 27B is the current active brain.",
                    "category": "project_fact",
                },
            ],
        })
        action = RuntimeActionCall(
            name=RUNTIME_ACTION_UPDATE_LT_FACTS,
            payload=json.dumps({
                "fact_ids": ["F96"],
                "message": (
                    "Update F96: Gemma 26B A4B is the current active brain, "
                    "and Qwen 3.8 27B is the night brain model. Create a new "
                    "fact: the current developmental goal is to test Qwen "
                    "3.6 27B."
                ),
            }),
        )

        applied = await apply_runtime_action_calls(
            context,
            (action,),
            action_display_ids={id(action): "update_lt_facts_001"},
        )

        self.assertEqual(applied, 1)
        tasks = list(getattr(context, "background_tasks", set()))
        self.assertEqual(len(tasks), 1)
        await asyncio.gather(*tasks)

        facts = context.runtime_long_term_memory_store["facts"]
        self.assertEqual([fact["id"] for fact in facts], ["F96", "F97"])
        self.assertIn("current active brain", facts[0]["value"])
        self.assertEqual(facts[1]["key"], "project_fact.model_test_goal")

        lifecycle = [
            event
            for event in emitter.events
            if event.get("type") == "runtime_action"
            and event.get("action") == "update_lt_facts"
        ]
        self.assertTrue(any(event.get("status") == "completed" for event in lifecycle))
        self.assertFalse(any(event.get("status") == "failed" for event in lifecycle))


if __name__ == "__main__":
    unittest.main()
