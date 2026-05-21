![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-Async-009688.svg)
![WebSocket](https://img.shields.io/badge/WebSocket-Streaming-orange.svg)
![Architecture](https://img.shields.io/badge/Architecture-Layered_Runtime-7c3aed.svg)
![Status](https://img.shields.io/badge/Status-Experimental-ef4444.svg)

# JIN Core Engine

> Experimental local AI orchestration runtime focused on streaming inference, layered pipelines, runtime observability, and future autonomous systems.

---

# Overview

JIN Core Engine is an experimental AI runtime built around the idea that modern local AI systems should behave less like a monolithic chatbot and more like a layered orchestration environment.

Instead of routing every request through a single opaque layer, JIN separates responsibilities into isolated runtime components:

- translator runtime
- service runtime
- reasoning runtime
- telemetry layer
- stream validation layer
- frontend rendering layer

The architecture is intentionally infrastructure-first:

- streaming-first
- runtime-aware
- modular
- telemetry-driven
- orchestration-oriented
- future-agent compatible

The current runtime already supports:

- dual-runtime routing
- streaming generation
- thinking stream rendering
- translation-aware pipelines
- runtime telemetry
- WebSocket orchestration
- stream validation
- layered execution flow
- isolated runtime utilities
- experimental memory foundations

---

# Architecture

```text
                        ┌─────────────────┐
                        │     USER UI     │
                        │  WebSocket Chat │
                        └────────┬────────┘
                                 │
                                 ▼

                    ┌────────────────────────┐
                    │   WEBSOCKET RUNTIME    │
                    │ websocket.py           │
                    └────────┬───────────────┘
                             │
                             ▼

                ┌────────────────────────────┐
                │      PIPELINE FACTORY      │
                │ pipeline_factory.py        │
                └───────┬───────────┬────────┘
                        │           │

         translation route          standard route
                        │           │
                        ▼           ▼

        ┌────────────────────┐   ┌────────────────────┐
        │ TranslationPipeline│   │  ServicePipeline   │
        └─────────┬──────────┘   └─────────┬──────────┘
                  │                        │
                  ▼                        ▼

        ┌────────────────────┐   ┌────────────────────┐
        │ Translator Runtime │   │  Service Runtime   │
        └─────────┬──────────┘   └─────────┬──────────┘
                  │                        │
                  ▼                        ▼

                     ┌────────────────────┐
                     │ Reasoning Runtime  │
                     │ generation layer   │
                     └─────────┬──────────┘
                               │
                               ▼

                     ┌────────────────────┐ 
                     │  Stream Validator  │
                     └─────────┬──────────┘
                               │
                               ▼

                     ┌────────────────────┐
                     │  Stream Handler    │
                     │ lifecycle manager  │
                     └─────────┬──────────┘
                               │
                               ▼

                     ┌────────────────────┐
                     │ Frontend Renderer  │
                     │ think + answer UI  │
                     └────────────────────┘
```

---

# Runtime Philosophy

JIN Core is intentionally built around strict separation of responsibilities.

```text
translation != reasoning
reasoning != orchestration
orchestration != rendering
rendering != telemetry
telemetry != memory
```

Every subsystem is designed to evolve independently without collapsing the runtime into a single tightly-coupled layer.

The long-term direction is closer to:

- AI runtime infrastructure
- orchestration middleware
- reactive AI systems
- autonomous execution environments

rather than a traditional chatbot application.

---

# Runtime Layers

```text
user input
    ↓
pipeline routing
    ↓
translation layer
    ↓
context contracts
    ↓
reasoning runtime
    ↓
stream validation
    ↓
runtime telemetry
    ↓
frontend rendering
```

---

# Streaming Lifecycle

JIN Core uses a streaming-first architecture.

Every generated response follows a structured lifecycle:

```text
message_start
    ↓
thinking_chunk
    ↓
message_chunk
    ↓
message_end
```

This architecture allows:

- live token streaming
- reasoning visualization
- partial rendering
- validator interception
- telemetry synchronization
- future hook injection

The runtime is intentionally structured so future systems can intercept generation at any stage.

---

# Thinking Stream

The frontend renders reasoning and final output independently.

The `<think>` stream is displayed separately from the final response and can be dynamically collapsed inside the UI.

This creates a foundation for:

- reasoning inspection
- chain-of-thought visualization
- autonomous debugging
- future planning systems
- runtime introspection

---

# Runtime Telemetry

Telemetry is treated as a first-class runtime subsystem.

Each runtime maintains observable internal state:

```text
- runtime id
- runtime label
- token usage
- context usage
- runtime status
- last runtime error
```

Telemetry is synchronized through WebSocket updates and rendered live inside the frontend control panel.

The runtime is intentionally observable instead of behaving like a black box.

---

# Stream Validation

JIN Core contains a dedicated stream validation layer.

Current protections include:

- repeated word loop detection
- repeated sentence detection
- repeated paragraph detection

Validation occurs during live streaming and can interrupt broken generation before the frontend collapses into repetition loops.

---

# Translation Runtime

Translation is intentionally isolated from reasoning.

Current flow:

```text
user input
    ↓
translation runtime
    ↓
reasoning runtime
    ↓
optional reverse translation
```

This separation allows:

- independent translator swapping
- multilingual experimentation
- cleaner reasoning contexts
- translation benchmarking
- reduced prompt contamination

---

# Memory Foundations

The project already contains early memory infrastructure:

- abstract memory interface
- local memory backend
- memory decay logic
- relevance scoring
- runtime state synchronization

The current memory layer is intentionally lightweight and experimental.

Future directions include:

- embeddings
- semantic retrieval
- graph memory
- persistent context assembly
- long-term runtime memory

---

# Frontend

The frontend is intentionally runtime-oriented rather than consumer-oriented.

Current UI capabilities:

- streaming chat
- think rendering
- runtime telemetry
- drag & drop file handling
- runtime status indicators
- structured logging console
- token monitoring

The interface behaves more like a runtime control panel than a standard AI chat UI.

---

# Tech Stack

## Backend

- FastAPI
- Uvicorn
- asyncio
- httpx
- WebSocket API

## Frontend

- Vanilla JavaScript
- TailwindCSS CDN
- Streaming DOM rendering

## Runtime

- local LLM runtimes
- OpenAI-compatible APIs
- streaming inference backends

---

# Quick Start

## Clone Repository

```bash
git clone <repo>
cd jin_core
```

## Install Dependencies

Install project dependencies manually inside your local environment.

---

## Configure Runtime

```bash
cp config.example.py config.py
```

Configure your runtime providers, endpoints, context windows, and runtime behavior inside the local configuration.

---

## Run Server

```bash
uvicorn app:app --reload
```

---

## Open Runtime UI

```text
http://127.0.0.1:8000
```

---

# Design Goals

The project is optimized for:

- runtime experimentation
- orchestration research
- local AI systems
- streaming UX
- modular AI infrastructure
- future autonomous systems

The architecture intentionally prioritizes:

- extensibility over simplicity
- observability over abstraction
- separation over convenience

---

# Roadmap

## Near-Term

- persistent conversation memory
- multimodal ingestion
- file processing pipeline
- runtime hook system
- runtime configuration UI
- improved telemetry
- tool execution layer

## Mid-Term

- vector memory
- semantic retrieval
- autonomous runtime hooks
- reasoning planners
- context compression
- agent task routing

## Long-Term

- autonomous orchestration runtime
- self-maintaining context systems
- distributed runtime nodes
- multi-agent collaboration
- reactive memory graphs
- long-running AI execution environments

---

# Vision

JIN Core is not trying to become another chat wrapper.

The long-term goal is to evolve toward a local AI runtime capable of:

- orchestrating specialized runtimes
- maintaining persistent context
- executing autonomous flows
- exposing internal reasoning state
- operating as a reactive AI environment

The project currently represents an early infrastructure prototype for that direction.

---

# Status

```text
Current Stage:
Experimental Runtime / AI Orchestration Prototype
```
