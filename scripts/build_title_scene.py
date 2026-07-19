"""Generate the title-screen artwork: web/title_bg.png + web/title_logo.png.

The backdrop is a composed pixel-art dungeon scene built from the game's
own sprites (walls, floor, chest, bones, moss) plus title-only set pieces
drawn here (banners, torches, archway, chains, crystal). The logo is
rendered from a chunky 5x7 pixel font. Both ship as small committed PNGs;
CSS scales them with image-rendering: pixelated.

    python3 scripts/build_title_scene.py
"""
from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import spritedata as S  # noqa: E402
from ui import texturepack as TP  # noqa: E402

GAME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H = 512, 336
FLOOR_Y = 240

rng = random.Random(90)  # the reserved number, naturally


# ----------------------------------------------------------------------
# Canvas helpers (RGBA rows)
# ----------------------------------------------------------------------
def blank(w, h, color=(0, 0, 0, 0)):
    return [[color] * w for _ in range(h)]


def px(canvas, x, y, color):
    if 0 <= x < len(canvas[0]) and 0 <= y < len(canvas):
        canvas[y][x] = color


def rect(canvas, x0, y0, w, h, color):
    for y in range(y0, y0 + h):
        for x in range(x0, x0 + w):
            px(canvas, x, y, color)


def blit(canvas, rows, ox, oy, scale=1):
    for gy, row in enumerate(rows):
        for gx, c in enumerate(row):
            if c[3] < 128:
                continue
            for dy in range(scale):
                for dx in range(scale):
                    px(canvas, ox + gx * scale + dx, oy + gy * scale + dy, c)


def sprite_px(key):
    return TP.grid_to_px(*S.SPRITE_DEFS[key])


def rgb(hexs, a=255):
    return (*TP.hex_to_rgb(hexs), a)


def darken(canvas, x0, y0, w, h, factor):
    for y in range(max(0, y0), min(len(canvas), y0 + h)):
        for x in range(max(0, x0), min(len(canvas[0]), x0 + w)):
            r, g, b, a = canvas[y][x]
            canvas[y][x] = (int(r * factor), int(g * factor), int(b * factor), a)


# ----------------------------------------------------------------------
# Title-only set pieces (drawn from tiny char grids)
# ----------------------------------------------------------------------
def grid_px(grid, palette):
    rows = []
    for grow in grid:
        row = []
        for ch in grow:
            row.append((0, 0, 0, 0) if ch == "." else rgb(palette[ch]))
        rows.append(row)
    return rows


BANNER = grid_px([
    "kkkkkkkkkkkk",
    "pPPPPPPPPPPp",
    "pPPPPPPPPPPp",
    "pPPPPPPPPPPp",
    "pPPwwPPwwPPp",
    "pPPwwPPwwPPp",
    "pPPPPPPPPPPp",
    "pPPwPPPPwPPp",
    "pPPPwwwwPPPp",
    "pPPPPPPPPPPp",
    "pPPPPPPPPPPp",
    "pPPPPPPPPPPp",
    "pPPPPPPPPPPp",
    "pP.PPPP.PPPp",
    "p..PPP...PP.",
    "...PP.....P.",
], {"k": "#3a3a45", "p": "#3a1f52", "P": "#54307a", "w": "#c9c2d8"})

TORCH = grid_px([
    ".....yy.....",
    "....yyyy....",
    "....yffy....",
    "...yffffy...",
    "...offffo...",
    "...offffo...",
    "....offo....",
    ".....oo.....",
    "....smms....",
    "....smms....",
    "....smms....",
    "...ssmmss...",
    "....mmmm....",
    "....mmmm....",
    "....mmmm....",
], {"y": "#ffe066", "f": "#f2801e", "o": "#c8460c", "m": "#5a3a20",
    "s": "#3a2412"})

CRYSTAL = grid_px([
    "...q....",
    "..qpq...",
    "..qppq..",
    ".qpppbq.",
    ".qppbbq.",
    ".qpbbq..",
    "..qbq...",
    "...q....",
], {"q": "#7030a0", "p": "#b060e0", "b": "#d9a8f0"})

