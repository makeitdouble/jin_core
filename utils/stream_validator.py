from contracts.rules_assembler import (
    get_stream_validator_excluded_markers,
)
from config_loader import config

import re
import unicodedata

# ---------------------------------------------------------
# STREAM VALIDATOR
# ---------------------------------------------------------
#
# Runtime stream validator for:
# - repeated word loops
# - repeated sentences
# - repeated paragraphs
# - provider artifact cleanup
#
# ---------------------------------------------------------

# ---------------------------------------------------------
# HTML TAG SANITIZATION
# ---------------------------------------------------------

HTML_TAGS = [
    "textarea",
    "div",
    "span",
    "p",
    "pre",
    "code",
    "html",
    "body",
    "head",
]

TRAILING_ARTIFACTS = [
    "</blockquote>",
]

# ---------------------------------------------------------
# VALIDATION THRESHOLDS
# ---------------------------------------------------------

def configured_int(
    name: str,
    default: int,
    *,
    minimum: int = 1,
    zero_disables: bool = False,
) -> int:

    try:
        value = int(
            getattr(
                config,
                name,
                default,
            )
        )
    except (TypeError, ValueError):
        value = default

    if zero_disables and value <= 0:
        return 0

    return max(
        minimum,
        value,
    )


WORD_WINDOW_SIZE = configured_int(
    "STREAM_VALIDATOR_WORD_WINDOW_SIZE",
    30,
)
MAX_REPEAT_WORDS = configured_int(
    "STREAM_VALIDATOR_MAX_REPEAT_WORDS",
    8,
    minimum=2,
    zero_disables=True,
)
MAX_REPEAT_WORD_SEQUENCE_SIZE = configured_int(
    "STREAM_VALIDATOR_MAX_REPEAT_WORD_SEQUENCE_SIZE",
    6,
    minimum=2,
    zero_disables=True,
)
MAX_REPEAT_WORD_SEQUENCE_REPETITIONS = configured_int(
    "STREAM_VALIDATOR_MAX_REPEAT_WORD_SEQUENCE_REPETITIONS",
    6,
    minimum=2,
    zero_disables=True,
)
MAX_REPEAT_SENTENCES = configured_int(
    "STREAM_VALIDATOR_MAX_REPEAT_SENTENCES",
    5,
    minimum=2,
    zero_disables=True,
)
MAX_REPEAT_SYMBOLIC_MOTIFS = configured_int(
    "STREAM_VALIDATOR_MAX_REPEAT_SYMBOLIC_MOTIFS",
    8,
    minimum=3,
    zero_disables=True,
)
SYMBOLIC_MOTIF_HISTORY_LINES = configured_int(
    "STREAM_VALIDATOR_SYMBOLIC_MOTIF_HISTORY_LINES",
    48,
    minimum=8,
)
# Inline symbol degeneration is deliberately conservative. A finite geometric
# drawing may repeat the same visual pattern for several rows, so line breaks
# are hard boundaries here. Only a long low-period run inside one physical line
# counts as strong evidence of a loop.
INLINE_SYMBOLIC_LOOP_MIN_CHARS = 96
INLINE_SYMBOLIC_LOOP_MAX_MOTIF_SIZE = 16
INLINE_SYMBOLIC_LOOP_MIN_REPETITIONS = 8
# Same short mixed-symbol ASCII row repeated for many physical lines is also
# a runaway shape. Keep the threshold high so ordinary finite ASCII art is not
# treated as a loop. Single-symbol rows (bars, box sides, etc.) are exempt.
ASCII_REPEAT_LOOP_MIN_LINES = 24
ASCII_REPEAT_LOOP_MIN_VISIBLE_CHARS = 3
# Same symbol-only ASCII row drifting one column per newline is a distinct
# runaway shape. Keep this deliberately high so finite diagonals stay valid.
ASCII_DRIFT_LOOP_MIN_LINES = 24
ASCII_DRIFT_LOOP_MIN_BODY_WIDTH = 12
MAX_SENTENCE_LOOP_SEQUENCE_SIZE = configured_int(
    "STREAM_VALIDATOR_MAX_SENTENCE_LOOP_SEQUENCE_SIZE",
    16,
)
MAX_RECURRENT_SENTENCE_HISTORY_SIZE = (
    MAX_SENTENCE_LOOP_SEQUENCE_SIZE
    * max(
        1,
        MAX_REPEAT_SENTENCES,
    )
)
MIN_RECURRENT_SENTENCE_WORDS = configured_int(
    "STREAM_VALIDATOR_MIN_RECURRENT_SENTENCE_WORDS",
    5,
)
MIN_RECURRENT_SENTENCE_ALNUM = configured_int(
    "STREAM_VALIDATOR_MIN_RECURRENT_SENTENCE_ALNUM",
    20,
)
SENTENCE_HISTORY_SIZE = (
    MAX_SENTENCE_LOOP_SEQUENCE_SIZE
    + 1
)
TRUNCATE = 160
SAME_ANSWER_OUTPUT_MIN_PREFIX_LENGTH = 64
SAME_ANSWER_OUTPUT_MAX_PREFIX_LENGTH = 160
SAME_ANSWER_OUTPUT_PREFIX_FRACTION = 0.5
SAME_ANSWER_OUTPUT_REASON = "same answer output"

