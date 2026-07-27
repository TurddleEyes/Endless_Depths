"""Item definitions and procedural item generation."""
from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from . import constants as C
from . import status as status_module

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
    # -- Gear affixes (weapon/armor/accessory only) -----------------------
    # "" / 0.0 means "no affix". All rolled at generation time through the
    # passed rng (see _roll_offense_affix/_roll_defense_affix below), so
    # they're replay-safe like everything else. Pre-M4 saves round-trip
    # through from_dict with every affix at its default, unaffected.
    lifesteal_pct: float = 0.0       # weapon: % of damage dealt healed back
    crit_chance_bonus: float = 0.0   # weapon: added to the global crit chance
    on_hit_status: str = ""          # weapon: "" | poison | burn | bleed - applied to the MONSTER
    on_hit_chance: float = 0.0
    resist_status: str = ""          # armor/accessory: "" | poison | burn | bleed
    resist_pct: float = 0.0          # armor/accessory: % chance to resist that status entirely
    set_name: str = ""               # "" = not part of a set; else a GEAR_SETS key
    # -- Beatitude (weapon/armor/accessory only) --------------------------
    # Hidden until the item is actually EQUIPPED (buc_known flips true then -
    # see world.py's equip_item). Blessed/cursed nudge the item's own base
    # bonus by +-1 on top of everything above. A cursed, EQUIPPED item can't
    # be unequipped/dropped until a Scroll of Remove Curse lifts it.
    buc: str = "uncursed"             # "blessed" | "uncursed" | "cursed"
    buc_known: bool = False
    # -- Found pages (category == "lore" only) ----------------------------
    # The engine/lorepages.py id to look up on pickup - never shown/sorted/
    # equipped like a normal item; _pickup_at() consumes it straight into
    # GameState.pages_found instead of the inventory.
    lore_id: str = ""

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
    ("Scroll of Remove Curse", "remove_curse", 0),
]

_CATEGORY_WEIGHTS = [
    ("weapon", 20),
    ("armor", 18),
    ("accessory", 8),
    ("potion", 28),
    ("scroll", 14),
    ("gold", 12),
]

# -- Gear affixes and sets --------------------------------------------------
# Higher rarity = more likely to roll ANY affix at all; common items stay
# plain. A set roll is checked first and, if it hits, REPLACES the item's
# name with the set's own named piece instead of an affix - a set item is
# special because of what it IS, not an extra prefix bolted onto a random
# roll, so set and per-item affixes never both land on the same item.
_AFFIX_CHANCE = {"common": 0.0, "uncommon": 0.06, "rare": 0.15, "epic": 0.30, "legendary": 0.55}
_SET_CHANCE = {"common": 0.0, "uncommon": 0.0, "rare": 0.05, "epic": 0.12, "legendary": 0.25}

_ON_HIT_PREFIX = {"poison": "Venomous", "burn": "Flaming", "bleed": "Serrated"}
_RESIST_PREFIX = {"poison": "Warded", "burn": "Fireproof", "bleed": "Reinforced"}

# Only 3 equip slots exist (weapon/armor/accessory), so "2-piece"/"3-piece"
# (not the usual 2/4-piece) are the only tiers that make sense here. Each
# tier's mult keys are read by set_bonus_mult() below and applied on top of
# Player.attack_power/defense_power (see engine/entities.py) - a flat
# multiplier stacking with individual item stats and status buffs, not a
# replacement for them.
GEAR_SETS = {
    "Berserker": {
        "weapon": "Berserker's Axe", "armor": "Berserker's Hide", "accessory": "Berserker's Fang",
        2: {"attack_mult": 1.10, "desc": "+10% Attack"},
        3: {"attack_mult": 1.25, "desc": "+25% Attack"},
    },
    "Warden": {
        "weapon": "Warden's Blade", "armor": "Warden's Bulwark", "accessory": "Warden's Seal",
        2: {"defense_mult": 1.10, "desc": "+10% Defense"},
        3: {"defense_mult": 1.25, "desc": "+25% Defense"},
    },
    "Shadow": {
        "weapon": "Shadow Dagger", "armor": "Shadow Wrap", "accessory": "Shadow Charm",
        2: {"attack_mult": 1.05, "defense_mult": 1.05, "desc": "+5% Attack, +5% Defense"},
        3: {"attack_mult": 1.15, "defense_mult": 1.15, "desc": "+15% Attack, +15% Defense"},
    },
}


