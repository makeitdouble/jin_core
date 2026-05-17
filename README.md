# JIN Core Engine

Локальный FastAPI-хост для JIN Core Engine: веб-панель, WebSocket-чат и мост к двум OpenAI-compatible inference nodes.

Проект сейчас работает как тонкий orchestrator:

1. принимает сообщение из браузера;
2. при необходимости переводит RU -> EN через service node;
3. собирает XML-контракт контекста;
4. отправляет payload в brain node или service fallback;
5. при необходимости переводит ответ EN -> RU;
6. возвращает финальный текст и диагностические логи в веб-интерфейс.

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

## Текущая структура

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

### `app.py`

Главная точка входа приложения.

Отвечает за:

- создание FastAPI-приложения;
- подключение `templates/` и `static/`;
- маршрут `GET /` для веб-панели;
- маршрут `GET /api/status` для проверки доступности brain/service nodes;
- WebSocket `/ws/chat` для основного чата;
- сборку `ContextContract`;
- вызов `ask_brain`;
- отправку логов и финального ответа обратно в браузер.

Если файл запускается напрямую, стартует Uvicorn на `127.0.0.1:8000`.

### `config.example.py`

Шаблон конфигурации. Его можно копировать в `config.py` и менять под локальные машины.

Основные настройки:

- `USE_SERVICE_AS_BRAIN` - использовать service node как основной brain;
- `SERVICE_API_BASE` - базовый URL service node;
- `BRAIN_API_BASE` - базовый URL brain node;
- `CHAT_ENDPOINT` - endpoint chat completions;
- `MODELS_ENDPOINT` - endpoint проверки моделей;
- `SERVICE_MODEL_UID` - модель service node;
- `BRAIN_MODEL_UID` - модель brain node;
- `BRAIN_REQUEST_TIMEOUT`, `SERVICE_BRAIN_TIMEOUT`, `TRANSLATION_TIMEOUT` - таймауты;
- `BRAIN_MAX_TOKENS`, `SERVICE_BRAIN_MAX_TOKENS` - лимиты ответа;
- `SERVICE_BRAIN_COMPACT_PROMPT` - сжимать XML-контракт в простой prompt для service fallback;
- `SERVICE_BRAIN_OUTPUT_LANGUAGE` - язык ответа service fallback;
- `SERVICE_BRAIN_USE_ORIGINAL_INPUT` - использовать исходный RU-ввод в service fallback.

### `config.py`

Локальный рабочий конфиг. В git не должен попадать, потому что содержит адреса локальной сети и реальные model ids.

### `clients/brain_client.py`

Клиент для brain node и fallback-логика.

Внутри:

- `_build_payload` собирает OpenAI-compatible chat payload;
- `_compact_service_brain_prompt` превращает XML-контракт в компактный prompt для слабой service-модели;
- `_ask_model` отправляет HTTP-запрос к модели;
- `ask_brain` выбирает маршрут:
  - service node как brain, если `USE_SERVICE_AS_BRAIN = True`;
  - primary brain node, если режим выключен;
  - service fallback, если primary brain node упал.

Возвращает либо текст модели, либо строку ошибки с префиксом `[QWEN_ERROR: ...]` / `[SERVICE_BRAIN_ERROR: ...]`.

### `clients/service_client.py`

Клиент для переводов через service node.

Внутри:

- `_post_translation` отправляет запрос, делает retry и форматирует ошибку;
- `translate_ru_to_en` переводит пользовательский ввод с русского на английский;
- `translate_en_to_ru` переводит ответ brain node обратно на русский.

Если перевод не удался, возвращается строка с префиксом `[TRANSLATION_ERROR: ...]`.

### `clients/errors.py`

Единый форматтер ошибок HTTP-клиентов.

Добавляет в текст ошибки:

- stage;
- тип исключения;
- URL;
- model id;
- repr ошибки;
- HTTP status и первые 500 символов body, если это `httpx.HTTPStatusError`.

### `clients/url_utils.py`

Маленькая утилита `join_url(base, endpoint)`, чтобы безопасно склеивать base URL и endpoint без двойных или пропущенных слешей.

### `contracts/context_contract.py`

Контракт контекста для brain node.

Класс `ContextContract` принимает:

- `user_input` - активный пользовательский ввод, обычно EN после перевода;
- `original_user_input` - исходный пользовательский ввод;
- `compressed_history` - сжатая память/история, пока пустая;
- `system_state` - состояние runtime.

Метод `to_xml()` возвращает XML-подобный payload с системной идентичностью, runtime state, timestamp, памятью и пользовательским вводом.

Перед вставкой в XML пользовательские поля проходят через `xml.sax.saxutils.escape`.

### `memory/memory.py`

Заготовка под будущую память. Сейчас файл пустой и в runtime не используется.

### `templates/index.html`

Основной HTML веб-панели.

Содержит:

- верхнюю строку статуса проекта;
- индикаторы `BRAIN` и `SERVICE`;
- левую консоль логов;
- центральный чат;
- форму ввода;
- кнопку выбора файлов;
- правую панель настроек-заглушку;
- inline JS для WebSocket-чата.

Стили сейчас подключаются через Tailwind CDN.

### `static/status.js`

Периодически опрашивает `/api/status` и обновляет индикаторы доступности:

- `BRAIN: ONLINE/OFFLINE`;
- `SERVICE: ONLINE/OFFLINE`.

Первый запрос выполняется сразу, затем повторяется каждые 30 секунд.

### `static/dragdrop.js`

Обрабатывает drag-and-drop файлов в центральную область чата.

Сейчас файлы:

- добавляются в локальный список `droppedFiles`;
- синхронизируются с `<input type="file">`;
- отображаются под формой;
- логируются в browser console.

На backend они пока не отправляются.

## Поток сообщения

```text
Browser
  -> WebSocket /ws/chat
  -> app.py
  -> optional translate_ru_to_en()
  -> ContextContract.to_xml()
  -> ask_brain()
  -> brain node or service fallback
  -> optional translate_en_to_ru()
  -> WebSocket response
  -> Browser
```

## Режимы работы

### Service as brain

Если в `config.py`:

```python
USE_SERVICE_AS_BRAIN = True
```

то pipeline пропускает перевод RU -> EN и обратный перевод EN -> RU. Исходный пользовательский текст отправляется в service node как compact prompt.

### Primary brain + service fallback

Если:

```python
USE_SERVICE_AS_BRAIN = False
```

то pipeline:

1. переводит RU -> EN через service node;
2. отправляет XML-контракт в brain node;
3. если brain node падает, пробует service fallback;
4. переводит финальный ответ EN -> RU.

## Текущие ограничения

- Нет `requirements.txt` или `pyproject.toml`.
- Нет автоматических тестов.
- `memory/memory.py` пока пустой.
- Drag-and-drop файлы отображаются на фронте, но не отправляются на backend.
- Tailwind подключен через CDN, поэтому внешний вид зависит от доступности сети.
- В HTML/JS есть места с `innerHTML`; если туда попадут пользовательские данные, это надо заменить на безопасную сборку DOM через `textContent`.
