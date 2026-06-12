"""Restaurant Rotator — data + logic layer (pyscript).

Drop this file in /config/pyscript/restaurant_rotator.py on the HA box.

Requires in configuration.yaml:

    pyscript:
      allow_all_imports: true
      hass_is_global: true

And (strongly recommended) keep the big list attributes out of the recorder DB:

    recorder:
      exclude:
        entity_globs:
          - sensor.restaurant_*

Reload after editing via Developer Tools -> Actions -> pyscript.reload
(or restart HA). Sensors are recreated on every HA start by the startup
trigger below, so they survive restarts even though state.set is ephemeral.
"""

import json
import pathlib
import asyncio
import datetime

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

DATA_FILE = "/config/restaurant_rotator.json"

CATEGORIES = ["fast_food", "casual", "sit_down"]

SENSOR_FOR = {
    "fast_food": "sensor.restaurant_fast_food",
    "casual": "sensor.restaurant_casual",
    "sit_down": "sensor.restaurant_sit_down",
}
DEALS_SENSOR = "sensor.restaurant_deals_today"

# Initial restaurant list, written out the first time the JSON file is missing.
# After first run the JSON file is the source of truth and this is ignored;
# add/remove later via the restaurant_add / restaurant_remove services.
# Everyone starts never-visited (last_visited = None) so order personalizes as
# you tap; deal-day places are pinned to the top of their column.
SEED = {
    "restaurants": [
        # --- Fast Food ---
        {"id": "chick_fil_a", "name": "Chick-fil-A", "category": "fast_food",
         "last_visited": None, "deals": []},
        {"id": "mcdonalds", "name": "McDonald's", "category": "fast_food",
         "last_visited": None, "deals": []},
        {"id": "sonic", "name": "Sonic", "category": "fast_food",
         "last_visited": None,
         "deals": [{"day": "tuesday", "text": "1/2 price burgers"}]},
        {"id": "whataburger", "name": "Whataburger", "category": "fast_food",
         "last_visited": None, "deals": []},
        {"id": "jersey_mikes", "name": "Jersey Mike's", "category": "fast_food",
         "last_visited": None, "deals": []},
        {"id": "subway", "name": "Subway", "category": "fast_food",
         "last_visited": None, "deals": []},
        {"id": "dominos", "name": "Domino's Pizza", "category": "fast_food",
         "last_visited": None, "deals": []},
        {"id": "wendys", "name": "Wendy's", "category": "fast_food",
         "last_visited": None, "deals": []},
        {"id": "taco_bell", "name": "Taco Bell", "category": "fast_food",
         "last_visited": None, "deals": []},
        {"id": "arbys", "name": "Arby's", "category": "fast_food",
         "last_visited": None, "deals": []},

        # --- Casual ---
        {"id": "chipotle", "name": "Chipotle", "category": "casual",
         "last_visited": None, "deals": []},
        {"id": "jasons_deli", "name": "Jason's Deli", "category": "casual",
         "last_visited": None,
         "deals": [{"day": "monday", "text": "Kids eat free"}]},
        {"id": "raising_canes", "name": "Raising Cane's", "category": "casual",
         "last_visited": None, "deals": []},
        {"id": "mooyah", "name": "Mooyah Burger", "category": "casual",
         "last_visited": None, "deals": []},
        {"id": "culvers", "name": "Culver's", "category": "casual",
         "last_visited": None, "deals": []},
        {"id": "panera", "name": "Panera Bread", "category": "casual",
         "last_visited": None, "deals": []},
        {"id": "velvet_taco", "name": "Velvet Taco", "category": "casual",
         "last_visited": None, "deals": []},
        {"id": "torchys", "name": "Torchy's", "category": "casual",
         "last_visited": None, "deals": []},
        {"id": "fuzzys", "name": "Fuzzy's", "category": "casual",
         "last_visited": None, "deals": []},

        # --- Sit Down (Dine In) ---
        {"id": "chilis", "name": "Chili's", "category": "sit_down",
         "last_visited": None, "deals": []},
        {"id": "bjs", "name": "BJ's", "category": "sit_down",
         "last_visited": None, "deals": []},
    ]
}