def set_bonus_mult(player, kind: str) -> float:
    """Combined attack/defense multiplier from equipped gear sharing a
    GEAR_SETS name - "attack" or "defense". Duck-typed on `player` (just
    needs the three equipped_* attributes), so this works for the real
    Player without entities.py importing anything back from here."""
    names = [eq.set_name for eq in
             (player.equipped_weapon, player.equipped_armor, player.equipped_accessory)
             if eq and eq.set_name]
    if not names:
        return 1.0
    set_name, count = Counter(names).most_common(1)[0]
    tiers = GEAR_SETS.get(set_name, {})
    mult = 1.0
    for tier in (2, 3):
        if count >= tier and tier in tiers:
            mult = tiers[tier].get(f"{kind}_mult", mult)
    return mult


def _roll_offense_affix(item, rng) -> None:
    kind = rng.choice(["lifesteal", "crit", "on_hit"])
    if kind == "lifesteal":
        item.lifesteal_pct = round(rng.uniform(0.08, 0.18), 2)
        prefix = "Vampiric"
    elif kind == "crit":
        item.crit_chance_bonus = round(rng.uniform(0.08, 0.18), 2)
        prefix = "Keen"
    else:
        item.on_hit_status = rng.choice(["poison", "burn", "bleed"])
        item.on_hit_chance = round(rng.uniform(0.12, 0.22), 2)
        prefix = _ON_HIT_PREFIX[item.on_hit_status]
    item.name = f"{prefix} {item.name}"


def _roll_defense_affix(item, rng) -> None:
    item.resist_status = rng.choice(["poison", "burn", "bleed"])
    item.resist_pct = round(rng.uniform(0.25, 0.45), 2)
    item.name = f"{_RESIST_PREFIX[item.resist_status]} {item.name}"


def _maybe_tag_set(item, category: str, rarity_name: str, rng) -> bool:
    """Returns True if `item` became a set piece (name replaced, set_name
    set) - callers should skip rolling a per-item affix when this happens."""
    if rng.random() >= _SET_CHANCE.get(rarity_name, 0.0):
        return False
    set_name = rng.choice(list(GEAR_SETS))
    item.name = GEAR_SETS[set_name][category]
    item.set_name = set_name
    return True


# -- Beatitude ---------------------------------------------------------
_BUC_WEIGHTS = [("cursed", 12), ("uncursed", 76), ("blessed", 12)]


def _roll_buc(rng) -> str:
    return rng.choices([b for b, _w in _BUC_WEIGHTS], weights=[w for _b, w in _BUC_WEIGHTS], k=1)[0]


def _apply_buc(item, buc: str, stat_names: tuple) -> None:
    """Nudges the named bonus_* fields by +-1 for blessed/cursed - applied
    on top of the item's base roll, before affixes/sets are considered."""
    if buc == "blessed":
        for stat in stat_names:
            setattr(item, stat, getattr(item, stat) + 1)
    elif buc == "cursed":
        for stat in stat_names:
            setattr(item, stat, max(0, getattr(item, stat) - 1))


# -- Item identification -------------------------------------------------
# Potions/scrolls show a cosmetic per-run alias until identified (by using
# one, or any of the same effect elsewhere - see world.py's use_item/
# resolved_name). Equipment is never hidden by name; only its beatitude is
# (see buc_known above) - two independent "don't fully trust what you
# picked up" mechanics.
_POTION_APPEARANCES = ["Fizzy", "Murky", "Sparkling", "Bitter", "Milky", "Smoky"]
_SCROLL_RUNEWORDS = ["Xoreth", "Vaelun", "Krazak", "Mirthos", "Zhul", "Quennar"]


def build_item_identity(seed: int) -> dict:
    """Per-run {"potion:heal": "Murky Potion", ...} shuffle. Uses its OWN
    rng derived from the run seed - NEVER GameState.rng - so identification
    is purely cosmetic and never shifts the gameplay rng stream."""
    r = random.Random(seed * 2654435761 + 0x9E3779B9)
    potion_effects = [effect for _name, effect, _mag in _POTION_TYPES]
    scroll_effects = [effect for _name, effect, _mag in _SCROLL_TYPES]
    potion_names = r.sample(_POTION_APPEARANCES, len(potion_effects))
    scroll_names = r.sample(_SCROLL_RUNEWORDS, len(scroll_effects))
    identity = {f"potion:{e}": f"{n} Potion" for e, n in zip(potion_effects, potion_names)}
    identity.update({f"scroll:{e}": f"Scroll of {n}" for e, n in zip(scroll_effects, scroll_names)})
    return identity


