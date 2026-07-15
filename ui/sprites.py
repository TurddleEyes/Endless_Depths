"""Tkinter sprite construction on top of the pure-data grids in spritedata.py.

All pixel grids, palettes, and key mappings live in ui/spritedata.py (which
has no tkinter dependency, so the browser build can share it). This module
only turns those grids into tk.PhotoImage objects.
"""
from __future__ import annotations

import tkinter as tk

from .spritedata import *  # noqa: F401,F403 - re-export grids/keys for app.py
from .spritedata import _darken


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


def build_sprites(zoom: int = 2) -> dict:
    """Build every sprite (plus dim tile variants). Requires a Tk root."""
    sprites = {}
    for key, (grid, palette) in SPRITE_DEFS.items():
        sprites[key] = _build_image(grid, palette, zoom)
        if key in DIM_TILES:
            dim_palette = {ch: _darken(color) for ch, color in palette.items()}
            sprites[key + "_dim"] = _build_image(grid, dim_palette, zoom)
    return sprites


def build_sprite(key: str, zoom: int) -> tk.PhotoImage:
    """Build a single sprite at an arbitrary zoom (e.g. a big title-screen hero)."""
    grid, palette = SPRITE_DEFS[key]
    return _build_image(grid, palette, zoom)


def build_hero(weapon="sword", armor="none", accessory=False, poisoned=False,
                weapon_rarity="common", zoom: int = 2) -> tk.PhotoImage:
    """Build the hero sprite reflecting current equipment and status."""
    grid, palette = hero_grid_and_palette(weapon, armor, accessory, poisoned, weapon_rarity)
    return _build_image(grid, palette, zoom)
