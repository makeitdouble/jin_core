LIVE_AVATAR v1.1

# Live Avatar Visual Manual

This manual documents the visual side of the live avatar: what each part on the avatar means, how it reacts to memory state, and where to change each visual behavior.

It is intentionally not a full architecture document. The goal is practical: if you look at the avatar and ask "what is this ring?" or "where do I make this brighter, faster, wider, or calmer?", this file should point you to the exact place.

## The Mental Picture

The live avatar is a memory radar with a persistent-file perimeter. The inner moving rings represent the current runtime memory snapshot. The three outer memory-signal rings represent delayed reports, L4 long-term facts, and active memory. A fourth, farther-out ring is made of file dots and represents the persistent files known to `window.JinFiles`. The center is the JIN accent light; it also feeds the scene tint.

Read the radar like this:

| Visual cue | Meaning |
|---|---|
| Inner moving rings | Current runtime memory lines |
| Faster inner motion | Larger runtime memory diff |
| Color shifts in inner rings | Keyword/emotional content in runtime memory |
| Vertical stripes on a runtime ring | That runtime value contains `?` or `!` |
| Runtime change markers | Last real runtime transition: filled = new line, hollow = changed line |
| Breathing scaffold rays | Ambient runtime activity; ray energy follows snapshot diff |
| Delayed report dashes | Stored delayed memory reports |
| Bright delayed dash | Report is pinned or currently loaded into runtime context |
| Half-accent delayed dash | A loaded report hides an ordinary fact that another report keeps as an anchor |
| L4 blue dashes | Long-term facts that stay directly visible |
| Dim L4 dots | Ordinary report-covered L4 facts; archived, not deleted |
| Bright outer memory dashes | Active memory records |
| Outer file dots | Persistent files in `/assets/files` / `window.JinFiles` |
| Bright white file dot | File is directly pinned/attached to context |
| Half-accent file dot | File is indirectly present through a loaded delayed report |
| Center color | JIN accent color and scene tint |
| Glow on hover/citation/reference | A runtime, memory, or file item is being pointed at right now |

The important distinction is **representation versus activation**. A dim L4 dot or normal file dot still represents a real stored item. Loading, pinning, hovering, citing, or linking changes emphasis without changing that item's identity or angular slot.

## Main Files To Touch

Most radar-avatar behavior lives in:

`ui/static/js/runtime/runtime-avatar.js`

Use this file for runtime rings, memory rings, the file-dot ring, radii, colors, speed, punctuation stripes, seeded geometry, center rendering, delayed/L4/file link state, and avatar-level hover/reference/citation reactions.

The radar glow, shell aura, depth layer, entry softness, and reduced-motion behavior live in:

`ui/static/css/runtime-avatar.css`

Other visual/state knobs:

| Need | File | Change |
|---|---|---|
| Avatar panel size | `ui/static/css/base.css` | `--runtime-avatar-panel-size` |
| Center color tint applied to scene | `ui/static/js/runtime/runtime-avatar.js` | `setCenterColor()`, `JIN_SCENE_COLOR_INTENSITY` |
| L4 archived/visible classification | `ui/static/js/runtime/runtime-l4-memory.js` | `getArchivedFactIdSet()`, `getVisibleFacts()`, `getFactsWithArchiveState()` |
| Long-term facts panel visibility | `ui/static/js/runtime/runtime.js` | `getVisibleLongTermMemoryFacts()` |
| Runtime/L4/delayed/active/file row hover dispatch | `ui/static/js/runtime/runtime-memory-view.js` | row hover dispatch helpers and `data-avatar-memory-hover-id` |
| Attached-files plaque hover dispatch | `ui/static/js/dragdrop.js` | persistent file hover bindings |
| Persistent file source/state | `ui/static/js/dragdrop.js` + `window.JinFiles` | file store, pin state, `jin:files-store-changed` |
| Delayed report attachment links | `ui/static/js/runtime/runtime-storage.js`, `runtime-memory-view.js` | `attachments_ids` |
| Center button click wiring | `ui/static/js/socket/input.js` | `toggleRuntimeAvatarMemoryLayers()` |
| Browser cache after visual edits | `ui/templates/index.html` | bump query string for changed CSS/JS |

## Visual Stack

The radar avatar is drawn as a single SVG inside `#jin-runtime-avatar`. A full render replaces the old SVG, but state-only changes are deliberately synchronized in place where possible so a pin/load transition does not unnecessarily reshuffle or restart visual geometry.

The SVG is intentionally only the visual projection. Rich matching/link payload (`citationIdentity`, citation key/text, reference aliases, delayed/L4 relation ids, file links, and the L4 archive angle) lives in the private `avatarNodeState` `WeakMap` in `runtime-avatar.js`, not in `data-*` attributes. Keep only lightweight canonical ids and synchronization hooks in the DOM; do not serialize full values or derived payload back into SVG nodes. Ring-wide glow variables belong on the ring group rather than being duplicated on every memory dash.

The stack is built in this order:

