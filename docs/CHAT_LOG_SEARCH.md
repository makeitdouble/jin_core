# Chat log search

`CHAT_LOG_SEARCH` reads the existing `logs/YYYY-MM-DD/session/*.jsonl` archive;
it has no service, index, embedding, dependency or new persistent store.

```text
<CHAT_LOG_SEARCH>{"query":"пицца","source":["user"],"start_date":"2026-09-01","end_date":"2026-09-08","start_time":null,"end_time":null,"max_limit":10}</CHAT_LOG_SEARCH>
<CHAT_LOG_SEARCH>{"has_attachments":true,"start_date":"2026-09-01","end_date":"2026-09-01"}</CHAT_LOG_SEARCH>
```

The canonical schema and model rules live in `contracts/chat_log_search.json`.
At least one search criterion is required: `query` or `has_attachments=true`.
`query` is optional; a string array means OR, with case-insensitive literal
substring matching; there is no stemming, translation or semantic ranking.
`has_attachments=true` is a message predicate: with no `query` it performs a
filter-only search, and with `query` both conditions must match the same message.
Use the conversation's language and wording. `source` accepts `user`, `jin`,
or an array; default is both. Dates are inclusive, and clock bounds apply daily
in the timestamp's recorded timezone. An end minute includes its final second.
Missing bounds are open. Inverted bounds and invalid types fail visibly.

One result is a matching turn within an archive file, containing matching
messages from the requested sources. Results sort by newest matching message.
`utils/chat_log_search.py` owns `CHAT_LOG_SEARCH_DEFAULT_LIMIT = 10` and
`CHAT_LOG_SEARCH_MAX_LIMIT = 50`. Larger requested limits are errors, not silent
clamps. Full matched message text and saved attachment metadata remain intact;
the file need not match the query. File IDs/names are historical evidence, not
a guarantee that the persistent file still exists.

Including JIN also searches saved reasoning for text-only searches, but a reasoning
hit requires a matching USER in that same turn and range. That USER is included
even when `source` is only `jin`. Up to three bounded reasoning excerpts are
returned, never the complete reasoning file. USER-only search never reads
reasoning. Attachment-filtered searches do not read reasoning, so a reasoning-only
hit cannot bypass `has_attachments=true`.
Runtime events and prompt snapshots do not count as chat messages. Legacy
assistant/brain/service rows count as JIN. Missing timestamps are skipped and
reported, never replaced with the current time. For ordering only, legacy naive
timestamps are treated as UTC; their date/clock filters use the saved value.

Other anonymous rooms are excluded. The current anonymous room can search its
own logs and normal history, consistently with read-only durable-context access.
No archive is modified by searching; the ordinary action/result audit is saved.
Malformed rows are counted and skipped; unreadable archives fail the action
instead of masquerading as an empty search. Missing reasoning leaves available
visible-message matches usable. No matches is a successful empty result.

The formatted TOOL_RESULT repeats every effective request field, match count,
`has_more`, timestamps, session/turn IDs, archive location, messages, attachments
and reasoning excerpts. The exact supplied JSON is retained in the result's
`payload` and in failed-action diagnostics. Evidence is escaped in model context.
The shared failure follow-up supplies the error and canonical correction schema.
The existing search icon, action states and hover details render the bubble.
Distinct requests retain separate action identities; counter telemetry preserves
the final label and details.

Results use the existing `runtime_action` tool-result kind and temporary T IDs.
Raw archive restore and browser checkpoint hydration preserve structured results,
including full messages larger than the generic 32K JSON-slicing boundary.
Normal tool-result cleanup and cleared-checkpoint rules still apply. A result
can be large when the matched messages are large; use a smaller `max_limit` or
`CLEAN_TOOL_RESULTS` after consuming the evidence.

Verification: `python -m unittest tests.test_chat_log_search
tests.test_unclosed_runtime_actions tests.test_runtime_tool_result_text -q`.
The browser DOM test is `node tests/test_chat_log_search_client.js` with
Playwright available on `NODE_PATH` and Microsoft Edge installed.
