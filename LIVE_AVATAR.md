LIVE_AVATAR v1.0

# Live Avatar Visual Manual

This manual documents the visual side of the live avatar: what each part on the avatar means, how it reacts to memory state, and where to change each visual behavior.

It is intentionally not a full architecture document. The goal is practical: if you look at the avatar and ask "what is this ring?" or "where do I make this brighter, faster, wider, or calmer?", this file should point you to the exact place.

## The Mental Picture

The live avatar is a memory radar. The inner moving rings represent the current runtime memory snapshot. The outer signal rings represent memory systems around that snapshot: delayed reports, L4 long-term facts, and active memory. The center is the JIN accent light; it also feeds the scene tint.

Read it like this:

| Visual cue                  | Meaning |
|-----------------------------|---|
| Inner moving rings          | Current runtime memory lines |
| Faster inner motion         | Larger runtime memory diff |
| Color shifts in inner rings | Keyword/emotional content in runtime memory |
| Runtime change markers      | Last real runtime transition: filled = new line, hollow = changed line |
| Delayed report dashes       | Stored delayed memory reports |
| Loaded delayed glow         | Delayed report is currently loaded into runtime context |
| Bright delayed dashes       | Pinned delayed memory reports |
| L4 blue dashes              | Long-term facts |
| Dim L4 dots                 | L4 facts archived behind delayed reports |
| Bright outer dashes         | Active memory records |
| Center color                | JIN accent color and scene tint |
| Glow on hover/citation      | A memory item is being pointed at right now |

## Main Files To Touch

Most visual changes happen in one file:

`ui/static/js/runtime/runtime-avatar.js`

Use this file for rings, radii, colors, speed, dash opacity, seeded random texture, center rendering, and avatar-level event reactions.

The CSS glow and panel presentation live here:

`ui/static/css/runtime-avatar.css`

Use this file for hover glow, citation glow, memory dash glow, panel collapsed behavior, and reduced-motion behavior.

A few visual knobs are outside those two files:

| Need | File | Change |
|---|---|---|
| Avatar panel size | `ui/static/css/base.css` | `--runtime-avatar-panel-size` |
| Center color tint applied to scene | `ui/static/js/runtime/runtime-avatar.js` | `setCenterColor()`, `JIN_SCENE_COLOR_INTENSITY` |
| L4 archived/visible classification | `ui/static/js/runtime/runtime-l4-memory.js` | `getVisibleFacts()`, `getFactsWithArchiveState()` |
| Long-term facts panel visibility | `ui/static/js/runtime/runtime.js` | `getVisibleLongTermMemoryFacts()` |
| Memory row hover dispatch | `ui/static/js/runtime/runtime-memory-view.js` | `dispatchRuntimeMemoryLineAvatarHover()`, `dispatchLongTermFactAvatarHover()`, `dispatchDelayedMemoryAvatarHover()` |
| Center button click wiring | `ui/static/js/socket/input.js` | `toggleRuntimeAvatarMemoryLayers()` |
| Browser cache after visual edits | `ui/templates/index.html` | bump query string for changed CSS/JS |

## Visual Stack

The avatar is drawn as a single SVG inside `#jin-runtime-avatar`. Each render replaces the old SVG with a fresh one.

Some memory signal updates avoid a full avatar refresh. Delayed, L4, and active memory can sync their own rings in place through `syncDelayedMemoryState()`, `syncL4MemoryState()`, `syncActiveMemoryState()`, and `syncMemorySignalLayer()`.

The stack is built in this order:

1. SVG definitions: gradients and glow filters.
2. Static scaffold: faint background circles and radial guide lines.
3. Runtime rings: one moving orbit per runtime memory line.
4. Memory signal rings: delayed, L4, active.
5. Center core: the central light and glow.
6. Runtime/citation/reference/hover classes are reapplied.

The main render function is:

```js
renderAvatar(snapshot, options = {})
```

File:

`ui/static/js/runtime/runtime-avatar.js`

Important helpers:

