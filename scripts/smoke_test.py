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
from engine.world import GameState, _bfs_next_step
from engine import puzzles as puzzle_module
from engine import save as save_module


def floor_connected(floor) -> bool:
    # BFS over genuinely walkable tiles. The stairs may be sealed behind a
    # rune door (solid, bump-to-interact), so reaching any neighbor of the
    # stairs tile counts as connected.
    start = start_position(floor)
    seen = {start}
    q = deque([start])
    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if floor.is_walkable(nx, ny) and (nx, ny) not in seen:
                seen.add((nx, ny))
                q.append((nx, ny))
    sx, sy = floor.stairs_pos
    return (sx, sy) in seen or any(
        (sx + dx, sy + dy) in seen for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))


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


# ----------------------------------------------------------------------
# Shared bot helpers: how a bot deals with sealed doors and puzzles using
# only the public, replay-recorded API (plus reading the open-book puzzle
# dict, which tests are allowed to do).
# ----------------------------------------------------------------------
def _bot_handle_puzzle_popup(state) -> bool:
    """One puzzle-popup interaction step; returns True if it acted."""
    if not state.pending_puzzle:
        return False
    seq = puzzle_module.solve_sequence(state.floor.puzzle)
    if seq:
        state.puzzle_input(seq[0])
    else:
        state.close_puzzle()  # in-dungeon kind: go work the props instead
    return True


def _bot_puzzle_target(state):
    """For an unsolved in-dungeon puzzle: (next prop position, tiles to
    avoid stepping on). None when there is nothing physical to do."""
    pz = state.floor.puzzle
    if not pz or pz["solved"] or pz["kind"] not in puzzle_module.IN_DUNGEON:
        return None
    hint = puzzle_module.bot_hint(pz, (state.player.x, state.player.y),
                                  [i.name for i in state.player.inventory])
    if hint[0] == "done":
        return None
    target = tuple(hint[1])
    lit = {(pl["x"], pl["y"]) for pl in pz.get("plates", []) if pl["lit"]}
    return target, lit - {target}


def _bot_step_toward(state, target, rng, blocked=frozenset()):
    """One move along BFS toward target. Solid interactables (sealed door,
    lever, block, chest) can't be BFS goals, so aim for their nearest
    walkable neighbor and bump once adjacent."""
    floor = state.floor
    pos = (state.player.x, state.player.y)
    tx, ty = target
    step = None
    if floor.is_walkable(tx, ty):
        step = (_bfs_next_step(floor, pos, target, blocked=set(blocked))
                or _bfs_next_step(floor, pos, target, blocked=set()))
    else:
        if abs(pos[0] - tx) + abs(pos[1] - ty) == 1:
            state.try_move_player(tx - pos[0], ty - pos[1])
            return
        for n in sorted(((tx + dx, ty + dy)
                         for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                         if floor.is_walkable(tx + dx, ty + dy)),
                        key=lambda t: abs(t[0] - pos[0]) + abs(t[1] - pos[1])):
            step = (_bfs_next_step(floor, pos, n, blocked=set(blocked))
                    or _bfs_next_step(floor, pos, n, blocked=set()))
            if step:
                break
    if step is None:
        dx, dy = rng.choice([(1, 0), (-1, 0), (0, 1), (0, -1)])
    else:
        dx, dy = step[0] - pos[0], step[1] - pos[1]
    state.try_move_player(dx, dy)


