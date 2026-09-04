import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("node"), "node is required")
class LTMergeTraceClientTests(unittest.TestCase):
    def test_socket_sequence_clicks_render_structured_and_legacy_traces(self):
        # Exercise the production socket handler, card listeners and modal
        # renderer. The small DOM double omits layout/animation only.
        script = r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class Element {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.dataset = {};
    this.style = {};
    this.attributes = {};
    this.listeners = {};
    this.className = "";
    this.disabled = false;
    this.classList = {
      contains: name => this.className.split(/\s+/).includes(name),
      add: (...names) => {
        this.className = [...new Set(this.className.split(/\s+/).filter(Boolean).concat(names))].join(" ");
      },
      remove: (...names) => {
        this.className = this.className.split(/\s+/).filter(name => !names.includes(name)).join(" ");
      },
      toggle: (name, force) => {
        const present = force === undefined ? !this.classList.contains(name) : force;
        this.classList[present ? "add" : "remove"](name);
        return present;
      },
    };
  }
  set textContent(text) { this._text = String(text); this.children = []; }
  get textContent() { return (this._text || "") + this.children.map(node => node.textContent).join(""); }
  appendChild(node) {
    if (node.parentNode) {
      node.parentNode.children = node.parentNode.children.filter(child => child !== node);
    }
    node.parentNode = this;
    this.children.push(node);
    return node;
  }
  append(...nodes) { nodes.forEach(node => this.appendChild(node)); }
  replaceChildren(...nodes) { this._text = ""; this.children = []; this.append(...nodes); }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, listener) { (this.listeners[name] ||= []).push(listener); }
  click() { if (!this.disabled) (this.listeners.click || []).forEach(listener => listener({target: this})); }
  querySelectorAll(selector) {
    const descendants = this.children.flatMap(child => [child, ...child.querySelectorAll("*")]);
    if (selector === "*") return descendants;
    if (selector.startsWith(".")) return descendants.filter(node => node.classList.contains(selector.slice(1)));
    return [];
  }
  get isConnected() { return this.tagName === "body" || Boolean(this.parentNode?.isConnected); }
}

