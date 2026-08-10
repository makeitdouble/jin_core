LIVE_AVATAR v1.0

# Live Avatar Visual Manual

This manual documents the visual side of the live avatar: what each part on the avatar means, how it reacts to memory state, and where to change each visual behavior.

It is intentionally not a full architecture document. The goal is practical: if you look at the avatar and ask "what is this ring?" or "where do I make this brighter, faster, wider, or calmer?", this file should point you to the exact place.

## The Mental Picture

The live avatar is a memory radar. The inner moving rings represent the current runtime memory snapshot. The outer dashed rings represent memory systems around that snapshot: L4 long-term facts, delayed reports, and active memory. The center is the JIN accent light; it also feeds the scene tint.

Read it like this:

| Visual cue                  | Meaning |
|-----------------------------|---|
| Inner moving rings          | Current runtime memory lines |
| Faster inner motion         | Larger runtime memory diff |
| Color shifts in inner rings | Keyword/emotional content in runtime memory |
| Runtime change markers      | Last real runtime transition: filled = new line, hollow = changed line |
| L4 blue dashes              | Long-term facts |
| Dim L4 dots                 | L4 facts already represented by delayed reports |
| Delayed report dashes       | Stored delayed memory reports |
| Bright delayed dashes       | Pinned delayed memory reports |
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
| Browser cache after visual edits | `ui/templates/index.html` | bump query string for changed CSS/JS |

## Visual Stack

The avatar is drawn as a single SVG inside `#jin-runtime-avatar`. Each render replaces the old SVG with a fresh one.

The stack is built in this order:

1. SVG definitions: gradients and glow filters.
2. Static scaffold: faint background circles and radial guide lines.
3. Runtime rings: one moving orbit per runtime memory line.
4. Memory signal rings: L4, delayed, active dashes.
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
| `appendMemorySignalRings()` | draws L4, delayed, active dash rings |
| `appendCenter()` | draws center core |
| `applyThinkRuntimeCitationGlow()` | applies citation glow |
| `applyMemoryReferenceGlow()` | applies reference glow |
| `applyMemoryRowAvatarHoverGlow()` | applies hover glow |

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
| Ring radius | Relative length of that memory line |
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

The memory signal rings are the outer dashed rings. They are not runtime memory lines. They represent separate memory systems around the current runtime state.

They are configured in:

```js
MEMORY_RING_LAYOUT
```

File:

`ui/static/js/runtime/runtime-avatar.js`

| Ring | Radius | Meaning |
|---|---:|---|
| L4 | `156` | Long-term facts |
| Delayed | `166` | Delayed memory reports |
| Active | `176` | Active memory records |

Each item becomes one dash. So 10 L4 facts means 10 L4 dashes. 3 delayed reports means 3 delayed dashes.

### Memory Ring Layout Controls

| Field | Meaning |
|---|---|
| `radius` | How far from center the ring sits |
| `strokeWidth` | Thickness of dash stroke |
| `minArcDegrees` | Smallest dash length |
| `maxArcDegrees` | Largest dash length |
| `arcRatio` | How much of each item slot is filled |
| `startAngle` | Where the first dash starts |

Use these fields when you want to move a ring inward/outward or change how dense the dashes feel.

## L4 Facts Ring

The L4 ring shows long-term facts. Each dash is one L4 fact.

There are two visual states:

| L4 state | Meaning | Avatar |
|---|---|---|
| Visible fact | Fact is directly available in long-term context | normal blue dash |
| Archived fact | Fact is represented by a delayed report | dim blue dash |

Current opacity:

```js
opacity: record.archived ? 0.26 : 0.52
```

File:

`ui/static/js/runtime/runtime-avatar.js`

Place:

L4 branch inside `appendMemorySignalRing()`.

### L4 Archived Meaning

Archived does not mean deleted. It means the fact is already covered by a delayed report and should not be shown as a direct long-term context line.

Visual behavior:

- It stays visible in the avatar.
- It becomes half as bright.
- It disappears from the long-term facts panel.

Anchor facts are the exception. If a delayed report lists a fact in `anchor_fact_ids`, that fact remains visible and is not dimmed.

### L4 Visual Edit Guide

