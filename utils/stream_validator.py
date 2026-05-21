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

# ---------------------------------------------------------
# VALIDATION THRESHOLDS
# ---------------------------------------------------------

WORD_WINDOW_SIZE = 30

MAX_REPEAT_WORDS = 8

TRUNCATE = 10


class StreamValidator:

    def __init__(self):

        self.current_sentence = ""

        self.history_sentences = set()

        self.history_paragraphs = set()

        self.recent_words = []

        self.last_failure_reason = None

        self.last_failure_preview = ""

        self.stream_started = False

        self.failure_emitted = False

        self.leading_tag_buffer = ""

        self.leading_cleanup_done = False

        self.visible_content_started = False

        self.leading_buffer = ""

        self.cleanup_events = []

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

        # -------------------------------------------------
        # FULL MATCH
        # -------------------------------------------------

        for artifact in normalized_artifacts:

            if normalized.startswith(
                artifact
            ):

                artifact_length = len(artifact)

                removed = (
                    self.leading_buffer[
                        :artifact_length
                    ]
                )

                remaining = (
                    self.leading_buffer[
                        artifact_length:
                    ]
                )

                self.last_failure_reason = (
                    "Leading artifact removed."
                )

                self.last_failure_preview = (
                    removed
                )

                return remaining

        # -------------------------------------------------
        # PARTIAL MATCH
        # -------------------------------------------------

        for artifact in normalized_artifacts:

            if artifact.startswith(
                normalized
            ):

                return None

        # -------------------------------------------------
        # CLEAN START
        # -------------------------------------------------

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
        # CLEANUP ALREADY FINISHED
        # -------------------------------------------------

        if self.leading_cleanup_done:
            return chunk

        self.leading_tag_buffer += chunk

        working = self.leading_tag_buffer

        # -------------------------------------------------
        # REMOVE LEADING TAGS ONLY
        # -------------------------------------------------

        while True:

            stripped = working.lstrip()

            # ---------------------------------------------
            # NORMAL CONTENT STARTED
            # ---------------------------------------------

            if not stripped.startswith("<"):

                self.leading_cleanup_done = True

                self.leading_tag_buffer = ""

                return working

            closing = stripped.find(">")

            # ---------------------------------------------
            # INCOMPLETE TAG
            # ---------------------------------------------

            if closing == -1:

                return None

            full_tag = stripped[:closing + 1]

            normalized = (
                full_tag
                .lower()
                .replace("<", "")
                .replace(">", "")
                .replace("/", "")
                .strip()
                .split()[0]
            )

            # ---------------------------------------------
            # UNKNOWN TAG
            # ---------------------------------------------

            if normalized not in HTML_TAGS:

                self.leading_cleanup_done = True

                self.leading_tag_buffer = ""

                return working

            # ---------------------------------------------
            # REMOVE KNOWN TAG
            # ---------------------------------------------

            self.cleanup_events.append({
                "reason": "HTML tag removed.",
                "preview": full_tag,
            })

            tag_start = working.find(full_tag)

            working = (
                working[:tag_start]
                + working[
                    tag_start + len(full_tag):
                ]
            )

            self.leading_tag_buffer = working

            # ---------------------------------------------
            # STILL ONLY TAGS
            # ---------------------------------------------

            if not working.strip():

                return None

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

            clean_word = (
                word
                .lower()
                .strip(
                    ".,!?()[]{}:;\"'"
                )
            )

            if not clean_word:
                continue

            self.recent_words.append(
                clean_word
            )

            self.recent_words = (
                self.recent_words[
                    -WORD_WINDOW_SIZE:
                ]
            )

            if (
                len(self.recent_words)
                >= MAX_REPEAT_WORDS
            ):

                last_word = (
                    self.recent_words[-1]
                )

                repeated = all(
                    recent_word == last_word
                    for recent_word in (
                        self.recent_words[
                            -MAX_REPEAT_WORDS:
                        ]
                    )
                )

                if repeated:

                    preview = " ".join(
                        self.recent_words[
                            -MAX_REPEAT_WORDS:
                        ]
                    )

                    self.last_failure_reason = (
                        "Repeated word loop detected."
                    )

                    self.last_failure_preview = (
                        preview[:TRUNCATE]
                    )

                    return False

        return True

    # -----------------------------------------------------
    # VALIDATE SENTENCES
    # -----------------------------------------------------

    def validate_sentences(
        self,
        chunk: str,
    ):

        self.current_sentence += chunk

        if not any(
            char in chunk
            for char in [
                ".",
                "!",
                "?",
                "\n",
            ]
        ):

            return True

        sentence = (
            self.current_sentence
            .strip()
            .lower()
            .rstrip(".!? \n")
        )

        if (
            sentence
            in self.history_sentences
        ):

            self.last_failure_reason = (
                "Repeated sentence detected."
            )

            self.last_failure_preview = (
                sentence[:TRUNCATE]
            )

            return False

        self.history_sentences.add(
            sentence
        )

        self.current_sentence = ""

        return True

    # -----------------------------------------------------
    # VALIDATE PARAGRAPHS
    # -----------------------------------------------------

    def validate_paragraphs(
        self,
        chunk: str,
    ):

        if "\n" not in chunk:
            return True

        paragraphs = [
            p.strip().lower()
            for p in (
                chunk.split("\n")
            )
            if p.strip()
        ]

        for paragraph in paragraphs:

            if (
                paragraph
                in self.history_paragraphs
            ):

                self.last_failure_reason = (
                    "Repeated paragraph detected."
                )

                self.last_failure_preview = (
                    paragraph[:TRUNCATE]
                )

                return False

            self.history_paragraphs.add(
                paragraph
            )

        return True

    # -----------------------------------------------------
    # FILTER STREAM CHUNK
    # -----------------------------------------------------

    def filter_chunk(
        self,
        chunk: str,
    ):

        """
        Validate streamed chunk.

        Returns:
            (
                chunk,
                is_valid,
            )
        """

        # -------------------------------------------------
        # SANITIZE ARTIFACTS
        # -------------------------------------------------

        chunk = (
            self.sanitize_artifacts(
                chunk
            )
        )

        # -------------------------------------------------
        # WAIT FOR REAL CONTENT
        # -------------------------------------------------

        if chunk is None:

            return (
                "",
                True,
            )

        # -------------------------------------------------
        # EMPTY CHUNK AFTER SANITIZATION
        # -------------------------------------------------

        if not chunk.strip():

            # still waiting for real text
            # after removing leading tags

            if not self.leading_cleanup_done:

                return (
                    "",
                    True,
                )

            self.last_failure_reason = (
                "Empty chunk after sanitization."
            )

            self.last_failure_preview = ""

            return (
                "",
                True,
            )

        # -------------------------------------------------
        # WORD LOOPS
        # -------------------------------------------------

        if not (
            self.validate_word_loops(
                chunk
            )
        ):

            return (
                "",
                False,
            )

        # -------------------------------------------------
        # SENTENCES
        # -------------------------------------------------

        if not (
            self.validate_sentences(
                chunk
            )
        ):

            return (
                "",
                False,
            )

        # -------------------------------------------------
        # PARAGRAPHS
        # -------------------------------------------------

        if not (
            self.validate_paragraphs(
                chunk
            )
        ):

            return (
                "",
                False,
            )

        if chunk.strip():

            self.visible_content_started = True

        return (
            chunk,
            True,
        )
