// NODE_PATH must contain Playwright. No providers or personal data are used.
const fs = require("node:fs");
const assert = require("node:assert/strict");
const { chromium } = require("playwright");

(async () => {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.setContent('<div id="chat-history"></div><div id="chat-input-shell"><input id="user-input"></div><div style="height:3000px"></div>');
    await page.evaluate(() => {
      window.activity = [];
      window.sendSocketMessage = payload => { activity.push(payload); return true; };
      window.handlers = {};
      window.registerSocketMessageHandler = (name, handler) => { handlers[name] = handler; };
      window.handleSocketLTMemoryRestoreResult = () => {};
      window.handleSocketError = () => {};
      window.handleSocketChatMessage = () => {};
    });
    for (const file of [
      "jin-ui-utils.js", "chat-response-formatter.js", "chat-reactions.js", "think-citations.js",
      "chat-reference-ids.js", "chat.js", "chat-attachments.js", "chat-runtime-actions.js",
      "runtime/runtime-idle.js", "socket/event-handlers.js",
    ]) {
      await page.addScriptTag({ content: fs.readFileSync("ui/static/js/" + file, "utf8") });
    }
    await page.mouse.move(50, 50);
    await page.waitForTimeout(300);
    assert(await page.evaluate(() => activity.length > 0));
    let count = await page.evaluate(() => activity.length);
    await page.mouse.wheel(0, 200);
    await page.waitForTimeout(300);
    assert(await page.evaluate(n => activity.length > n, count));
    count = await page.evaluate(() => activity.length);
    await page.evaluate(() => window.scrollTo(0, 500));
    await page.waitForTimeout(300);
    assert.equal(await page.evaluate(() => activity.length), count, "automatic scroll is not USER activity");
    await page.locator("#user-input").fill("hello");
    await page.waitForTimeout(300);
    assert(await page.evaluate(n => activity.length > n, count));
    count = await page.evaluate(() => activity.length);
    await page.evaluate(() => { window.sendSocketMessage = () => false; });
    await page.mouse.move(80, 80);
    await page.waitForTimeout(300);
    await page.evaluate(() => {
      window.sendSocketMessage = payload => { activity.push(payload); return true; };
      window.JinRuntime.idle.flushHeartbeatActivity();
    });
    assert.equal(await page.evaluate(() => activity.length), count + 1, "offline activity survives reconnect");
    const payload = { source_session_id: "heartbeat-room", turns: [{
      user: "", jin: "Heartbeat cat 🐈", heartbeat: true,
      jin_created_at: 1792500000, reasoning: "Autonomous thought",
    }] };
    await page.evaluate(data => handlers.session_bootstrap_chat_tail(data), payload);
    assert(await page.locator("#chat-history").innerText().then(text => text.includes("Heartbeat cat 🐈")));
    assert.equal(await page.locator('[data-user-message-text]').count(), 0);
    assert.equal(await page.locator(".jin-session-restore-divider").count(), 1);
    await page.evaluate(data => handlers.session_bootstrap_chat_tail(data), payload);
    assert.equal(await page.locator(".jin-session-restore-divider").count(), 1);
    // An action-only owner has a boundary but no invented empty bubbles.
    await page.evaluate(() => document.getElementById("chat-history").replaceChildren());
    payload.turns[0].jin = "";
    await page.evaluate(data => handlers.session_bootstrap_chat_tail(data), payload);
    await page.evaluate(data => handlers.session_bootstrap_chat_tail(data), payload);
    assert.equal(await page.locator(".jin-session-restore-divider").count(), 1);
    assert.equal(await page.locator(".jin-message-shell").count(), 0);
    assert.deepEqual(errors, []);
    console.log("PASS: real DOM heartbeat history; pointer/wheel/input activity; automatic scroll; replay");
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
