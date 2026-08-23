import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

import utils.stream_validator as stream_validator_module

from utils.stream_validator import (
    INCORRECT_L4_FACT_IDS_HALLUCINATION_REASON,
    MAX_REPEAT_SYMBOLIC_MOTIFS,
    MAX_REPEAT_SENTENCES,
    SAME_ANSWER_OUTPUT_REASON,
    StreamValidator,
)


def collect(validator, chunks):
    output = []

    for chunk in chunks:
        clean, is_valid = validator.filter_chunk(chunk)
        assert is_valid
        output.append(clean)

    output.append(
        validator.flush_trailing_artifact_candidate()
    )

    return "".join(output)


def test_stream_validator_same_answer_prefix_is_held_and_rejected():
    previous_output = (
        "This is a deliberately long visible answer that should be "
        "recognized when the next generation actually repeats it. "
    )
    validator = StreamValidator(
        previous_output=previous_output
    )

    prefix = validator.same_output_reference_prefix
    assert len(prefix) >= 64

    midpoint = len(prefix) // 2
    assert validator.filter_chunk(prefix[:midpoint]) == ("", True)
    assert validator.filter_chunk(prefix[midpoint:]) == ("", False)
    assert validator.last_failure_reason == SAME_ANSWER_OUTPUT_REASON


def test_stream_validator_same_answer_prefix_releases_on_first_mismatch():
    previous_output = (
        "Принято. Запускаю процесс финализации. Сейчас всё упакую, "
        "проведу аудит и сохраню текущее состояние сессии целиком."
    )
    validator = StreamValidator(
        previous_output=previous_output
    )

    # A follow-up can naturally reuse a short acknowledgement such as
    # "Принято. Запускаю...". That is not enough evidence of a loop.
    output = (
        "Принято. Запускаю итоговую проверку сохранения и сразу "
        "сообщу только оставшийся результат."
    )

    assert collect(validator, [output]) == output
    assert validator.last_failure_reason is None


def test_stream_validator_removes_trailing_blockquote_tag():
    validator = StreamValidator()

    text = collect(
        validator,
        [
            "Понял. ",
            "Буду проще.</blockquote>",
        ],
    )

    assert text == "Понял. Буду проще."
    assert validator.cleanup_events == [
        {
            "reason": "Trailing artifact removed.",
            "preview": "</blockquote>",
        }
    ]


def test_stream_validator_removes_split_trailing_blockquote_tag():
    validator = StreamValidator()

    text = collect(
        validator,
        [
            "Понял. ",
            "Буду проще.</bloc",
            "kquote>",
        ],
    )

    assert text == "Понял. Буду проще."


def test_stream_validator_allows_repeated_sentences_when_sentence_check_disabled():
    validator = StreamValidator()

    repeated = (
        "* Wait, I'll check if I should use "
        "`load_skill` first.\n"
    )

    for _ in range(3):
        assert validator.filter_chunk(repeated) == (
            repeated,
            True,
        )

    assert validator.last_failure_reason is None
    assert validator.last_failure_preview == ""


def test_stream_validator_allows_non_consecutive_repeated_sentences():
    validator = StreamValidator()

    repeated = (
        "The rain sound is actually a form of pink noise.\n"
    )
    separator = (
        "That context makes the response feel more continuous.\n"
    )

    text = collect(
        validator,
        [
            repeated,
            separator,
            repeated,
            separator,
            repeated,
        ],
    )

    assert text == (
        repeated
        + separator
        + repeated
        + separator
        + repeated
    )
    assert validator.last_failure_reason is None


