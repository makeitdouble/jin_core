const fs = require('fs');
const assert = require('assert/strict');
const {chromium} = require('playwright');
(async () => {
 const browser = await chromium.launch({channel: 'msedge', headless: true});
 try {
  const page = await browser.newPage();
  await page.setContent('<main><div id="chat"></div></main>');
  await page.addScriptTag({content: 'window.registerSocketMessageHandler = () => {};'});
  for (const file of ['ui/static/js/chat-runtime-actions.js', 'ui/static/js/socket/runtime-actions.js']) {
   await page.addScriptTag({content: fs.readFileSync(file, 'utf8')});
  }
  const result = await page.evaluate(() => {
   window.chatHistory = document.getElementById('chat');
   window.jinConversationTurnCounter = 1;
   window.openedContexts = [];
   window.showContextModal = c => openedContexts.push(c);
   const counts = [];
   for (let i=1; i<=4; i++) {
    const base = {action:'posting_board', id:`posting_board_${i}`, runtime_message_id:`m${i}`,
      runtime_turn_id:'t1', close_tag:true, display_name:'POSTING_BOARD',
      context:{system_prompt:`PROMPT_${i}`, context_role:'brain'}};
    handleRuntimeAction({...base, status:'started', text:'POSTING_BOARD'});
    counts.push(chatHistory.querySelectorAll('.jin-runtime-action-row').length);
    handleRuntimeAction({...base, status:'completed', text:'POSTING_BOARD: action:read',
      posting_board_result:{ok:true, action:'read', response:{body:'BODY'}}, detail:`Result T${i}`});
    handleRuntimeAction({...base, counter_id:`t1:m${i}:posting_board:payload`, status:'counter_final',
      counter_only:true, counter_final:true, aggregate_markers:true, marker_count:1,
      text:'POSTING_BOARD: action:read'});
   }
   const rows = [...chatHistory.querySelectorAll('.jin-runtime-action-row')];
   return {counts, rows:rows.map(row=>({message:row.dataset.runtimeActionRuntimeMessage,
    text:row.textContent, buttons:row.querySelectorAll('button').length}))};
  });
  assert.deepEqual(result.counts, [1,2,3,4]);
  assert.equal(result.rows.length,4);
  assert.deepEqual(result.rows.map(r=>r.message),['m1','m2','m3','m4']);
  result.rows.forEach(r=> {assert.match(r.text,/action:read/); assert.ok(r.buttons>0);});
  console.log('PASS actual socket/render path: four attempts visible before Stop with separate context buttons');
 } finally {await browser.close();}
})().catch(e=>{console.error(e); process.exitCode=1;});