1. SVG definitions: gradients and glow filters.
2. Static scaffold: halo, concentric radar circles, and breathing radial rays.
3. Runtime rings: one moving orbit per runtime memory line.
4. Memory signal rings: delayed, L4, active.
5. Persistent file ring: one dot per file, outside active memory.
6. Center core: the central light and glow.
7. Runtime/citation/reference/hover/link classes are reapplied.

The main render function is:

```js
renderAvatar(snapshot, options = {})
```

Important helpers:

| Helper | Role |
|---|---|
| `appendDefs()` | SVG filters and gradients |
| `appendStaticScaffold()` | background radar structure and diff-reactive rays |
| `computeRingRecords()` | turns runtime lines into orbit records |
| `appendOrbit()` | draws one runtime memory orbit |
| `appendMemorySignalRings()` | draws delayed, L4, active memory rings |
| `appendFileRing()` / `appendFileSignalRing()` | draws the persistent-file perimeter |
| `appendCenter()` | draws center core |
| `applyThinkRuntimeCitationGlow()` | applies think-citation glow |
| `applyMemoryReferenceGlow()` | applies response/reference glow |
| `applyMemoryRowAvatarHoverGlow()` | applies row/plaque hover glow and cross-layer links |
| `applyDelayedMemoryFactLinkGlow()` | delayed-report <-> L4 highlighting plus secondary-report state |
| `applyDelayedMemoryFileLinkGlow()` | focused delayed-report <-> attachment-dot highlighting |
| `syncMemorySignalLayer()` | rebuilds one memory signal ring in place when possible |
| `syncDelayedMemoryState()` | resyncs delayed state, L4 archive/link state, and file-link state |
| `syncFilesState()` | updates file-dot state without restarting the orbit when the file set is unchanged |

### Live Sync Rules

Several interactions intentionally avoid a full `avatar.refresh()`:

- delayed, L4, and active memory use their dedicated sync functions;
- `repaintAvatar()` performs a full redraw with the current `avatarRefreshNonce`, so the seeded geometry stays the same; `reinitializeAvatar()` / public `refresh()` increments the nonce when an intentional reseed is wanted;
- file pin/context-link changes update existing file dots in place when the set of file ids did not change;
- the file ring is rebuilt only when the persistent file set itself changes;
- file records are sorted by file id, so changing pin/load state never changes a file's angular slot;
- `jin:files-store-changed` triggers file-state synchronization;
- delayed-memory state synchronization also refreshes related L4 and file-link states.

The memory panel may stay on `[active]`, `[delayed]`, `[facts]`, `[long_term]`, or `[files]` while L1 updates. `renderRuntimeMemorySnapshot()` now still dispatches the newest runtime snapshot to the avatar when the visible panel mode is not `[runtime]`. This prevents the radar from freezing merely because the user is looking at another memory tab.

## Static Scaffold

The scaffold is the quiet radar structure behind the live memory rings. It is not a memory item. It gives the avatar depth and now carries a very slow activity signal from the current runtime diff.

It is drawn by:

```js
appendStaticScaffold(svg, overallColor, currentCenterColor, diffPercent, random)
```

Current behavior:

- the concentric circles remain faint and structural;
- there are `16` radial rays;
- only a seeded subset of roughly `3..7` rays receives stronger breathing energy;
- `diffPercent` controls `rayEnergy`, so a larger runtime diff makes the active rays somewhat more visible;
- ray color mixes the current center color, overall runtime color, and a dark base;
- each ray receives a long seeded duration/phase, so the effect reads as ambient breathing rather than a busy equalizer;
- `prefers-reduced-motion` disables the breathing animation.

Change these when you want the background to feel denser, cleaner, brighter, or more technical:

| Visual part | Where |
|---|---|
| Concentric scaffold circles | `STATIC_SCAFFOLD_RADII` |
| Radial guide line range | `STATIC_RADIAL_LINE_INNER_RADIUS`, `STATIC_RADIAL_LINE_OUTER_RADIUS` |
| Number of rays | `rayCount` in `appendStaticScaffold()` |
| Diff response | `rayEnergy`, `activeRayCount` |
| Ray color/opacity/duration | `appendStaticScaffold()` |
| Breathing curve | `.jin-avatar-scaffold-ray.is-jin-avatar-ray-breathing`, `@keyframes jin-avatar-scaffold-ray-breathe` in `runtime-avatar.css` |

The inner scaffold/ring geometry is globally compressed with `INNER_RING_SCALE = 0.90`. The SVG itself also renders at `transform: scale(0.90)` so the new outer file perimeter has breathing room inside the square avatar shell.

## Runtime Rings

Runtime rings are the inner moving orbits. They are tied to the current runtime memory snapshot. Each visible runtime memory line becomes one ring.

These rings are the most "alive" part of the avatar: they change radius, speed, color, dash texture, and decoration based on current runtime memory.

### Runtime Ring Meaning