const body = new Element("body");
const stream = new Element("div");
body.append(stream);
const document = {
  body,
  getElementById: id => id === "console-stream" ? stream : null,
  createElement: tag => new Element(tag),
  createTextNode: text => { const node = new Element("#text"); node.textContent = text; return node; },
  addEventListener() {},
};
const sandbox = {
  assert, document,
  registerSocketMessageHandler() {},
  moveLogToBottomWithFlip: node => stream.appendChild(node),
  cancelAnimationFrame() {},
  setTimeout() {},
};
sandbox.window = sandbox;
sandbox.addEventListener = () => {};
const context = vm.createContext(sandbox);
const root = path.join(process.argv[2], "ui/static/js");
const logger = fs.readFileSync(path.join(root, "logger/logger.js"), "utf8");
// Load the real parsing helpers without unrelated draggable-panel startup.
vm.runInContext(logger.slice(0, logger.indexOf("function parseValidatorLogPayload(")), context);
for (const file of ["logger/trace-modal.js", "logger/log-entries.js", "logger/frame-summarizer.js", "socket/memory.js"]) {
  vm.runInContext(fs.readFileSync(path.join(root, file), "utf8"), context, {filename: file});
}
vm.runInContext(`
const fact = (id, key, value) => ({id, key, value, category: "user_fact"});
const trace = {
  kind: "lt_merge_applied",
  operation_details: [
    {action: "update", pending_id: "PF1", target_id: "F1",
     pending_fact: fact("PF1", "user_state", "новый сигнал"),
     target_before: fact("F1", "user_state", "любит код"),
     target_after: fact("F1", "user_state", "любит код и фото")},
    {action: "create", pending_id: "PF2", created_id: "F2",
     pending_fact: fact("PF2", "camera", "camera value"),
     created_fact: fact("F2", "camera", "camera value")},
    {action: "merge", pending_id: "PF3", created_id: "F5",
     pending_fact: fact("PF3", "project", "project value"),
     merged_facts: [fact("F3", "old_a", "first"), fact("F4", "old_b", "second")],
     created_fact: fact("F5", "project", "merged value"), comment: "Combined."},
    {action: "ignore", pending_id: "PF4",
     pending_fact: fact("PF4", "duplicate", "known value"), comment: "Already known."},
  ],
};
const legacy = [
  "1. UPDATE PF1 -> F1",
  "   incoming: user_state: новый сигнал [ id: PF1 ]",
  "   before: user_state: любит код [ id: F1 ]",
  "   after: user_state: любит код и фото [ id: F1 ]",
  "2. CREATE PF2 -> F2",
  "   incoming: camera: camera value [ id: PF2 ]",
  "   created: camera: camera value [ id: F2 ]",
  "3. MERGE PF3 -> F5",
  "   source: old_a: first [ id: F3 ]",
  "   source: old_b: second [ id: F4 ]",
  "   incoming: project: project value [ id: PF3 ]",
  "   created: project: merged value [ id: F5 ]",
  "   comment: Combined.",
  "4. IGNORE PF4",
  "   ignored: duplicate: known value [ id: PF4 ]",
  "   comment: Already known.",
].join("\\n");
function emit(event, details, extra = {}, message = "L-T merge applied") {
  // Match the JSON wire boundary; no object references from the server survive it.
  handleSocketLog(JSON.parse(JSON.stringify({
    type: "log", tag: "[MEMORY:L-T]", memory_level: "L-T",
    memory_event: event, message, details, ...extra,
  })));
  return activeLTMemorySequence;
}
function snapshot(node) {
  return {tag: node.tagName, classes: node.className, text: node.textContent, children: node.children.map(snapshot)};
}
function openBoth(state) {
  assert.equal(state.showButton.disabled, false);
  assert.equal(state.elements.apply.label.disabled, false);
  state.showButton.click();
  const rendered = snapshot(traceModalContent);
  state.elements.apply.label.click();
  assert.deepEqual(snapshot(traceModalContent), rendered);
  return rendered;
}

const modern = emit("merge_applied", "Readable text can change freely →", {trace});
assert.equal(modern.diffDetails, "Readable text can change freely →");
assert.deepEqual(modern.diffTrace, trace);
const savedLegacyParser = parseLegacyLTMergeAppliedTrace;
parseLegacyLTMergeAppliedTrace = () => { throw new Error("Structured event reparsed human text"); };
const modernDOM = openBoth(modern);
assert.equal(traceModalContent.querySelectorAll(".jin-lt-merge-operation").length, 4);
assert.ok(traceModalContent.querySelectorAll(".jin-lt-merge-diff-token").length > 0);
assert.equal(traceModalContent.querySelectorAll(".jin-lt-merge-row-ignored").length, 1);
parseLegacyLTMergeAppliedTrace = savedLegacyParser;

const old = emit("merge_applied", legacy);
assert.notEqual(old, modern);
assert.equal(old.diffTrace, null);
assert.deepEqual(openBoth(old), modernDOM);
// Opening another card must not overwrite the first card's structured payload.
assert.deepEqual(openBoth(modern), modernDOM);

for (const malformed of [null, "bad trace", {}, {kind: "other"}, {kind: "lt_merge_applied", operation_details: {}}]) {
  assert.deepEqual(openBoth(emit("merge_applied", legacy, {trace: malformed})), modernDOM);
}
// Older JSON-in-details callers remain valid.
showTrace(JSON.stringify(trace), "L-T merge applied");
assert.deepEqual(snapshot(traceModalContent), modernDOM);

const empty = emit("merge_applied", "No changes", {trace: {kind: "lt_merge_applied", operation_details: []}});
openBoth(empty);
assert.equal(traceModalContent.textContent, "No changes");
assert.equal(traceModal.classList.contains("jin-lt-merge-trace-modal"), false);
openBoth(emit("merge_applied", "No changes"));
assert.equal(traceModalContent.textContent, "No changes");

const pendingExtract = emit("summarizer_request", "extraction request", {}, "L-T extraction summarizer request");
assert.equal(pendingExtract.elements.extraction.label.dataset.status, "pending");
assert.equal(pendingExtract.elements.extraction.label.disabled, false);
pendingExtract.elements.extraction.label.click();
assert.equal(traceModalTitle.textContent, "L-T extraction request");
assert.equal(traceModalContent.textContent, "extraction request");
emit("summarizer_result", '{"facts": []}', {}, "L-T extraction summarizer result");
const noExtraction = emit("extract_applied", "No changes", {continues_to_merge: false});
openBoth(noExtraction);
assert.ok(traceModalContent.textContent.includes("No changes"));
assert.equal(noExtraction.elements.apply.label.dataset.status, "success");
assert.equal(noExtraction.elements.merge.label.dataset.status, "idle");
assert.equal(noExtraction.diffTrace, null);

const pendingMerge = emit("summarizer_request", "merge request", {}, "L-T merge summarizer request");
assert.equal(pendingMerge.elements.merge.label.dataset.status, "pending");
assert.equal(pendingMerge.elements.merge.label.disabled, false);
pendingMerge.elements.merge.label.click();
assert.equal(traceModalTitle.textContent, "L-T merge request");
assert.equal(traceModalContent.textContent, "merge request");
const failed = emit("merge_failed", "Original failure details");
assert.equal(failed.showButton.disabled, true);
failed.elements.merge.label.click();
assert.equal(traceModalTitle.textContent, "L-T merge failed");
assert.equal(traceModalContent.textContent, "Original failure details");
// The third showTrace argument must retain its existing reason semantics.
showTrace("plain details", "Other trace", "reason");
assert.equal(traceModalContent.textContent, "plain details");
assert.equal(traceModalReason.textContent, "Reason: reason");
assert.equal(traceModal.classList.contains("jin-lt-merge-trace-modal"), false);
assert.deepEqual(openBoth(modern), modernDOM);

const frameEmit = (event, details, level = "FRAME") => {
  handleSocketLog({tag: "[MEMORY:" + level + "]", memory_level: level,
    memory_event: event, message: "FRAME summarizer", details});
  return activeFrameMemorySequence;
};
const frameRequest = JSON.stringify({model: "test-model", temperature: 0.1, stream: false,
  messages: [{role: "system", content: "Summarize frame"}, {role: "user", content: "User turn"}]});
const frame = frameEmit("summarizer_request", frameRequest);
assert.equal(frame.logDiv.children[0].textContent, "[MEMORY:FRAME]");
assert.equal(frame.extract.dataset.status, "pending");
assert.equal(frame.extract.disabled, false);
assert.equal(frame.showButton.disabled, true);
assert.equal(frame.apply.disabled, true);
frame.extract.click();
assert.equal(traceModalTitle.textContent, "FRAME SUMMARIZER REQUEST");
assert.ok(traceModalContent.textContent.includes("test-model"));
assert.ok(traceModalContent.textContent.includes("Summarize frame"));
const count = consoleStream.children.length;
frameEmit("summarizer_stream_chunk", "ignored old stream", "L1");
assert.equal(consoleStream.children.length, count);
const frameResponse = JSON.stringify({kind: "summarizer_response", model: "test-model",
  content: "raw model answer", reasoning_content: "private dump",
  extracted_memory: "discussion_focus: context: runtime\\nuser_state: <script>alert(1)</script>"});
assert.equal(frameEmit("summarizer_response", frameResponse), frame);
assert.equal(consoleStream.children.length, count);
assert.equal(frame.extract.dataset.status, "success");
assert.equal(frame.apply.dataset.status, "success");
assert.equal(frame.showButton.disabled, false);
frame.showButton.click();
assert.equal(traceModalTitle.textContent, "FRAME SUMMARIZER RESPONSE");
assert.equal(traceModalContent.children.length, 1);
assert.equal(traceModalContent.querySelectorAll(".jin-context-card").length, 1);
assert.equal(traceModalContent.querySelectorAll(".jin-context-card-title")[0].textContent, "EXTRACTED FRAME");
assert.equal(traceModalContent.querySelectorAll(".jin-context-kv-key").map(n => n.textContent).join("|"),
  "discussion_focus|user_state");
assert.equal(traceModalContent.querySelectorAll(".jin-context-kv-value").map(n => n.textContent).join("|"),
  "context: runtime|<script>alert(1)</script>");
assert.equal(traceModalContent.textContent.includes("raw model answer"), false);
assert.equal(traceModalContent.textContent.includes("private dump"), false);
const frameDOM = snapshot(traceModalContent);
frame.apply.click();
assert.deepEqual(snapshot(traceModalContent), frameDOM);
frame.extract.click();
assert.equal(traceModalTitle.textContent, "FRAME SUMMARIZER REQUEST");
for (const event of ["summarizer_failed", "summarizer_skipped", "summarizer_cancelled"]) {
  const pending = frameEmit("summarizer_request", frameRequest, "L1");
  assert.notEqual(pending, frame);
  assert.equal(frameEmit(event, "Failure detail", "L1"), pending);
  assert.equal(pending.complete, true);
  assert.equal(pending.extract.dataset.status, "failed");
  assert.equal(pending.showButton.disabled, true);
  pending.extract.click();
  assert.equal(traceModalTitle.textContent, "FRAME SUMMARIZER REQUEST");
  pending.apply.click();
  assert.equal(traceModalContent.textContent, "Failure detail");
}
const single = frameEmit("summarizer_request", frameRequest);
frameEmit("summarizer_response", JSON.stringify({kind: "summarizer_response", extracted_memory: "focus: one field"}));
single.showButton.click();
assert.equal(traceModalContent.querySelectorAll(".jin-context-kv-row").length, 1);
assert.equal(traceModalContent.querySelectorAll(".jin-context-kv-value")[0].textContent, "one field");
const emptyFrame = frameEmit("summarizer_request", frameRequest);
frameEmit("summarizer_response", JSON.stringify({kind: "summarizer_response", extracted_memory: ""}));
emptyFrame.showButton.click();
assert.equal(traceModalContent.children.length, 1);
assert.equal(traceModalContent.querySelectorAll(".jin-context-empty")[0].textContent, "EMPTY");
// Existing cards keep their own immutable request/response after later cycles.
frame.showButton.click();
assert.deepEqual(snapshot(traceModalContent), frameDOM);
`, context);
'''
        result = subprocess.run(
            ["node", "-", str(ROOT)], input=script, text=True,
            capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
