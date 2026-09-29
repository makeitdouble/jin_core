// Run without Playwright: exercise the existing shared 1500ms hold-delete helper.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const source = fs.readFileSync('ui/static/js/runtime/runtime-memory-view.js', 'utf8');
const begin = source.indexOf('  function configureRuntimeMemoryDeleteHold(');
const end = source.indexOf('  function getPersistentFileReferenceAliases(', begin);
assert.ok(begin >= 0 && end > begin, 'reuse existing memory hold handler');
const sharedFunctions = source.slice(begin, end);
assert.match(source, /configureOpenableMemoryRowHoldDelete\(\s*row,\s*\(\) => window\.open\(`\/\?restore_session=/);
assert.match(source, /method: "DELETE"/);
assert.match(source, /archivedSessionDeletedIds\.add\(sessionId\)/);
assert.match(source, /archivedSessions = archivedSessions\.filter\(session => session\.session_id !== sessionId\)/);

class FakeRow {
  constructor() {
    this.listeners = new Map();
    this.dataset = {};
    this.classList = {add: () => {}};
    this.isConnected = true;
  }
  addEventListener(type, handler) {
    const list = this.listeners.get(type) || [];
    list.push(handler);
    this.listeners.set(type, list);
  }
  dispatch(type) {
    const event = {button: 0, pointerId: 1, preventDefault() {}, stopImmediatePropagation() {}};
    (this.listeners.get(type) || []).forEach(fn => fn(event));
  }
}
function makeHarness(onOpen, onDelete) {
  let nextId = 0;
  const tasks = new Map();
  const calls = [];
  const setTimeoutFake = (fn, ms) => {const id = ++nextId; tasks.set(id, {fn, ms}); return id;};
  const clearTimeoutFake = id => tasks.delete(id);
  const bind = new Function('MEMORY_DELETE_HOLD_MS', 'setRuntimeMemoryRowPressVisual',
    'setTimeout', 'clearTimeout', sharedFunctions + '\nreturn configureOpenableMemoryRowHoldDelete;');
  const configure = bind(1500, (row, active) => calls.push(active), setTimeoutFake, clearTimeoutFake);
  const row = new FakeRow();
  configure(row, onOpen, onDelete);
  return {row, calls, hold(ms) {for (const [id, task] of [...tasks]) {
    if (task.ms <= ms) {tasks.delete(id); task.fn();}
  }}};
}
(async () => {
  let opened = 0, deleted = 0;
  const success = makeHarness(() => opened++, async () => {deleted++; return true;});
  success.row.dispatch('pointerdown');
  success.hold(1499);
  success.row.dispatch('pointerup');
  success.row.dispatch('click');
  assert.equal(opened, 1, 'short click opens session');
  assert.equal(deleted, 0, 'short click must not delete');
  assert.deepEqual(success.calls, [true, false]);

  success.row.dispatch('pointerdown');
  success.hold(1500);
  success.row.dispatch('pointerup');
  success.row.dispatch('click');
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(deleted, 1, 'long hold deletes once');
  assert.equal(opened, 1, 'click after long hold cannot open deleted session');
  assert.equal(success.row.dataset.runtimeMemoryHoldDeleted, 'false'); // consumed the synthetic click

  const failed = makeHarness(() => opened++, async () => false);
  failed.row.dispatch('pointerdown');
  failed.hold(1500);
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(failed.calls.at(-1), false, 'failed delete restores opacity');
  assert.equal(failed.row.dataset.runtimeMemoryHoldDeleted, 'false');
  console.log('LOGS: shared 1500ms fade, short-click restore, long-hold deletion, click suppression, failure reset passed');
})().catch(e => {console.error(e); process.exitCode = 1;});
