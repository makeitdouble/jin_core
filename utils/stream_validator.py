# ---------------------------------------------------------
# STREAM VALIDATOR
# ---------------------------------------------------------
#
# Runtime stream validator for:
# - repeated word loops
# - repeated sentences
# - repeated paragraphs
#
#
# ---------------------------------------------------------


# ---------------------------------------------------------
# VALIDATION THRESHOLDS
# ---------------------------------------------------------

# How many recent words to keep in memory.
WORD_WINDOW_SIZE = 30

# How many repeated consecutive words
# trigger repetition detection.
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
        # WORD LOOP DETECTION
        # -------------------------------------------------

        words = chunk.split()

        for word in words:

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

                    return (
                        "",
                        False,
                    )

        # -------------------------------------------------
        # SENTENCE TRACKING
        # -------------------------------------------------

        self.current_sentence += chunk

        if any(
            char in chunk
            for char in [
                ".",
                "!",
                "?",
                "\n",
            ]
        ):

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

                return (
                    "",
                    False,
                )

            self.history_sentences.add(
                sentence
            )

            self.current_sentence = ""

        # -------------------------------------------------
        # PARAGRAPH TRACKING
        # -------------------------------------------------

        if "\n" in chunk:

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

                    return (
                        "",
                        False,
                    )

                self.history_paragraphs.add(
                    paragraph
                )

        return (
            chunk,
            True,
        )