STREAM_VALIDATOR_EXCLUDED_MARKERS = list(
    get_stream_validator_excluded_markers()
)


def extract_marker_name(
        marker: str,
) -> str:

    marker = str(marker or "")

    if not marker.startswith("<"):
        return ""

    offset = 2 if marker.startswith("</") else 1
    chars = []

    for char in marker[offset:]:
        if char.isalnum() or char == "_":
            chars.append(char)
            continue

        break

    return "".join(chars)


EXCLUDED_MARKER_NAMES = frozenset(
    marker_name
    for marker_name in (
        extract_marker_name(marker)
        for marker in STREAM_VALIDATOR_EXCLUDED_MARKERS
    )
    if marker_name
)

EXCLUDED_BLOCK_MARKER_NAMES = frozenset(
    extract_marker_name(marker)
    for marker in STREAM_VALIDATOR_EXCLUDED_MARKERS
    if str(marker or "").lstrip().startswith("</")
)

EXCLUDED_MARKER_STARTS = tuple(
    marker_start
    for marker_name in EXCLUDED_MARKER_NAMES
    for marker_start in (
        f"<{marker_name}",
        f"</{marker_name}",
    )
)

def build_preview(
        text: str,
) -> str:

    return (
        text
        .replace("\n", "\\n")
        .strip()
    )[:TRUNCATE]

def build_loop_preview(
        text: str,
) -> str:

    return (
        str(text or "")
        .replace("\n", "\\n")
        .strip()
    )