def test_stream_validator_stops_recurrent_sentence_inside_mixed_loop():
    validator = StreamValidator()

    anchor = "Actually, I'll just do the task.\n"
    mixed_blocks = [
        (
            "Wait, I'll do this:\n"
            '"I used the wrong tag, so the tool never ran."\n'
            "Then the task.\n"
        ),
        (
            "Let's try to be very precise.\n"
            "1. Acknowledge the error.\n"
            "2. Perform the task.\n"
        ),
    ]

    for repeat_index in range(
        MAX_REPEAT_SENTENCES
    ):
        chunk = (
            anchor
            + mixed_blocks[
                repeat_index % len(mixed_blocks)
            ]
        )

        clean, is_valid = validator.filter_chunk(
            chunk
        )

        if repeat_index < MAX_REPEAT_SENTENCES - 1:
            assert clean == chunk
            assert is_valid
            continue

        assert clean == ""
        assert not is_valid

    assert validator.last_failure_reason == (
        "Repeated sentence loop detected."
    )
    assert validator.last_failure_preview.startswith(
        "Actually, I'll just do the task."
    )
    assert validator.last_failure_loop_preview == (
        "Actually, I'll just do the task."
    )


def test_stream_validator_sentence_repeat_threshold_can_be_raised(monkeypatch):
    threshold = 7

    monkeypatch.setattr(
        stream_validator_module,
        "MAX_REPEAT_SENTENCES",
        threshold,
    )

    validator = StreamValidator()
    repeated = "Actually, I'll just do the task.\n"

    for repeat_index in range(threshold):
        clean, is_valid = validator.filter_chunk(
            repeated
        )

        if repeat_index < threshold - 1:
            assert clean == repeated
            assert is_valid
            continue

        assert clean == ""
        assert not is_valid


def test_stream_validator_sentence_repeat_threshold_zero_disables_check(monkeypatch):
    monkeypatch.setattr(
        stream_validator_module,
        "MAX_REPEAT_SENTENCES",
        0,
    )

    validator = StreamValidator()
    repeated = "Actually, I'll just do the task.\n"

    text = collect(
        validator,
        [
            repeated
            for _ in range(10)
        ],
    )

    assert text == repeated * 10
    assert validator.last_failure_reason is None


def test_stream_validator_stops_repeated_sentence_sequence_with_markers():
    validator = StreamValidator()

    repeated_block = (
        "* *Actually*, I'll do:\n"
        "- `<SAVE_ACTIVE_MEMORY> Experiment timer </SAVE_ACTIVE_MEMORY>`\n"
        "- `<WEB_SEARCH: fusion energy>`\n"
        "\n"
        "* *Wait*, I'll just do the search.\n"
        "\n"
    )

    for repeat_index in range(
        MAX_REPEAT_SENTENCES
    ):
        clean, is_valid = validator.filter_chunk(
            repeated_block
        )

        if repeat_index < MAX_REPEAT_SENTENCES - 1:
            assert clean == repeated_block
            assert is_valid
            continue

        assert clean == ""
        assert not is_valid

    assert validator.last_failure_reason == (
        "Repeated sentence loop detected."
    )
    assert validator.last_failure_preview == (
        "* *Actually*, I'll do:\\n"
        "* *Wait*, I'll just do the search."
    )
    assert validator.last_failure_loop_preview == (
        "* *Wait*, I'll just do the search."
    )


def test_stream_validator_keeps_single_word_loop_instance_for_history():
    validator = StreamValidator()

    clean, is_valid = validator.filter_chunk(
        "wait " * 8
    )

    assert clean == ""
    assert not is_valid
    assert validator.last_failure_preview == (
        "wait wait wait wait wait wait wait wait"
    )
    assert validator.last_failure_loop_preview == "wait"


def test_stream_validator_stops_repeated_short_word_sequence():
    validator = StreamValidator()

    clean, is_valid = validator.filter_chunk(
        '"запиши" or ' * 6
    )

    assert clean == ""
    assert not is_valid
    assert validator.last_failure_reason == (
        "Repeated word sequence loop detected."
    )
    assert validator.last_failure_loop_preview == "запиши or"


