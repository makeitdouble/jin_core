"""Prompt rule blocks for JIN.

Allows clean imports:
    from rules import IDENTITY, REQUEST_RULES, build_brain_context
"""

from .identity import IDENTITY
from .signal import LOOP_RULES

__all__ = [
    "IDENTITY",
    "LOOP_RULES",
]


def __getattr__(name):
    if name in {
        "BRAIN_RUNTIME_ACTIONS",
        "build_brain_context",
    }:
        from .brain_context_builder import (
            BRAIN_RUNTIME_ACTIONS,
            build_brain_context,
        )

        exports = {
            "BRAIN_RUNTIME_ACTIONS": BRAIN_RUNTIME_ACTIONS,
            "build_brain_context": build_brain_context,
        }

        return exports[name]

    raise AttributeError(
        f"module {__name__!r} has no attribute {name!r}"
    )

