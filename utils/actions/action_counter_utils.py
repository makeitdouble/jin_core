from collections import OrderedDict
from dataclasses import dataclass

from contracts.rules_assembler import (
    build_runtime_action_display_text,
    get_runtime_action_display_name,
    runtime_action_has_close_tag,
)

from .common_action_utils import (
    normalize_runtime_action_name,
)


@dataclass(frozen=True)
class RuntimeActionCount:
    name: str
    count: int
    payloads: tuple[str, ...] = ()

    @property
    def payload(self) -> str:
        return (
            self.payloads[-1]
            if self.payloads
            else ""
        )


class RuntimeActionCounter:
    """Count every parsed runtime marker once, before execution dedupe."""

    def __init__(self):
        self._counts = OrderedDict()
        self._payloads = {}

    def record(self, actions) -> tuple[RuntimeActionCount, ...]:
        changed_names = []

        for action in actions or ():
            name = normalize_runtime_action_name(
                getattr(
                    action,
                    "name",
                    "",
                )
            )

            if not name:
                continue

            if name not in self._counts:
                self._counts[name] = 0
                self._payloads[name] = []

            self._counts[name] += 1

            payload = str(
                getattr(
                    action,
                    "payload",
                    "",
                )
                or ""
            ).strip()

            if payload:
                self._payloads[name].append(
                    payload
                )

            if name not in changed_names:
                changed_names.append(
                    name
                )

        return tuple(
            self.get(name)
            for name in changed_names
        )

    def get(
        self,
        action_name: str,
    ) -> RuntimeActionCount | None:
        name = normalize_runtime_action_name(
            action_name
        )

        if name not in self._counts:
            return None

        return RuntimeActionCount(
            name=name,
            count=int(
                self._counts[name]
            ),
            payloads=tuple(
                self._payloads.get(
                    name,
                    (),
                )
            ),
        )

    def entries(self) -> tuple[RuntimeActionCount, ...]:
        return tuple(
            self.get(name)
            for name in self._counts
        )

    def marker_actions(
        self,
        *,
        display_payloads=None,
    ) -> list[dict]:
        resolved_display_payloads = (
            display_payloads
            if isinstance(
                display_payloads,
                dict,
            )
            else {}
        )
        marker_actions = []

        for entry in self.entries():
            if entry is None:
                continue

            payloads = resolved_display_payloads.get(
                entry.name,
                entry.payloads,
            )

            if isinstance(
                payloads,
                (str, bytes),
            ):
                payloads = [
                    payloads,
                ]
            elif not isinstance(
                payloads,
                (list, tuple),
            ):
                payloads = []

            normalized_payloads = [
                str(payload or "").strip()
                for payload in payloads
                if str(payload or "").strip()
            ]

            marker_action = {
                "name": entry.name,
                "marker_count": entry.count,
                "payloads": normalized_payloads,
            }

            if normalized_payloads:
                marker_action["payload"] = (
                    normalized_payloads[-1]
                )

            marker_actions.append(
                marker_action
            )

        return marker_actions


def format_runtime_action_count(
    text: str,
    count: int,
) -> str:
    normalized_text = str(
        text
        or ""
    ).strip()

    if not normalized_text:
        return ""

    try:
        normalized_count = max(
            0,
            int(
                count
                or 0
            ),
        )
    except (
        TypeError,
        ValueError,
    ):
        normalized_count = 0

    if normalized_count <= 1:
        return normalized_text

    return (
        f"{normalized_text} "
        f"(count: {normalized_count})"
    )


async def emit_runtime_action_counter_updates(
    context,
    entries,
    *,
    context_snapshot: dict | None = None,
    display_payloads=None,
    status: str = "counted",
    detail: str = "",
) -> None:
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

    if emit is None:
        return

    resolved_display_payloads = (
        display_payloads
        if isinstance(
            display_payloads,
            dict,
        )
        else {}
    )
    runtime_turn_id = str(
        getattr(
            context,
            "runtime_current_turn_id",
            "",
        )
        or ""
    ).strip()

    for entry in entries or ():
        if not isinstance(
            entry,
            RuntimeActionCount,
        ):
            continue

        payloads = resolved_display_payloads.get(
            entry.name,
            entry.payloads,
        )

        if isinstance(
            payloads,
            (str, bytes),
        ):
            payloads = [
                payloads,
            ]
        elif not isinstance(
            payloads,
            (list, tuple),
        ):
            payloads = []

        normalized_payloads = [
            str(payload or "").strip()
            for payload in payloads
            if str(payload or "").strip()
        ]
        payload = (
            normalized_payloads[-1]
            if normalized_payloads
            else entry.payload
        )
        display_name = get_runtime_action_display_name(
            entry.name
        )

        event = {
            "type": "runtime_action",
            "action": entry.name.lower(),
            "status": status,
            "display_name": display_name,
            "text": build_runtime_action_display_text(
                entry.name,
                payload,
            ),
            "close_tag": runtime_action_has_close_tag(
                entry.name
            ),
            "marker_count": entry.count,
            "counter_only": (
                status in {
                    "counted",
                    "counter_final",
                }
            ),
            "counter_final": (
                status == "counter_final"
            ),
            "aggregate_markers": True,
            "payloads": normalized_payloads,
        }

        if entry.name == "JIN_COLOR":
            event["colors"] = normalized_payloads

            if normalized_payloads:
                event["color"] = normalized_payloads[-1]

        if payload:
            event["payload"] = payload

        if runtime_turn_id:
            event["runtime_turn_id"] = (
                runtime_turn_id
            )
            event["counter_id"] = (
                f"{runtime_turn_id}:"
                f"{entry.name.lower()}"
            )

        normalized_detail = str(
            detail
            or ""
        ).strip()

        if normalized_detail:
            event["detail"] = normalized_detail

        if isinstance(
            context_snapshot,
            dict,
        ) and context_snapshot:
            event["context"] = dict(
                context_snapshot
            )

        await emit(
            event
        )
