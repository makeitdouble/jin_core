![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)
![WebSocket](https://img.shields.io/badge/WebSocket-Streaming-orange.svg)
![Vanilla JS](https://img.shields.io/badge/Frontend-Vanilla_JS-f7df1e.svg)

# JIN Core Engine

> Experimental local LLM runtime with a dual-node architecture, live telemetry, translation routing, and a clean WebSocket-driven UI.

---

## Overview

JIN Core Engine is a local orchestration runtime for experimenting with multi-model inference pipelines.

The current architecture separates responsibilities between two independent nodes:

- **Service Node** — lightweight utility model
- **Brain Node** — primary reasoning / generation model

# Current State

The project is currently an MVP runtime skeleton focused on architecture validation and pipeline experimentation.

Already implemented:

- dual-node routing
- translation pipeline
- runtime telemetry
- streaming UI
- WebSocket infrastructure
- modular runtime separation

Not implemented yet:

- persistent memory
- vector database integration
- autonomous hooks
- multimodal ingestion
- file processing pipeline
- tool execution layer
- auth system
- production deployment layer

---

# Tech Stack

## Backend

- FastAPI
- Uvicorn
- httpx
- Jinja2

## Frontend

- Vanilla JavaScript
- Tailwind CDN
- WebSocket API

## LLM Runtime

- LM Studio
- OpenAI-compatible endpoints

---

# Quick Start

## 1. Clone project

```bash
git clone <repo>
cd jin_core
```

---

## 2. Install dependencies

```bash
pip install -r requirements.txt
```

---

## 3. Configure runtime

Create local config:

```bash
cp config.example.py config.py
```

Adjust endpoints and models inside:

```python
SERVICE_MODEL = "gemma"
BRAIN_MODEL = "qwen"
```

---

## 4. Run server

```bash
uvicorn app:app --reload
```

---

## 5. Open UI

```text
http://127.0.0.1:8000
```

---

# Design Philosophy

JIN Core is intentionally being built as a layered runtime instead of a monolithic chatbot.

The long-term goal is to evolve toward:

```text
translation layer
    ↓
memory layer
    ↓
context contracts
    ↓
reasoning layer
    ↓
tool execution
    ↓
autonomous runtime hooks
```

The current codebase is primarily focused on keeping these layers isolated early, before adding complex autonomous behavior.

---

# Status

Current stage:

```text
Architecture Prototype / Runtime Skeleton
```

Main focus right now:

- pipeline stability
- clean separation of layers
- telemetry visibility
- runtime observability
- future extensibility



## Project Structure

```text
├── clients
│   ├── brain_client.py
│   ├── model_client.py
│   ├── service_client.py
│   └── translation_client.py
├── contracts
│   └── context_contract.py
├── memory
│   ├── memory.py
│   └── runtime_state.py
├── pipelines
│   ├── pipeline_factory.py
│   ├── service_pipeline.py
│   └── translation_pipeline.py
├── static
│   ├── chat.js
│   ├── dragdrop.js
│   ├── logger.js
│   ├── socket.js
│   ├── status.js
│   └── telemetry.js
├── templates
│   └── index.html
├── utils
│   ├── brain.py
│   ├── errors.py
│   ├── language.py
│   ├── runtime_state_sync.py
│   ├── telemetry.py
│   ├── text_cleanup.py
│   ├── tokens.py
│   ├── urls.py
│   └── ws_errors.py
├── .gitignore
├── app.py
├── config.example.py
├── config.py
├── logger.py
└── README.md
```

## Core Components

- `app.py` — Main FastAPI / application entrypoint
- `brain_client.py` — Brain orchestration client
- `service_client.py` — Service/backend communication layer
- `model_client.py` — LLM model abstraction layer
- `translation_pipeline.py` — Translation processing pipeline
- `service_pipeline.py` — Service execution pipeline
- `pipeline_factory.py` — Pipeline resolver/factory
- `chat.js` — Frontend chat UI logic
- `index.html` — Frontend interface

## Features

- Modular pipeline architecture
- Translation-aware request flow
- Service / brain separation
- Frontend chat interface
- URL normalization utilities
- Structured logging
- Extensible client abstraction layer
