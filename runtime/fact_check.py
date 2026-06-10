import json
import re
from dataclasses import dataclass

from clients.response_extractor import ResponseExtractor
from clients.search_client import run_search_provider
from clients.service_client import ask_service_model
from config_loader import config


FACT_CHECK_MAX_CANDIDATES_PER_RUN = 1


# Add keys here as soon as a memory field starts carrying concrete claims
# that should be eligible for lightweight web confirmation.
CONFIRMABLE_MEMORY_KEYS = [
    "user fact",
    "user_fact",
    "jin fact",
    "jin_fact",
    "pending fact",
    "pending_fact",
    "jin recommendation",
    "jin_recommendation",
    "user recommendation",
    "user_recommendation",
]

CONFIRMATION_SOURCES = (
    "user",
    "jin",
    "web",
    "none",
)

USER_CONFIRMATION_MARKERS = (
    "подтверждаю",
    "это факт",
    "точно",
    "верно",
    "да, это так",
    "запомни",
    "сохрани",
    "remember that",
    "confirmed",
    "that is true",
)

JIN_CONFIRMATION_MARKERS = (
    "подтверждаю",
    "это факт",
    "точно",
    "верно",
    "confirmed",
    "i confirm",
)

NEGATIVE_WEB_MARKERS = (
    "does not exist",
    "no album",
    "not an album",
    "not found",
    "нет такого",
    "не существует",
)

TOKEN_RE = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9]{3,}")
CONFIRMED_RE = re.compile(
    r"\(confirmed:\s*((?:[^()]|\([^()]*\))*)\)",
    re.IGNORECASE,
)
WEB_FIELD_RE = re.compile(
    r"web:\s*(?:no|fail)(?:\s*\(\d+\))?",
    re.IGNORECASE,
)
WEB_FAIL_COUNT_RE = re.compile(
    r"web:\s*fail(?:\s*\((\d+)\))?",
    re.IGNORECASE,
)
TRACE_FIELD_RE = re.compile(r"\s*\(trace:\s*[^)]*\)", re.IGNORECASE)

FACT_CHECK_QUERY_MAX = 1
FACT_CHECK_SEARCH_RESULTS_PER_QUERY = 5
FACT_CHECK_PLANNER_MAX_TOKENS = 512
FACT_CHECK_JUDGE_MAX_TOKENS = 768
FACT_CHECK_LLM_TEMPERATURE = 0.05
FACT_CHECK_STATUSES = ("web", "fail")

