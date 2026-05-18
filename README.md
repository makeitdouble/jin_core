# JIN Core Engine

Локальный runtime-хост для двухузловой LLM-архитектуры.

## Основная идея

Архитектура разделена на два независимых inference-узла:

- service node
- brain node

Service node отвечает за быстрые вспомогательные задачи:

- перевод;
- preprocessing;
- lightweight inference;
- bypass mode.

Brain node отвечает за:

- reasoning;
- code generation;
- planning;
- future memory orchestration.

---

# Runtime Pipeline

## Normal Mode

```text
USER RU INPUT
    ↓
SERVICE NODE
(RU → EN translation)
    ↓
BRAIN PAYLOAD BUILDER
(XML contract)
    ↓
BRAIN NODE
(reasoning / generation)
    ↓
SERVICE NODE
(EN → RU translation)
    ↓
WEBSOCKET UI
```

---

## BYPASS MODE

```text
USER RU INPUT
    ↓
SERVICE NODE
(emulates brain)
    ↓
WEBSOCKET UI
```

В bypass режиме:

- brain считается OFFLINE;
- service node временно работает как brain;
- telemetry отображает BYPASSED state.

---

# Runtime Architecture

## app.py

Главный orchestration layer.

Отвечает за:

- websocket lifecycle;
- runtime pipeline;
- telemetry dispatch;
- frontend communication;
- runtime error routing;
- UI events.

---

## clients/model_client.py

Transport layer.

Содержит:

- ask_model()
- ask_brain_model()
- ask_service_model()

Отвечает за:

- HTTP transport;
- payload delivery;
- response parsing;
- model validation.

---

## clients/brain_client.py

Brain orchestration layer.

Содержит:

- build_brain_payload()
- bypass routing
- ContextContract integration
- brain execution pipeline
- brain exception handling

---

## clients/service_client.py

Translation layer.

Содержит:

- translate_ru_to_en()
- translate_en_to_ru()
- retries
- timeout handling

---

## contracts/context_contract.py

Контракт контекста brain node.

Содержит:

- XML serialization;
- runtime state injection;
- compressed history;
- future memory integration.

---

# Telemetry System

Frontend telemetry работает через единый websocket stream.

Поддерживаются:

- runtime logs;
- token counters;
- model labels;
- OFFLINE state;
- BYPASSED state;
- websocket error events.

---


# Frontend

Frontend построен на:

- Tailwind
- Vanilla JS
- WebSocket API

## UI Panels

### Left Panel

Runtime console:

- hooks;
- logs;
- errors;
- telemetry events.

### Center Panel

Chat runtime:

- live chat;
- token counters;
- model labels;
- drag-and-drop zone.

### Right Panel

Будущая runtime configuration panel.

---

# Runtime UI

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

# Current Project Structure

```text
jin_core/
│
├── README.md
├── app.py
├── config.py
├── config.example.py
├── logger.py
│
├── clients/
│   ├── brain_client.py
│   ├── errors.py
│   ├── model_client.py
│   ├── service_client.py
│   └── url_utils.py
│
├── contracts/
│   └── context_contract.py
│
├── memory/
│   ├── memory.py
│   └── runtime_state.py
│
├── static/
│   ├── dragdrop.js
│   ├── status.js
│   └── telemetry.js
│
└── templates/
    └── index.html
```

## Backend

- FastAPI
- Uvicorn
- httpx
- Jinja2

## Frontend

- Tailwind CDN
- Vanilla JS
- WebSocket API

## Runtime

- LM Studio
- OpenAI-compatible REST API

---

# Local Launch

## 1. Create config

```powershell
Copy-Item config.example.py config.py
```

---

## 2. Configure models

```python
SERVICE_API_BASE =
BRAIN_API_BASE =

SERVICE_MODEL_UID =
BRAIN_MODEL_UID =
```

---

## 3. Start backend

```powershell
python app.py
```

# Planned Features

- autonomous hooks;
- vector memory;
- multimodal ingestion;
- distributed nodes;
- runtime graph execution;
- persistent sessions;
- tool routing;
- live state synchronization.

---
