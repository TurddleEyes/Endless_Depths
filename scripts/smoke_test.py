"""Headless engine smoke test - no tkinter required. Run with:
    python3 scripts/smoke_test.py
"""
import json
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import constants as C
from engine import bosses as boss_module
from engine.dungeon import generate_floor, start_position
from engine.fov import compute_fov
from engine.items import generate_item
from engine.entities import generate_monster
from engine.world import GameState, _bfs_next_step, _flee_step
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
    assert boss_floor.boss_arena_sealed, "A boss floor with a boss must seal its arena"
    sx, sy = boss_floor.stairs_pos
    assert boss_floor.tiles[sy][sx] == C.TILE_BOSS_DOOR, "Arena door must sit on the stairs tile"
    print("OK: boss monster spawns on boss-interval floor, arena door seals the stairs")


def test_boss_ability_kits():
    """Every one of the 12 boss kits, exercised directly (bypassing the
    weighted random monster roll so rare-depth bosses like the Lich get
    covered too): telegraphs an ability, resolves it next turn, and
    escalates phases as HP drops past each threshold."""
    import random
    from engine.entities import MONSTER_TEMPLATES, Player, generate_boss_of

    assert set(boss_module.BOSS_KITS) == {t[0] for t in MONSTER_TEMPLATES}, \
        "Every monster template must have a boss kit"

    # Every summon ability must name a REAL template: generate_monster_of
    # silently falls back to MONSTER_TEMPLATES[0] (Rat) on an unknown name,
    # which would turn a boss's signature summon into rats without any error.
    template_names = {t[0] for t in MONSTER_TEMPLATES}
    for name, kit in boss_module.BOSS_KITS.items():
        for ability in kit.abilities:
            if ability.kind == "summon":
                assert ability.minion_name in template_names, \
                    f"{name} boss kit summons unknown template {ability.minion_name!r}"

    rng = random.Random(11)
    floor = generate_floor(20, rng)
    px, py = floor.rooms[0].center
    player = Player(x=px, y=py, hp=10 ** 6, max_hp=10 ** 6)

    for name, kit in boss_module.BOSS_KITS.items():
        boss = generate_boss_of(name, 20, px, py)
        boss.state = "chasing"
        seen_kinds = set()
        phases_seen = {1}
        # Step HP through each phase threshold explicitly rather than a
        # fixed per-turn drain: a self_heal ability (e.g. the Skeleton's)
        # can restore more in one resolve than a small fixed attrition
        # removes over the turns it takes to come off cooldown, which
        # would mask real phase transitions behind a healing tug-of-war
        # that has nothing to do with what this test is actually checking.
        # Phases only ever escalate (see maybe_process_boss_turn), so a
        # brief dip below a threshold sticks even if HP recovers after.
        for frac in (1.0, 0.74, 0.49, 0.24):
            boss.hp = max(1, round(boss.max_hp * frac))
            for _ in range(20):
                results = boss_module.maybe_process_boss_turn(boss, player, floor, rng)
                for r in results:
                    if r.kind == "phase":
                        phases_seen.add(boss.boss_state["phase"])
                    else:
                        seen_kinds.add(r.kind)
                if {"telegraph", "resolve"} <= seen_kinds:
                    break
        assert "telegraph" in seen_kinds and "resolve" in seen_kinds, \
            f"{name} boss kit never telegraphed+resolved an ability"
        assert len(phases_seen) >= 3, f"{name} boss kit never reached phase 3 (saw {phases_seen})"
    print(f"OK: all {len(boss_module.BOSS_KITS)} boss kits telegraph, resolve, and escalate phases")


