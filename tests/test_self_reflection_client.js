// Real DOM test, offline: the app's context renderer and action event path.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');

(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1100, height: 850}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setContent('<body style="background:#09090b;color:#ddd;font-family:monospace"><div id="chat-history"></div></body>');
    await page.addStyleTag({content: '*{box-sizing:border-box}.flex{display:flex}.flex-col{flex-direction:column}.flex-1{flex:1 1 0%}.min-h-0{min-height:0}'});
    await page.addStyleTag({content: fs.readFileSync('ui/static/css/runtime-memory.css', 'utf8')});
    await page.evaluate(() => {window.registerSocketMessageHandler = () => {};});
    for (const file of ['jin-ui-utils.js', 'chat-response-formatter.js', 'chat-reactions.js', 'think-citations.js',
      'chat-reference-ids.js', 'chat.js', 'chat-attachments.js', 'chat-runtime-actions.js',
      'socket/runtime-actions.js', 'logger/trace-modal.js']) {
      await page.addScriptTag({content: fs.readFileSync('ui/static/js/' + file, 'utf8')});
    }
    const prompt = '<FRAME_MEMORY_1>\nfocus: reflection\n</FRAME_MEMORY_1>\n<JIN INTUITION BLOCK>\nID | Behavior | Success | Failure\nIC-000001 | Я проверил результат | 0.85 | 0.15\nIC-000002 | I checked &lt;output&gt; | 0.10 | 0.90\n</JIN INTUITION BLOCK>';
    await page.evaluate(prompt => {
      ensureTraceModal();
      renderTraceDetails(`SYSTEM PROMPT\n----------------\n${prompt}\n\nUSER PROMPT / CONTEXT PAYLOAD\n----------------\nhello`, 'Context');
    }, prompt);
    await page.getByRole('tab', {name: 'SYSTEM', exact: true}).click();
    const card = page.locator('.jin-context-card').filter({has: page.locator('.jin-context-card-title', {hasText: 'JIN INTUITION BLOCK'})});
    assert.equal(await card.count(), 1);
    assert.equal(await card.getByRole('row').count(), 3);
    assert.equal(await card.getByRole('columnheader').count(), 4);
    assert.match(await card.innerText(), /IC-000001/);
    assert.match(await card.innerText(), /0\.85/);
    assert.match(await card.innerText(), /I checked <output>/);
    await card.locator('.jin-context-card-header').click();
    assert.match(await card.getAttribute('class'), /is-collapsed/);
    await card.locator('.jin-context-card-header').click();
    for (const width of [1100, 390]) {
      await page.setViewportSize({width, height: 850});
      assert(await card.evaluate(node => node.scrollWidth <= node.clientWidth + 1));
      const cells = await card.getByRole('row').nth(1).getByRole('cell').evaluateAll(nodes => nodes.map(n => n.getBoundingClientRect().x));
      assert(cells[0] < cells[1] && cells[1] < cells[2] && cells[2] < cells[3]);
    }
    if (process.env.REFLECTION_SCREENSHOT) await card.screenshot({path: process.env.REFLECTION_SCREENSHOT});
    await page.evaluate(() => {
      const base = {type: 'runtime_action', action: 'run_self_reflection', id: 'reflection_1',
        display_name: 'RUN_SELF_REFLECTION', runtime_turn_id: 'turn_1', runtime_message_id: 'message_1', close_tag: false};
      const counter = {...base, id: '', counter_id: 'turn_1:message_1:run_self_reflection', counter_only: true,
        aggregate_markers: true, marker_count: 1, payloads: [], text: 'RUN_SELF_REFLECTION'};
      handleRuntimeAction({...counter, status: 'counted', counter_final: false});
      handleRuntimeAction({...base, status: 'running', text: 'RUN_SELF_REFLECTION'});
      handleRuntimeAction({...base, status: 'completed', text: 'RUN_SELF_REFLECTION: session=old; sent=1–3; event=1–2; operation=CREATE; characteristic=IC-000001; behavior=I checked results; outcome=success; cursor=0→2', detail: 'saved'});
      handleRuntimeAction({...counter, status: 'counter_final', counter_final: true});
      handleRuntimeAction({...base, id: 'reflection_2', status: 'running', text: 'RUN_SELF_REFLECTION'});
      handleRuntimeAction({...base, id: 'reflection_2', status: 'failed', text: 'RUN_SELF_REFLECTION: Self-reflection cancelled; progress unchanged', detail: 'cancelled'});
    });
    const chat = await page.locator('#chat-history').innerText();
    assert.match(chat, /RUN_SELF_REFLECTION/);
    assert.match(chat, /checked results/);
    assert.match(chat, /cancelled/);
    assert.deepEqual(errors, []);
    console.log('PASS: intuition card/table, escaping, collapse, narrow layout and action lifecycle DOM');
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
