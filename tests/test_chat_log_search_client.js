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
    for (const file of ['ui/static/js/chat-runtime-actions.js', 'ui/static/js/socket/runtime-actions.js']) {
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
      const common = {action:'chat_log_search', id:'search1', close_tag:true, runtime_message_id:'m1'};
      handleRuntimeAction({...common, status:'running', text:'CHAT_LOG_SEARCH', detail:'Request: pizza'});
      handleRuntimeAction({...common, status:'completed', text:'CHAT_LOG_SEARCH: 1 results', detail:'Request: pizza\nUSER: pizza\nAttachments: menu.jpg'});
      const row = document.getElementById('search1');
      const completed = {text:row.textContent, title:row.title};
      handleRuntimeAction({...common, status:'failed', text:'CHAT_LOG_SEARCH: failed - invalid limit', detail:'Reason: invalid limit\nCorrect action schema: max_limit 1..50'});
      const failed = {text:row.textContent, title:row.title};
      updateRuntimeActionRow(row, 'chat_log_search', 'CHAT_LOG_SEARCH', {counterOnly:true, preserveLabel:true, markerCount:1});
      handleRuntimeAction({...common, id:'search2', status:'completed', text:'CHAT_LOG_SEARCH: 0 results', detail:'Request: delivery\nNo matching messages'});
      return {completed, failed, retained:row.title, retainedText:row.textContent,
              childrenTitle:row.querySelector('.jin-runtime-action-name').title,
              rows:chatHistory.children.length, icon:runtimeActionIconDefinitions.chat_log_search};
    });
    assert.match(result.completed.text, /1 results/);
    assert.match(result.completed.title, /Attachments: menu.jpg/);
    assert.match(result.failed.text, /failed - invalid limit/);
    assert.match(result.failed.title, /Correct action schema/);
    assert.equal(result.retained, result.failed.title);
    assert.match(result.retainedText, /failed - invalid limit/);
    assert.equal(result.childrenTitle, result.failed.title);
    assert.equal(result.rows, 2);
    assert.equal(result.icon.tone, 'search');
    console.log('CHAT_LOG_SEARCH browser DOM: completion, failure, hover, counter preservation passed');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