| Visual signal | Meaning |
|---|---|
| Number of rings | Number of runtime memory lines |
| Ring radius | Source order in the runtime snapshot: earlier lines sit farther out, later lines move inward |
| Ring speed | Snapshot diff intensity |
| Ring direction | Seeded random direction |
| Ring color | Keyword palette plus emotional/alert influence |
| Runtime highlight glow | Uses that ring's current color rather than a fixed generic glow |
| Vertical stripes | The runtime **value** contains `?` or `!` |
| Filled change marker | The line was added in the last real runtime transition |
| Hollow change marker | The line changed in the last real runtime transition |
| Change marker size | Magnitude of the line change |

### Runtime Ring Controls

| Change | File | Exact place |
|---|---|---|
| Inner/outer radius range | `runtime-avatar.js` | `MIN_RING_RADIUS`, `MAX_RING_RADIUS` |
| How radius is calculated | `runtime-avatar.js` | `computeRingRecords()` |
| Speed | `runtime-avatar.js` | `appendOrbit()` -> `baseSpeed`, `effectiveSpeed`, `duration` |
| Dash texture | `runtime-avatar.js` | `appendOrbit()` -> `dashLength`, `gapLength`, `strokeWidth` |
| Arc fragments | `runtime-avatar.js` | `appendOrbit()` -> `arcCount`, `appendArcCircle()` |
| Punctuation-triggered stripes | `runtime-avatar.js` | `appendOrbit()` condition + `appendLongFieldStripes()` |
| Runtime change markers | `runtime-avatar.js` | `appendRuntimeChangeMarker()`, `resolveRuntimeChangeMarkers()` |

`computeRingRecords()` uses `sourceOrderRatio`, not line length, for the base radius. `record.isLong` may still exist as record metadata, but it no longer controls the stripe visual. Stripes are appended only when `String(record.value || "")` matches `/[!?]/`. The old stripe geometry itself is preserved: seeded count, height, arc span, color, width, and opacity.

Runtime hover/citation/reference glow variables are derived from the orbit's current `ringColor`, so a highlighted orbit keeps its own semantic color instead of flattening every highlight to cyan. Idle-opacity CSS targets only direct structural circles/lines; nested filled change markers are not accidentally dimmed with the base orbit.

### Runtime Ring Speed

The runtime orbit speed is based on snapshot diff:

```js
const baseSpeed = 11 + random() * 36;
const effectiveSpeed = baseSpeed * (diffPercent / 100);
const duration = effectiveSpeed > 0.05 ? 360 / effectiveSpeed : 9999;
```

If the runtime memory barely changed, the rings nearly stop. If the diff is high, they move faster.

To make runtime rings calmer:

```js
const baseSpeed = 6 + random() * 18;
```

To make them more energetic:

```js
const baseSpeed = 18 + random() * 52;
```

### Runtime Change Markers

Runtime circles are no longer decorative and are no longer triggered by words such as `pending`.

They show the last real runtime memory transition:

| Marker | Meaning |
|---|---|
| Filled circle | A runtime line was newly added |
| Hollow circle | An existing runtime line changed |
| Marker size | Larger `key_change_ratio` / `value_change_ratio` |
| Marker angle | Stable hash of the runtime line identity |

If a later snapshot has no real line changes, the previous change markers remain visible. The avatar searches backward through runtime snapshot history until it finds the latest real transition. This keeps the last meaningful transition visible instead of making the markers disappear on a no-op redraw.

A removal-only transition clears the old markers: the removed line is represented by its orbit disappearing, so no stale circle is carried forward.

Random orbit circles and pending-keyword circles are intentionally not rendered.

## Runtime Colors

Runtime colors come from a weighted palette. The avatar looks at text in the current runtime snapshot and blends colors if specific words appear.

The default palettes live near the top of:

`ui/static/js/runtime/runtime-avatar.js`

| Palette | What it does |
|---|---|
| `KEYWORD_PALETTE` | Softly pushes rings toward thematic colors |
| `AGGRESSIVE_PALETTE` | Strong alert-like coloring for high-priority words |

Current keyword palette:

| Words | Color |
|---|---|
| `jin`, `runtime` | `#22d9b5` |
| `user` | `#9276d8` |
| `memory` | `#e1a449` |

Current aggressive palette:

| Words | Color |
|---|---|
| `angry`, `aggressive` | `#ff0000` |

To add a soft visual theme:

```js
[["project", "repo", "code"], "#65c99a"]
```

To add a warning theme:

```js
[["error", "failure", "blocked"], "#ff4b4b"]
```

## Memory Signal Rings

The memory signal rings are the outer dash/dot rings. They are not runtime memory lines. They represent separate memory systems around the current runtime state. The persistent-file perimeter sits one step farther out and uses dots instead of memory dashes.

Memory dashes are configured in:

```js
MEMORY_RING_LAYOUT
```

The file perimeter is configured separately in:

```js
FILE_RING_LAYOUT
```

| Ring | Radius | Stroke / dot size | Meaning |
|---|---:|---:|---|
| Delayed | `158` | `3.10` | Delayed memory reports |
| L4 | `168` | `1.05` | Long-term facts |
| Active | `178` | `1.35` | Active memory records |
| Files | `188` | dot radius `2.7` | Persistent files |

