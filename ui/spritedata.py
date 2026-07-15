"""Pixel-art sprite data: 16x16 grids of palette characters ('.' = transparent).

Pure data + helpers, no tkinter - shared by the desktop renderer
(ui/sprites.py) and the browser build (web/webbridge.py).
"""
from __future__ import annotations

SPRITE_PX = 16
OUTLINE = "#14141a"
MISSING = "#ff00ff"  # loud fallback for any palette-char typo

# ----------------------------------------------------------------------
# Shared body shapes (recolored per creature via palettes)
# ----------------------------------------------------------------------
BEAST = [
    "................",
    "................",
    "................",
    "................",
    "................",
    "...oo......oo...",
    "..oaao....oao...",
    ".oaaaaooooaao...",
    ".oaeaaaaaaaao...",
    "oaaaaaaaaaao.bb.",
    "oaaaaaaaaaaobb..",
    ".oaaaaaaaaao....",
    "..oaaooaaoo.....",
    "..obo..obo......",
    "..oo....oo......",
    "................",
]

SPIDER = [
    "................",
    "................",
    "..o..........o..",
    "...o..oooo..o...",
    "....ooaaaaoo....",
    "..oo.oaaaao.oo..",
    ".o..oaeaaeao..o.",
    ".o.oaaaaaaaao.o.",
    "..ooaaaaaaaaoo..",
    ".o..oaaaaaao..o.",
    ".o...oaaaao...o.",
    "..o...oooo...o..",
    "...o........o...",
    "................",
    "................",
    "................",
]

HUMANOID_SMALL = [
    "................",
    "................",
    "....oooo........",
    "...oaaaao.......",
    "...oaeaeo.......",
    "...oaaaao.......",
    "....oaao........",
    "...ooaaoo.......",
    "..oaoaaoao......",
    "..o.oaao.o......",
    "....oaao........",
    "....oaao........",
    "....o..o........",
    "...oo..oo.......",
    "................",
    "................",
]

HUMANOID_BIG = [
    "................",
    "................",
    "...oooooo.......",
    "..oaaaaaao......",
    "..oaeaaeao......",
    "..oaaaaaao......",
    "..oaaffaao......",
    "...oaaaao.......",
    "..ooaaaaoo......",
    ".oaoaaaaoao.....",
    ".oa.oaao.ao.....",
    ".oo.oaao.oo.....",
    "....oaao........",
    "....o..o........",
    "...oo..oo.......",
    "................",
]

GHOST = [
    "................",
    ".....oooo.......",
    "....oaaaao......",
    "...oaaaaaao.....",
    "...oaeaaeao.....",
    "...oaaaaaao.....",
    "...oaabbaao.....",
    "...oaaaaaao.....",
    "...oaaaaaao.....",
    "...oaaaaaao.....",
    "...oaoaaoao.....",
    "...o..oo..o.....",
    "................",
    "................",
    "................",
    "................",
]

SKELETON = [
    "................",
    "....oooo........",
    "...oaaaao.......",
    "...oeaaeo.......",
    "...oaaaao.......",
    "....obbo........",
    "...oabbao.......",
    "...oabbao.......",
    "...oabbao.......",
    "....oaao........",
    "....o..o........",
    "....o..o........",
    "...oo..oo.......",
    "................",
    "................",
    "................",
]

WYVERN = [
    "................",
    "................",
    "..oo........oo..",
    "..obo......obo..",
    "..obbo....obbo..",
    "...obbo..obbo...",
    "....obboobbo....",
    ".....oaaaao.....",
    ".....oaeaeo.....",
    ".....oaaaao.....",
    "......oaao......",
    ".......oao......",
    "........o.......",
    "................",
    "................",
    "................",
]

MAGE = [
    "................",
    ".....oooo.......",
    "....oaaaao......",
    "....oebbeo......",
    "....obbbbo......",
    "...oaaaaaao.....",
    "...oaaccaao.....",
    "..oaaaaaaaao....",
    "..oaaaaaaaao....",
    "..oaaaaaaaao....",
    "..oaaaaaaaao....",
    "..oaaaaaaaao....",
    "...oooooooo.....",
    "................",
    "................",
    "................",
]

