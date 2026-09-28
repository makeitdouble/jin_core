const fs = require('fs');
const assert = require('assert/strict');
const {chromium} = require('playwright');

const systemPrompt = `Keep the base system rules visible.

<TRUSTED_RUNTIME_VARIABLES>
runtime: ready
</TRUSTED_RUNTIME_VARIABLES>
<SKILLS_LIST>
alpha
</SKILLS_LIST>
<FRAME_MEMORY_2>
focus: tabs
</FRAME_MEMORY_2>
<ACTIVE_MEMORY>
AM-000001 | conditions: now
</ACTIVE_MEMORY>
<LOADED_DELAYED_MEMORY>
report: pinned
</LOADED_DELAYED_MEMORY>
<LONG_TERM_MEMORY>
LT-000001 | preference: compact
</LONG_TERM_MEMORY>
<TOOLS_RESULTS>
<TOOL_RESULT tool_id="T2" name="CHAT_LOG_SEARCH" timestamp="2026-09-28T12:00:00Z"> (1 minute ago)
Status: success
Returned: 0; matching turns: 0; more: false
</TOOL_RESULT>
<TOOL_RESULT name="LEGACY_TOOL">
legacy payload
</TOOL_RESULT>
legacy note outside a result
</TOOLS_RESULTS>
JIN_COLOR
Follow-up: false
schema: paired XML

<UNRECOGNIZED_SYSTEM_CONTEXT>
preserve me
</UNRECOGNIZED_SYSTEM_CONTEXT>`;

const userPrompt = 'hello from the user';
const details = `SYSTEM PROMPT\n----------------\n${systemPrompt}\n\nUSER PROMPT / CONTEXT PAYLOAD\n----------------\n${userPrompt}`;

