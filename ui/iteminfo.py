"""Human-readable item stat descriptions for the inventory and shop UIs."""
from __future__ import annotations

from engine import constants as C
from engine.shop import SELL_RATIO

RARITY_COLORS = {name: color for name, _mult, _weight, color in C.RARITIES}


def sell_price(item) -> int:
    return max(1, round(item.value * SELL_RATIO))


def _diff_text(diff: int) -> str:
    if diff > 0:
        return f"Better than equipped by {diff}."
    if diff < 0:
        return f"Worse than equipped by {abs(diff)}."
    return "Same as equipped."


def describe_item(item, player) -> list:
    """Stat lines for the details panel (title/name is rendered separately)."""
    lines = [f"{item.rarity.title()} {item.category}"]

    if item.category == "weapon":
        lines.append(f"Attack: +{item.bonus_attack}")
        eq = player.equipped_weapon
        if eq is item:
            lines.append("Currently equipped.")
        elif eq is None:
            lines.append("You have no weapon equipped.")
        else:
            lines.append(f"Equipped: {eq.name} (+{eq.bonus_attack})")
            lines.append(_diff_text(item.bonus_attack - eq.bonus_attack))

    elif item.category == "armor":
        lines.append(f"Defense: +{item.bonus_defense}")
        eq = player.equipped_armor
        if eq is item:
            lines.append("Currently equipped.")
        elif eq is None:
            lines.append("You have no armor equipped.")
        else:
            lines.append(f"Equipped: {eq.name} (+{eq.bonus_defense})")
            lines.append(_diff_text(item.bonus_defense - eq.bonus_defense))

    elif item.category == "accessory":
        parts = []
        if item.bonus_attack:
            parts.append(f"Attack +{item.bonus_attack}")
        if item.bonus_defense:
            parts.append(f"Defense +{item.bonus_defense}")
        lines.append(", ".join(parts) if parts else "No stat bonuses")
        eq = player.equipped_accessory
        if eq is item:
            lines.append("Currently equipped.")
        elif eq is None:
            lines.append("You have no accessory equipped.")
        else:
            lines.append(f"Equipped: {eq.name} (+{eq.bonus_attack}/+{eq.bonus_defense})")
            new_total = item.bonus_attack + item.bonus_defense
            cur_total = eq.bonus_attack + eq.bonus_defense
            lines.append(_diff_text(new_total - cur_total))

    elif item.category == "potion":
        if item.effect == "heal":
            lines.append(f"Restores up to {item.magnitude} HP.")
        elif item.effect == "strength":
            lines.append(f"Permanently raises attack by {item.magnitude}.")
        elif item.effect == "cure":
            lines.append("Cures poison.")
        lines.append("One use. Drinking takes a turn.")

    elif item.category == "scroll":
        if item.effect == "enchant":
            lines.append("Makes your equipped weapon")
            lines.append("or armor permanently stronger.")
        elif item.effect == "teleport":
            lines.append("Warps you somewhere random")
            lines.append("on this floor.")
        elif item.effect == "fireball":
            lines.append(f"Burns every enemy you can see")
            lines.append(f"for {item.magnitude} damage.")
        lines.append("One use. Reading takes a turn.")

    elif item.category == "gold":
        lines.append(f"{item.quantity} gold pieces.")

    return lines
