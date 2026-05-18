# 🧞‍♂️ JIN Core Engine: Архитектура и Спецификация ИИ-агента

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

The system already includes:

- real-time WebSocket streaming
- runtime telemetry
- live logs
- translation routing
- dynamic frontend status updates
- isolated runtime pipeline layers
- configurable brain bypass mode

---

# Runtime Pipeline

Current pipeline flow:

```text
USER INPUT (RU)
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

The pipeline structure remains stable even when the brain node is bypassed.

---

# Runtime Modes

## 1. Normal Brain Mode

```python
USE_SERVICE_AS_BRAIN = False
```

Flow:

```text
RU
→ translation
→ brain generation
→ translation
→ RU
```

In this mode:

- the main reasoning model is active
- service node handles translation and utility work
- telemetry shows active brain execution

---

## 2. Service Bypass Mode

```python
USE_SERVICE_AS_BRAIN = True
```

Flow:

```text
RU
→ translation
→ service emulates brain
→ translation
→ RU
```

In this mode:

- primary brain requests are skipped
- service node temporarily acts as a lightweight brain emulator
- telemetry displays `BYPASSED`

Useful for:

- frontend testing
- latency testing
- pipeline debugging
- offline runtime experiments

---

# Frontend Features

Current UI already supports:

- live WebSocket chat
- streaming responses
- runtime telemetry
- dynamic model labels
- token counters
- runtime console
- drag-and-drop upload area
- centered isolated chat layout
- configuration/status panels

---

# Telemetry System

Frontend telemetry is pushed through WebSocket events.

Example payload:

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

Telemetry currently tracks:

- active models
- token usage
- bypass state
- runtime status
- node activity

---

# Project Structure

```text
jin_core/
│
├── app.py                     # Main FastAPI runtime orchestrator
├── config.py                  # Local runtime configuration
├── config.example.py          # Example configuration template
├── logger.py                  # Runtime logging layer
├── README.md
│
├── clients/
│   ├── brain_client.py        # Brain node execution layer
│   ├── service_client.py      # Translation/service layer
│   ├── model_client.py        # Shared model request helpers
│   ├── errors.py              # Runtime exception definitions
│   └── url_utils.py           # URL and endpoint helpers
│
├── contracts/
│   └── context_contract.py    # XML context payload builder
│
├── memory/
│   ├── memory.py              # Temporary memory layer
│   └── runtime_state.py       # Runtime state container
│
├── static/
│   ├── dragdrop.js            # Upload/drop interactions
│   ├── status.js              # Runtime status renderer
│   └── telemetry.js           # Telemetry renderer
│
└── templates/
    └── index.html             # Main frontend UI
```

---

# Core Modules

## `app.py`

Main runtime orchestrator.

Responsibilities:

- FastAPI routes
- WebSocket lifecycle
- pipeline execution
- telemetry dispatch
- frontend communication
- runtime streaming

---

## `clients/service_client.py`

Service node layer.

Responsibilities:

- RU ↔ EN translation
- lightweight inference calls
- timeout handling
- utility routing

---

## `clients/brain_client.py`

Brain node layer.

Responsibilities:

- primary reasoning requests
- brain execution
- bypass routing
- response generation

---

## `contracts/context_contract.py`

Context contract builder.

Contains:

- system identity
- compressed runtime state
- translated payloads
- XML serialization
- context packaging

---

## `logger.py`

Centralized runtime logging layer.

Goal:

- avoid scattered websocket logging
- standardize runtime events
- separate transport from runtime diagnostics

Planned future hook system:

```text
before_hook_log()
after_hook_log()
system_log()
brain_log()
service_log()
```

---

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
