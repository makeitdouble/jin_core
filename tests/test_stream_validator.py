import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

from utils.stream_validator import (
    MAX_REPEAT_SENTENCES,
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
        "`append_skill` first.\n"
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


def test_stream_validator_stops_repeated_sentence_sequence_with_markers():
    validator = StreamValidator()

    repeated_block = (
        "* *Actually*, I'll do:\n"
        "- `<CREATE_ACTIVE_MEMORY: Experiment timer>`\n"
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
        validator.last_failure_preview
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
