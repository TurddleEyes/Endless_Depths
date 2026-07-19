"""Tkinter sprite construction on top of the pure-data grids in spritedata.py.

All pixel grids, palettes, and key mappings live in ui/spritedata.py (which
has no tkinter dependency, so the browser build can share it). This module
only turns those grids into tk.PhotoImage objects.

If a textures/ folder is present (see ui/texturepack.py), its PNGs override
the built-in grids sprite-by-sprite; anything missing or invalid falls back
to the generated art.
"""
from __future__ import annotations

import sys

import tkinter as tk

from .spritedata import *  # noqa: F401,F403 - re-export grids/keys for app.py
from .spritedata import _darken, _scale2x
from . import texturepack as TP

# One pack scan per process; warnings surface once on stderr.
_PACK_SPRITES, _PACK_HERO, _PACK_WARNINGS = TP.load_pack(for_desktop=True)
for _w in _PACK_WARNINGS:
    print(f"texture pack: {_w}", file=sys.stderr)


def _build_image(grid, palette, zoom: int) -> tk.PhotoImage:
    img = tk.PhotoImage(width=SPRITE_PX, height=SPRITE_PX)
    rows = list(grid[:SPRITE_PX])
    while len(rows) < SPRITE_PX:
        rows.append("." * SPRITE_PX)
    for y, row in enumerate(rows):
        row = (row + "." * SPRITE_PX)[:SPRITE_PX]
        x = 0
        while x < SPRITE_PX:
            if row[x] == ".":
                x += 1
                continue
            x0 = x
            run = []
            while x < SPRITE_PX and row[x] != ".":
                run.append(palette.get(row[x], MISSING))
                x += 1
            img.put("{" + " ".join(run) + "}", to=(x0, y))
    if zoom > 1:
        img = img.zoom(zoom, zoom)
    return img


def _build_image_px(rows, zoom: int) -> tk.PhotoImage:
    """PhotoImage from RGBA pixel rows (texture-pack path). Same row-run
    put() technique as _build_image; alpha < 128 = transparent."""
    size = len(rows)
    img = tk.PhotoImage(width=size, height=size)
    for y, row in enumerate(rows):
        x = 0
        while x < size:
            if row[x][3] < 128:
                x += 1
                continue
            x0 = x
            run = []
            while x < size and row[x][3] >= 128:
                r, g, b, _a = row[x]
                run.append(f"#{r:02x}{g:02x}{b:02x}")
                x += 1
            img.put("{" + " ".join(run) + "}", to=(x0, y))
    if zoom > 1:
        img = img.zoom(zoom, zoom)
    return img


def build_sprites(zoom: int = 2) -> dict:
    """Build every sprite (plus dim tile variants). Requires a Tk root."""
    sprites = {}
    for key, (grid, palette) in SPRITE_DEFS.items():
        pack = _PACK_SPRITES.get(key)
        if pack is not None:
            sprites[key] = _build_image_px(pack, zoom)
            if key in DIM_TILES:
                sprites[key + "_dim"] = _build_image_px(TP.darken_px(pack), zoom)
            continue
        sprites[key] = _build_image(grid, palette, zoom)
        if key in DIM_TILES:
            dim_palette = {ch: _darken(color) for ch, color in palette.items()}
            sprites[key + "_dim"] = _build_image(grid, dim_palette, zoom)
    return sprites


def build_sprite(key: str, zoom: int) -> tk.PhotoImage:
    """Build a single sprite at an arbitrary zoom (e.g. a big title-screen hero)."""
    pack = _PACK_SPRITES.get(key)
    if pack is not None:
        return _build_image_px(pack, zoom)
    grid, palette = SPRITE_DEFS[key]
    return _build_image(grid, palette, zoom)


def _hero_piece_px(pack_rows, fallback_grid):
    """A hero layer from the pack, or the built-in grid rendered to pixels
    at shipped resolution - so packs may override any subset of pieces."""
    if pack_rows is not None:
        return pack_rows
    return TP.grid_to_px(_scale2x(fallback_grid), PLAYER_PALETTE)


def build_hero(weapon="sword", armor="none", accessory=False, poisoned=False,
                weapon_rarity="common", zoom: int = 2,
                facing: str = "down") -> tk.PhotoImage:
    """Build the hero sprite reflecting current equipment, status and the
    direction of the last step taken."""
    if _PACK_HERO["base"] is None:
        grid, palette = hero_grid_and_palette(weapon, armor, accessory,
                                               poisoned, weapon_rarity, facing)
        return _build_image(grid, palette, zoom)

    layers = []
    if facing == "up":
        layers.append(_hero_piece_px(_PACK_HERO["base_up"], HERO_BASE_UP))
    elif facing in ("left", "right"):
        layers.append(_hero_piece_px(_PACK_HERO["base_side"], HERO_BASE_SIDE))
        if weapon != "none":
            layers.append(_hero_piece_px(
                _PACK_HERO["weapons_side"].get(weapon),
                HELD_WEAPONS_SIDE.get(weapon, HELD_SWORD_SIDE)))
        if accessory:
            layers.append(_hero_piece_px(_PACK_HERO["accessory"], ACCESSORY_OVERLAY))
    else:
        layers.append(_hero_piece_px(_PACK_HERO["base"], HERO_BASE))
        if weapon != "none":
            layers.append(_hero_piece_px(_PACK_HERO["weapons"].get(weapon),
                                         HELD_WEAPONS.get(weapon, HELD_SWORD)))
        if accessory:
            layers.append(_hero_piece_px(_PACK_HERO["accessory"], ACCESSORY_OVERLAY))
    composed = TP.compose_px(*layers)
    if facing == "left":
        composed = [row[::-1] for row in composed]

    mapping = {}
    tunic_color = ARMOR_TUNIC_COLORS.get(armor, ARMOR_TUNIC_COLORS["none"])
    blade_color = BLADE_RARITY_COLORS.get(weapon_rarity, BLADE_RARITY_COLORS["common"])
    if tunic_color != ARMOR_TUNIC_COLORS["none"]:
        mapping[TP.hex_to_rgb(ARMOR_TUNIC_COLORS["none"])] = TP.hex_to_rgb(tunic_color)
    if blade_color != BLADE_RARITY_COLORS["common"]:
        mapping[TP.hex_to_rgb(BLADE_RARITY_COLORS["common"])] = TP.hex_to_rgb(blade_color)
    if poisoned:
        mapping[TP.hex_to_rgb(PLAYER_PALETTE["f"])] = TP.hex_to_rgb(POISONED_SKIN)
    return _build_image_px(TP.remap_px(composed, mapping), zoom)