The memory-ring render order is `delayed`, then `l4`, then `active`; the file ring is inserted after those and before the center. L4 intentionally sits between delayed reports and active memory.

Each delayed/active item becomes one dash record. L4 always keeps one avatar record per fact, but archived L4 facts settle into dots instead of disappearing from the radar. The file ring uses one stable dot per persistent file.

### Memory Ring Layout Controls

| Field | Meaning |
|---|---|
| `radius` | How far from center the ring sits |
| `strokeWidth` | Thickness of a memory dash |
| `minArcDegrees` | Smallest dash length |
| `maxArcDegrees` | Largest dash length |
| `arcRatio` | How much of each item slot is filled |
| `arcTrimPixels` | Optional pixel trim before arc degrees are finalized; currently used by L4 |
| `startAngle` | Where the first dash/dot slot starts |
| `FILE_RING_LAYOUT.dotRadius` | Persistent-file dot size |

Use these fields when you want to move a ring inward/outward or change how dense its records feel. Keep enough separation between radii for hover/link glows to remain visually distinct.

## L4 Facts Ring

The L4 ring shows all stored long-term facts. A directly exposed fact renders as a blue dash. A report-covered ordinary fact keeps the same avatar identity but renders as a dim dot.

There are two base visual states:

| L4 state | Meaning | Avatar |
|---|---|---|
| Visible / anchor fact | Fact stays directly available in long-term context | normal blue dash |
| Archived ordinary fact | Fact is listed by a delayed report as ordinary report content | dim blue dot; dash arc fades away |

Current opacity:

```js
opacity: record.archived ? 0.26 : 0.52
```

Archived L4 records also pass:

```js
dot: record.archived
```

File:

`ui/static/js/runtime/runtime-avatar.js`

Place: L4 branch inside `appendMemorySignalRing()`.

### L4 Archived Meaning

Archived does **not** mean deleted. It means the fact has been absorbed into delayed-memory report content and should not occupy a normal direct L4 line in context or the long-term panel.

Current classification is intentionally simple and global:

1. collect archive candidates from every report's `facts_ids`, legacy `absorbed_fact_ids`, and legacy `long_term_facts_ids`;
2. collect every report's `anchor_fact_ids`;
3. remove all anchor ids from the archived set.

So the important direct-id rule is:

**Anchor ids are removed globally from the archived-id set. Loaded/pinned does not remove an ordinary `facts_ids` id from that set.**

`factMatchesArchivedIds()` then checks both `fact.id` and `source_fact_ids`. That matters for merged/derived L4 records: even when the record's own id is anchored, an archived source id can still make the combined record classify as archived.

A report being loaded or pinned can make its linked archived L4 dot glow through `is-delayed-memory-linked-hit`, but load state by itself never changes archive classification.

This distinction prevents a report load from rewriting the structural meaning of L4. Load/pin is context emphasis; `anchor_fact_ids` is the structural exception that keeps an L4 fact exposed.

### Delayed Memory Highlight Contract

Delayed memory uses **one base blue hue and exactly two highlight tiers**. There is no third persistent DM highlight level.

1. DM id cited in JIN output -> Tier 1 (soft).
2. Pinned DM, not explicitly loaded -> Tier 2 (strong).
3. Pinned + loaded DM -> Tier 2.
4. Explicitly loaded DM -> Tier 2.
5. Pinned DM1 cross-links DM2 -> DM1 Tier 2, DM2 Tier 1. The cross-link alone must not move DM2 upward in the delayed-memory panel.
6. Loaded DM1 cross-links DM2 -> DM1 Tier 2, DM2 Tier 1.
7. Any directly pinned/loaded DM highlights all of its own linked L4 facts at Tier 1; those L4 facts move upward in the long-term panel.
8. A secondary cross-linked DM does **not** highlight or promote its own L4 facts unless that DM independently becomes pinned or loaded.

Transient hover/modal focus reuses Tier 1; it never introduces another visual intensity. Direct Tier 2 state always wins if both classes are present.

### Cross-Report Anchor Signal

A loaded/pinned report can contain an ordinary fact that is archived behind it while another report uses the same fact in `anchor_fact_ids`. In that case the **other delayed report** receives the softer class:

```text
is-delayed-memory-secondary-linked
```

That half-accent says: "this loaded report contains a hidden fact whose exposed anchor lives in another report." The delayed-memory panel mirrors this relation, and the report modal can surface the other report under `anchored_to` for the fact.

### L4 Visual Edit Guide

| Desired change | File | Edit |
|---|---|---|
| Make archived dots dimmer/brighter | `runtime-avatar.js` | change archived opacity `0.26` |
| Make visible L4 facts brighter | `runtime-avatar.js` | change `0.52` |
| Change L4 color | `runtime-avatar.js` | `L4_MEMORY_RING_COLOR` |
| Move L4 ring | `runtime-avatar.js` | `MEMORY_RING_LAYOUT.l4.radius` |
| Make L4 dashes longer | `runtime-avatar.js` | `MEMORY_RING_LAYOUT.l4.arcRatio` or `maxArcDegrees` |
| Change archived dot transition | `runtime-avatar.css` | `.jin-avatar-memory-dash.is-memory-dot`, `jin-avatar-memory-absorb-dot` |
| Change archive semantics | `runtime-l4-memory.js` | `getArchivedFactIdSet()` |
| Hide archived facts from avatar entirely | `runtime-avatar.js` | use visible facts instead of `getFactsWithArchiveState()` in `getL4MemoryAvatarRecords()` |