SKULL = grid_px([
    "..wwwwww..",
    ".wwwwwwww.",
    "wwwwwwwwww",
    "wwkkwwkkww",
    "wwkkwwkkww",
    "wwwwwwwwww",
    ".wwwkkwww.",
    ".ww.ww.ww.",
    "ww.wwww.ww",
], {"w": "#9a9aa8", "k": "#0e0e12"})


def draw_chain(canvas, x, y0, y1):
    grey, dark = rgb("#5a5a68"), rgb("#3a3a45")
    for y in range(y0, y1, 4):
        rect(canvas, x, y, 2, 3, grey)
        px(canvas, x, y + 1, dark)


def draw_arch(canvas, cx, top, w, bottom):
    """A stone archway; a black void deep in it with a magenta glow
    welling up from the stairs, pooling brightest at the threshold."""
    stone, stone_d, stone_hi = rgb("#565668"), rgb("#34343f"), rgb("#6e6e82")
    void = rgb("#050508")
    half = w // 2

    def cur_at(y):
        t = (y - top) / max(1, (bottom - top))
        return int(half * min(1.0, 0.32 + t * 1.7))

    for y in range(top, bottom):
        cur = cur_at(y)
        for x in range(cx - cur, cx + cur):
            px(canvas, x, y, void)
        for k, col in ((0, stone), (1, stone_d)):
            px(canvas, cx - cur - 1 - k, y, col)
            px(canvas, cx + cur + k, y, col)
    # a thin bright inner lip catching torchlight
    for y in range(top, top + 10):
        cur = cur_at(y)
        px(canvas, cx - cur, y, stone_hi)
        px(canvas, cx + cur - 1, y, stone_hi)

    # descending steps, each darker, glow rising between them
    step_c, step_edge = rgb("#26262f"), rgb("#131318")
    n_steps = 6
    for i in range(n_steps):
        sy = bottom - 6 - i * 5
        cur = cur_at(sy) - 2
        rect(canvas, cx - cur, sy, cur * 2, 3, step_c)
        rect(canvas, cx - cur, sy + 2, cur * 2, 1, step_edge)

    # the glow itself: a soft magenta/violet bloom seated low in the void,
    # additive-ish blending so it reads as light, not paint.
    glow_cx, glow_cy = cx, bottom - 10
    for y in range(top + 20, bottom):
        cur = cur_at(y)
        for x in range(cx - cur, cx + cur):
            dx, dy = x - glow_cx, (y - glow_cy) * 1.4
            d = (dx * dx + dy * dy) ** 0.5
            if d > 46:
                continue
            t = max(0.0, 1 - d / 46)
            if rng.random() > t * 0.9 + 0.1:
                continue
            r, g, b, a = canvas[y][x]
            add = t * (60 if t > 0.6 else 40)
            nr = min(255, int(r + add * 1.15))
            ng = min(255, int(g + add * 0.35))
            nb = min(255, int(b + add * 1.3))
            px(canvas, x, y, (nr, ng, nb, 255))
    # bright core embers near the threshold
    for _ in range(24):
        x = cx + rng.randint(-10, 10)
        y = bottom - rng.randint(2, 9)
        px(canvas, x, y, rgb("#e0a0f5"))


