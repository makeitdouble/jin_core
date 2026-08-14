from collections import OrderedDict
from dataclasses import dataclass
import hashlib

from contracts.rules_assembler import (
    build_runtime_action_display_text,
    get_runtime_action_display_name,
    runtime_action_has_close_tag,
)

from .common_action_utils import (
    normalize_runtime_action_name,
)
from .jin_color_utils import (
    normalize_jin_color_payload,
)
from .jin_size_utils import (
    normalize_jin_size_payload,
)
@dataclass(frozen=True)
class RuntimeActionCount:
    name: str
    count: int
    payloads: tuple[str, ...] = ()
    identity: str = ""

    @property
    def payload(self) -> str:
        return (
            self.payloads[-1]
            if self.payloads
            else ""
        )


class RuntimeActionCounter:
    """Count identical parsed markers once, before execution dedupe."""

    _EXCLUDED_ACTIONS = frozenset({
        "LOAD_SKILL",
        "LOAD_SKILLS",
        "UNLOAD_SKILL",
        "UNLOAD_SKILLS",
        "DEEP_WEB_SEARCH",
    })

    def __init__(self):
        self._counts = OrderedDict()
        self._payloads = {}

    @staticmethod
    def _identity_key(
        name: str,
        payload: str,
    ) -> tuple[str, str]:

        # Visual JIN markers intentionally remain ordered aggregate sequences.
        if name in {
            "JIN_COLOR",
            "JIN_SIZE",
        }:
            return (
                name,
                "",
            )

        return (
            name,
            payload,
        )

    def record(self, actions) -> tuple[RuntimeActionCount, ...]:
        changed_keys = []

        for action in actions or ():
            name = normalize_runtime_action_name(
                getattr(
                    action,
                    "name",
                    "",
                )
            )

            if (
                not name
                or name in self._EXCLUDED_ACTIONS
            ):
                continue

            payload = str(
                getattr(
                    action,
                    "payload",
                    "",
                )
                or ""
            ).strip()
            identity_key = self._identity_key(
                name,
                payload,
            )

            if identity_key not in self._counts:
                self._counts[identity_key] = 0
                self._payloads[identity_key] = []

            self._counts[identity_key] += 1

            if payload:
                self._payloads[identity_key].append(
                    payload
                )

            if identity_key not in changed_keys:
                changed_keys.append(
                    identity_key
                )

        return tuple(
            self._get_by_key(identity_key)
            for identity_key in changed_keys
        )

    def _get_by_key(
        self,
        identity_key: tuple[str, str],
    ) -> RuntimeActionCount | None:

        if identity_key not in self._counts:
            return None

        name, identity = identity_key

        return RuntimeActionCount(
            name=name,
            count=int(
                self._counts[identity_key]
            ),
            payloads=tuple(
                self._payloads.get(
                    identity_key,
                    (),
                )
            ),
            identity=identity,
        )

    def get(
        self,
        action_name: str,
        payload: str | None = None,
    ) -> RuntimeActionCount | None:
        name = normalize_runtime_action_name(
            action_name
        )

        if payload is not None:
            return self._get_by_key(
                self._identity_key(
                    name,
                    str(
                        payload
                        or ""
                    ).strip(),
                )
            )

        matches = [
            identity_key
            for identity_key in self._counts
            if identity_key[0] == name
        ]

        if len(matches) != 1:
            return None

        return self._get_by_key(
            matches[0]
        )

    def entries(self) -> tuple[RuntimeActionCount, ...]:
        return tuple(
            self._get_by_key(identity_key)
            for identity_key in self._counts
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
                (
                    entry.name,
                    entry.identity,
                ),
                resolved_display_payloads.get(
                    entry.name,
                    entry.payloads,
                ),
            )

            normalized_payloads = normalize_runtime_action_counter_payloads(
                entry,
                payloads,
            )
            raw_payloads = normalize_runtime_action_counter_payloads(
                entry,
                entry.payloads,
            )

            marker_action = {
                "name": entry.name,
                "marker_count": entry.count,
                "payloads": normalized_payloads,
            }

            if raw_payloads:
                marker_action["raw_payloads"] = raw_payloads

            if normalized_payloads:
                marker_action["payload"] = (
                    normalized_payloads[-1]
                )

            marker_actions.append(
                marker_action
            )

        return marker_actions


def normalize_runtime_action_counter_payloads(
    entry: RuntimeActionCount,
    payloads,
) -> list[str]:

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

    if entry.name not in {
        "JIN_COLOR",
        "JIN_SIZE",
    }:
        return normalized_payloads

    normalizer = (
        normalize_jin_color_payload
        if entry.name == "JIN_COLOR"
        else normalize_jin_size_payload
    )
    visual_payloads = [
        normalizer(payload)
        for payload in (
            normalized_payloads
            or list(entry.payloads)
        )
    ]

    return [
        payload
        for payload in visual_payloads
        if payload
    ]


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
    runtime_message_id: str = "",
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
    resolved_runtime_message_id = str(
        runtime_message_id
        or ""
    ).strip()

    for entry in entries or ():
        if not isinstance(
            entry,
            RuntimeActionCount,
        ):
            continue

        payloads = resolved_display_payloads.get(
            (
                entry.name,
                entry.identity,
            ),
            resolved_display_payloads.get(
                entry.name,
                entry.payloads,
            ),
        )

        normalized_payloads = normalize_runtime_action_counter_payloads(
            entry,
            payloads,
        )
        raw_payloads = normalize_runtime_action_counter_payloads(
            entry,
            entry.payloads,
        )
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

        if raw_payloads:
            event["raw_payloads"] = raw_payloads

        if entry.name == "JIN_COLOR":
            event["colors"] = normalized_payloads

            if normalized_payloads:
                event["color"] = normalized_payloads[-1]

        if entry.name == "JIN_SIZE":
            event["sizes"] = normalized_payloads

            if normalized_payloads:
                event["size"] = normalized_payloads[-1]

        if payload:
            event["payload"] = payload

        if runtime_turn_id:
            event["runtime_turn_id"] = (
                runtime_turn_id
            )
            counter_identity = str(
                entry.identity
                or ""
            ).strip()
            counter_suffix = ""

            if counter_identity:
                counter_suffix = (
                    ":"
                    + hashlib.sha1(
                        counter_identity.encode(
                            "utf-8"
                        )
                    ).hexdigest()[:10]
                )

            event["counter_id"] = (
                f"{runtime_turn_id}:"
                f"{entry.name.lower()}"
                f"{counter_suffix}"
            )

        if resolved_runtime_message_id:
            event["runtime_message_id"] = (
                resolved_runtime_message_id
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
