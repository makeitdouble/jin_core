const fs = require('fs');
const assert = require('assert/strict');
const {chromium} = require('playwright');

(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1200, height: 900}});
    await page.setContent('<body style="background:#09090b;color:#ddd;font-family:monospace"><main id="results"></main></body>');
    await page.addStyleTag({content: fs.readFileSync('ui/static/css/runtime-memory.css', 'utf8')});
    await page.addScriptTag({content: fs.readFileSync('ui/static/js/logger/trace-modal.js', 'utf8')});
    const sample = `Status: success
Request: {"query":["photo"]}
Returned: 2; matching turns: 2; more: false

[1] Session: session-a | Turn: turn_1 | Archive: date/session-a/1.jsonl
USER [2026-08-20T12:00:00+03:00]:
  A photo with <script>not executable</script>.
  USER [literal]:
  [9] Session: literal | Turn: literal | Archive: literal
Attachments: full_photo.jpg [id: abc123]
JIN [2026-08-20T12:01:00+03:00]:
  First paragraph.

  Second paragraph.
JIN reasoning excerpts [2026-08-20T12:01:00+03:00] (matching USER above):
  Reasoning excerpt.

[2] Session: session-b | Turn: turn_2 | Archive: date/session-b/2.jsonl
USER [2026-08-21T12:00:00+03:00]:
  An interrupted user-only turn.`;
    const result = await page.evaluate(sample => {
      const root = document.getElementById('results');
      renderContextToolResultsBody(root, `<TOOL_RESULT tool_id="T1" name="CHAT_LOG_SEARCH">\n${sample}\n</TOOL_RESULT>`);
      const cards = root.querySelectorAll('.jin-context-card');
      const messages = root.querySelectorAll('.jin-context-search-message');
      return {cards: cards.length, messages: messages.length, text: root.textContent,
        scripts: root.querySelectorAll('script').length,
        lastRoles: [...cards[cards.length - 1].querySelectorAll('.jin-context-chat-role')].map(n => n.textContent)};
    }, sample);
    assert.equal(result.cards, 3);
    assert.equal(result.messages, 5);
    assert.equal(result.scripts, 0);
    assert.match(result.text, /USER \[literal\]:/);
    assert.match(result.text, /Second paragraph/);
    assert.match(result.text, /Reasoning excerpt/);
    assert.equal(result.lastRoles.length, 1);
    await page.locator('.jin-context-card').nth(1).locator('.jin-context-card-header').first().click();
    assert.equal(await page.locator('.jin-context-card').nth(1).evaluate(n => n.classList.contains('is-collapsed')), true);
    for (const name of ['CHAT_LOG_SEARCH', 'OTHER']) {
      const text = await page.evaluate(name => {
        const root = document.createElement('div');
        renderContextToolResultBody(root, 'Status: failed\nReason: missing query', name);
        return root.textContent;
      }, name);
      assert.match(text, /Reason: missing query/);
    }
    if (process.argv[2]) {
      const fixture = fs.readFileSync(process.argv[2], 'utf8');
      await page.evaluate(fixture => {
        const root = document.getElementById('results');
        root.replaceChildren();
        renderContextToolResultsBody(root, fixture.match(/<TOOL_RESULT[^>]*name="CHAT_LOG_SEARCH"[^>]*>([\s\S]*?)<\/TOOL_RESULT>/)[0]);
      }, fixture);
      assert.equal(await page.locator('#results > .jin-context-stack > .jin-context-card .jin-context-card').count(), 10);
      await page.screenshot({path: process.argv[3] || 'chat-search-modal.png'});
    }
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    console.log('PASS: search results modal grouping, full messages, literal headers, safe text, collapse, fallback, narrow viewport');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
