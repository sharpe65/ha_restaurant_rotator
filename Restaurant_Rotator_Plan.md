# Restaurant Rotator — Home Assistant Dashboard

## Purpose
A Home Assistant dashboard tab that helps the household decide where to eat by
rotating through curated restaurant lists. Recently-visited places sink to the
bottom so favorites cycle evenly, and restaurants with a deal active *today* are
highlighted and pinned to the top of their list. A cross-category "Today's Deals"
summary sits at the top of the tab.

This document is a build spec for Claude Code. It defines the data model, the
core logic, the layout, and a phased build order. Where a v1 decision has been
made to keep scope tight, it is marked **[v1 assumption]** — adjust if desired.

---

## Tech stack / dependencies

**Data + logic engine: `pyscript` (HACS)**
The rotation sort and deal-of-the-day promotion need real Python (sorting,
date math, JSON read/write). HA's built-in `python_script` is sandboxed and
cannot do file I/O or imports, so it is **not** suitable. Use `pyscript`.
- File I/O must be wrapped in `task.executor(...)` so it doesn't block the
  HA event loop.

**Storage: a JSON file at `/config/restaurant_rotator.json`**
Chosen over MS To Do (its "completed = removed" model and lack of programmatic
reordering fight the rotation mechanic). A flat JSON file is portable,
hand-editable, and easy to back up.

