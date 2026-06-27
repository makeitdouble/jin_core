"""Prompt rule blocks for JIN.

Allows clean imports:
    from rules import IDENTITY, REQUEST_RULES, build_system_prompt
"""

from .assembler import (
    BRAIN_RUNTIME_ACTIONS,
    SERVICE_AS_BRAIN_RUNTIME_ACTIONS,
    build_system_prompt,
    prompt_stats,
)
from .identity import IDENTITY
from .loop_rules import LOOP_RULES

__all__ = [
    "BRAIN_RUNTIME_ACTIONS",
    "IDENTITY",
    "LOOP_RULES",
    "SERVICE_AS_BRAIN_RUNTIME_ACTIONS",
    "build_system_prompt",
    "prompt_stats",
]
