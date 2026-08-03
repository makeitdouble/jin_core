# JIN Core Engine

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-runtime-009688.svg)
![WebSocket](https://img.shields.io/badge/WebSocket-streaming-orange.svg)
![OpenAI Compatible](https://img.shields.io/badge/API-OpenAI--compatible-111827.svg)
![Tests](https://github.com/makeitdouble/jin_core/actions/workflows/tests.yml/badge.svg)

**JIN Core Engine** is a local AI runtime for OpenAI-compatible models with visible memory, visible reasoning traces, and inspectable session state.
Without context, there is no **JIN**, only a generic response engine. **JIN Core Engine** is what makes this interaction **last**.

### 3-Layer Memory + Runtime-Owned Channels
JIN uses short-term continuity to dynamically guide conversation strategy:

* **L1 (Live Facts):** Actionable session state kept in active process memory.
* **L2 (Patterns):** Tracks interaction loops and repetition counters to adapt prompts on the fly.
* **L3 (Digest):** Compressed session snapshots serialized to browser `localStorage` and replayed on reconnect.
* **Active Memory:** Runtime-owned pending contracts for reminders, ask-later conditions, and recall games.
* **Delayed Memory:** Structured reports saved separately and appended into a session only when requested.
* **Facts Memory:** A session-scoped browser index of durable L1 fields that remains inspectable outside the live snapshot.

*Every memory update is captured as a versioned snapshot with diff highlights, fully inspectable in the right-side timeline panel.*

## UI Preview

### Runtime Workspace

![JIN Core Engine runtime UI dark theme](ui/static/images/jin-core-default-theme.jpg)

Main runtime view: chat, live avatar, telemetry, and inspectable memory panels in one browser workspace.

### Memory Timeline

![Runtime memory snapshot timeline](ui/static/images/runtime-highlight.png)

Runtime memory snapshots can be stepped through visually, with new or changed facts highlighted in the sidebar.

### Reasoning Citations

![Think citation highlighting](ui/static/images/think-highlight.jpg)

Think citation highlighting shows where reasoning quotes rules, runtime memory, or restored session context.

## Capabilities

### Conversation and Workspace

- Streams thinking and the final answer as separate blocks.
- Shows model status, token usage, context pressure, runtime memory, and logs in the workspace.
- Accepts text files and images by picker, drag and drop, or paste.
- Stops an active generation from the input area without losing the whole session.
- Highlights direct references to runtime rules, live memory, and restored session context inside completed thinking blocks.

### Memory and Continuity

- Keeps the current topic, task, decisions, feedback, and unresolved points in visible runtime memory.
- Stores every accepted memory update as a snapshot that can be inspected in the sidebar.
- Detects repeated inputs and interaction loops during the current session.
- Saves a compact session digest and restores it after a reload or reconnect.
- Keeps pending reminders and ask-later conditions separate from normal conversation memory.
- Saves larger reports separately and appends them to the active context only when needed.
- Builds a cross-session L4 store from durable facts, preferences, project decisions, and persistent constraints.

### Runtime Actions

JIN can request runtime actions while answering. The action is handled by the runtime, and any result needed for the answer is returned to the model in the same workflow.

Available actions include:

- web search for current information;
- session save and restore;
- active-memory creation and resolution;
- delayed-memory save, update, append, and removal from the current context;
- runtime TODO lists for multi-step work;
- skill discovery and temporary skill attachment;
- asset operations for files, prompts, wildcards, templates, and local Python skills;
- live avatar and workspace color changes.

## Architecture

![schema](ui/static/images/schema.jpg)

## How JIN Works

A normal turn follows this path:

1. The user sends a message and optional attachments.
2. The brain model produces thinking and the visible answer.
3. Runtime actions are executed when the model needs search, memory, skills, assets, or another internal step.
4. The service model updates memory after the visible answer finishes.
5. The next turn receives the current memory, selected reports, active contracts, attached skills, and long-term facts as context.

The default path is `planner -> brain -> validator`. When translation is enabled, the translator is inserted before the brain. Brain, service, and translator roles may use separate OpenAI-compatible endpoints, or one model can handle all roles.

## Memory Model

JIN separates memory by purpose instead of keeping one growing transcript.

| Layer | Purpose | Lifetime |
| --- | --- | --- |
| **L1 — Live Facts** | Current topic, request, task state, decisions, feedback, and unresolved points needed for the next turn. | Current runtime session |
| **L2 — Patterns** | Repeated inputs, stalled loops, and other short-term interaction patterns that may require a strategy change. | Current runtime session |
| **L3 — Session Digest** | A compact handoff containing durable session state, completed work, open tasks, and the next step. | Saved across reloads and reconnects |
| **L4 — Long-Term Facts** | Stable facts, preferences, project decisions, constraints, and environment details that should remain available across sessions. | Cross-session |

The current runtime also uses several separate memory channels:

| Channel | Use |
| --- | --- |
| **Active Memory** | Pending reminders, recall conditions, and rules that stay active until fulfilled or cancelled. |
| **Delayed Memory** | Full reports and summaries stored outside the live prompt. A report is appended only when it is relevant. |
| **Facts Memory** | Inspectable per-session fields selected from L1. These fields are the input for L4 consolidation. |
| **Runtime TODO** | A visible step ledger for multi-step work. Items are checked and resolved as the task progresses. |

### Current L4 Flow

JIN waits until the workspace is idle, reads new Facts Memory fields, extracts durable candidates, and merges them into the long-term store. Duplicate or overlapping facts are consolidated. Long-term facts are then available to future brain calls and can be removed from the memory panel.

Delayed Memory can also absorb selected L4 facts into a larger report. Facts already archived by a report are not injected twice.

## Basic Use

| What you do | What JIN does |
| --- | --- |
| Continue a normal conversation | Updates L1 and, when relevant, L2 after each completed turn. |
| Say `save the session` or clearly end the session | Creates an L3 digest and restores it on the next connection. |
| Ask JIN to remember, remind, or check something later | Creates an Active Memory record and keeps it outside L1 until resolved. |
| Ask to save a report or summary | Creates a Delayed Memory report with a title, summary, tags, and body. |
| Ask to use a saved report | Appends that report to the current context. |
| Give JIN a multi-step task | Creates a runtime TODO list and works through its items. |
| Ask for current information | Runs web search and answers from the returned evidence. |
| Attach a file or image | Adds it to the current request; supported skills can process larger files in steps. |

Memory is visible in the right panel. Use the panel arrows to move through runtime snapshots and switch between live memory, Facts Memory, Long-Term Memory, and Active Memory views.

## Assets and Skills

Reusable material lives under `assets/`:

- `assets/skills/` — instructions and optional local Python tools;
- `assets/prompts/` — reusable prompt lists;
- `assets/templates/` — prompt templates;
- `assets/wildcards/` — text values used by templates and generators;
- `assets/outputs/` — generated files.

JIN can list available skills, attach the skill needed for the current task, run its allowed actions, and remove it afterward. Python skills are restricted to `.py` files inside the selected skill directory and run without a shell.

## Project Layout

```text
.
|-- app.py                  # FastAPI app, routes, lifespan
|-- websocket/              # WebSocket router, message handling, and UI console logging
|-- contracts/              # Per-action markers, rules, guards, and follow-up effects
|-- config.example.py       # Runtime configuration template
|-- config_loader.py        # Local config module loader
|-- app_settings.py         # Typed settings wrapper
|-- launch_jin.bat          # Windows one-click launcher
|-- launch_jin.ps1          # LM Studio readiness check and startup script
|-- package.json            # Local command shortcuts
|-- requirements.txt        # Pinned Python dependencies
|-- saved_runtime.example.txt  # Template for persisted L3 session memory
|-- .github/workflows/      # GitHub Actions CI
|-- agent/                  # Agent runtime, state, router, and nodes
|-- clients/                # Runtime client builders and provider helpers
|-- memory/                 # Local delayed-memory reports and memory placeholders
|-- runtime/                # Runtime context, memory layers, stream, telemetry, registry
|-- rules/                  # Brain prompt rule blocks
|-- ui/                     # HTML templates, browser JavaScript, and README assets
|-- tests/                  # Unit, runtime-action, and optional model integration tests
`-- utils/                  # Actions, assets, validation, storage, and shared helpers
```

## Requirements

- Python 3.10+
- One or more OpenAI-compatible model servers
- Node.js 20+ only for npm test and behavior-probe shortcuts
- A Serper API key only when the built-in web-search action is enabled

The model server must provide `/v1/chat/completions` and `/v1/models`. LM Studio can also provide `/api/v0/models` so JIN can read the loaded context length.

## Quick Start

### Windows + LM Studio

1. Install LM Studio and load an OpenAI-compatible chat model.
2. Start the LM Studio Local Server.
3. Run:

```text
launch_jin.bat
```

The launcher checks the local model server, creates `config.py` from the template when needed, prepares `.venv`, installs dependencies, starts JIN, and opens:

```text
http://127.0.0.1:8000
```

It does not download models automatically and does not replace model IDs or provider URLs that you already configured.

### Manual Start

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
Copy-Item config.example.py config.py
```

Linux/macOS:

```bash
source .venv/bin/activate
cp config.example.py config.py
```

Install and run:

```bash
pip install -r requirements.txt
python app.py
```

Then open `http://127.0.0.1:8000`.

## Model Setup

JIN is model-agnostic at the API layer. A simple setup uses one model for both brain and service roles. A split setup can use:

- a stronger thinking model for the visible answer and runtime decisions;
- a smaller service model for memory updates and supporting work;
- an optional translator model for internal translation.

A thinking-capable model is recommended for the brain role. Reliable reasoning separation and runtime-action use depend on the selected model.

## Configuration

Copy `config.example.py` to `config.py` and set the provider URLs and model IDs. `config.py` is ignored by Git.

Main options:

| Option | Purpose |
| --- | --- |
| `USE_SERVICE_AS_BRAIN` | Use the service model for visible brain responses. |
| `BRAIN_API_BASE`, `BRAIN_MODEL_UID` | Brain provider and model. |
| `SERVICE_API_BASE`, `SERVICE_MODEL_UID` | Service provider and model. |
| `TRANSLATION_ENABLED` | Enable the translator path. |
| `*_CONTEXT_WINDOW`, `*_MAX_TOKENS` | Local fallbacks for context and output limits. |
| `BRAIN_IMAGE_INPUT_ENABLED`, `SERVICE_IMAGE_INPUT_ENABLED` | Send image attachments to roles that support OpenAI-compatible image input. |
| `L4_MEMORY_ENABLED`, `L4_IDLE_SECONDS` | Enable long-term memory consolidation and set the idle delay. |
| `SEARCH_SERPER_API_KEY`, `SEARCH_MAX_RESULTS` | Configure built-in web search. |
| `BRAIN_MAX_FOLLOWUPS` | Limit internal action and follow-up steps for one user turn. |

Every uppercase option can also be set through environment variables. Plain names and `JIN_`-prefixed names are supported; plain names take priority.

## Local Storage

- JIN keeps its persistent runtime state locally in browser `localStorage` and written as JSON files under `memory/`;
- `saved_runtime.example.txt` can be copied to `saved_runtime.txt` to provide a static session-memory seed.

No server-side database is required.

## Tests

Run the fast local suite:

```bash
npm test
```

Run the translator smoke test against the configured local model:

```bash
npm run translation_tests
```

Run an optional behavior probe:

```bash
npm run probe ascii
npm run probe movie
npm run probe word
npm run probe marker
npm run probe save
npm run probe delayed
```

GitHub Actions runs the fast suite. Model-dependent probes remain local unless CI is connected to a compatible runtime.
