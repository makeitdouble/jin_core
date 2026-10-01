// Replay server memory events through the real logger and panel DOM in Edge.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const {chromium} = require('playwright');

(async () => {
  const python = process.env.PYTHON || (fs.existsSync('.venv/Scripts/python.exe')
    ? '.venv/Scripts/python.exe' : 'python');
  const events = JSON.parse(execFileSync(python, ['-m', 'tests.test_frame_lt_order', '--events'], {encoding: 'utf8'}));
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setContent('<div id="memory-panel">FRAME / L-T</div><div id="console-stream"></div>');
    await page.addStyleTag({path: 'ui/static/css/base.css'});
    await page.evaluate(() => {
      window.handlers = {};
      window.registerSocketMessageHandler = (name, handler) => { handlers[name] = handler; };
      window.moveLogToBottomWithFlip = node => document.getElementById('console-stream').append(node);
    });
    const logger = fs.readFileSync('ui/static/js/logger/logger.js', 'utf8');
    await page.addScriptTag({content: logger.slice(0, logger.indexOf('function parseValidatorLogPayload('))});
    for (const path of ['logger/trace-modal.js', 'logger/log-entries.js', 'logger/frame-summarizer.js', 'socket/memory.js']) {
      await page.addScriptTag({path: 'ui/static/js/' + path});
    }
    let frameDone = false;
    let sawFrame = false;
    let sawLT = false;
    for (const event of events) {
      await page.evaluate(event => handlers.log(event), event);
      const classes = await page.locator('#memory-panel').getAttribute('class') || '';
      if (event.memory_level === 'FRAME' && event.memory_event === 'summarizer_request') {
        sawFrame = true;
        assert.match(classes, /memory-updating/);
        assert.doesNotMatch(classes, /memory-lt-updating/);
        assert.equal(await page.locator('.jin-lt-sequence-card').count(), 1);
      }
      if (event.memory_level === 'FRAME' && event.memory_event === 'summarizer_response') {
        frameDone = true;
        assert.match(classes, /memory-fading/);
      }
      if (event.memory_level === 'L-T' && event.memory_event === 'summarizer_request') {
        sawLT = true;
        assert.equal(frameDone, true);
        assert.match(classes, /memory-lt-updating/);
        assert.doesNotMatch(classes, /\bmemory-updating\b/);
        assert.equal(await page.locator('.jin-lt-sequence-card').count(), 2);
      }
      if (event.memory_level === 'L-T' && event.memory_event === 'jin_note_applied') {
        assert.match(classes, /memory-lt-success/);
      }
    }
    assert.ok(sawFrame && sawLT && frameDone);
    assert.deepEqual(errors, []);
    console.log('PASS: real server events -> FRAME card/glow -> FRAME complete -> L-T card/glow -> success');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
