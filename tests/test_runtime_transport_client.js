// Actual socket and generation DOM handlers, with only network/model mocked.
const fs = require('fs');
const assert = require('assert/strict');
const {chromium} = require('playwright');

(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setContent('<form id="chat-form"><input id="user-input"><button type="submit"></button></form><div id="stop-indicator"></div><div id="output"></div>');
    await page.evaluate(() => {
      window.sockets = [];
      window.sent = [];
      window.appendLog = () => {};
      window.syncDelayedMemoryReportsToRuntime = () => {};
      window.WebSocket = class {
        static OPEN = 1; static CONNECTING = 0;
        constructor() { this.readyState = 0; sockets.push(this); }
        send(text) { sent.push(JSON.parse(text)); }
        close() { this.readyState = 3; this.onclose({code:1006, wasClean:false}); }
      };
      window.deliver = data => sockets.at(-1).onmessage({data:JSON.stringify(data)});
      window.openSocket = (live, epoch='first') => {
        const socket = sockets.at(-1);
        socket.readyState = 1;
        socket.onopen();
        deliver({type:'runtime_transport_ready', live_resume:live, epoch});
      };
    });
    for (const file of ['ui/static/js/socket.js', 'ui/static/js/socket/event-handlers.js']) {
      await page.addScriptTag({content:fs.readFileSync(file, 'utf8')});
    }
    await page.waitForFunction(() => sockets.length === 1);
    await page.evaluate(() => {
      registerSocketMessageHandler('test_chunk', data => { document.getElementById('output').textContent += data.chunk; });
      openSocket(false);
      deliver({type:'agent_runtime_start', _jin_event_id:1});
      deliver({type:'test_chunk', chunk:'A', _jin_event_id:2});
      sockets.at(-1).close();
    });
    assert.equal(await page.locator('#chat-form').getAttribute('aria-busy'), 'true');
    const cdp = await page.context().newCDPSession(page);
    await cdp.send('Page.setWebLifecycleState', {state:'frozen'});
    await cdp.send('Page.setWebLifecycleState', {state:'active'});
    // Even after freeze and while hidden, repeated failures keep retrying.
    await page.evaluate(() => {
      Object.defineProperty(document, 'hidden', {configurable:true, get:()=>true});
      document.dispatchEvent(new Event('freeze'));
    });
    for (let n=2; n<=5; n++) {
      await page.waitForFunction(n => sockets.length === n, n, {timeout:7000});
      if (n<5) await page.evaluate(() => sockets.at(-1).close());
    }
    await page.evaluate(() => {
      window.getSoftReconnectRuntimeResume = () => { throw Error('Stale bootstrap must not overwrite live runtime'); };
      openSocket(true);
      deliver({type:'test_chunk', chunk:'A', _jin_event_id:2}); // ACK lost before disconnect.
      deliver({type:'test_chunk', chunk:'B', _jin_event_id:3});
      deliver({type:'agent_runtime_end', _jin_event_id:4});
    });
    assert.equal(await page.locator('#output').textContent(), 'AB');
    assert.equal(await page.locator('#chat-form').getAttribute('aria-busy'), 'false');
    assert.equal(await page.evaluate(() => sent.at(-1).sequence), 4);
    // Restart epoch resets deduplication and uses existing bootstrap fallback.
    await page.evaluate(() => {
      window.getSoftReconnectRuntimeResume = () => ({type:'runtime_resume'});
      sockets.at(-1).close();
      window.dispatchEvent(new Event('online'));
      openSocket(false, 'restarted');
      deliver({type:'test_chunk', chunk:'C', _jin_event_id:1});
    });
    assert.equal(await page.locator('#output').textContent(), 'ABC');
    assert.equal(await page.evaluate(() => sent.some(e=>e.type==='runtime_resume')), true);
    assert.deepEqual(errors, []);
    console.log('PASS: hidden/frozen retries beyond three failures, live DOM continuity, replay dedupe, restart fallback');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