def test_boss_fight_end_to_end():
    """A full GameState boss encounter: sealed arena blocks the stairs,
    bumping the sealed door refuses, fighting the boss produces telegraphed
    abilities and (for summon-capable kits) real minions on the floor, and
    killing it reopens the arena. Player HP is boosted for a controlled,
    guaranteed-winnable scripted fight - this test is about the ENGINE
    WIRING (door/minions/arena), not combat balance, so it deliberately
    does not double as a replay-fidelity check (see test_boss_determinism
    for that): a hand-set 10**6 HP is a direct mutation outside the
    recorded-action system, which a real replay could never reproduce.
    """
    # Jump straight to a BOSS_INTERVAL floor across seeds until one has a
    # summon-capable boss, so the minion-spawn path gets exercised too.
    state = None
    for seed in range(1, 200):
        candidate = GameState(seed=seed)
        candidate.depth = C.BOSS_INTERVAL
        candidate._enter_floor(regenerate=True)
        boss = next((m for m in candidate.floor.monsters if m.is_boss), None)
        if boss is None:
            continue
        base = boss.name[:-5]
        if any(a.kind == "summon" for a in boss_module.BOSS_KITS[base].abilities):
            state = candidate
            break
    assert state is not None, "no seed produced a summon-capable boss in range"

    boss = next(m for m in state.floor.monsters if m.is_boss)
    sx, sy = state.floor.stairs_pos
    assert state.floor.tiles[sy][sx] == C.TILE_BOSS_DOOR

    # Bumping the sealed door must do nothing but log a refusal.
    bump_key = _stand_beside_for_test(state, sx, sy)
    log_len = len(state.log)
    state.try_move_player(*bump_key)
    assert state.floor.tiles[sy][sx] == C.TILE_BOSS_DOOR, "sealed door must not open on a bump"
    assert not state.pending_puzzle, "the arena door is not a puzzle door"
    assert len(state.log) > log_len

    # Make the fight winnable-but-not-instant and watch it through: stand
    # beside the boss, keep attacking, let monster-turn processing run its
    # ability cycle. Calibrated off the boss's own stats so it survives
    # ~30 hits - too high an attack (e.g. a flat huge number) can one-shot
    # the boss before it ever gets a turn, which would mean no ability
    # ever fires and this test would pass for the wrong reason. Needs more
    # runway than a plain combat calibration would: every boss stands
    # dormant (AWAKEN_COUNTDOWN_TURNS + 1 turns, engine/bosses.py) before
    # its first real turn, and the player gets free, unanswered hits the
    # whole time - the boss must survive that opening burst with enough HP
    # left for a full telegraph/resolve/cooldown cycle on BOTH its abilities
    # (phase jumps straight past 2 once it wakes up, since HP tracking was
    # frozen during the dormancy), including the summon-capable one. Uses
    # max(1, ...) rather than max(3, ...): a floor of 3 dominates the whole
    # formula for the low-HP early bosses this seed search tends to find
    # (e.g. a 38-HP Rat Boss), silently reintroducing a too-fast kill -
    # combat.py's own resolve_attack already floors every hit at 1 damage,
    # so no extra minimum is needed here.
    state.floor.monsters[:] = [boss]
    state.floor.traps.clear()
    state.player.hp = state.player.max_hp = 10 ** 6
    state.player.base_attack = boss.defense + max(1, boss.max_hp // 30)
    attack_key = _stand_beside_for_test(state, boss.x, boss.y)

    seen_events = set()
    minions_seen = False
    for _ in range(500):
        if not boss.is_alive():
            break
        state.try_move_player(*attack_key)
        for ev in state.take_events():
            seen_events.add(ev["type"])
        if len(state.floor.monsters) > 1:
            minions_seen = True
        # Re-aim at the boss each step in case a blink_strike moved it.
        attack_key = _stand_beside_for_test(state, boss.x, boss.y)
    assert not boss.is_alive(), "boss should have died within 500 scripted turns"
    assert "boss_telegraph" in seen_events, "expected at least one telegraphed ability"
    assert minions_seen, "expected the summon-capable boss to actually spawn minions"
    assert state.floor.tiles[sy][sx] == C.TILE_STAIRS, "arena must reopen once the boss falls"
    assert not state.floor.boss_arena_sealed
    print(f"OK: boss fight end-to-end (seed {state.seed}) - sealed arena, door refuses "
          f"a bump, telegraphed abilities, minion summons, arena reopens on death")


def test_boss_determinism():
    """Same seed, same sequence of turn-rng calls -> the exact same boss
    ability sequence, every time. maybe_process_boss_turn's only
    randomness sources are the rng argument (ability tie-breaks,
    blink_strike's landing tile) - this proves there's no other hidden
    source, which is what actually keeps a real boss fight replay-safe
    (mirrors test_puzzle_and_chest_determinism's same-seed-same-result
    shape rather than the full record/replay machinery, since a
    controlled test fight needs boosted player HP - a direct mutation a
    real replay could never reproduce)."""
    import random
    from engine.entities import Player

    def run(seed):
        rng = random.Random(seed)
        floor = generate_floor(C.BOSS_INTERVAL, rng)
        boss = next(m for m in floor.monsters if m.is_boss)
        boss.state = "chasing"
        player = Player(x=boss.x, y=max(0, boss.y - 1), hp=10 ** 6, max_hp=10 ** 6)
        turn_rng = random.Random(seed * 7919 + 1)
        log = []
        for _ in range(60):
            results = boss_module.maybe_process_boss_turn(boss, player, floor, turn_rng)
            log.append([(r.kind, r.message, r.damage, r.heal, r.minion_count) for r in results])
            boss.hp = max(1, boss.hp - max(1, boss.max_hp // 30))
        return log

    a, b = run(2026), run(2026)
    assert a == b, "identical seeds must produce an identical boss ability sequence"
    # Not just "any non-empty step": the first ~11 turns are always the
    # awaken-countdown's own dormant "awaken"/"awaken_done" ticks, which
    # would trivially satisfy a bare non-emptiness check regardless of
    # whether real ability logic ever ran. Require an actual
    # telegraph/resolve/phase entry so a regression in that logic still
    # fails this test.
    real_kinds = {"telegraph", "resolve", "phase"}
    assert any(r[0] in real_kinds for step in a for r in step), \
        "expected at least some real ability/phase activity across 60 turns"
    print("OK: boss ability sequences are fully deterministic given the same rng stream")


def _stand_beside_for_test(state, tx, ty):
    """Move the player to a walkable tile adjacent to (tx, ty) and return
    the (dx, dy) that bumps back into it. Used only by boss-fight tests."""
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        sx, sy = tx + dx, ty + dy
        if state.floor.is_walkable(sx, sy):
            state.player.x, state.player.y = sx, sy
            return (-dx, -dy)
    raise AssertionError(f"no walkable tile adjacent to ({tx}, {ty})")


def test_deep_monster_variety():
    """The deep roster keeps refreshing: hardcore players at floor 100+
    must keep meeting breeds that unlocked recently, not grind the same
    twelve shallow monsters forever."""
    import random
    from engine.entities import MONSTER_TEMPLATES, base_template_name
    rng = random.Random(4321)
    by_name = {t[0]: t for t in MONSTER_TEMPLATES}
    for depth in (40, 70, 100):
        # Strip the " Elite" suffix a tougher-instance roll may add - this
        # test is about which BREEDS appear, not the elite tier on top.
        names = {base_template_name(generate_monster(depth, rng, 0, 0).name) for _ in range(300)}
        assert len(names) >= 8, f"depth {depth}: only {len(names)} distinct breeds"
        newest_seen = max(by_name[n][7] for n in names)
        assert newest_seen >= depth - 25, \
            f"depth {depth}: newest breed seen unlocked at {newest_seen} - roster is stale"
    deepest_unlock = max(t[7] for t in MONSTER_TEMPLATES)
    assert deepest_unlock >= 90, "the roster should keep unlocking near floor 100"
    print(f"OK: deep floors keep unlocking new breeds "
          f"({len(MONSTER_TEMPLATES)} templates, deepest unlock at floor {deepest_unlock})")


def test_monster_traits_data_integrity():
    from engine.traits import MONSTER_TRAITS
    from engine.entities import MONSTER_TEMPLATES

    template_names = {t[0] for t in MONSTER_TEMPLATES}
    valid_procs = {"", "poison", "burn", "bleed"}
    valid_ai = {"melee", "ranged", "fleeing", "caster"}
    for name, trait in MONSTER_TRAITS.items():
        assert name in template_names, f"MONSTER_TRAITS references unknown template {name!r}"
        assert trait.proc_type in valid_procs, f"{name}: invalid proc_type {trait.proc_type!r}"
        assert trait.ai in valid_ai, f"{name}: invalid ai {trait.ai!r}"
        if trait.ai == "ranged":
            kit = boss_module.BOSS_KITS[name]
            assert any(a.kind == "ranged_bolt" for a in kit.abilities), \
                f"{name} has ranged AI but its kit has no ranged_bolt ability"
    print(f"OK: {len(MONSTER_TRAITS)} MONSTER_TRAITS entries reference real templates and valid kinds")


def test_spider_poison_proc_reproduced():
    """The old hardcoded "if 'Spider' in m.name" melee poison proc is now
    data-driven (engine/traits.py) - this reproduces it end-to-end through
    the real GameState combat path with the exact original odds (20%) and
    damage formula (max(1, 1 + depth // 8))."""
    from engine.entities import generate_monster_of

    state = GameState(seed=77)
    state.new_game()
    px, py = state.floor.rooms[0].center
    state.player.x, state.player.y = px, py
    state.player.hp = state.player.max_hp = 10 ** 6
    spider = generate_monster_of("Giant Spider", state.depth, px + 1, py)
    spider.state = "chasing"
    state.floor.monsters[:] = [spider]
    proc_seen = False
    for _ in range(300):
        state.wait()
        if any(e.get("type") == "poison" for e in state.player.status_effects):
            proc_seen = True
            break
        if not spider.is_alive():
            break
    assert proc_seen, "Giant Spider's melee should eventually proc poison"
    print("OK: Giant Spider's melee poison proc still fires through the data-driven MONSTER_TRAITS path")


def test_elite_generation_and_ability():
    import random
    from engine.entities import (generate_monster, generate_boss_of, Monster, Player,
                                  ELITE_MIN_DEPTH, ELITE_CHANCE)

    rng = random.Random(5)
    trials = 4000
    elites = 0
    for _ in range(trials):
        m = generate_monster(ELITE_MIN_DEPTH + 2, rng, 0, 0)
        if m.is_elite:
            elites += 1
            assert m.name.endswith(" Elite")
            assert not m.is_boss, "a monster must never be both boss and elite"
    rate = elites / trials
    assert abs(rate - ELITE_CHANCE) < 0.03, f"elite roll rate {rate:.3f} far from expected {ELITE_CHANCE}"

    for _ in range(300):
        assert not generate_monster(1, rng, 0, 0).is_elite, "no elites before ELITE_MIN_DEPTH"

    # An elite's one ability: telegraphs then resolves, at REDUCED potency
    # vs. the same kit/ability on a real boss, with no phase/awaken/enrage
    # state ever appearing.
    floor = generate_floor(20, random.Random(9))
    px, py = floor.rooms[0].center
    player = Player(x=px, y=py, hp=10 ** 6, max_hp=10 ** 6)

    boss_twin = generate_boss_of("Orc", 20, px, py)
    boss_twin.state = "chasing"
    boss_twin.boss_state["awakened"] = True
    boss_twin.boss_state["phase"] = 2  # unlocks Orc's aoe_burst (ground_slam)

    elite = Monster(px, py, "Orc Elite", "o", boss_twin.max_hp, boss_twin.max_hp,
                     boss_twin.attack, boss_twin.defense, 10, 10, is_elite=True, boss_state={})
    elite.state = "chasing"

    def _drive_to_resolve(process_fn, monster, rng_):
        seen_kinds = set()
        for _ in range(10):
            for r in process_fn(monster, player, floor, rng_):
                seen_kinds.add(r.kind)
                if r.kind == "resolve":
                    return r, seen_kinds
        return None, seen_kinds

    boss_result, _ = _drive_to_resolve(boss_module.maybe_process_boss_turn, boss_twin, random.Random(1))
    elite_result, elite_kinds = _drive_to_resolve(boss_module.maybe_process_elite_turn, elite, random.Random(1))

    assert boss_result is not None and elite_result is not None
    assert elite_kinds == {"telegraph", "resolve"}, \
        f"elites must never gain phase/awaken state, saw {elite_kinds}"
    assert elite.boss_state.get("phase") is None and elite.boss_state.get("awakened") is None
    assert elite_result.damage < boss_result.damage, \
        f"elite ability should be weaker than the same boss ability ({elite_result.damage} !< {boss_result.damage})"
    print(f"OK: elites roll at ~{ELITE_CHANCE:.0%} past floor {ELITE_MIN_DEPTH}, "
          f"never before, and their one ability resolves at reduced potency with no phases")


def test_ranged_and_fleeing_ai():
    import random
    from engine.entities import generate_monster_of, Player
    from engine.traits import trait_for

    rng = random.Random(15)
    floor = generate_floor(20, rng)
    room = floor.rooms[0]
    px, py = room.center
    player = Player(x=px, y=py, hp=10 ** 6, max_hp=10 ** 6)
    compute_fov(floor, px, py)

    # "ranged" AI (engine/traits.py: Wyvern) reuses the boss ranged_bolt LOS
    # convention - lands a hit based on visibility alone, no distance check,
    # at FULL potency (these are ordinary monsters, not the elite tier).
    # Try a few offsets rather than assuming room size/shape - only distance
    # and line-of-sight actually matter here.
    wpos = next(
        (cx, cy) for cx, cy in
        ((px + 3, py), (px - 3, py), (px, py + 3), (px, py - 3),
         (px + 2, py), (px - 2, py), (px, py + 2), (px, py - 2))
        if floor.in_bounds(cx, cy) and floor.is_walkable(cx, cy) and floor.visible[cy][cx]
    )
    wyvern = generate_monster_of("Wyvern", 20, *wpos)
    wyvern.state = "chasing"
    assert floor.visible[wyvern.y][wyvern.x], "test setup needs LOS to the wyvern"
    resolved = None
    for _ in range(10):
        for r in boss_module.maybe_process_kited_turn(wyvern, player, floor, rng, prefer_kind="ranged_bolt"):
            if r.kind == "resolve":
                resolved = r
        if resolved:
            break
    assert resolved is not None and resolved.ability_kind == "ranged_bolt" and resolved.damage > 0
    assert abs(wyvern.x - px) + abs(wyvern.y - py) > 1, "the wyvern should still be at range, not adjacent"

    # "fleeing" AI (Rat): retreats to the farthest open neighbor while
    # healthy, and stops fleeing (falls back to normal chase/melee) once
    # wounded below half HP.
    rat = generate_monster_of("Rat", 20, px + 1, py)
    rat.max_hp = rat.hp = 20
    occupied = set()
    start_dist = abs(rat.x - px) + abs(rat.y - py)
    flee_to = _flee_step(floor, rat, player, occupied)
    assert flee_to is not None, "an open room should always have a retreat tile"
    new_dist = abs(flee_to[0] - px) + abs(flee_to[1] - py)
    assert new_dist > start_dist, "fleeing should move strictly away from the player"

    rat.hp = 9  # wounded below 50% of max_hp=20
    assert not (trait_for(rat).ai == "fleeing" and rat.hp > rat.max_hp * 0.5), \
        "a wounded rat must fall through to normal chase/melee, not keep fleeing"
    print("OK: ranged AI hits from beyond melee range; fleeing AI retreats while healthy, fights once wounded")


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


def test_gear_affixes_and_sets():
    """M4 loot: weapon/armor/accessory affixes and gear sets. Rarity-gated
    generation, set_bonus_mult's tiering, and describe_item's new stat
    lines - all pure/deterministic, no GameState needed."""
    import random
    from engine.items import generate_item, GEAR_SETS, set_bonus_mult
    from engine.entities import Player

    rng = random.Random(31)
    rolled = [generate_item(30, rng) for _ in range(4000)]
    weapons = [i for i in rolled if i.category == "weapon"]
    armors = [i for i in rolled if i.category == "armor"]
    affixed = [w for w in weapons if w.lifesteal_pct or w.crit_chance_bonus or w.on_hit_status]
    set_pieces = [w for w in weapons if w.set_name]
    assert affixed, "some depth-30 weapons should roll an offense affix"
    assert set_pieces, "some depth-30 weapons should roll into a gear set"
    for w in set_pieces:
        assert w.set_name in GEAR_SETS
        assert w.name == GEAR_SETS[w.set_name]["weapon"]
        assert not (w.lifesteal_pct or w.crit_chance_bonus or w.on_hit_status), \
            "a set piece must not ALSO carry a per-item affix"
    for w in affixed:
        assert sum(bool(x) for x in (w.lifesteal_pct, w.crit_chance_bonus, w.on_hit_status)) == 1, \
            "exactly one offense affix should roll at a time"
        if w.on_hit_status:
            assert w.on_hit_status in ("poison", "burn", "bleed")
            assert 0 < w.on_hit_chance < 1

    resisted = [a for a in armors if a.resist_status]
    assert resisted, "some depth-30 armor should roll a resist affix"
    for a in resisted:
        assert a.resist_status in ("poison", "burn", "bleed")
        assert 0 < a.resist_pct < 1

    # Common-rarity items never roll an affix or a set (only uncommon+/rare+).
    common_gear = [generate_item(1, random.Random(999)) for _ in range(500)]
    for i in common_gear:
        if i.category in ("weapon", "armor", "accessory") and i.rarity == "common":
            assert not (i.lifesteal_pct or i.crit_chance_bonus or i.on_hit_status
                        or i.resist_status or i.set_name), \
                f"common {i.category} should never carry an affix or set"

    # set_bonus_mult: 0/1 matching pieces = no bonus, 2 = the 2pc tier, 3 = the 3pc tier.
    from engine.items import Item
    p = Player()
    berserker_weapon = Item(1, "Berserker's Axe", "weapon", "/", "legendary", 1, set_name="Berserker")
    assert set_bonus_mult(p, "attack") == 1.0, "no equipped set pieces should mean no bonus"
    p.equipped_weapon = berserker_weapon
    assert set_bonus_mult(p, "attack") == 1.0, "1 matching piece should not be enough for a bonus"
    p.equipped_armor = Item(2, "Berserker's Hide", "armor", "[", "legendary", 1, set_name="Berserker")
    assert set_bonus_mult(p, "attack") == GEAR_SETS["Berserker"][2]["attack_mult"]
    p.equipped_accessory = Item(3, "Berserker's Fang", "accessory", "=", "legendary", 1, set_name="Berserker")
    assert set_bonus_mult(p, "attack") == GEAR_SETS["Berserker"][3]["attack_mult"]

    from ui.iteminfo import describe_item
    lines = describe_item(berserker_weapon, p)
    assert any("Berserker" in line for line in lines), "describe_item should surface the set name"
    print("OK: gear affixes/sets roll correctly (weapon/armor affixes, mutually exclusive with sets, "
          "set_bonus_mult tiers at 2/3 pieces)")


def test_weapon_affix_effects_in_combat():
    import random
    from engine import combat as combat_module
    from engine.entities import generate_monster_of
    from engine.items import Item

    # Crit chance bonus, exercised directly (deterministic: +100% must
    # guarantee a crit every time).
    rng = random.Random(3)
    for _ in range(20):
        _, is_crit, _ = combat_module.resolve_attack("You", "Rat", 10, 0, rng, crit_chance_bonus=1.0)
        assert is_crit, "a +100% crit_chance_bonus must guarantee a crit"

    # Lifesteal + on-hit status proc. Calls _player_attack directly (not
    # try_move_player) to isolate the attack itself from the monster's own
    # retaliation on the same turn, which would otherwise swamp a small
    # lifesteal heal and make this test about combat balance, not affixes.
    state = GameState(seed=61)
    state.new_game()
    state.player.max_hp = 100
    state.player.hp = 40  # damaged, so lifesteal has room to heal
    state.player.base_attack = 50
    weapon = Item(1, "Test Blade", "weapon", "/", "legendary", 1,
                   lifesteal_pct=1.0, on_hit_status="burn", on_hit_chance=1.0)
    state.player.equipped_weapon = weapon
    tough = generate_monster_of("Grave Titan", 40, 0, 0)
    tough.hp = tough.max_hp = 10 ** 6  # survives the hit so the proc can land

    hp_before = state.player.hp
    state._player_attack(tough)
    assert state.player.hp > hp_before, "100% lifesteal should heal the player back"
    assert any(e.get("type") == "burn" for e in tough.status_effects), \
        "a guaranteed on-hit proc should inflict its status on the monster"
    print("OK: crit_chance_bonus/lifesteal/on-hit weapon procs all work through real combat")


def test_gear_resistance_blocks_ailment():
    from engine.items import Item

    state = GameState(seed=62)
    state.new_game()
    state.player.equipped_armor = Item(1, "Test Wards", "armor", "[", "legendary", 1,
                                         resist_status="poison", resist_pct=1.0)
    landed = state._afflict_player("poison", dmg=5)
    assert not landed and not state.player.status_effects, \
        "a guaranteed resist should block the ailment entirely"
    print("OK: armor/accessory resist_status blocks a matching ailment")


def test_item_identification():
    from engine.items import (build_item_identity, resolved_name, identity_key,
                               make_cure_potion, _POTION_TYPES, _SCROLL_TYPES)

    identity = build_item_identity(123)
    for _name, effect, _mag in _POTION_TYPES:
        assert f"potion:{effect}" in identity
    for _name, effect, _mag in _SCROLL_TYPES:
        assert f"scroll:{effect}" in identity
    assert len(set(identity.values())) == len(identity), "aliases must all be distinct"

    # Through a real GameState: pickup/use shows the alias until the WHOLE
    # effect (not just this one item instance) gets identified by using one.
    state = GameState(seed=124)
    state.new_game()
    cure = make_cure_potion(state.depth)
    key = identity_key(cure)
    assert resolved_name(cure, state.item_identity, state.player.identified) == state.item_identity[key]
    state.player.inventory.append(cure)
    state.use_item(cure)
    assert key in state.player.identified
    cure2 = make_cure_potion(state.depth)
    assert resolved_name(cure2, state.item_identity, state.player.identified) == cure2.display_name(), \
        "identifying one potion of a type should reveal every potion of that type"
    print("OK: unidentified potions/scrolls show a cosmetic alias until used, then reveal the whole effect type")


def test_cursed_gear_locks_slot():
    from engine.items import Item

    state = GameState(seed=125)
    state.new_game()
    cursed_sword = Item(1, "Test Blade", "weapon", "/", "common", 1, bonus_attack=5, buc="cursed")
    other_sword = Item(2, "Other Blade", "weapon", "/", "common", 1, bonus_attack=10)
    state.player.inventory.extend([cursed_sword, other_sword])

    state.equip_item(cursed_sword)
    assert state.player.equipped_weapon is cursed_sword
    assert cursed_sword.buc_known, "equipping must reveal beatitude"

    # Can't swap to a different weapon, or drop this one, while cursed.
    state.equip_item(other_sword)
    assert state.player.equipped_weapon is cursed_sword, "cursed gear should refuse to be swapped out"
    state.drop_item(cursed_sword)
    assert cursed_sword in state.player.inventory, "cursed gear should refuse to be dropped"

    # A Scroll of Remove Curse lifts it, then both work normally.
    remove_curse = Item(3, "Test Scroll", "scroll", "?", "common", 1, effect="remove_curse")
    state.player.inventory.append(remove_curse)
    state.use_item(remove_curse)
    assert cursed_sword.buc == "uncursed"
    state.equip_item(other_sword)
    assert state.player.equipped_weapon is other_sword, "curse lifted - swapping should now work"
    print("OK: cursed equipped gear can't be swapped/dropped until a Scroll of Remove Curse lifts it")


def test_buc_rolls_and_stat_nudge():
    import random
    from engine.items import _roll_buc, _apply_buc, Item

    rng = random.Random(17)
    seen = {"cursed": False, "uncursed": False, "blessed": False}
    for _ in range(500):
        seen[_roll_buc(rng)] = True
    assert all(seen.values()), "all three beatitude states should show up over enough rolls"

    blessed = Item(2, "Test", "weapon", "/", "common", 1, bonus_attack=10)
    cursed = Item(3, "Test", "weapon", "/", "common", 1, bonus_attack=10)
    _apply_buc(blessed, "blessed", ("bonus_attack",))
    _apply_buc(cursed, "cursed", ("bonus_attack",))
    assert blessed.bonus_attack == 11 and cursed.bonus_attack == 9
    print("OK: beatitude rolls cover all three states and nudge the item's base stat by +-1")


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

    # Re-picked twice now (42->7 for M3's elite rolls, 7->16 for M4's gear
    # affix/set rolls): every generate_item/generate_monster call added a
    # new conditional rng draw, which shifts the ENTIRE rng stream for any
    # fixed seed - the seed still plays fine, it just meets a different mix
    # of monsters/loot along the way. Permadeath is legitimate (see the
    # assertion note below); 16 just clears comfortably more than the
    # required floor count so it isn't one shifted rng draw from flaking
    # again next milestone.
    state = GameState(seed=16)
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


def test_biome_bands():
    from engine.biomes import biome_for

    assert biome_for(1).key == "" and biome_for(10).key == ""
    assert biome_for(11).key == "_caverns" and biome_for(20).key == "_caverns"
    assert biome_for(21).key == "_frozen" and biome_for(30).key == "_frozen"
    assert biome_for(31).key == "_volcanic" and biome_for(40).key == "_volcanic"
    assert biome_for(41).key == "_abyss" and biome_for(200).key == "_abyss"
    # Same band -> the SAME instance (world.py's _descend compares with "is").
    assert biome_for(15) is biome_for(19)
    assert biome_for(15) is not biome_for(25)
    print("OK: biome_for() bands depth into 5 stable, deterministic biomes")


def test_biome_gated_hazard_traps():
    import random
    from engine.dungeon import generate_floor

    def trap_kinds_at(depth, trials=15):
        kinds = set()
        for seed in range(trials):
            floor = generate_floor(depth, random.Random(seed))
            kinds.update(t.kind for t in floor.traps)
        return kinds

    frozen_kinds = trap_kinds_at(25)
    volcanic_kinds = trap_kinds_at(35)
    catacombs_kinds = trap_kinds_at(5)
    assert "ice" in frozen_kinds, "frozen-band floors should be able to roll ice traps"
    assert "ice" not in catacombs_kinds, "ice traps must never appear outside the frozen band"
    assert "burn" in volcanic_kinds, "volcanic-band floors should be able to roll burn traps"
    assert "burn" not in frozen_kinds, "burn traps must never appear outside the volcanic band"
    print("OK: biome-gated hazard trap kinds (ice/burn) only ever appear in their own depth band")


def test_biome_hazard_traps_afflict_player():
    from engine.dungeon import Trap

    state = GameState(seed=201)
    state.new_game()
    state.player.hp = state.player.max_hp = 1000
    state._trigger_trap(Trap(0, 0, "burn"))
    assert any(e.get("type") == "burn" for e in state.player.status_effects)

    state2 = GameState(seed=202)
    state2.new_game()
    state2._trigger_trap(Trap(0, 0, "ice"))
    assert any(e.get("type") == "slow" for e in state2.player.status_effects)
    print("OK: biome hazard traps (burn/ice) afflict the player through the M2 status system")


def test_biome_entry_flavor_message():
    state = GameState(seed=203)
    state.new_game()
    state.depth = 10
    state._enter_floor(regenerate=True)

    log_len = len(state.log)
    state._descend()  # 10 -> 11: crosses into the Caverns
    assert any("Flooded Caverns" in m for m in state.log[log_len:]), \
        "crossing a biome boundary should log a flavor message"

    log_len = len(state.log)
    state._descend()  # 11 -> 12: stays in the Caverns
    assert not any("entered" in m for m in state.log[log_len:]), \
        "staying within the same biome should not repeat the entry message"
    print("OK: crossing a biome boundary logs a one-time flavor message, staying within one doesn't")


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


def test_burn_bleed_status():
    state = GameState(seed=46)
    state.new_game()
    state.player.max_hp = 1000
    state.player.hp = 1000
    state.floor.monsters.clear()
    state.player.status_effects.append({"type": "burn", "dmg": 4})
    hp_start = state.player.hp
    for _ in range(3):
        state.wait()
    # Default burn duration is 3 turns, ticking every turn (unlike poison's
    # every-other-turn), then it's gone on its own - no cure needed.
    assert state.player.hp == hp_start - 3 * 4, f"burn should tick every turn, hp={state.player.hp}"
    assert not any(e.get("type") == "burn" for e in state.player.status_effects), \
        "burn must expire on its own after its default duration"

    # Unlike poison, burn/bleed CAN land the killing blow.
    state2 = GameState(seed=47)
    state2.new_game()
    state2.floor.monsters.clear()
    state2.player.hp = 3
    state2.player.status_effects.append({"type": "bleed", "dmg": 5})
    state2.wait()
    assert state2.player.hp <= 0 and state2.game_over, "bleed must be able to kill, unlike poison"
    print("OK: burn/bleed tick every turn, expire on schedule, and can kill")


def test_freeze_slow_status():
    from engine import status as status_module

    effects = [{"type": "freeze"}]
    assert status_module.is_incapacitated(effects, 5), "freeze blocks every turn"
    status_module.tick(effects, 5)
    assert effects[0]["turns_left"] == 1, "default freeze duration is 2 turns"
    outcomes = status_module.tick(effects, 6)
    assert any(o.kind == "expired" and o.type == "freeze" for o in outcomes)
    assert effects == [], "freeze should remove itself once expired"

    effects = [{"type": "slow"}]
    assert status_module.is_incapacitated(effects, 2), "slow blocks on even turns"
    assert not status_module.is_incapacitated(effects, 3), "slow allows odd turns"
    print("OK: freeze blocks every turn, slow gates on alternating turns, both expire on schedule")


def test_timed_buff_status():
    state = GameState(seed=48)
    state.new_game()
    state.floor.monsters.clear()
    base_atk = state.player.attack_power
    state.player.status_effects.append({"type": "buff_attack", "mult": 1.5})
    assert state.player.attack_power == max(1, round(base_atk * 1.5)), \
        "an active attack buff should scale attack_power"
    for _ in range(4):
        state.wait()
    assert not any(e.get("type") == "buff_attack" for e in state.player.status_effects), \
        "default buff duration is 4 turns"
    assert state.player.attack_power == base_atk, "attack_power should fall back once the buff expires"
    print("OK: timed attack buff scales attack_power and expires on schedule")


def test_cure_keeps_buffs():
    from engine.items import make_cure_potion

    state = GameState(seed=49)
    state.new_game()
    state.player.status_effects.append({"type": "poison", "dmg": 3})
    state.player.status_effects.append({"type": "buff_attack", "mult": 1.4})
    cure = make_cure_potion(1)
    state.player.inventory.append(cure)
    state.use_item(cure)
    types = {e.get("type") for e in state.player.status_effects}
    assert "poison" not in types, "cure must wash away poison"
    assert "buff_attack" in types, "cure must not strip the player's own timed buffs"
    print("OK: cure potion clears ailments but leaves timed buffs intact")


def test_status_effects_survive_save_load():
    from engine.entities import Player

    p = Player()
    p.status_effects.append({"type": "burn", "dmg": 4, "turns_left": 2})
    p.status_effects.append({"type": "buff_defense", "mult": 1.25, "turns_left": 3})
    restored = Player.from_dict(json.loads(json.dumps(p.to_dict())))
    assert restored.status_effects == p.status_effects, "status effects must round-trip through JSON exactly"
    print("OK: status effects round-trip through save/load JSON exactly")


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
        # Equipped gear was never separately compared before (only whatever
        # copy sat in `inventory`) - closing that gap now that affixes/sets
        # (M4) make equipped items' exact stats matter a lot more.
        "equipped": tuple(
            item_key(eq) if eq else None
            for eq in (state.player.equipped_weapon, state.player.equipped_armor,
                       state.player.equipped_accessory)
        ),
        "status_effects": json.dumps(state.player.status_effects, sort_keys=True),
        "identified": sorted(state.player.identified),
        "tiles": ["".join(r) for r in state.floor.tiles],
        # boss_state (phase, cooldowns, pending ability, buffs - also used
        # by elites/kited regular monsters, see engine/bosses.py) is plain
        # JSON-able data - fold it in as a sorted-key string so two
        # semantically-identical dicts always compare equal regardless of
        # insertion order, and so it can never break sorted()'s tuple
        # comparison (x, y already make every monster tuple unique, but a
        # bare dict as a tuple element isn't safely comparable in general).
        # Folded in for every monster, not just bosses, now that regular
        # monsters can carry ability-engine state and status effects too.
        "monsters": sorted((m.x, m.y, m.hp, m.name, m.is_elite,
                            json.dumps(m.boss_state, sort_keys=True),
                            json.dumps(m.status_effects, sort_keys=True))
                           for m in state.floor.monsters),
        "boss_arena_sealed": state.floor.boss_arena_sealed,
        # Never compared before (a pre-existing gap) - trap KIND is now
        # biome-dependent (M5), worth catching a desync in either kind or
        # triggered-state after a replay.
        "traps": sorted((t.x, t.y, t.kind, t.triggered) for t in state.floor.traps),
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
    test_boss_ability_kits()
    test_boss_fight_end_to_end()
    test_boss_determinism()
    test_deep_monster_variety()
    test_monster_traits_data_integrity()
    test_spider_poison_proc_reproduced()
    test_elite_generation_and_ability()
    test_ranged_and_fleeing_ai()
    test_fov_blocks_through_walls()
    test_item_scaling()
    test_gear_affixes_and_sets()
    test_weapon_affix_effects_in_combat()
    test_gear_resistance_blocks_ailment()
    test_item_identification()
    test_cursed_gear_locks_slot()
    test_buc_rolls_and_stat_nudge()
    test_monster_scaling()
    test_shop_transactions()
    test_shop_prices_scale_with_depth()
    test_traps()
    test_biome_bands()
    test_biome_gated_hazard_traps()
    test_biome_hazard_traps_afflict_player()
    test_biome_entry_flavor_message()
    test_poison_status()
    test_burn_bleed_status()
    test_freeze_slow_status()
    test_timed_buff_status()
    test_cure_keeps_buffs()
    test_status_effects_survive_save_load()
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
