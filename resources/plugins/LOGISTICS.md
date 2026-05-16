# DCS Retribution — Logistics Module

## What this adds

A full logistics system for DCS Retribution campaigns:

| Feature | Description |
|---|---|
| **Troop Drop Zones** | Player-defined circular zones for infantry delivery. Appear as DCS trigger zones in the `.miz` file. |
| **Cargo Drop Zones** | Same as above, but typed for supply crates, vehicles, and ammunition pallets. |
| **Warehouse inventory** | Each base tracks stock across 5 categories: ammunition, fuel, spare parts, troops, vehicles. Stock persists across turns. |
| **Import / Export** | Transfer stock between bases instantly (pre-mission balancing) or via scheduled helicopter/transport flights. |
| **Turn rollover** | Warehouse stock carries forward to the next round. Fuel spoils slightly each turn. Reservations reset. |
| **Lua delivery script** | Runs inside the DCS mission. Reports delivery success/failure back to `state.json`. |
| **FastAPI REST routes** | Full CRUD for drop zones, warehouses, and transfers. Auto-documented at `/docs`. |
| **Qt panel** | Three-tab UI: Drop Zones, Warehouses, Transfers. Integrates into the existing main window. |
| **Full test suite** | 30+ unit and integration tests covering all layers. |

---

## File layout

```
game/
  logistics/
    __init__.py          ← public API
    dropzone.py          ← DropZone data model
    warehouse.py         ← Warehouse + WarehouseItem
    transfer.py          ← LogisticsTransfer lifecycle
    manager.py           ← LogisticsManager (orchestrator)
  server/
    routes/
      logistics.py       ← FastAPI REST endpoints

qt/
  logisticspanel.py      ← PySide6 UI panel (3 tabs)

resources/
  plugins/
    retribution_logistics.lua  ← In-mission Lua delivery script

tests/
  test_logistics.py      ← Full test suite (pytest)
```

---

## How to fork and push to your GitHub

### Step 1 — Fork the upstream repo on GitHub

1. Go to https://github.com/dcs-retribution/dcs-retribution
2. Click **Fork** (top right)
3. Set owner to **krazyj83**, name to **dcs-retribution2** (or any name you prefer)
4. Click **Create fork**

### Step 2 — Clone your fork locally

```bash
git clone https://github.com/krazyj83/dcs-retribution2.git
cd dcs-retribution2
```

### Step 3 — Create a feature branch

```bash
git checkout -b feature/logistics-module
```

### Step 4 — Copy the logistics files in

```bash
# From the directory containing this bundle:

# Core Python module
cp -r game/logistics/         <your-repo>/game/logistics/
cp    game/server/routes/logistics.py  <your-repo>/game/server/routes/logistics.py

# Qt panel
cp    qt/logisticspanel.py    <your-repo>/qt/logisticspanel.py

# Lua script
cp    resources/plugins/retribution_logistics.lua \
      <your-repo>/resources/plugins/retribution_logistics.lua

# Tests
cp    tests/test_logistics.py <your-repo>/tests/test_logistics.py
```

### Step 5 — Register the FastAPI router

In `game/server/app.py` (or wherever the FastAPI app is created), add:

```python
from game.server.routes.logistics import router as logistics_router
app.include_router(logistics_router)
```

### Step 6 — Attach LogisticsManager to the Game object

In `game/game.py`, add to `__init__`:

```python
from game.logistics import LogisticsManager

# Inside Game.__init__:
self.logistics = LogisticsManager()

# Initialise warehouses for each control point:
for cp in self.theater.control_points:
    is_farp = getattr(cp, 'is_farp', False)
    self.logistics.ensure_warehouse(
        cp_id=cp.id,
        cp_name=cp.name,
        coalition=cp.captured_by,
        is_farp=is_farp,
    )
```

### Step 7 — Add the Qt panel to the main window

In `qt/windows/mainwindow.py`:

```python
from qt.logisticspanel import LogisticsPanel

# In MainWindow.__init__ or _build_tabs():
self.logistics_panel = LogisticsPanel(self.game)
self.tab_widget.addTab(self.logistics_panel, "Logistics")
```

### Step 8 — Wire turn lifecycle hooks

In the turn processor (wherever `finish_turn()` / `process_turn_results()` are called):

```python
# At end of player turn (before mission generation):
game.logistics.on_turn_end(current_turn=game.turn)

# During mission generation:
game.logistics.inject_into_mission(mission)   # adds DZ trigger zones

# After state.json is processed:
game.logistics.on_state_processed(state_dict, current_turn=game.turn)

# At start of new turn:
game.logistics.on_turn_start(previous_snapshot=previous_logistics_dict)
```

### Step 9 — Save / load

In your campaign serialiser (`game/persistence.py` or equivalent):

```python
# Save:
data["logistics"] = game.logistics.to_dict()

# Load:
from game.logistics import LogisticsManager
game.logistics = LogisticsManager.from_dict(data.get("logistics", {}))
```

### Step 10 — Run the tests

```bash
pip install pytest
pytest tests/test_logistics.py -v
```

You should see all tests pass (they have no external dependencies — no pydcs, no Qt).

### Step 11 — Commit and push

```bash
git add game/logistics/ game/server/routes/logistics.py \
        qt/logisticspanel.py resources/plugins/retribution_logistics.lua \
        tests/test_logistics.py LOGISTICS.md
git commit -m "feat: add logistics module (drop zones, warehouses, transfers)"
git push origin feature/logistics-module
```

### Step 12 — Open a Pull Request

Go to https://github.com/krazyj83/dcs-retribution2 and open a PR from
`feature/logistics-module` → `dev`.

---

## Design notes

### Why no neural network for the warehouse?
The warehouse is a simple ledger — add, subtract, cap at capacity. Complexity lives in
*what* the player does with it (routing supply convoys, prioritising scarce fuel) not in
the data model itself. Keeping the model simple means it's easy to serialise, test, and extend.

### Why is spoilage only on fuel?
Fuel evaporation is a real logistics concern in real-world air campaigns. Ammunition and spare
parts don't meaningfully degrade on the timescale of a DCS campaign turn (days to weeks).
The spoilage system is extensible — just update `SPOILAGE_RATE` in `warehouse.py`.

### Why does rollover clear reservations?
Reservations represent "this stock is earmarked for a flight that hasn't taken off yet."
At turn boundary, all planned missions either launched (stock consumed) or were cancelled.
Carrying reservations across turns would incorrectly block stock that's actually available.

### Lua ↔ Python state exchange
The Lua script writes `logistics_events` into the same `retribution_state.json` that the
existing event exporter produces. Python reads this on `on_state_processed()`. The only
coupling is the `transfer_id` UUID — stable across the mission lifecycle.
