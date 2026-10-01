// Actual socket -> bubble DOM -> Session Actions renderer, no model required.
const fs = require('fs');
const assert = require('assert/strict');
const {chromium} = require('playwright');

(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage();
    await page.setContent('<main><div id="chat"></div></main>');
    await page.addScriptTag({content: 'window.registerSocketMessageHandler = () => {};'});
    for (const file of ['ui/static/js/chat-runtime-actions.js', 'ui/static/js/socket/runtime-actions.js', 'ui/static/js/logger/session-actions.js']) {
      await page.addScriptTag({content: fs.readFileSync(file, 'utf8')});
    }
    const result = await page.evaluate(() => {
      window.chatHistory = document.getElementById('chat');
      window.jinConversationTurnCounter = 1;
      const label = 'MALFORMED_ACTION: ATTACH_FILE_BY_ID';
      for (let i = 1; i <= 3; i++) {
        handleRuntimeAction({action:'malformed_action', name:'malformed_action', id:`T${i}`,
          tool_id:`T${i}`, runtime_message_id:'message1', runtime_turn_id:'turn1',
          close_tag:false, status:'failed', error:'malformed_action', display_name:'MALFORMED_ACTION',
          text:label, detail:`Action: ATTACH_FILE_BY_ID\nPayload: {id:"file${i}"}`});
      }
      const rows = [...chatHistory.querySelectorAll('.jin-runtime-action-row')];
      const history = buildSessionActionRow({parts:[{text:label, tool_ids:['T1']}], createdAt:Date.now()/1000}, 0);
      return {rows:rows.map(row => ({text:row.textContent, title:row.title, id:row.dataset.runtimeActionId})), history:history.textContent};
    });
    assert.equal(result.rows.length, 3);
    assert.deepEqual(result.rows.map(row => row.id), ['T1', 'T2', 'T3']);
    result.rows.forEach((row, i) => {
      assert.match(row.text, /MALFORMED_ACTION: ATTACH_FILE_BY_ID/);
      assert.match(row.title, new RegExp(`file${i+1}`));
    });
    assert.match(result.history, /MALFORMED_ACTION: ATTACH_FILE_BY_ID/);
    console.log('MALFORMED_ACTION browser DOM: three separate bubbles, payload hover and history passed');
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