# ----------------------------------------------------------------------
# The scene
# ----------------------------------------------------------------------
def build_scene():
    canvas = blank(W, H, rgb("#0a0a0e"))

    wall = sprite_px("wall")
    wall2 = sprite_px("wall2")
    floor_keys = ("floor", "floor2", "floor3")
    floors = {k: sprite_px(k) for k in floor_keys}

    for ty in range(0, FLOOR_Y, 32):
        for tx in range(0, W, 32):
            blit(canvas, wall2 if rng.random() < 0.25 else wall, tx, ty)
    for ty in range(FLOOR_Y, H, 32):
        for tx in range(0, W, 32):
            blit(canvas, floors[rng.choice(floor_keys)], tx, ty)
    # seam ledge between wall and floor
    rect(canvas, 0, FLOOR_Y - 2, W, 2, rgb("#1e1e26"))

    # depth shading: subtle, walls stay legible instead of murky
    for band, f in ((0, 0.62), (32, 0.68), (64, 0.75), (96, 0.85), (128, 0.95)):
        darken(canvas, 0, band, W, 32, f)
    darken(canvas, 0, H - 20, W, 20, 0.82)

    # set pieces
    draw_arch(canvas, cx=88, top=88, w=92, bottom=FLOOR_Y)
    draw_chain(canvas, 34, 0, 22)
    draw_chain(canvas, 60, 0, 22)
    draw_chain(canvas, W - 36, 0, 22)
    draw_chain(canvas, W - 62, 0, 22)
    blit(canvas, BANNER, 28, 18, 2)
    blit(canvas, BANNER, W - 52, 18, 2)
    blit(canvas, TORCH, 18, 170, 2)
    blit(canvas, TORCH, W - 44, 170, 2)

    # warm firelight pools around each torch's flame (additive glow)
    for (tx, ty) in ((30, 186), (W - 32, 186)):
        for _ in range(260):
            dx, dy = rng.randint(-26, 26), rng.randint(-20, 22)
            d = (dx * dx + dy * dy) ** 0.5
            if d > 26 or rng.random() > max(0, 1 - d / 26) * 0.85:
                continue
            x, y = tx + dx, ty + dy
            r, g, b, a = canvas[y][x] if 0 <= y < H and 0 <= x < W else (0, 0, 0, 0)
            t = max(0, 1 - d / 26)
            px(canvas, x, y, (min(255, int(r + 70 * t)),
                              min(255, int(g + 40 * t)), b, a))

    blit(canvas, SKULL, W - 108, 112, 3)    # skull relief on the right wall
    blit(canvas, CRYSTAL, W - 30, 210, 3)
    bones = sprite_px("decor_bones")
    moss = sprite_px("decor_moss")
    chest = sprite_px("chest")
    for (bx, by) in ((96, 262), (210, 300), (380, 258), (150, 296)):
        blit(canvas, bones, bx, by)
    for (mx, my) in ((180, 208), (300, 214), (240, 226), (410, 210), (60, 246)):
        blit(canvas, moss, mx, my)
    blit(canvas, chest, W - 92, H - 76, 2)

    # gentle edge vignette baked in (CSS adds the center menu shade)
    for i, f in ((0, 0.7), (1, 0.8), (2, 0.9), (3, 0.96)):
        darken(canvas, 0, 0, W, 3 - i + 1, f)
        darken(canvas, 0, H - (4 - i), W, 4 - i, f)
        darken(canvas, 0, 0, 4 - i, H, f)
        darken(canvas, W - (4 - i), 0, 4 - i, H, f)
    return canvas


# ----------------------------------------------------------------------
# The logo: a chunky 7x9 block font, heavily scaled, with real pixel-art
# beveling (bright highlight edge top/left, dark shadow edge bottom/right
# on every filled cell) so it reads as carved/chiseled rather than flat.
# ----------------------------------------------------------------------
FONT = {
    "E": ["1111111", "1000000", "1000000", "1000000", "1111110",
          "1000000", "1000000", "1000000", "1111111"],
    "N": ["1000001", "1100001", "1110001", "1111001", "1011101",
          "1001111", "1000111", "1000011", "1000001"],
    "D": ["1111100", "1000110", "1000011", "1000011", "1000011",
          "1000011", "1000011", "1000110", "1111100"],
    "L": ["1000000", "1000000", "1000000", "1000000", "1000000",
          "1000000", "1000000", "1000000", "1111111"],
    "S": ["0111110", "1000001", "1000000", "0100000", "0011100",
          "0000010", "0000001", "1000001", "0111110"],
    "P": ["1111100", "1000010", "1000001", "1000001", "1111110",
          "1000000", "1000000", "1000000", "1000000"],
    "T": ["1111111", "0011000", "0011000", "0011000", "0011000",
          "0011000", "0011000", "0011000", "0011000"],
    "H": ["1000001", "1000001", "1000001", "1000001", "1111111",
          "1000001", "1000001", "1000001", "1000001"],
    " ": ["0000000"] * 9,
}
GRADIENT = ["#f4feff", "#dbfaff", "#b8f0fc", "#8fd9ef", "#66d9ef",
            "#48b6d6", "#3696b8", "#2b7a96", "#215f76"]
