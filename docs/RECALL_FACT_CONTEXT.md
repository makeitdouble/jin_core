# RECALL_FACT_CONTEXT

`<RECALL_FACT_CONTEXT: F123>` reads saved historical evidence through the ordinary
contract/parser/dispatcher/tool-result/follow-up path. Several markers are allowed.
Historical text is escaped in TOOL_RESULT, never applied as current FRAME,
loaded resources, or executable actions. CLEAN_TOOL_RESULTS owns its lifetime.

## Provenance

L-T `sources` is backend-owned and survives normalize, merge, rebase, browser
storage, restore and value edits. Sources are deduplicated episode identities:

- FRAME extraction: `{session_id, runtime_snapshot_id}` from selected intake
  fields. An unchanged field retains its previous snapshot identity.
- Explicit UPDATE_LT_FACTS: `{session_id, turn_id}`, captured before scheduling
  the background job. The model cannot provide those identities.

The existing FRAME archive now records the actual summarized `source_turn_ids`
and whether that list is complete. A single proven turn has an anchor; a batch
is labelled `frame_episode`, never falsely attributed to one message. Direct
turn sources do not claim to have a FRAME. Recall selects the anchor USER row
and its immediately adjacent dialogue rows, staying within that session. Batch
windows are combined without duplicating rows. Text is returned whole.

Legacy facts with no saved `sources` use a read-only compatibility bridge. Exact
old `UPDATE_LT_FACTS` runtime results are matched by `fact_id` and recover their
original turn. Otherwise the fact creation/update time plus a small text-overlap
check can select a nearby legacy FRAME archive; its old numeric `turn` header is resolved back
to the exact saved USER turn when that mapping is unique. This fallback never writes
provenance back into L-T and is used only when normal backend-owned `sources` are
missing. Missing, ambiguous or low-confidence evidence still returns
`source_not_saved`/`source_unavailable`. If logging was disabled, evidence cannot be
recovered.

## Context budget

Recall uses the measured Brain context capacity and occupancy, reserving half
of the free space for generation and follow-up scaffolding. Token cost uses the
existing runtime estimate scale and escaped tool-result text. Unknown capacity
loads no evidence and is reported explicitly. This is an estimate, as elsewhere
in the runtime, not a provider tokenizer guarantee.

Whole sources are admitted; none is silently clipped. Results list deferred
source IDs. Already-loaded sources/messages reference earlier tool results.
After consuming a page, the model can CLEAN_TOOL_RESULTS and recall again;
turn-local delivery progress skips consumed sources. The next real turn starts
new progress. An individual source that still cannot fit remains deferred;
when even the full current fact value cannot fit, its omission is explicit.
The small status/deferred-ID response itself still needs prompt space.

Anonymous rooms resolve only facts in their own current L-T state. Recall is
read-only; it does not hydrate global L-T or enable persistent memory writes.
Dates remain in the existing fact tooltip; it now also shows source count.

## Verification

- `python -m unittest tests.test_recall_fact_context -q`
- `node tests/test_recall_fact_context_client.js`
- Existing L-T, tool-result, incomplete-marker and stream-filter tests compared
  against the exact unmodified input archive: the same five pre-existing failures
  in `tests.test_lt_memory` occur on both trees; the other tests pass.
- Python syntax/import checks, JavaScript syntax, diff whitespace and clean
  patch application checked. No live LM Studio conversation was run here.
