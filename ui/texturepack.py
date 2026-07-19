"""PNG texture-pack support: pure-stdlib PNG codec + pack loader.

The game's built-in art is generated from the char grids in spritedata.py.
This module lets a `textures/` folder of PNG files override any sprite:
players (or the developer) edit the PNGs with any image editor and the
game picks them up at launch - missing or invalid files silently fall
back to the built-in art, so a partial or broken pack never breaks the
game.

Toolkit-free and dependency-free (zlib + struct only, no PIL) - shared by
the desktop renderer (ui/sprites.py), the export script
(scripts/export_textures.py) and the headless tests. The browser build
does NOT import this module: it decodes PNGs natively in JS using the
manifest.json the export script writes.

Accepted PNG sizes per sprite:
    16x16 - treated as authoring resolution, auto-upscaled via Scale2x
    32x32 - native shipped resolution
    64x64 - HD; used natively in the browser, nearest-downsampled to 32
            on desktop (tk needs integer zoom factors)
Anything else is rejected with a warning and the built-in art is used.

Pixels are RGBA tuples; alpha < 128 counts as transparent.
"""
from __future__ import annotations

import os
import struct
import zlib

from .spritedata import DIM_FACTOR

PACK_ENV = "ENDLESS_DEPTHS_TEXTURES"   # test/power-user override for the root
ACCEPTED_SIZES = (16, 32, 64)

# Reserved file stems under textures/hero/ (not sprite keys): the hero is
# composed at runtime from these pieces, with slot-color remapping.
# Facing variants: hero_base is the front (down) view, hero_base_up the
# back view, hero_base_side the right-facing view (left is mirrored at
# runtime). weapon_<kind>.png overlays the front view, weapon_<kind>_side
# the side view (hidden entirely when facing up).
HERO_BASE_STEM = "hero_base"
HERO_BASE_UP_STEM = "hero_base_up"
HERO_BASE_SIDE_STEM = "hero_base_side"
HERO_ACCESSORY_STEM = "accessory"
HERO_WEAPON_PREFIX = "weapon_"   # weapon_sword.png, weapon_axe.png, ...
HERO_SIDE_SUFFIX = "_side"       # weapon_sword_side.png etc.


# ----------------------------------------------------------------------
# PNG encoding (RGBA, filter 0) - used by the export script and tests
# ----------------------------------------------------------------------
def encode_png(rows) -> bytes:
    """rows: list of lists of (r, g, b, a) tuples, all rows equal length."""
    h = len(rows)
    w = len(rows[0]) if h else 0
    raw = b"".join(
        b"\x00" + bytes(v for px in row for v in px) for row in rows
    )

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data)))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