HI = rgb("#ffffff")            # crisp top-left highlight speck
SHADOW_DEEP = rgb("#0a1418")   # cast shadow, offset down-right
OUTLINE = rgb("#0d1c24")


def build_logo(text="ENDLESS DEPTHS"):
    scale = 5
    cell_w, space_w = 8, 5
    gw, gh = 7, 9
    lw = sum((cell_w if ch != " " else space_w) for ch in text) * scale + scale * 2
    lh = gh * scale + scale * 3
    canvas = blank(lw, lh)
    shadow = blank(lw, lh)

    x = scale
    for ch in text:
        glyph = FONT[ch]
        if ch != " ":
            for gy in range(gh):
                for gx in range(gw):
                    if glyph[gy][gx] != "1":
                        continue
                    color = rgb(GRADIENT[gy])
                    rect(canvas, x + gx * scale, scale + gy * scale, scale, scale, color)
                    rect(shadow, x + gx * scale + scale, scale + gy * scale + scale,
                         scale, scale, SHADOW_DEEP)
        x += (cell_w if ch != " " else space_w) * scale

    # composite: drop shadow behind, then the glyphs, then bevel + outline
    out = blank(lw, lh)
    for y in range(lh):
        for xx in range(lw):
            if shadow[y][xx][3] and not canvas[y][xx][3]:
                out[y][xx] = shadow[y][xx]
    for y in range(lh):
        for xx in range(lw):
            if canvas[y][xx][3]:
                out[y][xx] = canvas[y][xx]

    # per-pixel bevel: brighten cells with empty space above/left,
    # darken cells with empty space below/right (inside the glyph only).
    beveled = [row[:] for row in out]
    for y in range(lh):
        for xx in range(lw):
            if not canvas[y][xx][3]:
                continue
            up_empty = y == 0 or not canvas[y - 1][xx][3]
            left_empty = xx == 0 or not canvas[y][xx - 1][3]
            down_empty = y == lh - 1 or not canvas[y + 1][xx][3]
            right_empty = xx == lw - 1 or not canvas[y][xx + 1][3]
            if up_empty or left_empty:
                r, g, b, a = out[y][xx]
                beveled[y][xx] = (min(255, r + 55), min(255, g + 55),
                                  min(255, b + 45), a)
            elif down_empty or right_empty:
                r, g, b, a = out[y][xx]
                beveled[y][xx] = (max(0, r - 40), max(0, g - 45),
                                  max(0, b - 35), a)
    out = beveled

    # crisp corner-pixel outline around the glyph silhouette
    final = [row[:] for row in out]
    for y in range(lh):
        for xx in range(lw):
            if canvas[y][xx][3] >= 128:
                continue
            near = any(
                0 <= y + dy < lh and 0 <= xx + dx < lw and canvas[y + dy][xx + dx][3] >= 128
                for dy in (-1, 0, 1) for dx in (-1, 0, 1)
            )
            if near and not (shadow[y][xx][3] and not canvas[y][xx][3]):
                final[y][xx] = OUTLINE
    return final


# ----------------------------------------------------------------------
# Menu icons: one 16x16 glyph per button, doubled and laid out in a
# single horizontal strip so the page only needs one extra image request.
# ----------------------------------------------------------------------
ICON_ORDER = ("sword", "hourglass", "ghost", "play", "book", "gear")

