# JIN Core Engine

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-runtime-009688.svg)
![WebSocket](https://img.shields.io/badge/WebSocket-streaming-orange.svg)
![Status](https://img.shields.io/badge/status-experimental-ef4444.svg)

JIN Core Engine - локальный экспериментальный runtime для AI-оркестрации: FastAPI-приложение с WebSocket-чатом, streaming-first обработкой ответов, отдельными runtime-клиентами, telemetry-панелью и ранним агентным контуром.

Проект сейчас ближе к инженерной песочнице runtime-инфраструктуры, чем к обычной chat-wrapper обертке. Главная идея - разделить транспорт, конфигурацию моделей, пайплайны, стриминг, валидацию потока, telemetry и UI так, чтобы каждый слой можно было развивать отдельно.

## Что уже есть

- FastAPI backend с HTML UI на `/` и health/status API на `/api/status`.
- WebSocket endpoint `/ws/chat` для чата, логов, telemetry и отмены активной генерации.
- Единый `httpx.AsyncClient` на lifespan приложения.
- Runtime-клиенты для OpenAI-compatible API (`/v1/chat/completions`, `/v1/models`).
- Раздельные роли runtime: `brain`, `service`, `translator`.
- Переключатель `USE_SERVICE_AS_BRAIN`, позволяющий использовать service-модель как brain-runtime.
- Streaming lifecycle: `message_start`, `thinking_chunk`, `message_chunk`, `message_end`, `message_error`.
- Обработка reasoning/thinking chunks отдельно от финального ответа.
- Runtime telemetry: модели, контекстные окна, token usage, статусы, ошибки.
- Stream validator против повторяющихся слов, предложений, параграфов и стартовых HTML-артефактов.
- Отмена генерации через WebSocket с закрытием активных stream response.
- Ранний агентный runtime: planner -> translator -> brain -> validator.
- Локальные заготовки memory-слоя и runtime state.

## Текущий статус

Аудит от 2026-05-25:

- Проект активно развивается и находится в experimental/prototype стадии.
- Основной рабочий вход - `app.py`.
- Основной backend transport - `websocket.py`.
- Активная маршрутизация пайплайнов находится в `pipelines/pipeline_factory.py`.
- Сейчас кириллический ввод уходит в `AgentPipeline`, остальной ввод - в `BrainPipeline`.
- Старые `TranslationPipeline` и `ServicePipeline` сохранены в коде, но активный `get_pipeline()` их не использует. Они доступны через `get_pipeline_old()`.
- UI работает на vanilla JS + Tailwind CDN, без frontend build step.
- В репозитории пока нет `requirements.txt` или `pyproject.toml`.
- В части шаблонов и JS есть mojibake-артефакты после проблем с кодировкой. Это не архитектурный блокер, но первый кандидат на ближайший клининг.

## Архитектура

```text
Browser UI
    |
    v
FastAPI app.py
    |
    +-- GET /              -> templates/index.html
    +-- GET /api/status    -> checks brain/service/translator providers
    +-- WS  /ws/chat       -> streaming chat runtime
                                  |
                                  v
                         pipelines/pipeline_factory.py
                                  |
                    +-------------+-------------+
                    |                           |
                    v                           v
              AgentPipeline                BrainPipeline
        Cyrillic input path             default input path
                    |                           |
                    v                           v
        AgentRuntime nodes              RuntimeStream
   planner -> translator -> brain             |
             -> validator                     v
                                      RuntimeClient.stream()
                                              |
                                              v
                                  OpenAI-compatible backend
```

## Основные слои

### App layer

- `app.py` создает FastAPI-приложение.
- На старте приложения создается общий `httpx.AsyncClient`.
- Через `build_clients()` собираются runtime-клиенты.
- `/api/status` проверяет доступность provider endpoints через `MODELS_ENDPOINT`.

### WebSocket layer

- `websocket.py` принимает соединение на `/ws/chat`.
- Для каждого подключения создается `RuntimeContext`.
- Контекст хранит WebSocket, emitter, logger, clients и active stream responses.
- Сообщение типа `abort` отменяет текущую задачу и закрывает активные потоки.
- Параллельная генерация на одном подключении блокируется.

### Pipeline layer

- `pipelines/pipeline_factory.py` выбирает пайплайн по входному тексту.
- `BrainPipeline` отправляет запрос напрямую в brain-runtime.
- `AgentPipeline` запускает агентный граф: planner, translation, brain, validation.
- `TranslationPipeline` и `ServicePipeline` пока выглядят как legacy/альтернативный путь.

### Runtime layer

- `runtime/runtime_client.py` формирует payload для OpenAI-compatible chat completions.
- `runtime/runtime_stream.py` оборачивает генератор chunks в общий stream lifecycle.
- `runtime/runtime_context.py` задает объект контекста для runtime-операций.
- `runtime/runtime_registry.py` содержит общий `RuntimeState`.

### Stream layer

- `utils/stream_handler.py` отправляет stream-события во frontend.
- `utils/response_extractor.py` вытаскивает usage, thinking, content и finish reason из provider chunks.
- `utils/stream_validator.py` фильтрует повторы и некоторые provider/UI артефакты.
- `utils/runtime_state_sync.py` синхронизирует usage и telemetry.

### Frontend layer

- `templates/index.html` - основной UI.
- `static/socket.js` - WebSocket lifecycle, отправка, abort, обработка событий.
- `static/chat.js` - рендер обычных и streaming сообщений.
- `static/status.js` - provider status indicators.
- `static/telemetry.js` - runtime telemetry panel.
- `static/logger.js` - runtime console.
- `static/dragdrop.js` - drag and drop attachments UI.

## Структура проекта

```text
.
├── app.py                         # FastAPI app, routes, lifespan
├── websocket.py                   # WebSocket runtime loop
├── websocket_logger.py            # JSON logs into UI console
├── config.example.py              # local runtime config template
├── agents/                        # early agent runtime nodes
├── clients/                       # provider-specific helper clients
├── contracts/                     # context contract objects
├── emitter/                       # WebSocket JSON emitter
├── memory/                        # early memory abstractions
├── pipelines/                     # routing and pipeline flows
├── runtime/                       # runtime client/context/stream/state
├── settings/                      # typed settings wrapper over config.py
├── static/                        # frontend JavaScript
├── templates/                     # HTML UI
└── utils/                         # stream, telemetry, errors, language helpers
```

## Быстрый старт

### 1. Создать окружение

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Linux/macOS:

```bash
source .venv/bin/activate
```

### 2. Установить зависимости

Файл зависимостей пока не зафиксирован. Минимальный набор для запуска текущего backend:

```bash
pip install fastapi uvicorn httpx jinja2 python-multipart
```

`python-multipart` нужен не для текущего core flow, но обычно полезен для FastAPI-проектов с файловым вводом. Когда появится `requirements.txt` или `pyproject.toml`, запуск стоит перевести на него.

### 3. Создать локальный конфиг

```bash
cp config.example.py config.py
```

Windows PowerShell:

```powershell
Copy-Item config.example.py config.py
```

### 4. Настроить runtime providers

В `config.py` нужно указать OpenAI-compatible endpoints и model ids:

```python
BRAIN_API_BASE = "http://brain-host:1234"
BRAIN_MODEL_UID = "brain-model"

SERVICE_API_BASE = "http://service-host:1234"
SERVICE_MODEL_UID = "service-model"

TRANSLATOR_API_BASE = "http://translator-host:1234"
TRANSLATOR_MODEL_UID = "translator-model"
```

По умолчанию используются:

```python
CHAT_ENDPOINT = "/v1/chat/completions"
MODELS_ENDPOINT = "/v1/models"
```

Если отдельного brain-runtime нет, можно включить:

```python
USE_SERVICE_AS_BRAIN = True
```

### 5. Запустить сервер

```bash
uvicorn app:app --reload
```

И открыть:

```text
http://127.0.0.1:8000
```

## WebSocket protocol

Frontend отправляет пользовательский ввод:

```json
{
  "text": "Hello"
}
```

Отмена генерации:

```json
{
  "type": "abort"
}
```

Backend отправляет stream events:

```json
{ "type": "message_start", "message_id": "...", "role": "brain" }
{ "type": "thinking_chunk", "message_id": "...", "chunk": "..." }
{ "type": "message_chunk", "message_id": "...", "chunk": "..." }
{ "type": "message_end", "message_id": "...", "text": "..." }
```

Логи runtime приходят как:

```json
{ "type": "log", "tag": "[RUNTIME]", "message": "..." }
```

## Конфигурация

Ключевые параметры `config.py`:

| Параметр | Назначение |
|---|---|
| `USE_SERVICE_AS_BRAIN` | Использовать service-runtime вместо отдельного brain-runtime |
| `BRAIN_API_BASE` | Base URL brain provider |
| `BRAIN_MODEL_UID` | Model id brain provider |
| `BRAIN_CONTEXT_WINDOW` | Контекстное окно brain-runtime |
| `BRAIN_TEMPERATURE` | Температура brain-runtime |
| `BRAIN_MAX_TOKENS` | Лимит генерации brain-runtime |
| `SERVICE_API_BASE` | Base URL service provider |
| `SERVICE_MODEL_UID` | Model id service provider |
| `SERVICE_CONTEXT_WINDOW` | Контекстное окно service-runtime |
| `SERVICE_TEMPERATURE` | Температура service-runtime |
| `SERVICE_MAX_TOKENS` | Лимит генерации service-runtime |
| `TRANSLATOR_API_BASE` | Base URL translator provider |
| `TRANSLATOR_MODEL_UID` | Model id translator provider |
| `TRANSLATION_RETRIES` | Количество retry для translation flow |
| `TRANSLATION_MIN_TOKENS` | Минимальный бюджет перевода |
| `TRANSLATION_MAX_TOKENS` | Максимальный бюджет перевода |

