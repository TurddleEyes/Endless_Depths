"""JSON bridge between the headless game engine and the browser front-end.

Runs inside Pyodide. JavaScript calls these functions and receives JSON
strings; it never touches engine objects directly. No tkinter anywhere in
this import chain (engine/*, ui/spritedata, ui/iteminfo, ui/audio).
"""
from __future__ import annotations

import base64
import json

from engine import constants as C
from engine.world import GameState
from engine import puzzles as puzzle_module
from engine import replay as replay_module
from ui import spritedata as S
from ui.iteminfo import RARITY_COLORS, describe_item, sell_price
from ui import audio as audio_synth
from ui import lore as lore_data

# Halve the sample rate in the browser: WASM synthesis is slower than
# native and the retro chiptune sound survives 11 kHz just fine.
audio_synth.SAMPLE_RATE = 11025

STATE: GameState | None = None
REPLAY: replay_module.ReplayPlayer | None = None
_last_floor_depth = None


# ----------------------------------------------------------------------
# Static data for the renderer
# ----------------------------------------------------------------------
def sprite_atlas_json() -> str:
    atlas = {}
    for key, (grid, palette) in S.SPRITE_DEFS.items():
        atlas[key] = {"grid": list(grid), "palette": dict(palette)}
        if key in S.DIM_TILES:
            atlas[key + "_dim"] = {
                "grid": list(grid),
                "palette": {ch: S._darken(color) for ch, color in palette.items()},
            }
    return json.dumps(atlas)


def hero_sprite_json(weapon, armor, accessory, poisoned, rarity) -> str:
    grid, palette = S.hero_grid_and_palette(weapon, armor, bool(accessory),
                                             bool(poisoned), rarity)
    return json.dumps({"grid": grid, "palette": palette})


def lore_json() -> str:
    return json.dumps({"title": lore_data.TITLE, "pages": lore_data.PAGES,
                        "taglines": lore_data.TAGLINES})


def sfx_names_json() -> str:
    return json.dumps({
        "sfx": sorted(audio_synth.SFX_BUILDERS.keys()),
        "music": sorted(audio_synth.MUSIC_BUILDERS.keys()),
    })


def synth_wav_b64(name: str) -> str:
    builder = audio_synth.SFX_BUILDERS.get(name) or audio_synth.MUSIC_BUILDERS.get(name)
    if builder is None:
        return ""
    return base64.b64encode(builder().wav_bytes()).decode("ascii")


# ----------------------------------------------------------------------
# Game lifecycle
# ----------------------------------------------------------------------
def new_game(seed=None, mode="normal") -> str:
    global STATE, REPLAY, _last_floor_depth
    seed = int(seed) if seed not in (None, "") else None
    STATE = GameState(seed=seed, mode=mode)
    STATE.new_game()
    STATE.take_events()
    _last_floor_depth = None
    REPLAY = None
    return snapshot_json()


def load_game(save_json: str) -> str:
    """Restore from a save dict JSON (stored in localStorage by JS)."""
    global STATE, _last_floor_depth
    try:
        STATE = GameState.from_dict(json.loads(save_json))
        STATE.take_events()
        _last_floor_depth = None
        return snapshot_json()
    except Exception:
        return json.dumps({"error": "bad_save"})


def save_json() -> str:
    return json.dumps(STATE.to_dict())


# ----------------------------------------------------------------------
# Replays
# ----------------------------------------------------------------------
def save_replay(elapsed_seconds) -> str:
    return json.dumps(replay_module.build_replay_dict(STATE, float(elapsed_seconds)))


def load_replay(replay_text: str) -> str:
    """Accepts raw replay JSON or a base64 code; starts playback mode."""
    global STATE, REPLAY, _last_floor_depth
    try:
        REPLAY = replay_module.ReplayPlayer(replay_module.replay_from_text(replay_text))
    except (ValueError, KeyError, TypeError):
        return json.dumps({"error": "bad_replay"})
    STATE = REPLAY.state
    _last_floor_depth = None
    return snapshot_json()


def replay_step() -> str:
    if REPLAY is not None:
        REPLAY.step()
    return snapshot_json()


def replay_skip_to_end() -> str:
    if REPLAY is not None:
        REPLAY.run_to_end()
    return snapshot_json()


def replay_progress() -> str:
    if REPLAY is None:
        return json.dumps({"cursor": 0, "total": 0, "finished": True})
    return json.dumps({"cursor": REPLAY.cursor, "total": len(REPLAY.actions),
                        "finished": REPLAY.finished})