The archived/visible classification itself is in:

`ui/static/js/runtime/runtime-l4-memory.js`

Important functions:

| Function | Role |
|---|---|
| `getArchivedFactIdSet()` | Collects report-covered fact ids, then removes every globally anchored fact id |
| `factMatchesArchivedIds()` | Checks direct id and `source_fact_ids` |
| `getVisibleFacts()` | Returns only facts visible in the long-term panel |
| `getFactsWithArchiveState()` | Returns all facts with `archived` flag for avatar |

## Delayed Reports Ring

The delayed ring shows delayed memory reports. Each dash is one report.

`getDelayedMemoryAvatarRecords()` treats a report as loaded when it is either pinned or present in the runtime's loaded delayed-memory id set. Both direct pinning and runtime loading therefore use the same strong base visual; the classes remain separate so interaction logic can still distinguish them.

| Report state | Avatar opacity | Color / class |
|---|---:|---|
| Normal | `0.36` | delayed color mixed with overall avatar color |
| Runtime-loaded, not pinned | `0.82` | bright `PINNED_DELAYED_MEMORY_RING_COLOR`, `is-context-loaded` |
| Pinned | `0.82` | bright `PINNED_DELAYED_MEMORY_RING_COLOR`, `is-memory-pinned` and loaded semantics |
| Secondary-linked | base state plus softer half-accent | `is-delayed-memory-secondary-linked` |

The stronger generic reference/citation/link selector intentionally does not treat a merely context-loaded delayed dash as a generic `is-context-loaded` memory hit. Its normal loaded/pinned brightness is handled by the dedicated delayed selector, preventing accidental overboost.

Files:

- `ui/static/js/runtime/runtime-avatar.js`
- `ui/static/css/runtime-avatar.css`

Places:

- delayed branch inside `appendMemorySignalRing()`;
- live pin update in `setDelayedMemoryDashPinned()`;
- loaded/link update in `syncDelayedMemoryDashState()` and `applyDelayedMemoryFactLinkGlow()`;
- cross-report relation in `getSecondaryLinkedDelayedMemoryReportIds()`.

Delayed reports also expose `attachments_ids`. Those ids feed the persistent file ring: a loaded report gives each non-pinned attached file a softer indirect-context accent, while focusing/hovering that report can give the linked file dot the stronger relational glow.

| Desired change | Edit |
|---|---|
| Make normal reports more visible | raise normal `0.36` |
| Make loaded/pinned reports less intense | lower active `0.82` and/or edit dedicated delayed CSS |
| Make active report color less white | change `PINNED_DELAYED_MEMORY_RING_COLOR` |
| Change secondary-link intensity | edit `.is-delayed-memory-secondary-linked` |
| Move delayed ring | change `MEMORY_RING_LAYOUT.delayed.radius` |
| Make report dashes thicker | change `MEMORY_RING_LAYOUT.delayed.strokeWidth` |

## Active Memory Ring

The active ring shows active memory records. It is the outermost **memory-dash** ring and is intentionally bright; the file-dot perimeter sits beyond it.

Current behavior:

| Visual rule | Value |
|---|---|
| Color | `ACTIVE_MEMORY_RING_COLOR` |
| Opacity | `0.76` |
| Radius | `MEMORY_RING_LAYOUT.active.radius` = `178` |

File:

`ui/static/js/runtime/runtime-avatar.js`

Places:

- `getActiveMemoryAvatarRecords()`;
- active branch inside `appendMemorySignalRing()`;
- `MEMORY_RING_LAYOUT.active`.

Active memory records come from strings like:

```text
active_memory: ...
active_memory_2: ...
```

For hover identity, active records use `[active_memory_id: abc123]` embedded in the text when present; otherwise the fallback id is `record-<index>`.

If you want active memory to feel less dominant, lower opacity or move the ring inward.

## Persistent Files Ring

The outermost signal layer is a slow counter-orbit of persistent file dots. It is sourced from `window.JinFiles.getFiles()` and uses one dot per valid persistent file.

Configuration:

```js
FILE_RING_LAYOUT = {
  radius: 188,
  dotRadius: 2.7,
  baseColor: "#7ab8d8",
  glowColor: "#7ab8d8",
  startAngle: -12,
}
```

The ring duration is seeded from the file-id set and falls in roughly `92..176s`. File records are sorted by id before assigning slots, so pinning/unpinning or delayed-context changes alter only appearance, never the dot's angular position.

### File Dot States

