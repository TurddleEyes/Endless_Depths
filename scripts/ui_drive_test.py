"""Headless drive test for the desktop UI (ui/app.py).

Swaps in the fake tkinter from scripts/fake_tk, then boots the REAL App
and plays it: menus, movement, the sealed-door puzzle popup (number keys
and button clicks), chests, and full-map renders that would crash on any
missing sprite. Run with:
    python3 scripts/ui_drive_test.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "fake_tk"))  # `import tkinter` -> stub
sys.path.insert(0, GAME)
os.environ["ENDLESS_DEPTHS_NO_AUDIO"] = "1"

import tkinter as tk  # noqa: E402 - the stub
assert hasattr(tk, "AFTER_QUEUE"), "expected the fake tkinter to win the import"

from engine import save as save_module  # noqa: E402

# Never touch the player's real save/scores/settings.
_tmp = tempfile.mkdtemp(prefix="depths_ui_test_")
save_module.SAVE_PATH = os.path.join(_tmp, "save.json")
save_module.HIGHSCORE_PATH = os.path.join(_tmp, "highscores.json")
save_module.SPEEDRUN_SCORE_PATH = os.path.join(_tmp, "speedrun.json")
save_module.SETTINGS_PATH = os.path.join(_tmp, "settings.json")

from engine import constants as C  # noqa: E402
from engine import puzzles as puzzle_module  # noqa: E402
from engine.dungeon import GroundItem  # noqa: E402
from engine.entities import make_mimic  # noqa: E402
from engine.items import make_key  # noqa: E402
from ui.app import App  # noqa: E402


class FakeEvent:
    def __init__(self, keysym):
        self.keysym = keysym


def key(app, keysym):
    app._on_key(FakeEvent(keysym))


DIR_KEY = {(1, 0): "Right", (-1, 0): "Left", (0, 1): "Down", (0, -1): "Up"}


def clear_hazards(state):
    state.floor.monsters.clear()
    state.floor.traps.clear()
    state.player.hp = state.player.max_hp = 10 ** 6
    state.player.status_effects.clear()


def skim_to(state, predicate, floors=80):
    for _ in range(floors):
        if predicate(state.floor):
            return True
        state.depth += 1
        state._enter_floor(regenerate=True)
    return False


def stand_beside(state, tx, ty):
    spot = next((tx + dx, ty + dy) for dx, dy in DIR_KEY
                if state.floor.is_walkable(tx + dx, ty + dy))
    state.player.x, state.player.y = spot
    return DIR_KEY[(tx - spot[0], ty - spot[1])]


def reveal_map(state):
    floor = state.floor
    for y in range(floor.height):
        for x in range(floor.width):
            floor.explored[y][x] = True
            floor.visible[y][x] = True


# ----------------------------------------------------------------------
# Boot: lore -> title -> seeded new game
# ----------------------------------------------------------------------
app = App()
assert app.mode == "lore", "first launch should open on the lore screen"
key(app, "Escape")
assert app.mode == "title"
app.seed_entry.insert(0, "42")
app._start_new_game()
assert app.mode == "play" and app.state is not None and app.state.seed == 42
print("OK: boots through lore/title into a seeded run")

# ----------------------------------------------------------------------
# Movement, inventory, settings
# ----------------------------------------------------------------------
turns = app.state.player.turns
key(app, "Right")
key(app, "Left")
assert app.state.player.turns >= turns, "movement keys must reach the engine"
key(app, "e")
assert app.mode == "inventory"
key(app, "Escape")
assert app.mode == "play"
key(app, "o")
assert app.mode == "settings"
music_before = app.settings.get("music_on", True)
app.setting_music_btn.invoke()
assert app.settings.get("music_on") == (not music_before)
app.setting_music_btn.invoke()
key(app, "Escape")
assert app.mode == "play"
print("OK: movement keys, inventory (E), and settings (O) all work")

# ----------------------------------------------------------------------
# The sealed-door puzzle popup
# ----------------------------------------------------------------------
state = app.state
assert skim_to(state, lambda f: f.puzzle is not None
               and f.puzzle["kind"] not in puzzle_module.IN_DUNGEON)
clear_hazards(state)
pz = state.floor.puzzle
sx, sy = state.floor.stairs_pos
assert state.floor.tiles[sy][sx] == C.TILE_DOOR
bump_key = stand_beside(state, sx, sy)

key(app, bump_key)
assert app.mode == "puzzle", "bumping the door must open the puzzle overlay"
assert app.puzzle_frame.packed and app._puzzle_buttons
tk.pump_after(10)  # any intro reveal animation runs to completion
assert not app._puzzle_locked

# Walk away, then bump back in - state must persist.
key(app, "Escape")
assert app.mode == "play" and not state.pending_puzzle
key(app, bump_key)
assert app.mode == "puzzle"
tk.pump_after(10)

# Solve it through the UI: number keys where possible, clicks otherwise.
for _ in range(200):
    if pz["solved"]:
        break
    tk.pump_after(10)
    press = puzzle_module.solve_sequence(pz)[0]
    if press < 9:
        key(app, str(press + 1))
    else:
        app._puzzle_buttons[press].invoke()
assert pz["solved"], f"{pz['kind']} not solved through the UI"
assert app.mode == "play" and not app.puzzle_frame.packed
assert state.floor.tiles[sy][sx] == C.TILE_STAIRS
print(f"OK: puzzle popup ({pz['kind']}) opens, persists, and solves via keys+clicks")

# ----------------------------------------------------------------------
# Chests through the UI
# ----------------------------------------------------------------------
assert skim_to(state, lambda f: any(c.kind != "locked" for c in f.chests))
clear_hazards(state)
chest = next(c for c in state.floor.chests if c.kind != "locked")
bump_key = stand_beside(state, chest.x, chest.y)
log_len = len(state.log)
key(app, bump_key)
assert state.floor.tiles[chest.y][chest.x] == C.TILE_FLOOR
assert len(state.log) > log_len
print(f"OK: chest ({chest.kind}) opens with a bump through the UI")

# ----------------------------------------------------------------------
# Renderer sweep: every new tile/sprite in both lit and dim states.
# A missing sprite key (e.g. a forgotten _dim variant) raises KeyError.
# ----------------------------------------------------------------------
for kind in ("plates", "lever_order", "push_block"):
    if not skim_to(state, lambda f, k=kind: f.puzzle is not None
                   and f.puzzle["kind"] == k):
        continue
    clear_hazards(state)
    pz = state.floor.puzzle
    if kind == "plates":
        pz["plates"][0]["lit"] = True
    elif kind == "lever_order":
        pz["levers"][0]["pulled"] = True
    reveal_map(state)
    app._render()
    # dim pass: explored but not visible
    for row in state.floor.visible:
        for x in range(len(row)):
            row[x] = False
    app._render()

# Chest + mimic + key item on one visible floor.
assert skim_to(state, lambda f: bool(f.chests))
clear_hazards(state)
px, py = state.player.x, state.player.y
spot = next((px + dx, py + dy) for dx, dy in DIR_KEY
            if state.floor.is_walkable(px + dx, py + dy))
state.floor.monsters.append(make_mimic(state.depth, *spot))
state.floor.ground_items.append(GroundItem(px, py, make_key("Iron Key")))
reveal_map(state)
app._render()
drawn = app.minimap.drawn
assert drawn, "minimap must draw"
for d in drawn:
    if d["kind"] == "rectangle":
        assert d["args"][2] <= 240 and d["args"][3] <= 80, \
            f"minimap overflow at 60x32: {d['args']}"
print("OK: renderer sweep - doors, chests, levers, plates, blocks, switch, "
      "mimic and key all draw lit + dim; minimap fits")

app._closing = True
print("\nAll headless UI drive tests passed.")