# ----------------------------------------------------------------------
# Player actions (each returns a fresh snapshot)
# ----------------------------------------------------------------------
def move(dx: int, dy: int) -> str:
    STATE.try_move_player(int(dx), int(dy))
    return snapshot_json()


def wait_turn() -> str:
    STATE.wait()
    return snapshot_json()


def _find_item(collection, item_id: int):
    for item in collection:
        if item.id == item_id:
            return item
    return None


def use_item(item_id: int) -> str:
    item = _find_item(STATE.player.inventory, int(item_id))
    if item is not None:
        STATE.use_item(item)
    return snapshot_json()


def equip_item(item_id: int) -> str:
    item = _find_item(STATE.player.inventory, int(item_id))
    if item is not None:
        STATE.equip_item(item)
    return snapshot_json()


def drop_item(item_id: int) -> str:
    item = _find_item(STATE.player.inventory, int(item_id))
    if item is not None:
        STATE.drop_item(item)
    return snapshot_json()


def buy_item(item_id: int) -> str:
    item = _find_item(STATE.floor.shop_stock, int(item_id))
    if item is not None:
        STATE.buy_item(item)
    return snapshot_json()


def sell_item(item_id: int) -> str:
    item = _find_item(STATE.player.inventory, int(item_id))
    if item is not None:
        STATE.sell_item(item)
    return snapshot_json()


def close_shop() -> str:
    STATE.close_shop()
    return snapshot_json()


def puzzle_input(index: int) -> str:
    STATE.puzzle_input(int(index))
    return snapshot_json()


def close_puzzle() -> str:
    STATE.close_puzzle()
    return snapshot_json()


# ----------------------------------------------------------------------
# Snapshot
# ----------------------------------------------------------------------
def _hero_variant(p) -> dict:
    weapon, rarity = "none", "common"
    if p.equipped_weapon:
        name = p.equipped_weapon.name.lower()
        rarity = p.equipped_weapon.rarity
        if "dagger" in name:
            weapon = "dagger"
        elif "axe" in name:
            weapon = "axe"
        elif "hammer" in name:
            weapon = "hammer"
        elif "spear" in name:
            weapon = "spear"
        else:
            weapon = "sword"
    armor = "none"
    if p.equipped_armor:
        name = p.equipped_armor.name.lower()
        if "leather" in name or "vest" in name:
            armor = "leather"
        elif "plate" in name:
            armor = "plate"
        else:
            armor = "chain"
    return {
        "weapon": weapon, "armor": armor,
        "accessory": p.equipped_accessory is not None,
        "poisoned": any(e.get("type") == "poison" for e in p.status_effects),
        "rarity": rarity,
    }


def _puzzle_props(floor) -> list:
    """Mutable render state for in-dungeon puzzle props. Lever/plate states
    persist after the solve (the props stay on the map); the push-block
    switch disappears once the seal breaks."""
    pz = floor.puzzle
    if pz is None:
        return []
    props = []
    if pz["kind"] == "lever_order":
        for lv in pz["levers"]:
            props.append({"x": lv["x"], "y": lv["y"], "kind": "lever",
                          "on": lv["pulled"]})
    elif pz["kind"] == "plates":
        for pl in pz["plates"]:
            props.append({"x": pl["x"], "y": pl["y"], "kind": "plate",
                          "on": pl["lit"]})
    elif pz["kind"] == "push_block" and pz.get("switch") and not pz["solved"]:
        props.append({"x": pz["switch"][0], "y": pz["switch"][1],
                      "kind": "switch", "on": False})
    return props


def _decor_key(depth: int, x: int, y: int):
    h = (x * 2654435761 ^ y * 97531 ^ depth * 8191) & 0xFFFFFFFF
    if h % 13 == 0:
        return S.DECOR_SPRITES[(h >> 8) % len(S.DECOR_SPRITES)]
    return None


def _item_entry(item, p, price=None):
    entry = {
        "id": item.id,
        "label": item.display_name(),
        "category": item.category,
        "rarity": item.rarity,
        "color": RARITY_COLORS.get(item.rarity, "#e6e6e6"),
        "sprite": S.ITEM_KEYS.get(item.category, "potion"),
        "details": describe_item(item, p),
        "sell_price": sell_price(item),
        "equipped": item in (p.equipped_weapon, p.equipped_armor, p.equipped_accessory),
    }
    if price is not None:
        entry["price"] = price
        entry["affordable"] = p.gold >= price
    return entry


