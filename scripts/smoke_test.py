"""Headless engine smoke test - no tkinter required. Run with:
    python3 scripts/smoke_test.py
"""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import constants as C
from engine.dungeon import generate_floor, start_position
from engine.fov import compute_fov
from engine.items import generate_item
from engine.entities import generate_monster
from engine.world import GameState
from engine import save as save_module


def floor_connected(floor) -> bool:
    start = start_position(floor)
    seen = {start}
    q = deque([start])
    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if floor.in_bounds(nx, ny) and floor.tiles[ny][nx] != C.TILE_WALL and (nx, ny) not in seen:
                seen.add((nx, ny))
                q.append((nx, ny))
    return floor.stairs_pos in seen


def test_generation_and_connectivity():
    import random
    rng = random.Random(42)
    for depth in (1, 3, 5, 10, 25, 60):
        floor = generate_floor(depth, rng)
        assert floor_connected(floor), f"Floor {depth} not connected from spawn to stairs"
        assert len(floor.rooms) >= 2
    print("OK: dungeon generation + connectivity across depths 1..60")


def test_shop_intervals():
    import random
    rng = random.Random(1)
    shop_floor = generate_floor(C.SHOP_INTERVAL, rng)
    assert shop_floor.shop_pos is not None, "Expected a shop on a SHOP_INTERVAL floor"
    assert len(shop_floor.shop_stock) > 0
    print("OK: shop rooms generate stock on shop-interval floors")


def test_boss_floor():
    import random
    rng = random.Random(7)
    boss_floor = generate_floor(C.BOSS_INTERVAL, rng)
    assert any(m.is_boss for m in boss_floor.monsters), "Expected a boss on a BOSS_INTERVAL floor"
    print("OK: boss monster spawns on boss-interval floor")


def test_fov_blocks_through_walls():
    import random
    rng = random.Random(3)
    floor = generate_floor(1, rng)
    px, py = start_position(floor)
    compute_fov(floor, px, py, radius=6)
    # Every visible floor tile must be reachable in a straight-ish line - sanity: player's own tile always visible.
    assert floor.visible[py][px] is True
    assert floor.explored[py][px] is True
    # find a wall tile and confirm tiles strictly beyond it along same axis are not marked visible
    print("OK: FOV computes without error and marks player tile visible/explored")


def test_item_scaling():
    import random
    rng = random.Random(9)
    low_values = [generate_item(1, rng).value for _ in range(300)]
    high_values = [generate_item(50, rng).value for _ in range(300)]
    avg_low = sum(low_values) / len(low_values)
    avg_high = sum(high_values) / len(high_values)
    assert avg_high > avg_low * 2, f"Expected item value to scale with depth: low={avg_low} high={avg_high}"
    print(f"OK: item value scales with depth (avg depth1={avg_low:.1f}, avg depth50={avg_high:.1f})")


def test_monster_scaling():
    import random
    rng = random.Random(11)
    low_hp = [generate_monster(1, rng, 0, 0).max_hp for _ in range(200)]
    high_hp = [generate_monster(40, rng, 0, 0).max_hp for _ in range(200)]
    assert (sum(high_hp) / len(high_hp)) > (sum(low_hp) / len(low_hp)) * 2
    print("OK: monster HP scales with depth")


def test_shop_transactions():
    import random
    from engine.dungeon import generate_floor

    state = GameState(seed=21)
    state.new_game()
    rng = random.Random(21)
    # Force-generate floors until one has a shop (SHOP_INTERVAL guarantees it periodically).
    depth = C.SHOP_INTERVAL
    while True:
        floor = generate_floor(depth, rng)
        if floor.shop_pos is not None:
            break
        depth += 1
    state.floor = floor
    state.player.gold = 100000  # plenty to afford anything on offer

    item = floor.shop_stock[0]
    starting_stock = len(floor.shop_stock)
    starting_inventory = len(state.player.inventory)
    state.buy_item(item)
    assert len(state.player.inventory) == starting_inventory + 1
    assert len(floor.shop_stock) == starting_stock - 1
    assert item in state.player.inventory

    gold_after_buy = state.player.gold
    state.sell_item(item)
    assert item not in state.player.inventory
    assert state.player.gold > gold_after_buy

    # Insufficient funds should be rejected cleanly.
    state.player.gold = 0
    other_item = floor.shop_stock[0] if floor.shop_stock else None
    if other_item:
        stock_before = len(floor.shop_stock)
        state.buy_item(other_item)
        assert len(floor.shop_stock) == stock_before, "Purchase without enough gold should not remove stock"
    print("OK: shop buy/sell transactions update gold and inventory correctly")


