# JIN Core Engine

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-runtime-009688.svg)
![WebSocket](https://img.shields.io/badge/WebSocket-streaming-orange.svg)
![OpenAI Compatible](https://img.shields.io/badge/API-OpenAI--compatible-111827.svg)
![Tests](https://github.com/makeitdouble/jin_core/actions/workflows/tests.yml/badge.svg)

**JIN Core Engine** is an experimental cognitive runtime for OpenAI-compatible models with **visible memory, session continuity, and model-driven actions.**

JIN is designed for long-running interaction. It carries model state forward, exposes the context shaping the current response, lets the model act on that state, and can restore archived sessions through the dedicated bootstrap/restore path.

The main chat stays visually simple while memory layers, reasoning, context pressure, runtime actions, persistent files, and action history remain accessible in collapsible panels.

## Interface

![JIN Core Engine runtime workspace](ui/static/images/jin-core-default-theme.jpg)

The JIN workspace combines the chat stream, draggable/collapsible runtime panels, model telemetry, inspectable memory layers, runtime actions, persistent files, and the Live Avatar.

### Live Avatar
<table>
<tr>
<td width="66%" valign="top">
<p>Live Avatar visualizes JIN's runtime state in real time.</p>
<p>Inner orbits react to live FRAME/runtime-memory changes, while outer signal rings track Delayed Memory, L-T facts, Active Memory, and persistent files.</p>
<p>The avatar is interactive: reasoning references light up matching runtime signals, and hovering linked signals reveals the related memory and files.</p>
<p>During reasoning, the avatar shifts into a dedicated motion state. Runtime actions can also change its size and tint the workspace, giving the model a small visual language beyond text.</p>
</td>
<td width="34%" align="center" valign="middle">
<img src="ui/static/images/live-avatar.jpg" alt="Live Avatar memory rings" width="260" />
</td>
</tr>
</table>

## Memory Architecture

JIN no longer uses the old numbered four-layer hierarchy. The current user-facing memory panel has five stable views: **FRAME**, **ACTIVE**, **DELAYED**, **L-T**, and **FILES**.

### FRAME / Live Runtime Memory

**FRAME** is the UI name for the current live runtime-memory snapshot. Backend implementation still lives under `runtime/L1_memory*`; the rename is intentionally presentation-only. FRAME keeps the current topic, request/task state, decisions, feedback, and unresolved points needed by upcoming turns. Accepted updates are versioned as snapshots so the UI can step through diffs and inspect what changed.

![Runtime memory snapshot timeline](ui/static/images/runtime-highlight.png)

### Active Memory

**Active Memory** keeps unfinished intentions and pending commitments separate from the general conversation state. Conditions and unresolved contracts remain active across turns until they are fulfilled, cancelled, paused, or explicitly resolved. Relevant active records are projected back into Brain context without changing their canonical storage order.

### Delayed Memory

**Delayed Memory** stores larger structured context that should be available without living in every prompt. Reports can link L-T facts and persistent files, can be loaded/unloaded by runtime actions, pinned from the UI, or surfaced from matching user-text tags.

### L-T Long-Term Facts

**L-T** is the UI view of canonical L-T durable facts: stable user/project facts, preferences, constraints, decisions, and environment details that should survive sessions. An internal Facts Memory candidate buffer feeds idle L-T extraction/merge; it is not a sixth user-facing memory tab or a revived L2/L3 layer.

### Files

**FILES** exposes the persistent uploaded-file library. Stored files keep stable IDs and can be attached/detached across turns or linked from Delayed Memory.

## Core Capabilities

* **Visible Reasoning:** Displays provider/model reasoning separately from the final answer when the backend exposes a reasoning stream.
* **Reasoning References:** Maps direct references back to runtime rules, memory records, restored context, and linked runtime objects.
* **Inspectable Memory:** Keeps FRAME/live state, long-term facts, delayed reports, active commitments, persistent files, and continuity checkpoints as separate systems.
* **Session Continuity:** Supports soft WebSocket resume, atomic browser checkpoints for reload/new-tab continuity, and explicit archived-session restore from persisted logs.
* **Persistent Files:** Stores uploaded text, images, PDFs, and other files under stable ids; the same stored files can be attached to or detached from context across turns.
* **Runtime Telemetry:** Shows model status, token usage, context pressure, memory updates, action state, and runtime logs.
* **Interruptible Generation:** Stops an active response while preserving the logical session and a dedicated interrupted-memory path.

![Reasoning citation highlighting](ui/static/images/think-highlight.jpg)

### Runtime Actions

JIN can request an action while answering. The runtime validates and executes it, then returns any required result to the model before the workflow continues.

Available actions include:

* one-shot web search and bounded multi-query Deep Web Search;
* Active Memory creation and resolution;
* Delayed Memory save, load, and unload;
* persistent file listing, attachment, and detachment;
* focused L-T fact updates and reconciliation;
* asset and skill discovery, including bounded local Python skills;
* Live Avatar size changes and workspace tint/color changes.

## Architecture

![JIN Core Engine architecture](ui/static/images/schema.jpg)

### Runtime Flow

The WebSocket layer creates a `RuntimeContext` for each connection. Every user message is then handled by `AgentRuntime`.

A normal turn follows this path:

1. The user sends a message with optional persistent attachments.
2. `AgentRuntime` passes the request directly to the Brain.
3. The Brain streams reasoning and visible answer content through separate runtime channels.
4. Stream validation guards repetition and malformed generation while private runtime-action markers are extracted.
5. Runtime Actions can mutate state or return trusted results; actions that need another model step continue inside the same user sequence.
6. After the visible turn completes, the logical Service route performs background FRAME/L1 integration; if no dedicated Service endpoint is configured, this route reuses the Brain client.
7. A later user turn waits for any pending FRAME/L1 update, then receives current Active Memory, recent chat beside `<FRAME_MEMORY_N>`, loaded Delayed Memory, L-T facts, files/skills, action history, and trusted tool results.

The model path is intentionally direct:

```text
user -> brain
```

There is no pre-Brain routing layer. Planning decisions, runtime actions, and follow-up decisions stay inside the Brain/runtime loop.

### Model Roles

JIN talks to models through an OpenAI-compatible API.

The runtime separates model work into roles:

* **Brain:** visible reasoning, responses, and runtime decisions;
* **Service:** background memory updates and supporting work.

JIN is model-agnostic at the API boundary. **Brain is the only foreground response route.** Service is background-only. `SERVICE_API_BASE` is optional: when it is empty, the Service client aliases the Brain client, so one physical model can handle both logical roles without changing foreground routing. Set `SERVICE_API_BASE` only when a dedicated background Service node exists.

Older local configs that still contain `USE_SERVICE_AS_BRAIN = True` are accepted only by a localized migration adapter: their old Service endpoint is promoted to the canonical Brain settings, the legacy flag is removed during normalization, and no runtime code branches on it. Archived `SERVICE` response labels are likewise reader compatibility, not a current response mode.

On Windows, the LM Studio launcher can fill unset/default Brain model settings from a loaded Gemma-family model and can separately initialize a dedicated Service endpoint when one is configured. Explicit provider URLs and model ids remain unchanged.

### Runtime Storage

JIN stores persistent runtime state locally through:

* `jin.liveRuntimeMemory.v2` in `sessionStorage` for the current page's soft-reconnect FRAME;
* one atomic `jin.sessionCheckpoint.v2` in `localStorage` for new-tab/reload continuity;
* `memory/delayed/*.json` for Delayed Memory reports;
* `memory/facts/long_term_facts.json` for the canonical L-T store;
* `assets/files/` plus its local index for persistent uploaded files;
* `logs/` for chat and per-turn reasoning logs.

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
|-- agent/                     # Direct Brain runtime, state, and Brain node
|-- clients/                   # OpenAI-compatible client builders
|-- runtime/                   # Context, memory, streams, telemetry, registry
|-- memory/                    # Delayed/L-T runtime stores and placeholders
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
|-- docs/                      # Current architecture, state, and durable decisions
`-- LIVE_AVATAR.md             # Avatar visual-state contract
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

1. Install LM Studio and load the Brain model you want JIN to use. A single model is enough by default: with `SERVICE_API_BASE` left empty, background Service work reuses Brain. Configure a second endpoint only if you want a dedicated Service model.
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
| `BRAIN_API_BASE`, `BRAIN_MODEL_UID` | Configure the required foreground Brain provider and model. |
| `SERVICE_API_BASE`, `SERVICE_MODEL_UID` | Optionally configure a dedicated background Service provider/model. Leave `SERVICE_API_BASE` empty to reuse Brain. |
| `FOLLOW_UP_ON_LIMIT` | Continue a Brain generation in an internal tick when the provider stops at its output/context limit. |
| `NATIVE_MODELS_ENDPOINT` | Optional provider-native model metadata endpoint. JIN reads the active context window from the loaded model and uses the same live value for request budgeting and UI telemetry. |
| `BRAIN_IMAGE_INPUT_ENABLED` | Allow image attachments on the foreground Brain request when the selected provider/model supports OpenAI-compatible image input. |
| `LT_MEMORY_ENABLED`, `LT_IDLE_SECONDS` | Enable L-T consolidation and set its idle delay. |
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
