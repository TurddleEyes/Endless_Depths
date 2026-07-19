"""Pixel-art sprite data: grids of palette characters ('.' = transparent).

Pure data + helpers, no tkinter - shared by the desktop renderer
(ui/sprites.py) and the browser build (web/webbridge.py).

Sprites are AUTHORED at 16x16 (_SRC_PX) and SHIPPED at 32x32 (SPRITE_PX):
every grid is doubled once, at import time, through Scale2x (EPX) - the
classic pixel-art upscaler that rounds diagonal staircases without
blurring or inventing colors. Renderers only ever see 32x32 grids. To
hand-detail an individual sprite at full resolution later, author it at
32x32 and add its key to NATIVE_32 so the upscaler leaves it alone.
"""
from __future__ import annotations

_SRC_PX = 16      # authoring resolution (all grids below)
SPRITE_PX = 32    # shipped resolution (after Scale2x, see end of module)
OUTLINE = "#14141a"
MISSING = "#ff00ff"  # loud fallback for any palette-char typo

# Keys whose grids are already authored at 32x32 and skip the upscaler.
NATIVE_32: set = set()


def _scale2x(grid) -> list:
    """Scale2x/EPX: double a char grid, rounding diagonals.

    For each source pixel P with orthogonal neighbors A (up), B (right),
    C (left), D (down), the four output sub-pixels are the neighbor color
    where two like neighbors meet at a corner, else P. Equality is plain
    char equality, so '.' (transparent) participates naturally and no new
    palette entries are ever created.
    """
    # Pad to a clean square first - a few decorative grids are authored
    # with trailing blank rows omitted.
    rows = [(grid[i] if i < len(grid) else "")[:_SRC_PX].ljust(_SRC_PX, ".")
            for i in range(_SRC_PX)]
    h = w = _SRC_PX
    out = [[None] * (w * 2) for _ in range(h * 2)]
    for y in range(h):
        for x in range(w):
            p = rows[y][x]
            a = rows[y - 1][x] if y > 0 else p
            d = rows[y + 1][x] if y < h - 1 else p
            c = rows[y][x - 1] if x > 0 else p
            b = rows[y][x + 1] if x < w - 1 else p
            out[y * 2][x * 2] = a if (c == a and c != d and a != b) else p
            out[y * 2][x * 2 + 1] = b if (a == b and a != c and b != d) else p
            out[y * 2 + 1][x * 2] = c if (d == c and d != b and c != a) else p
            out[y * 2 + 1][x * 2 + 1] = d if (b == d and b != a and d != c) else p
    return ["".join(r) for r in out]

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

