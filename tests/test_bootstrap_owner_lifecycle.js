// node --preserve-symlinks-main tests/test_bootstrap_owner_lifecycle.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../ui/static/js/runtime/runtime-session.js'), 'utf8');

function page(previous = null) {
  let checkpoint = previous;
  let live = {session_id: 'child', runtime_memory: 'topic: inherited', runtime_memory_updates: 1};
  let writes = 0;
  const window = {};
  vm.runInNewContext(source, {window});
  window.JinRuntime.session.init({
    history: {}, memoryModel: {}, feedback: {},
    storage: {
      readLatestRuntimeMemory: () => live,
      writeLatestRuntimeMemory: value => {live = value;},
      readSessionCheckpoint: () => checkpoint,
      writeSessionCheckpoint: value => {checkpoint = JSON.parse(JSON.stringify(value)); writes++; return true;},
      getCurrentRuntimeSessionId: () => 'child',
      buildPersistedRuntimeSnapshot: value => value,
      markSessionCheckpointUserActivity() {},
    },
  });
  return {window, save: window.JinRuntime.session.persistLiveSessionCheckpoint,
    checkpoint: () => checkpoint, writes: () => writes};
}

for (const existing of [null, {session_id: 'parent', saved_at: 'original', session_snapshot: {recent_turns: []}}]) {
  const p = page(existing);
  assert.equal(p.save({session_snapshot: {recent_turns: [{user: '', jin: 'greeting'}]}, completed_turn_commit: false}), false);
  assert.equal(p.checkpoint(), existing, 'scenario 1: greeting cannot create/promote checkpoint');
  assert.equal(p.writes(), 0);
}
for (const scenario of [2, 3, 4]) {
  const p = page({session_id: 'parent'});
  p.window.markSessionActivityDirty();
  const turn = {user: 'real request', jin: scenario === 4 ? 'reply' : ''};
  if (scenario === 4) turn.reasoning = 'saved reasoning';
  assert.equal(p.save({session_snapshot: {recent_turns: [turn]}, completed_turn_commit: scenario === 4}), true);
  const restored = JSON.parse(JSON.stringify(p.checkpoint()));
  assert.equal(restored.session_id, 'child');
  assert.equal(restored.previous_session_id, 'parent');
  assert.deepEqual(restored.session_snapshot.recent_turns, [turn]);
  assert.equal(Boolean(restored.conversation_committed_at), scenario === 4);
}
console.log('PASS: D049 four scenarios, clean/existing profile, USER-only vs completed checkpoint');