MARKDOWN_TITLE_RE = re.compile(r"\*([^*]{2,96})\*")
QUOTED_TITLE_RE = re.compile(r"[\"\']([^\"\']{2,96})[\"\']")
RECOMMENDATION_VALUE_TITLE_RE = re.compile(
    r"^\s*(?:jin_recommendation|user_recommendation)\s*:\s*(.+)$",
    re.IGNORECASE,
)
ALBUM_TITLE_PATTERNS = (
    re.compile(
        r"\b(?:recommended|suggested)?[ \t]*(?:the[ \t]+)?album[ \t]+[\"\']([^\"\']{2,96})[\"\']",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b[\"\']([^\"\']{2,96})[\"\'][ \t]+by[ \t]+[^\n\r:.;,()]{2,80}",
        re.IGNORECASE,
    ),
)
ARTIST_PATTERNS = (
    re.compile(
        # Prefer explicit ownership in recommendation prose:
        #   Suggested *Rusk* by Four Tet.
        # This must run before generic "artist:" patterns, otherwise text like
        # "artist's sound palette" can be misread as an artist name.
        r"\bby\s+(?:the[ \t]+artist[ \t]+)?([^\n\r:.;,()]{2,80})",
        re.IGNORECASE,
    ),
    re.compile(
        # Do not let the artist capture run across memory lines into keys like
        # "jin_recommendation". Stop at punctuation/line/key boundaries.
        # Also require a real word boundary after "artist" so "artist's" does
        # not become the bogus artist name "s sound palette".
        r"(?:specific[ \t]+artist|artist)\b(?!['’])\s*:?\s*([^\n\r:.;,()]{2,80})",
        re.IGNORECASE,
    ),
)
NOISE_TITLE_WORDS = {
    "JIN",
    "SERVICE",
    "BRAIN",
}


@dataclass
class FactCheckPlan:
    claim: str
    search_queries: list[str]
    check_instructions: str
    expected_evidence: str
    raw_response: str = ""
    structured_claim: dict | None = None


@dataclass
class FactCheckDecision:
    status: str
    reasoning: str
    supporting_evidence: str = ""
    raw_response: str = ""



@dataclass
class FactCheckCandidate:
    layer: str
    line_index: int
    key: str
    value: str
    line: str


def normalize_key(key: str) -> str:
    return str(key or "").strip().lower().replace(" ", "_")


def strip_confirmation_suffix(value: str) -> str:
    value = CONFIRMED_RE.sub("", str(value or ""))
    value = TRACE_FIELD_RE.sub("", value)
    return value.strip()


def parse_memory_line(line: str) -> tuple[str, str] | None:
    if ":" not in line:
        return None

    key, value = line.split(":", 1)
    key = key.strip().lstrip("-").strip()
    value = value.strip()

    if not key:
        return None

    return key, value


def confirmation_sources_from_text(text: str) -> set[str]:
    match = CONFIRMED_RE.search(text or "")

    if not match:
        return set()

    # Parse the comma-separated confirmation payload instead of scanning it as
    # raw text. Otherwise `web: fail (1)` is misread as a successful `web`
    # confirmation and the line becomes non-retryable after the first fail.
    parts = [
        part.strip().casefold()
        for part in match.group(1).split(",")
        if part.strip()
    ]
    sources = set()

    for part in parts:
        if part.startswith("web:"):
            continue

        if part in CONFIRMATION_SOURCES:
            sources.add(part)

    return sources


def has_web_check_result(line: str) -> bool:
    return bool(WEB_FIELD_RE.search(line or ""))


def has_successful_web_confirmation(line: str) -> bool:
    return "web" in confirmation_sources_from_text(line or "")


def next_web_fail_attempt_count(web_field: str | None) -> int:
    match = WEB_FAIL_COUNT_RE.search(web_field or "")

    if not match:
        return 1

    raw_count = match.group(1)

    if raw_count is None:
        # Legacy memory may already contain `web: fail` without a counter.
        # Treat the next write as the second failed attempt.
        return 2

    try:
        return max(1, int(raw_count)) + 1
    except ValueError:
        return 1


def is_confirmable_key(key: str) -> bool:
    return normalize_key(key) in {
        normalize_key(item)
        for item in CONFIRMABLE_MEMORY_KEYS
    }


def infer_initial_confirmation_source(
        *,
        key: str,
        user_message: str = "",
        assistant_message: str = "",
) -> str:
    normalized_key = normalize_key(key)
    normalized_user = str(user_message or "").casefold()
    normalized_assistant = str(assistant_message or "").casefold()

    if (
            normalized_key == "user_fact"
            and any(marker in normalized_user for marker in USER_CONFIRMATION_MARKERS)
    ):
        return "user"

    if (
            normalized_key == "jin_fact"
            and any(marker in normalized_assistant for marker in JIN_CONFIRMATION_MARKERS)
    ):
        return "jin"

    return "none"


def add_or_update_confirmation(
        line: str,
        *,
        source: str | None = None,
        web_status: str | None = None,
) -> str:
    line = str(line or "").rstrip()
    match = CONFIRMED_RE.search(line)

    if match:
        content = match.group(1).strip()
        parts = [
            part.strip()
            for part in content.split(",")
            if part.strip()
        ]
    else:
        parts = []

    sources = []
    web_field = None

    for part in parts:
        low = part.casefold()
        if low.startswith("web:"):
            web_field = part
            continue
        if low in CONFIRMATION_SOURCES and low not in sources:
            sources.append(low)

    if not sources:
        sources = ["none"]

    if source:
        normalized_source = source.casefold()
        if normalized_source in CONFIRMATION_SOURCES:
            if normalized_source != "none" and "none" in sources:
                sources = [item for item in sources if item != "none"]
            if normalized_source not in sources:
                sources.append(normalized_source)

    if web_status in {"no", "fail"}:
        # Memory should not store a separate "web: no" state. A web lookup
        # that did not confirm the claim is only an unconfirmed/failed check,
        # not a durable negative fact. Count repeated attempts so the UI shows
        # that JIN already tried to verify this fact.
        web_field = f"web: fail ({next_web_fail_attempt_count(web_field)})"

    if source == "web":
        web_field = None

    new_parts = sources
    if web_field:
        new_parts = [*new_parts, web_field]

    suffix = f"(confirmed: {', '.join(new_parts)})"

    if match:
        return (
            line[:match.start()].rstrip()
            + " "
            + suffix
            + line[match.end():]
        ).strip()

    return f"{line} {suffix}".strip()


def ensure_confirmable_memory_markers(
        memory: str,
        *,
        user_message: str = "",
        assistant_message: str = "",
) -> str:
    output = []

    for raw_line in (memory or "").splitlines():
        line = raw_line.rstrip()
        parsed = parse_memory_line(line)

        if parsed is None:
            output.append(line)
            continue

        key, _ = parsed

        if not is_confirmable_key(key):
            output.append(line)
            continue

        if CONFIRMED_RE.search(line):
            output.append(line)
            continue

        output.append(
            add_or_update_confirmation(
                line,
                source=infer_initial_confirmation_source(
                    key=key,
                    user_message=user_message,
                    assistant_message=assistant_message,
                ),
            )
        )

    return "\n".join(output).strip()


def extract_fact_check_candidates(
        memory: str,
        *,
        layer: str,
) -> list[FactCheckCandidate]:
    candidates = []

    for index, raw_line in enumerate((memory or "").splitlines()):
        line = raw_line.strip()
        parsed = parse_memory_line(line)

        if parsed is None:
            continue

        key, value = parsed

        if not is_confirmable_key(key):
            continue

        if has_successful_web_confirmation(line):
            continue

        candidates.append(
            FactCheckCandidate(
                layer=layer,
                line_index=index,
                key=key,
                value=strip_confirmation_suffix(value),
                line=line,
            )
        )

    return candidates



def extract_model_text(response: dict) -> str:
    return (
        ResponseExtractor.extract_content_text(response)
        or ResponseExtractor.extract_reasoning_text(response)
        or ""
    ).strip()


def extract_json_object(text: str) -> dict:
    raw = str(text or "").strip()

    if raw.startswith("```"):
        raw = re.sub(
            r"^```(?:json)?\s*",
            "",
            raw,
            flags=re.IGNORECASE,
        )
        raw = re.sub(
            r"\s*```$",
            "",
            raw,
        ).strip()

    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    end = raw.rfind("}")

    if start == -1 or end == -1 or end <= start:
        return {}

    try:
        value = json.loads(raw[start:end + 1])
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def get_fact_check_service_client(context):
    clients = getattr(context, "clients", {}) or {}
    return clients.get("service")


def normalize_search_query(query: str) -> str:
    query = str(query or "")

    # The search provider must receive one normal Google-style query, not a
    # planner/debug string with alternatives. Keep only the first concrete
    # query before any cleanup, so `A | B`, `A OR B`, `A; B`, and multiline
    # planner output cannot leak into Serper.
    query = re.split(
        r"\s+\|\s+|\s+OR\s+|[;\n\r]+",
        query,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    query = " ".join(query.split()).strip()
    query = query.strip("` ")

    # Strip memory/UI helper tokens that are not part of the checked entity.
    # Example bad query from memory: "Rusk" "Four Tet. jin" album
    query = query.replace("*", "")
    query = re.sub(r"\b(?:JIN|SERVICE|BRAIN)\b", "", query, flags=re.IGNORECASE)

    # Never let memory bookkeeping leak into Google. The LLM sometimes copies
    # `(confirmed: none)` into a quoted title, or even truncates it as
    # `(confirmed: none"`; both must be removed before the provider call.
    query = re.sub(
        r"\s*\(?confirmed:\s*[^)\"']*\)?",
        "",
        query,
        flags=re.IGNORECASE,
    )
    # Final provider-side cleanup for type hints that accidentally got copied
    # into a quoted title, e.g. `"The Fat of the Land (album" ...`.
    query = re.sub(
        r"\s*\(\s*(?:album|single|track|song|ep|lp)\s*\)?(?=\"|$)",
        "",
        query,
        flags=re.IGNORECASE,
    )

    # Google handles plain entity queries better here than brittle exact-quote
    # searches. Remove all quote characters so a slightly noisy artist/title
    # does not turn into an empty-result exact phrase query.
    query = query.translate(str.maketrans({
        '"': "",
        "'": "",
        "“": "",
        "”": "",
        "‘": "",
        "’": "",
    }))
    query = re.sub(r"\s+", " ", query).strip()
    query = re.sub(r"\s+\.\s*$", "", query)

    return query


def normalize_fact_check_queries(queries: list[str]) -> list[str]:
    # One fact-check candidate should trigger exactly one precise search query.
    # Do not fan out alternatives: the modal/report should show the same single
    # query that was actually executed.
    for query in queries or []:
        normalized = normalize_search_query(str(query))
        if normalized:
            return [normalized]

    return []

def strip_markdown_title(title: str) -> str:
    title = str(title or "").strip()
    title = title.strip("*`_ ")
    title = re.sub(r"\s+", " ", title)
    return title.strip(" .,:;!?()[]{}")


def clean_recommendation_title_hint(text: str) -> str:
    title = strip_confirmation_suffix(str(text or "").strip())

    # Prefer explicit emphasis/quotes first: `*Images of You* was suggested...`
    # must become `Images of You`, not the whole recommendation sentence.
    emphasized = extract_title_hint_from_markup(title)
    if emphasized:
        return emphasized

    title = strip_markdown_title(title)
    title = re.split(
        r"\s+(?:was|is|as)\s+(?:suggested|recommended|described|picked|chosen|presented)\b",
        title,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]

    # Recommendation memory often stores helper parentheticals after the title:
    #   `The Fat of the Land (for Prodigy)`
    #   `The Fat of the Land (album)`
    # These are context/type hints, not part of the exact album title, and must
    # not enter the quoted search query. Also handle a previously malformed
    # query path where `(album)` was truncated to `(album`.
    title = re.split(
        r"\s*\((?:for|by|from)\s+[^)]{2,96}\)",
        title,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    title = re.split(
        r"\s*\(\s*(?:album|single|track|song|ep|lp)\s*\)?",
        title,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    title = re.split(
        r"\s*\((?:described|because|covering|with)\b|\s*,\s*(?:covering|because|with)\b",
        title,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return strip_markdown_title(title)


def extract_title_hint_from_markup(text: str) -> str:
    raw = str(text or "")

    for regex in (MARKDOWN_TITLE_RE, QUOTED_TITLE_RE):
        for match in regex.finditer(raw):
            title = strip_markdown_title(match.group(1))
            if title and title not in NOISE_TITLE_WORDS:
                return title

    return ""


def clean_extracted_artist(artist: str) -> str:
    artist = str(artist or "").strip()
    artist = artist.replace("*", "").replace("`", "")

    # Guard against accidental captures from prose like
    # "the artist's sound palette". That is context, not an artist.
    if re.match(r"^['’]?s[ \t]+", artist, flags=re.IGNORECASE):
        return ""

    artist = re.split(
        r"\b(user_request|jin_recommendation|last_jin_response|known_fact|current_topic|active_topics)\b",
        artist,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    artist = re.sub(
        r"\b(albums?|discography|music|recommendations?|release|track|jin|service|brain)\b.*$",
        "",
        artist,
        flags=re.IGNORECASE,
    )
    # Stop artist capture before recommendation prose. Example:
    # `by The Prodigy as a classic starting point` -> `The Prodigy`.
    artist = re.split(
        r"\s+\b(?:as|because|due|with|while|but|and)\b\s+",
        artist,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    artist = re.sub(
        r"^(?:the[ \t]+)?(?:band|artist|group|act)[ \t]+",
        "",
        artist,
        flags=re.IGNORECASE,
    )
    artist = re.sub(r"\s+", " ", artist)
    artist = artist.strip(" .,:;!?()[]{}\"'")

    # Common ambiguity in album recommendations: `Prodigy` often means the
    # electronic band, while search results for bare `Prodigy` are polluted by
    # the rapper Prodigy and generic product pages. Canonicalize the band name
    # once the extractor has already captured it as the artist.
    if artist.casefold() in {"prodigy", "the prodigy"}:
        return "The Prodigy"

    return artist

def extract_title_hint(*texts: str) -> str:
    for text in texts:
        raw = str(text or "")

        # Prefer explicit album/recommendation structure over generic prose.
        # Example memory state:
        #   user_request: Recommend one Four Tet album.
        #   jin_recommendation: Rahn (described as a balance...)
        #   last_jin_response: Recommended the album 'Rahn' by Four Tet.
        # The checked line itself may only contain the title plus a description,
        # so this extracts the concrete item instead of searching the whole JIN
        # explanation as a literal quote.
        recommendation_match = RECOMMENDATION_VALUE_TITLE_RE.search(raw)
        if recommendation_match:
            title = clean_recommendation_title_hint(recommendation_match.group(1))
            if title and title not in NOISE_TITLE_WORDS:
                return title

        for regex in ALBUM_TITLE_PATTERNS:
            for match in regex.finditer(raw):
                title = strip_markdown_title(match.group(1))
                if title and title not in NOISE_TITLE_WORDS:
                    return title

        title = extract_title_hint_from_markup(raw)
        if title:
            return title

    return ""


def extract_artist_hint(*texts: str) -> str:
    joined = "\n".join(str(text or "") for text in texts)

    for pattern in ARTIST_PATTERNS:
        match = pattern.search(joined)
        if match:
            artist = clean_extracted_artist(match.group(1))
            if artist:
                return artist

    return ""


def build_structured_query_hints(
        *,
        candidate: FactCheckCandidate,
        memory_snapshot: str,
        claim: str = "",
) -> tuple[list[str], dict | None]:
    # Keep this deliberately tiny and testable. The LLM still plans the check,
    # but this guardrail prevents it from searching the whole prose sentence.
    # Current high-value case: music recommendation hallucinations.
    title = extract_title_hint(
        candidate.line,
        candidate.value,
        claim,
        memory_snapshot,
    )
    artist = extract_artist_hint(
        candidate.line,
        candidate.value,
        claim,
        memory_snapshot,
    )

    if not title or not artist:
        return [], None

    queries = [
        f"{title} {artist} album",
    ]

    return queries, {
        "type": "music_album",
        "title": title,
        "artist": artist,
    }


def merge_precise_queries(
        *,
        precise_queries: list[str],
        llm_queries: list[str],
) -> list[str]:
    # Code-level structured hints beat the LLM planner. The planner may still
    # include prose, alternatives, or tool-ish separators; for album/entity checks
    # the safest test query is the exact title + exact owner query.
    if precise_queries:
        return normalize_fact_check_queries(precise_queries)

    return normalize_fact_check_queries(llm_queries)


def build_fact_check_plan_system_prompt() -> str:
    return """You are JIN's background fact-check search planner.
Your job is to convert one memory line into exactly ONE precise web search query.
Output strict JSON only. No markdown. No prose outside JSON.

Hard rules:
- Return exactly one item in search_queries.
- Never join alternatives with |, OR, commas, semicolons, or newlines.
- Do not search the whole memory sentence literally.
- Do not include helper words from memory such as JIN, recommended, suggested, best, strong choice, trace, confirmed, user_request, or jin_recommendation unless they are the actual entity being checked.
- Extract the smallest factual core that can be checked on the web.
- For recommendation lines, verify the concrete factual entity, not taste or quality.
- If the line says JIN recommended an album/book/tool, check whether that exact item exists and belongs to the named artist/author/vendor.
- Use context from the memory snapshot to recover missing entities, such as artist names and titles.
- If the checked line is a JIN recommendation with a description, do not quote the description. Extract only the item title from the checked line or last_jin_response.
- Never include adjectives, reasons, or explanation phrases like "was suggested", "most balanced", "deep album", "covering textures", or parenthesized descriptions in search_queries.
- The query must be short and targeted, without quote characters.
- For a music album, use this exact shape: Album Title Artist Name album

Good examples:
- Rounds Four Tet album
- This Is Music Four Tet album
- Rathole Four Tet album

Bad examples:
- "Suggested Rounds as a strong starting point"
- "Rahn (described as a balance of complexity and pleasant sound)."
- Images of You was suggested as the most balanced and deep album Four Tet album
- Rounds Four Tet album | Four Tet discography
- Rusk Four Tet. jin album

Return JSON:
{
  "claim": "short factual claim being checked",
  "search_queries": ["one exact query only"],
  "check_instructions": "what the judge must verify",
  "expected_evidence": "what would count as confirmation"
}
""".strip()


def build_fact_check_plan_user_prompt(
        *,
        candidate: FactCheckCandidate,
        memory_snapshot: str,
) -> str:
    return "\n\n".join([
        "Memory snapshot:",
        memory_snapshot or "<empty>",
        "Checked memory line:",
        candidate.line,
        "Parsed key:",
        candidate.key,
        "Parsed value:",
        candidate.value,
        "Task:",
        "Build exactly one targeted web search query for checking this memory fact.",
    ])


def normalize_fact_check_plan(
        payload: dict,
        *,
        candidate: FactCheckCandidate,
        memory_snapshot: str = "",
        raw_response: str = "",
) -> FactCheckPlan:
    claim = str(
        payload.get("claim")
        or candidate.value
        or candidate.line
        or ""
    ).strip()

    queries = payload.get("search_queries")

    if isinstance(queries, str):
        queries = [queries]

    if not isinstance(queries, list):
        queries = []

    precise_queries, structured_claim = build_structured_query_hints(
        candidate=candidate,
        memory_snapshot=memory_snapshot,
        claim=claim,
    )
    queries = merge_precise_queries(
        precise_queries=precise_queries,
        llm_queries=[str(item) for item in queries],
    )

    if structured_claim and structured_claim.get("type") == "music_album":
        claim = (
            f"{structured_claim.get('title')} is an album by "
            f"{structured_claim.get('artist')}"
        )

    if not queries:
        queries = [build_fact_check_query(candidate)]

    return FactCheckPlan(
        claim=claim,
        search_queries=queries,
        check_instructions=str(
            payload.get("check_instructions")
            or "Check whether the factual core of the memory line is supported by the web results."
        ).strip(),
        expected_evidence=str(
            payload.get("expected_evidence")
            or "A reliable result that contains the checked entity and its owner/context."
        ).strip(),
        raw_response=raw_response,
        structured_claim=structured_claim,
    )


async def ask_fact_check_plan(
        *,
        context,
        candidate: FactCheckCandidate,
        memory_snapshot: str,
) -> FactCheckPlan:
    service_client = get_fact_check_service_client(context)

    if service_client is None:
        return normalize_fact_check_plan(
            {},
            candidate=candidate,
            memory_snapshot=memory_snapshot,
            raw_response="<no service client; fallback query used>",
        )

    response = await ask_service_model(
        client=service_client,
        system_prompt=build_fact_check_plan_system_prompt(),
        user_prompt=build_fact_check_plan_user_prompt(
            candidate=candidate,
            memory_snapshot=memory_snapshot,
        ),
        temperature=FACT_CHECK_LLM_TEMPERATURE,
        max_tokens=FACT_CHECK_PLANNER_MAX_TOKENS,
        timeout=config.SERVICE_REQUEST_TIMEOUT,
    )
    raw_text = extract_model_text(response)

    return normalize_fact_check_plan(
        extract_json_object(raw_text),
        candidate=candidate,
        memory_snapshot=memory_snapshot,
        raw_response=raw_text,
    )


async def run_fact_check_search_plan(
        *,
        context,
        plan: FactCheckPlan,
) -> tuple[list[dict], list[dict], str | None]:
    all_results = []
    searches = []
    provider_error = None

    for query in plan.search_queries[:FACT_CHECK_QUERY_MAX]:
        try:
            results = await run_search_provider(
                query=query,
                context=context,
            )
            result_summaries = summarize_search_results(
                results,
                limit=FACT_CHECK_SEARCH_RESULTS_PER_QUERY,
            )
            searches.append({
                "query": query,
                "results": result_summaries,
                "error": None,
            })
            all_results.extend(result_summaries)
        except Exception as error:
            error_text = repr(error)
            provider_error = error_text
            searches.append({
                "query": query,
                "results": [],
                "error": error_text,
            })

    return all_results, searches, provider_error


def build_fact_check_judge_system_prompt() -> str:
    return """You are JIN's background web fact-check judge.
Output strict JSON only. No markdown. No prose outside JSON.

Statuses:
- "web": web results confirm the factual claim.
- "fail": the check did not confirm the claim. Use this for search/provider failures, ambiguous evidence, no usable results, or targeted searches that simply did not find the claimed entity.

Rules:
- For recommendations, judge only the factual entity, not whether it is a good recommendation.
- Example: "JIN recommended album X by Artist Y" checks whether album X exists and belongs to Artist Y.
- Do not require every word from the original memory line to appear. Use semantic judgement.
- Ignore unrelated search noise, social posts, and results about another artist/entity.
- If exact title + artist are found together in a relevant result, return "web".
- If targeted exact-title/exact-artist searches ran successfully and no result connects that title to that artist, return "fail".
- Do not create a separate "no" verdict merely because some unrelated result contains words like "not found".

Return JSON:
{
  "status": "web|fail",
  "reasoning": "short explanation",
  "supporting_evidence": "specific result title/source/quote used, or why none worked"
}
""".strip()


def build_fact_check_judge_user_prompt(
        *,
        candidate: FactCheckCandidate,
        plan: FactCheckPlan,
        searches: list[dict],
) -> str:
    return "\n\n".join([
        "Original memory line:",
        candidate.line,
        "Factual claim to check:",
        plan.claim,
        "Planner check instructions:",
        plan.check_instructions,
        "Expected confirming evidence:",
        plan.expected_evidence,
        "Executed web searches and results:",
        json.dumps(searches, ensure_ascii=False, indent=2),
        "Task:",
        "Decide whether the factual claim is confirmed by web, contradicted/not found by web, or failed.",
    ])


def normalize_fact_check_decision(
        payload: dict,
        *,
        fallback_status: str,
        raw_response: str = "",
) -> FactCheckDecision:
    status = str(
        payload.get("status")
        or fallback_status
        or "fail"
    ).strip().lower()

    if status == "no":
        status = "fail"

    if status not in FACT_CHECK_STATUSES:
        status = fallback_status if fallback_status in FACT_CHECK_STATUSES else "fail"

    return FactCheckDecision(
        status=status,
        reasoning=str(
            payload.get("reasoning")
            or "No model reasoning returned."
        ).strip(),
        supporting_evidence=str(
            payload.get("supporting_evidence")
            or ""
        ).strip(),
        raw_response=raw_response,
    )


def normalize_evidence_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).casefold()


def result_contains_phrase(result: dict, phrase: str) -> bool:
    haystack = normalize_evidence_text(
        " ".join(
            str(result.get(field, "") or "")
            for field in ("title", "source", "url", "quote", "excerpt")
        )
    )
    return normalize_evidence_text(phrase) in haystack


def result_title_contains_phrase(result: dict, phrase: str) -> bool:
    title_text = normalize_evidence_text(result.get("title", "") or "")
    return normalize_evidence_text(phrase) in title_text


def result_has_album_context(result: dict) -> bool:
    haystack = normalize_evidence_text(
        " ".join(
            str(result.get(field, "") or "")
            for field in ("title", "source", "url", "quote", "excerpt")
        )
    )
    return any(
        marker in haystack
        for marker in (
            " album",
            "albums",
            "discography",
            "release",
            "released",
            "tracklist",
            "lp",
            "ep",
        )
    )


def result_confirms_music_album(result: dict, *, title: str, artist: str) -> bool:
    # A generic artist page or random social/news result can contain both words
    # without proving that the checked title is an album by that artist. For an
    # album claim, require the checked title to be part of the result title and
    # require either the artist in the title too, or clear album/release context
    # elsewhere in the result. This prevents false positives like:
    #   query: "Rusk" "Four Tet" album
    #   result title: "Four Tet - Apple Music"
    # where the page can mention many tracks but does not prove an album named
    # Rusk exists.
    if not result_contains_phrase(result, title):
        return False

    if not result_contains_phrase(result, artist):
        return False

    title_has_album = result_title_contains_phrase(result, title)
    title_has_artist = result_title_contains_phrase(result, artist)

    if title_has_album and title_has_artist:
        return True

    if title_has_album and result_has_album_context(result):
        return True

    return False


def classify_structured_music_album_evidence(
        *,
        plan: FactCheckPlan,
        searches: list[dict],
        provider_error: str | None,
) -> FactCheckDecision | None:
    structured_claim = plan.structured_claim or {}

    if structured_claim.get("type") != "music_album":
        return None

    title = str(structured_claim.get("title") or "").strip()
    artist = str(structured_claim.get("artist") or "").strip()

    if not title or not artist:
        return None

    all_results = [
        result
        for search in searches
        for result in (search.get("results") or [])
    ]

    for result in all_results:
        if result_confirms_music_album(
                result,
                title=title,
                artist=artist,
        ):
            title_text = result.get("title") or "untitled"
            source_text = result.get("source") or result.get("url") or "unknown source"
            return FactCheckDecision(
                status="web",
                reasoning=(
                    f"Structured album check confirmed album title {title!r} "
                    f"with artist {artist!r} in a result title/release context."
                ),
                supporting_evidence=f"{title_text} — {source_text}",
                raw_response="<structured strict album evidence override>",
            )

    if provider_error and not all_results:
        return FactCheckDecision(
            status="fail",
            reasoning=(
                "Structured album check could not run: the search provider "
                "failed before returning usable results."
            ),
            supporting_evidence=provider_error,
            raw_response="<structured album check failed>",
        )

    if searches:
        return FactCheckDecision(
            status="fail",
            reasoning=(
                f"Structured album check did not find any result connecting "
                f"exact title {title!r} with artist {artist!r}. Unrelated "
                "results were ignored."
            ),
            supporting_evidence="No top result contained both exact title and exact artist.",
            raw_response="<structured exact album not found>",
        )

    return None


def reconcile_fact_check_decision(
        *,
        plan: FactCheckPlan,
        searches: list[dict],
        provider_error: str | None,
        decision: FactCheckDecision,
) -> FactCheckDecision:
    structured_decision = classify_structured_music_album_evidence(
        plan=plan,
        searches=searches,
        provider_error=provider_error,
    )

    if structured_decision is None:
        return decision

    # Exact positive evidence is stronger than any judge uncertainty.
    if structured_decision.status == "web":
        return structured_decision

    # For structured album claims, code-level evidence is stricter than the
    # generic LLM/token judge. If the strict album check fails to confirm,
    # do not let a loose result containing both words upgrade it to web.
    return structured_decision


async def ask_fact_check_decision(
        *,
        context,
        candidate: FactCheckCandidate,
        plan: FactCheckPlan,
        searches: list[dict],
        provider_error: str | None,
) -> FactCheckDecision:
    if provider_error and not any((search.get("results") or []) for search in searches):
        return FactCheckDecision(
            status="fail",
            reasoning=(
                "Search provider failed before usable evidence was collected; "
                "the worker cannot confirm or reject the claim."
            ),
            supporting_evidence=provider_error,
            raw_response="<judge skipped because search provider failed>",
        )

    service_client = get_fact_check_service_client(context)
    fallback_status = "fail" if provider_error else classify_fact_search_results(
        candidate,
        [result for search in searches for result in (search.get("results") or [])],
    )

    if service_client is None:
        return reconcile_fact_check_decision(
            plan=plan,
            searches=searches,
            provider_error=provider_error,
            decision=FactCheckDecision(
                status=fallback_status,
                reasoning="No service client was available; fallback token classifier was used.",
                supporting_evidence="",
                raw_response="<no service client; fallback classifier used>",
            ),
        )

    response = await ask_service_model(
        client=service_client,
        system_prompt=build_fact_check_judge_system_prompt(),
        user_prompt=build_fact_check_judge_user_prompt(
            candidate=candidate,
            plan=plan,
            searches=searches,
        ),
        temperature=FACT_CHECK_LLM_TEMPERATURE,
        max_tokens=FACT_CHECK_JUDGE_MAX_TOKENS,
        timeout=config.SERVICE_REQUEST_TIMEOUT,
    )
    raw_text = extract_model_text(response)

    decision = normalize_fact_check_decision(
        extract_json_object(raw_text),
        fallback_status=fallback_status,
        raw_response=raw_text,
    )

    return reconcile_fact_check_decision(
        plan=plan,
        searches=searches,
        provider_error=provider_error,
        decision=decision,
    )


async def run_llm_fact_check_candidate(
        *,
        context,
        candidate: FactCheckCandidate,
        memory_snapshot: str,
) -> dict:
    plan = await ask_fact_check_plan(
        context=context,
        candidate=candidate,
        memory_snapshot=memory_snapshot,
    )
    results, searches, provider_error = await run_fact_check_search_plan(
        context=context,
        plan=plan,
    )
    decision = await ask_fact_check_decision(
        context=context,
        candidate=candidate,
        plan=plan,
        searches=searches,
        provider_error=provider_error,
    )

    query = plan.search_queries[0] if plan.search_queries else ""

    return {
        "query": query,
        "status": decision.status,
        "results": results,
        "searches": searches,
        "provider_error": provider_error,
        "claim": plan.claim,
        "plan": {
            "claim": plan.claim,
            "search_queries": plan.search_queries,
            "check_instructions": plan.check_instructions,
            "expected_evidence": plan.expected_evidence,
            "raw_response": plan.raw_response,
            "structured_claim": plan.structured_claim,
        },
        "reasoning": build_llm_fact_check_reasoning(
            candidate=candidate,
            plan=plan,
            decision=decision,
            searches=searches,
            provider_error=provider_error,
        ),
        "decision": {
            "status": decision.status,
            "reasoning": decision.reasoning,
            "supporting_evidence": decision.supporting_evidence,
            "raw_response": decision.raw_response,
        },
    }


def build_llm_fact_check_reasoning(
        *,
        candidate: FactCheckCandidate,
        plan: FactCheckPlan,
        decision: FactCheckDecision,
        searches: list[dict],
        provider_error: str | None,
) -> str:
    query = plan.search_queries[0] if plan.search_queries else ""

    lines = [
        f"checked_line={candidate.line!r}",
        f"claim={plan.claim!r}",
        f"query={query!r}",
        f"status={decision.status!r}",
        f"planner_instructions={plan.check_instructions!r}",
        f"expected_evidence={plan.expected_evidence!r}",
        f"structured_claim={plan.structured_claim!r}",
        f"judge_reasoning={decision.reasoning!r}",
    ]

    if decision.supporting_evidence:
        lines.append(
            f"supporting_evidence={decision.supporting_evidence!r}"
        )

    if provider_error:
        lines.append(
            f"provider_error={provider_error!r}"
        )

    lines.append(
        "search_result_counts="
        + repr([
            {
                "query": search.get("query"),
                "count": len(search.get("results") or []),
                "error": search.get("error"),
            }
            for search in searches
        ])
    )

    return "\n".join(lines)


def build_fact_check_query(candidate: FactCheckCandidate) -> str:
    claim = " ".join(candidate.value.split())

    if len(claim) > 160:
        claim = claim[:160].rstrip()

    return f'"{claim}"'


def tokenize_for_match(text: str) -> set[str]:
    return {
        token.casefold()
        for token in TOKEN_RE.findall(text or "")
        if token.casefold() not in {"the", "and", "или", "что", "это"}
    }


def combine_search_result_text(results: list[dict]) -> str:
    return "\n".join(
        " ".join(
            str(item.get(field, "") or "")
            for field in ("title", "source", "url", "quote", "excerpt")
        )
        for item in results[:5]
    )


def classify_fact_search_results(
        candidate: FactCheckCandidate,
        results: list[dict],
) -> str:
    if not results:
        return "fail"

    claim_tokens = tokenize_for_match(candidate.value)

    if not claim_tokens:
        return "fail"

    combined = combine_search_result_text(
        results
    )
    normalized_combined = combined.casefold()

    if any(marker in normalized_combined for marker in NEGATIVE_WEB_MARKERS):
        return "fail"

    found_tokens = tokenize_for_match(combined)
    overlap = claim_tokens & found_tokens
    required = max(2, min(len(claim_tokens), round(len(claim_tokens) * 0.6)))

    if len(overlap) >= required:
        return "web"

    return "fail"


def summarize_search_results(results: list[dict], *, limit: int = 5) -> list[dict]:
    summaries = []

    for item in (results or [])[:limit]:
        summaries.append({
            "title": str(item.get("title", "") or ""),
            "source": str(item.get("source", "") or ""),
            "url": str(item.get("url", "") or ""),
            "quote": str(item.get("quote", "") or ""),
            "excerpt": str(item.get("excerpt", "") or ""),
        })

    return summaries


def build_fact_check_reasoning(
        candidate: FactCheckCandidate,
        *,
        query: str,
        results: list[dict],
        status: str,
) -> str:
    claim_tokens = tokenize_for_match(
        candidate.value
    )
    combined = combine_search_result_text(
        results
    )
    found_tokens = tokenize_for_match(
        combined
    )
    overlap = sorted(
        claim_tokens & found_tokens
    )
    required = (
        max(2, min(len(claim_tokens), round(len(claim_tokens) * 0.6)))
        if claim_tokens
        else 0
    )

    if status == "web":
        verdict = (
            "web confirmation accepted: enough claim tokens were found "
            "in the first search results."
        )
    else:
        verdict = (
            "web confirmation failed: no reliable enough overlap was found, "
            "or the provider returned no usable results."
        )

    return (
        f"checked_line={candidate.line!r}\n"
        f"query={query!r}\n"
        f"status={status!r}\n"
        f"claim_tokens={sorted(claim_tokens)}\n"
        f"matched_tokens={overlap}\n"
        f"required_matches={required}\n"
        f"verdict={verdict}"
    )


def format_fact_check_status(status: str, *, provider_error: str | None = None) -> tuple[str, str]:
    normalized = str(status or "fail").lower()

    if normalized == "web":
        return "CONFIRMED BY WEB", "OK"

    if provider_error:
        return "CHECK FAILED", "ERROR"

    return "CHECK FAILED", "PENDING"


def get_fact_check_explanation(check: dict) -> str:
    decision = check.get("decision") or {}
    reasoning = str(decision.get("reasoning") or "").strip()

    if reasoning:
        return reasoning

    status = str(check.get("status", "fail") or "fail")
    provider_error = check.get("provider_error")
    result_count = len(check.get("results") or [])

    if status == "web":
        return "Web evidence confirmed the factual core of the checked memory line."

    if provider_error:
        return "The search provider raised an error; this is not a factual contradiction."

    if result_count == 0:
        return "The search provider returned no usable results; the claim remains unconfirmed."

    return "Search results existed, but they were not strong enough to confirm the checked claim."


def get_fact_check_evidence(check: dict) -> str:
    decision = check.get("decision") or {}
    supporting_evidence = str(decision.get("supporting_evidence") or "").strip()

    if supporting_evidence:
        return supporting_evidence

    results = check.get("results") or []
    if not results:
        return "<no supporting evidence>"

    first_result = results[0]
    title = first_result.get("title") or "<untitled>"
    source = first_result.get("source") or first_result.get("url") or "<unknown source>"
    return f"{title} — {source}"


def format_fact_check_summary(checks: list[dict]) -> list[str]:
    confirmed = sum(1 for check in checks if check.get("status") == "web")
    failed = len(checks) - confirmed
    changed = sum(1 for check in checks if check.get("changed"))

    return [
        f"Checks executed : {len(checks)}",
        f"Confirmed       : {confirmed}",
        f"Failed/pending  : {failed}",
        f"Memory writes   : {changed}",
    ]


def format_search_return_summary(check: dict) -> list[str]:
    searches = check.get("searches") or []

    if not searches:
        return ["Search provider returned: <no search call recorded>"]

    lines = ["Search provider returned:"]

    for index, search in enumerate(searches, start=1):
        query = search.get("query") or ""
        error = search.get("error")
        results = search.get("results") or []

        lines.append(f"  Search #{index}: {query}")

        if error:
            lines.append(f"    error: {error}")
            continue

        if not results:
            lines.append("    results: <empty list>")
            continue

        lines.append(f"    results: {len(results)}")
        for result_index, result in enumerate(results[:5], start=1):
            title = result.get("title") or "untitled"
            source = result.get("source") or result.get("url") or "unknown source"
            url = result.get("url") or ""
            lines.append(f"    {result_index}. {title} — {source}")
            if url:
                lines.append(f"       {url}")

    return lines


def build_fact_check_report(checks: list[dict]) -> str:
    if not checks:
        return "FACT CHECK REPORT\n=================\n\nNo checks were executed."

    lines = [
        "FACT CHECK REPORT",
        "=================",
        "",
        *format_fact_check_summary(checks),
    ]

    for index, check in enumerate(checks, start=1):
        status = str(check.get("status", "fail") or "fail")
        provider_error = check.get("provider_error")
        verdict, badge = format_fact_check_status(
            status,
            provider_error=provider_error,
        )
        changed = "yes" if check.get("changed") else "no"
        results = check.get("results") or []
        result_count = len(results)
        explanation = get_fact_check_explanation(check)
        evidence = get_fact_check_evidence(check)

        lines.extend([
            "",
            "-" * 72,
            f"#{index} [{badge}] {verdict}",
            "-" * 72,
            f"Layer/key          : {check.get('layer')} / {check.get('key')}",
            f"Memory line changed: {changed}",
            f"Status written     : {status}",
            f"Search results used: {result_count}",
            "",
            "Checked line:",
            indent_text(str(check.get("line") or "")),
            "",
            "Extracted claim:",
            indent_text(str(check.get("claim") or check.get("value") or "")),
            "",
            "Search query:",
            indent_text(str(check.get("query") or "")),
            "",
            "Evidence:",
            indent_text(evidence),
            "",
            "Why:",
            indent_text(explanation),
        ])

        if provider_error:
            lines.extend([
                "",
                "Provider error:",
                indent_text(str(provider_error)),
            ])

        lines.extend([
            "",
            *format_search_return_summary(check),
        ])

    return "\n".join(lines)





def indent_text(text: str, *, prefix: str = "  ") -> str:
    if not text:
        return f"{prefix}<empty>"

    return "\n".join(
        f"{prefix}{line}" if line else ""
        for line in str(text).splitlines()
    )


def format_search_results_for_payload(results: list[dict]) -> str:
    if not results:
        return "  <no search results>"

    lines = []

    for index, result in enumerate(results, start=1):
        title = result.get("title") or "<untitled>"
        source = result.get("source") or result.get("url") or "<unknown source>"
        url = result.get("url") or ""
        quote = result.get("quote") or result.get("excerpt") or ""

        lines.append(f"  {index}. {title}")
        lines.append(f"     source: {source}")

        if url:
            lines.append(f"     url: {url}")

        if quote:
            lines.append("     excerpt:")
            lines.append(indent_text(quote, prefix="       "))

    return "\n".join(lines)


def build_fact_check_details_text(
        *,
        checks: list[dict],
        memory_snapshots: dict[str, str],
        runtime_memory: str,
        runtime_l2_memory: str,
) -> str:
    sections = [
        build_fact_check_report(checks),
        "",
        "=== MEMORY SNAPSHOT BEFORE CHECK ===",
        "",
        "L1:",
        indent_text(memory_snapshots.get("L1", "")),
        "",
        "L2:",
        indent_text(memory_snapshots.get("L2", "")),
        "",
        "=== CHECK DETAILS ===",
    ]

    if not checks:
        sections.append("  <no checks>")

    for index, check in enumerate(checks, start=1):
        verdict, badge = format_fact_check_status(
            str(check.get("status") or "fail"),
            provider_error=check.get("provider_error"),
        )
        sections.extend([
            "",
            f"--- CHECK #{index}: [{badge}] {verdict} / {check.get('layer')} / {check.get('key')} ---",
            f"status: {check.get('status')}",
            f"changed: {check.get('changed')}",
            "",
            "checked line:",
            indent_text(str(check.get("line") or "")),
            "",
            "search query:",
            indent_text(str(check.get("query") or "")),
            "",
            "llm extracted claim:",
            indent_text(str(check.get("claim") or check.get("value") or "")),
            "",
            "llm plan:",
            indent_text(json.dumps(check.get("plan") or {}, ensure_ascii=False, indent=2)),
            "",
            "searches executed:",
            indent_text(json.dumps(check.get("searches") or [], ensure_ascii=False, indent=2)),
            "",
            "search results:",
            format_search_results_for_payload(check.get("results") or []),
            "",
            "llm decision:",
            indent_text(json.dumps(check.get("decision") or {}, ensure_ascii=False, indent=2)),
            "",
            "worker reasoning:",
            indent_text(str(check.get("reasoning") or "")),
        ])

        provider_error = check.get("provider_error")
        if provider_error:
            sections.extend([
                "",
                "provider error:",
                indent_text(str(provider_error)),
            ])

    sections.extend([
        "",
        "=== MEMORY AFTER CHECK ===",
        "",
        "L1:",
        indent_text(runtime_memory),
        "",
        "L2:",
        indent_text(runtime_l2_memory),
        "",
        "=== RAW JSON ===",
        json.dumps(
            {
                "memory_snapshot_before_check": memory_snapshots,
                "checks": checks,
                "runtime_memory_after": runtime_memory,
                "runtime_l2_memory_after": runtime_l2_memory,
            },
            ensure_ascii=False,
            indent=2,
        ),
    ])

    return "\n".join(sections)


def build_fact_check_payload(
        *,
        checks: list[dict],
        memory_snapshots: dict[str, str],
        runtime_memory: str,
        runtime_l2_memory: str,
) -> str:
    # Keep the modal human-readable first. The UI displays details as plain text,
    # so JSON with escaped newlines makes the context almost impossible to read.
    # Raw JSON is still appended at the bottom for debugging/copying.
    return build_fact_check_details_text(
        checks=checks,
        memory_snapshots=memory_snapshots,
        runtime_memory=runtime_memory,
        runtime_l2_memory=runtime_l2_memory,
    )


def line_matches_candidate(
        line: str,
        candidate: FactCheckCandidate,
) -> bool:
    parsed = parse_memory_line(line)

    if parsed is None:
        return False

    key, value = parsed

    if normalize_key(key) != normalize_key(candidate.key):
        return False

    if has_successful_web_confirmation(line):
        return False

    candidate_value = strip_confirmation_suffix(candidate.value).casefold()
    line_value = strip_confirmation_suffix(value).casefold()

    if not candidate_value:
        return True

    return (
        candidate_value in line_value
        or line_value in candidate_value
        or tokenize_for_match(candidate_value) <= tokenize_for_match(line_value)
    )


def find_candidate_line_index(
        lines: list[str],
        candidate: FactCheckCandidate,
) -> int | None:
    if (
            0 <= candidate.line_index < len(lines)
            and line_matches_candidate(
                lines[candidate.line_index],
                candidate,
            )
    ):
        return candidate.line_index

    for index, line in enumerate(lines):
        if line.strip() == candidate.line.strip():
            return index

    for index, line in enumerate(lines):
        if line_matches_candidate(line, candidate):
            return index

    return None


def apply_fact_check_result_to_memory(
        memory: str,
        candidate: FactCheckCandidate,
        status: str,
) -> str:
    lines = (memory or "").splitlines()
    line_index = find_candidate_line_index(
        lines,
        candidate,
    )

    if line_index is None:
        return memory

    source = "web" if status == "web" else None
    web_status = status if status in {"no", "fail"} else None
    lines[line_index] = add_or_update_confirmation(
        lines[line_index],
        source=source,
        web_status=web_status,
    )

    return "\n".join(lines).strip()


def cancel_idle_fact_check(context) -> None:
    """Compatibility no-op.

    Background/idle fact-checking was removed: fact-checks must be
    started explicitly by the UI click path. Keep this function so old
    callers/imports do not crash while no task can remain scheduled.
    """
    context.fact_check_idle_task = None


def schedule_idle_fact_check(
        context,
        *,
        delay_seconds: float | None = None,
):
    """Compatibility no-op for the removed idle fact-check scheduler."""
    cancel_idle_fact_check(context)
    return None


async def emit_fact_check_state(
        context,
        *,
        active: bool,
        reason: str,
) -> None:
    emitter = getattr(context, "emitter", None)
    emit = getattr(emitter, "emit", None)

    if emit is None:
        return

    await emit({
        "type": "fact_check_state",
        "active": bool(active),
        "reason": reason,
    })


async def wait_for_runtime_memory_update(context) -> None:
    task = getattr(context, "runtime_memory_update_task", None)

    if task is None:
        return

    await task


async def run_fact_check_once(
        context,
        *,
        max_checks: int = FACT_CHECK_MAX_CANDIDATES_PER_RUN,
        reason: str = "manual",
) -> list[dict]:
    await emit_fact_check_state(
        context,
        active=True,
        reason=reason,
    )

    try:
        checks = []
        changed_layers = set()
        checks_remaining = max(1, int(max_checks or FACT_CHECK_MAX_CANDIDATES_PER_RUN))
        memory_snapshots = {
            "L1": getattr(context, "runtime_memory", ""),
            "L2": getattr(context, "runtime_l2_memory", ""),
        }
        l1_memory_before = getattr(
            context,
            "runtime_memory",
            "",
        )

        for layer, attr in (
                ("L1", "runtime_memory"),
                ("L2", "runtime_l2_memory"),
        ):
            memory = getattr(context, attr, "")
            candidates = extract_fact_check_candidates(
                memory,
                layer=layer,
            )

            for candidate in candidates:
                if checks_remaining <= 0:
                    break

                fact_check = await run_llm_fact_check_candidate(
                    context=context,
                    candidate=candidate,
                    memory_snapshot=memory_snapshots.get(layer, ""),
                )
                query = fact_check["query"]
                status = fact_check["status"]
                results = fact_check["results"]
                provider_error = fact_check["provider_error"]

                current_memory = getattr(context, attr, "")
                updated_memory = apply_fact_check_result_to_memory(
                    current_memory,
                    candidate,
                    status,
                )
                changed = updated_memory != current_memory

                if changed:
                    setattr(context, attr, updated_memory)
                    changed_layers.add(layer)

                checks.append({
                    "reason": reason,
                    "layer": layer,
                    "key": candidate.key,
                    "value": candidate.value,
                    "line": candidate.line,
                    "memory_snapshot": memory_snapshots.get(layer, ""),
                    "query": query,
                    "status": status,
                    "changed": changed,
                    "claim": fact_check.get("claim", ""),
                    "plan": fact_check.get("plan", {}),
                    "searches": fact_check.get("searches", []),
                    "results": results,
                    "provider_error": provider_error,
                    "reasoning": fact_check.get("reasoning", ""),
                    "decision": fact_check.get("decision", {}),
                })
                checks_remaining -= 1

            if checks_remaining <= 0:
                break

        l1_memory_after = getattr(
            context,
            "runtime_memory",
            "",
        )
        l1_memory_changed = (
            "L1" in changed_layers
            or l1_memory_after != l1_memory_before
        )

        if checks:
            context.runtime_memory_stable = l1_memory_after

            emitter = getattr(context, "emitter", None)
            emit = getattr(emitter, "emit", None)

            if emit is not None:
                await emit({
                    "type": "fact_check_update",
                    "checks": checks,
                    "runtime_memory": l1_memory_after,
                    "runtime_l2_memory": getattr(context, "runtime_l2_memory", ""),
                })

            if l1_memory_changed:
                context.runtime_memory_updates = (
                    int(getattr(context, "runtime_memory_updates", 0) or 0)
                    + 1
                )

                # Emit a real runtime snapshot, not a snapshot=None event.
                # The frontend renders the right memory panel from snapshot history;
                # a raw memory payload alone is intentionally ignored by the panel.
                from runtime.memory import emit_runtime_memory_update

                await emit_runtime_memory_update(
                    context
                )

        logger = getattr(context, "logger", None)
        log_service = getattr(logger, "log_service", None)

        if checks and logger is not None:
            changed_count = sum(
                1
                for check in checks
                if check.get("changed")
            )
            statuses = ", ".join(
                f"{check.get('layer')}:{check.get('key')}={check.get('status')}"
                for check in checks
            )
            message = (
                f"[FACT_CHECK] {reason} web check completed "
                f"({changed_count}/{len(checks)} changed; {statuses})"
            )
            details = build_fact_check_payload(
                checks=checks,
                memory_snapshots=memory_snapshots,
                runtime_memory=getattr(context, "runtime_memory", ""),
                runtime_l2_memory=getattr(context, "runtime_l2_memory", ""),
            )
            log = getattr(logger, "log", None)

            if log is not None:
                await log(
                    "[MEMORY:FACT_CHECK]",
                    message,
                    details=details,
                    channel="memory",
                    memory_level="FACT_CHECK",
                    memory_event="fact_check",
                )
            elif log_service is not None:
                await log_service(
                    message
                )

        return checks
    finally:
        await emit_fact_check_state(
            context,
            active=False,
            reason=reason,
        )
