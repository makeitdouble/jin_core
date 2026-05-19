const chatHistory = document.getElementById('chat-history');

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// Функция добавления сообщений в центральный чат
function appendChatMessage(role, text) {
  const msgDiv = document.createElement('div');
  msgDiv.className = 'flex items-start gap-3 max-w-3xl';

  const avatar = role === 'user' ? 'US' : 'JN';
  const bgClass = role === 'user' ? 'bg-slate-500 border-slate-400' : 'bg-slate-600 border-slate-500';

  msgDiv.innerHTML = `
            <div class="h-6 w-6 rounded bg-zinc-800 border border-zinc-700 flex items-center justify-center text-[10px] text-zinc-400 shrink-0">${avatar}</div>
            <div class="space-y-1 ${bgClass} p-3 rounded-lg border">
                <pre class="text-zinc-200 leading-relaxed whitespace-pre-wrap overflow-x-auto font-mono text-[13px]">${escapeHtml(text)}</pre>
            </div>
        `;
  chatHistory.appendChild(msgDiv);
  chatHistory.scrollTop = chatHistory.scrollHeight;
}

window.appendChatMessage = appendChatMessage;