| Desired change | File | Edit |
|---|---|---|
| Make archived facts dimmer | `runtime-avatar.js` | lower `0.26` |
| Make archived facts brighter | `runtime-avatar.js` | raise `0.26` |
| Make all L4 facts brighter | `runtime-avatar.js` | raise `0.52` |
| Change L4 color | `runtime-avatar.js` | `L4_MEMORY_RING_COLOR` |
| Move L4 ring | `runtime-avatar.js` | `MEMORY_RING_LAYOUT.l4.radius` |
| Make L4 dashes longer | `runtime-avatar.js` | `MEMORY_RING_LAYOUT.l4.arcRatio` or `maxArcDegrees` |
| Hide archived facts from avatar entirely | `runtime-avatar.js` | use `getVisibleFacts()` instead of `getFactsWithArchiveState()` in `getL4MemoryAvatarRecords()` |

The archived/visible classification itself is in:

`ui/static/js/runtime/runtime-l4-memory.js`

Important functions:

| Function | Role |
|---|---|
| `getArchivedFactIdSet()` | Collects hidden fact ids from delayed reports |
| `factMatchesArchivedIds()` | Checks direct id and `source_fact_ids` |
| `getVisibleFacts()` | Returns only facts visible in long-term panel |
| `getFactsWithArchiveState()` | Returns all facts with `archived` flag for avatar |

## Delayed Reports Ring

The delayed ring shows delayed memory reports. Each dash is one report.

Normal reports are dimmer. Pinned reports are much brighter, almost white.

| Report state | Avatar opacity | Color |
|---|---:|---|
| Normal | `0.36` | `DELAYED_MEMORY_RING_COLOR` mixed with overall avatar color |
| Pinned | `0.82` | `PINNED_DELAYED_MEMORY_RING_COLOR` |

File:

`ui/static/js/runtime/runtime-avatar.js`

Places:

- delayed branch inside `appendMemorySignalRing()`
- live pin update in `setDelayedMemoryDashPinned()`

Use this section when you want reports to feel more or less present.

| Desired change | Edit |
|---|---|
| Make normal reports more visible | raise `0.36` |
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
| Radius | `MEMORY_RING_LAYOUT.active.radius` = `176` |

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
| `is-memory-archived` | L4 fact is archived by report | Marker for hidden-from-context facts |

Use CSS for brightness, drop-shadow, stroke-width, and transition feel. Use JS only if the matching logic changes.

## Hover Matching

Hover matching connects rows in the memory panel to shapes in the avatar.

The shared identity is:

```js
buildAvatarMemoryHoverId(kind, id)
```

File:

`ui/static/js/runtime/runtime-core.js`

Shapes:

| Memory type | Hover id shape |
|---|---|
| Runtime line | `runtime:<line_id>` |
| L4 fact | `l4:<fact_id>` |
| Delayed report | `delayed:<report_id>` |
| Active memory | `active:<active_id>` |

L4 and delayed memory also cross-highlight through their fact links. Hovering an L4 fact lights any delayed report that lists the fact in `anchor_fact_ids`. Hovering a delayed report lights the related L4 dots and dashes from its `facts_ids`, if the report has linked facts.

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

## Central Button

The center button is visually part of the avatar. It currently refreshes the avatar drawing.

DOM id:

`#fact-check-trigger`

Visual style:

`ui/static/css/runtime-avatar.css`

Click behavior:

`ui/static/js/socket/input.js`

Current click behavior:

```js
window.JinRuntime.avatar.refresh()
```

The old manual fact-check WebSocket path still exists separately, but the center click currently redraws the avatar rather than starting fact-check.

## Edit Recipes

### Make archived L4 facts almost invisible

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
MEMORY_RING_LAYOUT.l4.radius
MEMORY_RING_LAYOUT.delayed.radius
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
| Center click | Avatar redraws with same data and fresh seeded layout |
| Runtime memory row hover | Matching inner orbit glows |
| Long-term fact row hover | Matching L4 dash glows |
| Delayed report row hover | Matching delayed dash glows |
| Active memory row hover | Matching active dash glows |
| Think citation hover | Matching orbit or dash gets citation glow |
| Pinned delayed report | Dash becomes brighter and whiter |
| Unpinned delayed report | Dash returns to normal dim blue |
| Archived L4 fact | Dash remains but is dimmer |
| Long-term facts panel | Archived L4 facts are not listed |
| Collapsed panel | Avatar keeps stable size |
| Win95 theme | Avatar still fits |
| Reduced motion | Orbit animations stop |

## Final Rule Of Thumb

If the change is about what the avatar means, edit the record collectors or L4 visibility helpers.

If the change is about how the avatar looks, edit `runtime-avatar.js` constants/functions or `runtime-avatar.css`.

If the change is about whether a row and a dash glow together, check `buildAvatarMemoryHoverId()` and `data-avatar-memory-hover-id`.

If the change is visible in browser but not after reload, bump the script or stylesheet query string in `ui/templates/index.html`.