| Helper | Role |
|---|---|
| `appendDefs()` | SVG filters and gradients |
| `appendStaticScaffold()` | background radar structure |
| `computeRingRecords()` | turns runtime lines into orbit records |
| `appendOrbit()` | draws one runtime memory orbit |
| `appendMemorySignalRings()` | draws delayed, L4, active memory signal rings |
| `appendCenter()` | draws center core |
| `applyThinkRuntimeCitationGlow()` | applies citation glow |
| `applyMemoryReferenceGlow()` | applies reference glow |
| `applyMemoryRowAvatarHoverGlow()` | applies hover glow |
| `syncMemorySignalLayer()` | rebuilds one memory signal ring in place when possible |

## Static Scaffold

The scaffold is the quiet radar structure behind the live memory rings. It does not represent a memory item directly. It gives the avatar depth and makes the active rings easier to read.

It is drawn by:

```js
appendStaticScaffold(svg, overallColor, random)
```

Change these when you want the background to feel denser, cleaner, brighter, or more technical:

| Visual part | Where |
|---|---|
| Concentric scaffold circles | `STATIC_SCAFFOLD_RADII` |
| Radial guide line range | `STATIC_RADIAL_LINE_INNER_RADIUS`, `STATIC_RADIAL_LINE_OUTER_RADIUS` |
| Scaffold circle opacity | `appendStaticScaffold()` circle attributes |
| Radial line opacity | `appendStaticScaffold()` line attributes |
| Warm radial accents | `AMBER_ACCENT` and `index % 5` logic |

Good edit examples:

- To make the avatar calmer, lower scaffold `stroke-opacity`.
- To make it more technical, add more scaffold radii or increase dash visibility.
- To make it less noisy, reduce radial guide lines or their opacity.

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
| Extra stripes | The line is long compared to the others |
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
| Long-line stripes | `runtime-avatar.js` | `appendLongFieldStripes()` |
| Runtime change markers | `runtime-avatar.js` | `appendRuntimeChangeMarker()`, `resolveRuntimeChangeMarkers()` |

`computeRingRecords()` uses `sourceOrderRatio`, not line length, for the base radius. Line length is still used to decide whether a line gets extra long-field stripes.

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

The memory signal rings are the outer dash/dot rings. They are not runtime memory lines. They represent separate memory systems around the current runtime state.

They are configured in:

```js
MEMORY_RING_LAYOUT
```

File:

`ui/static/js/runtime/runtime-avatar.js`

| Ring | Radius | Stroke width | Meaning |
|---|---:|---:|---|
| Delayed | `158` | `3.10` | Delayed memory reports |
| L4 | `168` | `1.05` | Long-term facts |
| Active | `178` | `1.35` | Active memory records |

The render and sync insertion order is `delayed`, then `l4`, then `active`. L4 intentionally sits between delayed reports and active memory.

Each item becomes one memory dash record. Delayed and active records stay dashes; archived L4 records use the same record path but visually settle into dots. So 10 L4 facts means 10 L4 memory records, some of which may appear as dots. 3 delayed reports means 3 delayed dashes.

### Memory Ring Layout Controls

| Field | Meaning |
|---|---|
| `radius` | How far from center the ring sits |
| `strokeWidth` | Thickness of dash stroke |
| `minArcDegrees` | Smallest dash length |
| `maxArcDegrees` | Largest dash length |
| `arcRatio` | How much of each item slot is filled |
| `arcTrimPixels` | Optional pixel trim before arc degrees are finalized; currently used by L4 |
| `startAngle` | Where the first dash starts |

Use these fields when you want to move a ring inward/outward or change how dense the dashes feel.

## L4 Facts Ring

The L4 ring shows long-term facts. Each visible L4 fact becomes one memory dash record. Archived facts use the same record identity, but render as a dim dot state.

There are two visual states:

| L4 state | Meaning | Avatar |
|---|---|---|
| Visible fact | Fact is directly available in long-term context | normal blue dash |
| Archived fact | Fact is covered by a delayed report and is not currently anchored or loaded | dim blue dot; the dash arc fades away |

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

