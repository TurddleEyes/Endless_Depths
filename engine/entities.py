"""Player and monster entity definitions."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import constants as C
from .items import Item


@dataclass
class Player:
    x: int = 0
    y: int = 0
    hp: int = C.PLAYER_BASE_HP
    max_hp: int = C.PLAYER_BASE_HP
    base_attack: int = C.PLAYER_BASE_ATTACK
    base_defense: int = C.PLAYER_BASE_DEFENSE
    level: int = 1
    xp: int = 0
    xp_to_next: int = C.PLAYER_XP_BASE
    gold: int = 0
    inventory: list = field(default_factory=list)
    equipped_weapon: Optional[Item] = None
    equipped_armor: Optional[Item] = None
    equipped_accessory: Optional[Item] = None
    status_effects: list = field(default_factory=list)
    kills: int = 0
    turns: int = 0

    @property
    def attack_power(self) -> int:
        bonus = 0
        for eq in (self.equipped_weapon, self.equipped_accessory):
            if eq:
                bonus += eq.bonus_attack
        return self.base_attack + bonus

    @property
    def defense_power(self) -> int:
        bonus = 0
        for eq in (self.equipped_armor, self.equipped_accessory):
            if eq:
                bonus += eq.bonus_defense
        return self.base_defense + bonus

    def is_alive(self) -> bool:
        return self.hp > 0

    def gain_xp(self, amount: int) -> list:
        messages = []
        self.xp += amount
        while self.xp >= self.xp_to_next:
            self.xp -= self.xp_to_next
            self.level += 1
            self.max_hp += 6
            self.hp = self.max_hp
            self.base_attack += 2
            self.base_defense += 1
            self.xp_to_next = round(self.xp_to_next * C.PLAYER_XP_GROWTH)
            messages.append(f"You reached level {self.level}! Fully healed and stronger.")
        return messages

    def equip(self, item: Item) -> str:
        if item.category == "weapon":
            self.equipped_weapon = item
            return f"You equip the {item.name}."
        if item.category == "armor":
            self.equipped_armor = item
            return f"You equip the {item.name}."
        if item.category == "accessory":
            self.equipped_accessory = item
            return f"You equip the {item.name}."
        return f"You can't equip the {item.name}."

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["inventory"] = [i.to_dict() for i in self.inventory]
        d["equipped_weapon"] = self.equipped_weapon.to_dict() if self.equipped_weapon else None
        d["equipped_armor"] = self.equipped_armor.to_dict() if self.equipped_armor else None
        d["equipped_accessory"] = self.equipped_accessory.to_dict() if self.equipped_accessory else None
        return d

    @staticmethod
    def from_dict(data: dict) -> "Player":
        data = dict(data)
        data["inventory"] = [Item.from_dict(i) for i in data.get("inventory", [])]
        data["equipped_weapon"] = Item.from_dict(data["equipped_weapon"]) if data.get("equipped_weapon") else None
        data["equipped_armor"] = Item.from_dict(data["equipped_armor"]) if data.get("equipped_armor") else None
        data["equipped_accessory"] = Item.from_dict(data["equipped_accessory"]) if data.get("equipped_accessory") else None
        return Player(**data)


# name, glyph, hp, attack, defense, xp_reward, gold_reward, min_depth
#
# Base stats follow a deliberate curve (attack/min_depth tapers from ~1.0
# toward ~0.6-0.7 as depth grows; the flat depth-scale multiplier in
# _scaled_stats does the rest), so a breed's FIRST appearance always reads
# as "newer and scarier than the old breeds at this depth" without spiking
# the overall difficulty curve. The spawn weighting in generate_monster
# already favors the newest eligible breeds, so each band below becomes
# the local population as players reach it.
MONSTER_TEMPLATES = [
    ("Rat", "r", 5, 2, 0, 3, 2, 1),
    ("Giant Spider", "s", 7, 3, 0, 5, 3, 1),
    ("Goblin", "g", 9, 3, 1, 7, 5, 1),
    ("Kobold", "k", 8, 4, 0, 6, 4, 2),
    ("Skeleton", "z", 12, 4, 2, 10, 6, 3),
    ("Orc", "o", 16, 5, 2, 14, 9, 5),
    ("Wraith", "w", 14, 7, 1, 16, 10, 7),
    ("Troll", "T", 24, 8, 3, 24, 15, 9),
    ("Ogre", "O", 30, 9, 3, 28, 18, 11),
    ("Dark Knight", "K", 26, 10, 5, 32, 22, 14),
    ("Wyvern", "W", 34, 12, 4, 40, 28, 17),
    ("Lich", "L", 30, 14, 3, 48, 35, 20),
    # -- the deep breeds: something new keeps appearing all the way down --
    ("Ghoul", "u", 34, 15, 4, 54, 38, 22),
    ("Basilisk", "b", 38, 17, 5, 62, 43, 26),
    ("Shade", "h", 34, 20, 4, 70, 48, 30),
    ("Grave Golem", "G", 52, 19, 8, 80, 54, 34),
    ("Void Weaver", "V", 44, 23, 6, 90, 60, 38),
    ("Revenant", "v", 50, 25, 8, 100, 66, 42),
    ("Chimera", "C", 58, 27, 8, 112, 72, 46),
    ("Barrow King", "R", 62, 30, 10, 126, 80, 50),
    ("Deep Wyrm", "D", 72, 33, 10, 142, 88, 55),
    ("Archlich", "A", 64, 38, 9, 160, 96, 60),
    ("Faceless One", "F", 74, 42, 11, 180, 105, 66),
    ("Marrow Fiend", "f", 86, 47, 13, 205, 115, 74),
    ("Grave Titan", "I", 100, 52, 15, 232, 126, 82),
    ("Unfinished One", "n", 96, 60, 14, 265, 140, 90),
]


@dataclass
class Monster:
    x: int
    y: int
    name: str
    glyph: str
    hp: int
    max_hp: int
    attack: int
    defense: int
    xp_reward: int
    gold_reward: int
    state: str = "idle"  # idle, chasing
    is_boss: bool = False
    # Boss-only runtime scratch space (plain JSON-able data so it survives
    # save/replay fingerprinting for free). See engine/bosses.py. Keys:
    # phase (int), cooldowns (dict[ability_name -> turns left]),
    # pending (ability name awaiting resolution, or None),
    # buff_turns_left (int), buff_attack_mult/buff_defense_mult (float).
    boss_state: dict = field(default_factory=dict)

    def is_alive(self) -> bool:
        return self.hp > 0


def _eligible_templates(depth: int) -> list:
    eligible = [t for t in MONSTER_TEMPLATES if t[7] <= depth]
    return eligible or [MONSTER_TEMPLATES[0]]


def _scaled_stats(hp: int, attack: int, defense: int, xp: int, gold: int, depth: int) -> tuple:
    scale = 1 + (depth - 1) * 0.22
    hp = round(hp * scale)
    attack = round(attack * scale)
    defense = round(defense * (1 + (depth - 1) * 0.12))
    xp = round(xp * scale)
    # Gold uses the soft-capped economy scale, not the uncapped combat
    # scale above - otherwise deep-floor gold rewards spiral out of control.
    gold = round(gold * C.gold_scale(depth))
    return hp, attack, defense, xp, gold


_BOSS_HP_MULT = 2.5
_BOSS_ATTACK_MULT = 1.4
_BOSS_DEFENSE_MULT = 1.3
_BOSS_XP_MULT = 3
_BOSS_GOLD_MULT = 3


def _boss_scaled_stats(hp: int, attack: int, defense: int, xp: int, gold: int) -> tuple:
    return (round(hp * _BOSS_HP_MULT), round(attack * _BOSS_ATTACK_MULT),
            round(defense * _BOSS_DEFENSE_MULT), round(xp * _BOSS_XP_MULT),
            round(gold * _BOSS_GOLD_MULT))


def _fresh_boss_state() -> dict:
    return {"phase": 1, "cooldowns": {}, "pending": None,
            "buff_turns_left": 0, "buff_attack_mult": 1.0, "buff_defense_mult": 1.0}


def generate_monster(depth: int, rng, x: int, y: int, force_boss: bool = False) -> Monster:
    eligible = _eligible_templates(depth)
    # Weight toward templates closer to (but not far above) current depth.
    weights = [1.0 / (1 + max(0, depth - t[7])) + 0.05 for t in eligible]
    name, glyph, hp, attack, defense, xp, gold, min_depth = rng.choices(eligible, weights=weights, k=1)[0]
    hp, attack, defense, xp, gold = _scaled_stats(hp, attack, defense, xp, gold, depth)

    boss_state = {}
    if force_boss:
        hp, attack, defense, xp, gold = _boss_scaled_stats(hp, attack, defense, xp, gold)
        boss_state = _fresh_boss_state()
        name = f"{name} Boss"
        glyph = glyph.upper()

    return Monster(x, y, name, glyph, hp, hp, attack, defense, xp, gold,
                   is_boss=force_boss, boss_state=boss_state)


def generate_boss_of(name: str, depth: int, x: int, y: int) -> Monster:
    """A specific named template at boss-tier scaling, independent of the
    weighted random roll generate_monster() normally uses for force_boss.
    Used by tests to exercise every boss kit deterministically."""
    template = next((t for t in MONSTER_TEMPLATES if t[0] == name), MONSTER_TEMPLATES[0])
    _, glyph, hp, attack, defense, xp, gold, _min_depth = template
    hp, attack, defense, xp, gold = _scaled_stats(hp, attack, defense, xp, gold, depth)
    hp, attack, defense, xp, gold = _boss_scaled_stats(hp, attack, defense, xp, gold)
    return Monster(x, y, f"{name} Boss", glyph.upper(), hp, hp, attack, defense, xp, gold,
                   is_boss=True, boss_state=_fresh_boss_state())


def generate_monster_of(name: str, depth: int, x: int, y: int) -> Monster:
    """A specific named template at this depth's normal (non-boss) scaling.
    Used for boss-summoned minions, which should be dangerous but not
    boss-tier - MONSTER_TEMPLATES lookup, not the weighted random roll."""
    template = next((t for t in MONSTER_TEMPLATES if t[0] == name), MONSTER_TEMPLATES[0])
    _, glyph, hp, attack, defense, xp, gold, _min_depth = template
    hp, attack, defense, xp, gold = _scaled_stats(hp, attack, defense, xp, gold, depth)
    return Monster(x, y, name, glyph, hp, hp, attack, defense, xp, gold, state="chasing")


def make_mimic(depth: int, x: int, y: int) -> Monster:
    """A chest that was never a chest. Not in MONSTER_TEMPLATES - mimics
    only ever hatch from opened chests, already awake and angry. They are
    treasure made flesh, so the gold reward runs rich."""
    scale = 1 + (depth - 1) * 0.22
    hp = round(14 * scale)
    attack = round(5 * scale)
    defense = round(2 * (1 + (depth - 1) * 0.12))
    xp = round(18 * scale)
    gold = round(22 * C.gold_scale(depth))
    return Monster(x, y, "Mimic", "m", hp, hp, attack, defense, xp, gold,
                   state="chasing")
