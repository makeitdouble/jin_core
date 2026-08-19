# JIN Core Engine

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-runtime-009688.svg)
![WebSocket](https://img.shields.io/badge/WebSocket-streaming-orange.svg)
![OpenAI Compatible](https://img.shields.io/badge/API-OpenAI--compatible-111827.svg)
![Tests](https://github.com/makeitdouble/jin_core/actions/workflows/tests.yml/badge.svg)

**JIN Core Engine** is an experimental cognitive runtime for OpenAI-compatible models with **visible memory, session continuity, and model-driven actions.**

JIN is designed for long-running interaction. It carries model state forward, exposes the context shaping the current response, lets the model act on that state, and restores explicitly saved sessions through a compact session handoff.

The main chat stays visually simple while memory layers, reasoning, context pressure, runtime actions, persistent files, and action history remain accessible in collapsible panels.

## Interface

![JIN Core Engine runtime workspace](ui/static/images/jin-core-default-theme.jpg)

The JIN workspace combines the chat stream, draggable/collapsible runtime panels, model telemetry, inspectable memory layers, runtime actions, persistent files, and the Live Avatar.

### Live Avatar
<table>
<tr>
<td width="66%" valign="top">
<p>Live Avatar visualizes JIN's runtime state in real time.</p>
<p>Inner orbits react to live L1 memory changes, while outer signal rings track Delayed Memory, L4 facts, Active Memory, and persistent files.</p>
<p>The avatar is interactive: reasoning references light up matching runtime signals, and hovering linked signals reveals the related memory and files.</p>
<p>During reasoning, the avatar shifts into a dedicated motion state. Runtime actions can also change its size and tint the workspace, giving the model a small visual language beyond text.</p>
</td>
<td width="34%" align="center" valign="middle">
<img src="ui/static/images/live-avatar.jpg" alt="Live Avatar memory rings" width="260" />
</td>
</tr>
</table>

## Memory Architecture

JIN organizes memory by cognitive purpose across four layers and dedicated memory systems.

### The Four-Layer Memory Model

* **L1 — Live Facts:** The current topic, request, task state, decisions, feedback, and unresolved points needed for the next turn.
* **L2 — Patterns:** Repeated inputs, stalled loops, and short-term interaction patterns that may require a strategy change.
* **L3 — Session Digest:** A compact handoff created by an explicit session save. It preserves the state used to re-enter an archived conversation. Soft reconnect is a separate transport-resume path.
* **L4 — Long-Term Facts:** Stable facts, preferences, project decisions, constraints, and environment details that should remain available across sessions.

Every accepted L1 update is stored as a versioned snapshot. The runtime-memory timeline can be stepped through visually, with new and changed fields highlighted across snapshots.

![Runtime memory snapshot timeline](ui/static/images/runtime-highlight.png)

### Delayed Memory

JIN uses **Delayed Memory** for larger pieces of context that enter the prompt when they are relevant. Discussions, specifications, and reports are stored as structured objects with tags and links to L4 facts or persistent files. Reports can be **loaded or unloaded by the runtime**, **pinned from the UI**, or **activated by matching user-text tags**.

### Active Memory

**Active Memory** keeps unfinished intentions and pending commitments separate from the general conversation state. Conditions, recall rules, and other unresolved contracts remain active across turns until they are fulfilled, cancelled, or explicitly resolved. Relevant stored conditions are carried back into the Brain context on later turns.

### Facts Memory and L4 Consolidation

**Facts Memory** is an inspectable index of durable context candidates collected from runtime state. During idle consolidation, JIN merges duplicate or overlapping facts with the existing L4 store. Delayed Memory reports can absorb ordinary L4 facts while essential anchor facts remain directly exposed, keeping the injected context compact.

## Core Capabilities

* **Visible Reasoning:** Displays provider/model reasoning separately from the final answer when the backend exposes a reasoning stream.
* **Reasoning References:** Maps direct references back to runtime rules, memory records, restored context, and linked runtime objects.
* **Inspectable Memory:** Keeps live state, session handoff, long-term facts, delayed reports, and active commitments as separate visible systems.
* **Session Continuity:** Supports soft WebSocket resume plus explicit session save and archived restore, with continuity state carried through memory and the session handoff.
* **Persistent Files:** Stores uploaded text, images, PDFs, and other files under stable ids; the same stored files can be attached to or detached from context across turns.
* **Runtime Telemetry:** Shows model status, token usage, context pressure, memory updates, action state, and runtime logs.
* **Interruptible Generation:** Stops an active response while preserving the logical session and a dedicated interrupted-memory path.

![Reasoning citation highlighting](ui/static/images/think-highlight.jpg)

### Runtime Actions

JIN can request an action while answering. The runtime validates and executes it, then returns any required result to the model before the workflow continues.

Available actions include:

* one-shot web search and bounded multi-query Deep Web Search;
* explicit session save, with archived restore handled by the session bootstrap flow;
* Active Memory creation and resolution;
* Delayed Memory save, update, load, and unload;
* persistent file listing, attachment, and detachment;
* focused L4 fact updates and reconciliation;
* asset and skill discovery, including bounded local Python skills;
* Live Avatar size changes and workspace tint/color changes.

## Architecture

![JIN Core Engine architecture](ui/static/images/schema.jpg)

### Runtime Flow

The WebSocket layer creates a `RuntimeContext` for each connection. Every user message is then handled by `AgentRuntime`.

A normal turn follows this path:

1. The user sends a message with optional persistent attachments.
2. The planner prepares the request and selects the runtime path.
3. The Brain streams reasoning and visible answer content through separate runtime channels.
4. Stream validation guards repetition and malformed generation while private runtime-action markers are extracted.
5. Runtime Actions can mutate state or return trusted results; actions that need another model step continue inside the same user sequence.
6. After the visible turn completes, the Service model schedules the L1/L2 memory update.
7. A later user turn waits for any pending memory update, then receives current L1/L2/L3/L4 state, relevant Delayed/Active Memory, files, skills, and action results.

The default model path is:

```text
planner -> brain -> validator
```

When translation is enabled, Cyrillic input can be routed through:

```text
planner -> translator -> brain -> validator
```

Translator output remains internal and is logged for observability. The Brain streams the visible response from the configured brain runtime.

### Model Roles

JIN talks to models through an OpenAI-compatible API.

The runtime separates model work into roles:

* **Brain:** visible reasoning, responses, and runtime decisions;
* **Service:** background memory updates and supporting work;
* **Translator:** optional internal translation before the brain step.

JIN is model-agnostic at the API boundary. Brain and Service roles can use different models: the Brain benefits most from stronger reasoning, while the Service role can use a smaller/faster model for background work. `USE_SERVICE_AS_BRAIN = True` lets one configured model handle both roles while preserving their logical separation.

On Windows, the LM Studio launcher can fill unset/default model ids from a loaded Gemma-family model and currently recommends `google/gemma-3-12b-it`. Explicit provider URLs and model ids remain unchanged.

### Runtime Storage

JIN stores persistent runtime state locally through:

* browser storage for resumable session-facing state, Active Memory, and explicit save/bootstrap data;
* `memory/delayed/*.json` for Delayed Memory reports;
* `memory/facts/long_term_facts.json` for the canonical L4 store;
* `assets/files/` plus its local index for persistent uploaded files;
* `logs/` for chat and per-turn reasoning logs;
* optional `saved_runtime.txt` runtime/session fallback data.

Model and search traffic goes to the endpoints and providers configured for the runtime.

## Assets and Skills

Reusable material lives under `assets/`:

```text
assets/
|-- skills/       # Instructions and optional local Python tools
|-- files/        # Persistent uploaded-file library
|-- prompts/      # Reusable prompt lists
|-- templates/    # Prompt templates
|-- wildcards/    # Text values used by templates and generators
`-- outputs/      # Generated files
```

JIN can inspect available skills, attach the one required for the current task, run its allowed actions, and remove it afterward. Python skills execute from `.py` files inside the selected skill directory with bounded execution and output limits. Persistent uploaded files are stored separately under `assets/files/` and keep stable ids across turns.

## Project Layout

```text
.
|-- app.py                     # FastAPI app, routes, and lifespan
|-- websocket/                 # WebSocket routing, messages, and UI logging
|-- contracts/                 # Action markers, rules, guards, and follow-ups
|-- agent/                     # Agent runtime, state, router, and nodes
|-- clients/                   # OpenAI-compatible client builders
|-- runtime/                   # Context, memory, streams, telemetry, registry
|-- memory/                    # Delayed/L4 runtime stores and placeholders
|-- assets/                    # Skills, persistent files, prompts, and generators
|-- rules/                     # Brain and runtime rule blocks
|-- utils/                     # Actions, assets, validation, and storage helpers
|-- ui/                        # Browser interface and README images
|-- tests/                     # Unit, action, and model-integration tests
|-- config.example.py          # Configuration template
|-- config_loader.py           # Local configuration loader
|-- app_settings.py            # Typed settings wrapper
|-- launch_jin.bat             # Windows one-click launcher
|-- launch_jin.ps1             # LM Studio readiness and startup script
|-- requirements.txt           # Python dependencies
|-- package.json               # Test and probe commands
|-- ARCHITECTURE.md            # Runtime ownership, data flow, persistence
|-- LIVE_AVATAR.md             # Avatar visual-state contract
`-- saved_runtime.example.txt  # Optional runtime/session fallback template
```

## Setup and Quick Start

### Requirements

* Python 3.10+
* One or more OpenAI-compatible model servers
* Node.js 20+ for local tests and behavior probes
* A Serper API key when built-in web search is enabled

The model server must expose:

```text
/v1/chat/completions
/v1/models
```

For LM Studio, JIN also probes the provider-native `/api/v1/models` metadata endpoint and falls back to legacy `/api/v0/models` when needed, allowing the runtime to read the context length of the model that is actually loaded.

### Windows + LM Studio

1. Install LM Studio and load the model or models you want JIN to use. A single model is enough when `USE_SERVICE_AS_BRAIN = True`; with untouched/default model ids, the launcher selects a loaded Gemma-family model automatically.
2. Start the LM Studio Local Server.
3. Run:

```cmd
launch_jin.bat
```

The launcher checks the local model server, creates `config.py` from the template when needed, prepares `.venv`, installs dependencies, starts JIN, and opens:

```text
http://127.0.0.1:8000
```

Models are loaded and managed in LM Studio. The launcher fills missing or template provider URLs and model ids while preserving values you configured explicitly.

### Manual Start

```bash
git clone https://github.com/makeitdouble/jin_core.git
cd jin_core
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

Before starting, edit `config.py` if your provider URLs or model ids differ from the template values.

Install and run:

```bash
pip install -r requirements.txt
python app.py
```

Then open:

```text
http://127.0.0.1:8000
```

## Configuration

Copy `config.example.py` to `config.py`, then set the provider URLs and model IDs. `config.py` is ignored by Git.

| Option | Purpose |
| --- | --- |
| `USE_SERVICE_AS_BRAIN` | Use the service model for visible brain responses. |
| `BRAIN_API_BASE`, `BRAIN_MODEL_UID` | Configure the Brain provider and model. |
| `SERVICE_API_BASE`, `SERVICE_MODEL_UID` | Configure the Service provider and model. |
| `TRANSLATION_ENABLED` | Enable the optional Translator path before Brain execution. |
| `FOLLOW_UP_ON_LIMIT` | Continue a Brain generation in an internal tick when the provider stops at its output/context limit. |
| `BRAIN_CONTEXT_WINDOW`, `SERVICE_CONTEXT_WINDOW` | Set UI/reference context denominators; live request budgets can come from the context window reported by the loaded model. |
| `BRAIN_IMAGE_INPUT_ENABLED`, `SERVICE_IMAGE_INPUT_ENABLED` | Send image attachments to compatible model roles. |
| `L4_MEMORY_ENABLED`, `L4_IDLE_SECONDS` | Enable L4 consolidation and set its idle delay. |
| `SEARCH_SERPER_API_KEY`, `SEARCH_MAX_RESULTS` | Configure built-in web search. |
| `DEEP_WEB_SEARCH_MAX_*` | Bound the Service-worker research sequence used by Deep Web Search. |
| `BRAIN_MAX_FOLLOWUPS` | Limit internal action/follow-up continuation ticks per user turn. |
| `WEBSOCKET_MAX_MESSAGE_BYTES` | Set the WebSocket ceiling used for large attachment transport. |

Every uppercase option can also be supplied through environment variables. Plain names and `JIN_`-prefixed names are supported; plain names take priority.

## Tests

Run the fast local suite:

```bash
npm test
```

You can also run the same suite directly with Python:

```bash
python -m unittest discover -s tests
```

Run the translator smoke test against the configured local model:

```bash
npm run translation_tests
```

Run optional behavior probes:

```bash
npm run probe ascii
npm run probe movie
npm run probe word
npm run probe marker
npm run probe save
npm run probe delayed
```

GitHub Actions runs the fast suite. Model-dependent probes remain local unless CI is connected to a compatible runtime.