Place:

L4 branch inside `appendMemorySignalRing()`.

### L4 Archived Meaning

Archived does not mean deleted. It means the fact is already covered by a delayed report and should not be shown as a direct long-term context line right now.

Visual behavior:

- It stays represented in the avatar as a dim dot.
- Its dash arc is animated away by the `is-memory-dot` CSS state.
- It disappears from the long-term facts panel while archived.

Archive ids are collected from delayed report `facts_ids`, legacy `absorbed_fact_ids`, and legacy `long_term_facts_ids`.

Anchor and loaded facts are the exceptions. If a delayed report lists a fact in `anchor_fact_ids`, or if a report is loaded into runtime context and lists the fact in `facts_ids`, that fact remains visible and is not dimmed. Pinned delayed reports count as loaded for this classification.

### L4 Visual Edit Guide

| Desired change | File | Edit |
|---|---|---|
| Make archived dots dimmer | `runtime-avatar.js` | lower `0.26` |
| Make archived dots brighter | `runtime-avatar.js` | raise `0.26` |
| Make all L4 facts brighter | `runtime-avatar.js` | raise `0.52` |
| Change L4 color | `runtime-avatar.js` | `L4_MEMORY_RING_COLOR` |
| Move L4 ring | `runtime-avatar.js` | `MEMORY_RING_LAYOUT.l4.radius` |
| Make L4 dashes longer | `runtime-avatar.js` | `MEMORY_RING_LAYOUT.l4.arcRatio` or `maxArcDegrees` |
| Change archived dot transition | `runtime-avatar.css` | `.jin-avatar-memory-dash.is-memory-dot`, `jin-avatar-memory-absorb-dot` |
| Hide archived facts from avatar entirely | `runtime-avatar.js` | use `getVisibleFacts()` instead of `getFactsWithArchiveState()` in `getL4MemoryAvatarRecords()` |

The archived/visible classification itself is in:

`ui/static/js/runtime/runtime-l4-memory.js`

Important functions:

| Function | Role |
|---|---|
| `getArchivedFactIdSet()` | Collects hidden fact ids from delayed reports, then removes anchored and loaded fact ids |
| `factMatchesArchivedIds()` | Checks direct id and `source_fact_ids` |
| `getVisibleFacts()` | Returns only facts visible in long-term panel |
| `getFactsWithArchiveState()` | Returns all facts with `archived` flag for avatar |

## Delayed Reports Ring

The delayed ring shows delayed memory reports. Each dash is one report.

Normal reports are dimmer. Loaded reports get a context glow through CSS. Pinned reports are much brighter, almost white.

| Report state | Avatar opacity | Color / class |
|---|---:|---|
| Normal | `0.36` | `DELAYED_MEMORY_RING_COLOR` mixed with overall avatar color |
| Loaded | base `0.36`, visually boosted by CSS | `is-context-loaded` |
| Pinned | `0.82` | `PINNED_DELAYED_MEMORY_RING_COLOR`, `is-memory-pinned`; also treated as loaded |

File:

`ui/static/js/runtime/runtime-avatar.js`

Places:

- delayed branch inside `appendMemorySignalRing()`
- live pin update in `setDelayedMemoryDashPinned()`
- live loaded/link update in `syncDelayedMemoryDashState()` and `applyDelayedMemoryFactLinkGlow()`

Use this section when you want reports to feel more or less present.

| Desired change | Edit |
|---|---|
| Make normal reports more visible | raise `0.36` |
| Make loaded reports less intense | edit `.jin-avatar-memory-dash.is-context-loaded` |
| Make pinned reports less intense | lower `0.82` |
| Make pinned color less white | change `PINNED_DELAYED_MEMORY_RING_COLOR` |
| Move delayed ring | change `MEMORY_RING_LAYOUT.delayed.radius` |
| Make report dashes thicker | change `MEMORY_RING_LAYOUT.delayed.strokeWidth` |

## Active Memory Ring

