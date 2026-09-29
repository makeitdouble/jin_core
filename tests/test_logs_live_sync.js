const fs = require('fs');
const assert = require('assert/strict');
const {chromium} = require('playwright');

(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage();
    page.on('pageerror', error => console.error(error));
    await page.setContent('<div id="memory-panel"><div id="runtime-memory-position"></div><div id="runtime-memory-text"></div></div>');
    const source = fs.readFileSync('ui/static/js/runtime/runtime-memory-view.js', 'utf8');
    await page.addScriptTag({content: source.replace('  window.JinRuntime.memoryView = {', `
      getDisplayMode = () => 'logs';
      runtimeMemoryLazyMode = 'logs';
      window.logsTest = {loadArchivedSessions, renderArchivedSessions,
        append: () => runtimeMemoryLazyAppendBatch?.(),
        count: () => archivedSessionCount};
      window.JinRuntime.memoryView = {`)});
    const result = await page.evaluate(async () => {
      let resolveFetch;
      let requests = 0;
      window.fetch = () => {
        requests++;
        return new Promise(resolve => {resolveFetch = resolve;});
      };
      const update = window.JinRuntime.memoryView.applyArchivedSessionUpdate;
      const initial = Array.from({length: 50}, (_, i) => ({session_id: 'old-' + i,
        date: '2026-09-26', created_at: '2026-09-26T12:00:00Z', title: 'Old ' + i}));
      const current = {session_id: 'current', date: '2026-09-29',
        created_at: '2026-09-29T14:04:00Z', title: 'First committed title'};
      const loading = logsTest.loadArchivedSessions();
      update(current); // WebSocket commit arrives during the initial HTTP read.
      resolveFetch({ok: true, json: async () => ({sessions: initial})});
      await loading;
      const initialRows = document.querySelectorAll('.runtime-memory-log-row').length;
      logsTest.append();
      const lazyRows = document.querySelectorAll('.runtime-memory-log-row').length;
      const row = document.querySelector('[data-session-id="current"]');
      update({...current, title: 'New committed FRAME title'});
      update({...current, title: 'New committed FRAME title'});
      const sameNode = row === document.querySelector('[data-session-id="current"]');
      const updated = row.textContent;
      const count = logsTest.count();
      update({...current, session_id: 'next', created_at: '2026-09-29T15:00:00Z'});
      const countAfterNew = logsTest.count();
      const counter = document.getElementById('runtime-memory-position').textContent;
      const date = document.querySelector('.runtime-memory-logs-date').textContent;
      logsTest.renderArchivedSessions(); // Reopening tab uses cached rows.
      return {requests, initialRows, lazyRows, sameNode, updated, count,
        countAfterNew, counter, date};
    });
    assert.equal(result.requests, 1);
    assert.ok(result.initialRows < 51);
    assert.ok(result.lazyRows > result.initialRows);
    assert.equal(result.sameNode, true);
    assert.equal(result.updated, 'New committed FRAME title');
    assert.equal(result.count, 51);
    assert.equal(result.countAfterNew, 52);
    assert.equal(result.counter, '52');
    assert.equal(result.date, '2026-09-29');
    console.log('LOGS DOM: live insert, title update, dedup, HTTP race, lazy rows and cached reopening passed');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
