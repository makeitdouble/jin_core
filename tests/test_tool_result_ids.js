const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const read = name => fs.readFileSync(path.join(__dirname, '..', name), 'utf8');
class Element {
  constructor() { this.children = []; this.textContent = ''; this.style = {}; this.dataset = {}; this.classList = {add() {}}; }
  appendChild(child) { this.children.push(child); }
}
const context = vm.createContext({window: {}, document: {createElement: () => new Element(), createTextNode: text => ({textContent: text})}, Date});
vm.runInContext(read('ui/static/js/logger/session-actions.js'), context);
context.item = {parts: [{text: 'ATTACH_FILE_CONTENT', detail: 'agent/nodes/base.py', tool_ids: ['T1']}], createdAt: Date.now()/1000 - 1};
const row = vm.runInContext('buildSessionActionRow(item, 5)', context);
function text(node) { return node.textContent + (node.children || []).map(text).join(''); }
assert.match(text(row), /^6\. ATTACH_FILE_CONTENT: agent\/nodes\/base\.py \[ tool_id: T1 \] \(1s ago\)$/);
let checkpoint = {saved_at: 'old', session_id: 'session', session_snapshot: {tool_results: [{tool_id: 'T1'}, {tool_id: 'T2'}], recent_turns: ['keep'], tool_result_sequence: 2}};
vm.runInContext(read('ui/static/js/runtime/runtime-session.js'), context);
context.window.JinRuntime.session.init({memoryModel: {}, storage: {readSessionCheckpoint: () => checkpoint, writeSessionCheckpoint: value => {checkpoint = value;}}});
context.window.JinRuntime.session.clearPersistedToolResultsCheckpoint([{tool_id: 'T2'}], 2);
assert.equal(checkpoint.saved_at, 'old');
assert.equal(checkpoint.session_id, 'session');
assert.equal(checkpoint.session_snapshot.tool_results[0].tool_id, 'T2');
assert.equal(checkpoint.session_snapshot.recent_turns[0], 'keep');
context.window.JinRuntime.session.clearPersistedToolResultsCheckpoint();
assert.equal(checkpoint.session_snapshot.tool_results.length, 0);
assert.equal(checkpoint.session_snapshot.tool_result_sequence, 2);
console.log('Tool ID history DOM and cleanup checkpoint tests passed');
