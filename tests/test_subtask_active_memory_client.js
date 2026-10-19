const fs = require('fs');
const assert = require('assert/strict');
const {chromium} = require('playwright');
(async () => {
  const browser = await chromium.launch({channel:'msedge', headless:true});
  try {
    const page = await browser.newPage();
    await page.setContent('<div id="memory-panel"><div class="memory-scroll"><div id="runtime-memory-text"></div></div></div><span id="runtime-memory-position"></span>');
    for (const file of ['jin-ui-utils.js', 'runtime/runtime-core.js', 'runtime/runtime-memory-model.js', 'runtime/runtime-memory-view.js']) {
      await page.addScriptTag({content: fs.readFileSync('ui/static/js/'+file,'utf8')});
    }
    await page.evaluate(() => {
      window.records = [
        'active_memory_2: child note [ id: SUB-AM-abcdef ] [ owner_subtask_agent_id: child ] [ subtask_memory_label: sub5_active_memory_3 ] [ status: pending ] [ updated_at: 2026-10-19 ]',
        'active_memory_1: parent note [ id: AM-123abc ] [ status: pending ] [ updated_at: 2026-10-18 ]',
      ];
      JinRuntime.memoryView.init({history:{snapshots:[],index:0},idle:{configure(){},stop(){}},
        memoryModel:JinRuntime.memoryModel, getActiveMemoryRecords:()=>records,
        getDisplayMode:()=> 'active',setDisplayMode(){}});
    });
    const rows = page.locator('#runtime-memory-text .runtime-memory-line');
    assert.equal(await rows.count(), 2);
    assert.equal(await rows.nth(0).getAttribute('data-active-memory-id'), 'AM-123abc');
    assert.equal(await rows.nth(1).getAttribute('data-active-memory-id'), 'SUB-AM-abcdef');
    assert.equal(await rows.nth(1).locator('.runtime-memory-key').textContent(), 'sub5_active_memory_3:');
    await rows.nth(1).hover();
    await page.evaluate(() => { records = records.filter(row=>!row.includes('SUB-AM-')); JinRuntime.memoryView.render(); });
    assert.equal(await rows.count(), 1);
    assert.equal(await rows.nth(0).getAttribute('data-active-memory-id'), 'AM-123abc');
    console.log('Subtask Active DOM: label, ID, parent-first order, hover and cleanup passed');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