# The hero is composited from layers: base body + held weapon overlay +
# accessory overlay, with palette swaps for armor / poison / weapon rarity.
HERO_BASE = [
    "................",
    "....oooo........",
    "...ohhhho.......",
    "...offffo.......",
    "...ofefeo.......",
    "...offffo.......",
    "....offo........",
    "..otttttto......",
    "..otttttto......",
    "..otttttto......",
    "...obbbbo.......",
    "...ob..bo.......",
    "...oo..oo.......",
    "................",
    "................",
    "................",
]

HELD_SWORD = [
    "................",
    "................",
    "............w...",
    "............s...",
    "............s...",
    "............s...",
    "............s...",
    "............s...",
    "...........ggg..",
    "............m...",
    "............m...",
    "................",
    "................",
    "................",
    "................",
    "................",
]

HELD_DAGGER = [
    "................",
    "................",
    "................",
    "................",
    "................",
    "............w...",
    "............s...",
    "............s...",
    "............g...",
    "............m...",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
]

HELD_AXE = [
    "................",
    "................",
    "................",
    "............mss.",
    "............msw.",
    "............ms..",
    "............m...",
    "............m...",
    "............m...",
    "............m...",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
]

HELD_HAMMER = [
    "................",
    "................",
    "................",
    "...........ssss.",
    "...........ssss.",
    "............m...",
    "............m...",
    "............m...",
    "............m...",
    "............m...",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
]

HELD_SPEAR = [
    "................",
    "............w...",
    "............m...",
    "............m...",
    "............m...",
    "............m...",
    "............m...",
    "............m...",
    "............m...",
    "............m...",
    "............m...",
    "............m...",
    "................",
    "................",
    "................",
    "................",
]

ACCESSORY_OVERLAY = [
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    ".....yy.........",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
]

HELD_WEAPONS = {
    "dagger": HELD_DAGGER,
    "sword": HELD_SWORD,
    "axe": HELD_AXE,
    "hammer": HELD_HAMMER,
    "spear": HELD_SPEAR,
}

PLAYER_PALETTE = {
    "o": OUTLINE, "h": "#7a4a22", "f": "#eab984", "e": "#20242c",
    "t": "#3868c8", "b": "#28304a", "w": "#f0f4fa",
    "s": "#c8d0dc", "g": "#caa53c", "m": "#6a4a2a", "y": "#f2c94c",
}

ARMOR_TUNIC_COLORS = {
    "none": "#3868c8",     # plain blue tunic
    "leather": "#8a5a32",
    "chain": "#8a94a4",
    "plate": "#b8c2d2",
}

BLADE_RARITY_COLORS = {
    "common": "#c8d0dc",
    "uncommon": "#3ecf4a",
    "rare": "#3ea1cf",
    "epic": "#b25ce0",
    "legendary": "#e0a83a",
}

POISONED_SKIN = "#9ec089"


def _compose(base, *overlays):
    """Merge overlay grids onto a base grid; non-'.' overlay pixels win."""
    rows = [list((base[i] if i < len(base) else "")[:SPRITE_PX].ljust(SPRITE_PX, "."))
            for i in range(SPRITE_PX)]
    for overlay in overlays:
        if not overlay:
            continue
        for y in range(min(SPRITE_PX, len(overlay))):
            row = overlay[y]
            for x in range(min(SPRITE_PX, len(row))):
                if row[x] != ".":
                    rows[y][x] = row[x]
    return ["".join(r) for r in rows]


def hero_grid_and_palette(weapon="sword", armor="none", accessory=False,
                           poisoned=False, weapon_rarity="common"):
    """Pure-data hero variant (no tkinter needed) - grid + palette."""
    overlays = []
    if weapon != "none":
        overlays.append(HELD_WEAPONS.get(weapon, HELD_SWORD))
    if accessory:
        overlays.append(ACCESSORY_OVERLAY)
    grid = _compose(HERO_BASE, *overlays)
    palette = dict(PLAYER_PALETTE)
    palette["t"] = ARMOR_TUNIC_COLORS.get(armor, ARMOR_TUNIC_COLORS["none"])
    palette["s"] = BLADE_RARITY_COLORS.get(weapon_rarity, BLADE_RARITY_COLORS["common"])
    if poisoned:
        palette["f"] = POISONED_SKIN
    return grid, palette