class StreamValidator:

    def __init__(
        self,
        *,
        previous_output: str = "",
    ):

        self.current_sentence_parts = []
        self.sentence_history = []
        self.recurrent_sentence_history = []
        self.sentence_period_match_counts = [
            0
        ] * (
            MAX_SENTENCE_LOOP_SEQUENCE_SIZE
            + 1
        )

        self.history_paragraphs = set()

        self.recent_words = []
        # A provider chunk boundary is not a word boundary. Keep the
        # unfinished trailing token so streamed identifiers such as
        # ``F`` + ``5,`` are validated as ``F5`` instead of eight fake
        # repeated ``F`` words.
        self.word_fragment = ""
        # Symbol-only reasoning loops are invisible to the lexical guards.
        # Keep a physical-line window so a recurring visual motif such as
        # ``(😼) ⚡`` is still detectable when prose and code fences are
        # interleaved between occurrences.
        self.symbolic_line_fragment = ""
        self.symbolic_line_index = 0
        self.symbolic_motif_history = []
        self.ascii_repeat_history = []
        self.ascii_drift_history = []
        self.validation_marker_buffer = ""
        self.validation_excluded_block_name = ""

        previous_output = str(previous_output or "")
        same_output_compare_length = min(
            SAME_ANSWER_OUTPUT_MAX_PREFIX_LENGTH,
            max(
                SAME_ANSWER_OUTPUT_MIN_PREFIX_LENGTH,
                int(
                    len(previous_output)
                    * SAME_ANSWER_OUTPUT_PREFIX_FRACTION
                ),
            ),
        )
        self.same_output_reference_prefix = (
            previous_output[:same_output_compare_length]
            if len(previous_output) >= SAME_ANSWER_OUTPUT_MIN_PREFIX_LENGTH
            else ""
        )
        self.same_output_prefix_buffer = ""

        self.last_failure_reason: str | None = None
        self.last_failure_preview = ""
        self.last_failure_loop_preview = ""

        self.stream_started = False
        self.failure_emitted = False
        self.leading_buffer = ""

        # -------------------------------------------------
        # HTML CLEANUP
        # -------------------------------------------------

        self.leading_cleanup_done = False

        self.leading_tag_buffer = ""

        self.leading_tags_removed = False

        self.cleanup_events = []

        # -------------------------------------------------
        # TRAILING CLEANUP
        # -------------------------------------------------

        self.trailing_artifact_buffer = ""

    # -----------------------------------------------------
    # REMOVE LEADING ARTIFACT
    # -----------------------------------------------------

    def remove_leading_artifact(
        self,
        chunk: str,
        artifacts: list[str],
    ):
        if self.stream_started:
            return chunk

        self.leading_buffer += chunk

        normalized = (
            "".join(
                self.leading_buffer
                .lower()
                .split()
            )
        )

        normalized_artifacts = [
            "".join(
                artifact
                .strip()
                .lower()
                .split()
            )
            for artifact in artifacts
        ]

        for artifact in normalized_artifacts:

            if normalized.startswith(artifact):

                artifact_length = len(artifact)

                removed = self.leading_buffer[:artifact_length]

                remaining = self.leading_buffer[artifact_length:]

                self.last_failure_reason = (
                    "Leading artifact removed."
                )

                self.last_failure_preview = removed

                return remaining

        for artifact in normalized_artifacts:

            if artifact.startswith(normalized):
                return None

        self.stream_started = True

        clean = self.leading_buffer

        self.leading_buffer = ""

        return clean

    # -----------------------------------------------------
    # SANITIZE ARTIFACTS
    # -----------------------------------------------------

    def sanitize_artifacts(
        self,
        chunk: str,
    ):
        # -------------------------------------------------
        # SANITIZER DISABLED
        # -------------------------------------------------

        if self.leading_cleanup_done:
            return chunk

        self.leading_tag_buffer += chunk

        while True:

            working = self.leading_tag_buffer

            if not working:
                return None

            stripped = working.lstrip()

            left_spaces = len(working) - len(stripped)

            if not stripped:
                return None

            # -------------------------------------------------
            # REAL CONTENT STARTED
            # -------------------------------------------------

            if not stripped.startswith("<"):

                self.leading_cleanup_done = True

                result = working

                self.leading_tag_buffer = ""

                return result

            # -------------------------------------------------
            # TAG TYPE
            # -------------------------------------------------

            is_closing = stripped.startswith("</")

            tag_offset = 2 if is_closing else 1

            # -------------------------------------------------
            # EXTRACT ASCII TAG NAME
            # -------------------------------------------------

            chars = []

            for char in stripped[tag_offset:]:

                lower = char.lower()

                if (
                    "a" <= lower <= "z"
                    or "0" <= char <= "9"
                ):
                    chars.append(lower)
                    continue

                break

            candidate = "".join(chars)

            # -------------------------------------------------
            # "<" OR "</"
            # -------------------------------------------------

            if candidate == "":

                # Broken non-ASCII text after "<".
                if len(stripped) > tag_offset:

                    self.leading_cleanup_done = True

                    result = working

                    self.leading_tag_buffer = ""

                    return result

                return None

            # -------------------------------------------------
            # MATCH HTML TAG PREFIX
            # -------------------------------------------------

            matching_tags = [
                tag
                for tag in HTML_TAGS
                if tag.startswith(candidate)
            ]

            # -------------------------------------------------
            # NOT TAG
            # -------------------------------------------------

            if not matching_tags:

                self.leading_cleanup_done = True

                result = working

                self.leading_tag_buffer = ""

                return result

            # -------------------------------------------------
            # NEXT CHAR
            # -------------------------------------------------

            next_index = tag_offset + len(candidate)

            next_char = ""

            if len(stripped) > next_index:
                next_char = stripped[next_index]

            is_full_tag = candidate in HTML_TAGS

            # -------------------------------------------------
            # PARTIAL TAG
            # -------------------------------------------------

            if not is_full_tag:

                # Broken non-ASCII text after a partial tag name.
                if next_char:

                    remove_len = (
                        left_spaces
                        + tag_offset
                        + len(candidate)
                    )

                    removed = working[:remove_len]

                    self.cleanup_events.append({
                        "reason": "Broken HTML tag removed.",
                        "preview": removed,
                    })

                    self.leading_tag_buffer = working[remove_len:]

                    continue

                return None

            # -------------------------------------------------
            # BROKEN FULL TAG
            # -------------------------------------------------

            # Broken non-ASCII text after a full tag name.
            if (
                next_char
                and next_char not in [
                    ">",
                    "/",
                    " ",
                    "\t",
                    "\r",
                    "\n",
                ]
            ):

                remove_len = (
                    left_spaces
                    + tag_offset
                    + len(candidate)
                )

                removed = working[:remove_len]

                self.cleanup_events.append({
                    "reason": "Broken HTML tag removed.",
                    "preview": removed,
                })

                self.leading_tag_buffer = working[remove_len:]

                continue

            # -------------------------------------------------
            # WAIT FOR FULL TAG
            # -------------------------------------------------

            close_index = stripped.find(
                ">",
                next_index,
            )

            if close_index == -1:
                return None

            # -------------------------------------------------
            # REMOVE CURRENT TAG
            # -------------------------------------------------

            remove_len = left_spaces + close_index + 1

            removed = working[:remove_len]

            self.cleanup_events.append({
                "reason": "HTML tag removed.",
                "preview": removed,
            })

            self.leading_tag_buffer = working[remove_len:]

            self.leading_tags_removed = True

    # -----------------------------------------------------
    # TRAILING ARTIFACT CLEANUP
    # -----------------------------------------------------

    def get_trailing_artifact_candidate_length(
        self,
        text: str,
    ) -> int:

        best_length = 0

        for artifact in TRAILING_ARTIFACTS:

            max_length = min(
                len(artifact),
                len(text),
            )

            for length in range(
                1,
                max_length + 1,
            ):

                if text.endswith(
                    artifact[:length]
                ):
                    best_length = max(
                        best_length,
                        length,
                    )

        return best_length

    def hold_trailing_artifact_candidate(
        self,
        chunk: str,
    ) -> str:

        if not TRAILING_ARTIFACTS:
            return chunk

        working = (
            self.trailing_artifact_buffer
            + chunk
        )

        candidate_length = (
            self.get_trailing_artifact_candidate_length(
                working
            )
        )

        if not candidate_length:

            self.trailing_artifact_buffer = ""

            return working

        safe_chunk = working[:-candidate_length]

        self.trailing_artifact_buffer = (
            working[-candidate_length:]
        )

        return safe_chunk

    def flush_trailing_artifact_candidate(
        self,
    ) -> str:

        prefix = ""

        if self.same_output_reference_prefix:
            prefix = self.same_output_prefix_buffer
            self.same_output_prefix_buffer = ""
            self.same_output_reference_prefix = ""

            if prefix:
                prefix = self.hold_trailing_artifact_candidate(
                    prefix
                )

        tail = self.trailing_artifact_buffer

        self.trailing_artifact_buffer = ""

        if not tail:
            return prefix

        if tail in TRAILING_ARTIFACTS:

            self.cleanup_events.append({
                "reason": "Trailing artifact removed.",
                "preview": tail,
            })

            return prefix

        return prefix + tail

    # -----------------------------------------------------
    # VALIDATE SYMBOLIC / EMOJI MOTIF LOOPS
    # -----------------------------------------------------

    @staticmethod
    def find_inline_symbolic_loop(
        line: str,
    ) -> tuple[str, str]:
        """Return (motif, repeated_tail) for an obvious one-line symbol loop."""

        line = str(line or "").rstrip("\r")

        runs = []
        current_run = []

        for char in line:
            category = unicodedata.category(char)

            # Layout spacing and lightweight markdown wrappers do not change a
            # visual motif, but a physical newline is never present here: the
            # caller checks one completed/current line at a time.
            if char.isspace() or char in "`*_~":
                continue

            if category[:1] in {"P", "S"}:
                current_run.append(char)
                continue

            if category in {"Cf", "Mn", "Me"}:
                continue

            if current_run:
                runs.append("".join(current_run))
                current_run = []

        if current_run:
            runs.append("".join(current_run))

        for run in reversed(runs):
            if len(run) < INLINE_SYMBOLIC_LOOP_MIN_CHARS:
                continue

            max_motif_size = min(
                INLINE_SYMBOLIC_LOOP_MAX_MOTIF_SIZE,
                len(run) // INLINE_SYMBOLIC_LOOP_MIN_REPETITIONS,
            )

            for motif_size in range(2, max_motif_size + 1):
                motif = run[-motif_size:]

                # A solid bar / divider is common intentional ASCII art.
                # The failure we care about has an actual repeating pattern.
                if len(set(motif)) < 2:
                    continue

                repetitions = 0
                offset = len(run)

                while (
                    offset >= motif_size
                    and run[offset - motif_size:offset] == motif
                ):
                    repetitions += 1
                    offset -= motif_size

                repeated_length = repetitions * motif_size

                if (
                    repetitions < INLINE_SYMBOLIC_LOOP_MIN_REPETITIONS
                    or repeated_length < INLINE_SYMBOLIC_LOOP_MIN_CHARS
                ):
                    continue

                return (
                    motif,
                    run[len(run) - repeated_length:],
                )

        return "", ""

    @staticmethod
    def normalize_symbolic_motif(
        line: str,
    ) -> str:
        stripped = str(line or "").strip()

        if not stripped:
            return ""

        # This guard is intentionally narrow. Ordinary prose containing
        # emoji belongs to the word/sentence validators, not here.
        if any(
            char.isalnum()
            for char in stripped
        ):
            return ""

        # Pure ASCII art commonly repeats structural rows (pipes,
        # slashes, underscores, etc.) on purpose. Keep the cross-line
        # motif guard scoped to non-ASCII symbols. Extremely long
        # low-period runs inside one line are handled separately by
        # ``find_inline_symbolic_loop``.
        if stripped.isascii():
            return ""

        symbol_chars = [
            char
            for char in stripped
            if (
                unicodedata.category(char).startswith("S")
                and char not in "`*_~"
            )
        ]

        if len(symbol_chars) < 2:
            return ""

        # Two bare emoji are common conversational punctuation and are not
        # enough evidence of a loop. Require either a richer 3+ symbol motif
        # or real structural punctuation such as parentheses/brackets.
        structural_punctuation = [
            char
            for char in stripped
            if (
                unicodedata.category(char).startswith("P")
                and char not in "`*_~"
            )
        ]

        if (
            len(symbol_chars) < 3
            and not structural_punctuation
        ):
            return ""

        # Ignore spacing/markdown wrappers while preserving the actual
        # visual motif order. ZWJ/variation selectors are deliberately not
        # required for equality; the visible base symbols are enough.
        return "".join(
            char
            for char in stripped
            if (
                (
                    unicodedata.category(char).startswith("S")
                    and char not in "`*_~"
                )
                or (
                    unicodedata.category(char).startswith("P")
                    and char not in "`*_~"
                )
            )
        )

    @staticmethod
    def get_ascii_repeat_candidate(
        line: str,
    ) -> str:
        line = str(line or "").rstrip("\r")
        stripped = line.strip()

        if (
            not stripped
            or "\t" in line
            or not line.isascii()
            or any(char.isalnum() for char in stripped)
        ):
            return ""

        visible = [
            char
            for char in stripped
            if not char.isspace()
        ]

        if (
            len(visible) < ASCII_REPEAT_LOOP_MIN_VISIBLE_CHARS
            or len(set(visible)) < 2
            or any(
                not (
                    unicodedata.category(char).startswith("P")
                    or unicodedata.category(char).startswith("S")
                )
                for char in visible
            )
        ):
            return ""

        # Spacing jitter is common in a degenerating ASCII stream. Normalize
        # it so ``( ) )`` and ``(  )  )`` remain the same visual row.
        return " ".join(
            stripped.split()
        )

    def validate_ascii_repeat_line(
        self,
        line: str,
    ) -> bool:
        body = self.get_ascii_repeat_candidate(
            line
        )

        if not body:
            self.ascii_repeat_history = []
            return True

        if (
            self.ascii_repeat_history
            and self.ascii_repeat_history[-1][0] != body
        ):
            self.ascii_repeat_history = []

        self.ascii_repeat_history.append((
            body,
            line.rstrip("\r"),
        ))
        self.ascii_repeat_history = self.ascii_repeat_history[
            -ASCII_REPEAT_LOOP_MIN_LINES:
        ]

        if len(self.ascii_repeat_history) < ASCII_REPEAT_LOOP_MIN_LINES:
            return True

        preview = "\n".join(
            item[1]
            for item in self.ascii_repeat_history
        )

        self.last_failure_reason = (
            "Repeated symbolic motif loop detected."
        )
        self.last_failure_preview = build_preview(
            preview
        )
        self.last_failure_loop_preview = build_loop_preview(
            body
        )

        return False

    @staticmethod
    def get_ascii_drift_candidate(
        line: str,
    ) -> tuple[int, str] | None:
        line = str(line or "").rstrip("\r")
        stripped = line.strip(" ")

        if (
            not stripped
            or "\t" in line
            or not line.isascii()
            or len(stripped) < ASCII_DRIFT_LOOP_MIN_BODY_WIDTH
            or any(char.isalnum() for char in stripped)
        ):
            return None

        visible = [
            char
            for char in stripped
            if not char.isspace()
        ]

        if (
            len(visible) < 2
            or any(
                not (
                    unicodedata.category(char).startswith("P")
                    or unicodedata.category(char).startswith("S")
                )
                for char in visible
            )
        ):
            return None

        return (
            len(line) - len(line.lstrip(" ")),
            stripped,
        )

    def validate_ascii_drift_line(
        self,
        line: str,
    ) -> bool:
        candidate = self.get_ascii_drift_candidate(
            line
        )

        if candidate is None:
            self.ascii_drift_history = []
            return True

        indent, body = candidate

        if (
            self.ascii_drift_history
            and self.ascii_drift_history[-1][1] != body
        ):
            self.ascii_drift_history = []

        self.ascii_drift_history.append((
            indent,
            body,
            line.rstrip("\r"),
        ))
        self.ascii_drift_history = self.ascii_drift_history[
            -ASCII_DRIFT_LOOP_MIN_LINES:
        ]

        if len(self.ascii_drift_history) < ASCII_DRIFT_LOOP_MIN_LINES:
            return True

        step = (
            self.ascii_drift_history[1][0]
            - self.ascii_drift_history[0][0]
        )

        if (
            abs(step) != 1
            or any(
                current[0] - previous[0] != step
                for previous, current in zip(
                    self.ascii_drift_history,
                    self.ascii_drift_history[1:],
                )
            )
        ):
            return True

        preview = "\n".join(
            item[2]
            for item in self.ascii_drift_history
        )

        self.last_failure_reason = (
            "Repeated symbolic motif loop detected."
        )
        self.last_failure_preview = build_preview(
            preview
        )
        self.last_failure_loop_preview = build_loop_preview(
            body
        )

        return False

    def validate_symbolic_motif_loops(
        self,
        chunk: str,
    ) -> bool:
        if MAX_REPEAT_SYMBOLIC_MOTIFS <= 0:
            return True

        text = self.symbolic_line_fragment + chunk
        lines = text.split("\n")

        if text.endswith("\n"):
            complete_lines = lines[:-1]
            self.symbolic_line_fragment = ""
        else:
            complete_lines = lines[:-1]
            self.symbolic_line_fragment = lines[-1]

        # Do not collapse separate rows into one symbol stream. Repeated rows
        # are valid structure in ASCII/Unicode art; only an obviously runaway
        # low-period sequence inside one physical line is rejected here.
        inline_lines = list(complete_lines)
        if self.symbolic_line_fragment:
            inline_lines.append(self.symbolic_line_fragment)

        for raw_line in inline_lines:
            inline_motif, repeated_tail = self.find_inline_symbolic_loop(
                raw_line
            )

            if not inline_motif:
                continue

            self.last_failure_reason = (
                "Repeated symbolic motif loop detected."
            )
            self.last_failure_preview = build_preview(
                repeated_tail
            )
            self.last_failure_loop_preview = build_loop_preview(
                inline_motif
            )

            return False

        for raw_line in complete_lines:
            if not self.validate_ascii_repeat_line(
                raw_line
            ):
                return False

            if not self.validate_ascii_drift_line(
                raw_line
            ):
                return False

            self.symbolic_line_index += 1

            line = raw_line.rstrip("\r")
            motif_key = self.normalize_symbolic_motif(
                line
            )

            min_line_index = (
                self.symbolic_line_index
                - SYMBOLIC_MOTIF_HISTORY_LINES
            )
            self.symbolic_motif_history = [
                item
                for item in self.symbolic_motif_history
                if item[0] >= min_line_index
            ]

            if not motif_key:
                continue

            self.symbolic_motif_history.append((
                self.symbolic_line_index,
                motif_key,
                line.strip(),
            ))

            matching = [
                item
                for item in self.symbolic_motif_history
                if item[1] == motif_key
            ]

            if (
                len(matching)
                < MAX_REPEAT_SYMBOLIC_MOTIFS
            ):
                continue

            matching = matching[
                -MAX_REPEAT_SYMBOLIC_MOTIFS:
            ]
            loop_text = matching[-1][2]
            preview = "\n".join(
                item[2]
                for item in matching
            )

            self.last_failure_reason = (
                "Repeated symbolic motif loop detected."
            )
            self.last_failure_preview = build_preview(
                preview
            )
            self.last_failure_loop_preview = build_loop_preview(
                loop_text
            )

            return False

        return True

    # -----------------------------------------------------
    # VALIDATE WORD LOOPS
    # -----------------------------------------------------

    def validate_word_loops(
        self,
        chunk: str,
    ):
        text = self.word_fragment + chunk
        words = text.split()

        # Streaming providers may split one lexical token across chunks
        # (for example: ``" F"`` then ``"5,"``). Do not treat the chunk
        # edge as whitespace. Hold the trailing token until a real
        # whitespace boundary arrives.
        if text and not text[-1].isspace():
            if words:
                self.word_fragment = words.pop()
            else:
                self.word_fragment = text
        else:
            self.word_fragment = ""

        for word in words:

            if word == "":
                continue

            clean_word = word.lower().strip(
                " \t\r\n`*_~\"'“”‘’.,:;!?()[]{}<>"
            )

            if not clean_word:
                continue

            # Pure numeric fragments are common in streamed decimals,
            # counters, coordinates, and probabilities. They are not words
            # and must not trigger the repeated-word loop guard.
            if not any(
                char.isalpha()
                for char in clean_word
            ):
                continue

            self.recent_words.append(clean_word)

            self.recent_words = (
                self.recent_words[-WORD_WINDOW_SIZE:]
            )

            if (
                MAX_REPEAT_WORDS > 0
                and len(self.recent_words) >= MAX_REPEAT_WORDS
            ):

                last_word = self.recent_words[-1]

                repeated = all(
                    recent_word == last_word
                    for recent_word in (
                        self.recent_words[-MAX_REPEAT_WORDS:]
                    )
                )

                if repeated:

                    preview = " ".join(
                        self.recent_words[-MAX_REPEAT_WORDS:]
                    )

                    self.last_failure_reason = (
                        "Repeated word loop detected."
                    )

                    self.last_failure_preview = build_preview(preview)
                    self.last_failure_loop_preview = build_loop_preview(
                        last_word
                    )

                    return False

            max_sequence_size = 0

            if MAX_REPEAT_WORD_SEQUENCE_REPETITIONS > 0:
                max_sequence_size = min(
                    MAX_REPEAT_WORD_SEQUENCE_SIZE,
                    len(self.recent_words) // 2,
                )

            for sequence_size in range(
                2,
                max_sequence_size + 1,
            ):
                required_words = (
                    sequence_size
                    * MAX_REPEAT_WORD_SEQUENCE_REPETITIONS
                )

                if len(self.recent_words) < required_words:
                    continue

                recent_sequence = self.recent_words[
                    -sequence_size:
                ]
                window = self.recent_words[
                    -required_words:
                ]
                repeated_sequence = all(
                    window[index:index + sequence_size]
                    == recent_sequence
                    for index in range(
                        0,
                        required_words,
                        sequence_size,
                    )
                )

                if not repeated_sequence:
                    continue

                preview = " ".join(
                    window
                )
                loop_preview = " ".join(
                    recent_sequence
                )

                self.last_failure_reason = (
                    "Repeated word sequence loop detected."
                )
                self.last_failure_preview = build_preview(
                    preview
                )
                self.last_failure_loop_preview = build_loop_preview(
                    loop_preview
                )

                return False

        return True

    # -----------------------------------------------------
    # FILTER SYSTEM MARKERS FOR VALIDATION
    # -----------------------------------------------------

    @staticmethod
    def is_excluded_marker(
        marker: str,
    ) -> bool:

        return (
            extract_marker_name(marker)
            in EXCLUDED_MARKER_NAMES
        )

    @staticmethod
    def can_be_excluded_marker_prefix(
        candidate: str,
    ) -> bool:

        return any(
            marker_start.startswith(candidate)
            or candidate.startswith(marker_start)
            for marker_start in EXCLUDED_MARKER_STARTS
        )

    def filter_validation_exclusions(
        self,
        chunk: str,
    ) -> str:

        text = self.validation_marker_buffer + chunk
        self.validation_marker_buffer = ""

        output = []
        offset = 0

        while offset < len(text):

            marker_start = text.find("<", offset)

            if marker_start < 0:
                if not self.validation_excluded_block_name:
                    output.append(text[offset:])
                break

            if not self.validation_excluded_block_name:
                output.append(
                    text[offset:marker_start]
                )

            marker_end = text.find(
                ">",
                marker_start + 1,
            )

            if marker_end < 0:
                candidate = text[marker_start:]

                if self.can_be_excluded_marker_prefix(
                    candidate
                ):
                    self.validation_marker_buffer = candidate
                elif not self.validation_excluded_block_name:
                    output.append(candidate)

                break

            marker = text[
                marker_start:marker_end + 1
            ]
            marker_name = extract_marker_name(marker)
            is_closing = str(marker).lstrip().startswith("</")

            if self.validation_excluded_block_name:
                if (
                    is_closing
                    and marker_name == self.validation_excluded_block_name
                ):
                    self.validation_excluded_block_name = ""
                    output.append(" ")

                offset = marker_end + 1
                continue

            if (
                marker_name in EXCLUDED_BLOCK_MARKER_NAMES
                and not is_closing
            ):
                self.validation_excluded_block_name = marker_name
                output.append(" ")
            elif self.is_excluded_marker(marker):
                output.append(" ")
            else:
                output.append(marker)

            offset = marker_end + 1

        return "".join(output)

    # -----------------------------------------------------
    # VALIDATE REPETITIONS
    # -----------------------------------------------------

    def validate_repetitions(
        self,
        chunk: str,
    ) -> bool:

        validation_chunk = (
            self.filter_validation_exclusions(
                chunk
            )
        )

        if not validation_chunk:
            return True

        if not self.validate_symbolic_motif_loops(
            validation_chunk
        ):
            return False

        if not self.validate_word_loops(
            validation_chunk
        ):
            return False

        return self.validate_sentences(
            validation_chunk
        )

    # -----------------------------------------------------
    # NORMALIZE CHANGING QUOTED SENTENCE TEMPLATES
    # -----------------------------------------------------

    @staticmethod
    def normalize_sentence_template(
        sentence: str,
    ) -> tuple[str, bool]:

        normalized = " ".join(
            str(sentence or "")
            .casefold()
            .split()
        ).strip(" *_~-\t")

        quote_indexes = [
            index
            for quote in (
                '"',
                "“",
                "„",
                "`",
            )
            if (index := normalized.find(quote)) >= 0
        ]

        if not quote_indexes:
            return (
                normalized,
                False,
            )

        quote_index = min(quote_indexes)
        prefix = normalized[:quote_index].rstrip()

        if sum(
            char.isalnum()
            for char in prefix
        ) < 8:
            return (
                normalized,
                False,
            )

        return (
            f"{prefix}<quoted>",
            True,
        )

    @staticmethod
    def normalize_recurrent_sentence_key(
        sentence: str,
    ) -> str:

        normalized = " ".join(
            str(sentence or "")
            .casefold()
            .split()
        ).strip(" *_~-\t")

        if not normalized:
            return ""

        words = [
            word.strip(
                " \t\r\n`*_~\"'.,:;!?()[]{}<>"
            )
            for word in normalized.split()
        ]
        words = [
            word
            for word in words
            if any(
                char.isalpha()
                for char in word
            )
        ]

        if (
            len(words)
            < MIN_RECURRENT_SENTENCE_WORDS
        ):
            return ""

        if (
            sum(
                char.isalnum()
                for char in normalized
            )
            < MIN_RECURRENT_SENTENCE_ALNUM
        ):
            return ""

        return normalized

    def validate_recurrent_sentence_loop(
        self,
        sentence: str,
    ) -> bool:

        sentence_key = (
            self.normalize_recurrent_sentence_key(
                sentence
            )
        )

        if not sentence_key:
            return True

        if MAX_REPEAT_SENTENCES <= 0:
            return True

        matching_sentences = [
            history_sentence
            for history_sentence in (
                self.recurrent_sentence_history
            )
            if (
                self.normalize_recurrent_sentence_key(
                    history_sentence
                )
                == sentence_key
            )
        ]

        if (
            len(matching_sentences)
            < MAX_REPEAT_SENTENCES
        ):
            return True

        preview = "\n".join(
            sentence.strip()
            for sentence in matching_sentences[
                -MAX_REPEAT_SENTENCES:
            ]
        )

        self.last_failure_reason = (
            "Repeated sentence loop detected."
        )
        self.last_failure_preview = build_preview(
            preview
        )
        self.last_failure_loop_preview = build_loop_preview(
            sentence.strip()
        )

        return False

    # -----------------------------------------------------
    # VALIDATE SENTENCES
    # -----------------------------------------------------

    def validate_sentence_sequence_loop(
        self,
        sentence: str,
    ) -> bool:

        self.sentence_history.append(
            sentence
        )
        self.recurrent_sentence_history.append(
            sentence
        )

        if (
            len(self.sentence_history)
            > SENTENCE_HISTORY_SIZE
        ):
            del self.sentence_history[0]

        if (
            len(self.recurrent_sentence_history)
            > MAX_RECURRENT_SENTENCE_HISTORY_SIZE
        ):
            del self.recurrent_sentence_history[0]

        if MAX_REPEAT_SENTENCES <= 0:
            return True

        max_sequence_size = min(
            MAX_SENTENCE_LOOP_SEQUENCE_SIZE,
            len(self.sentence_history) - 1,
        )

        for sequence_size in range(
            1,
            max_sequence_size + 1,
        ):
            current_sentence = (
                self.sentence_history[-1]
            )
            previous_sentence = (
                self.sentence_history[
                    -1 - sequence_size
                ]
            )

            sentences_match = (
                current_sentence
                == previous_sentence
            )

            if (
                not sentences_match
                and sequence_size >= 2
            ):
                current_template, current_generalized = (
                    self.normalize_sentence_template(
                        current_sentence
                    )
                )
                previous_template, previous_generalized = (
                    self.normalize_sentence_template(
                        previous_sentence
                    )
                )

                sentences_match = (
                    current_generalized
                    and previous_generalized
                    and current_template
                    == previous_template
                )

            if sentences_match:
                self.sentence_period_match_counts[
                    sequence_size
                ] += 1
            else:
                self.sentence_period_match_counts[
                    sequence_size
                ] = 0

            required_match_count = (
                sequence_size
                * (MAX_REPEAT_SENTENCES - 1)
            )

            if (
                self.sentence_period_match_counts[
                    sequence_size
                ]
                < required_match_count
            ):
                continue

            sequence = self.sentence_history[
                -sequence_size:
            ]
            loop_text = "\n".join(
                sentence.strip()
                for sentence in sequence
                if sentence.strip()
            )

            self.last_failure_reason = (
                "Repeated sentence loop detected."
            )
            self.last_failure_preview = build_preview(
                loop_text
            )
            # Keep the whole detected sentence period, not only the
            # final sentence that happened to trip the threshold.
            # The loop preview is used both by the validator console
            # and CURRENT_SEQUENCE recovery context, so reducing a
            # two-sentence loop to e.g. only "No." loses the cause.
            self.last_failure_loop_preview = build_loop_preview(
                loop_text
            )

            return False

        if not self.validate_recurrent_sentence_loop(
            sentence
        ):
            return False

        return True

    def validate_sentence(
        self,
        sentence: str,
    ) -> bool:

        if not any(
            char.isalnum()
            for char in sentence
        ):
            return True

        return self.validate_sentence_sequence_loop(
            sentence
        )

    def validate_sentences(
        self,
        chunk: str,
    ) -> bool:

        sentence_start = 0

        for index, char in enumerate(chunk):

            if char not in ".!?\n":
                continue

            self.current_sentence_parts.append(
                chunk[sentence_start:index + 1]
            )

            raw_sentence = "".join(
                self.current_sentence_parts
            )
            self.current_sentence_parts.clear()

            if not self.validate_sentence(
                raw_sentence
            ):
                return False

            sentence_start = index + 1

        if sentence_start < len(chunk):
            self.current_sentence_parts.append(
                chunk[sentence_start:]
            )

        return True
    # -----------------------------------------------------
    # VALIDATE PARAGRAPHS
    # -----------------------------------------------------

    def validate_paragraphs(
        self,
        chunk: str,
    ):
        return True
        if "\n" not in chunk:
            return True

        paragraphs = [
            p.strip().lower()
            for p in chunk.split("\n")
            if p.strip()
        ]

        for paragraph in paragraphs:

            if paragraph in self.history_paragraphs:

                self.last_failure_reason = (
                    "Repeated paragraph detected."
                )

                self.last_failure_preview = build_preview(paragraph)
                self.last_failure_loop_preview = build_loop_preview(
                    paragraph
                )

                return False

            self.history_paragraphs.add(paragraph)

        return True

    # -----------------------------------------------------
    # FILTER STREAM CHUNK
    # -----------------------------------------------------

    def filter_chunk(
        self,
        chunk: str,
    ):
        # -------------------------------------------------
        # SANITIZE
        # -------------------------------------------------

        clean_chunk = self.sanitize_artifacts(chunk)

        # -------------------------------------------------
        # WAIT STREAM
        # -------------------------------------------------

        if clean_chunk is None:
            return (
                "",
                True,
            )

        if self.same_output_reference_prefix:
            self.same_output_prefix_buffer += clean_chunk
            compare_length = min(
                len(self.same_output_prefix_buffer),
                len(self.same_output_reference_prefix),
            )

            if (
                self.same_output_prefix_buffer[:compare_length]
                != self.same_output_reference_prefix[:compare_length]
            ):
                clean_chunk = self.same_output_prefix_buffer
                self.same_output_prefix_buffer = ""
                self.same_output_reference_prefix = ""
            elif compare_length < len(self.same_output_reference_prefix):
                return (
                    "",
                    True,
                )
            else:
                preview = self.same_output_reference_prefix
                self.last_failure_reason = SAME_ANSWER_OUTPUT_REASON
                self.last_failure_preview = build_preview(preview)
                self.last_failure_loop_preview = build_loop_preview(
                    preview
                )
                self.same_output_prefix_buffer = ""
                self.same_output_reference_prefix = ""

                return (
                    "",
                    False,
                )

        chunk = self.hold_trailing_artifact_candidate(
            clean_chunk
        )

        if not chunk:
            return (
                "",
                True,
            )

        # -------------------------------------------------
        # REPETITION LOOPS
        # -------------------------------------------------

        if not self.validate_repetitions(chunk):
            return (
                "",
                False,
            )

        # -------------------------------------------------
        # PARAGRAPHS
        # -------------------------------------------------

        if not self.validate_paragraphs(chunk):
            return (
                "",
                False,
            )

        return (
            chunk,
            True,
        )
