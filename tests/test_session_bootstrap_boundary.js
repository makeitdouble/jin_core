// Run with: node tests/test_session_bootstrap_boundary.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
process.env.TZ = 'Europe/Kyiv';

const source = fs.readFileSync(path.join(
  __dirname, '../ui/static/js/socket/event-handlers.js'
), 'utf8');

function render(turns, archived = false) {
  const history = {
    children: [],
    appendChild(node) { this.children.push(node); },
    querySelectorAll() { return this.children.filter(n => n.role); },
  };
  const handlers = {};
  const window = {
    jinArchivedSessionRestorePayload: archived ? {} : null,
    activateLiveUserTurnViewport(node) { this.boundary = node; },
  };
  const context = vm.createContext({
    window,
    document: {
      getElementById: () => history,
      createElement: () => ({
        children: [], attributes: {},
        appendChild(node) { this.children.push(node); },
        setAttribute(name, value) { this.attributes[name] = value; },
      }),
    },
    registerSocketMessageHandler(name, handler) { handlers[name] = handler; },
    handleSocketLTMemoryRestoreResult() {},
    handleSocketError() {},
    handleSocketChatMessage() {},
    appendChatMessage(role, text) { history.children.push({role, text}); },
    startStreamMessage(id, role) { history.children.push({id, role}); },
    appendThinkingChunk() {}, appendStreamChunk() {}, finishStreamMessage() {},
  });
  vm.runInContext(source, context);
  const payload = JSON.parse(JSON.stringify({source_session_id: 'old', turns}));
  handlers.session_bootstrap_chat_tail(payload);
  return {history, window, replay: () => handlers.session_bootstrap_chat_tail(payload)};
}

const userAt = Date.parse('2026-09-02T23:27:10+03:00') / 1000;
const jinAt = Date.parse('2026-09-02T23:29:12+03:00') / 1000;
const user = {user: 'saved user message', user_created_at: userAt};
function check(turns, expected, roles) {
  const result = render(turns);
  const divider = result.history.children.find(n => n.attributes?.role === 'separator');
  assert.equal(divider?.children[0].textContent, expected);
  assert.deepEqual(result.history.children.filter(n => n.role).map(n => n.role), roles);
  assert.equal(result.window.boundary, divider);
  const count = result.history.children.length;
  result.replay();
  assert.equal(result.history.children.length, count, 'reconnect must not duplicate history');
}

check([{...user, jin: 'reply', jin_created_at: jinAt}],
  '2 september 23:29, Wednesday', ['user', 'brain']);
check([user], '2 september 23:27, Wednesday', ['user']);
check([{...user, jin: '', jin_created_at: jinAt}],
  '2 september 23:29, Wednesday', ['user']);
check([{...user, jin_created_at: 'invalid'}],
  '2 september 23:27, Wednesday', ['user']);
check([{...user, jin_created_at: String(jinAt)}],
  '2 september 23:29, Wednesday', ['user']);
check([{...user, jin: 'reply', jin_created_at: jinAt},
  {...user, user_created_at: Date.parse('2026-09-03T00:01:00+03:00') / 1000}],
  '3 september 00:01, Thursday', ['user', 'brain', 'user']);
check([{...user, jin_created_at: jinAt}, {user: 'legacy, no dates'}],
  undefined, ['user', 'user']);
for (const value of [undefined, null, '', 0, -1, 'invalid', 1e20]) {
  check([{user: 'legacy', user_created_at: value}], undefined, ['user']);
}
check([], undefined, []);
assert.equal(render([user], true).history.children.length, 0,
  'explicit archived restore owns its rendering');
console.log('PASS: historical dates, interrupted/action-only turns, local midnight, legacy dates, reconnect, archived restore');