(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1200, height: 900}});
    await page.setContent('<body style="background:#09090b;color:#ddd;font-family:monospace"></body>');
    await page.addStyleTag({content: fs.readFileSync('ui/static/css/runtime-memory.css', 'utf8')});
    await page.addScriptTag({content: fs.readFileSync('ui/static/js/logger/trace-modal.js', 'utf8')});
    await page.evaluate(() => {
      window.__skin = 'dark';
      window.JinAppearance = {
        getBubbleSkin: () => window.__skin,
        setBubbleSkin: skin => { window.__skin = skin; },
      };
      ensureTraceModal();
    });
    await page.evaluate(details => renderTraceDetails(details, 'Context'), details);

    const initial = await page.evaluate(() => {
      const content = traceModalContent;
      const children = [...content.children];
      const tabs = [...content.querySelectorAll('[role="tab"]')];
      const selected = content.querySelector('[role="tab"][aria-selected="true"]');
      const panel = document.getElementById(selected.getAttribute('aria-controls'));
      return {
        childClasses: children.map(node => node.className),
        labels: tabs.map(node => node.textContent),
        selected: selected.textContent,
        memoryTitles: [...panel.querySelectorAll(':scope > .jin-context-tab-stack > .jin-context-card > .jin-context-card-header .jin-context-card-title')].map(node => node.textContent),
        userText: content.querySelector('.jin-context-user-stack').textContent,
        rulesText: content.querySelector('.jin-context-common-stack').textContent,
        rulesCollapsed: content.querySelector('.jin-context-common-stack > .jin-context-card').classList.contains('is-collapsed'),
        visiblePanels: [...content.querySelectorAll('[role="tabpanel"]')].filter(node => !node.hidden).length,
        overviewText: content.querySelector('.jin-context-overview').textContent,
      };
    });
    assert.equal(initial.selected, 'MEMORY');
    assert.deepEqual(initial.labels, ['MEMORY', 'SYSTEM', 'TOOL RESULTS (2)', 'ACTIONS']);
    assert.equal(initial.visiblePanels, 1);
    assert.doesNotMatch(initial.overviewText, /\bblocks\b|system chars/);
    assert.match(initial.userText, /hello from the user/);
    assert.match(initial.rulesText, /Keep the base system rules visible/);
    assert.equal(initial.rulesCollapsed, true);
    assert.deepEqual(initial.memoryTitles, [
      'FRAME_MEMORY_2', 'ACTIVE_MEMORY', 'DELAYED_MEMORY',
      'LOADED_DELAYED_MEMORY', 'LONG_TERM_MEMORY',
    ]);
    assert.ok(initial.childClasses.indexOf('jin-context-stack jin-context-user-stack') < initial.childClasses.indexOf('jin-context-tabs'));
    assert.ok(initial.childClasses.indexOf('jin-context-tabs') < initial.childClasses.indexOf('jin-context-stack jin-context-common-stack'));
    assert.equal(
      await page.locator('.jin-context-trace-modal .delayed-memory-modal-panel').evaluate(node => getComputedStyle(node).height),
      `${Math.round(900 * 0.86)}px`
    );
    const footerLayout = await page.evaluate(() => {
      const content = document.querySelector('.jin-context-trace-modal .delayed-memory-modal-content');
      const tabs = content.querySelector('.jin-context-tabs');
      const panels = content.querySelector('.jin-context-tab-panels');
      const footer = content.querySelector('.jin-context-common-stack');
      return {
        contentDisplay: getComputedStyle(content).display,
        contentOverflow: getComputedStyle(content).overflow,
        tabsGrow: getComputedStyle(tabs).flexGrow,
        tabsBasis: getComputedStyle(tabs).flexBasis,
        tabListShrink: getComputedStyle(content.querySelector('.jin-context-tab-list')).flexShrink,
        panelsOverflow: getComputedStyle(panels).overflow,
        panelsScrollbarWidth: getComputedStyle(panels).scrollbarWidth,
        userShrink: getComputedStyle(content.querySelector('.jin-context-user-stack')).flexShrink,
        footerShrink: getComputedStyle(footer).flexShrink,
        footerBottom: footer.getBoundingClientRect().bottom,
        contentBottom: content.getBoundingClientRect().bottom,
      };
    });
    assert.equal(footerLayout.contentDisplay, 'flex');
    assert.equal(footerLayout.contentOverflow, 'hidden');
    assert.equal(footerLayout.tabsGrow, '1');
    assert.equal(footerLayout.tabsBasis, '0px');
    assert.equal(footerLayout.tabListShrink, '0');
    assert.equal(footerLayout.panelsOverflow, 'auto');
    assert.equal(footerLayout.panelsScrollbarWidth, 'none');
    assert.equal(footerLayout.userShrink, '0');
    assert.equal(footerLayout.footerShrink, '0');
    assert.ok(footerLayout.contentBottom - footerLayout.footerBottom <= 15);

    await page.locator('.jin-context-collapse-all').click();
    const collapsed = await page.evaluate(() => ({
      all: [...document.querySelectorAll('.jin-context-trace-modal .jin-context-card')].every(node => node.classList.contains('is-collapsed')),
      label: document.querySelector('.jin-context-collapse-all').textContent,
    }));
    assert.equal(collapsed.all, true);
    assert.equal(collapsed.label, 'EXPAND ALL');

    await page.getByRole('tab', {name: 'SYSTEM'}).click();
    assert.equal(await page.locator('.jin-context-collapse-all').textContent(), 'EXPAND ALL');
    const systemText = await page.getByRole('tabpanel', {name: 'SYSTEM'}).textContent();
    assert.match(systemText, /jin_bubble_skin/);
    assert.match(systemText, /runtime: ready/);
    assert.match(systemText, /alpha/);
    assert.match(systemText, /preserve me/);
    await page.getByRole('button', {name: 'bamboo'}).click();
    assert.equal(await page.evaluate(() => window.__skin), 'bamboo');
    assert.equal(await page.getByRole('button', {name: 'bamboo'}).getAttribute('aria-pressed'), 'true');

    await page.getByRole('tab', {name: 'TOOL RESULTS (2)'}).click();
    const toolTitles = await page.evaluate(() => [...document.querySelectorAll('[role="tabpanel"]:not([hidden]) > .jin-context-tab-stack > .jin-context-card > .jin-context-card-header .jin-context-card-title')].map(node => node.textContent));
    assert.deepEqual(toolTitles.slice(0, 2), ['T2 · CHAT_LOG_SEARCH', 'LEGACY_TOOL']);
    assert.match(await page.getByRole('tabpanel', {name: 'TOOL RESULTS (2)'}).textContent(), /legacy note outside a result/);

    await page.getByRole('tab', {name: 'ACTIONS'}).focus();
    await page.keyboard.press('Home');
    assert.equal(await page.getByRole('tab', {name: 'MEMORY'}).getAttribute('aria-selected'), 'true');

    await page.evaluate(details => renderTraceDetails(details, 'Context'), details);
    assert.equal(await page.locator('[role="tablist"]').count(), 1);
    assert.equal(await page.getByRole('tab', {name: 'MEMORY'}).getAttribute('aria-selected'), 'true');
    assert.equal(await page.locator('.jin-context-user-stack').count(), 1);

    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.locator('.jin-context-tab').first().evaluate(node => getComputedStyle(node).whiteSpace), 'nowrap');
    console.log('PASS: context snapshot tabs, grouping, counts, global collapse, settings, keyboard, reopen, narrow tabs');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