def identity_key(item) -> str:
    return f"{item.category}:{item.effect}"


def resolved_name(item, item_identity: dict, identified: set) -> str:
    """The name to show for `item` - its true display name, unless it's an
    unidentified potion/scroll, in which case the per-run cosmetic alias.
    Equipment/gold/keys are never hidden by name."""
    if item.category not in ("potion", "scroll"):
        return item.display_name()
    key = identity_key(item)
    if key in identified:
        return item.display_name()
    return item_identity.get(key, item.display_name())


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
        item = Item(_new_id(), f"{rarity_name.title()} {name}", category, "/", rarity_name,
                     value, bonus_attack=bonus_attack, buc=_roll_buc(rng))
        _apply_buc(item, item.buc, ("bonus_attack",))
        if not _maybe_tag_set(item, "weapon", rarity_name, rng):
            if rng.random() < _AFFIX_CHANCE.get(rarity_name, 0.0):
                _roll_offense_affix(item, rng)
        return item

    if category == "armor":
        name = rng.choice(_ARMOR_NAMES)
        bonus_defense = max(1, round((1 + depth * 0.6) * mult))
        value = round(9 * scale * mult)
        item = Item(_new_id(), f"{rarity_name.title()} {name}", category, "[", rarity_name,
                     value, bonus_defense=bonus_defense, buc=_roll_buc(rng))
        _apply_buc(item, item.buc, ("bonus_defense",))
        if not _maybe_tag_set(item, "armor", rarity_name, rng):
            if rng.random() < _AFFIX_CHANCE.get(rarity_name, 0.0):
                _roll_defense_affix(item, rng)
        return item

    if category == "accessory":
        name = rng.choice(_ACCESSORY_NAMES)
        bonus_attack = round(rng.choice([0, 1]) * (1 + depth * 0.2) * mult)
        bonus_defense = round(rng.choice([0, 1]) * (1 + depth * 0.2) * mult)
        bonus_attack = max(bonus_attack, 0)
        bonus_defense = max(bonus_defense, 0)
        if bonus_attack == 0 and bonus_defense == 0:
            bonus_attack = 1
        value = round(12 * scale * mult)
        item = Item(_new_id(), f"{rarity_name.title()} {name}", category, "=", rarity_name,
                     value, bonus_attack=bonus_attack, bonus_defense=bonus_defense, buc=_roll_buc(rng))
        _apply_buc(item, item.buc, ("bonus_attack", "bonus_defense"))
        if not _maybe_tag_set(item, "accessory", rarity_name, rng):
            if rng.random() < _AFFIX_CHANCE.get(rarity_name, 0.0):
                if rng.random() < 0.5:
                    _roll_offense_affix(item, rng)
                else:
                    _roll_defense_affix(item, rng)
        return item

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


def make_key(name: str) -> Item:
    """Quest keys: the Iron Key opens locked chests, the Rune Key opens a
    Hidden Key puzzle door. Worthless to merchants - their value is the
    lock they open."""
    return Item(_new_id(), name, "key", "~", "uncommon", 0)


def make_lore_page(page) -> Item:
    """A found-page pickup (engine/lorepages.py:LorePage) - consumed
    straight into GameState.pages_found on pickup, never carried in the
    inventory or sold, so rarity/value are nominal."""
    return Item(_new_id(), f"Torn Page ({page.author})", "lore", "?",
                "common", 0, lore_id=page.id)


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
            # Cure washes away sicknesses (poison/burn/bleed/slow/freeze),
            # not the player's own timed buffs - it's a cleanse, not a purge.
            player.status_effects = [
                e for e in player.status_effects
                if e.get("type") not in status_module.AILMENT_TYPES
            ]
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
        if item.effect == "remove_curse":
            cursed = [eq for eq in (player.equipped_weapon, player.equipped_armor, player.equipped_accessory)
                      if eq and eq.buc == "cursed"]
            for eq in cursed:
                eq.buc = "uncursed"
            if cursed:
                names = ", ".join(eq.name for eq in cursed)
                return f"A soft light washes over you - the curse lifts from your {names}!"
            return "You feel a faint warmth, but nothing on you seems cursed right now."
    return f"Nothing happens."