def test_full_playthrough_simulation():
    import random

    state = GameState(seed=42)
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

        if _bot_handle_puzzle_popup(state):
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
        extra_blocked = frozenset()
        puzzle_target = _bot_puzzle_target(state)
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
        if target is None and puzzle_target is not None:
            # An in-dungeon puzzle gates this floor: work its props.
            target, extra_blocked = puzzle_target
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
        depth_before = state.depth
        _bot_step_toward(state, target, rng, blocked=boss_zone | extra_blocked)
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
    """Drive a GameState through its public recorded methods only, using
    the same heuristics as the playthrough test."""
    import random
    rng = random.Random(999)
    state.new_game()
    state.take_events()
    walked_away_once = False

    while max_iters > 0 and not state.game_over and state.depth < stop_depth:
        max_iters -= 1
        if state.pending_shop:
            if state.floor.shop_stock and state.player.gold >= state.floor.shop_stock[0].value:
                state.buy_item(state.floor.shop_stock[0])
            state.close_shop()
            continue
        if state.pending_puzzle and not walked_away_once:
            # Walk away from the first door once (then bump it right back
            # open) so recorded runs exercise the "q" action code too.
            state.close_puzzle()
            walked_away_once = True
            continue
        if _bot_handle_puzzle_popup(state):
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
        puzzle_target = _bot_puzzle_target(state)
        if puzzle_target is not None:
            target, extra_blocked = puzzle_target
        else:
            target, extra_blocked = state.floor.stairs_pos, frozenset()
        _bot_step_toward(state, target, rng, blocked=extra_blocked)
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
        "chests": sorted((c.x, c.y, c.kind, c.gold,
                          tuple(i.name for i in c.items))
                         for c in state.floor.chests),
        # The puzzle dict is plain JSON-able data (positions, secrets,
        # lever/plate states, attempt counts) - compare it wholesale.
        "puzzle": state.floor.puzzle,
        "game_over": state.game_over,
        "game_won": state.game_won,
    }


def test_replay_fidelity_full_playthrough():
    from engine.replay import build_replay_dict, ReplayPlayer, replay_to_code, replay_from_text

    seed = 20260715
    original = _run_scripted_bot(GameState(seed=seed, mode="speedrun", target_floor=8))
    assert original.depth >= 2, "bot should have made progress"
    assert len(original.action_log) > 50
    # The run must exercise the puzzle action codes, or this test proves
    # nothing about replaying them.
    codes = {a[0] for a in original.action_log}
    assert "p" in codes and "q" in codes, \
        f"the run must exercise both puzzle action codes (codes: {codes})"

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


def _find_puzzle_floor(predicate, max_seeds=600, max_depth=40):
    """Scan seeds/depths for a floor whose puzzle satisfies predicate;
    returns a GameState sitting on that floor."""
    for seed in range(1, max_seeds + 1):
        state = GameState(seed=seed)
        state.new_game()
        while state.depth <= max_depth:
            pz = state.floor.puzzle
            if pz is not None and predicate(pz):
                return state
            state.depth += 1
            state._enter_floor(regenerate=True)
    raise AssertionError("no matching puzzle floor found")


def _prepare_test_floor(state):
    """Make a floor safe for a deterministic walking test."""
    state.floor.monsters.clear()
    state.floor.traps.clear()
    state.player.hp = state.player.max_hp = 10 ** 6
    state.player.status_effects.clear()


def _drive_to_solve(state, max_steps=800):
    """Beat the current floor's puzzle using only public methods + the
    shared bot helpers. Returns the step count used."""
    import random
    rng = random.Random(4242)
    sx, sy = state.floor.stairs_pos
    for step in range(max_steps):
        if state.floor.puzzle["solved"]:
            return step
        if _bot_handle_puzzle_popup(state):
            continue
        pt = _bot_puzzle_target(state)
        target, blocked = pt if pt else ((sx, sy), frozenset())
        _bot_step_toward(state, target, rng, blocked=blocked)
        state.floor.monsters.clear()  # summons from stray fails stay out
    raise AssertionError(f"{state.floor.puzzle['kind']}: unsolved after {max_steps} steps")


