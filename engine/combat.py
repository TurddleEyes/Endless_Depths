"""Combat resolution between the player and monsters."""
from __future__ import annotations

CRIT_CHANCE = 0.1
CRIT_MULTIPLIER = 2.0


def resolve_attack(attacker_name: str, defender_name: str, attack: int, defense: int, rng,
                    crit_chance_bonus: float = 0.0) -> tuple:
    """Returns (damage, is_crit, message). crit_chance_bonus is gear-driven
    (M4 weapon affixes) - always 0 for monster attacks, since monsters
    don't carry items."""
    jitter = rng.randint(-1, 2)
    raw = attack - defense + jitter
    damage = max(1, raw)
    is_crit = rng.random() < (CRIT_CHANCE + crit_chance_bonus)
    if is_crit:
        damage = max(1, round(damage * CRIT_MULTIPLIER))
    if attacker_name == "You":
        verb = "critically hit" if is_crit else "hit"
    else:
        verb = "critically hits" if is_crit else "hits"
    message = f"{attacker_name} {verb} {defender_name} for {damage} damage."
    return damage, is_crit, message
