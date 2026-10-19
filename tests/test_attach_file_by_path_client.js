// Real attachment DOM, socket, hover/modal, logger and Session Actions; provider-free.
const fs = require('fs');
const assert = require('assert/strict');
const {chromium} = require('playwright');
const PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=';
(async () => {
  const browser = await chromium.launch({channel:'msedge', headless:true});
  try {
    for (const skin of ['dark', 'light', 'bamboo']) {
      const page = await browser.newPage();
      const errors = []; page.on('pageerror', e => errors.push(e.message));
      let available = true;
      await page.route('http://jin.test/**', async route => {
        const url = new URL(route.request().url());
        if (url.pathname === '/') return route.fulfill({contentType:'text/html', body:`<main data-jin-bubble-skin="${skin}"><div id="chat"></div><div id="console"></div></main>`});
        if (!available) return route.fulfill({status:404, body:'unloaded'});
        const image = url.searchParams.get('path') === 'Photo.PNG';
        if (url.searchParams.get('raw')) return route.fulfill({contentType:'image/png', body:Buffer.from(PNG,'base64')});
        return route.fulfill({contentType:'application/json', body:JSON.stringify(image
          ? {name:'Photo.PNG', kind:'image', type:'image/png', data_url:`data:image/png;base64,${PNG}`}
          : {name:'caption.txt', kind:'text', type:'text/plain', text_content:'FULL CAPTION\nUnicode: Привет'})});
      });
      await page.goto('http://jin.test/');
      await page.evaluate(() => { window.registerSocketMessageHandler = () => {}; });
      for (const file of ['jin-ui-utils.js', 'chat-attachments.js', 'chat-runtime-actions.js', 'socket/runtime-actions.js', 'logger/session-actions.js', 'logger/log-entries.js']) {
        await page.addScriptTag({content:fs.readFileSync('ui/static/js/'+file,'utf8')});
      }
      await page.evaluate(() => {
        window.chatHistory = document.getElementById('chat');
        window.consoleStream = document.getElementById('console');
        window.jinConversationTurnCounter = 1;
        window.getRuntimeActionMessageId = data => data.runtime_message_id || '';
        window.fadeRuntimeAction = () => {};
        clearRuntimeActionGuardConfirmation = () => {};
        markRuntimeActionRowCompleted = row => row.dataset.runtimeActionCompleted = 'true';
        reviveRuntimeActionRow = () => {};
        window.appendRuntimeAction = (action, text, options) => {
          let row = document.getElementById(options.id);
          if (!row) {
            row = document.createElement('div'); row.id = options.id;
            row.className = 'jin-runtime-action-row'; row.innerHTML = '<span class="jin-runtime-action-label"></span>';
            chatHistory.append(row);
          }
          updateRuntimeActionRow(row, action, text, options); return row;
        };
        window.pathEvent = (id, path, kind) => {
          const result = {action:'attach_file_by_path', source:'project', ok:true, loaded:true, name:path,
            display_ref:'dataset/'+path, kind, type:kind==='image'?'image/png':'text/plain',
            preview_url:'/api/project-attachment/preview?path='+encodeURIComponent(path)};
          const common = {action:'attach_file_by_path', id, runtime_message_id:'m1', close_tag:true};
          handleRuntimeAction({...common, status:'running', text:'ATTACH_FILE_BY_PATH'});
          handleRuntimeAction({...common, status:'completed', text:'ATTACH_FILE_BY_PATH: dataset/'+path,
            detail:'File: dataset/'+path, attachment_result:result});
          return common;
        };
        pathEvent('image1','Photo.PNG','image'); pathEvent('text1','caption.txt','text');
        const failed = {action:'attach_file_by_path', id:'failed1', runtime_message_id:'m1', status:'failed',
          text:'ATTACH_FILE_BY_PATH: dataset/missing.png : failed - file not exists',
          detail:'Reason: file not exists\nCorrect action schema: <ASSET_ACTION> {"action":"ATTACH_FILE_BY_PATH","path":"dataset/image.png"} </ASSET_ACTION>',
          attachment_result:{action:'attach_file_by_path', ok:false, name:'dataset/missing.png'}};
        handleRuntimeAction(failed);
        log_internal_action('attach_file_by_path', failed);
        handleRuntimeAction({...failed, status:'counter_final', counter_only:true, marker_count:1, text:'ATTACH_FILE_BY_PATH'});
        const history = buildSessionActionRow({parts:[{text:'ATTACH_FILE_BY_PATH: dataset/Photo.PNG',tool_ids:['T1']},
          {text:failed.text,tool_ids:['T3']}],createdAt:Date.now()/1000},0);
        history.id='history'; chatHistory.append(history);
      });
      assert.equal(await page.locator('.jin-runtime-action-row').count(),3);
      assert.match(await page.locator('#failed1').innerText(),/failed - file not exists/);
      assert.match(await page.locator('#failed1').getAttribute('title'),/Correct action schema/);
      assert.match(await page.locator('#history').innerText(),/dataset\/Photo.PNG/);
      assert.match(await page.locator('#console').innerText(),/ATTACH_FILE_BY_PATH/);
      assert.match(await page.locator('#console').innerText(),/file not exists/);
      await page.locator('#image1 .jin-runtime-action-label').hover();
      await page.waitForFunction(() => document.querySelector('.jin-attachment-hover-preview img')?.naturalWidth > 0);
      await page.locator('#image1 .jin-runtime-action-label').click();
      await page.waitForFunction(() => document.querySelector('.jin-attachment-modal-image')?.naturalWidth > 0);
      assert.equal(await page.locator('#jin-attachment-modal').evaluate(e=>e.classList.contains('hidden')),false);
      await page.evaluate(() => document.getElementById('jin-attachment-modal').classList.add('hidden'));
      await page.locator('#text1 .jin-runtime-action-label').click();
      await page.waitForFunction(() => document.querySelector('.jin-attachment-modal-text')?.textContent.includes('FULL CAPTION'));
      assert.match(await page.locator('.jin-attachment-modal-text').innerText(),/Привет/);
      await page.evaluate(() => document.getElementById('jin-attachment-modal').classList.add('hidden'));
      available=false;
      await page.locator('#image1 .jin-runtime-action-label').click();
      await page.waitForFunction(() => document.querySelector('.jin-attachment-modal-text')?.textContent.includes('unloaded'));
      assert.deepEqual(errors,[]);
      await page.close();
    }
    console.log('BY_PATH DOM: three skins, running/completed/failed, counters, Session Actions, real image hover, image/TXT modal, unavailable preview passed');
  } finally { await browser.close(); }
})().catch(e=>{console.error(e); process.exitCode=1;});
