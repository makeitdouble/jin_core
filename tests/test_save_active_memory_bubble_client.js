const fs = require('fs');
const assert = require('assert/strict');
const {chromium} = require('playwright');
(async () => {
  const browser = await chromium.launch({channel:'msedge', headless:true});
  try {
    const page = await browser.newPage();
    await page.setContent('<main><div id="chat"></div></main>');
    await page.evaluate(() => { window.registerSocketMessageHandler = () => {}; });
    for (const file of ['ui/static/js/chat-runtime-actions.js', 'ui/static/js/socket/runtime-actions.js']) {
      await page.addScriptTag({content:fs.readFileSync(file,'utf8')});
    }
    const result = await page.evaluate(() => {
      window.chatHistory = document.getElementById('chat');
      window.jinConversationTurnCounter = 1;
      window.getRuntimeActionMessageId = () => '';
      clearRuntimeActionGuardConfirmation = () => {};
      // Use the production label/detail writer and completion path in real DOM.
      window.appendRuntimeAction = (action, text, options) => {
        let row = document.getElementById(options.id);
        if (!row) {
          row = document.createElement('div');
          row.id = options.id;
          row.dataset.runtimeAction = action;
          row.dataset.runtimeActionKey = buildRuntimeActionVisibleKey(action, options);
          row.className = 'jin-runtime-action-row';
          row.innerHTML = '<span class="jin-runtime-action-label"></span>';
          chatHistory.append(row);
        }
        return updateRuntimeActionRow(row, action, text, options);
      };
      const common = {action:'save_active_memory',id:'save1',close_tag:true,display_name:'SAVE_ACTIVE_MEMORY'};
      handleRuntimeAction({...common,status:'started'});
      const row = document.getElementById('save1');
      const started = row.textContent;
      handleRuntimeAction({...common,status:'completed',active_memory_id:'abc123',active_memory:'active_memory_1: test [ active_memory_id: abc123 ]'});
      const completed = row.textContent;
      const faded = row.dataset.runtimeActionCompleted;
      handleRuntimeAction({...common,counter_only:true,counter_final:true,marker_count:1});
      return {started,completed,faded,retained:row.textContent,rows:chatHistory.children.length};
    });
    assert.equal(result.started,'SAVE_ACTIVE_MEMORY');
    assert.equal(result.completed,'SAVE_ACTIVE_MEMORY: active_memory_1');
    assert.equal(result.faded,'true');
    assert.match(result.retained,/SAVE_ACTIVE_MEMORY: active_memory_1/);
    assert.equal(result.rows,1);
    console.log('PASS: save completion key, faded DOM state, counter preservation, single bubble');
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exitCode=1;});
