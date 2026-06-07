"""Prompt rule blocks for JIN.

Allows clean imports:
    from rules import IDENTITY, REQUEST_RULES, build_system_prompt
"""

from .assembler import LAST_JIN_RESPONSE_RULES, build_system_prompt, prompt_stats
from .core_identity import IDENTITY
from .loop_rules import LOOP_RULES
from .memory_rules import MEMORY_RULES
from .philosophy_mode import PHILOSOPHY_MODE
from .request_rules import REQUEST_RULES
from .runtime_actions import AUTONOMY_RULES, RUNTIME_ACTIONS
from .vision_rules import IMAGE_INPUT_RULES

__all__ = [
    "AUTONOMY_RULES",
    "IDENTITY",
    "IMAGE_INPUT_RULES",
    "LAST_JIN_RESPONSE_RULES",
    "LOOP_RULES",
    "MEMORY_RULES",
    "PHILOSOPHY_MODE",
    "REQUEST_RULES",
    "RUNTIME_ACTIONS",
    "build_system_prompt",
    "prompt_stats",
]
