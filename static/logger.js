const consoleStream = document.getElementById('console-stream');

// Функция добавления логов в левую консоль
function appendLog(tag, message) {
  const logDiv = document.createElement('div');

  logDiv.className = 'whitespace-pre-wrap mb-1';

  let tagClass = 'text-zinc-500';

  if (tag.includes('BEFORE')) tagClass = 'text-amber-500';
  if (tag.includes('BRAIN')) tagClass = 'text-pink-500';
  if (tag.includes('SERVICE')) tagClass = 'text-blue-500';
  if (tag.includes('AFTER')) tagClass = 'text-purple-500';
  if (tag.includes('SYSTEM')) tagClass = 'text-emerald-500';

  if (tag.includes('ERROR')) {
    tagClass = 'text-red-500 font-bold';
    logDiv.classList.add('font-mono', 'text-[12px]', 'bg-red-500/5', 'p-1', 'rounded');
  }

  logDiv.innerHTML = "";

  const tagSpan =
    document.createElement("span");

  tagSpan.className =
    tagClass;

  tagSpan.textContent =
    tag;

  logDiv.appendChild(
    tagSpan
  );

  logDiv.appendChild(
    document.createTextNode(
      "\n" + message
    )
  );

  consoleStream.appendChild(logDiv);
  consoleStream.scrollTop = consoleStream.scrollHeight;
}

window.appendLog = appendLog;