def test_stream_validator_stops_repeated_complex_symbolic_motif_in_mixed_reasoning():
    validator = StreamValidator()

    blocks = [
        "Wait, I'll do:\n```\n  (😼) ⚡\n```\nLet's go.\n",
        "*Final decision:*\n```\n  (😼) ⚡\n```\nActually, I'll do it.\n",
        "Let's inspect one more thing.\n```\n  (😼) ⚡\n```\nThen continue.\n",
        "*Actually, I'll do:*\n```\n  (😼) ⚡\n```\nLet's go.\n",
    ]

    assert len(blocks) == MAX_REPEAT_SYMBOLIC_MOTIFS

    for repeat_index, block in enumerate(blocks):
        clean, is_valid = validator.filter_chunk(
            block
        )

        if repeat_index < MAX_REPEAT_SYMBOLIC_MOTIFS - 1:
            assert clean == block
            assert is_valid
            continue

        assert clean == ""
        assert not is_valid

    assert validator.last_failure_reason == (
        "Repeated symbolic motif loop detected."
    )
    assert validator.last_failure_loop_preview == "(😼) ⚡"


def test_stream_validator_allows_repeated_ascii_art_rows():
    validator = StreamValidator()
    line = "| | | | | | | |\n"

    text = collect(
        validator,
        [
            line
            for _ in range(
                MAX_REPEAT_SYMBOLIC_MOTIFS + 4
            )
        ],
    )

    assert text == line * (
        MAX_REPEAT_SYMBOLIC_MOTIFS + 4
    )
    assert validator.last_failure_reason is None
    assert validator.last_failure_loop_preview == ""


def test_stream_validator_allows_bare_two_emoji_lines_even_when_repeated():
    validator = StreamValidator()
    line = "😂 ⚡\n"

    text = collect(
        validator,
        [
            line
            for _ in range(
                MAX_REPEAT_SYMBOLIC_MOTIFS + 4
            )
        ],
    )

    assert text == line * (
        MAX_REPEAT_SYMBOLIC_MOTIFS + 4
    )
    assert validator.last_failure_reason is None


def test_stream_validator_symbolic_motif_survives_provider_chunk_splits():
    validator = StreamValidator()

    for repeat_index in range(
        MAX_REPEAT_SYMBOLIC_MOTIFS
    ):
        clean, is_valid = validator.filter_chunk(
            "```\n  (😼"
        )
        assert clean == "```\n  (😼"
        assert is_valid

        clean, is_valid = validator.filter_chunk(
            ") ⚡\n```\n"
        )

        if repeat_index < MAX_REPEAT_SYMBOLIC_MOTIFS - 1:
            assert clean == ") ⚡\n```\n"
            assert is_valid
            continue

        assert clean == ""
        assert not is_valid

    assert validator.last_failure_reason == (
        "Repeated symbolic motif loop detected."
    )


def test_stream_validator_allows_repeated_numeric_stream_fragments():
    validator = StreamValidator()

    for chunk in ["0"] * 12:
        clean, is_valid = validator.filter_chunk(chunk)

        assert clean == chunk
        assert is_valid

    assert validator.last_failure_reason is None
    assert validator.last_failure_preview == ""
    assert validator.last_failure_loop_preview == ""


def test_stream_validator_does_not_split_fact_ids_at_provider_chunk_edges():
    validator = StreamValidator()

    chunks = ["Cluster B contains: "]
    for fact_id in range(5, 13):
        chunks.extend(["F", f"{fact_id}, "])

    for chunk in chunks:
        clean, is_valid = validator.filter_chunk(chunk)

        assert clean == chunk
        assert is_valid

    assert validator.last_failure_reason is None
    assert validator.last_failure_preview == ""
    assert validator.last_failure_loop_preview == ""


def test_stream_validator_stops_after_five_consecutive_nonexistent_l4_fact_ids():
    validator = StreamValidator(
        valid_l4_fact_ids={
            "F1",
            "F190",
        }
    )

    for index, fact_id in enumerate(
        [
            "F257",
            "F258",
            "F259",
            "F260",
            "F261",
        ]
    ):
        is_valid = validator.validate_repetitions(
            f"* {fact_id}: fabricated fact description.\n"
        )

        if index < 4:
            assert is_valid
            continue

        assert not is_valid

    assert validator.last_failure_reason == (
        INCORRECT_L4_FACT_IDS_HALLUCINATION_REASON
    )
    assert validator.last_failure_loop_preview == (
        "F257, F258, F259, F260, F261"
    )