PLAYER = _compose(HERO_BASE, HELD_SWORD)

SHOPKEEPER = [
    "................",
    "................",
    "....oooooo......",
    "...ohhhhhho.....",
    "..oooooooooo....",
    "...offffffo.....",
    "...ofeffeoo.....",
    "...offffffo.....",
    "..occcccccco....",
    "..occcccccco....",
    "..occggggcco....",
    "..occcccccco....",
    "...occcccco.....",
    "...obo..obo.....",
    "................",
    "................",
]

CROWN = [
    "...g...gg...g...",
    "...g..g..g..g...",
    "...gggggggggg...",
    "...ggeggggegg...",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
]

# ----------------------------------------------------------------------
# Item sprites
# ----------------------------------------------------------------------
SWORD = [
    "................",
    "................",
    ".......ow.......",
    ".......ows......",
    ".......ows......",
    ".......ows......",
    ".......ows......",
    ".......ows......",
    ".......ows......",
    ".....ogggggo....",
    ".......omo......",
    ".......omo......",
    "......ommmo.....",
    ".......oo.......",
    "................",
    "................",
]

ARMOR = [
    "................",
    "................",
    "................",
    "................",
    "..ooo......ooo..",
    "..oooooooooooo..",
    ".oaaaaabbaaaaao.",
    ".oaaaaabbaaaaao.",
    "..oaaaabbaaaao..",
    "..oaaaaaaaaaao..",
    "...oaaaaaaaao...",
    "...oaaggaaaao...",
    "....oaaaaaao....",
    ".....oooooo.....",
    "................",
    "................",
]

RING = [
    "................",
    "................",
    "................",
    "................",
    "......eeee......",
    ".....oeeeeo.....",
    "....og....go....",
    "....og....go....",
    "....og....go....",
    ".....oggggo.....",
    "......oooo......",
    "................",
    "................",
    "................",
    "................",
    "................",
]

POTION = [
    "................",
    "................",
    "................",
    "......oko.......",
    "......oko.......",
    ".....oaaao......",
    "....oalllao.....",
    "...oalllllao....",
    "...oalllllao....",
    "...oalllllao....",
    "....oalllao.....",
    ".....ooooo......",
    "................",
    "................",
    "................",
    "................",
]

SCROLL = [
    "................",
    "................",
    "................",
    "................",
    "................",
    "..oooooooooooo..",
    ".obwwwwwwwwwwbo.",
    ".obwtwtwtwtwwbo.",
    ".obwwwwwwwwwwbo.",
    ".obwtwtwtwwwwbo.",
    ".obwwwwwwwwwwbo.",
    "..oooooooooooo..",
    "................",
    "................",
    "................",
    "................",
]

GOLD = [
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "......oooo......",
    ".....oggddo.....",
    ".....oggddo.....",
    "..oooo.oo.oooo..",
    ".oggddo..oggddo.",
    ".oggddo..oggddo.",
    "..oooo....oooo..",
    "................",
    "................",
    "................",
]

# ----------------------------------------------------------------------
# Traps (drawn over the floor once triggered) and floor decorations
# ----------------------------------------------------------------------
TRAP_SPIKE = [
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "...w...w...w....",
    "...s...s...s....",
    "..sss.sss.sss...",
    "..sss.sss.sss...",
    ".oooooooooooo...",
    ".obbbbbbbbbbo...",
    "................",
    "................",
    "................",
]

TRAP_POISON = [
    "................",
    "................",
    "................",
    "................",
    "......g....g....",
    "....g......g....",
    "................",
    ".....oooooo.....",
    "....oggggggo....",
    "...ogdgddgdgo...",
    "...oggggggggo...",
    "....ogdggdgo....",
    ".....oooooo.....",
    "................",
    "................",
    "................",
]

TRAP_TELEPORT = [
    "................",
    "................",
    "................",
    "................",
    ".......pp.......",
    "......p..p......",
    ".....p.qq.p.....",
    "....p.qqqq.p....",
    "....p.qqqq.p....",
    ".....p.qq.p.....",
    "......p..p......",
    ".......pp.......",
    "................",
    "................",
    "................",
    "................",
]

