# ─────────────────────────────────────────────
#  JIN PROMPT ASSEMBLER
#  Shows which blocks load and when.
# ─────────────────────────────────────────────

from .core_identity    import IDENTITY
from .runtime_actions  import RUNTIME_ACTIONS, AUTONOMY_RULES
from .request_rules    import REQUEST_RULES
from .memory_rules     import MEMORY_RULES       # load if: memory_request detected
from .loop_rules       import LOOP_RULES         # load if: pattern_counter > 0
from .vision_rules     import IMAGE_INPUT_RULES  # load if: image/file in payload
from .philosophy_mode  import PHILOSOPHY_MODE    # load if: philosophy_mode active


# ── Always loaded ─────────────────────────────
LAST_JIN_RESPONSE_RULES = (
    "Use last_jin_response from trusted runtime memory as the primary anchor "
    "for short, elliptical feedback about JIN's immediately previous output.\n"
    "For brief negative feedback, do not ask what exactly is wrong by default; "
    "answer by challenging yourself and changing the previous output into a "
    "concrete alternative, preferably from an unexpected angle.\n"
)

def build_system_prompt(
    has_memory_request: bool = False,
    pattern_counter: int = 0,
    has_media: bool = False,
    philosophy_active: bool = False,
) -> str:

    blocks = [
        LAST_JIN_RESPONSE_RULES,
        IDENTITY,
        RUNTIME_ACTIONS,
        AUTONOMY_RULES,
        REQUEST_RULES,
    ]

    if has_memory_request:
        blocks.append(MEMORY_RULES)

    if pattern_counter > 0:
        blocks.append(LOOP_RULES)

    if has_media:
        blocks.append(IMAGE_INPUT_RULES)

    if philosophy_active:
        blocks.append(PHILOSOPHY_MODE)

    return "\n".join(blocks)


def prompt_stats(
    has_memory_request: bool = False,
    pattern_counter: int = 0,
    has_media: bool = False,
    philosophy_active: bool = False,
) -> dict:
    """Return char/token estimates for the assembled prompt under given flags."""
    prompt = build_system_prompt(
        has_memory_request=has_memory_request,
        pattern_counter=pattern_counter,
        has_media=has_media,
        philosophy_active=philosophy_active,
    )
    chars = len(prompt)
    tokens_approx = chars // 4  # rough GPT-family estimate
    return {"chars": chars, "tokens_approx": tokens_approx}


if __name__ == "__main__":
    baseline = prompt_stats()
    worst    = prompt_stats(has_memory_request=True, pattern_counter=1, has_media=True, philosophy_active=True)
    print(f"Baseline (always):  {baseline['chars']} chars / ~{baseline['tokens_approx']} tokens")
    print(f"Worst case (all):   {worst['chars']} chars / ~{worst['tokens_approx']} tokens")
