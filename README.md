# 🍔 Restaurant Rotator

A Home Assistant dashboard that helps a household decide **where to eat** by rotating through curated restaurant lists. Recently‑visited places sink to the bottom so favorites cycle evenly, restaurants with a deal active **today** are highlighted and pinned to the top, and a cross‑category **Today's Deals** summary sits up top — with a "Coming up" preview when nothing's on today.

> Built for a wall‑mounted tablet, but fully responsive (stacks to a single column on phones).

---

## ✨ Features

- **Rotation by recency** — tap a restaurant to mark it visited; it sinks to the bottom of its column. Never‑visited places float to the top.
- **Tap to toggle** — tapping a checked restaurant un‑checks it and returns it to its prior position. No accidental‑tap regret.
- **Weekly check reset** — "checked" is derived from the visit timestamp, so all checkmarks clear automatically at **Monday 00:00** while preserving list order. No reset job to maintain.
- **Deal of the day** — a restaurant with a deal active today is pinned to the top of its column, tinted gold, and listed in the Today's Deals card.
- **"Coming up" preview** — when there are no deals today, the Today's Deals card shows the next couple of upcoming deals (nearest day first).
- **In‑dashboard add form** — a "+" button opens a popup to add a new restaurant (name, category, optional deal day/text).
- **Three categories** — Fast Food, Casual, Sit Down.

---

## 🧩 How it works

