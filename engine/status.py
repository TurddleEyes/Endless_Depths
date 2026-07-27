"""Generalized status-effect system: damage-over-time, turn-skips, and
timed stat buffs/debuffs - all over the SAME plain-dict shape poison has
always used (Player.status_effects / eventually Monster.status_effects),
so it round-trips through save.py for free with no new serialization code.

Mirrors puzzles.py/bosses.py's split with world.py: everything here is a
pure function over plain data. This module never touches hp, never logs,
never emits an event - world.py applies every StatusOutcome tick() returns.

A bare dict like {"type": "poison", "dmg": 3} must keep resolving to
exactly today's behavior, so every other field (duration, tick rate,
whether it can kill) is optional and falls back to DEFAULTS below.
"""
from __future__ import annotations

from dataclasses import dataclass

# Ailments: sicknesses a Potion of Cure washes away. Buffs/debuffs are a
# creature's own state (rage, haste, a shield spell) - a cure cleanses
# poison, not a warrior's battle-fury.
AILMENT_TYPES = {"poison", "burn", "bleed", "slow", "freeze"}
DOT_TYPES = {"poison", "burn", "bleed"}

# Per-type defaults. Only fields NOT already present on the effect dict are
# filled in from here, so callers can override any one of them per-instance
# (e.g. a stronger burn with a longer fuse) while everything else still
# resolves the same as always.
DEFAULTS = {
    # Ticks every other turn (fires when turn_count % 2 == 1) and is
    # permanent until cured - never expires, never lands the killing blow.
    "poison": {"tick_every": 2, "can_kill": False, "turns_left": None},
    "burn": {"tick_every": 1, "can_kill": True, "turns_left": 3},
    "bleed": {"tick_every": 1, "can_kill": True, "turns_left": 5},
    "slow": {"turns_left": 3},
    "freeze": {"turns_left": 2},
    "buff_attack": {"turns_left": 4, "mult": 1.3},
    "buff_defense": {"turns_left": 4, "mult": 1.3},
    "debuff_attack": {"turns_left": 4, "mult": 0.75},
    "debuff_defense": {"turns_left": 4, "mult": 0.75},
}


@dataclass
class StatusOutcome:
    """One effect's result for this turn's tick(). world.py owns hp/log/
    events - this is purely descriptive."""
    type: str
    kind: str  # "dot" | "expired"
    dmg: int = 0
    can_kill: bool = False


def _default(etype: str, field: str, fallback=None):
    return DEFAULTS.get(etype, {}).get(field, fallback)


def add_effect(effects: list, new_eff: dict) -> bool:
    """Adds a status, or strengthens/refreshes a matching one already
    active (same "keep the strongest dose" rule poison has always used).
    Returns True if this created a brand new entry - callers typically only
    want to react to that (e.g. emit a "poisoned" popup once, not on every
    re-application)."""
    etype = new_eff["type"]
    for eff in effects:
        if eff.get("type") != etype:
            continue
        if "dmg" in new_eff:
            eff["dmg"] = max(eff.get("dmg", 0), new_eff["dmg"])
        if "mult" in new_eff:
            cur = eff.get("mult", _default(etype, "mult", 1.0))
            stronger = max if etype.startswith("buff_") else min
            eff["mult"] = stronger(cur, new_eff["mult"])
        new_turns = new_eff.get("turns_left", _default(etype, "turns_left"))
        if new_turns is not None:
            cur_turns = eff.get("turns_left", _default(etype, "turns_left")) or 0
            eff["turns_left"] = max(cur_turns, new_turns)
        return False
    effects.append(dict(new_eff))
    return True


def tick(effects: list, turn_count: int) -> list:
    """Advances every status by one turn: decides which DoTs fire, counts
    down timed effects, and drops anything that just expired (mutating
    `effects` in place - same pattern as bosses.py mutating boss_state).
    Returns the list of StatusOutcome for world.py to log/emit/apply."""
    outcomes = []
    for eff in list(effects):
        etype = eff.get("type")
        if etype in DOT_TYPES:
            tick_every = eff.get("tick_every", _default(etype, "tick_every", 1))
            if turn_count % tick_every == tick_every - 1:
                outcomes.append(StatusOutcome(
                    type=etype, kind="dot", dmg=eff.get("dmg", 0),
                    can_kill=eff.get("can_kill", _default(etype, "can_kill", False))))

        turns_left = eff.get("turns_left", _default(etype, "turns_left"))
        if turns_left is None:
            continue
        turns_left -= 1
        if turns_left <= 0:
            effects.remove(eff)
            outcomes.append(StatusOutcome(type=etype, kind="expired"))
        else:
            eff["turns_left"] = turns_left
    return outcomes


def stat_mult(effects: list, kind: str) -> float:
    """Combined multiplier on "attack" or "defense" from active timed
    buffs/debuffs. A buff and a debuff of the same stat both apply and
    stack multiplicatively, so e.g. a hasted-but-hexed target nets out."""
    mult = 1.0
    for eff in effects:
        etype = eff.get("type")
        if etype in (f"buff_{kind}", f"debuff_{kind}"):
            mult *= eff.get("mult", _default(etype, "mult", 1.0))
    return mult


def is_incapacitated(effects: list, turn_count: int) -> bool:
    """True if freeze/slow should skip this actor's action this turn.
    Freeze blocks every turn; the engine has no underlying speed stat, so
    slow just gates on the same alternating-turn clock poison already used
    (blocks on even turn_count). Uses the same turn_count passed to tick()."""
    for eff in effects:
        etype = eff.get("type")
        if etype == "freeze":
            return True
        if etype == "slow" and turn_count % 2 == 0:
            return True
    return False
