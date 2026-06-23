"""Prompt rule blocks for JIN.

Allows clean imports:
    from rules import IDENTITY, REQUEST_RULES, build_system_prompt
"""

from .assembler import build_system_prompt, prompt_stats
from .identity import IDENTITY
from .loop_rules import LOOP_RULES

__all__ = [
    "IDENTITY",
    "LOOP_RULES",
    "build_system_prompt",
    "prompt_stats",
]
