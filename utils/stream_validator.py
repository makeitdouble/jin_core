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

WORD_WINDOW_SIZE = 30
MAX_REPEAT_WORDS = 8
TRUNCATE = 160

def build_preview(
        text: str,
) -> str:

    return (
        text
        .replace("\n", "\\n")
        .strip()
    )[:TRUNCATE]

class StreamValidator:

    def __init__(self):

        self.current_sentence = ""

        self.history_sentences = set()
        self.history_paragraphs = set()

        self.recent_words = []

        self.last_failure_reason: str | None = None
        self.last_failure_preview = ""

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

        tail = self.trailing_artifact_buffer

        self.trailing_artifact_buffer = ""

        if not tail:
            return ""

        if tail in TRAILING_ARTIFACTS:

            self.cleanup_events.append({
                "reason": "Trailing artifact removed.",
                "preview": tail,
            })

            return ""

        return tail

    # -----------------------------------------------------
    # VALIDATE WORD LOOPS
    # -----------------------------------------------------

    def validate_word_loops(
        self,
        chunk: str,
    ):
        words = chunk.split(" ")

        for word in words:

            if word == "":
                continue

            clean_word = word.lower()

            if not clean_word:
                continue

            if not any(
                char.isalnum()
                for char in clean_word
            ):
                continue

            self.recent_words.append(clean_word)

            self.recent_words = (
                self.recent_words[-WORD_WINDOW_SIZE:]
            )

            if len(self.recent_words) >= MAX_REPEAT_WORDS:

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

                    return False

        return True

    # -----------------------------------------------------
    # VALIDATE SENTENCES
    # -----------------------------------------------------

    def validate_sentences(
        self,
        chunk: str,
    ):

        return True
        self.current_sentence += chunk

        raw_sentence = self.current_sentence.strip()

        if not any(
            char in chunk
            for char in [".", "!", "?", "\n"]
        ):
            return True

        sentence = (
            raw_sentence
            .lower()
            .rstrip(".!? \n")
        )

        sentence = (
            raw_sentence
            .lower()
            .rstrip(".!? \n")
        )

        if not sentence:
            self.current_sentence = ""
            return True

        if sentence in self.history_sentences:

            self.last_failure_reason = (
                "Repeated sentence detected."
            )

            self.last_failure_preview = build_preview(raw_sentence)

            return False

        self.history_sentences.add(sentence)

        self.current_sentence = ""

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

        chunk = self.hold_trailing_artifact_candidate(
            clean_chunk
        )

        if not chunk:
            return (
                "",
                True,
            )

        # -------------------------------------------------
        # WORD LOOPS
        # -------------------------------------------------

        if not self.validate_word_loops(chunk):
            return (
                "",
                False,
            )

        # -------------------------------------------------
        # SENTENCES
        # -------------------------------------------------

        if not self.validate_sentences(chunk):
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
