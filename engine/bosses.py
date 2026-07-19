"""Boss fight logic - abilities, phases, and the 12 hand-built boss kits.

Mirrors puzzles.py's architecture: pure functions over plain data, no
GameState coupling. maybe_process_boss_turn() is called once per boss per
turn from GameState._process_monsters(); it returns a list of
BossTurnResult describing what happened (phase change / telegraph /
resolved ability), and world.py does all the logging/emitting/HP-applying/
minion-spawning based on those results. All randomness comes from the
rng passed in (GameState.rng), so boss fights are replay-deterministic
exactly like everything else in the engine.

Turn structure per boss, once "chasing":
  1. Phase check (HP threshold crossed -> permanent enrage stat bump).
  2. Tick any active self-buff's remaining duration.
  3. Tick ability cooldowns.
  4. If an ability is "pending" (telegraphed last turn): resolve it now.
     This consumes the boss's turn - no move, no melee.
  5. Else, if an unlocked, off-cooldown ability exists: telegraph one.
     This ALSO consumes the turn - the boss announces, doesn't act, and
     the player gets exactly one full turn to react (retreat out of an
     aoe/poison radius, break line of sight for a ranged bolt, heal).
  6. Otherwise nothing here consumes the turn - world.py's normal
     chase/melee logic runs unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

PHASE_THRESHOLDS = (0.75, 0.50, 0.25)  # HP fraction; crossing below bumps the phase
ENRAGE_ATTACK_MULT = {1: 1.0, 2: 1.0, 3: 1.15, 4: 1.35}
ENRAGE_DEFENSE_MULT = {1: 1.0, 2: 1.0, 3: 1.05, 4: 1.1}
SELF_BUFF_DURATION = 4  # turns a self_buff ability's boost lasts on top of enrage


@dataclass
class Ability:
    name: str
    kind: str  # summon | aoe_burst | poison_burst | ranged_bolt | self_heal | self_buff | lifedrain | blink_strike
    telegraph_msg: str  # "{Title} {this}" - shown the turn before it fires
    resolve_msg: str    # shown when it fires, before the hit/miss clause
    unlock_phase: int   # phase (2 or 3) at which this ability becomes usable
    cooldown: int = 5
    radius: int = 1          # aoe_burst / poison_burst: Chebyshev range that still hits
    attack_mult: float = 1.3  # damage-dealing kinds: multiplier on the boss's (buffed) attack
    heal_pct: float = 0.2     # self_heal: fraction of max HP restored
    buff_kind: str = "attack"  # self_buff: "attack" or "defense"
    buff_mult: float = 1.35
    minion_name: str = ""     # summon: MONSTER_TEMPLATES name to spawn
    minion_count: int = 2


@dataclass
class BossKit:
    template_name: str  # must match a MONSTER_TEMPLATES[i][0] exactly
    title: str           # flavor name shown in the log/UI ("the Broodmother")
    abilities: tuple      # (phase-2 ability, phase-3 ability)


@dataclass
class BossTurnResult:
    kind: str  # "phase" | "telegraph" | "resolve"
    message: str
    event: str = ""
    ability_kind: str = ""
    damage: int = 0
    heal: int = 0
    poison: bool = False
    minion_name: str = ""
    minion_count: int = 0
    teleport_to: Optional[tuple] = None


BOSS_KITS: dict = {
    "Rat": BossKit("Rat", "the Plague Rat King", (
        Ability("shriek", "summon",
                "lets out a piercing shriek that echoes down every tunnel...",
                "Ratlings pour out of the walls!",
                unlock_phase=2, cooldown=6, minion_name="Rat", minion_count=3),
        Ability("fangs", "poison_burst",
                "bares yellow teeth, dripping with sickness...",
                "It lunges, fangs flashing!",
                unlock_phase=3, cooldown=5, radius=1),
    )),
    "Giant Spider": BossKit("Giant Spider", "the Broodmother", (
        Ability("venom_burst", "poison_burst",
                "rears back, abdomen glistening with venom...",
                "A cloud of venom bursts outward!",
                unlock_phase=2, cooldown=5, radius=2),
        Ability("spiderlings", "summon",
                "clicks its mandibles - unseen legs stir in the dark...",
                "Spiderlings drop from the ceiling!",
                unlock_phase=3, cooldown=6, minion_name="Giant Spider", minion_count=2),
    )),
    "Goblin": BossKit("Goblin", "the Goblin Warchief", (
        Ability("horn", "summon",
                "raises a crooked horn to its lips...",
                "A goblin warband rushes to answer the horn!",
                unlock_phase=2, cooldown=6, minion_name="Goblin", minion_count=3),
        Ability("bloodroar", "self_buff",
                "beats its chest and howls for blood...",
                "Its swings come faster and harder!",
                unlock_phase=3, cooldown=5, buff_kind="attack", buff_mult=1.4),
    )),
    "Kobold": BossKit("Kobold", "the Trapmaster", (
        Ability("rigged_blast", "aoe_burst",
                "stamps down on a hidden lever...",
                "The floor erupts in a rigged blast!",
                unlock_phase=2, cooldown=5, radius=1, attack_mult=1.3),
        Ability("shield_cache", "self_buff",
                "ducks behind a wall of scavenged shields...",
                "It hunkers down, plating clattering into place!",
                unlock_phase=3, cooldown=5, buff_kind="defense", buff_mult=1.5),
    )),
    "Skeleton": BossKit("Skeleton", "the Bone Colossus", (
        Ability("reassemble", "self_heal",
                "rattles - loose bones drift back into place around it...",
                "Fallen bones snap back onto its frame!",
                unlock_phase=2, cooldown=5, heal_pct=0.2),
        Ability("bone_shards", "aoe_burst",
                "draws itself up, ribs flexing outward...",
                "A burst of bone shards rakes outward!",
                unlock_phase=3, cooldown=5, radius=1, attack_mult=1.35),
    )),
    "Orc": BossKit("Orc", "the Orc Warlord", (
        Ability("ground_slam", "aoe_burst",
                "plants its feet and raises its weapon overhead...",
                "The ground SLAMS beneath a crushing blow!",
                unlock_phase=2, cooldown=5, radius=1, attack_mult=1.4),
        Ability("battle_fury", "self_buff",
                "roars, veins bulging with battle-fury...",
                "Its rage boils over!",
                unlock_phase=3, cooldown=6, buff_kind="attack", buff_mult=1.35),
    )),
    "Wraith": BossKit("Wraith", "the Deathless Wraith", (
        Ability("cold_grasp", "lifedrain",
                "reaches through you before its body arrives...",
                "Cold fingers close around your heart!",
                unlock_phase=2, cooldown=4, attack_mult=1.3),
        Ability("mist_strike", "blink_strike",
                "dissolves into mist, drifting toward your shadow...",
                "It reforms at your back and strikes!",
                unlock_phase=3, cooldown=5, attack_mult=1.25),
    )),
    "Troll": BossKit("Troll", "the Troll Chieftain", (
        Ability("regenerate", "self_heal",
                "digs blunt claws into its own wounds...",
                "Its flesh knits back together, wet and fast!",
                unlock_phase=2, cooldown=5, heal_pct=0.22),
        Ability("reckless_swing", "aoe_burst",
                "winds up a wild, two-handed swing...",
                "A reckless overhead blow crashes down!",
                unlock_phase=3, cooldown=5, radius=1, attack_mult=1.4),
    )),
    "Ogre": BossKit("Ogre", "the Ogre Brute", (
        Ability("boulder_toss", "aoe_burst",
                "tears a slab of stone free of the floor...",
                "A boulder of broken stone comes crashing down!",
                unlock_phase=2, cooldown=5, radius=2, attack_mult=1.3),
        Ability("enrage", "self_buff",
                "grinds its teeth into a snarling frenzy...",
                "It stops holding back!",
                unlock_phase=3, cooldown=6, buff_kind="attack", buff_mult=1.4),
    )),
    "Dark Knight": BossKit("Dark Knight", "the Dark Knight Commander", (
        Ability("shield_wall", "self_buff",
                "raises a black shield, runes flaring along its edge...",
                "A wall of dark steel locks into place!",
                unlock_phase=2, cooldown=5, buff_kind="defense", buff_mult=1.5),
        Ability("cleave", "aoe_burst",
                "draws its blade back in a low, wide arc...",
                "A cleaving strike scythes through the air!",
                unlock_phase=3, cooldown=5, radius=1, attack_mult=1.35),
    )),
    "Wyvern": BossKit("Wyvern", "the Wyvern Matriarch", (
        Ability("fire_breath", "ranged_bolt",
                "draws a burning breath deep into its chest...",
                "A gout of fire roars across the room!",
                unlock_phase=2, cooldown=4, attack_mult=1.3),
        Ability("wing_gale", "aoe_burst",
                "beats its wings, kicking up a howling gale...",
                "A battering wind slams into you!",
                unlock_phase=3, cooldown=5, radius=2, attack_mult=1.25),
    )),
    "Lich": BossKit("Lich", "the Lich", (
        Ability("raise_dead", "summon",
                "traces a cold sigil in the air...",
                "Bones rise from the dust to answer the call!",
                unlock_phase=2, cooldown=6, minion_name="Skeleton", minion_count=2),
        Ability("death_bolt", "ranged_bolt",
                "a violet light gathers at its fingertips...",
                "A bolt of raw death strikes true!",
                unlock_phase=3, cooldown=4, attack_mult=1.45),
    )),
    # -- the deep breeds --
    "Ghoul": BossKit("Ghoul", "the Grave-Glutton", (
        Ability("feast", "lifedrain",
                "unhinges its jaw with a wet crack...",
                "It tears a mouthful away and swallows!",
                unlock_phase=2, cooldown=4, attack_mult=1.3),
        Ability("carrion_call", "summon",
                "lets out a gurgling, hungry moan...",
                "Ghouls claw their way up through the floor!",
                unlock_phase=3, cooldown=6, minion_name="Ghoul", minion_count=2),
    )),
    "Basilisk": BossKit("Basilisk", "the Stone-Eyed King", (
        Ability("venom_spit", "poison_burst",
                "its throat swells with churning venom...",
                "A spray of caustic venom rains down!",
                unlock_phase=2, cooldown=5, radius=2),
        Ability("stone_hide", "self_buff",
                "its scales begin to gray into granite...",
                "Its hide sets like quarry stone!",
                unlock_phase=3, cooldown=5, buff_kind="defense", buff_mult=1.6),
    )),
    "Shade": BossKit("Shade", "the Unlit", (
        Ability("smother", "lifedrain",
                "the torchlight around you thins to a thread...",
                "The dark itself inhales!",
                unlock_phase=2, cooldown=4, attack_mult=1.3),
        Ability("unlight_step", "blink_strike",
                "folds itself into your shadow...",
                "It unfolds behind you, cold as a held breath!",
                unlock_phase=3, cooldown=5, attack_mult=1.3),
    )),
    "Grave Golem": BossKit("Grave Golem", "the Doorstone", (
        Ability("brace", "self_buff",
                "grinds its seams shut, stone on stone...",
                "It sets itself like a sealed tomb!",
                unlock_phase=2, cooldown=5, buff_kind="defense", buff_mult=1.5),
        Ability("headstone_slam", "aoe_burst",
                "hoists its whole weight overhead...",
                "The floor buckles under a monumental blow!",
                unlock_phase=3, cooldown=5, radius=1, attack_mult=1.45),
    )),
    "Void Weaver": BossKit("Void Weaver", "the Last Shroudmother", (
        Ability("brood_silk", "summon",
                "spins something pale and squirming in its forelegs...",
                "Weavers descend on threads of nothing!",
                unlock_phase=2, cooldown=6, minion_name="Void Weaver", minion_count=2),
        Ability("winding_sheet", "poison_burst",
                "casts a wide, glistening net of silk...",
                "The shroud settles over you, wet with venom!",
                unlock_phase=3, cooldown=5, radius=2),
    )),
    "Revenant": BossKit("Revenant", "the Oathbound", (
        Ability("refuse_death", "self_heal",
                "its wounds begin to close in reverse...",
                "Its oath drags it back from the brink!",
                unlock_phase=2, cooldown=5, heal_pct=0.25),
        Ability("oathstrike", "aoe_burst",
                "levels its broken blade in a dead man's salute...",
                "The blade falls with the weight of a promise!",
                unlock_phase=3, cooldown=5, radius=1, attack_mult=1.4),
    )),
    "Chimera": BossKit("Chimera", "the Threefold Beast", (
        Ability("fire_head", "ranged_bolt",
                "one of its heads draws a glowing breath...",
                "A jet of flame lashes across the room!",
                unlock_phase=2, cooldown=4, attack_mult=1.3),
        Ability("all_three", "aoe_burst",
                "all three heads scream at once...",
                "Claw, fang and horn strike as one!",
                unlock_phase=3, cooldown=5, radius=1, attack_mult=1.45),
    )),
    "Barrow King": BossKit("Barrow King", "the First Interred", (
        Ability("court_of_bones", "summon",
                "raps its scepter twice on the floor...",
                "Its buried court answers the summons!",
                unlock_phase=2, cooldown=6, minion_name="Revenant", minion_count=2),
        Ability("crown_wrath", "self_buff",
                "the tarnished crown begins to glow...",
                "Old royalty remembers its rage!",
                unlock_phase=3, cooldown=5, buff_kind="attack", buff_mult=1.4),
    )),
    "Deep Wyrm": BossKit("Deep Wyrm", "the Undertow", (
        Ability("swallowing_coil", "aoe_burst",
                "its coils rise around you like a closing tide...",
                "The coils crash together!",
                unlock_phase=2, cooldown=5, radius=2, attack_mult=1.3),
        Ability("pressure_roar", "ranged_bolt",
                "a roar builds somewhere far below its throat...",
                "The roar arrives like deep water!",
                unlock_phase=3, cooldown=4, attack_mult=1.35),
    )),
    "Archlich": BossKit("Archlich", "the Keeper of Names", (
        Ability("recite", "summon",
                "begins reading aloud from an open hand...",
                "The named dead answer the recitation!",
                unlock_phase=2, cooldown=6, minion_name="Revenant", minion_count=2),
        Ability("unwrite", "ranged_bolt",
                "a black quill of light forms at its fingertip...",
                "A stroke of erasure cuts through you!",
                unlock_phase=3, cooldown=4, attack_mult=1.5),
    )),
    "Faceless One": BossKit("Faceless One", "the Borrowed Face", (
        Ability("wear_you", "blink_strike",
                "its blank face ripples, trying on your outline...",
                "It steps out of where you were just standing!",
                unlock_phase=2, cooldown=5, attack_mult=1.3),
        Ability("smooth_over", "self_heal",
                "passes a hand across its wounds like wet clay...",
                "Its surface smooths back to blankness!",
                unlock_phase=3, cooldown=5, heal_pct=0.22),
    )),
    "Marrow Fiend": BossKit("Marrow Fiend", "the Hollowing Hunger", (
        Ability("marrow_sup", "lifedrain",
                "its hollow needles extend, questing...",
                "It drinks deep of what keeps you standing!",
                unlock_phase=2, cooldown=4, attack_mult=1.35),
        Ability("hunger_cloud", "poison_burst",
                "exhales a cloud of powdered bone...",
                "The bone-dust settles into your lungs!",
                unlock_phase=3, cooldown=5, radius=2),
    )),
    "Grave Titan": BossKit("Grave Titan", "the Weight of the Deep", (
        Ability("burial_blow", "aoe_burst",
                "raises fists the size of coffins...",
                "The blow lands like six feet of earth!",
                unlock_phase=2, cooldown=5, radius=2, attack_mult=1.35),
        Ability("deep_set", "self_buff",
                "settles its mass like a mountain sitting down...",
                "It becomes unmovable, unbreakable!",
                unlock_phase=3, cooldown=6, buff_kind="defense", buff_mult=1.6),
    )),
    "Unfinished One": BossKit("Unfinished One", "the First Draft", (
        Ability("borrow_shapes", "summon",
                "sketches figures in the air with a half-made hand...",
                "Rough copies of old delvers shamble forward!",
                unlock_phase=2, cooldown=6, minion_name="Faceless One", minion_count=2),
        Ability("revision", "ranged_bolt",
                "the space around you begins to be rewritten...",
                "Reality's rough edit slices through you!",
                unlock_phase=3, cooldown=4, attack_mult=1.5),
    )),
}


def effective_attack(monster) -> int:
    mult = monster.boss_state.get("buff_attack_mult", 1.0) if monster.is_boss else 1.0
    return round(monster.attack * mult)


def effective_defense(monster) -> int:
    mult = monster.boss_state.get("buff_defense_mult", 1.0) if monster.is_boss else 1.0
    return round(monster.defense * mult)


def _kit_for(monster) -> Optional[BossKit]:
    base_name = monster.name[:-5] if monster.name.endswith(" Boss") else monster.name
    return BOSS_KITS.get(base_name)


def maybe_process_boss_turn(monster, player, floor, rng) -> list:
    """Empty list -> world.py's normal chase/melee logic should run as-is.
    A list containing a "telegraph" or "resolve" result -> that result
    fully handles this boss's turn (world.py must NOT also move/attack it).
    A list containing only a "phase" result -> logged/emitted, but the
    turn is NOT consumed; normal behavior still follows."""
    if not monster.is_boss or monster.state != "chasing":
        return []
    kit = _kit_for(monster)
    if kit is None:
        return []
    bs = monster.boss_state
    results = []

    hp_pct = monster.hp / max(1, monster.max_hp)
    target_phase = 1
    for i, threshold in enumerate(PHASE_THRESHOLDS, start=2):
        if hp_pct < threshold:
            target_phase = i
    if target_phase > bs.get("phase", 1):
        bs["phase"] = target_phase
        bs["buff_attack_mult"] = ENRAGE_ATTACK_MULT.get(target_phase, 1.0)
        bs["buff_defense_mult"] = ENRAGE_DEFENSE_MULT.get(target_phase, 1.0)
        results.append(BossTurnResult(
            kind="phase", event="boss_phase",
            message=f"{kit.title} is enraged! (phase {target_phase})"))

    if bs.get("buff_turns_left", 0) > 0:
        bs["buff_turns_left"] -= 1
        if bs["buff_turns_left"] == 0:
            bs["buff_attack_mult"] = ENRAGE_ATTACK_MULT.get(bs.get("phase", 1), 1.0)
            bs["buff_defense_mult"] = ENRAGE_DEFENSE_MULT.get(bs.get("phase", 1), 1.0)

    for name in list(bs.get("cooldowns", {})):
        if bs["cooldowns"][name] > 0:
            bs["cooldowns"][name] -= 1

    pending = bs.get("pending")
    if pending:
        ability = next((a for a in kit.abilities if a.name == pending), None)
        bs["pending"] = None
        if ability is not None:
            results.append(_resolve_ability(kit, ability, monster, player, floor, rng))
            bs.setdefault("cooldowns", {})[ability.name] = ability.cooldown
        return results

    ready = [a for a in kit.abilities
             if bs.get("phase", 1) >= a.unlock_phase
             and bs.get("cooldowns", {}).get(a.name, 0) <= 0]
    if ready:
        ability = ready[0] if len(ready) == 1 else rng.choice(ready)
        bs["pending"] = ability.name
        results.append(BossTurnResult(
            kind="telegraph", event="boss_telegraph", ability_kind=ability.kind,
            message=f"{kit.title} {ability.telegraph_msg}"))
        return results

    return results


def _resolve_ability(kit, ability, monster, player, floor, rng) -> BossTurnResult:
    atk = effective_attack(monster)
    dmg = max(1, round(atk * ability.attack_mult) - player.defense_power // 2)
    dist = abs(monster.x - player.x) + abs(monster.y - player.y)

    if ability.kind == "self_heal":
        heal = min(round(monster.max_hp * ability.heal_pct), monster.max_hp - monster.hp)
        monster.hp += heal
        return BossTurnResult(kind="resolve", event="boss_ability", ability_kind=ability.kind,
                               heal=heal, message=f"{ability.resolve_msg} (+{heal} HP)")

    if ability.kind == "self_buff":
        key = "buff_attack_mult" if ability.buff_kind == "attack" else "buff_defense_mult"
        monster.boss_state["buff_turns_left"] = SELF_BUFF_DURATION
        monster.boss_state[key] = max(monster.boss_state.get(key, 1.0), ability.buff_mult)
        return BossTurnResult(kind="resolve", event="boss_ability", ability_kind=ability.kind,
                               message=ability.resolve_msg)

    if ability.kind == "summon":
        return BossTurnResult(kind="resolve", event="summon", ability_kind=ability.kind,
                               minion_name=ability.minion_name, minion_count=ability.minion_count,
                               message=ability.resolve_msg)

    if ability.kind == "aoe_burst":
        if dist <= ability.radius:
            return BossTurnResult(kind="resolve", event="boss_ability", ability_kind=ability.kind,
                                   damage=dmg,
                                   message=f"{ability.resolve_msg} You take {dmg} damage!")
        return BossTurnResult(kind="resolve", event="boss_ability_miss", ability_kind=ability.kind,
                               message=f"{ability.resolve_msg} You dodge clear of it!")

    if ability.kind == "poison_burst":
        if dist <= ability.radius:
            return BossTurnResult(kind="resolve", event="boss_ability", ability_kind=ability.kind,
                                   poison=True,
                                   message=f"{ability.resolve_msg} Poison seeps into you!")
        return BossTurnResult(kind="resolve", event="boss_ability_miss", ability_kind=ability.kind,
                               message=f"{ability.resolve_msg} You escape the cloud!")

    if ability.kind == "ranged_bolt":
        if floor.visible[monster.y][monster.x]:
            return BossTurnResult(kind="resolve", event="boss_ability", ability_kind=ability.kind,
                                   damage=dmg,
                                   message=f"{ability.resolve_msg} You take {dmg} damage!")
        return BossTurnResult(kind="resolve", event="boss_ability_miss", ability_kind=ability.kind,
                               message=f"{ability.resolve_msg} It loses its mark in the dark!")

    if ability.kind == "lifedrain":
        monster.hp = min(monster.max_hp, monster.hp + dmg)
        return BossTurnResult(kind="resolve", event="boss_ability", ability_kind=ability.kind,
                               damage=dmg, heal=dmg,
                               message=f"{ability.resolve_msg} You take {dmg} damage; it mends by the same!")

    if ability.kind == "blink_strike":
        adjacent = [(player.x + dx, player.y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                    if floor.is_walkable(player.x + dx, player.y + dy)
                    and floor.monster_at(player.x + dx, player.y + dy) is None]
        teleport_to = rng.choice(adjacent) if adjacent else None
        if teleport_to:
            monster.x, monster.y = teleport_to
        return BossTurnResult(kind="resolve", event="boss_ability", ability_kind=ability.kind,
                               damage=dmg, teleport_to=teleport_to,
                               message=f"{ability.resolve_msg} You take {dmg} damage!")

    return BossTurnResult(kind="resolve", event="boss_ability", message="...")
