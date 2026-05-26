from dataclasses import dataclass

from contracts.context_contract import (
    DEEP_THOUGHT_ACTION,
)


@dataclass(frozen=True)
class RuntimeActionResult:
    text: str
    deep_thought_count: int = 0


def extract_runtime_actions(
    text: str,
) -> RuntimeActionResult:

    if not text:
        return RuntimeActionResult(
            text="",
            deep_thought_count=0,
        )

    call_count = text.count(
        DEEP_THOUGHT_ACTION
    )

    if not call_count:
        return RuntimeActionResult(
            text=text,
            deep_thought_count=0,
        )

    return RuntimeActionResult(
        text=text.replace(
            DEEP_THOUGHT_ACTION,
            "",
        ),
        deep_thought_count=call_count,
    )


def _trailing_marker_prefix_length(
    text: str,
) -> int:

    max_length = min(
        len(text),
        len(DEEP_THOUGHT_ACTION) - 1,
    )

    for length in range(
        max_length,
        0,
        -1,
    ):

        if text.endswith(
            DEEP_THOUGHT_ACTION[:length]
        ):
            return length

    return 0


class RuntimeActionStreamFilter:

    def __init__(self):
        self.pending = ""

    def filter(
        self,
        chunk: str,
    ) -> RuntimeActionResult:

        if not chunk:
            return RuntimeActionResult(
                text="",
                deep_thought_count=0,
            )

        combined = (
            self.pending
            + chunk
        )

        self.pending = ""

        result = extract_runtime_actions(
            combined
        )

        hold_length = (
            _trailing_marker_prefix_length(
                result.text
            )
        )

        if not hold_length:
            return result

        self.pending = result.text[
            -hold_length:
        ]

        return RuntimeActionResult(
            text=result.text[
                :-hold_length
            ],
            deep_thought_count=(
                result.deep_thought_count
            ),
        )

    def flush(self) -> str:

        pending = self.pending
        self.pending = ""

        return pending
