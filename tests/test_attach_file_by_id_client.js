// Run with Playwright on NODE_PATH; exercises the actual socket handler and
// action label/detail DOM writer in a headless browser, without a model/server.
const fs = require('fs');
const assert = require('assert/strict');
const {chromium} = require('playwright');

(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage();
    await page.setContent('<main><div id="chat"></div></main>');
    for (const file of ['ui/static/js/chat-runtime-actions.js', 'ui/static/js/socket/runtime-actions.js', 'ui/static/js/logger/session-actions.js']) {
      await page.addScriptTag({content: fs.readFileSync(file, 'utf8')});
    }
    const result = await page.evaluate(() => {
      // Only app-shell dependencies are stubbed; socket interpretation, label
      // rendering, dataset persistence and title propagation run production code.
      window.chatHistory = document.getElementById('chat');
      window.jinConversationTurnCounter = 1;
      window.getRuntimeActionMessageId = data => data.runtime_message_id || '';
      window.fadeRuntimeAction = () => {};
      clearRuntimeActionGuardConfirmation = () => {};
      markRuntimeActionRowCompleted = row => { row.dataset.runtimeActionCompleted = 'true'; };
      reviveRuntimeActionRow = () => {};
      window.appendRuntimeAction = (action, text, options) => {
        let row = document.getElementById(options.id);
        if (!row) {
          row = document.createElement('div');
          row.id = options.id;
          row.className = 'jin-runtime-action-row';
          row.innerHTML = '<span class="jin-runtime-action-label"></span>';
          chatHistory.append(row);
        }
        return updateRuntimeActionRow(row, action, text, options);
      };
      const common = {action:'attach_file_by_id', id:'search1', close_tag:false, runtime_message_id:'m1'};
      handleRuntimeAction({...common, status:'running', text:'ATTACH_FILE_BY_ID', detail:'Request: pizza'});
      handleRuntimeAction({...common, status:'completed', text:'ATTACH_FILE_BY_ID: full_file_name.jpg', detail:'Request: pizza\nUSER: pizza\nAttachments: menu.jpg'});
      const row = document.getElementById('search1');
      const completed = {text:row.textContent, title:row.title};
      handleRuntimeAction({...common, status:'failed', text:'ATTACH_FILE_BY_ID: zzzzzz : failed - file not exists', detail:'Reason: file not exists\nCorrect action schema: <ATTACH_FILE_BY_ID: file_id >'});
      const failed = {text:row.textContent, title:row.title};
      updateRuntimeActionRow(row, 'attach_file_by_id', 'ATTACH_FILE_BY_ID', {counterOnly:true, preserveLabel:true, markerCount:1});
      handleRuntimeAction({...common, id:'search2', status:'completed', text:'ATTACH_FILE_BY_ID: notes.txt', detail:'Request: delivery\nNo matching messages'});
      const history = buildSessionActionRow({parts: [{text: 'ATTACH_FILE_BY_ID: full_file_name.jpg', tool_ids: ['T1']}, {text: 'ATTACH_FILE_BY_ID: zzzzzz : failed - file not exists', tool_ids: ['T2']}], createdAt: Date.now()/1000}, 0);
      chatHistory.appendChild(history);
      return {history: history.textContent, completed, failed, retained:row.title, retainedText:row.textContent,
              childrenTitle:row.querySelector('.jin-runtime-action-name').title,
              rows:chatHistory.children.length};
    });
    assert.match(result.completed.text, /ATTACH_FILE_BY_ID: full_file_name.jpg/);
    assert.match(result.completed.title, /Attachments: menu.jpg/);
    assert.match(result.failed.text, /zzzzzz : failed - file not exists/);
    assert.match(result.failed.title, /Correct action schema/);
    assert.equal(result.retained, result.failed.title);
    assert.match(result.retainedText, /zzzzzz : failed - file not exists/);
    assert.equal(result.childrenTitle, result.failed.title);
    assert.equal(result.rows, 3);
    assert.match(result.history, /ATTACH_FILE_BY_ID: full_file_name.jpg/);
    assert.match(result.history, /ATTACH_FILE_BY_ID: zzzzzz : failed - file not exists/);
    console.log('ATTACH_FILE_BY_ID browser DOM: completion, failure, hover, counter preservation passed');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