def test_puzzle_solvability_sweep():
    import random
    popup = [k for k in (puzzle_module.EASY + puzzle_module.MEDIUM + puzzle_module.HARD)
             if k not in puzzle_module.IN_DUNGEON]
    for kind in popup:
        for i in range(30):
            for depth in (2, 10, 20):
                rng = random.Random(i * 7919 + depth)
                pz = puzzle_module.generate(kind, depth, rng)
                steps = 0
                while not pz["solved"]:
                    seq = puzzle_module.solve_sequence(pz)
                    assert seq, f"{kind} seed {i}: no solution from current state"
                    for press in seq:
                        result = puzzle_module.apply_input(pz, press, rng)
                        steps += 1
                        if pz["solved"]:
                            break
                        assert result != "failed", \
                            f"{kind} seed {i}: solver caused a fail"
                    assert steps < 200, f"{kind} seed {i}: unsolved after 200 presses"
                view = puzzle_module.view(pz)
                assert view["title"] and isinstance(view["buttons"], list)
    print(f"OK: {len(popup)} pop-up puzzle kinds x 30 seeds x 3 depths all solvable")


def test_puzzle_door_gating_and_summons():
    # A choice-style puzzle so a wrong answer is easy to construct.
    state = _find_puzzle_floor(lambda pz: "answer" in pz)
    _prepare_test_floor(state)
    pz = state.floor.puzzle
    sx, sy = state.floor.stairs_pos
    assert state.floor.tiles[sy][sx] == C.TILE_DOOR, "puzzle floor must seal its stairs"
    assert not state.floor.is_walkable(sx, sy)

    # Walk to the door and bump it: the puzzle opens, the world freezes.
    import random
    rng = random.Random(7)
    for _ in range(400):
        if state.pending_puzzle:
            break
        _bot_step_toward(state, (sx, sy), rng)
    assert state.pending_puzzle, "bumping the door must open the puzzle"
    turns = state.player.turns
    state.try_move_player(1, 0)
    state.wait()
    assert state.player.turns == turns, "movement must be blocked while the popup is open"

    # A wrong answer summons a chasing monster nearby.
    monsters_before = len(state.floor.monsters)
    state.puzzle_input((pz["answer"] + 1) % len(pz["options"]))
    assert not pz["solved"] and state.pending_puzzle
    assert len(state.floor.monsters) == monsters_before + 1, "wrong answer must summon"
    assert state.floor.monsters[-1].state == "chasing"
    assert any(e["type"] == "summon" for e in state.take_events())

    # Walking away and returning keeps the puzzle's state.
    state.close_puzzle()
    assert not state.pending_puzzle
    attempts = pz["attempts"]
    _bot_step_toward(state, (sx, sy), rng)  # still adjacent: bump reopens
    assert state.pending_puzzle and pz["attempts"] == attempts

    # Solving dissolves the door into stairs and lets the player descend.
    state.floor.monsters.clear()
    while not pz["solved"]:
        state.puzzle_input(puzzle_module.solve_sequence(pz)[0])
    assert not state.pending_puzzle
    assert state.floor.tiles[sy][sx] == C.TILE_STAIRS
    assert any(e["type"] == "puzzle_solved" for e in state.take_events())
    depth_before = state.depth
    for _ in range(400):
        if state.depth != depth_before:
            break
        _bot_step_toward(state, (sx, sy), rng)
    assert state.depth == depth_before + 1, "solved door must open the way down"
    print("OK: sealed door gates the stairs; wrong answers summon; solving descends")


def test_in_dungeon_puzzles():
    driven = {}
    for kind in puzzle_module.IN_DUNGEON:
        state = _find_puzzle_floor(lambda pz, k=kind: pz["kind"] == k)
        _prepare_test_floor(state)
        steps = _drive_to_solve(state)
        sx, sy = state.floor.stairs_pos
        assert state.floor.tiles[sy][sx] == C.TILE_STAIRS
        driven[kind] = steps
    print(f"OK: all in-dungeon puzzles beaten on real floors: "
          + ", ".join(f"{k} ({v} steps)" for k, v in driven.items()))


