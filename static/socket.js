// Подключаемся к WebSocket бэкенда
const ws = new WebSocket(`ws://${window.location.host}/ws/chat`);

const chatForm = document.getElementById('chat-form');
const userInput = document.getElementById('user-input');

// Автовысота поля ввода
userInput.addEventListener('input', function() {
  this.style.height = 'auto';
  this.style.height = this.scrollHeight + 'px';
});

// Обработка отправки по Ctrl+Enter
userInput.addEventListener('keydown', function(e) {
  if (e.ctrlKey && e.key === 'Enter') {
    e.preventDefault();
    chatForm.requestSubmit();
  }
});




// Прием данных от сервера
ws.onmessage = function(event) {
  console.log("RAW WS:", event.data);

  const data = JSON.parse(event.data);

  console.log("PARSED WS:", data);

  handleTelemetryMessage(data);

  if (data.type === 'log') {
    appendLog(data.tag, data.message);
  } else if (data.type === 'message') {
    appendChatMessage('jin', data.text);
  }
};

// Отправка формы
chatForm.addEventListener('submit', function(e) {
  e.preventDefault();
  const text = userInput.value.trim();
  if (!text) return;

  // Добавляем реплику юзера на экран
  appendChatMessage('user', text);

  // Шлем по WebSocket
  ws.send(JSON.stringify({ text: text }));

  // Очищаем инпут
  userInput.value = '';
  userInput.style.height = 'auto';
});

ws.onopen = () => appendLog('[SYSTEM]', 'Веб-интерфейс подключен к локальному ядру Jin.');
console.log("WS CONNECTED");
ws.onclose = () => appendLog('[SYSTEM]', 'Критическая ошибка: Соединение с ядром разорвано.');
