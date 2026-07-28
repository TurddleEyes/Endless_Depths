"""Depth-banded visual theme + a couple of hazard trap kinds, layered on
top of the M2 status-effect system (engine/status.py). A biome is a pure
function of depth alone - no rng, no GameState - so dungeon generation and
the web build derive the identical biome from depth with nothing to
thread through: depth is already part of every floor payload.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Biome:
    key: str                       # sprite-key suffix ("" = the default look)
    name: str                      # flavor name for the first-entry log line
    extra_trap_kinds: tuple = ()   # additional Trap.kind choices this biome mixes in


# (min_depth, Biome) - the LAST entry whose min_depth <= depth wins. Bands
# line up with BOSS_INTERVAL (10) so a new biome opens right after clearing
# the previous one's guardian - a fresh look immediately after every boss.
BIOMES = [
    (1, Biome(key="", name="the Catacombs")),
    (11, Biome(key="_caverns", name="the Flooded Caverns")),
    (21, Biome(key="_frozen", name="the Frozen Depths", extra_trap_kinds=("ice", "ice"))),
    (31, Biome(key="_volcanic", name="the Volcanic Depths", extra_trap_kinds=("burn", "burn"))),
    (41, Biome(key="_abyss", name="the Abyss")),
]


def biome_for(depth: int) -> Biome:
    result = BIOMES[0][1]
    for min_depth, biome in BIOMES:
        if depth < min_depth:
            break
        result = biome
    return result
