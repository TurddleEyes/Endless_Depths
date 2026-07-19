"""Headless drive test for the desktop UI (ui/app.py).

Swaps in the fake tkinter from scripts/fake_tk, then boots the REAL App
and plays it: menus, movement, the sealed-door puzzle popup (number keys
and button clicks), chests, and full-map renders that would crash on any
missing sprite. Run with:
    python3 scripts/ui_drive_test.py
"""
import os
import random
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

# Texture-pack override: a tiny pack (one marker-colored rat + a bad file)
# proves ui/sprites.py prefers pack PNGs and survives invalid ones. Must be
# in place BEFORE ui.app imports ui.sprites (the pack loads at import).
from ui import texturepack as TP  # noqa: E402

_pack_dir = os.path.join(_tmp, "textures")
os.makedirs(os.path.join(_pack_dir, "monsters"))
RAT_MARKER = "#aa00aa"
_marker_rows = [[(0xAA, 0x00, 0xAA, 255)] * 32 for _ in range(32)]
with open(os.path.join(_pack_dir, "monsters", "rat.png"), "wb") as f:
    f.write(TP.encode_png(_marker_rows))
with open(os.path.join(_pack_dir, "monsters", "orc.png"), "wb") as f:
    f.write(b"definitely not a png")
os.environ[TP.PACK_ENV] = _pack_dir

from engine import constants as C  # noqa: E402
from engine import puzzles as puzzle_module  # noqa: E402
from engine.dungeon import GroundItem  # noqa: E402
from engine.entities import generate_monster_of, make_mimic  # noqa: E402
from engine.items import generate_item, make_key  # noqa: E402
from ui.app import App  # noqa: E402


class FakeEvent:
    def __init__(self, keysym):
        self.keysym = keysym


class FakeClick:
    def __init__(self, y):
        self.y = y


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
# Texture pack: the marker-colored rat.png overrides the built-in art;
# the corrupt orc.png was skipped with a warning and orc kept code-art.
# ----------------------------------------------------------------------
from ui import sprites as sprites_module  # noqa: E402

rat_colors = set(app.sprites["rat"].pixels.values())
assert rat_colors == {RAT_MARKER}, f"rat should be all {RAT_MARKER}, got {rat_colors}"
orc_colors = set(app.sprites["orc"].pixels.values())
assert RAT_MARKER not in orc_colors and orc_colors, "orc must keep built-in art"
assert any("orc.png" in w for w in sprites_module._PACK_WARNINGS), \
    "corrupt pack file should be warned about"

# Hero slot remap on the pack path: inject a pack hero base (the default
# art, via the pack pipeline) and check armor/rarity/poison recolors.
sprites_module._PACK_HERO["base"] = TP.grid_to_px(
    sprites_module._scale2x(sprites_module.HERO_BASE),
    sprites_module.PLAYER_PALETTE)
_hero_img = sprites_module.build_hero(weapon="sword", armor="plate",
                                       poisoned=True, weapon_rarity="legendary",
                                       zoom=1)
_hero_colors = set(_hero_img.pixels.values())
assert sprites_module.ARMOR_TUNIC_COLORS["plate"] in _hero_colors, "tunic slot not remapped"
assert sprites_module.ARMOR_TUNIC_COLORS["none"] not in _hero_colors, "default tunic remains"
assert sprites_module.BLADE_RARITY_COLORS["legendary"] in _hero_colors, "blade slot not remapped"
assert sprites_module.POISONED_SKIN in _hero_colors, "poison skin not remapped"
sprites_module._PACK_HERO["base"] = None  # back to built-in hero for the rest

# Facing follows the movement keys and the hero sprite cache keys on it.
for keysym, expected in (("Left", "left"), ("Up", "up"),
                          ("Right", "right"), ("Down", "down")):
    key(app, keysym)
    assert app.hero_facing == expected, f"{keysym} -> {app.hero_facing}"
    assert app._hero_sprite() is not None
assert len({k[-1] for k in app._hero_cache}) >= 4, "one cached pose per facing"
print("OK: texture pack overrides rat, hero slots recolor, facing follows "
      "movement, corrupt file falls back with a warning")

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
# Item-list category headers: set_items always opens with a header row
# (see ItemListPanel - a fresh sentinel guarantees row 0 is never a real
# item), so clicking row 0 must redirect the selection to a real item
# rather than leaving the panel with nothing selected.
# ----------------------------------------------------------------------
rng = random.Random(1)
app.state.player.inventory = [generate_item(1, rng) for _ in range(6)]
key(app, "e")
assert app.mode == "inventory"
app._refresh_inventory()
assert app.inv_panel.entries, "expected items in the seeded inventory"
app.inv_panel._on_click(FakeClick(0))
assert app.inv_panel.selected_item() is not None, \
    "clicking a category header must redirect to the nearest real item"
key(app, "Escape")
assert app.mode == "play"
print("OK: item-list category headers redirect clicks to a real item")

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

# Boss arena: sealed door tile, boss nameplate/HP bar, arena reopening.
# clear_hazards() wipes ALL monsters, so grab the boss reference first and
# keep only it (mirroring how the analogous smoke_test.py check does it).
assert skim_to(state, lambda f: any(m.is_boss for m in f.monsters))
boss = next(m for m in state.floor.monsters if m.is_boss)
state.floor.traps.clear()
state.player.hp = state.player.max_hp = 10 ** 6
state.player.status_effects.clear()
state.floor.monsters[:] = [boss]
sx, sy = state.floor.stairs_pos
assert state.floor.tiles[sy][sx] == C.TILE_BOSS_DOOR
reveal_map(state)
app._render()
assert app.boss_name_label.packed and app.boss_bar.packed, \
    "boss nameplate must show while a boss is alive"
assert app.boss_name_label.cget("text"), "boss nameplate must show a name/phase"
# dim pass: explored but not visible
for row in state.floor.visible:
    for x in range(len(row)):
        row[x] = False
app._render()
# Kill it outright and confirm both the UI and the arena door react.
boss.hp = 0
state._kill_monster(boss)
app._render()
assert not app.boss_name_label.packed and not app.boss_bar.packed, \
    "boss nameplate must hide once the boss is dead"
assert state.floor.tiles[sy][sx] == C.TILE_STAIRS, "arena must reopen once the boss falls"
print("OK: boss arena renders (sealed door, nameplate/HP bar lit + dim, "
      "nameplate hides and door reopens on death)")

# Chest + mimic + key item on one visible floor.
assert skim_to(state, lambda f: bool(f.chests))
clear_hazards(state)
px, py = state.player.x, state.player.y
spot = next((px + dx, py + dy) for dx, dy in DIR_KEY
            if state.floor.is_walkable(px + dx, py + dy))
state.floor.monsters.append(make_mimic(state.depth, *spot))
state.floor.ground_items.append(GroundItem(px, py, make_key("Iron Key")))
# Plant a few deep breeds too, so their tk sprites get drawn at least once.
deep_spots = [(x, y) for y in range(state.floor.height)
              for x in range(state.floor.width)
              if state.floor.is_walkable(x, y) and state.floor.monster_at(x, y) is None
              and (x, y) != (px, py)][:4]
for name, (dx, dy) in zip(("Ghoul", "Void Weaver", "Grave Titan", "Unfinished One"),
                          deep_spots):
    state.floor.monsters.append(generate_monster_of(name, state.depth, dx, dy))
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
