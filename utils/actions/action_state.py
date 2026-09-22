"""Generic admission state for source-ordered runtime actions."""

from contracts.rules_assembler import (
    RUNTIME_ACTION_SAVE_DELAYED_MEMORY,
    runtime_action_emits_followup,
)
from rules.runtime import ACTION_FAILURE_FOLLOWUP_MESSAGE, ACTION_REJECTED_MISSING_TRIGGER_WORDS_MESSAGE
from runtime.anonymous_mode import (
    RESTRICTED_WRITE_REASON,
    build_restricted_write_event,
    runtime_action_write_is_restricted,
)
from runtime.behavior_contract import (
    get_action_guard_blocker_match,
    get_action_guard_name_for_runtime_action,
    should_pause_action_guard_for_confirmation,
)
from utils.brain_client_utils import (
    build_action_missing_trigger_words_message,
    build_delayed_memory_report,
)
from utils.skills_asset_utils import normalize_skill_name
from utils.tool_results import TOOL_RESULT_KIND_RUNTIME_ACTION, record_runtime_tool_result

from .action_dedup import ActionDedup
from .action_registry import SKILL_WORKFLOW_ACTIONS, SOURCE_REPEAT_ACTIONS, get_action
from .result_reuse import reuse_action_result


class ActionState:
    """Batch-local checks shared by every action.

    Concrete action rules live in action_registry.py. This object only keeps
    cross-action state such as dedup, guard results and skill-barrier state.
    """

    def __init__(self, batch):
        self.batch = batch
        self.dedup = ActionDedup(
            batch.context,
            batch.resolved_runtime_message_id,
            batch.resolved_runtime_turn_id,
        )
        self.rejected_action_events = {}
        self.rejected_active_memory_results = []
        self.delete_active_memory_ids_seen = set()
        self.delete_active_memory_failures_seen = set()
        self.save_delayed_memory_seen = set()
        self.handled_action_keys = set()
        self.had_search_queries = bool(
            getattr(batch.context, "runtime_search_queries", [])
        )
        self.had_deep_search_calls = bool(
            getattr(batch.context, "runtime_deep_search_calls", [])
        )
        self.loaded_skill_names = {
            normalize_skill_name(skill.get("name", ""))
            for skill in getattr(batch.context, "runtime_loaded_skills", []) or []
            if isinstance(skill, dict) and normalize_skill_name(skill.get("name", ""))
        }

    async def _restricted(self, action):
        if runtime_action_write_is_restricted(
            self.batch.context, action.name, action.payload
        ):
            self.rejected_action_events[id(action)] = build_restricted_write_event(
                action.name,
                include_followup=runtime_action_emits_followup(action.name),
            )
            logger = getattr(self.batch.context, "logger", None)
            log_runtime = getattr(logger, "log_runtime", None)
            if log_runtime is not None:
                await log_runtime(
                    f"[RUNTIME ACTION] {action.name.lower()} failed: {RESTRICTED_WRITE_REASON}"
                )
            return False
        return True

    def _guard(self, action):
        action_guard_confirmed = id(action) in self.batch.confirmed_action_ids
        if id(action) in self.batch.rejected_action_ids:
            self.rejected_action_events[id(action)] = {
                "status": "failed",
                "error": "user_rejected_runtime_action",
                "title": f"{action.name} cancelled",
                "confirmation_id": self.batch.guard_confirmation_ids.get(id(action), ""),
            }
            return False

        guard_name = get_action_guard_name_for_runtime_action(action.name)
        blocker_match = (
            get_action_guard_blocker_match(guard_name, self.batch.resolved_user_message)
            if guard_name
            else ""
        )
        if blocker_match:
            from utils.context.runtime_state import format_runtime_blocked_trigger_word_message

            self.rejected_action_events[id(action)] = {
                "status": "failed",
                "error": "behavior_contract_blocker_matched",
                "blocker": blocker_match,
                "failure_followup_message": format_runtime_blocked_trigger_word_message(
                    blocker_match
                ),
                "confirmation_id": self.batch.guard_confirmation_ids.get(id(action), ""),
            }
            return False

        if (
            guard_name
            and not action_guard_confirmed
            and should_pause_action_guard_for_confirmation(
                guard_name,
                self.batch.resolved_user_message,
                context=self.batch.context,
            )
        ):
            rejection_event = {
                "status": "failed",
                "error": "user_did_not_confirm_runtime_action",
                "failure_followup_message": build_action_missing_trigger_words_message(
                    action.name,
                    ACTION_REJECTED_MISSING_TRIGGER_WORDS_MESSAGE,
                ),
                "confirmation_id": self.batch.guard_confirmation_ids.get(id(action), ""),
            }
            if action.name == RUNTIME_ACTION_SAVE_DELAYED_MEMORY:
                rejected_report = build_delayed_memory_report(
                    self.batch.context, action.payload
                )
                rejected_title = ""
                for report_value in rejected_report.values():
                    if isinstance(report_value, dict):
                        rejected_title = str(report_value.get("title", "") or "").strip()
                    if rejected_title:
                        break
                self.batch.context.runtime_delayed_memory_save_rejected_pending = True
                self.batch.context.runtime_delayed_memory_save_rejected_title = rejected_title
                rejection_event.update(
                    {
                        "error": "user_did_not_explicitly_request_report_save",
                        "title": rejected_title,
                    }
                )
                self.save_delayed_memory_seen.add(str(action.payload or "").strip())
            self.rejected_action_events[id(action)] = rejection_event
            return False

        return True

    async def prepare(self, action):
        """Return ``ready``, ``reused``, ``rejected`` or ``skipped``."""

        definition = get_action(action.name)
        if definition is None:
            return "skipped"

        # A LOAD/UNLOAD that already ran in this emitted stream turns the
        # barrier on immediately. Later calls therefore see the new state;
        # earlier calls are never retroactively removed.
        if (
            getattr(self.batch.context, "runtime_skill_state_barrier_active", False)
            and action.name not in SKILL_WORKFLOW_ACTIONS
        ):
            reason = (
                "Action was not executed: skill context changed in this response. "
                "Read the updated skill context before emitting the action again."
            )
            self.rejected_action_events[id(action)] = {
                "status": "failed",
                "error": "skill_context_changed",
                "failure_reason": reason,
                "failure_followup_message": ACTION_FAILURE_FOLLOWUP_MESSAGE,
            }
            record_runtime_tool_result(
                self.batch.context,
                TOOL_RESULT_KIND_RUNTIME_ACTION,
                {
                    "ok": False,
                    "action": action.name.lower(),
                    "error": "skill_context_changed",
                    "detail": reason,
                    "payload": action.payload,
                },
            )
            return "rejected"

        if not await self._restricted(action):
            return "rejected"
        if not self._guard(action):
            return "rejected"

        action_key = self.dedup.key(action)
        if (
            action.name not in SOURCE_REPEAT_ACTIONS
            and action_key in self.handled_action_keys
        ):
            return "skipped"

        if await reuse_action_result(
            self.batch.context,
            action,
            runtime_message_id=self.batch.resolved_runtime_message_id,
            action_display_ids=self.batch.action_display_ids,
            with_action_context=self.batch.with_action_context_for(action),
        ):
            self.dedup.accept(action)
            self.handled_action_keys.add(action_key)
            return "reused"

        accepted = (
            definition.prepare(self, action)
            if definition.prepare is not None
            else self.dedup.accept(action)
        )
        if accepted:
            self.handled_action_keys.add(action_key)
            return "ready"
        if id(action) in self.rejected_action_events:
            return "rejected"
        return "skipped"
