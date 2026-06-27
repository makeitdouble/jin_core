import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

from utils.stream_validator import StreamValidator


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