def test_stream_validator_l4_fact_id_guard_handles_provider_chunk_splits():
    validator = StreamValidator(
        valid_l4_fact_ids={
            "F1",
        }
    )

    chunks = []
    for fact_id in range(257, 262):
        chunks.extend([
            "* F",
            f"{fact_id}: fabricated.\n",
        ])

    for index, chunk in enumerate(chunks):
        is_valid = validator.validate_repetitions(
            chunk
        )

        if index < len(chunks) - 1:
            assert is_valid
            continue

        assert not is_valid

    assert validator.last_failure_loop_preview == (
        "F257, F258, F259, F260, F261"
    )


def test_stream_validator_existing_l4_fact_resets_invalid_id_streak():
    validator = StreamValidator(
        valid_l4_fact_ids={
            "F190",
        }
    )

    for fact_id in [
        "F257",
        "F258",
        "F190",
        "F259",
        "F260",
        "F261",
        "F262",
    ]:
        assert validator.validate_repetitions(
            f"{fact_id}: item.\n"
        )

    assert not validator.validate_repetitions(
        "F263: item.\n"
    )
    assert validator.last_failure_loop_preview == (
        "F259, F260, F261, F262, F263"
    )


def test_stream_validator_l4_fact_id_guard_is_disabled_without_initialized_store():
    validator = StreamValidator()

    for fact_id in range(257, 267):
        assert validator.validate_repetitions(
            f"F{fact_id}: unknown because store is unavailable.\n"
        )

    assert validator.last_failure_reason is None


def test_stream_validator_still_catches_words_split_from_whitespace_chunks():
    validator = StreamValidator()

    for repeat_index in range(8):
        clean, is_valid = validator.filter_chunk("wait")
        assert clean == "wait"
        assert is_valid

        clean, is_valid = validator.filter_chunk(" ")

        if repeat_index < 7:
            assert clean == " "
            assert is_valid
            continue

        assert clean == ""
        assert not is_valid

    assert validator.last_failure_reason == (
        "Repeated word loop detected."
    )
    assert validator.last_failure_loop_preview == "wait"


def test_stream_validator_allows_short_repeated_sentences():
    validator = StreamValidator()

    text = collect(
        validator,
        [
            "Yes. ",
            "Yes. ",
            "Yes. ",
        ],
    )

    assert text == "Yes. Yes. Yes. "


def test_stream_validator_flushes_unfinished_tag_as_content():
    validator = StreamValidator()

    text = collect(
        validator,
        [
            "Сравнение: ",
            "2 <",
        ],
    )

    assert text == "Сравнение: 2 <"



def test_stream_validator_stops_reasoning_loop_with_changing_quoted_checks():
    validator = StreamValidator()

    prompt_checks = [
        "I must avoid appending default assistant questions.",
        "I do not automatically agree or turn everything into a lecture.",
        "I must skip redundant drafts and trial loops.",
        "I prefer to keep my presence unobtrusive.",
        "I respect the consistency and reliability of my context.",
    ]

    for repeat_index, prompt_check in enumerate(
        prompt_checks
    ):
        block = (
            f'*Final check of the prompt: "{prompt_check}"*\n\n'
            "*The response is good.*\n\n"
        )

        is_valid = True

        for chunk in (
            block[:19],
            block[19:53],
            block[53:],
        ):
            is_valid = validator.validate_repetitions(
                chunk
            )

            if not is_valid:
                break

        if repeat_index < len(prompt_checks) - 1:
            assert is_valid
            continue

        assert not is_valid

    assert validator.last_failure_reason == (
        "Repeated sentence loop detected."
    )
    assert validator.last_failure_preview == (
        '*Final check of the prompt: "I respect the consistency '
        'and reliability of my context.*The response is good.'
    )


def test_stream_validator_allows_single_changing_quoted_template_list():
    validator = StreamValidator()

    for item in [
        "alpha",
        "beta",
        "gamma",
        "delta",
        "epsilon",
        "zeta",
    ]:
        assert validator.validate_repetitions(
            f'*Check item: "{item}".\n'
        )

    assert validator.last_failure_reason is None
