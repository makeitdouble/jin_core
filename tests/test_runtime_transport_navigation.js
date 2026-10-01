// Real Edge navigation + actual endpoint/queue/RuntimeStream; only model output is fake.
const {spawn} = require('child_process');
const net = require('net');
const assert = require('assert/strict');
const {chromium} = require('playwright');

(async () => {
  const port = await new Promise(resolve => {
    const probe = net.createServer();
    probe.listen(0, '127.0.0.1', () => {
      const port = probe.address().port;
      probe.close(() => resolve(port));
    });
  });
  const server = spawn('.venv/Scripts/python.exe', ['-m', 'tests.runtime_transport_browser_server', String(port)], {stdio:'pipe', windowsHide:true});
  let stderr = '';
  server.stderr.on('data', data => { stderr += data; });
  let browser;
  try {
    const url = `http://127.0.0.1:${port}`;
    const poll = async predicate => {
      for (let i = 0; i < 100; i++) {
        if (await predicate()) return;
        await new Promise(resolve => setTimeout(resolve, 50));
      }
      throw Error('Timed out: ' + stderr + JSON.stringify(await (await fetch(url + '/state')).json()));
    };
    await poll(async () => { try { return (await fetch(url + '/state')).ok; } catch { return false; } });
    browser = await chromium.launch({channel:'msedge', headless:true});
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(url);
    for (const kind of ['stream', 'guard']) {
      await page.waitForFunction(() => window.jinWebSocketConnected);
      const oldId = await page.evaluate(kind => {
        sendSocketMessage({type:'message', text:kind});
        return jinRuntimeSessionId;
      }, kind);
      await page.waitForFunction(kind => seen.some(e => e.type === (kind === 'guard' ? 'runtime_action_guard_confirmation' : 'test_chunk')), kind);
      await page.reload();
      await page.waitForFunction(() => window.jinWebSocketConnected);
      await poll(async () => {
        const state = await (await fetch(url + '/state')).json();
        return !state.ids.includes(oldId) && state.events.some(e => e[0] === oldId && e[1] === 'cancelled');
      });
    }
    const lastId = await page.evaluate(() => jinRuntimeSessionId);
    await page.close();
    await poll(async () => !(await (await fetch(url + '/state')).json()).ids.includes(lastId));
    assert.deepEqual(errors, []);
    const state = await (await fetch(url + '/state')).json();
    assert.equal(state.ids.length, 0);
    assert.equal(state.events.filter(e => e[1] === 'completed').length, 0);
    console.log('PASS: real reload cancels streaming and action guard; tab close removes final runtime');
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
