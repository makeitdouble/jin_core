const fs = require('fs');
const assert = require('assert/strict');
const {chromium} = require('playwright');

(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage();
    await page.route('http://bubble.test/**', route => route.fulfill({
      contentType: 'text/html',
      body: '<div id="chat-history"><div class="jin-message-row"><div class="jin-chat-bubble jin-chat-bubble-brain"><span class="jin-chat-bubble-skin"></span><pre class="jin-chat-pre">Test answer</pre></div></div></div>',
    }));
    await page.goto('http://bubble.test');
    for (const file of ['chat.css', 'chat-bamboo.css']) {
      await page.addStyleTag({content: fs.readFileSync(`ui/static/css/${file}`, 'utf8')});
    }
    const theme = fs.readFileSync('ui/static/js/win95-theme.js', 'utf8');
    await page.addScriptTag({content: theme});
    async function check(skin, custom) {
      const state = await page.evaluate(skin => {
        JinAppearance.setBubbleSkin(skin);
        const bubble = document.querySelector('.jin-chat-bubble');
        const style = getComputedStyle(bubble);
        return {top: style.marginTop, left: style.marginLeft,
          backing: getComputedStyle(bubble.firstElementChild).display,
          inset: getComputedStyle(bubble.firstElementChild).inset,
          custom: document.body.classList.contains('custom-theme-bubble'),
          standard: document.body.classList.contains('default-theme-bubble')};
      }, skin);
      assert.deepEqual(state, {top: '0px', left: '0px',
        backing: custom ? 'block' : 'none', inset: custom ? '-10px' : 'auto', custom, standard: !custom});
    }
    await check('dark', false);
    await check('bamboo', true);
    await check('light', false);
    await check('bamboo', true);
    await page.reload();
    await page.addScriptTag({content: theme});
    assert.equal(await page.evaluate(() => document.body.classList.contains('custom-theme-bubble')), true);
    assert.equal(await page.evaluate(() => JinAppearance.getBubbleSkin()), 'bamboo');
    console.log('PASS: default/custom computed margins, backing, live switching and persisted reload');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