# In-memory "undo" stash: id -> previous last_visited value (so a row's
# accidental tap can be reverted by restaurant_undo_visit). Phase 3 (frontend)
# wires the undo toast to that service.
_undo = {}

# Guards the read-modify-write cycle so two near-simultaneous taps can't
# interleave and clobber the JSON file.
_lock = asyncio.Lock()


# --------------------------------------------------------------------------
# File I/O. The blocking read/write runs in the executor thread via real stdlib
# callables (pathlib.Path methods). pyscript refuses its own in-file functions
# in task.executor, AND doing open()/write directly in the event loop did NOT
# persist to /config on this setup — so we hand Path's bound methods (which are
# real, non-pyscript callables) to task.executor.
# --------------------------------------------------------------------------

async def _read_file():
    """Return parsed JSON dict, seeding the file if absent."""
    p = pathlib.Path(DATA_FILE)
    if not await task.executor(p.exists):
        await _write_file(SEED)
        return json.loads(json.dumps(SEED))  # deep copy
    text = await task.executor(p.read_text)
    return json.loads(text)


async def _write_file(data):
    """Persist the data file. Path.write_text is a real stdlib bound method, so
    task.executor accepts it (unlike functions defined in this pyscript file)."""
    text = json.dumps(data, indent=2)
    await task.executor(pathlib.Path(DATA_FILE).write_text, text)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _today():
    """Lowercase weekday name, e.g. 'tuesday'."""
    return datetime.datetime.now().strftime("%A").lower()


def _week_start(now):
    """Most recent Sunday 00:00 — the start of the current 'check' cycle.

    A restaurant counts as checked only if visited on/after this moment, so the
    checkmarks clear automatically at Sunday midnight (the daily @time_trigger
    refresh recomputes the sensors). No separate reset job needed, and
    last_visited is never altered, so the rotation order is preserved.
    """
    days_since_sunday = (now.weekday() + 1) % 7  # weekday(): Mon=0..Sun=6
    sunday = now - datetime.timedelta(days=days_since_sunday)
    return sunday.replace(hour=0, minute=0, second=0, microsecond=0)


def _slugify(name):
    out = []
    for ch in name.lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "_":
            out.append("_")
    return "".join(out).strip("_") or "restaurant"


def _unique_id(base, existing_ids):
    """Append _2, _3, ... if the slug collides."""
    if base not in existing_ids:
        return base
    n = 2
    while f"{base}_{n}" in existing_ids:
        n += 1
    return f"{base}_{n}"


def _deal_text_for_today(r, today):
    """Return joined deal text(s) active today, or None."""
    texts = [d.get("text", "") for d in r.get("deals", [])
             if d.get("day", "").lower() == today]
    texts = [t for t in texts if t]
    return " / ".join(texts) if texts else None


def _days_since(last_visited, now):
    if not last_visited:
        return None
    try:
        dt = datetime.datetime.fromisoformat(last_visited)
    except ValueError:
        return None
    return (now - dt).days


def _to_item(r, today, now):
    """Shape a raw restaurant record into the frontend item shape."""
    deal_text = _deal_text_for_today(r, today)
    last_visited = r.get("last_visited")
    checked = False
    if last_visited:
        try:
            checked = datetime.datetime.fromisoformat(last_visited) >= _week_start(now)
        except ValueError:
            checked = False
    return {
        "id": r["id"],
        "name": r["name"],
        "last_visited": last_visited,
        "has_deal_today": deal_text is not None,
        "deal_text": deal_text,
        "days_since_visited": _days_since(last_visited, now),
        "checked": checked,
    }


