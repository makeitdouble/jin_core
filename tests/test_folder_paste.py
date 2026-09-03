"""Folder paste must use the normal link/pin path without losing the draft."""
import shutil
import subprocess
import unittest
from pathlib import Path


class FolderPasteTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is required")
    def test_folder_labels_keep_folder_icon_and_original_identity(self):
        script = r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const source = fs.readFileSync(process.argv[1], "utf8");
eval(source.slice(0, source.indexOf("function ensureAttachmentHoverPreview(")));
const folder = {name:"Промпты.jin-folder", kind:"text", size_label:"42 B", id:"abc123"};
assert.equal(getAttachmentName(folder), "Промпты");
assert.equal(getAttachmentChipEmoji(folder), "📁");
assert.equal(formatAttachmentHoverTitle(folder), "Промпты · 42 B");
assert.equal(folder.name, "Промпты.jin-folder");
assert.equal(getAttachmentName({name:"notes.txt"}), "notes.txt");
assert.equal(getAttachmentChipEmoji({name:"notes.txt",kind:"text"}), "📄");
'''
        result = subprocess.run(
            [shutil.which("node"), "-e", script,
             str(Path(__file__).resolve().parents[1] / "ui/static/js/chat-attachments.js")],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    @unittest.skipUnless(shutil.which("node"), "node is required")
    def test_paste_queue_snapshot_sync_and_failed_path_restore(self):
        script = r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const source = fs.readFileSync(process.argv[1], "utf8");
let uploadQueue = Promise.resolve(), calls = [], snapshots = [], renders = 0, syncs = 0;
let reject = false, release;
const fetch = async (url, options) => {
  calls.push({url, path: JSON.parse(options.body).path});
  if (release) await release;
  return {ok: !reject, json: async () => reject ? {detail:"not a directory"} : {pinned_ids:["abc123"]}};
};
const normalizeSnapshot = payload => snapshots.push(payload);
const dispatchStoreChanged = () => renders++;
const syncAttachmentContext = () => syncs++;
eval(source.slice(source.indexOf("async function linkProjectFolder("), source.indexOf("async function setPinned(")));
const input = {
  id:"user-input", value:"inspect this", selectionStart:12, selectionEnd:12,
  setRangeText(text, start, end) { this.value = this.value.slice(0,start) + text + this.value.slice(end); },
  dispatchEvent() {},
};
const paste = text => {
  const event = {target:input, defaultPrevented:false,
    preventDefault() { this.defaultPrevented=true; },
    clipboardData:{getData:type => type === "text/plain" ? text : ""}};
  pasteFolderLink(event);
  return event;
};
(async () => {
  for (const path of ['C:\\Users\\JPG\\Desktop\\jin_core', '"C:\\My projects\\Промпты"',
    'file:///C:/My%20projects/jin_core', '/tmp/project', '~/project', '\\\\server\\share']) {
    assert.ok(paste(path).defaultPrevented, path);
    await uploadQueue;
    assert.equal(input.value, "inspect this");
  }
  assert.equal(calls.length, 6);
  assert.equal(calls[1].path, 'C:\\My projects\\Промпты');
  assert.ok(calls.every(call => call.url === '/api/files/link-folder'));
  assert.equal(renders, 6); assert.equal(syncs, 6);
  assert.deepEqual(snapshots.at(-1).pinned_ids, ['abc123']);
  for (const text of ['ordinary text', 'https://example.com', 'see C:\\project', '/tmp/a\n/tmp/b']) {
    assert.equal(paste(text).defaultPrevented, false);
  }
  input.id='other-field';
  assert.equal(paste('C:\\project').defaultPrevented, false);
  input.id='user-input';
  input.value='before OLD after'; input.selectionStart=7; input.selectionEnd=10;
  reject=true;
  paste('C:\\missing'); await uploadQueue;
  assert.equal(input.value, 'before C:\\missing after');
  input.value='draft'; input.selectionStart=5; input.selectionEnd=5;
  let resume; release = new Promise(resolve => resume=resolve);
  paste('/missing');
  await Promise.resolve();
  input.value='new draft'; input.selectionStart=9; input.selectionEnd=9;
  resume(); await uploadQueue; release=null;
  assert.equal(input.value, 'new draft/missing');
  // A failed link must not poison the queue for the next paste.
  reject=false; paste('/valid'); await uploadQueue;
  assert.equal(syncs, 7);
})().catch(error => { console.error(error); process.exitCode=1; });
'''
        result = subprocess.run(
            [shutil.which("node"), "-e", script,
             str(Path(__file__).resolve().parents[1] / "ui/static/js/dragdrop.js")],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