def floor_data_json() -> str:
    """Static-per-floor data: tile rows, stairs, shop, decor positions."""
    floor = STATE.floor
    decor = []
    for y in range(floor.height):
        for x in range(floor.width):
            if floor.tiles[y][x] == C.TILE_FLOOR:
                key = _decor_key(floor.depth, x, y)
                if key:
                    decor.append([x, y, key])
    # Per-tile texture variant digits (floor and wall variants share the
    # digit slot; JS picks the right sprite family from the tile char).
    variants = []
    for y in range(floor.height):
        row = []
        for x in range(floor.width):
            tile = floor.tiles[y][x]
            if tile == C.TILE_WALL:
                row.append(str(S.wall_variant(floor.depth, x, y)))
            elif tile == C.TILE_FLOOR or tile == C.TILE_SHOPKEEPER:
                row.append(str(S.floor_variant(floor.depth, x, y)))
            else:
                row.append("0")
        variants.append("".join(row))

    return json.dumps({
        "depth": floor.depth,
        "width": floor.width,
        "height": floor.height,
        "tiles": ["".join(row) for row in floor.tiles],
        "variants": variants,
        "tiles_version": floor.tiles_version,
        "stairs": list(floor.stairs_pos),
        "shop": list(floor.shop_pos) if floor.shop_pos else None,
        "decor": decor,
    })


def snapshot_json() -> str:
    global _last_floor_depth
    p = STATE.player
    floor = STATE.floor
    floor_changed = _last_floor_depth != floor.depth
    _last_floor_depth = floor.depth

    poison = next((e for e in p.status_effects if e.get("type") == "poison"), None)
    cause = STATE.log[-2] if STATE.game_over and len(STATE.log) >= 2 else None

    snap = {
        "depth": STATE.depth,
        "floor_changed": floor_changed,
        "tiles_version": floor.tiles_version,
        "game_over": STATE.game_over,
        "game_won": STATE.game_won,
        "seed": STATE.seed,
        "run_mode": STATE.mode,
        "target_floor": STATE.target_floor,
        "replayable": STATE.replayable,
        "cause_of_death": cause,
        "shop_open": STATE.pending_shop,
        "puzzle_open": STATE.pending_puzzle,
        "puzzle": (puzzle_module.view(floor.puzzle)
                   if STATE.pending_puzzle and floor.puzzle else None),
        "puzzle_props": _puzzle_props(floor),
        "boss_alive": any(m.is_boss and m.is_alive() for m in floor.monsters),
        "music_track": audio_synth.track_for_depth(
            STATE.depth, any(m.is_boss and m.is_alive() for m in floor.monsters)),
        "player": {
            "x": p.x, "y": p.y, "hp": p.hp, "max_hp": p.max_hp,
            "level": p.level, "xp": p.xp, "xp_to_next": p.xp_to_next,
            "gold": p.gold, "attack": p.attack_power, "defense": p.defense_power,
            "kills": p.kills, "turns": p.turns,
            "poisoned": poison is not None,
            "weapon": p.equipped_weapon.name if p.equipped_weapon else None,
            "armor": p.equipped_armor.name if p.equipped_armor else None,
            "accessory": p.equipped_accessory.name if p.equipped_accessory else None,
            "hero": _hero_variant(p),
        },
        "visible": ["".join("1" if v else "0" for v in row) for row in floor.visible],
        "explored": ["".join("1" if v else "0" for v in row) for row in floor.explored],
        "monsters": [
            {"x": m.x, "y": m.y, "hp": m.hp, "max_hp": m.max_hp, "boss": m.is_boss,
             "sprite": S.MONSTER_KEYS.get(
                 m.name[:-5] if m.name.endswith(" Boss") else m.name, "goblin")}
            for m in floor.monsters if m.is_alive()
        ],
        "items": [
            {"x": gi.x, "y": gi.y,
             "sprite": S.ITEM_KEYS.get(gi.item.category, "potion")}
            for gi in floor.ground_items
        ],
        "traps": [
            {"x": t.x, "y": t.y, "sprite": S.TRAP_KEYS[t.kind]}
            for t in floor.traps if t.triggered
        ],
        "log": STATE.log[-12:],
        "events": STATE.take_events(),
        "inventory": [_item_entry(i, p) for i in p.inventory],
        "shop_stock": [_item_entry(i, p, price=i.value) for i in floor.shop_stock],
    }
    return json.dumps(snap)