def _sort_items(items):
    """Sort by last_visited asc (never-visited '' first), tie-break by name.

    Uses decorate-sort-undecorate instead of sorted(key=...): pyscript funcs
    are async under the hood, so they can't be passed as a key callback to the
    built-in sorted(). Sorting tuples of plain str/int needs no callback. The
    running index makes every tuple unique so the item dict is never compared.
    """
    decorated = []
    idx = 0
    for i in items:
        decorated.append((i["last_visited"] or "", i["name"].lower(), idx, i))
        idx += 1
    decorated = sorted(decorated)
    return [d[3] for d in decorated]


def _ordered_for_category(restaurants, category, today, now):
    """Deal-today rows pinned to top, then normal — each group oldest-first."""
    items = [_to_item(r, today, now) for r in restaurants
             if r.get("category") == category]
    deal_today = _sort_items([i for i in items if i["has_deal_today"]])
    normal = _sort_items([i for i in items if not i["has_deal_today"]])
    return deal_today + normal


# --------------------------------------------------------------------------
# Sensor computation
# --------------------------------------------------------------------------

def _publish_sensors(data):
    """Recompute all four sensors from the in-memory data dict."""
    today = _today()
    now = datetime.datetime.now()
    restaurants = data.get("restaurants", [])

    ordered_by_cat = {}
    for cat in CATEGORIES:
        items = _ordered_for_category(restaurants, cat, today, now)
        ordered_by_cat[cat] = items
        state.set(
            SENSOR_FOR[cat],
            value=len(items),
            new_attributes={
                "items": items,
                "friendly_name": cat.replace("_", " ").title(),
                "icon": "mdi:silverware-fork-knife",
            },
        )

    # Cross-category deals summary, ordered fast_food -> casual -> sit_down,
    # preserving each category's display order.
    deals = []
    for cat in CATEGORIES:
        for item in ordered_by_cat[cat]:
            if item["has_deal_today"]:
                deals.append({"name": item["name"], "deal_text": item["deal_text"]})

    # Upcoming deals (not today), nearest day first — a "coming up" fallback the
    # UI shows when there are no deals today.
    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday",
                "saturday", "sunday"]
    today_idx = weekdays.index(today) if today in weekdays else now.weekday()
    cat_order = {}
    for i in range(len(CATEGORIES)):
        cat_order[CATEGORIES[i]] = i
    decorated = []
    idx = 0
    for r in restaurants:
        for d in r.get("deals", []):
            day = d.get("day", "").lower()
            if day not in weekdays:
                continue
            days_until = (weekdays.index(day) - today_idx) % 7
            if days_until == 0:
                continue  # active today; already counted in `deals`
            entry = {
                "name": r["name"],
                "deal_text": d.get("text", ""),
                "day": day.capitalize(),
                "days_until": days_until,
            }
            # (days_until, category order, name, idx) sorts nearest-first; idx
            # keeps tuples unique so the dict is never compared (no key callback).
            decorated.append((days_until, cat_order.get(r.get("category"), 99),
                              r["name"].lower(), idx, entry))
            idx += 1
    decorated = sorted(decorated)
    upcoming = [row[4] for row in decorated]

    state.set(
        DEALS_SENSOR,
        value=len(deals),
        new_attributes={
            "deals": deals,
            "upcoming": upcoming,
            "friendly_name": "Today's Deals",
            "icon": "mdi:tag-heart",
        },
    )

    log.info(f"[restaurant_rotator] sensors refreshed for {today}: "
             f"{len(restaurants)} restaurants, {len(deals)} deal(s) today")


# --------------------------------------------------------------------------
# Services
# --------------------------------------------------------------------------

@service
async def restaurant_refresh():
    """Recompute and publish all sensors. Safe to call anytime."""
    async with _lock:
        data = await _read_file()
        _publish_sensors(data)


