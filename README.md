# JIN Core Engine

Локальный FastAPI-хост для веб-чата JIN Core Engine и моста к двум OpenAI-compatible inference nodes: service node и brain node.

## Основной поток

Проект держит один фиксированный message pipeline:

1. Пользователь пишет сообщение в чат на русском языке.
2. Backend отправляет русский текст на service node.
3. Лёгкая модель service node переводит RU -> EN.
4. Backend собирает `ContextContract` с английским `ACTIVE_USER_INPUT`.
5. Английский payload уходит на brain node.
6. Brain node формирует ответ на английском.
7. Английский ответ возвращается на service node.
8. Service node переводит EN -> RU.
9. Русский ответ отправляется обратно в чат.

Сейчас большая brain LLM отключена. Пока `USE_SERVICE_AS_BRAIN = True`, её роль эмулирует service node, но форма потока не меняется: перевод RU -> EN всё равно выполняется до “мозга”, а перевод EN -> RU всё равно выполняется после него.

## Быстрый старт

Создай локальный конфиг из примера:

```powershell
Copy-Item config.example.py config.py
```

Проверь адреса inference nodes и model ids в `config.py`, затем запусти:

```powershell
python app.py
```

После запуска открой:

```text
http://127.0.0.1:8000
```

Нужные Python-зависимости по текущему коду:

```text
fastapi
uvicorn
httpx
jinja2
```

Отдельного `requirements.txt` пока нет.

## Структура

```text
jin_core/
|-- app.py
|-- config.example.py
|-- config.py
|-- clients/
|   |-- brain_client.py
|   |-- service_client.py
|   |-- errors.py
|   `-- url_utils.py
|-- contracts/
|   `-- context_contract.py
|-- memory/
|   `-- memory.py
|-- static/
|   |-- status.js
|   `-- dragdrop.js
|-- templates/
|   `-- index.html
`-- README.md
```

## Ключевые файлы

`app.py`:

- принимает WebSocket-сообщения из чата;
- всегда запускает перевод RU -> EN через `translate_ru_to_en`;
- собирает XML-контракт контекста;
- отправляет английский payload в `ask_brain`;
- всегда запускает перевод EN -> RU через `translate_en_to_ru`;
- возвращает финальный русский текст в чат.

`clients/service_client.py`:

- содержит клиент service node;
- переводит пользовательский ввод RU -> EN;
- переводит ответ мозга EN -> RU;
- возвращает `[TRANSLATION_ERROR: ...]`, если перевод не удался.

`clients/brain_client.py`:

- отправляет payload в brain node, когда `USE_SERVICE_AS_BRAIN = False`;
- отправляет payload на service node как brain emulator, когда `USE_SERVICE_AS_BRAIN = True`;
- в режиме эмуляции использует уже переведённый английский `ACTIVE_USER_INPUT`;
- требует от эмулятора английский ответ, чтобы последующий EN -> RU hook оставался обязательной частью потока.

`contracts/context_contract.py`:

- хранит системную идентичность, runtime state, timestamp, compressed history, английский активный ввод и оригинальный русский ввод;
- экранирует пользовательские поля перед вставкой в XML-подобный контракт.

`config.py` / `config.example.py`:

- `USE_SERVICE_AS_BRAIN` включает временную эмуляцию мозга на service node;
- `SERVICE_API_BASE` и `BRAIN_API_BASE` задают адреса узлов;
- `SERVICE_MODEL_UID` и `BRAIN_MODEL_UID` задают модели;
- таймауты, лимиты токенов и температуры управляют HTTP-запросами и генерацией.

В конфиге нет настройки языка ответа: язык задаётся архитектурой пайплайна, а не переключателем.

## Режимы

### Service as brain

```python
USE_SERVICE_AS_BRAIN = True
```

Фактический маршрут:

```text
Chat RU
  -> service translate RU -> EN
  -> service brain emulator answers EN
  -> service translate EN -> RU
  -> Chat RU
```

### Primary brain

```python
USE_SERVICE_AS_BRAIN = False
```

Фактический маршрут:

```text
Chat RU
  -> service translate RU -> EN
  -> brain node answers EN
  -> service translate EN -> RU
  -> Chat RU
```

Если primary brain node падает, `clients/brain_client.py` пробует service node как fallback brain emulator. Даже в этом fallback финальный ответ остаётся английским до обязательного обратного перевода.

## Ограничения

- Нет `requirements.txt` или `pyproject.toml`.
- Нет автоматических тестов.
- `memory/memory.py` пока пустой.
- Drag-and-drop файлы отображаются на фронтенде, но не отправляются на backend.
- Tailwind подключён через CDN, поэтому внешний вид зависит от доступности сети.
- В HTML/JS есть места с `innerHTML`; если туда попадут пользовательские данные, их стоит заменить на безопасную сборку DOM через `textContent`.
