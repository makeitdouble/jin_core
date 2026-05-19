const chatHistory =
  document.getElementById("chat-history");


function escapeHtml(text) {

  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

}


// ROLE CONFIG

function getRoleConfig(role) {

  switch (role) {

    case "user":
      return {
        avatar: "US",
        bgClass:
          "bg-slate-500 border-slate-400"
      };

    case "service":
      return {
        avatar: "SV",
        bgClass:
          "bg-emerald-950/70 border-emerald-700 shadow-[0_0_12px_rgba(16,185,129,0.08)]"
      };

    case "brain":
    default:
      return {
        avatar: "BR",
        bgClass:
          "bg-zinc-800 border-zinc-600 shadow-[0_0_12px_rgba(255,255,255,0.04)]"
      };

  }

}


// CHAT MESSAGE

function appendChatMessage(role, text) {

  const config =
    getRoleConfig(role);

  const msgDiv =
    document.createElement("div");

  msgDiv.className =
    "flex items-start gap-3 max-w-3xl";

  msgDiv.innerHTML = `
        <div class="h-6 w-6 rounded bg-zinc-800 border border-zinc-700 flex items-center justify-center text-[10px] text-zinc-400 shrink-0">
            ${config.avatar}
        </div>

        <div class="${config.bgClass} px-4 py-3 rounded-xl border shadow-sm">
            <pre class="text-zinc-50 leading-relaxed whitespace-pre-wrap overflow-x-auto font-mono text-[13px]">${escapeHtml(text)}</pre>
        </div>
    `;

  chatHistory.appendChild(msgDiv);

  chatHistory.scrollTop =
    chatHistory.scrollHeight;

}


window.appendChatMessage =
  appendChatMessage;
