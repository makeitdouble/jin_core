const fs = require('fs');
const assert = require('assert/strict');
const {chromium} = require('playwright');
(async () => {
 const browser = await chromium.launch({channel:'msedge',headless:true});
 try {
  const scenarios = JSON.parse(fs.readFileSync('.tmp/asset-alias-events.json','utf8'));
  scenarios.push(JSON.parse(fs.readFileSync('.tmp/asset-owner-events.json','utf8')));
  for (let i=0;i<scenarios.length;i++) {
   const page=await browser.newPage();
   await page.setContent('<main><div id="chat"></div></main>');
   await page.addScriptTag({content:'window.registerSocketMessageHandler=()=>{}; window.chatHistory=document.getElementById("chat"); window.jinConversationTurnCounter=1;'});
   for(const file of ['jin-ui-utils.js','chat-attachments.js','chat-runtime-actions.js','socket/runtime-actions.js']) await page.addScriptTag({content:fs.readFileSync('ui/static/js/'+file,'utf8')});
   await page.evaluate(events=>events.forEach(e=>handleRuntimeAction(e)),scenarios[i]);
   const rows=await page.locator('.jin-runtime-action-row').allTextContents();
   assert.equal(rows.length,1,JSON.stringify(rows));
   if(i<2) assert.ok(!rows[0].includes('ASSET_ACTION'),rows[0]);
   else {assert.match(rows[0],/Photo.PNG/);assert.match(rows[0],/missing.txt/);}
   await page.close();
  }
  console.log('PASS: actual stream events render one row per operation; no orphan asset or child duplicates');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