# The Unfinished One: a HUMANOID_BIG the Well never finished drawing -
# the right side simply stops, with a few stray pixels of static ("x")
# where the rest of it should have been.
UNFINISHED = [
    "................",
    "................",
    "...oooooo.......",
    "..oaaaaaao......",
    "..oaeaaeao......",
    "..oaaaaaao......",
    "..oaaffaao......",
    "...oaaaao.......",
    "..ooaaaa.x......",
    ".oaoaaaa..x.....",
    ".oa.oaa......x..",
    ".oo.oaa.........",
    "....oa.....x....",
    "....o...........",
    "...oo...........",
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

# ---- directional hero poses ----
# "down" is HERO_BASE (the classic front view). "up" hides the face and the
# held weapon (both are on the far side of the body). "side" faces RIGHT;
# the left-facing sprite is a runtime mirror of the composed right-facing
# one, so no separate art exists for it.
HERO_BASE_UP = [
    "................",
    "....oooo........",
    "...ohhhho.......",
    "...ohhhho.......",
    "...ohhhho.......",
    "...ohhhho.......",
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

HERO_BASE_SIDE = [
    "................",
    "....oooo........",
    "...ohhhho.......",
    "...ohfffo.......",
    "...ohfefo.......",
    "...ohfffo.......",
    "....offo........",
    "...ottttto......",
    "...ottttto......",
    "...ottttto......",
    "....obbbo.......",
    "....ob.bo.......",
    "....oo.oo.......",
    "................",
    "................",
    "................",
]

# Side-view weapons: held level, pointing the way the hero walks.
HELD_SWORD_SIDE = [
    "................", "................", "................",
    "................", "................", "................",
    "................", "................",
    "........mgsssw..",
    "................", "................", "................",
    "................", "................", "................",
    "................",
]
HELD_DAGGER_SIDE = [
    "................", "................", "................",
    "................", "................", "................",
    "................", "................",
    "........mgsw....",
    "................", "................", "................",
    "................", "................", "................",
    "................",
]
HELD_AXE_SIDE = [
    "................", "................", "................",
    "................", "................", "................",
    "................",
    "...........sw...",
    "........mmmms...",
    "...........ss...",
    "................", "................",
    "................", "................", "................",
    "................",
]
HELD_HAMMER_SIDE = [
    "................", "................", "................",
    "................", "................", "................",
    "................",
    "...........sss..",
    "........mmmsss..",
    "...........sss..",
    "................", "................",
    "................", "................", "................",
    "................",
]
HELD_SPEAR_SIDE = [
    "................", "................", "................",
    "................", "................", "................",
    "................", "................",
    ".......mmmmmmw..",
    "................", "................", "................",
    "................", "................", "................",
    "................",
]

HELD_WEAPONS_SIDE = {
    "dagger": HELD_DAGGER_SIDE,
    "sword": HELD_SWORD_SIDE,
    "axe": HELD_AXE_SIDE,
    "hammer": HELD_HAMMER_SIDE,
    "spear": HELD_SPEAR_SIDE,
}

HERO_FACINGS = ("down", "up", "left", "right")


def mirror_grid(grid):
    """Horizontal flip (used for the left-facing hero)."""
    return [row[::-1] for row in grid]

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
    """Merge overlay grids onto a base grid; non-'.' overlay pixels win.
    Works at authoring resolution - callers upscale the finished result,
    so Scale2x gets to smooth ACROSS layer boundaries (hand meets hilt)."""
    rows = [list((base[i] if i < len(base) else "")[:_SRC_PX].ljust(_SRC_PX, "."))
            for i in range(_SRC_PX)]
    for overlay in overlays:
        if not overlay:
            continue
        for y in range(min(_SRC_PX, len(overlay))):
            row = overlay[y]
            for x in range(min(_SRC_PX, len(row))):
                if row[x] != ".":
                    rows[y][x] = row[x]
    return ["".join(r) for r in rows]


def hero_grid_and_palette(weapon="sword", armor="none", accessory=False,
                           poisoned=False, weapon_rarity="common",
                           facing="down"):
    """Pure-data hero variant (no tkinter needed) - grid + palette.
    Returned grid is at shipped resolution (SPRITE_PX). facing is one of
    HERO_FACINGS; "left" mirrors the composed right-facing sprite."""
    overlays = []
    if facing == "up":
        base = HERO_BASE_UP          # weapon and pendant are behind the body
    elif facing in ("left", "right"):
        base = HERO_BASE_SIDE
        if weapon != "none":
            overlays.append(HELD_WEAPONS_SIDE.get(weapon, HELD_SWORD_SIDE))
        if accessory:
            overlays.append(ACCESSORY_OVERLAY)
    else:
        base = HERO_BASE
        if weapon != "none":
            overlays.append(HELD_WEAPONS.get(weapon, HELD_SWORD))
        if accessory:
            overlays.append(ACCESSORY_OVERLAY)
    grid = _compose(base, *overlays)
    if facing == "left":
        grid = mirror_grid(grid)
    grid = _scale2x(grid)
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

FLOOR_TILE_CRACKED = [
    "aaaaaaaaaaaaaaaa",
    "aabaaaaaacaaaaaa",
    "aaaad aaaaaaaaaa".replace(" ", "a"),
    "aaaaadaaaaaabaaa",
    "aaaaaadaaaaaaaaa",
    "abaaaaadaaaaaaaa",
    "aaaaaaaadddaacaa",
    "aaaacaaaaaadaaaa",
    "aaaaaaaabaaadaaa",
    "aacaaaaaaaaabdaa",
    "aaaaaaacaaaaadaa",
    "aaaaaaaaaaaaaaaa",
    "abaaaacaaaabaaaa",
    "aaaaaaaaaaaaaaca",
    "aaacaaaaabaaaaaa",
    "aaaaaaaaaaaaaaaa",
]

FLOOR_TILE_MOSSY = [
    "aaaaaaaaaaaaaaaa",
    "aabaaaammaaaaaaa",
    "aaaaaaammmaaaaaa",
    "aaaaacaamaaabaaa",
    "aaaaaaaaaaaaaaaa",
    "abaaaaaabaaaaaaa",
    "amaaaaaaaaaaacaa",
    "ammacaaaaaaaaaaa",
    "aamaaaaabaaaaaaa",
    "aacaaaaaaaaabaaa",
    "aaaaaaacaaaammaa",
    "aaaaaaaaaaaamnaa",
    "abaaaacaaaabaaaa",
    "aaaaaaaaaaaaaaca",
    "aaacaaaaabaaaaaa",
    "aaaaaaaaaaaaaaaa",
]

WALL_TILE_CRACKED = [
    "hhhhhhhhhhhhhhhh",
    "aaaaaaamaaaaaaaa",
    "aaakaaamaaaaaaaa",
    "aaakkaamaaaaaaaa",
    "mmmmkmmmmmmmmmmm",
    "aaamak aaaaamaaa".replace(" ", "a"),
    "aaamaakaaaaamaaa",
    "aaamaaakkaaamaaa",
    "aaamaaaaakaamaaa",
    "mmmmmmmmmmkmmmmm",
    "aaaaaaamaakaaaaa",
    "aaaaaaamaaakaaaa",
    "aaaaaaamaaaakaaa",
    "aaaaaaamaaaaaaaa",
    "mmmmmmmmmmmmmmmm",
    "aaamaaaaaaaamaaa",
]

# A stairwell seen from above: three treads step down and inward, each a
# bright lit nosing over a darkening tread with a hard shadow line between
# steps (the banding is what makes it read as STAIRS at tile size), ending
# in a void with a faint glint from somewhere far below.
STAIRS_TILE = [
    "aaaaaaaaaaaaaaaa",
    "aaaaaaaaaaaaaaaa",
    "aaddddddddddddaa",
    "aadhhhhhhhhhhdaa",
    "aad1111111111daa",
    "aadggggggggggdaa",
    "aaddhhhhhhhhddaa",
    "aadd22222222ddaa",
    "aaddggggggggddaa",
    "aadddhhhhhhdddaa",
    "aaddd333333dddaa",
    "aadddggggggdddaa",
    "aaddddkwwkddddaa",
    "aaddddkkkkddddaa",
    "aaaaaaaaaaaaaaaa",
    "aaaaaaaaaaaaaaaa",
]

DOOR_RUNE_TILE = [
    "ssssssssssssssss",
    "sdddddddddddddds",
    "sdkddddddddddkds",
    "sddddddrrdddddds",
    "sdddddrddrdddDds",
    "sdddddrddrdddDds",
    "sddddddrrdddddds",
    "sdddddddrddddDds",
    "sddddddrrrdddDds",
    "sdddddrdrdrddDds",
    "sdddddddrddddDds",
    "sdkddddddddddkds",
    "sdddddddddddddds",
    "sdddddddddddddds",
    "sdddddddddddddds",
    "ssssssssssssssss",
]

DOOR_BOSS_TILE = [
    "ssssssssssssssss",
    "sdddddddddddddds",
    "sdkddddddddddkds",
    "sdddrddddddrddds",
    "sddddrddddrdddds",
    "sdddddrddrddddds",
    "sddddddrrdddddds",
    "sddddddrrdddddds",
    "sdddddrddrddddds",
    "sddddrddddrdddds",
    "sdddrddddddrddds",
    "sdkddddddddddkds",
    "sdddddddddddddds",
    "sdddddddddddddds",
    "sdddddddddddddds",
    "ssssssssssssssss",
]

CHEST_TILE = [
    "aaaaaaaaaaaaaaaa",
    "aaaaaaaaaaaaaaaa",
    "aaaaaaaaaaaaaaaa",
    "aaooooooooooooaa",
    "aowwwwwwwwwwwwoa",
    "aowwwwwwwwwwwwoa",
    "aoggggggggggggoa",
    "aowwwwwggwwwwwoa",
    "aobbbbbggbbbbboa",
    "aobbbbbggbbbbboa",
    "aobbbbbbbbbbbboa",
    "aobbbbbbbbbbbboa",
    "aaooooooooooooaa",
    "aaaaaaaaaaaaaaaa",
    "aaaaaaaaaaaaaaaa",
    "aaaaaaaaaaaaaaaa",
]

LEVER_UP_TILE = [
    "aaaaaaaaaaaaaaaa",
    "aaaaaaaaaaaaaaaa",
    "aaaaaaaaaaggaaaa",
    "aaaaaaaaaaggaaaa",
    "aaaaaaaaawwaaaaa",
    "aaaaaaaawwaaaaaa",
    "aaaaaaawwaaaaaaa",
    "aaaaaawwaaaaaaaa",
    "aaaaawwaaaaaaaaa",
    "aaaasskssaaaaaaa",
    "aaasssksssaaaaaa",
    "aaasssksssaaaaaa",
    "aaassssssaaaaaaa",
    "aaassssssaaaaaaa",
    "aaaaaaaaaaaaaaaa",
    "aaaaaaaaaaaaaaaa",
]

LEVER_DOWN_TILE = [
    "aaaaaaaaaaaaaaaa",
    "aaaaaaaaaaaaaaaa",
    "aaaaaaaaaaaaaaaa",
    "aaaaaaaaaaaaaaaa",
    "aaaaaaaaaaaaaaaa",
    "aaaaaaaaaaaaaaaa",
    "aaaaaaaaaaaaaaaa",
    "aaaaaaaaaaaaaaaa",
    "aaaaawwaaaaaaaaa",
    "aaaasskwwaaaaaaa",
    "aaasssksswwaaaaa",
    "aaasssksssawwaaa",
    "aaassssssaaaggaa",
    "aaassssssaaaggaa",
    "aaaaaaaaaaaaaaaa",
    "aaaaaaaaaaaaaaaa",
]

PLATE_OFF_TILE = [
    "aaaaaaaaaaaaaaaa",
    "aaaaaaaaaaaaaaaa",
    "aaaaaaaaaaaaaaaa",
    "aaaappppppppaaaa",
    "aaappqqqqqqppaaa",
    "aappqqqqqqqqppaa",
    "aapqqqqqqqqqqpaa",
    "aapqqqqqqqqqqpaa",
    "aapqqqqqqqqqqpaa",
    "aapqqqqqqqqqqpaa",
    "aappqqqqqqqqppaa",
    "aaappqqqqqqppaaa",
    "aaaappppppppaaaa",
    "aaaaaaaaaaaaaaaa",
    "aaaaaaaaaaaaaaaa",
    "aaaaaaaaaaaaaaaa",
]

PLATE_ON_TILE = [
    "aaaaaaaaaaaaaaaa",
    "aaaaaaaaaaaaaaaa",
    "aaaaaaaaaaaaaaaa",
    "aaaappppppppaaaa",
    "aaappllllllppaaa",
    "aappllllllllppaa",
    "aapllllllllllpaa",
    "aapllllwwllllpaa",
    "aapllllwwllllpaa",
    "aapllllllllllpaa",
    "aappllllllllppaa",
    "aaappllllllppaaa",
    "aaaappppppppaaaa",
    "aaaaaaaaaaaaaaaa",
    "aaaaaaaaaaaaaaaa",
    "aaaaaaaaaaaaaaaa",
]

BLOCK_TILE = [
    "oooooooooooooooo",
    "otttttttttttttto",
    "otttttttttttttso",
    "otttttttttttttso",
    "offfffffffffffso",
    "offffkffffffffso",
    "offffkkfffffffso",
    "offffffffkffffso",
    "offfffffkkffffso",
    "offfffffffffffso",
    "offffffkffffffso",
    "offfffffffffffso",
    "osssssssssssssso",
    "osssssssssssssso",
    "oooooooooooooooo",
    "oooooooooooooooo",
]

RUNE_SWITCH = [
    "................",
    "................",
    "................",
    "....cccccccc....",
    "...cc......cc...",
    "...c..cccc..c...",
    "...c.cc..cc.c...",
    "...c.c....c.c...",
    "...c.c....c.c...",
    "...c.cc..cc.c...",
    "...c..cccc..c...",
    "...cc......cc...",
    "....cccccccc....",
    "................",
    "................",
    "................",
]

KEY = [
    "................",
    "................",
    "................",
    "....ooo.........",
    "...ogggo........",
    "...og.go........",
    "...ogggo........",
    "....ogo.........",
    ".....go.........",
    ".....go.........",
    ".....gggo.......",
    ".....go.........",
    ".....gggo.......",
    "......oo........",
    "................",
    "................",
]

MIMIC = [
    "................",
    "................",
    "..oooooooooooo..",
    ".owwwwwwwwwwwwo.",
    ".owweewwwweewwo.",
    ".owweewwwweewwo.",
    ".owwwwwwwwwwwwo.",
    ".oggggggggggggo.",
    ".otthhtthhtthho.",
    ".ohhhhhhhhhhhho.",
    ".othhtthhtthhto.",
    ".obbbbbbbbbbbbo.",
    ".obbbbbbbbbbbbo.",
    "..oooooooooooo..",
    "................",
    "................",
]

# ----------------------------------------------------------------------
# Palettes
# ----------------------------------------------------------------------
_o = OUTLINE

SPRITE_DEFS = {
    # tiles
    "floor": (FLOOR_TILE, {"a": "#43434f", "b": "#3a3a45", "c": "#4c4c59"}),
    "floor2": (FLOOR_TILE_CRACKED, {"a": "#43434f", "b": "#3a3a45", "c": "#4c4c59",
                                     "d": "#33333d"}),
    "floor3": (FLOOR_TILE_MOSSY, {"a": "#43434f", "b": "#3a3a45", "c": "#4c4c59",
                                   "m": "#3d5a44", "n": "#2c4634"}),
    "wall": (WALL_TILE, {"a": "#34343f", "m": "#1e1e26", "h": "#41414e"}),
    "wall2": (WALL_TILE_CRACKED, {"a": "#34343f", "m": "#1e1e26", "h": "#41414e",
                                   "k": "#26262e"}),
    "stairs": (STAIRS_TILE, {"a": "#43434f", "d": "#23232b", "h": "#82828f",
                              "1": "#6a6a7c", "2": "#4a4a58", "3": "#32323c",
                              "g": "#17171d", "k": "#08080c", "w": "#8fd9ef"}),
    "door_rune": (DOOR_RUNE_TILE, {"s": "#5a5a68", "d": "#3b3b47",
                                    "D": "#32323d", "k": "#26262e",
                                    "r": "#e0a83a"}),
    "door_boss": (DOOR_BOSS_TILE, {"s": "#5a3838", "d": "#3b2020",
                                    "k": "#261515", "r": "#ff3b3b"}),
    "chest": (CHEST_TILE, {"a": "#43434f", "o": _o, "w": "#a06a32",
                            "b": "#7a4e24", "g": "#f2c94c"}),
    "lever_up": (LEVER_UP_TILE, {"a": "#43434f", "s": "#5a5a68",
                                  "k": "#2a2a33", "w": "#c8d0dc",
                                  "g": "#d04040"}),
    "lever_down": (LEVER_DOWN_TILE, {"a": "#43434f", "s": "#5a5a68",
                                      "k": "#2a2a33", "w": "#c8d0dc",
                                      "g": "#d04040"}),
    "plate_off": (PLATE_OFF_TILE, {"a": "#43434f", "p": "#5a5a68",
                                    "q": "#35353f"}),
    "plate_on": (PLATE_ON_TILE, {"a": "#43434f", "p": "#5a5a68",
                                  "l": "#e0a83a", "w": "#fff2c8"}),
    "block": (BLOCK_TILE, {"o": "#1e1e26", "t": "#6a6a7a", "f": "#565664",
                            "s": "#3e3e4a", "k": "#2e2e38"}),
    "rune_switch": (RUNE_SWITCH, {"c": "#66d9ef"}),
    "key": (KEY, {"o": _o, "g": "#e8c34c"}),
    "mimic": (MIMIC, {"o": _o, "w": "#a06a32", "b": "#7a4e24",
                       "g": "#f2c94c", "e": "#e04444", "t": "#f0f0e0",
                       "h": "#3a0f14"}),
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
    # deep breeds (palette swaps of the shared body shapes - on-theme: the
    # Well re-drafts the same shapes deeper and wronger)
    "ghoul": (HUMANOID_BIG, {"o": _o, "a": "#a8b088", "e": "#e0e042", "f": "#6a7050"}),
    "basilisk": (BEAST, {"o": _o, "a": "#7ab83a", "e": "#f0e040", "b": "#4c7a26"}),
    "shade": (GHOST, {"o": _o, "a": "#3a3a52", "e": "#b060e0", "b": "#242438"}),
    "grave_golem": (HUMANOID_BIG, {"o": _o, "a": "#6a6a78", "e": "#e0a83a", "f": "#3a6a45"}),
    "void_weaver": (SPIDER, {"o": _o, "a": "#2c2440", "e": "#66d9ef"}),
    "revenant": (SKELETON, {"o": _o, "a": "#b0a890", "e": "#e05050", "b": "#7a5a3a"}),
    "chimera": (BEAST, {"o": _o, "a": "#b06a3a", "e": "#f0e040", "b": "#3f9e8f"}),
    "barrow_king": (HUMANOID_BIG, {"o": _o, "a": "#8a8468", "e": "#e0c040", "f": "#caa53c"}),
    "deep_wyrm": (WYVERN, {"o": _o, "a": "#4a6a8a", "e": "#8fd9ef", "b": "#32485e"}),
    "archlich": (MAGE, {"o": _o, "a": "#2a2a30", "b": "#141418", "e": "#e0a83a",
                         "c": "#caa53c"}),
    # the Faceless One's "eyes" are the same color as its face - that IS the sprite
    "faceless": (GHOST, {"o": _o, "a": "#d8d4c8", "e": "#d8d4c8", "b": "#b8b4a4"}),
    "marrow_fiend": (BEAST, {"o": _o, "a": "#7a2a2a", "e": "#f0f0e0", "b": "#4c1a1a"}),
    "grave_titan": (HUMANOID_BIG, {"o": _o, "a": "#4c4c58", "e": "#e05030", "f": "#2e2e38"}),
    "unfinished": (UNFINISHED, {"o": _o, "a": "#b8bcd0", "e": "#14141a",
                                 "f": "#9098b0", "x": "#66d9ef"}),
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

# One-time upscale pass: everything above is authored at 16x16; renderers
# only ever see the 32x32 Scale2x results installed here.
SPRITE_DEFS = {
    key: (grid if key in NATIVE_32 else _scale2x(grid), palette)
    for key, (grid, palette) in SPRITE_DEFS.items()
}

TRAP_KEYS = {
    "spike": "trap_spike",
    "poison": "trap_poison",
    "teleport": "trap_teleport",
}

DECOR_SPRITES = ("decor_bones", "decor_rubble", "decor_moss")

MONSTER_KEYS = {
    "Mimic": "mimic",
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
    "Ghoul": "ghoul",
    "Basilisk": "basilisk",
    "Shade": "shade",
    "Grave Golem": "grave_golem",
    "Void Weaver": "void_weaver",
    "Revenant": "revenant",
    "Chimera": "chimera",
    "Barrow King": "barrow_king",
    "Deep Wyrm": "deep_wyrm",
    "Archlich": "archlich",
    "Faceless One": "faceless",
    "Marrow Fiend": "marrow_fiend",
    "Grave Titan": "grave_titan",
    "Unfinished One": "unfinished",
}

ITEM_KEYS = {
    "weapon": "sword",
    "armor": "armor",
    "accessory": "ring",
    "potion": "potion",
    "scroll": "scroll",
    "gold": "gold",
    "key": "key",
}

# Tile-char -> sprite key for the new interactable tiles, shared by both
# renderers (lever/plate pick their lit/pulled variant from puzzle state).
PUZZLE_TILE_KEYS = {
    "+": "door_rune",
    "=": "door_boss",
    "&": "chest",
    "L": "lever_up",
    "_": "plate_off",
    "B": "block",
}

# Sprites that get a darkened "explored but not visible" variant.
DIM_TILES = ("floor", "floor2", "floor3", "wall", "wall2", "stairs",
             "door_rune", "door_boss", "chest", "lever_up", "lever_down",
             "plate_off", "plate_on", "block", "rune_switch",
             "trap_spike", "trap_poison", "trap_teleport",
             "decor_bones", "decor_rubble", "decor_moss")
DIM_FACTOR = 0.45

# Deterministic per-tile texture variation, shared by both renderers so the
# desktop and browser builds draw identical dungeons.
FLOOR_VARIANTS = ("floor", "floor2", "floor3")
WALL_VARIANTS = ("wall", "wall2")


def _tile_hash(depth: int, x: int, y: int) -> int:
    return (x * 73856093 ^ y * 19349663 ^ depth * 83492791) & 0xFFFFFFFF


def floor_variant(depth: int, x: int, y: int) -> int:
    h = _tile_hash(depth, x, y) % 10
    if h >= 9:
        return 2  # mossy
    if h >= 7:
        return 1  # cracked
    return 0


def wall_variant(depth: int, x: int, y: int) -> int:
    return 1 if _tile_hash(depth, x, y) % 10 >= 8 else 0


def _darken(hex_color: str, factor: float = DIM_FACTOR) -> str:
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return f"#{int(r * factor):02x}{int(g * factor):02x}{int(b * factor):02x}"


