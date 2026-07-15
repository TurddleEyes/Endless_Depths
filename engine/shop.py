"""Shop inventory generation and buy/sell transactions."""
from __future__ import annotations

from .items import Item, generate_item

SELL_RATIO = 0.5
SHOP_QUALITY_BONUS = 1.15


def generate_shop_inventory(depth: int, rng, n_items: int = 6) -> list:
    return [generate_item(depth, rng, quality_bonus=SHOP_QUALITY_BONUS) for _ in range(n_items)]


def buy(player, shop_stock: list, item: Item) -> tuple:
    """Returns (success, message)."""
    if item not in shop_stock:
        return False, "That item is no longer available."
    if player.gold < item.value:
        return False, f"You can't afford the {item.name} ({item.value} gold)."
    player.gold -= item.value
    shop_stock.remove(item)
    player.inventory.append(item)
    return True, f"You bought {item.name} for {item.value} gold."


def sell(player, item: Item) -> tuple:
    """Returns (success, message)."""
    if item not in player.inventory:
        return False, "You don't have that item."
    price = max(1, round(item.value * SELL_RATIO))
    player.gold += price
    player.inventory.remove(item)
    if player.equipped_weapon is item:
        player.equipped_weapon = None
    if player.equipped_armor is item:
        player.equipped_armor = None
    if player.equipped_accessory is item:
        player.equipped_accessory = None
    return True, f"You sold {item.name} for {price} gold."
