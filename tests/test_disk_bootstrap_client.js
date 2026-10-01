// Real Edge DOM + production storage/session/socket/chat; only transport is mocked.
const fs = require('fs');
const assert = require('assert/strict');
const {chromium} = require('playwright');

(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage();
    await page.route('http://bootstrap.test/**', route => route.fulfill({body:
      '<div id="chat-history"></div><div id="chat-input-shell"></div>' +
      '<form id="chat-form"><input id="user-input"><button type="submit"></button></form>' +
      '<div id="stop-indicator"></div><pre id="frame"></pre>', contentType: 'text/html'}));
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const boot = async () => {
      await page.goto('http://bootstrap.test/');
      await page.evaluate(() => {
        localStorage.setItem('theme', 'keep-ui-preference');
        for (const key of ['jin.sessionCheckpoint.v2', 'jin.latestSavedSessionSnapshot.v1',
          'jin.activeMemory.v1', 'jin.factsMemory.foreign.v2']) {
          localStorage.setItem(key, JSON.stringify({version:2, state:'checkpoint', session_id:'foreign',
            runtime_memory:'FOREIGN FRAME', session_snapshot:{recent_turns:[{user:'FOREIGN USER'}]}}));
        }
        sessionStorage.setItem('jin.liveRuntimeMemory.v2', JSON.stringify({runtime_memory:'FOREIGN LIVE'}));
        window.sockets = []; window.sent = []; window.colors = [];
        window.appendLog = () => {};
        window.WebSocket = class {
          static OPEN = 1; static CONNECTING = 0;
          constructor() { this.readyState = 0; sockets.push(this); }
          send(text) { sent.push(JSON.parse(text)); }
          close() { this.readyState = 3; }
        };
        window.deliver = data => sockets.at(-1).onmessage({data:JSON.stringify(data)});
      });
      for (const file of ['jin-ui-utils.js', 'runtime/runtime-storage.js', 'runtime/runtime-memory-model.js',
        'runtime/runtime-session.js', 'think-formatter.js', 'think-citations.js', 'chat-response-formatter.js', 'chat.js',
        'chat-runtime-actions.js', 'session-restore.js']) {
        await page.addScriptTag({content:fs.readFileSync('ui/static/js/' + file, 'utf8')});
      }
      await page.evaluate(() => {
        window.frameHistory = {snapshots:[], index:0};
        JinRuntime.avatar = {setCenterColor: color => colors.push(color)};
        JinRuntime.session.init({history:frameHistory, storage:JinRuntime.storage,
          memoryModel:JinRuntime.memoryModel, feedback:{},
          defaultRuntimeMemoryText:'This session has just begun.',
          setRuntimeMemoryDisplayMode() {}, renderRuntimeMemorySnapshot() {
            document.getElementById('frame').textContent = frameHistory.snapshots.at(-1)?.raw_memory || '';
          }});
      });
      for (const file of ['socket.js', 'socket/event-handlers.js']) {
        await page.addScriptTag({content:fs.readFileSync('ui/static/js/' + file, 'utf8')});
      }
      await page.waitForFunction(() => sockets.length === 1);
      await page.evaluate(() => {
        sockets[0].readyState = 1;
        sockets[0].onopen();
        deliver({type:'runtime_transport_ready', live_resume:false, epoch:'first'});
      });
      await page.waitForFunction(() => sent.some(item => item.type === 'session_bootstrap'));
      assert.deepEqual(await page.evaluate(() => sent.filter(item => item.type === 'session_bootstrap')),
        [{type:'session_bootstrap'}]);
      assert.equal(await page.evaluate(() => localStorage.getItem('theme')), 'keep-ui-preference');
      assert.equal(await page.evaluate(() => JinRuntime.storage.readSessionCheckpoint()), null);
      assert.doesNotMatch(await page.locator('body').innerText(), /FOREIGN/);
    };
    await boot();
    await page.evaluate(() => deliver({type:'bootstrap_state', bootstrap:{type:'session_bootstrap'}}));
    assert.equal(await page.locator('.jin-message-shell').count(), 0);
    assert.equal(await page.evaluate(() => sent.some(item => item.type === 'archived_session_resume')), false);

    // Reload in the same browser, with the same poisoned durable storage.
    await boot();
    await page.evaluate(() => {
      deliver({type:'bootstrap_state', bootstrap:{source_session_id:'disk-session',
        archived_session_restore:true, runtime_memory:'topic: DISK FRAME', runtime_memory_updates:2}});
      deliver({type:'session_bootstrap_chat_tail', source_session_id:'disk-session', turns:[
        {user:'DISK USER', jin:'DISK JIN', reasoning:'disk reasoning', user_created_at:1750000000, jin_created_at:1750000002},
        {user:'INTERRUPTED USER', user_created_at:1750000010},
      ]});
    });
    assert.match(await page.locator('#frame').innerText(), /DISK FRAME/);
    assert.match(await page.locator('#chat-history').innerText(), /DISK USER/);
    assert.match(await page.locator('#chat-history').innerText(), /DISK JIN/);
    assert.match(await page.locator('#chat-history').innerText(), /INTERRUPTED USER/);
    assert.equal(await page.locator('.jin-message-shell[data-role="user"]').count(), 2);
    assert.match(await page.locator('#chat-history').textContent(), /disk reasoning/);
    assert.equal(await page.locator('[role="separator"]').count(), 1);
    assert.equal(await page.evaluate(() => sent.filter(item => item.type === 'archived_session_resume').length), 1);
    const sentBefore = await page.evaluate(() => sent.length);
    await page.evaluate(() => deliver({type:'runtime_transport_ready', live_resume:true, epoch:'first'}));
    assert.equal(await page.evaluate(() => sent.length), sentBefore, 'live RAM reconnect sends no state');
    assert.deepEqual(errors, []);
    console.log('PASS: poisoned storage, clean boot, reload, disk FRAME/chat/reasoning, interrupted USER, live reconnect');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