ICON_GRIDS = {
    "sword": (
        ["................",
         ".............ww.",
         "............wss.",
         "...........wss..",
         "..........wss...",
         ".........wss....",
         "........wss.....",
         ".......wss......",
         "......wssg......",
         ".....mgg........",
         "....mg..........",
         "...m............",
         "................",
         "................",
         "................",
         "................"],
        {"w": "#f4f4fa", "s": "#c8d0dc", "g": "#caa53c", "m": "#6a4a2a"}),
    "hourglass": (
        ["................",
         "...gggggggg.....",
         "...gwwwwwwg.....",
         "....gwwwwg......",
         ".....gwwg.......",
         "......gg........",
         ".....gwwg.......",
         "....gwyywg......",
         "...gwyyyywg.....",
         "...gwyyyywg.....",
         "...gggggggg.....",
         "................",
         "................",
         "................",
         "................",
         "................"],
        {"g": "#8a94a4", "w": "#d8e4f0", "y": "#f2c94c"}),
    "ghost": (
        ["................",
         "....oooooo......",
         "...oeeeeeeo.....",
         "..oeeeeeeeeo....",
         "..oeeewweeeo....",
         "..oeewwwweeo....",
         "..oeeeeeeeeo....",
         "..oeeeeeeeeo....",
         "..oeeeeeeeeo....",
         "..oeeeeeeeeo....",
         "..oe.oe.oeeo....",
         "..o.oo.oo..o....",
         "................",
         "................",
         "................",
         "................"],
        {"o": "#3a3a52", "e": "#b8c2e0", "w": "#232338"}),
    "play": (
        ["................",
         "................",
         "....gg..........",
         "....ggg.........",
         "....gwgg........",
         "....gwwgg.......",
         "....gwwwgg......",
         "....gwwwwgg.....",
         "....gwwwgg......",
         "....gwwgg.......",
         "....gwgg........",
         "....ggg.........",
         "....gg..........",
         "................",
         "................",
         "................"],
        {"g": "#66d9ef", "w": "#c9f3fb"}),
    "book": (
        ["................",
         "................",
         "..rrrrr.hhhhhh..",
         "..rccccdkkkkkh..",
         "..rccccdkyyykh..",
         "..rccccdkyyykh..",
         "..rccccdkyyykh..",
         "..rccccdkyyykh..",
         "..rccccdkyyykh..",
         "..rccccdkkkkkh..",
         "..rrrrr.hhhhhh..",
         "................",
         "................",
         "................",
         "................",
         "................"],
        {"r": "#8a2a2a", "c": "#c8433f", "d": "#3a1414", "h": "#caa53c",
         "k": "#7a5a1e", "y": "#f2d98a"}),
    "gear": (
        ["................",
         ".......gg.......",
         "......gwwg......",
         "..gg..gwwg..gg..",
         ".gwwg.gwwg.gwwg.",
         ".gwwggwwwwggwwg.",
         "..gwwwweewwwwg..",
         "..gwwweeeewwwg..",
         "..gwwweeeewwwg..",
         "..gwwwweewwwwg..",
         ".gwwggwwwwggwwg.",
         ".gwwg.gwwg.gwwg.",
         "..gg..gwwg..gg..",
         "......gwwg......",
         ".......gg.......",
         "................"],
        {"g": "#8a8a95", "w": "#c4c4cf", "e": "#2a2a33"}),
}


def build_icon_strip():
    icons_px = []
    for name in ICON_ORDER:
        grid, palette = ICON_GRIDS[name]
        icons_px.append(TP.scale2x_px(grid_px(grid, palette)))  # 16 -> 32
    n = len(icons_px)
    strip = blank(32 * n, 32)
    for i, icon in enumerate(icons_px):
        blit(strip, icon, i * 32, 0)
    return strip


if __name__ == "__main__":
    scene = build_scene()
    logo = build_logo()
    icons = build_icon_strip()
    with open(os.path.join(GAME, "web", "title_bg.png"), "wb") as f:
        f.write(TP.encode_png(scene))
    with open(os.path.join(GAME, "web", "title_logo.png"), "wb") as f:
        f.write(TP.encode_png(logo))
    with open(os.path.join(GAME, "web", "title_icons.png"), "wb") as f:
        f.write(TP.encode_png(icons))
    print(f"title_bg.png {W}x{H}, title_logo.png "
          f"{len(logo[0])}x{len(logo)}, title_icons.png "
          f"{len(icons[0])}x{len(icons)} ({len(ICON_ORDER)} icons)")
