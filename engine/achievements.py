"""Achievement definitions - milestone checks over a finished run's stats.
Pure data + pure check functions; front-ends own the actual persistence
(engine/save.py's achievements.json on desktop, localStorage on web) and UI.

A run-summary `ctx` dict is whatever the front-end can readily put
together at run-end - see save.py's record_run_history call sites for the
shape both front-ends already build for run history, which this reuses:
depth_reached, level, gold, kills, mode, finished, is_daily, plus two
GameState-tracked extras (breeds_seen, boss_kills).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class Achievement:
    id: str
    name: str
    description: str
    check: Callable[[dict], bool]


ACHIEVEMENTS = [
    Achievement("first_blood", "First Blood", "Defeat your first monster.",
                lambda ctx: ctx.get("kills", 0) >= 1),
    Achievement("delver", "Delver", "Reach floor 10.",
                lambda ctx: ctx.get("depth_reached", 0) >= 10),
    Achievement("deep_delver", "Deep Delver", "Reach floor 25.",
                lambda ctx: ctx.get("depth_reached", 0) >= 25),
    Achievement("into_the_abyss", "Into the Abyss", "Reach floor 41.",
                lambda ctx: ctx.get("depth_reached", 0) >= 41),
    Achievement("conqueror", "Conqueror", "Escape the depths for good in normal mode.",
                lambda ctx: ctx.get("finished", False) and ctx.get("mode") == "normal"),
    Achievement("speed_demon", "Speed Demon", "Finish a speedrun.",
                lambda ctx: ctx.get("finished", False) and ctx.get("mode") == "speedrun"),
    Achievement("boss_slayer", "Boss Slayer", "Defeat a boss.",
                lambda ctx: ctx.get("boss_kills", 0) >= 1),
    Achievement("well_traveled", "Well Traveled", "See 10 different monster breeds.",
                lambda ctx: ctx.get("breeds_seen", 0) >= 10),
    Achievement("menagerie", "Menagerie", "See every monster breed.",
                lambda ctx: ctx.get("breeds_seen", 0) >= 26),
    Achievement("rich", "Rich", "Collect 1000 gold in a single run.",
                lambda ctx: ctx.get("gold", 0) >= 1000),
    Achievement("veteran", "Veteran", "Reach level 10.",
                lambda ctx: ctx.get("level", 0) >= 10),
    Achievement("daily_doer", "Daily Doer", "Complete a Daily Challenge.",
                lambda ctx: ctx.get("is_daily", False)),
]

ACHIEVEMENTS_BY_ID = {a.id: a for a in ACHIEVEMENTS}


def check_unlocks(ctx: dict, already_unlocked) -> list:
    """Returns the Achievement objects `ctx` newly earns - skips anything
    whose id is already in `already_unlocked` (a set or dict of ids)."""
    return [a for a in ACHIEVEMENTS if a.id not in already_unlocked and a.check(ctx)]
