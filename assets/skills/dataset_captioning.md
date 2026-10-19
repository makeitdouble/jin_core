# dataset_captioning

Purpose: Inspect a user's image dataset and create or correct short English .txt captions, one image at a time, using JIN's existing actions and automatic FOLLOW-UP ticks. Do not start a separate loop or invent tools.

## Caption

Write ONE short line: who is pictured, distinctive visible features, clothing and its colors, simple pose if useful, and background. Use only visible details. No storytelling, mood, style tags, or long descriptions.

Good:
- photo of a young girl, wearing a white t-shirt and blue jeans, soft gray background
- photo of a girl with brown hair and blue eyes, wearing a red dress, indoors
- close-up photo of a girl with freckles, brown hair, black background

Bad:
- A beautiful girl in an atmospheric cinematic portrait with amazing lighting.
- photo of a young girl, outdoors

## Dataset workflow

1. Read the user's requested number of images (e.g. 100). `directory_link` is automatically present when the folder is linked. Load `file_manager` separately if needed. When the user links a folder, use `project_tree` to list its real filenames. **Paginate with `offset`:** if the result says `More results`, repeat `project_tree` with the next offset, keeping the same attachment/path/depth, until enough image filenames are found (or there are no more results). TXT files also count toward the page limit, so one page of 100 entries may contain fewer than 100 images. Sort image filenames by name and use that order. Match each image to an optional `.txt` with the same basename.
2. Track the dataset folder, requested count, current filename, and completed count in the current task/FRAME. `35/100` means 35 images have been inspected and accepted or successfully saved. Never restart at image 1 on an automatic FOLLOW-UP.
3. For a linked dataset, attach the current image and its existing TXT in one marker: `<ATTACH_FILE_CONTENT: dataset/00036.png, dataset/00036.txt >`. Omit TXT when absent. For files already in the persistent library, use `<ATTACH_FILE_CONTENT: image_id, text_id >` instead. Never mix IDs and paths. WAIT for automatic FOLLOW-UP to inspect the actual pixels and text before describing the image. The next path marker replaces this temporary pair.
4. Read only the first line of an existing TXT; ignore any detailed second line. If the first line accurately describes the image, leave the file unchanged. Otherwise write a replacement caption. When a TXT is missing, create one with the same basename. A created or replaced caption contains exactly one line.
5. Write using `create_asset_file` with `attachment` set to the linked dataset folder and a relative `path` beside the image. Use `overwrite:true` only when the user requested correcting/replacing captions. Omitting attachment writes under assets/ as before. Do not count a save until the action confirms success.
6. After successful write, or after accepting a correct existing caption, increment progress. Attach the next image/pair, causing the next automatic FOLLOW-UP. Repeat until the requested number is complete, then report `N/N` and stop. Failed writes do not count; inspect TOOL_RESULTS and retry/correct before advancing.

## Existing action examples

List files in a linked folder (use the real folder name):

<ASSET_ACTION>
{"action":"project_tree","attachment":"dataset","path":".","offset":0,"limit":100}
</ASSET_ACTION>
If the response says `More results: ... offset 100`, call `project_tree` again with `"offset":100` (then 200, etc., using the actual returned count) until enough images are listed.

Attach a REAL image ID and optional REAL TXT ID shown by `LIST_ALL_USER_SHARED_FILES`:

<ATTACH_FILE_CONTENT: abc123, def456 >

For a linked image and TXT use one `<ATTACH_FILE_CONTENT: dataset/00036.png, dataset/00036.txt >` marker and wait for FOLLOW-UP. Text paths support source windows; images are sent to vision.

Create a caption in the currently linked dataset:

<ASSET_ACTION>
{"action":"create_asset_file","attachment":"dataset","path":"00036.txt","content":"photo of a young girl, wearing a white t-shirt and blue jeans, soft gray background"}
</ASSET_ACTION>

## Hard limits of the existing runtime

- Use BY_PATH only while the dataset folder is attached. Never treat a path as a persistent ID, and never caption an image before receiving its pixels.
- Writes require the explicit attachment selector, remain inside that linked folder, and are blocked in anonymous/shadow mode. Existing captions require explicit overwrite:true and user authorization to replace.
- If the required image cannot be visually attached or the destination cannot be written with an existing loaded action, report that precise limitation and stop. Do not fabricate a completed dataset, invent an action, or repeatedly fail on the same file.

Whole-file alternatives (file_manager required): <ASSET_ACTION> {"action":"ATTACH_FILE_BY_ID","ids":["abc123","def456"]} </ASSET_ACTION> or <ASSET_ACTION> {"action":"ATTACH_FILE_BY_PATH","paths":["dataset/image.png","dataset/caption.txt"]} </ASSET_ACTION>. Use only existing files, omit missing TXT, and wait for FOLLOW-UP. These are JSON operations; the only attachment XML marker is ATTACH_FILE_CONTENT.