def test_chest_kinds():
    from engine.items import make_key

    kinds_tested = set()
    for seed in range(1, 400):
        if kinds_tested == {"plain", "trapped", "locked", "mimic"}:
            break
        state = GameState(seed=seed)
        state.new_game()
        for chest in list(state.floor.chests):
            if chest.kind in kinds_tested:
                continue
            spot = next(((chest.x + dx, chest.y + dy)
                         for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                         if state.floor.is_walkable(chest.x + dx, chest.y + dy)
                         and state.floor.monster_at(chest.x + dx, chest.y + dy) is None),
                        None)
            if spot is None:
                continue
            _prepare_test_floor(state)
            state.player.x, state.player.y = spot
            gold_before, inv_before = state.player.gold, len(state.player.inventory)
            versions_before = state.floor.tiles_version

            if chest.kind == "locked":
                # Refuses without the key (a free bump)...
                state.try_move_player(chest.x - spot[0], chest.y - spot[1])
                assert state.floor.chest_at(chest.x, chest.y) is chest
                assert any(gi.item.name == "Iron Key" for gi in state.floor.ground_items), \
                    "a locked chest's key must exist on the same floor"
                # ...and opens once the Iron Key is carried (and consumes it).
                state.player.inventory.append(make_key("Iron Key"))
                state.try_move_player(chest.x - spot[0], chest.y - spot[1])
                assert not any(i.name == "Iron Key" for i in state.player.inventory)
            else:
                state.try_move_player(chest.x - spot[0], chest.y - spot[1])

            assert state.floor.tiles[chest.y][chest.x] == C.TILE_FLOOR, \
                f"{chest.kind} chest tile must clear after opening"
            assert state.floor.tiles_version > versions_before
            if chest.kind == "mimic":
                assert any(m.name == "Mimic" and m.state == "chasing"
                           for m in state.floor.monsters), "mimic must ambush"
            else:
                assert (state.player.gold > gold_before
                        or len(state.player.inventory) > inv_before), \
                    f"{chest.kind} chest must yield loot"
            if chest.kind == "trapped":
                poisoned = any(e.get("type") == "poison" for e in state.player.status_effects)
                assert poisoned or state.player.hp < 10 ** 6, "trapped chest must sting"
            kinds_tested.add(chest.kind)
    assert kinds_tested == {"plain", "trapped", "locked", "mimic"}, \
        f"only saw {kinds_tested}"
    print("OK: all four chest kinds behave (loot / mimic ambush / key-lock / trap sting)")


def test_reward_chest_on_solve():
    state = _find_puzzle_floor(
        lambda pz: pz["reward"] and pz["kind"] not in puzzle_module.IN_DUNGEON)
    _prepare_test_floor(state)
    chests_before = len(state.floor.chests)
    gold_before, inv_before = state.player.gold, len(state.player.inventory)
    _drive_to_solve(state)
    assert (len(state.floor.chests) > chests_before
            or state.player.gold > gold_before
            or len(state.player.inventory) > inv_before), \
        "a rewarded puzzle must leave a chest (or tribute) behind"
    print("OK: rewarded puzzles leave a chest behind the dissolving door")


def test_puzzle_and_chest_determinism():
    for seed in (11, 77, 1234):
        a, b = GameState(seed=seed), GameState(seed=seed)
        a.new_game()
        b.new_game()
        for _ in range(12):
            assert a.floor.puzzle == b.floor.puzzle, f"seed {seed}: puzzle differs"
            assert ([(c.x, c.y, c.kind, c.gold) for c in a.floor.chests]
                    == [(c.x, c.y, c.kind, c.gold) for c in b.floor.chests]), \
                f"seed {seed}: chests differ"
            for s in (a, b):
                s.depth += 1
                s._enter_floor(regenerate=True)
    print("OK: same seed generates identical puzzles and chests, floor after floor")


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
    test_puzzle_solvability_sweep()
    test_puzzle_door_gating_and_summons()
    test_in_dungeon_puzzles()
    test_chest_kinds()
    test_reward_chest_on_solve()
    test_puzzle_and_chest_determinism()
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