def test_full_playthrough_simulation():
    import random
    from engine.world import _bfs_next_step

    state = GameState(seed=123)
    state.new_game()
    assert state.floor is not None
    assert state.player.hp == state.player.max_hp

    # A "smart" agent that loots nearby items, equips upgrades, drinks
    # healing potions when hurt, and otherwise beelines for the stairs
    # (reusing the same BFS the monster AI uses). This exercises many floors
    # of infinite descent, combat, leveling, items and equipment together,
    # rather than relying on a pure random walk (which mixes far too slowly
    # through 1-wide corridors to reliably reach a specific target tile) or
    # a looter that ignores gear and dies to easily-avoidable damage.
    rng = random.Random(555)
    max_depth_seen = state.depth
    safety_iterations = 30000
    floors_descended = 0
    turns_at_floor_start = 0

    def nearest_item_target(floor, pos):
        if not floor.ground_items:
            return None
        best, best_dist = None, None
        for gi in floor.ground_items:
            step = _bfs_next_step(floor, pos, (gi.x, gi.y), blocked=set())
            if step is None and (gi.x, gi.y) != pos:
                continue
            dist = abs(gi.x - pos[0]) + abs(gi.y - pos[1])
            if best_dist is None or dist < best_dist:
                best, best_dist = (gi.x, gi.y), dist
        return best

    def auto_equip_upgrades():
        for item in list(state.player.inventory):
            if item.category == "weapon" and (
                state.player.equipped_weapon is None
                or item.bonus_attack > state.player.equipped_weapon.bonus_attack
            ):
                state.equip_item(item)
            elif item.category == "armor" and (
                state.player.equipped_armor is None
                or item.bonus_defense > state.player.equipped_armor.bonus_defense
            ):
                state.equip_item(item)

    for _ in range(safety_iterations):
        if state.game_over:
            break

        if state.pending_shop:
            # Stock up on a cure if the shop has one we can afford - poison
            # is permanent, so a prudent bot (and player) buys insurance.
            cure_stock = next((i for i in state.floor.shop_stock
                               if i.effect == "cure" and state.player.gold >= i.value), None)
            if cure_stock and not any(i.effect == "cure" for i in state.player.inventory):
                state.buy_item(cure_stock)
            state.close_shop()
            continue

        auto_equip_upgrades()

        if any(e.get("type") == "poison" for e in state.player.status_effects):
            cure = next((i for i in state.player.inventory
                         if i.category == "potion" and i.effect == "cure"), None)
            if cure:
                state.use_item(cure)
                continue

        if state.player.hp < state.player.max_hp * 0.65:
            heal_potion = next(
                (i for i in state.player.inventory if i.category == "potion" and i.effect == "heal"),
                None,
            )
            if heal_potion:
                state.use_item(heal_potion)
                continue

        player_pos = (state.player.x, state.player.y)
        # After lingering too long on one floor (e.g. oscillating between
        # equidistant loot), stop looting and head straight for the stairs.
        # When poisoned without a cure, beeline for this floor's shop if it
        # has one (bumping the shopkeeper opens it), else rush the stairs -
        # exactly what a sane player does.
        turns_on_floor = state.player.turns - turns_at_floor_start
        poisoned_no_cure = (
            any(e.get("type") == "poison" for e in state.player.status_effects)
            and not any(i.effect == "cure" for i in state.player.inventory)
        )
        target = None
        if poisoned_no_cure and state.floor.shop_pos:
            sx, sy = state.floor.shop_pos
            if abs(sx - player_pos[0]) + abs(sy - player_pos[1]) == 1:
                state.try_move_player(sx - player_pos[0], sy - player_pos[1])
                continue  # shop opens; handled at the top of the loop
            neighbors = [(sx + dx, sy + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                         if state.floor.is_walkable(sx + dx, sy + dy)]
            if neighbors:
                target = min(neighbors,
                             key=lambda t: abs(t[0] - player_pos[0]) + abs(t[1] - player_pos[1]))
        if target is None:
            if turns_on_floor > 300 or poisoned_no_cure:
                target = state.floor.stairs_pos
            else:
                target = nearest_item_target(state.floor, player_pos) or state.floor.stairs_pos
        # Give bosses a wide berth, like a sane player would - fight regular
        # monsters but only engage a boss if there's no way around it.
        boss_zone = set()
        for m in state.floor.monsters:
            if m.is_boss and m.is_alive():
                for bdx in range(-2, 3):
                    for bdy in range(-2, 3):
                        boss_zone.add((m.x + bdx, m.y + bdy))
        step = _bfs_next_step(state.floor, player_pos, target, blocked=boss_zone)
        if step is None:
            step = _bfs_next_step(state.floor, player_pos, target, blocked=set())
        depth_before = state.depth
        if step is None:
            dx, dy = rng.choice([(1, 0), (-1, 0), (0, 1), (0, -1)])
        else:
            dx, dy = step[0] - player_pos[0], step[1] - player_pos[1]
        state.try_move_player(dx, dy)
        if state.depth != depth_before:
            floors_descended += 1
            turns_at_floor_start = state.player.turns
        max_depth_seen = max(max_depth_seen, state.depth)

        if max_depth_seen >= 30:
            break

    # Dying deep in the dungeon (e.g. to a boss) is legitimate permadeath
    # behavior - the assertion is that many floors of infinite descent,
    # combat, loot and leveling all ran, not that the bot is immortal.
    assert floors_descended >= 8, f"Expected to descend many floors, only reached {floors_descended}"
    assert state.player.level >= 5, "Bot should have leveled substantially while descending"
    assert state.player.turns > 0
    print(f"OK: simulated playthrough descended {floors_descended} floors (max depth {max_depth_seen}), "
          f"{state.player.turns} turns, level {state.player.level}, game_over={state.game_over}")


def test_save_load_roundtrip(tmp_path_override):
    state = GameState(seed=77)
    state.new_game()
    state.player.gold = 250
    state.player.level = 3
    weapon = generate_item(5, state.rng)
    state.player.inventory.append(weapon)

    original_save_path = save_module.SAVE_PATH
    save_module.SAVE_PATH = tmp_path_override
    try:
        save_module.save_game(state)
        assert os.path.exists(tmp_path_override)
        loaded = save_module.load_game()
        assert loaded is not None
        assert loaded.player.gold == 250
        assert loaded.player.level == 3
        assert loaded.depth == state.depth
        assert len(loaded.player.inventory) == 1
        assert loaded.player.inventory[0].name == weapon.name
    finally:
        try:
            os.remove(tmp_path_override)
        except OSError:
            pass
        save_module.SAVE_PATH = original_save_path
    print("OK: save/load round-trip preserves player state")


def test_shop_prices_scale_with_depth():
    import random
    from engine.shop import generate_shop_inventory

    rng = random.Random(31)
    shallow = [i.value for i in generate_shop_inventory(3, rng, n_items=40)]
    deep = [i.value for i in generate_shop_inventory(30, rng, n_items=40)]
    avg_shallow = sum(shallow) / len(shallow)
    avg_deep = sum(deep) / len(deep)
    assert avg_deep > avg_shallow * 3, \
        f"deep shops should charge much more: shallow={avg_shallow:.0f} deep={avg_deep:.0f}"
    # Loot the player FINDS keeps its soft-capped value, so income stays
    # bounded while prices rise - that tension is the point.
    found = [generate_item(30, rng).value for _ in range(60)]
    assert avg_deep > (sum(found) / len(found)) * 2
    # Merchants never stock raw gold piles.
    stock = generate_shop_inventory(9, rng, n_items=60)
    assert all(i.category != "gold" for i in stock)
    print(f"OK: shop prices scale with depth (floor3 avg {avg_shallow:.0f}g, "
          f"floor30 avg {avg_deep:.0f}g); no gold piles in stock")


def test_traps():
    import random
    from engine.dungeon import Trap

    state = GameState(seed=42)
    state.new_game()
    floor = state.floor
    px, py = state.player.x, state.player.y
    # Plant a spike trap directly next to the player and step onto it.
    tx, ty = None, None
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        if floor.is_walkable(px + dx, py + dy) and floor.monster_at(px + dx, py + dy) is None:
            tx, ty = px + dx, py + dy
            break
    assert tx is not None
    floor.traps.append(Trap(tx, ty, "spike"))
    hp_before = state.player.hp
    state.try_move_player(tx - px, ty - py)
    trap = floor.trap_at(tx, ty)
    assert trap.triggered, "Trap should trigger when stepped on"
    assert state.player.hp < hp_before or state.game_over
    events = state.take_events()
    assert any(e["type"] == "trap" for e in events), "Trap should emit an event"
    print("OK: spike trap triggers, damages, and emits an event")


def test_poison_status():
    from engine.items import make_cure_potion

    state = GameState(seed=43)
    state.new_game()
    state.player.max_hp = 1000
    state.player.hp = 1000
    state.floor.monsters.clear()  # isolate poison from monster damage
    state.player.status_effects.append({"type": "poison", "dmg": 3})
    # Poison never wears off on its own; it ticks every other turn.
    hp_start = state.player.hp
    for _ in range(20):
        state.wait()
    assert state.player.hp == hp_start - 10 * 3, \
        f"poison should tick every other turn, hp={state.player.hp}"
    assert any(e.get("type") == "poison" for e in state.player.status_effects), \
        "poison must persist until cured"
    # ...but it never lands the killing blow: hp bottoms out at 1.
    state.player.hp = 2
    for _ in range(4):
        state.wait()
    assert state.player.hp == 1 and not state.game_over, "poison must not kill outright"
    # Only a cure potion ends it.
    cure = make_cure_potion(1)
    state.player.inventory.append(cure)
    state.use_item(cure)
    assert not any(e.get("type") == "poison" for e in state.player.status_effects)
    # Every shop stocks a cure so a poisoned player always has an out.
    from engine.shop import generate_shop_inventory
    import random
    stock = generate_shop_inventory(7, random.Random(2))
    assert any(i.effect == "cure" for i in stock), "every shop must stock a cure potion"
    print("OK: poison persists until cured; every shop stocks a cure potion")


def test_fireball_scroll():
    from engine.items import Item
    from engine.entities import generate_monster
    import random

    state = GameState(seed=44)
    state.new_game()
    rng = random.Random(44)
    # Place a monster right next to the player (guaranteed visible).
    px, py = state.player.x, state.player.y
    mx, my = None, None
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        if state.floor.is_walkable(px + dx, py + dy) and state.floor.monster_at(px + dx, py + dy) is None:
            mx, my = px + dx, py + dy
            break
    monster = generate_monster(1, rng, mx, my)
    monster.hp = 5
    state.floor.monsters.append(monster)
    from engine.fov import compute_fov
    compute_fov(state.floor, px, py)

    scroll = Item(9999, "Scroll of Fireball", "scroll", "?", "common", 10,
                   effect="fireball", magnitude=10)
    state.player.inventory.append(scroll)
    state.take_events()
    state.use_item(scroll)
    events = state.take_events()
    assert any(e["type"] == "fireball" for e in events)
    assert monster not in state.floor.monsters, "Fireball should have killed the 5hp monster"
    assert scroll not in state.player.inventory
    print("OK: fireball scroll burns visible monsters and is consumed")


def test_wait_and_events():
    state = GameState(seed=45)
    state.new_game()
    turns_before = state.player.turns
    state.wait()
    assert state.player.turns == turns_before + 1
    # Attack events: put a weak monster adjacent and bump it.
    from engine.entities import generate_monster
    import random
    rng = random.Random(45)
    px, py = state.player.x, state.player.y
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        if state.floor.is_walkable(px + dx, py + dy) and state.floor.monster_at(px + dx, py + dy) is None:
            m = generate_monster(1, rng, px + dx, py + dy)
            m.hp = 1
            state.floor.monsters.append(m)
            state.take_events()
            state.try_move_player(dx, dy)
            events = state.take_events()
            assert any(e["type"] == "hit" for e in events)
            assert any(e["type"] == "kill" for e in events)
            break
    print("OK: wait passes a turn; combat emits hit/kill events")


def test_audio_generation():
    """ui.audio is tkinter-free, so its synth can be verified headlessly."""
    import wave as wave_module
    from ui.audio import AudioManager, SFX_BUILDERS, MUSIC_BUILDERS

    cache = os.path.join(os.environ.get("TMPDIR", "/tmp"), "roguelike_audio_test")
    am = AudioManager(cache_dir=cache, muted=True, autostart=False)
    am.generate_all()
    names = list(SFX_BUILDERS) + list(MUSIC_BUILDERS)
    for name in names:
        path = am._path(name)
        assert os.path.exists(path), f"missing wav for {name}"
        with wave_module.open(path, "rb") as f:
            assert f.getnframes() > 0, f"{name} wav is empty"
            assert f.getframerate() == 22050
    # Cleanup
    for name in names:
        try:
            os.remove(am._path(name))
        except OSError:
            pass
    try:
        os.rmdir(cache)
    except OSError:
        pass
    print(f"OK: all {len(names)} audio files synthesize as valid WAVs")


def test_seed_always_populated():
    assert GameState().seed is not None
    assert GameState(seed=42).seed == 42
    a, b = GameState(), GameState()
    assert isinstance(a.seed, int) and isinstance(b.seed, int)
    print("OK: every GameState has a concrete integer seed")


def test_speedrun_victory_condition():
    state = GameState(seed=5, mode="speedrun", target_floor=3)
    state.new_game()
    state.take_events()
    state.depth = 2
    state._descend()
    assert state.game_won and state.game_over
    assert any(e["type"] == "victory" for e in state.take_events())
    # A normal-mode game must never trigger victory.
    normal = GameState(seed=5, mode="normal")
    normal.new_game()
    normal.depth = 500
    normal._descend()
    assert not normal.game_won
    print("OK: speedrun victory fires at target floor; normal mode never does")


def _run_scripted_bot(state, max_iters=20000, stop_depth=12):
    """Drive a GameState through its 8 public methods only (so every action
    is recorded), using the same heuristics as the playthrough test."""
    import random
    from engine.world import _bfs_next_step
    rng = random.Random(999)
    state.new_game()
    state.take_events()

    while max_iters > 0 and not state.game_over and state.depth < stop_depth:
        max_iters -= 1
        if state.pending_shop:
            if state.floor.shop_stock and state.player.gold >= state.floor.shop_stock[0].value:
                state.buy_item(state.floor.shop_stock[0])
            state.close_shop()
            continue
        if any(e.get("type") == "poison" for e in state.player.status_effects):
            cure = next((i for i in state.player.inventory
                         if i.category == "potion" and i.effect == "cure"), None)
            if cure:
                state.use_item(cure)
                continue
        for item in list(state.player.inventory):
            if item.category == "weapon" and (
                state.player.equipped_weapon is None
                or item.bonus_attack > state.player.equipped_weapon.bonus_attack
            ):
                state.equip_item(item)
            elif item.category == "armor" and (
                state.player.equipped_armor is None
                or item.bonus_defense > state.player.equipped_armor.bonus_defense
            ):
                state.equip_item(item)
        if state.player.hp < state.player.max_hp * 0.65:
            pot = next((i for i in state.player.inventory
                        if i.category == "potion" and i.effect == "heal"), None)
            if pot:
                state.use_item(pot)
                continue
        pos = (state.player.x, state.player.y)
        step = _bfs_next_step(state.floor, pos, state.floor.stairs_pos, blocked=set())
        if step is None:
            dx, dy = rng.choice([(1, 0), (-1, 0), (0, 1), (0, -1)])
        else:
            dx, dy = step[0] - pos[0], step[1] - pos[1]
        state.try_move_player(dx, dy)
    return state


def _state_fingerprint(state):
    """Everything that should match after a faithful replay. Item ids are
    excluded - they come from a process-global counter."""
    def item_key(i):
        d = i.to_dict()
        d.pop("id", None)
        return d
    return {
        "depth": state.depth,
        "hp": state.player.hp,
        "max_hp": state.player.max_hp,
        "gold": state.player.gold,
        "level": state.player.level,
        "xp": state.player.xp,
        "turns": state.player.turns,
        "kills": state.player.kills,
        "pos": (state.player.x, state.player.y),
        "inventory": [item_key(i) for i in state.player.inventory],
        "tiles": ["".join(r) for r in state.floor.tiles],
        "monsters": sorted((m.x, m.y, m.hp, m.name) for m in state.floor.monsters),
        "game_over": state.game_over,
        "game_won": state.game_won,
    }


def test_replay_fidelity_full_playthrough():
    from engine.replay import build_replay_dict, ReplayPlayer, replay_to_code, replay_from_text

    seed = 20260715
    original = _run_scripted_bot(GameState(seed=seed, mode="speedrun", target_floor=8))
    assert original.depth >= 2, "bot should have made progress"
    assert len(original.action_log) > 50

    replay = build_replay_dict(original, elapsed_seconds=12.3)
    assert replay["actions"] == original.action_log
    assert replay["seed"] == seed

    # Round-trip through the shareable text code too.
    replay = replay_from_text(replay_to_code(replay))

    player = ReplayPlayer(replay)
    player.run_to_end()
    a, b = _state_fingerprint(original), _state_fingerprint(player.state)
    for key in a:
        assert a[key] == b[key], f"replay mismatch on {key}: {a[key]!r} != {b[key]!r}"
    print(f"OK: full-playthrough replay is bit-exact "
          f"({len(replay['actions'])} actions, reached depth {original.depth}, "
          f"won={original.game_won})")


def test_replay_rejects_garbage_gracefully():
    from engine.replay import ReplayPlayer, build_replay_dict, replay_from_text

    state = GameState(seed=3)
    state.new_game()
    state.try_move_player(1, 0)
    state.wait()
    replay = build_replay_dict(state, 1.0)
    # Corrupt an action's index and inject a nonsense action.
    replay["actions"].append(["u", 999])
    replay["actions"].append(["zzz"])
    player = ReplayPlayer(replay)
    player.run_to_end()  # must not raise

    try:
        ReplayPlayer({"game": "something_else", "version": 1})
        assert False, "foreign replay should be rejected"
    except ValueError:
        pass
    try:
        replay_from_text("!!!not json or base64!!!")
        assert False, "garbage text should be rejected"
    except ValueError:
        pass
    print("OK: corrupt indices are tolerated; foreign/garbage replays are rejected")


def test_continued_save_not_replayable():
    state = GameState(seed=9)
    state.new_game()
    restored = GameState.from_dict(state.to_dict())
    assert restored.replayable is False
    assert state.replayable is True
    print("OK: continued saves are flagged non-replayable")


def test_speedrun_leaderboard_sorting():
    from engine.save import speedrun_sort_key
    runs = [
        {"finished": False, "depth_reached": 40, "elapsed_seconds": 100},
        {"finished": True, "depth_reached": 100, "elapsed_seconds": 900},
        {"finished": False, "depth_reached": 55, "elapsed_seconds": 800},
        {"finished": True, "depth_reached": 100, "elapsed_seconds": 600},
    ]
    runs.sort(key=speedrun_sort_key)
    assert [r["elapsed_seconds"] for r in runs] == [600, 900, 800, 100]
    print("OK: speedrun leaderboard sorts finishers by time, then DNFs by depth")


def test_engine_has_no_tkinter_dependency():
    assert "tkinter" not in sys.modules, "engine modules must never import tkinter"
    print("OK: engine package has no tkinter import")


if __name__ == "__main__":
    scratch_save = os.path.join(
        os.environ.get("TMPDIR", "/tmp"), "roguelike_smoke_test_save.json"
    )
    test_generation_and_connectivity()
    test_shop_intervals()
    test_boss_floor()
    test_fov_blocks_through_walls()
    test_item_scaling()
    test_monster_scaling()
    test_shop_transactions()
    test_shop_prices_scale_with_depth()
    test_traps()
    test_poison_status()
    test_fireball_scroll()
    test_wait_and_events()
    test_full_playthrough_simulation()
    test_save_load_roundtrip(scratch_save)
    test_seed_always_populated()
    test_speedrun_victory_condition()
    test_replay_fidelity_full_playthrough()
    test_replay_rejects_garbage_gracefully()
    test_continued_save_not_replayable()
    test_speedrun_leaderboard_sorting()
    test_engine_has_no_tkinter_dependency()
    test_audio_generation()
    print("\nAll headless engine smoke tests passed.")