| State | Base appearance | Class / source |
|---|---|---|
| Stored, inactive | blue dot, opacity `0.36` | normal file record |
| Directly pinned/attached | bright white dot, opacity `0.96` | `is-memory-pinned`, `is-context-loaded` |
| Indirectly in context through loaded delayed report | half-accent, not white | `is-delayed-memory-context-linked` |
| Hovered in file UI | same half-accent as indirect context link | `is-memory-hover-hit` |
| Referenced by JIN / relation-focused | stronger cyan relation glow | `is-memory-reference-hit` / `is-delayed-memory-linked-hit` |

A crucial distinction in `getPersistentFileAvatarRecords()`:

- `contextLoaded` means the file itself is pinned;
- `contextLinked` means the file is **not pinned**, but at least one loaded delayed report lists its id in `attachments_ids`.

Indirect context deliberately stays weaker than direct attachment. A pinned file keeps the stronger white state even while hovered or indirectly linked.

### File Identity And Matching

File hover identity is:

```text
file:<file_id>
```

Reference aliases include the six-character file id, original name, stored name, `/assets/files/...` context path, URL when available, and the stored name with the generated id prefix stripped. The SVG node also carries the linked delayed-report ids so `applyDelayedMemoryFileLinkGlow()` can light attachment dots when a delayed report is focused.

File hover sources include the `[ files ]` memory panel, delayed-report attachment chips/picker options, and the fixed attached-files plaque. Pin/name/attachment hover can therefore target the same dot without duplicating identity logic.

### File Ring Sync

`syncFilesState()` compares the current file-id set with the rendered file ring:

- same ids: update classes/data/colors in place and keep the current orbit animation;
- changed ids: rebuild the file ring;
- `jin:files-store-changed`: trigger sync;
- delayed-memory sync also triggers file sync because `attachments_ids` may change indirect context state.

## Center Core

The center is a visual anchor. It is drawn after all signal layers and sits on top.

It is made of:

- three thin circles;
- a soft radial glow;
- a soft inner circle;
- a core;
- a bright point.

File:

`ui/static/js/runtime/runtime-avatar.js`

Main places:

| Visual part | Edit |
|---|---|
| Center circles | `appendCenter()` |
| Core radius/opacity | `appendCenter()` |
| Default color | `DEFAULT_CENTER_COLOR` |
| Color transition speed | `CENTER_COLOR_STEP_MS` |
| Scene tint strength | `JIN_SCENE_COLOR_INTENSITY` |

`setCenterColor()` also updates page-level CSS variables:

| Variable | Meaning |
|---|---|
| `--jin-color` | Current JIN accent |
| `--scene-base-color` | Scene background tint |
| `--scene-jin-tint-alpha` | Scene tint opacity |

Lower `JIN_SCENE_COLOR_INTENSITY` if the center color affects the page too much.

## Ambient Shell, Depth, And Entry Softness

The avatar shell now has two CSS-only depth layers outside the SVG:

- `.jin-runtime-avatar-shell::before` — a soft radial aura colored from `--jin-color`, breathing on a `9s` cycle;
- `.jin-runtime-avatar-shell::after` — a dark radial/vignette depth layer that makes the radar feel embedded rather than flat.

These layers are deliberately ambient. They do not represent memory records and they do not become stronger just because the memory panel is collapsed.

Freshly redrawn runtime orbit entries use `jin-avatar-orbit-enter` for about `0.92s`, moving through a soft scale-in (`0.82` -> near full size -> slight `1.012` overshoot -> settled). This restores entry softness without changing the seeded orbit geometry.

Reduced-motion rules disable the breathing/rotation/entry animations where appropriate.

## Glow States

Glow is mostly CSS. JavaScript decides which semantic class to apply; CSS decides intensity, saturation, drop-shadow, stroke width, dot radius, and transition feel.

File:

`ui/static/css/runtime-avatar.css`

| Class | Trigger | Meaning |
|---|---|---|
| `is-memory-hover-hit` | Hovering the matching runtime/memory/file row | "User is pointing at this item" |
| `is-runtime-cited` | Hovering or activating a think citation | "This runtime/memory item is cited" |
| `is-memory-reference-hit` | JIN text references a unique alias | "This item was mentioned" |
| `is-memory-pinned` | Delayed report or file is pinned | direct strong context importance |
| `is-context-loaded` | Delayed report is runtime-loaded; on file dot, file itself is pinned | direct context presence |
| `is-delayed-memory-linked-hit` | Focused delayed report links to an L4 fact or file | strong cross-layer relation |
| `is-delayed-memory-secondary-linked` | Loaded report's hidden ordinary fact is anchored by another report | softer delayed-report relation |
| `is-delayed-memory-context-linked` | Non-pinned file is attached to a loaded delayed report | softer indirect file context |
| `is-memory-archived` | L4 fact is structurally archived behind report content | hidden-from-direct-context marker |
| `is-memory-dot` | Archived L4 dot state | dash arc fades and dot remains |

### Visual Priority

Direct active states should read stronger than inferred relations:

1. pinned/direct context and explicit reference/link hits;
2. ordinary row hover / secondary delayed link / indirect file context;
3. normal stored state.

