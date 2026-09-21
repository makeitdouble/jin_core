from dataclasses import dataclass

from utils.brain_client_utils import resolve_runtime_action_user_message


@dataclass
class ActionContext:
    """Normalized metadata shared while one emitted action stream is running."""

    context: object
    action_context_snapshot: dict | None
    confirmed_action_ids: set
    rejected_action_ids: set
    guard_confirmation_ids: dict
    action_display_ids: dict
    resolved_runtime_message_id: str
    resolved_runtime_turn_id: str
    resolved_user_message: str

    def with_action_context(self, payload: dict) -> dict:
        enriched = dict(payload)
        if self.resolved_runtime_turn_id:
            enriched["runtime_turn_id"] = self.resolved_runtime_turn_id
        if self.resolved_runtime_message_id:
            enriched["runtime_message_id"] = self.resolved_runtime_message_id
        if self.action_context_snapshot:
            enriched["context"] = self.action_context_snapshot
        if getattr(self.context, "runtime_session_restore_replay_in_progress", False):
            enriched["restore_replay"] = True
        return enriched


    def with_action_context_for(self, action):
        """Bind UI lifecycle formatting to one emitted action call."""
        def enrich(payload: dict) -> dict:
            from .action_registry import apply_action_feedback

            return apply_action_feedback(
                action,
                self.with_action_context(payload),
            )

        return enrich

    @classmethod
    def create(
        cls,
        context,
        user_message,
        context_snapshot,
        confirmed_action_ids,
        rejected_action_ids,
        guard_confirmation_ids,
        action_display_ids,
        runtime_message_id,
    ):
        for name in (
            "runtime_action_events",
            "runtime_search_calls",
            "runtime_deep_search_calls",
            "runtime_loaded_skills",
        ):
            if not hasattr(context, name):
                setattr(context, name, [])
        return cls(
            context=context,
            action_context_snapshot=dict(context_snapshot)
            if isinstance(context_snapshot, dict)
            else None,
            confirmed_action_ids={int(i) for i in confirmed_action_ids or () if isinstance(i, int)},
            rejected_action_ids={int(i) for i in rejected_action_ids or () if isinstance(i, int)},
            guard_confirmation_ids=dict(guard_confirmation_ids)
            if isinstance(guard_confirmation_ids, dict)
            else {},
            action_display_ids=dict(action_display_ids)
            if isinstance(action_display_ids, dict)
            else {},
            resolved_runtime_message_id=str(runtime_message_id or "").strip(),
            resolved_runtime_turn_id=str(
                getattr(context, "runtime_current_turn_id", "") or ""
            ).strip(),
            resolved_user_message=resolve_runtime_action_user_message(context, user_message),
        )
