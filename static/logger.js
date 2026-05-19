const chatHistory = document.getElementById('chat-history');
const consoleStream = document.getElementById('console-stream');

// Функция добавления сообщений в центральный чат
function appendChatMessage(role, text) {
  const msgDiv = document.createElement('div');
  msgDiv.className = 'flex items-start gap-3 max-w-3xl';

  const avatar = role === 'user' ? 'US' : 'JN';
  const bgClass = role === 'user' ? 'bg-slate-500 border-slate-400' : 'bg-slate-600 border-slate-500';

  msgDiv.innerHTML = `
            <div class="h-6 w-6 rounded bg-zinc-800 border border-zinc-700 flex items-center justify-center text-[10px] text-zinc-400 shrink-0">${avatar}</div>
            <div class="space-y-1 ${bgClass} p-3 rounded-lg border">
                <p class="text-zinc-200 leading-relaxed">${text}</p>
            </div>
        `;
  chatHistory.appendChild(msgDiv);
  chatHistory.scrollTop = chatHistory.scrollHeight;
}

// Функция добавления логов в левую консоль
function appendLog(tag, message) {
  const logDiv = document.createElement('div');

  logDiv.className = 'whitespace-pre-wrap mb-1';

  let tagClass = 'text-zinc-500';

  if (tag.includes('BEFORE')) tagClass = 'text-amber-500';
  if (tag.includes('BRAIN')) tagClass = 'text-blue-500';
  if (tag.includes('AFTER')) tagClass = 'text-purple-500';
  if (tag.includes('SYSTEM')) tagClass = 'text-emerald-500';
  if (tag.includes('STATUS')) tagClass = 'p-2 rounded border border-zinc-800 bg-zinc-900/60 text-zinc-500 overflow-x-auto';

  if (tag.includes('ERROR')) {
    tagClass = 'text-red-500 font-bold';
    logDiv.classList.add('font-mono', 'text-[12px]', 'bg-red-500/5', 'p-1', 'rounded');
  }

  logDiv.innerHTML = `<span class="${tagClass}">${tag}</span>\n${message}`;

  consoleStream.appendChild(logDiv);
  consoleStream.scrollTop = consoleStream.scrollHeight;
}

window.appendLog = appendLog;
window.appendChatMessage = appendChatMessage;