For files specifically, ordinary hover and indirect delayed context intentionally share the same half-accent. They must not become the bright white used for a directly pinned file.

## Hover Matching

Hover matching connects rows and plaques to shapes in the radar avatar.

The shared identity is:

```js
buildAvatarMemoryHoverId(kind, id)
```

Identity helper:

`ui/static/js/runtime/runtime-core.js`

Major dispatch sources:

- `ui/static/js/runtime/runtime-memory-view.js` — runtime/L4/delayed/active/files rows plus delayed-report attachment chips/picker options;
- `ui/static/js/dragdrop.js` — attached-files plaque.

Avatar-side application:

`ui/static/js/runtime/runtime-avatar.js`

Shapes:

| Memory type | Hover id shape |
|---|---|
| Runtime line | `runtime:<line_id>` or `runtime:line-<index>` |
| L4 fact | `l4:<fact_id>` |
| Delayed report | `delayed:<report_id>` |
| Active memory | `active:<active_memory_id>` or `active:record-<index>` |
| Persistent file | `file:<file_id>` |

Cross-layer behavior is separate from same-id hover:

- hover/focus an L4 fact -> delayed reports whose `anchor_fact_ids` contain it can glow;
- hover/focus a delayed report -> its linked L4 facts from `facts_ids` can glow, including archived dots;
- loaded/pinned delayed reports keep linked L4 facts highlighted without row hover;
- if one of those hidden ordinary facts is an anchor in another report, that other report gets the softer secondary-link accent;
- hover/focus a delayed report -> attached file dots from `attachments_ids` can receive the stronger relation glow;
- a non-pinned file that belongs to any loaded delayed report keeps the softer indirect-context accent even without hover.

If hover glow stops working, first check that the source row/plaque and the SVG node agree on `data-avatar-memory-hover-id`, then check whether the expected effect is a direct hover or a cross-layer relation class.

## Citation Matching

Citation/reference matching connects think citations and JIN output text to radar shapes.

For visual changes, edit:

`ui/static/css/runtime-avatar.css`

For matching logic, edit:

`ui/static/js/runtime/runtime-avatar.js`

Main function:

```js
applyThinkRuntimeCitationGlow()
```

For L4 facts, matching uses a strict identity tuple:

```js
buildCitationRecordIdentity(id, key, value)
```

This prevents two facts with the same key from glowing incorrectly.

For runtime, active, and delayed records, matching can fall back to exact normalized line text or a unique normalized key when no strict identity is present.

Persistent file dots participate in the same reference layer. Their aliases include id/name/stored path variants, so JIN mentioning a unique file id or file name can light the corresponding dot. File SVG text identity is normalized from `name · contextPath`.


## Central Button

The center button is visually part of the radar avatar. It toggles the visibility of the original radar memory layers without refreshing the SVG data.

DOM id:

`#memory-layers-toggle`

Visual style:

`ui/static/css/runtime-avatar.css`

Click behavior:

`ui/static/js/socket/input.js`

Current click behavior:

```js
window.JinRuntime.avatar.toggleMemoryLayers()
```

The click toggles `is-memory-layers-hidden` on `#jin-runtime-avatar`. Current CSS hides:

- scaffold;
- runtime orbit entries;
- delayed/L4/active memory rings and dashes;
- thin center rings.

The central light remains visible. The **file ring currently also remains visible**, because `.jin-avatar-file-ring` / `.jin-avatar-file-dot` are not part of the `is-memory-layers-hidden` selector. Treat that as current behavior when changing the toggle; do not assume "memory layers" automatically includes files.

The old manual fact-check WebSocket path still exists separately, but center click does not start fact-check and does not call `avatar.refresh()`.

## Edit Recipes

### Make archived L4 dots almost invisible

File: `ui/static/js/runtime/runtime-avatar.js`

Change:

```js
opacity: record.archived ? 0.12 : 0.52
```

### Make normal delayed reports stronger

Change the inactive branch in `appendMemorySignalRing()`:

```js
opacity: active ? 0.82 : 0.50
```

Do not change the active `0.82` unless you also want runtime-loaded and pinned reports to become weaker/stronger together.

### Change the secondary delayed-report accent

File: `ui/static/css/runtime-avatar.css`

Edit:

```css
.jin-avatar-memory-dash-delayed.is-delayed-memory-secondary-linked
```

Keep it visibly below the direct loaded/pinned white state.

### Make active memory less dominant

Change active opacity in `runtime-avatar.js`, for example:

```js
opacity: 0.58
```

Or move `MEMORY_RING_LAYOUT.active.radius` inward.

### Move all memory/file signal layers outward

Adjust:

```js
MEMORY_RING_LAYOUT.delayed.radius
MEMORY_RING_LAYOUT.l4.radius
MEMORY_RING_LAYOUT.active.radius
FILE_RING_LAYOUT.radius
```

Keep spacing so hover and link glows do not visually merge.

### Change file-dot size or base visibility

File: `ui/static/js/runtime/runtime-avatar.js`

Use:

```js
FILE_RING_LAYOUT.dotRadius
```

