chunk_reader

Purpose:
Read a large attached text document or PDF through JIN's internal iterative loop without placing the whole source in normal chat context. The runtime uses the service model, calculates chunk size from the detected model context window, calls the bundled reader until EOF, and returns the final accumulated result.

When to use:
- The user asks to read, digest, summarize, inspect, compare, or answer a question from a long attached document.
- The normal attachment preview is incomplete or the full source would not fit safely in one model request.
- The user asks to test one or more chunk-reading instruction modes.

Do not use:
- For a short attachment that already fits in the visible attachment context.
- Without a user request to process the attachment.
- For image-only or scanned PDFs unless their text layer is expected to be extractable. The bundled reader does not perform OCR.

Mode files:
- Every Markdown file beside `chunk_reader.py` whose name ends with `-mode.md` is an available reader mode.
- Use the exact filename shown in the appended skill context, for example `plain-mode.md`.
- Adding another `*-mode.md` file automatically makes it available; no Python or runtime changes are required.

Single-mode action:
<ASSET_ACTION>
{"action":"run_document_reader","skill":"chunk_reader","attachment":"optional exact attachment name","mode":"plain-mode.md","question":"the user's concrete request about the document"}
</ASSET_ACTION>

Multi-mode comparison:
<ASSET_ACTION>
{"action":"run_document_reader","skill":"chunk_reader","attachment":"optional exact attachment name","modes":["plain-mode.md","other-mode.md"],"question":"the user's concrete request about the document"}
</ASSET_ACTION>

Attachment selection:
- Omit `attachment` when exactly one compatible attachment exists.
- Otherwise pass the exact attachment name shown in Attached context.
- Supported inputs are text-like attachments and PDFs with an extractable text layer.

Result behavior:
- The runtime handles all chunks internally and returns one final ASSETS tool result.
- After the result arrives, answer the original user request from `result` for one mode or `results` for multiple modes, not from the short attachment preview.
- The progress bubble shows the exact selected mode filename.
- Report extraction warnings honestly. If PDF extraction returns no useful text, say that OCR is required.

Manual reader checks:
- `python chunk_reader.py modes`
- `python chunk_reader.py --source document.pdf info`
- `python chunk_reader.py --source document.pdf read 0 2000`

Generic Python skill execution:
Other explicitly appended directory skills may expose Python entry points through the same ASSET_ACTION marker:
<ASSET_ACTION>
{"action":"run_python_skill","skill":"skill_directory_name","script":"script.py","args":["arg1","$ATTACHMENT"],"attachment":"optional exact attachment name","timeout_seconds":120}
</ASSET_ACTION>

Rules for run_python_skill:
- The script must stay inside `assets/skills/<skill>/` and end in `.py`.
- `$ATTACHMENT` is replaced with a temporary local path containing the selected attachment.
- No shell is used. stdout and stderr are returned as the tool result.
- Use only when the appended skill documents the script contract or the user explicitly requests the test.