DECOR_BONES = [
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "...ww......w....",
    "...ww....ww.ww..",
    ".........w.w....",
    "....w.w.........",
    ".....w..........",
    "................",
    "................",
]

DECOR_RUBBLE = [
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "....rr..........",
    "....rr...ss.....",
    "..........ss....",
    "......rr........",
    "..s...rr........",
    "................",
    "................",
]

DECOR_MOSS = [
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "..mm......nn....",
    "..mmm....nmm....",
    "...mm...........",
    ".........mm.....",
    "....nn...mmn....",
    "................",
    "................",
]

# ----------------------------------------------------------------------
# Tile sprites (fully opaque)
# ----------------------------------------------------------------------
FLOOR_TILE = [
    "aaaaaaaaaaaaaaaa",
    "aabaaaaaacaaaaaa",
    "aaaaaaaaaaaaaaaa",
    "aaaaacaaaaaabaaa",
    "aaaaaaaaaaaaaaaa",
    "abaaaaaabaaaaaaa",
    "aaaaaaaaaaaaacaa",
    "aaaacaaaaaaaaaaa",
    "aaaaaaaabaaaaaaa",
    "aacaaaaaaaaabaaa",
    "aaaaaaacaaaaaaaa",
    "aaaaaaaaaaaaaaaa",
    "abaaaacaaaabaaaa",
    "aaaaaaaaaaaaaaca",
    "aaacaaaaabaaaaaa",
    "aaaaaaaaaaaaaaaa",
]

WALL_TILE = [
    "hhhhhhhhhhhhhhhh",
    "aaaaaaamaaaaaaaa",
    "aaaaaaamaaaaaaaa",
    "aaaaaaamaaaaaaaa",
    "mmmmmmmmmmmmmmmm",
    "aaamaaaaaaaamaaa",
    "aaamaaaaaaaamaaa",
    "aaamaaaaaaaamaaa",
    "aaamaaaaaaaamaaa",
    "mmmmmmmmmmmmmmmm",
    "aaaaaaamaaaaaaaa",
    "aaaaaaamaaaaaaaa",
    "aaaaaaamaaaaaaaa",
    "aaaaaaamaaaaaaaa",
    "mmmmmmmmmmmmmmmm",
    "aaamaaaaaaaamaaa",
]

STAIRS_TILE = [
    "aaaaaaaaaaaaaaaa",
    "aaaaaaaaaaaaaaaa",
    "aa1111222233kkaa",
    "aa1111222233kkaa",
    "aa1111222233kkaa",
    "aa1w11222233kkaa",
    "aa11w12222w3kkaa",
    "aa111w22w233kkaa",
    "aa1111ww2233kkaa",
    "aa1111222233kkaa",
    "aa1111222233kkaa",
    "aa1111222233kkaa",
    "aa1111222233kkaa",
    "aa1111222233kkaa",
    "aaaaaaaaaaaaaaaa",
    "aaaaaaaaaaaaaaaa",
]

# ----------------------------------------------------------------------
# Palettes
# ----------------------------------------------------------------------
_o = OUTLINE

