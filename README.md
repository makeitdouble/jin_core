# JIN Core Engine

Локальный runtime-хост для JIN Core Engine с двухузловой LLM-архитектурой:

- service node — лёгкая сервисная модель;
- brain node — основная reasoning/codegen модель.

Frontend работает через WebSocket и отображает live telemetry, runtime logs и состояние inference nodes.

---

# Архитектура пайплайна

Текущий pipeline фиксирован и всегда проходит через одинаковые этапы:

```text
USER RU INPUT
    ↓
SERVICE NODE
(RU → EN translation)
    ↓
CONTEXT CONTRACT
(XML payload builder)
    ↓
BRAIN NODE
(reasoning / generation)
    ↓
SERVICE NODE
(EN → RU translation)
    ↓
WEBSOCKET UI
```

Даже при bypass режиме структура пайплайна сохраняется.

---

# Режимы работы

## 1. Normal Brain Mode

```python
USE_SERVICE_AS_BRAIN = False
```

Маршрут:

```text
RU
→ service translate
→ brain generate
→ service translate
→ RU
```

---

## 2. Service Bypass Mode

```python
USE_SERVICE_AS_BRAIN = True
```

Маршрут:

```text
RU
→ service translate
→ service emulate brain
→ service translate
→ RU
```

В этом режиме:
- primary brain отключён;
- telemetry показывает `BYPASSED`;
- service node временно становится brain emulator.

---

# Текущий Runtime UI

Интерфейс уже поддерживает:

- WebSocket streaming;
- live runtime logs;
- telemetry updates;
- brain/service status;
- dynamic token counters;
- drag-and-drop upload UI;
- separate runtime console;
- isolated center chat;
- runtime configuration panel.

---

# Telemetry System

Frontend получает telemetry через WebSocket:

```json
{
  "type": "telemetry",
  "brain": {
    "model": "qwen2.5-coder-14b",
    "used_tokens": 1200,
    "max_tokens": 32768
  },
  "service": {
    "model": "gemma-4-e2b",
    "used_tokens": 220,
    "max_tokens": 8192
  }
}
```

Telemetry обновляет:

- model labels;
- context counters;
- bypass state;
- runtime monitoring UI.

---

# Централизованный Logger

Добавлен отдельный runtime logger:

```text
logger.py
```

Цели:

- убрать размазанные websocket.send_json() по проекту;
- стандартизировать runtime logs;
- разделить:
  - transport layer;
  - logging layer;
  - future hook system.

Планируется:

```text
before_hook_log()
after_hook_log()
system_log()
brain_log()
service_log()
```

---

# Структура проекта

```text
jin_core/
│
├── app.py
├── config.py
├── config.example.py
├── logger.py
├── README.md
│
├── clients/
│   ├── brain_client.py
│   ├── service_client.py
│   ├── errors.py
│   └── url_utils.py
│
├── contracts/
│   └── context_contract.py
│
├── memory/
│   └── memory.py
│
├── static/
│   ├── dragdrop.js
│   ├── status.js
│   └── telemetry.js
│
└── templates/
    └── index.html
```

---

# Основные модули

## app.py

Главный runtime orchestrator.

Отвечает за:

- FastAPI routes;
- WebSocket lifecycle;
- message pipeline;
- telemetry dispatch;
- hook execution;
- frontend communication.

---

## clients/service_client.py

Service node layer.

Содержит:

- RU → EN translation;
- EN → RU translation;
- service inference calls;
- timeout handling;
- translation error handling.

---

## clients/brain_client.py

Brain node layer.

Содержит:

- primary brain requests;
- bypass logic;
- fallback routing;
- brain payload execution.

---

## contracts/context_contract.py

Контракт контекста.

Содержит:

- system identity;
- runtime state;
- compressed history;
- original RU input;
- translated EN input;
- XML serialization.

---

## static/telemetry.js

Frontend telemetry renderer.

Обновляет:

- brain model label;
- service model label;
- token counters;
- bypass state.

---

# Текущие ограничения

Сейчас проект всё ещё является MVP skeleton.

Пока отсутствуют:

- полноценная memory system;
- persistent sessions;
- autonomous hooks;
- real vector memory;
- file ingestion pipeline;
- multimodal processing;
- structured runtime events;
- automatic tool execution;
- production auth layer.

---

# Текущий стек

## Backend

- FastAPI
- Uvicorn
- httpx
- Jinja2

## Frontend

- Tailwind CDN
- Vanilla JS
- WebSocket API

## LLM Runtime

- LM Studio
- OpenAI-compatible REST API
- Local inference nodes

---

# Локальный запуск

## 1. Создать конфиг

```powershell
Copy-Item config.example.py config.py
```

---

## 2. Настроить модели

В `config.py`:

```python
SERVICE_API_BASE =
BRAIN_API_BASE =

SERVICE_MODEL_UID =
BRAIN_MODEL_UID =
```

---

## 3. Запустить backend

```powershell
python app.py
```

---

## 4. Открыть UI

```text
http://127.0.0.1:8000
```

---

# Aider Workflow

Проект тестируется с локальным Aider + LM Studio.

Пример запуска:

```powershell
python -m aider ^
  --model openai/qwen/qwen2.5-coder-14b ^
  --openai-api-base http://127.0.0.1:1234/v1 ^
  --openai-api-key dummy
```

Aider используется как:
- repo-aware coding assistant;
- multi-file editor;
- fast refactor tool.

Полный structural analysis всё ещё лучше делать отдельным review.

---

# Roadmap

Следующий этап:

1. Удаление runtime заглушек.
2. Настоящая telemetry/state system.
3. Hook architecture.
4. Memory pipeline.
5. Runtime state orchestration.
6. Autonomous agent behaviors.
7. Multi-node execution graph.