The active ring shows active memory records. This is the outermost memory signal ring and is intentionally bright.

Current behavior:

| Visual rule | Value |
|---|---|
| Color | `ACTIVE_MEMORY_RING_COLOR` |
| Opacity | `0.76` |
| Radius | `MEMORY_RING_LAYOUT.active.radius` = `178` |

File:

`ui/static/js/runtime/runtime-avatar.js`

Places:

- `getActiveMemoryAvatarRecords()`
- active branch inside `appendMemorySignalRing()`
- `MEMORY_RING_LAYOUT.active`

Active memory records come from strings like:

```text
active_memory: ...
active_memory_2: ...
```

For hover identity, active records use `[active_memory_id: abc123]` embedded in the text when present; otherwise the fallback id is `record-<index>`.

If you want active memory to feel less dominant, lower opacity or move the ring inward.

## Center Core

The center is a visual anchor. It is drawn after all rings and sits on top.

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

## Glow States

Glow is mostly CSS. JavaScript only decides which class to apply.

File:

`ui/static/css/runtime-avatar.css`

| Class | Trigger | Meaning |
|---|---|---|
| `is-memory-hover-hit` | Hovering the matching memory row | "User is pointing at this memory item" |
| `is-runtime-cited` | Hovering or activating a think citation | "This memory item is cited" |
| `is-memory-reference-hit` | JIN response text references a unique alias | "This memory item was mentioned" |
| `is-memory-pinned` | Delayed report is pinned | "This report is important" |
| `is-context-loaded` | Delayed report is loaded into runtime context | "This report is active in context" |
| `is-delayed-memory-linked-hit` | Delayed report and L4 fact are linked through fact ids | "These memory layers refer to the same fact" |
| `is-memory-archived` | L4 fact is archived by report | Marker for hidden-from-context facts |
| `is-memory-dot` | Archived L4 fact dot state | Dash arc fades away and the dot remains |

Use CSS for brightness, drop-shadow, stroke-width, and transition feel. Use JS only if the matching logic changes.

## Hover Matching

Hover matching connects rows in the memory panel to shapes in the avatar.

The shared identity is:

```js
buildAvatarMemoryHoverId(kind, id)
```

Identity helper:

`ui/static/js/runtime/runtime-core.js`

Row event dispatch:

`ui/static/js/runtime/runtime-memory-view.js`

Avatar-side glow application:

`ui/static/js/runtime/runtime-avatar.js`

Shapes:

| Memory type | Hover id shape |
|---|---|
| Runtime line | `runtime:<line_id>` or `runtime:line-<index>` |
| L4 fact | `l4:<fact_id>` |
| Delayed report | `delayed:<report_id>` |
| Active memory | `active:<active_memory_id>` or `active:record-<index>` |

L4 and delayed memory also cross-highlight through their fact links. Hovering an L4 fact lights any delayed report that lists the fact in `anchor_fact_ids`. Hovering a delayed report lights the related L4 dots or dashes from its `facts_ids`, if the report has linked facts.

Pinned or currently loaded delayed reports also keep their linked L4 facts highlighted through `is-delayed-memory-linked-hit`, even without row hover.

If hover glow stops working, check that the row and the SVG node have the same `data-avatar-memory-hover-id`.

## Citation Matching

Citation matching connects think citations to avatar shapes.

For visual changes, edit CSS:

`ui/static/css/runtime-avatar.css`

For matching logic, edit:

`ui/static/js/runtime/runtime-avatar.js`

Function:

```js
applyThinkRuntimeCitationGlow()
```

For L4 facts, matching uses a strict identity tuple:

```js
buildCitationRecordIdentity(id, key, value)
```

This prevents two facts with the same key from glowing incorrectly.

For runtime, active, and delayed records, citation matching falls back to exact normalized line text or a unique normalized key when no strict identity is present.

## Central Button

The center button is visually part of the avatar. It toggles the visibility of the avatar's memory layers without refreshing the SVG data.

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