and the `record.pinned ? 0.96 : 0.36` opacity branch inside `appendFileSignalRing()`.

For hover/indirect-context intensity, edit the file selectors in `runtime-avatar.css`, not the dot geometry.

### Make runtime rings calmer

File: `ui/static/js/runtime/runtime-avatar.js`

Change:

```js
const baseSpeed = 6 + random() * 18;
```

### Change punctuation stripes

The trigger is in `appendOrbit()`:

```js
if (/[!?]/.test(String(record.value || ""))) {
  appendLongFieldStripes(orbitGroup, record, ringColor);
}
```

Change the regexp if you want different semantic punctuation. Change `appendLongFieldStripes()` only if you want different stripe count/height/span/opacity.

### Make memory signal rings rotate faster

Change `getMemoryRingAnimation()`:

```js
active: [28, 54],
delayed: [40, 80],
l4: [34, 70],
```

Lower duration means faster rotation. File-ring duration is separate in `appendFileSignalRing()`.

### Change hover glow intensity

File: `ui/static/css/runtime-avatar.css`

Edit the runtime/memory/file `is-memory-hover-hit` selectors. Remember that non-pinned file hover intentionally shares the secondary/indirect half-accent level.

### Change citation/reference glow intensity

File: `ui/static/css/runtime-avatar.css`

Edit the `is-runtime-cited`, `is-memory-reference-hit`, and relation-hit selectors for the relevant shape family.

### Change avatar panel size

File: `ui/static/css/base.css`

Edit:

```css
--runtime-avatar-panel-size
```

Then verify circular geometry, collapsed mode, and Win95 theme. The shell keeps `aspect-ratio: 1`, and the SVG uses `preserveAspectRatio: "xMidYMid meet"`.


## Visual QA Checklist

Use this after avatar visual/state changes.

| Check | Expected result |
|---|---|
| Page reload | Radar avatar appears centered and circular in the runtime panel |
| Shell aura | Soft `--jin-color` aura breathes without turning into a harsh collapsed-state glow |
| Runtime update | Inner orbits refresh; entry animation is soft rather than a hard pop |
| Runtime value contains `?` or `!` | That orbit gets the legacy vertical stripe texture |
| Long runtime value without `?`/`!` | Length alone does not create stripes |
| Runtime diff changes | Ring speed and scaffold-ray energy respond without becoming noisy |
| Center click | Scaffold/runtime/memory dash layers hide without refresh; central light and current file ring remain visible |
| Runtime memory row hover | Matching inner orbit glows |
| L4 row hover | Matching L4 dash or archived dot glows |
| Delayed row hover | Matching delayed dash glows and linked L4 facts/file attachments react |
| Active memory row hover | Matching active dash glows |
| File row/plaque hover | Matching non-pinned file dot gets the softer half-accent |
| Think citation/reference | Matching orbit, dash, dot, or uniquely named file gets the stronger citation/reference glow |
| Normal delayed report | Dim base dash at `0.36` |
| Runtime-loaded delayed report | Bright active dash at `0.82` even when not pinned |
| Pinned delayed report | Same strong active family, with pin state retained |
| Loaded report with ordinary `facts_ids` fact | Fact remains archived as a dot; load does not turn it back into a dash |
| Direct fact id used as any `anchor_fact_id` | That id is removed from the archive-id set; merged `source_fact_ids` can still affect final classification |
| Loaded report ordinary fact anchored by another report | Other report gets softer secondary-linked accent |
| Long-term facts panel | Archived ordinary report facts stay hidden; globally anchored facts stay listed |
| Persistent files | One outer dot per file, stable slot order by id |
| Pin a file | Same dot becomes bright white without jumping/restarting solely because of pin state |
| Unpin file while loaded report references it | Dot falls back to the softer indirect-context accent |
| Unpin file with no loaded-report link | Dot returns to normal blue state |
| Switch away from `[runtime]`, then receive L1 update | Visible tab stays put, but radar still updates to newest L1 snapshot |
| Collapsed memory panel | Radar keeps stable size |
| Win95 theme | Radar still fits |
| Reduced motion | Orbit/scaffold/entry animations are suppressed appropriately |

## Final Rule Of Thumb

If the change is about **what a radar mark means**, edit the record collectors, delayed/L4/file link logic, or L4 archive helper.

If the change is about **how the radar looks**, edit `runtime-avatar.js` constants/render helpers or `runtime-avatar.css`.

If the change is about **whether a row/plaque and an avatar mark glow together**, check `buildAvatarMemoryHoverId()`, `data-avatar-memory-hover-id`, and then the cross-layer relation functions.

If a file is directly pinned versus merely inherited through a loaded delayed report, preserve that distinction: direct = bright white; indirect = half-accent.

If an ordinary L4 fact belongs to a report, loading that report should change emphasis, not archive semantics. Anchor ids are the structural exception at the archive-id level; for merged facts, remember that `source_fact_ids` also participate in the final archived match.

If the browser still shows an old visual after reload, bump the relevant script/stylesheet query string in `ui/templates/index.html`.
