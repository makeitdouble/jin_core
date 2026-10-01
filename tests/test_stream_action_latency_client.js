// NODE_PATH must include Playwright. Uses the real socket and chat DOM path.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');

(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setContent('<div id="chat-history"></div><div id="chat-input-shell"></div>');
    await page.evaluate(() => {
      window.registerSocketMessageHandler = () => {};
      window.setGenerationState = () => {};
    });
    for (const file of [
      'chat-response-formatter.js', 'chat.js', 'chat-runtime-actions.js',
      'socket/delayed-memory.js', 'socket/event-handlers.js',
    ]) {
      await page.addScriptTag({content: fs.readFileSync(`ui/static/js/${file}`, 'utf8')});
    }
    await page.evaluate(() => {
      startStreamMessage('latency', 'brain');
      handleMessageChunk({message_id: 'latency', chunk: 'Hello'});
    });
    await page.waitForFunction(() => document.getElementById('chat-history').textContent.includes('Hello'));
    const first = await page.locator('#chat-history').innerText();
    assert.match(first, /Hello/);
    await page.evaluate(() => handleMessageChunk({message_id: 'latency', chunk: ' world!'}));
    await page.waitForFunction(() => document.getElementById('chat-history').textContent.includes('Hello world!'));
    assert.equal(await page.evaluate(() => streamMessages.has('latency')), true,
      'text must render before message_end, while the action is pending');
    assert.deepEqual(errors, []);
    console.log('PASS: socket chunks render incrementally in the real chat DOM before message_end');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