@service
async def restaurant_add(name=None, category=None, deal_day=None, deal_text=None):
    """Append a new restaurant (starts never-visited, so it sorts to top)."""
    if not name or not category:
        log.warning("[restaurant_rotator] add: name and category are required")
        return
    category = category.lower().replace(" ", "_")
    if category not in CATEGORIES:
        log.warning(f"[restaurant_rotator] add: bad category '{category}'")
        return

    async with _lock:
        data = await _read_file()
        restaurants = data.setdefault("restaurants", [])
        existing = set([r["id"] for r in restaurants])
        new_id = _unique_id(_slugify(name), existing)

        deals = []
        if deal_day and str(deal_day).lower() not in ("none", ""):
            deals.append({"day": str(deal_day).lower(),
                          "text": (deal_text or "").strip() or "Deal"})

        restaurants.append({
            "id": new_id,
            "name": name.strip(),
            "category": category,
            "last_visited": None,
            "deals": deals,
        })
        await _write_file(data)
        _publish_sensors(data)
        log.info(f"[restaurant_rotator] added '{name}' ({new_id}) to {category}")


@service
async def restaurant_mark_visited(id=None):
    """Stamp last_visited = now; remember the prior value for undo."""
    if not id:
        return
    async with _lock:
        data = await _read_file()
        for r in data.get("restaurants", []):
            if r["id"] == id:
                _undo[id] = r.get("last_visited")
                r["prev_visited"] = r.get("last_visited")  # persisted, for un-toggling
                r["last_visited"] = datetime.datetime.now().isoformat(timespec="seconds")
                await _write_file(data)
                _publish_sensors(data)
                log.info(f"[restaurant_rotator] marked visited: {id}")
                return
        log.warning(f"[restaurant_rotator] mark_visited: id '{id}' not found")


@service
async def restaurant_unmark_visited(id=None):
    """Toggle a check OFF: restore last_visited to the value from before the
    most recent visit (persisted as prev_visited), so the row un-checks and
    returns to its prior position. If that prior value is itself within the
    current week (e.g. visited twice this week), restoring it would still read
    as checked, so we clear to null instead — a single tap always un-checks.
    """
    if not id:
        return
    async with _lock:
        data = await _read_file()
        week_start = _week_start(datetime.datetime.now())
        for r in data.get("restaurants", []):
            if r["id"] == id:
                prev = r.get("prev_visited")
                if prev:
                    try:
                        if datetime.datetime.fromisoformat(prev) >= week_start:
                            prev = None
                    except ValueError:
                        prev = None
                r["last_visited"] = prev
                _undo[id] = r.get("last_visited")
                await _write_file(data)
                _publish_sensors(data)
                log.info(f"[restaurant_rotator] unmarked visited: {id}")
                return
        log.warning(f"[restaurant_rotator] unmark_visited: id '{id}' not found")


@service
async def restaurant_undo_visit(id=None):
    """Restore the last_visited value from before the most recent visit tap."""
    if not id or id not in _undo:
        log.warning(f"[restaurant_rotator] undo: nothing to undo for '{id}'")
        return
    async with _lock:
        data = await _read_file()
        for r in data.get("restaurants", []):
            if r["id"] == id:
                r["last_visited"] = _undo.pop(id)
                await _write_file(data)
                _publish_sensors(data)
                log.info(f"[restaurant_rotator] undid visit: {id}")
                return


@service
async def restaurant_remove(id=None):
    """Delete a restaurant by id. (v1 optional.)"""
    if not id:
        return
    async with _lock:
        data = await _read_file()
        before = len(data.get("restaurants", []))
        data["restaurants"] = [r for r in data.get("restaurants", []) if r["id"] != id]
        if len(data["restaurants"]) == before:
            log.warning(f"[restaurant_rotator] remove: id '{id}' not found")
            return
        await _write_file(data)
        _publish_sensors(data)
        log.info(f"[restaurant_rotator] removed: {id}")


# --------------------------------------------------------------------------
# Triggers
# --------------------------------------------------------------------------

@time_trigger("startup")
def _on_startup():
    """Recreate the ephemeral state.set sensors on every HA start / reload."""
    restaurant_refresh()


@time_trigger("cron(0 0 * * *)")
def _at_midnight():
    """Roll the deal-of-the-day over at midnight."""
    restaurant_refresh()
