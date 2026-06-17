# ─────────────────────────────────────────────
#  JIN PROMPT ASSEMBLER
#  Shows which blocks load and when.
# ─────────────────────────────────────────────

from .identity    import IDENTITY
from .runtime  import RUNTIME_ACTIONS
from .loop_rules       import LOOP_RULES         # load if: pattern_counter > 1

def build_system_prompt(
    has_memory_request: bool = False,
    pattern_counter: int = 0,
) -> str:

    blocks = [
        IDENTITY,
        RUNTIME_ACTIONS,
    ]

    if pattern_counter > 1:
        blocks.append(LOOP_RULES)

    return "\n".join(blocks)


def prompt_stats(
    pattern_counter: int = 0,
) -> dict:
    """Return char/token estimates for the assembled prompt under given flags."""
    prompt = build_system_prompt(
        pattern_counter=pattern_counter,
    )
    chars = len(prompt)
    tokens_approx = chars // 4  # rough GPT-family estimate
    return {"chars": chars, "tokens_approx": tokens_approx}


if __name__ == "__main__":
    baseline = prompt_stats()
    worst    = prompt_stats(pattern_counter=1)
    print(f"Baseline (always):  {baseline['chars']} chars / ~{baseline['tokens_approx']} tokens")
    print(f"Worst case (all):   {worst['chars']} chars / ~{worst['tokens_approx']} tokens")
