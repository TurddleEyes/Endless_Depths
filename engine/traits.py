"""Data-driven per-monster-type combat flavor: an on-hit status proc for
melee attacks, and a default AI style. Same idea as bosses.py's BOSS_KITS -
one shared table instead of scattered name checks in world.py's monster-turn
logic (this replaces the old hardcoded "if 'Spider' in m.name" poison proc).

Unlike the elite roll (a random, per-spawn "tougher instance" chance), these
are permanent per-species traits: every Wyvern has the same AI style, not
just some of them.
"""
from __future__ import annotations

from dataclasses import dataclass

from .entities import base_template_name


@dataclass
class MonsterTrait:
    proc_type: str = ""      # "" = no on-hit status proc; else poison/burn/bleed
    proc_chance: float = 0.0
    # Reproduces the original Spider formula exactly: max(1, flat + depth // div).
    proc_dmg_flat: int = 1
    proc_dmg_div: int = 8
    ai: str = "melee"        # "melee" | "ranged" | "fleeing" | "caster"


# Reproduces the original hardcoded Spider proc exactly (same 20% chance,
# same damage formula), then extends the idea to a few more breeds for
# combat variety, plus the new ranged/fleeing/caster AI styles.
MONSTER_TRAITS: dict = {
    "Giant Spider": MonsterTrait(proc_type="poison", proc_chance=0.2),
    "Basilisk": MonsterTrait(proc_type="poison", proc_chance=0.2),
    "Wyvern": MonsterTrait(proc_type="burn", proc_chance=0.18, ai="ranged"),
    "Ghoul": MonsterTrait(proc_type="bleed", proc_chance=0.18),
    "Rat": MonsterTrait(ai="fleeing"),
    "Skeleton": MonsterTrait(ai="caster"),
    "Lich": MonsterTrait(ai="ranged"),
}

DEFAULT_TRAIT = MonsterTrait()


def trait_for(monster) -> MonsterTrait:
    return MONSTER_TRAITS.get(base_template_name(monster.name), DEFAULT_TRAIT)
