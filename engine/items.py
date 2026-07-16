"""Item definitions and procedural item generation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import constants as C

_next_id = [1]


def _new_id() -> int:
    _next_id[0] += 1
    return _next_id[0]


@dataclass
class Item:
    id: int
    name: str
    category: str  # weapon, armor, accessory, potion, scroll, gold, food
    glyph: str
    rarity: str
    value: int
    bonus_attack: int = 0
    bonus_defense: int = 0
    effect: Optional[str] = None  # heal, strength, teleport, enchant, cure
    magnitude: int = 0
    quantity: int = 1

    @property
    def color(self) -> str:
        return C.CATEGORY_COLORS.get(self.category, "#ffffff")

    def display_name(self) -> str:
        suffix = f" x{self.quantity}" if self.category in ("gold", "food") and self.quantity > 1 else ""
        return f"{self.name}{suffix}"

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @staticmethod
    def from_dict(data: dict) -> "Item":
        return Item(**data)


_WEAPON_NAMES = ["Dagger", "Shortsword", "Longsword", "Axe", "War Hammer", "Rapier", "Spear"]
_ARMOR_NAMES = ["Leather Armor", "Chainmail", "Plate Armor", "Studded Vest", "Scale Mail"]
_ACCESSORY_NAMES = ["Ring of Vigor", "Amulet of Warding", "Band of Fortitude", "Charm of Focus"]
_POTION_TYPES = [
    ("Potion of Healing", "heal", 10),
    ("Potion of Strength", "strength", 2),
    ("Potion of Cure", "cure", 0),
]
_SCROLL_TYPES = [
    ("Scroll of Enchantment", "enchant", 1),
    ("Scroll of Teleportation", "teleport", 0),
    ("Scroll of Fireball", "fireball", 8),
]

_CATEGORY_WEIGHTS = [
    ("weapon", 20),
    ("armor", 18),
    ("accessory", 8),
    ("potion", 28),
    ("scroll", 14),
    ("gold", 12),
]


def _pick_rarity(rng, depth: int) -> tuple:
    # Higher depth nudges the odds toward better rarities without a hard cap.
    weights = []
    for name, mult, weight, color in C.RARITIES:
        boost = 1.0 + depth * 0.06 * C.RARITIES.index((name, mult, weight, color))
        weights.append(weight * boost)
    return rng.choices(C.RARITIES, weights=weights, k=1)[0]


def generate_item(depth: int, rng, quality_bonus: float = 1.0) -> Item:
    depth = max(1, depth)
    category = rng.choices(
        [c for c, _ in _CATEGORY_WEIGHTS],
        weights=[w for _, w in _CATEGORY_WEIGHTS],
        k=1,
    )[0]
    rarity_name, mult, _weight, color = _pick_rarity(rng, depth)
    mult *= quality_bonus
    # Value/gold use a soft-capped scale (see constants.gold_scale) so
    # currency doesn't spiral into absurd numbers at extreme depth, even
    # though combat-stat bonuses below keep scaling linearly for challenge.
    scale = C.gold_scale(depth)

    if category == "weapon":
        name = rng.choice(_WEAPON_NAMES)
        bonus_attack = max(1, round((2 + depth * 0.8) * mult))
        value = round(10 * scale * mult)
        return Item(_new_id(), f"{rarity_name.title()} {name}", category, "/", rarity_name,
                     value, bonus_attack=bonus_attack)

    if category == "armor":
        name = rng.choice(_ARMOR_NAMES)
        bonus_defense = max(1, round((1 + depth * 0.6) * mult))
        value = round(9 * scale * mult)
        return Item(_new_id(), f"{rarity_name.title()} {name}", category, "[", rarity_name,
                     value, bonus_defense=bonus_defense)

    if category == "accessory":
        name = rng.choice(_ACCESSORY_NAMES)
        bonus_attack = round(rng.choice([0, 1]) * (1 + depth * 0.2) * mult)
        bonus_defense = round(rng.choice([0, 1]) * (1 + depth * 0.2) * mult)
        bonus_attack = max(bonus_attack, 0)
        bonus_defense = max(bonus_defense, 0)
        if bonus_attack == 0 and bonus_defense == 0:
            bonus_attack = 1
        value = round(12 * scale * mult)
        return Item(_new_id(), f"{rarity_name.title()} {name}", category, "=", rarity_name,
                     value, bonus_attack=bonus_attack, bonus_defense=bonus_defense)

    if category == "potion":
        name, effect, base_mag = rng.choice(_POTION_TYPES)
        magnitude = round(base_mag * (1 + depth * 0.15) * mult) if base_mag else 0
        value = round(6 * scale * mult)
        return Item(_new_id(), name, category, "!", rarity_name, value, effect=effect, magnitude=magnitude)

    if category == "scroll":
        name, effect, base_mag = rng.choice(_SCROLL_TYPES)
        value = round(8 * scale * mult)
        magnitude = round(base_mag * (1 + depth * 0.15) * mult) if effect == "fireball" else base_mag
        return Item(_new_id(), name, category, "?", rarity_name, value, effect=effect, magnitude=magnitude)

    # Gold pile - deliberately not multiplied by rarity: currency isn't
    # "legendary", it's just an amount, and stacking the rarity multiplier
    # on top of the depth scale was a big part of the runaway-gold problem.
    amount = max(1, round(rng.randint(5, 15) * scale))
    return Item(_new_id(), "Gold", "gold", "*", rarity_name, amount, quantity=amount)


def make_cure_potion(depth: int) -> Item:
    """Guaranteed shop staple - poison is permanent until cured, so every
    merchant carries one."""
    value = round(6 * C.gold_scale(depth))
    return Item(_new_id(), "Potion of Cure", "potion", "!", "common", value,
                 effect="cure", magnitude=0)


def use_item(player, item: Item) -> str:
    """Apply a consumable's effect to the player. Returns a log message."""
    if item.category == "potion":
        if item.effect == "heal":
            healed = min(item.magnitude, player.max_hp - player.hp)
            player.hp += healed
            return f"You drink the {item.name} and recover {healed} HP."
        if item.effect == "strength":
            player.base_attack += item.magnitude
            return f"You drink the {item.name} and feel stronger (+{item.magnitude} attack)."
        if item.effect == "cure":
            player.status_effects.clear()
            return f"You drink the {item.name} and feel cleansed."
    if item.category == "scroll":
        if item.effect == "enchant":
            target = player.equipped_weapon or player.equipped_armor
            if target:
                target.bonus_attack += item.magnitude if target.category == "weapon" else 0
                target.bonus_defense += item.magnitude if target.category == "armor" else 0
                return f"Your {target.name} glows brighter!"
            return "The scroll fizzles - you have nothing equipped to enchant."
        if item.effect == "teleport":
            return "__TELEPORT__"
        if item.effect == "fireball":
            return "__FIREBALL__"
    return f"Nothing happens."
