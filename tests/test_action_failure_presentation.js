const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.join(__dirname, '../ui/static/js');
function extract(source, name, next) {
  return source.slice(source.indexOf(`function ${name}(`), source.indexOf(`function ${next}(`));
}
const trace = fs.readFileSync(path.join(root, 'logger/trace-modal.js'), 'utf8');
const socket = fs.readFileSync(path.join(root, 'socket/runtime-actions.js'), 'utf8');
const label = 'ATTACH_FILE_CONTENT: jin_core/agent/nodes/brain.py - failed: no project folder attached by user';
const body = 'Action: attach_file_content\nFile: jin_core/agent/nodes/brain.py\nStatus: failed\nReason: no project folder attached by user\nCorrect action schema:\n<ATTACH_FILE_CONTENT: file_id >';
const context = vm.createContext({
  decodeContextEntities: x => x,
  parseContextBlocks: () => [{title: 'TOOL_RESULT', attributes: ['tool_id=T8', 'name=ATTACH_FILE_CONTENT'], content: body}],
  getContextAttributeValue: (attrs, key) => attrs.find(a => a.startsWith(key + '='))?.split('=')[1],
  contextElement: () => ({children: [], appendChild(n) {this.children.push(n);}}),
  appendContextCard: (parent, card) => parent.appendChild(card),
});
vm.runInContext(extract(trace, 'contextToolResultFileTitleSuffix', 'setContextCardCollapsed'), context);
const parent = {children: [], appendChild(n) {this.children.push(n);}};
context.renderContextToolResultsBody(parent, body);
assert.equal(parent.children[0].children[0].title, 'T8 · ' + label);
vm.runInContext(extract(socket, 'buildRuntimeActionDisplayText', 'shouldUseDeepSearchStartedDisplayNameOnly'), context);
assert.equal(context.buildRuntimeActionDisplayText({}, 'attach_file_content', label), label);
assert.equal(context.contextToolResultFileTitleSuffix('File: root/a.py\nFile lines: 1-20 of 100 lines', 'ATTACH_FILE_CONTENT'), 'root/a.py#1-20');
console.log('PASS: rendered tool card title and bubble text agree; successful range labels preserved');