- **Data + logic** live in a [pyscript](https://github.com/custom-components/pyscript) module that reads/writes a flat JSON file and publishes Home Assistant **sensors** (one per category + a deals sensor) whose attributes carry the ordered, computed lists.
- **The frontend** is a single `custom:layout-card` view that templates those sensor attributes into tappable rows via `config-template-card` + `button-card`, wrapped in `stack-in-card` so each category renders as one clean card.
- **Storage** is a hand‑editable JSON file at `/config/restaurant_rotator.json` (seeded automatically on first run).

`python_script` and MS To‑Do were both ruled out — the first can't do file I/O, the second's "completed = removed" model fights the rotation mechanic. A flat JSON file is portable, hand‑editable, and easy to back up.

---

## 📦 Dependencies

Install these via **[HACS](https://hacs.xyz/)** before setting up.

**Integrations**
| Name | HACS type | Purpose |
|------|-----------|---------|
| [pyscript](https://github.com/custom-components/pyscript) | Integration | Data layer (file I/O, sorting, services, sensors) |
| [browser_mod](https://github.com/thomasloven/hass-browser_mod) | Integration | The "+" add‑form popup |

**Frontend cards**
| Name | Purpose |
|------|---------|
| [layout-card](https://github.com/thomasloven/lovelace-layout-card) | The responsive grid |
| [config-template-card](https://github.com/iantrich/config-template-card) | Render dynamic lists from sensor attributes |
| [button-card](https://github.com/custom-cards/button-card) | Per‑row rendering + tap action |
| [stack-in-card](https://github.com/custom-cards/stack-in-card) | Merge each category column into one card |
| [card-mod](https://github.com/thomasloven/lovelace-card-mod) | CSS tweaks (heights, padding, card backgrounds) |
| [better-moment-card](https://github.com/wassy/better-moment-card) | Date/time card (top row) — *swap for your own if preferred* |
| [weather-card](https://github.com/bramkragten/weather-card) | Current‑conditions card (top row) — *swap for your own if preferred* |

---

## 🗂️ Repository contents

| File | Installs to | What it is |
|------|-------------|------------|
| `restaurant_rotator.py` | `/config/pyscript/restaurant_rotator.py` | The data + logic layer (sensors, services, triggers) |
| `restaurant_rotator.yaml` *(the package)* | `/config/packages/restaurant_rotator.yaml` | Input helpers + the add‑form script. **Filename must be lowercase** (it becomes the package slug). |
| `Restaurant_Rotator.yaml` *(the dashboard)* | Pasted into a dashboard view | The Lovelace view config |
| `Restaurant_Rotator_Plan.md` | — | The original build spec / design doc |

> In this repo the package file is named `Restaurant_Rotator_Package.yaml` for clarity; rename it to **`restaurant_rotator.yaml`** when you drop it in `/config/packages/`.

---

## 🚀 Installation

1. **Install the HACS dependencies** listed above, then restart Home Assistant.

2. **Add to `configuration.yaml`:**
   ```yaml
   pyscript:
     allow_all_imports: true
     hass_is_global: true

   recorder:
     exclude:
       entity_globs:
         - sensor.restaurant_*   # keep the big list attributes out of the DB

   homeassistant:
     packages: !include_dir_named packages
   ```

3. **Copy the files:**
   - `restaurant_rotator.py` → `/config/pyscript/restaurant_rotator.py`
   - the package → `/config/packages/restaurant_rotator.yaml` *(lowercase!)*

4. **Restart Home Assistant.** On boot, pyscript seeds `/config/restaurant_rotator.json` with a few sample restaurants and creates the sensors. Verify in **Developer Tools → States** (search `restaurant_`).

5. **Set up browser_mod:** Settings → Devices & Services → **Add Integration → Browser Mod**. Then, in the **Browser Mod** sidebar panel, toggle **Register** on for each device that will use the dashboard. *(On a wall tablet, also disable Profile → "Automatically close connection" so popups keep working after idle.)*

6. **Create the dashboard view:** edit a dashboard → add a **Panel** view → add a **Manual** card → paste `Restaurant_Rotator.yaml`.

7. **Make it yours:** edit the seed list in `restaurant_rotator.py` (only used on first run) **or** just hand‑edit `/config/restaurant_rotator.json`, and point the weather/clock cards at your own entities (the dashboard uses `weather.forecast_home`).

---

## 🧾 Data model

`/config/restaurant_rotator.json`:

```json
{
  "restaurants": [
    {
      "id": "sonic",
      "name": "Sonic",
      "category": "fast_food",
      "last_visited": "2026-06-10T18:30:00",
      "deals": [
        { "day": "tuesday", "text": "1/2 price burgers" }
      ]
    }
  ]
}
```

- `id` — stable slug (auto‑generated from the name on add).
- `category` — one of `fast_food` | `casual` | `sit_down`.
- `last_visited` — ISO timestamp, or `null` for never‑visited (sorts to top).
- `deals` — array of `{ "day": <weekday lowercase>, "text": <short label> }`.

---

## 🛠️ Services

All exposed by pyscript (call from Developer Tools → Actions, automations, or the dashboard):

| Service | What it does |
|---------|--------------|
| `pyscript.restaurant_mark_visited` | `{ id }` → stamp visited (checks it, sinks it) |
| `pyscript.restaurant_unmark_visited` | `{ id }` → toggle the check off, restore prior position |
| `pyscript.restaurant_add` | `{ name, category, deal_day?, deal_text? }` → add a restaurant |
| `pyscript.restaurant_remove` | `{ id }` → delete a restaurant |
| `pyscript.restaurant_refresh` | recompute all sensors (also runs on HA start + nightly at 00:00) |

---

## 🎨 Customization quick‑reference

All in the dashboard YAML's top `layout:` blocks:

- **Overall width** — root `max-width`.
- **Top row sizing** — `grid-template-columns: 250px 250px 460px 80px` (clock | weather | deals | "+").
- **Category column width** — `grid-template-columns: 350px 350px 350px`.
- **Row padding** — `{ padding: '3px 14px' }` in each column's row styles.
- **Card heights** — the `height: 140px` in the top cards' `card_mod`.

---

## 📝 Notes & credits

- A few household‑specific bits to swap for your own: the weather entity (`weather.forecast_home`), and the better‑moment / weather cards if you prefer different ones.
- Built collaboratively with Claude Code. See `Restaurant_Rotator_Plan.md` for the original design spec.