**Frontend (HACS):**
- `custom:layout-card` — for the 3-column grid proportions (top row 1fr + 2fr-span).
- `custom:config-template-card` — to render a dynamic, ordered list of rows from
  a sensor attribute (the restaurant arrays are *not* HA entities, so auto-entities
  won't work; we template directly off the sensor attribute).
- `custom:button-card` — per-row rendering with a tap action (mark visited) and
  conditional styling for deal highlighting.
- Fallback if avoiding extra HACS cards: a `markdown` card can render each list
  for display, but tap-to-check-off is hard in markdown — `config-template-card`
  + `button-card` is the recommended interactive path.

---

## Data model

`/config/restaurant_rotator.json`:

```json
{
  "restaurants": [
    {
      "id": "in_n_out",
      "name": "In-N-Out",
      "category": "fast_food",
      "last_visited": "2026-06-01T18:30:00",
      "deals": [
        { "day": "tuesday", "text": "BOGO" }
      ]
    }
  ]
}
```

Field notes:
- `id` — stable slug (lowercase, underscores). Generated from name on add.
- `category` — one of `fast_food` | `casual` | `sit_down`.
- `last_visited` — ISO timestamp, or `null` for never-visited (sorts to top).
- `deals` — array (a restaurant can have deals on multiple days). Each entry is
  `{ "day": <weekday lowercase>, "text": <short label> }`. Empty array = no deals.

---

## Core logic (pyscript)

### Per-category ordered list
For each category, produce the display order:
1. `today = current weekday (lowercase)`.
2. Split the category's restaurants into **deal-today** (any `deals[].day == today`)
   and **normal**.
3. Sort **normal** by `last_visited` ascending — `null` (never visited) sorts
   first/top. Tie-break by name.
4. Sort **deal-today** the same way among themselves.
5. Final order = `deal-today` (pinned to top, flagged) + `normal`.
   - **[v1 assumption]** A deal-today restaurant pins to the top even if it was
     just visited. Simple and predictable; revisit if it feels wrong.

### Computed item shape (for the frontend)
Each rendered item should carry:
`{ id, name, last_visited, has_deal_today (bool), deal_text (str|null), days_since_visited (int|null) }`

### Exposed sensors (via `state.set` in pyscript)
- `sensor.restaurant_fast_food` — attribute `items` = ordered list (shape above).
- `sensor.restaurant_casual` — same.
- `sensor.restaurant_sit_down` — same.
- `sensor.restaurant_deals_today` — attribute `deals` = `[{ name, deal_text }]`
  across **all** categories, for the summary card. Order = fast food → casual →
  sit down, matching the columns left-to-right.

State value of each sensor can be the item count (useful for headers/empty states).

### Exposed services
- `pyscript.restaurant_add(name, category, deal_day=None, deal_text=None)`
  Appends a new restaurant with `last_visited = null` (starts at top as "new"),
  generates `id`, writes JSON, recomputes sensors.
- `pyscript.restaurant_mark_visited(id)`
  Sets `last_visited = now()`, writes JSON, recomputes. This is what naturally
  drops it toward the bottom next render.
- `pyscript.restaurant_remove(id)` — **[v1: optional]** delete a restaurant.
- `pyscript.restaurant_refresh()` — recompute sensors. Call on HA start and via a
  `@time_trigger` at `00:00` daily so deal-of-the-day rolls over at midnight.

---

## Layout

A **3-column grid** (each column `1fr`). Use `custom:layout-card` with
`grid-template`, or native **Sections** view with column spans.

```
┌──────────────┬───────────────────────────────────┐
│ Date /       │ Today's Deals                     │
│ Weather      │   (spans columns 2–3)             │
│  (col 1)     │                                   │
├──────────────┼─────────────────┬─────────────────┤
│ Fast Food    │ Casual          │ Sit Down        │
│  (col 1)     │  (col 2)        │  (col 3)        │
└──────────────┴─────────────────┴─────────────────┘
```

- Top-left card occupies column 1 only.
- "Today's Deals" spans columns 2–3 (i.e. ~2/3 width).
- The three category cards are equal thirds.
- Category cards are tall with room to grow as lists fill (let them auto-height;
  don't fix a short height).

Simpler alternative without grid-spanning: row 1 = a `layout-card`/grid at
`1fr 2fr`, row 2 = a `horizontal-stack` of the three category cards (equal width
is exactly what horizontal-stack gives).

---

## Card-by-card

### 1. Date / Weather (top-left)
- Date from `sensor.date` (or a template) + current weather.
- Use the household weather entity (McKinney, TX — confirm entity name).
- **[v1 assumption]** current conditions + temp only; forecast optional.

### 2. Today's Deals (top, spans 2 cols)
- Numbered list reading `sensor.restaurant_deals_today` attribute `deals`.
- Format per line: `<Name> – <deal_text>` (matches mockup, e.g. "Restaurant1 – BOGO").
- Empty state: "No deals today."
- `markdown` or `config-template-card` both fine here (display-only).

### 3–5. Category cards (Fast Food / Casual / Sit Down)
- Header: centered category title with an underline rule beneath (per mockup).
- Body: ordered rows from the matching sensor's `items`, rendered via
  `config-template-card` mapping each item to a `button-card`.
- Each row: a checkbox-style icon + restaurant name.
- **Tap action** on a row → `pyscript.restaurant_mark_visited(id)`.
- **Deal highlight:** if `has_deal_today`, style the row distinctly (background
  tint / badge / icon) and append the `deal_text`. These rows are already pinned
  to the top by the sort logic.

---

## "+" Add control
A simple in-dashboard add form at the bottom (per decision). Use input helpers:
- `input_text.restaurant_new_name`
- `input_select.restaurant_new_category` (options: Fast Food / Casual / Sit Down)
- `input_select.restaurant_new_deal_day` (options: None / Monday … Sunday)
- `input_text.restaurant_new_deal_text`
- An "➕ Add" button → a `script` that calls `pyscript.restaurant_add(...)` with
  the helper values, then clears the helpers.

**[v1 assumption]** Always-visible mini-form at the bottom of the tab (simplest).
A `browser_mod` popup triggered by a "+" button is a nicer-looking alternative
if preferred later.

---

## Build phases (suggested order)
1. **Data layer** — JSON schema + `pyscript`: load/save (via `task.executor`),
   services (`add`, `mark_visited`, `refresh`), computed category sensors +
   deals-today sensor, daily `@time_trigger` at midnight. Seed with a few test
   restaurants and verify sensors/attributes in Developer Tools → States.
2. **Layout shell** — the 3-column grid with placeholder cards.
3. **Category list rendering** — `config-template-card` + `button-card` reading
   the sensors; wire tap → `mark_visited`; confirm rotation works.
4. **Deals Today summary card.**
5. **Date / Weather card.**
6. **"+" add form** — helpers + script wired to `restaurant_add`.
7. **Deal highlighting / styling polish** — header underline, row tint/badge.
8. **Edge cases + testing** — empty lists, never-visited sorting, midnight deal
   rollover, multiple deals same day, accidental-tap handling.

---

## Open questions (decide before or during build)
- **Accidental taps:** mark-visited is one tap. Want a confirm dialog, an undo,
  or a hold-to-confirm instead? (Tap is fastest; undo is the gentlest safeguard.)
- **Just-visited deal restaurants:** keep pinned to top on their deal day (v1) or
  let them drop?
- **Remove/edit UI:** service exists; how to expose it — long-press a row? a
  separate manage view? (Could defer past v1.)
- **Weather entity name** and whether to show a forecast.
- **Manual reorder override** — ever want to hand-pin a place? (Probably not for v1.)
- **Household scope:** single shared dataset assumed (not per-person).