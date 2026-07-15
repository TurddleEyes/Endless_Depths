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

    def is_alive(self) -> bool:
        return self.hp > 0


def _eligible_templates(depth: int) -> list:
    eligible = [t for t in MONSTER_TEMPLATES if t[7] <= depth]
    return eligible or [MONSTER_TEMPLATES[0]]


def generate_monster(depth: int, rng, x: int, y: int, force_boss: bool = False) -> Monster:
    eligible = _eligible_templates(depth)
    # Weight toward templates closer to (but not far above) current depth.
    weights = [1.0 / (1 + max(0, depth - t[7])) + 0.05 for t in eligible]
    name, glyph, hp, attack, defense, xp, gold, min_depth = rng.choices(eligible, weights=weights, k=1)[0]

    scale = 1 + (depth - 1) * 0.22
    hp = round(hp * scale)
    attack = round(attack * scale)
    defense = round(defense * (1 + (depth - 1) * 0.12))
    xp = round(xp * scale)
    gold = round(gold * scale)

    if force_boss:
        hp = round(hp * 2.5)
        attack = round(attack * 1.4)
        defense = round(defense * 1.3)
        xp = round(xp * 3)
        gold = round(gold * 3)
        name = f"{name} Boss"
        glyph = glyph.upper()

    return Monster(x, y, name, glyph, hp, hp, attack, defense, xp, gold, is_boss=force_boss)