The click toggles `is-memory-layers-hidden` on `#jin-runtime-avatar`. CSS hides the scaffold, runtime orbit entries, memory rings/dashes, and thin center rings, while the central light remains visible. The old manual fact-check WebSocket path still exists separately, but the center click does not start fact-check and does not call `avatar.refresh()`.

## Edit Recipes

### Make archived L4 dots almost invisible

File:

`ui/static/js/runtime/runtime-avatar.js`

Change:

```js
opacity: record.archived ? 0.12 : 0.52
```

### Make normal delayed reports stronger

File:

`ui/static/js/runtime/runtime-avatar.js`

Change:

```js
opacity: pinned ? 0.82 : 0.50
```

### Make active memory less dominant

File:

`ui/static/js/runtime/runtime-avatar.js`

Change active opacity:

```js
opacity: 0.58
```

Or move the ring inward:

```js
MEMORY_RING_LAYOUT.active.radius
```

### Move all memory dashes outward

File:

`ui/static/js/runtime/runtime-avatar.js`

Increase:

```js
MEMORY_RING_LAYOUT.delayed.radius
MEMORY_RING_LAYOUT.l4.radius
MEMORY_RING_LAYOUT.active.radius
```

Keep spacing between rings so hover glow does not visually merge.

### Make runtime rings calmer

File:

`ui/static/js/runtime/runtime-avatar.js`

Change:

```js
const baseSpeed = 6 + random() * 18;
```

### Make memory signal rings rotate faster

File:

`ui/static/js/runtime/runtime-avatar.js`

Change `getMemoryRingAnimation()`:

```js
active: [28, 54],
delayed: [40, 80],
l4: [34, 70],
```

Lower duration means faster rotation.

### Change hover glow intensity

File:

`ui/static/css/runtime-avatar.css`

Edit:

```css
.jin-avatar-orbit.is-memory-hover-hit,
.jin-avatar-counter-orbit.is-memory-hover-hit,
.jin-avatar-memory-dash.is-memory-hover-hit
```

### Change citation glow intensity

File:

`ui/static/css/runtime-avatar.css`

Edit:

```css
.jin-avatar-memory-dash.is-runtime-cited,
.jin-avatar-orbit.is-runtime-cited,
.jin-avatar-counter-orbit.is-runtime-cited
```

### Change avatar panel size

File:

`ui/static/css/base.css`

Edit:

```css
--runtime-avatar-panel-size
```

Then check collapsed mode and win95 theme.

## Visual QA Checklist

Use this after avatar visual changes.

| Check | Expected result |
|---|---|
| Page reload | Avatar appears in the runtime panel |
| Center click | Memory layers hide/show without avatar refresh; central light remains visible |
| Runtime memory row hover | Matching inner orbit glows |
| Long-term fact row hover | Matching L4 dash or dot glows |
| Delayed report row hover | Matching delayed dash glows, and linked L4 facts glow when fact links exist |
| Active memory row hover | Matching active dash glows |
| Think citation hover | Matching orbit or dash gets citation glow |
| Pinned delayed report | Dash becomes brighter and whiter |
| Unpinned delayed report | Dash returns to normal delayed color unless it is still context-loaded |
| Loaded delayed report | Dash gets context glow and linked L4 facts are not archived by that report |
| Archived L4 fact | Dash arc fades away and the dim dot remains |
| Long-term facts panel | Archived L4 facts are not listed; anchored or loaded facts remain listed |
| Collapsed panel | Avatar keeps stable size |
| Win95 theme | Avatar still fits |
| Reduced motion | Orbit animations stop |

## Final Rule Of Thumb

If the change is about what the avatar means, edit the record collectors or L4 visibility helpers.

If the change is about how the avatar looks, edit `runtime-avatar.js` constants/functions or `runtime-avatar.css`.

If the change is about whether a row and a dash glow together, check `buildAvatarMemoryHoverId()` and `data-avatar-memory-hover-id`.

If the change is visible in browser but not after reload, bump the script or stylesheet query string in `ui/templates/index.html`.