SPRITE_DEFS = {
    # tiles
    "floor": (FLOOR_TILE, {"a": "#43434f", "b": "#3a3a45", "c": "#4c4c59"}),
    "wall": (WALL_TILE, {"a": "#34343f", "m": "#1e1e26", "h": "#41414e"}),
    "stairs": (STAIRS_TILE, {"a": "#43434f", "1": "#606070", "2": "#4c4c5a",
                              "3": "#3a3a46", "k": "#0a0a0e", "w": "#8fd9ef"}),
    # people
    "player": (PLAYER, PLAYER_PALETTE),
    "shopkeeper": (SHOPKEEPER, {"o": _o, "h": "#8a5a2a", "f": "#e8b888",
                                 "e": "#20242c", "c": "#7a3a8a", "g": "#f2c94c",
                                 "b": "#3a2a1a"}),
    # monsters
    "rat": (BEAST, {"o": _o, "a": "#8a6f52", "e": "#d33a3a", "b": "#5f4a36"}),
    "spider": (SPIDER, {"o": _o, "a": "#4a3b5c", "e": "#e04444"}),
    "goblin": (HUMANOID_SMALL, {"o": _o, "a": "#4fae4f", "e": "#d8e042"}),
    "kobold": (HUMANOID_SMALL, {"o": _o, "a": "#c07840", "e": "#e0e0d0"}),
    "skeleton": (SKELETON, {"o": _o, "a": "#e0ddd0", "e": "#202020", "b": "#b8b4a4"}),
    "orc": (HUMANOID_BIG, {"o": _o, "a": "#3e7d3e", "e": "#e0c040", "f": "#f0f0e0"}),
    "wraith": (GHOST, {"o": _o, "a": "#9fb8d8", "e": "#3050e0", "b": "#6a80a8"}),
    "troll": (HUMANOID_BIG, {"o": _o, "a": "#5e8a52", "e": "#e05050", "f": "#d8d8c0"}),
    "ogre": (HUMANOID_BIG, {"o": _o, "a": "#c9a06a", "e": "#803030", "f": "#e8e0d0"}),
    "knight": (HUMANOID_BIG, {"o": _o, "a": "#5a5a6e", "e": "#e03030", "f": "#44445a"}),
    "wyvern": (WYVERN, {"o": _o, "a": "#3f9e8f", "e": "#f0e040", "b": "#2c6e63"}),
    "lich": (MAGE, {"o": _o, "a": "#5e3a8a", "b": "#241640", "e": "#40e0d0",
                     "c": "#9a7ade"}),
    # items
    "sword": (SWORD, {"o": _o, "w": "#f0f4fa", "s": "#c8d0dc", "g": "#caa53c",
                       "m": "#6a4a2a"}),
    "armor": (ARMOR, {"o": _o, "a": "#8fa3b8", "b": "#5a6a7a", "g": "#caa53c"}),
    "ring": (RING, {"o": _o, "g": "#e8c34c", "e": "#d04070"}),
    "potion": (POTION, {"o": _o, "a": "#cfe4f0", "l": "#e04848", "k": "#8a5a2a"}),
    "scroll": (SCROLL, {"o": _o, "w": "#e8ddb8", "b": "#b8a878", "t": "#6a5a3a"}),
    "gold": (GOLD, {"o": _o, "g": "#f2c94c", "d": "#c9992c"}),
    # overlays
    "crown": (CROWN, {"g": "#f2c94c", "e": "#e03050"}),
    # traps
    "trap_spike": (TRAP_SPIKE, {"o": _o, "s": "#b8c0cc", "w": "#eef2f8", "b": "#26262e"}),
    "trap_poison": (TRAP_POISON, {"o": _o, "g": "#58c058", "d": "#2e7d32"}),
    "trap_teleport": (TRAP_TELEPORT, {"p": "#b060e0", "q": "#7030a0"}),
    # floor decorations (cosmetic)
    "decor_bones": (DECOR_BONES, {"w": "#c8c4b4"}),
    "decor_rubble": (DECOR_RUBBLE, {"r": "#55555f", "s": "#616170"}),
    "decor_moss": (DECOR_MOSS, {"m": "#3a6a45", "n": "#2c5236"}),
}

TRAP_KEYS = {
    "spike": "trap_spike",
    "poison": "trap_poison",
    "teleport": "trap_teleport",
}

DECOR_SPRITES = ("decor_bones", "decor_rubble", "decor_moss")

MONSTER_KEYS = {
    "Rat": "rat",
    "Giant Spider": "spider",
    "Goblin": "goblin",
    "Kobold": "kobold",
    "Skeleton": "skeleton",
    "Orc": "orc",
    "Wraith": "wraith",
    "Troll": "troll",
    "Ogre": "ogre",
    "Dark Knight": "knight",
    "Wyvern": "wyvern",
    "Lich": "lich",
}

ITEM_KEYS = {
    "weapon": "sword",
    "armor": "armor",
    "accessory": "ring",
    "potion": "potion",
    "scroll": "scroll",
    "gold": "gold",
}

# Sprites that get a darkened "explored but not visible" variant.
DIM_TILES = ("floor", "wall", "stairs",
             "trap_spike", "trap_poison", "trap_teleport",
             "decor_bones", "decor_rubble", "decor_moss")
DIM_FACTOR = 0.45


def _darken(hex_color: str, factor: float = DIM_FACTOR) -> str:
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return f"#{int(r * factor):02x}{int(g * factor):02x}{int(b * factor):02x}"