# ----------------------------------------------------------------------
# PNG decoding - the subset real editors produce for pixel art:
# 8-bit, non-interlaced; grayscale (0), RGB (2), palette (3, with
# optional tRNS), grayscale+alpha (4) and RGBA (6); all five scanline
# filters. Everything else raises ValueError with a clear message.
# ----------------------------------------------------------------------
_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def decode_png(data: bytes):
    """Returns rows of (r, g, b, a) tuples. Raises ValueError on
    unsupported or corrupt input."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    pos = 8
    ihdr = None
    idat = []
    plte = b""
    trns = b""
    while pos < len(data):
        if pos + 8 > len(data):
            raise ValueError("truncated PNG")
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif tag == b"PLTE":
            plte = body
        elif tag == b"tRNS":
            trns = body
        elif tag == b"IDAT":
            idat.append(body)
        elif tag == b"IEND":
            break
    if ihdr is None or not idat:
        raise ValueError("PNG missing IHDR/IDAT")
    w, h, bit_depth, color_type, compression, filt, interlace = ihdr
    if bit_depth != 8:
        raise ValueError(f"unsupported bit depth {bit_depth} (need 8-bit)")
    if color_type not in _CHANNELS:
        raise ValueError(f"unsupported color type {color_type}")
    if interlace:
        raise ValueError("interlaced (Adam7) PNGs are not supported - "
                         "re-save without interlacing")
    if compression or filt:
        raise ValueError("nonstandard PNG compression/filter method")

    nch = _CHANNELS[color_type]
    stride = w * nch
    raw = zlib.decompress(b"".join(idat))
    if len(raw) != (stride + 1) * h:
        raise ValueError("PNG pixel data has the wrong length")

    # Undo scanline filters.
    out = bytearray()
    prev = bytearray(stride)
    for y in range(h):
        base = y * (stride + 1)
        ftype = raw[base]
        line = bytearray(raw[base + 1:base + 1 + stride])
        if ftype == 0:
            pass
        elif ftype == 1:    # Sub
            for i in range(nch, stride):
                line[i] = (line[i] + line[i - nch]) & 0xFF
        elif ftype == 2:    # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:    # Average
            for i in range(stride):
                left = line[i - nch] if i >= nch else 0
                line[i] = (line[i] + (left + prev[i]) // 2) & 0xFF
        elif ftype == 4:    # Paeth
            for i in range(stride):
                a = line[i - nch] if i >= nch else 0
                b = prev[i]
                c = prev[i - nch] if i >= nch else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 0xFF
        else:
            raise ValueError(f"unknown PNG filter type {ftype}")
        out += line
        prev = line

    # Expand to RGBA rows.
    pal = [tuple(plte[i:i + 3]) for i in range(0, len(plte), 3)]
    rows = []
    for y in range(h):
        row = []
        base = y * stride
        for x in range(w):
            o = base + x * nch
            if color_type == 6:
                px = (out[o], out[o + 1], out[o + 2], out[o + 3])
            elif color_type == 2:
                px = (out[o], out[o + 1], out[o + 2], 255)
            elif color_type == 0:
                v = out[o]
                px = (v, v, v, 255)
            elif color_type == 4:
                v = out[o]
                px = (v, v, v, out[o + 1])
            else:  # 3: palette
                idx = out[o]
                if idx >= len(pal):
                    raise ValueError("palette index out of range")
                r, g, b = pal[idx]
                a = trns[idx] if idx < len(trns) else 255
                px = (r, g, b, a)
            row.append(px)
        rows.append(row)
    return rows


# ----------------------------------------------------------------------
# Pixel helpers
# ----------------------------------------------------------------------
def scale2x_px(rows):
    """Scale2x/EPX on RGBA pixel rows - the pixel-tuple twin of
    spritedata._scale2x (which works on palette-char strings)."""
    h = len(rows)
    w = len(rows[0]) if h else 0
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
    return out


def downsample2x_px(rows):
    """Nearest-neighbor 2x downsample (64 -> 32 for the desktop renderer)."""
    return [row[::2] for row in rows[::2]]


def darken_px(rows, factor: float = DIM_FACTOR):
    """Dim-variant pixels; matches spritedata._darken so packed and
    built-in tiles dim identically side by side."""
    return [[(int(r * factor), int(g * factor), int(b * factor), a)
             for (r, g, b, a) in row] for row in rows]


def remap_px(rows, mapping):
    """Exact-RGB color-slot remapping. mapping: {(r,g,b): (r,g,b)}.
    Alpha is preserved; only fully-matching RGB values are swapped."""
    if not mapping:
        return rows
    return [[(*(mapping.get((r, g, b), (r, g, b))), a)
             for (r, g, b, a) in row] for row in rows]


def compose_px(base, *overlays):
    """Paste overlays onto a copy of base; overlay pixels with alpha >= 128
    win. All layers must share dimensions."""
    out = [list(row) for row in base]
    for overlay in overlays:
        if not overlay:
            continue
        for y, row in enumerate(overlay):
            for x, px in enumerate(row):
                if px[3] >= 128:
                    out[y][x] = px
    return out


def hex_to_rgb(hex_color: str):
    return (int(hex_color[1:3], 16), int(hex_color[3:5], 16),
            int(hex_color[5:7], 16))


def grid_to_px(grid, palette):
    """Render a spritedata char grid + palette to RGBA pixel rows."""
    from .spritedata import MISSING
    rows = []
    for grow in grid:
        row = []
        for ch in grow:
            if ch == ".":
                row.append((0, 0, 0, 0))
            else:
                row.append((*hex_to_rgb(palette.get(ch, MISSING)), 255))
        rows.append(row)
    return rows


# ----------------------------------------------------------------------
# Pack loading
# ----------------------------------------------------------------------
def pack_root() -> str:
    """The textures/ folder next to the game (or the env override)."""
    override = os.environ.get(PACK_ENV)
    if override:
        return override
    game_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(game_dir, "textures")


def _normalize(rows, for_desktop: bool):
    """Bring accepted sizes to the renderer's native resolution."""
    size = len(rows)
    if size == 16:
        return scale2x_px(rows)
    if size == 64 and for_desktop:
        return downsample2x_px(rows)
    return rows


def load_pack(root: str | None = None, for_desktop: bool = True):
    """Scan the pack folder. Returns (sprites, hero, warnings):
        sprites:  {sprite_key: pixel rows}   (normalized per renderer)
        hero:     {"base": rows, "accessory": rows, "weapons": {kind: rows}}
        warnings: [str, ...]  (bad files - already skipped, never fatal)
    Folder layout is organizational only: any *.png anywhere under the
    root is keyed by its file stem. Reserved hero stems are split out."""
    root = root or pack_root()
    sprites: dict = {}
    hero: dict = {"base": None, "base_up": None, "base_side": None,
                  "accessory": None, "weapons": {}, "weapons_side": {}}
    warnings: list = []
    if not os.path.isdir(root):
        return sprites, hero, warnings

    seen: dict = {}
    for dirpath, _dirnames, filenames in sorted(os.walk(root)):
        for fname in sorted(filenames):
            if not fname.lower().endswith(".png"):
                continue
            stem = os.path.splitext(fname)[0]
            path = os.path.join(dirpath, fname)
            if stem in seen:
                warnings.append(f"{path}: duplicate of {seen[stem]} - ignored")
                continue
            seen[stem] = path
            try:
                with open(path, "rb") as f:
                    rows = decode_png(f.read())
            except (OSError, ValueError, zlib.error) as exc:
                warnings.append(f"{path}: {exc} - using built-in art")
                continue
            size = len(rows)
            if size not in ACCEPTED_SIZES or any(len(r) != size for r in rows):
                warnings.append(
                    f"{path}: {len(rows[0]) if rows else 0}x{size} - textures "
                    f"must be square 16, 32 or 64 px - using built-in art")
                continue
            rows = _normalize(rows, for_desktop)
            if stem == HERO_BASE_STEM:
                hero["base"] = rows
            elif stem == HERO_BASE_UP_STEM:
                hero["base_up"] = rows
            elif stem == HERO_BASE_SIDE_STEM:
                hero["base_side"] = rows
            elif stem == HERO_ACCESSORY_STEM:
                hero["accessory"] = rows
            elif stem.startswith(HERO_WEAPON_PREFIX):
                kind = stem[len(HERO_WEAPON_PREFIX):]
                if kind.endswith(HERO_SIDE_SUFFIX):
                    hero["weapons_side"][kind[:-len(HERO_SIDE_SUFFIX)]] = rows
                else:
                    hero["weapons"][kind] = rows
            else:
                sprites[stem] = rows
    return sprites, hero, warnings
