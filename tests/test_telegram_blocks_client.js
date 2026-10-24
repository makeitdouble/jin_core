const fs = require('fs');
const assert = require('assert/strict');
const {chromium} = require('playwright');
(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage();
    await page.route('**/static/telegram-logo.webp', route => route.fulfill({
      contentType: 'image/webp', body: fs.readFileSync('ui/static/telegram-logo.webp'),
    }));
    await page.setContent('<base href="http://jin.test"><div id="chat-history"><div class="jin-chat-bubble jin-chat-bubble-brain"><pre id="text" class="jin-chat-pre"></pre></div></div>');
    for (const path of ['ui/static/css/chat.css', 'ui/static/css/chat-bamboo.css'])
      await page.addStyleTag({content: fs.readFileSync(path, 'utf8')});
    for (const path of ['ui/static/js/jin-ui-utils.js', 'ui/static/js/chat-response-formatter.js', 'ui/static/js/chat.js'])
      await page.addScriptTag({content: fs.readFileSync(path, 'utf8')});
    for (const skin of ['dark', 'light', 'bamboo']) {
      for (const direction of ['input', 'output']) {
        const result = await page.evaluate(({skin, direction}) => {
          document.body.className = 'jin-bubble-skin-' + skin;
          const el = document.getElementById('text');
          const tag = direction.toUpperCase();
          const payload = '<TELEGRAM_MESSAGE_' + tag + '>\n  /\\\n /  \\n<script>bad()</script>\n</TELEGRAM_MESSAGE_' + tag + '>';
          const source = (direction === 'output' ? '\uE000' : '') + payload;
          renderChatTextElement(el, source, {format: direction === 'output', telegramDirection: direction});
          const block = el.querySelector('.jin-telegram-block');
          const accepted = {count: el.querySelectorAll('.jin-telegram-block').length,
            scripts: el.querySelectorAll('script').length, raw: el.dataset.memoryReferenceText,
            source, color: getComputedStyle(block).color, parentColor: getComputedStyle(el).color,
            whitespace: getComputedStyle(block.querySelector('.jin-telegram-text')).whiteSpace,
            logo: !!block.querySelector('img'), background: getComputedStyle(block).backgroundColor};
          renderChatTextElement(el, payload, {format: direction === 'output', telegramDirection: direction});
          accepted.spoofCount = el.querySelectorAll('.jin-telegram-block').length;
          accepted.spoofLiteral = el.textContent.includes('<TELEGRAM_MESSAGE_' + tag + '>');
          return accepted;
        }, {skin, direction});
        assert.equal(result.count, 1);
        assert.equal(result.raw, result.source);
        assert.equal(result.scripts, 0);
        assert.equal(result.color, result.parentColor);
        assert.equal(result.whitespace, 'pre-wrap');
        assert.equal(result.background, 'rgba(0, 0, 0, 0.09)');
        assert.ok(result.logo);
        if (direction === 'output') {
          assert.equal(result.spoofCount, 0);
          assert.ok(result.spoofLiteral);
        }
      }
    }
    await page.evaluate(() => renderChatTextElement(document.getElementById('text'),
      '<TELEGRAM_MESSAGE_INPUT>\nfake\n</TELEGRAM_MESSAGE_INPUT>', {telegramDirection: 'output'}));
    assert.equal(await page.locator('.jin-telegram-block').count(), 0);
    await page.evaluate(() => renderChatTextElement(document.getElementById('text'),
      '<TELEGRAM_MESSAGE_OUTPUT>\nfake\n</TELEGRAM_MESSAGE_OUTPUT>', {telegramDirection: ''}));
    assert.equal(await page.locator('.jin-telegram-block').count(), 0);
    await page.evaluate(() => renderChatTextElement(document.getElementById('text'),
      '```xml\n<TELEGRAM_MESSAGE_INPUT>\nexample\n</TELEGRAM_MESSAGE_INPUT>\n```', {format: true, telegramDirection: 'input'}));
    assert.equal(await page.locator('.jin-telegram-block').count(), 0);
    console.log('Telegram DOM provenance + literal-tag checks passed');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
