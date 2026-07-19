"""Export every built-in sprite as an editable PNG under textures/.

    python3 scripts/export_textures.py            # write missing files only
    python3 scripts/export_textures.py --force    # overwrite everything

The default mode NEVER overwrites a PNG that already exists, so your
hand-edited textures survive re-running the export after a game update
(new sprites get added alongside them). The manifest.json and README.md
are regenerated every run from what is actually on disk - they carry the
data the browser build needs (file list, hero slot colors, dim factor).

Deleting textures/ entirely just restores the built-in art everywhere.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import spritedata as S  # noqa: E402
from ui import texturepack as TP  # noqa: E402

GAME_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_TILE_KEYS = {"floor", "floor2", "floor3", "wall", "wall2", "stairs",
              "door_rune", "door_boss", "chest", "block", "lever_up",
              "lever_down", "plate_off", "plate_on", "rune_switch"}


def category_for_key(key: str) -> str:
    if key in _TILE_KEYS:
        return "tiles"
    if key in set(S.MONSTER_KEYS.values()) | {"shopkeeper"}:
        return "monsters"
    if key in set(S.ITEM_KEYS.values()):
        return "items"
    if key in set(S.TRAP_KEYS.values()):
        return "traps"
    if key in set(S.DECOR_SPRITES):
        return "decor"
    return "misc"


def _write_png(path: str, rows, force: bool, written: list, kept: list):
    if os.path.exists(path) and not force:
        kept.append(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(TP.encode_png(rows))
    written.append(path)


def export(root: str, force: bool = False) -> dict:
    written, kept = [], []

    # Every shipped sprite (already 32x32 post-Scale2x).
    for key, (grid, palette) in sorted(S.SPRITE_DEFS.items()):
        rows = TP.grid_to_px(grid, palette)
        path = os.path.join(root, category_for_key(key), f"{key}.png")
        _write_png(path, rows, force, written, kept)

    # Hero pieces, upscaled from their 16px sources the same way the game
    # ships them. Slot colors (see manifest) stay at their default RGBs so
    # the runtime recolor keeps working on edited art.
    hero_pieces = {TP.HERO_BASE_STEM: S.HERO_BASE,
                   TP.HERO_BASE_UP_STEM: S.HERO_BASE_UP,
                   TP.HERO_BASE_SIDE_STEM: S.HERO_BASE_SIDE,
                   TP.HERO_ACCESSORY_STEM: S.ACCESSORY_OVERLAY}
    for kind, overlay in S.HELD_WEAPONS.items():
        hero_pieces[f"{TP.HERO_WEAPON_PREFIX}{kind}"] = overlay
    for kind, overlay in S.HELD_WEAPONS_SIDE.items():
        hero_pieces[f"{TP.HERO_WEAPON_PREFIX}{kind}{TP.HERO_SIDE_SUFFIX}"] = overlay
    for stem, grid in sorted(hero_pieces.items()):
        rows = TP.grid_to_px(S._scale2x(grid), S.PLAYER_PALETTE)
        path = os.path.join(root, "hero", f"{stem}.png")
        _write_png(path, rows, force, written, kept)

    # Manifest + README regenerate from disk every run.
    files, hero_files = {}, {"weapons": {}, "weapons_side": {}}
    for dirpath, _d, filenames in sorted(os.walk(root)):
        for fname in sorted(filenames):
            if not fname.lower().endswith(".png"):
                continue
            stem = os.path.splitext(fname)[0]
            rel = os.path.relpath(os.path.join(dirpath, fname), root)
            if stem == TP.HERO_BASE_STEM:
                hero_files["base"] = rel
            elif stem == TP.HERO_BASE_UP_STEM:
                hero_files["base_up"] = rel
            elif stem == TP.HERO_BASE_SIDE_STEM:
                hero_files["base_side"] = rel
            elif stem == TP.HERO_ACCESSORY_STEM:
                hero_files["accessory"] = rel
            elif stem.startswith(TP.HERO_WEAPON_PREFIX):
                kind = stem[len(TP.HERO_WEAPON_PREFIX):]
                if kind.endswith(TP.HERO_SIDE_SUFFIX):
                    hero_files["weapons_side"][kind[:-len(TP.HERO_SIDE_SUFFIX)]] = rel
                else:
                    hero_files["weapons"][kind] = rel
            else:
                files[stem] = rel

    manifest = {
        "version": 1,
        "sprite_px": S.SPRITE_PX,
        "accepted_sizes": list(TP.ACCEPTED_SIZES),
        "files": files,
        "hero": hero_files,
        "slots": {
            "tunic": S.ARMOR_TUNIC_COLORS["none"],
            "blade": S.BLADE_RARITY_COLORS["common"],
            "skin": S.PLAYER_PALETTE["f"],
        },
        "colors": {
            "tunic_by_armor": S.ARMOR_TUNIC_COLORS,
            "blade_by_rarity": S.BLADE_RARITY_COLORS,
            "poisoned_skin": S.POISONED_SKIN,
        },
        "dim_factor": S.DIM_FACTOR,
        "dim_keys": list(S.DIM_TILES),
    }
    with open(os.path.join(root, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)

    with open(os.path.join(root, "README.md"), "w") as f:
        f.write(_readme(manifest))

    n_hero = (sum(1 for k in ("base", "base_up", "base_side", "accessory")
                  if hero_files.get(k))
              + len(hero_files["weapons"]) + len(hero_files["weapons_side"]))
    return {"written": written, "kept": kept, "files": len(files),
            "hero": n_hero}


def _readme(manifest: dict) -> str:
    return f"""# Endless Depths - texture pack folder

Every PNG here overrides one built-in sprite; the file's NAME (not its
folder) is the sprite it replaces. Edit with any image editor, save, and
restart the game (browser: hard refresh). Delete a file - or this whole
folder - to get the built-in art back. A broken or wrong-size file is
skipped with a console warning, never a crash.

## Rules

- Sizes allowed: 16x16 (auto-upscaled), 32x32 (native), or 64x64
  (HD - full detail in the browser, downscaled on desktop).
- Transparency: use a real alpha channel. Pixels with alpha < 128 are
  treated as fully transparent.
- Save as a normal non-interlaced PNG (every editor's default).
- Do not rename files: the stem IS the sprite key.

## The hero (textures/hero/)

The player is assembled at runtime from facing-specific pieces:
`hero_base.png` (walking down/toward you), `hero_base_up.png` (walking
away), `hero_base_side.png` (walking right - left is auto-mirrored),
plus one `weapon_*.png` overlay (front view) or `weapon_*_side.png`
(side view; no weapon shows when facing up) and `accessory.png`, then
recolored. Three exact colors in these files act as RECOLOR SLOTS -
keep using them wherever you want the dynamic colors to apply:

- tunic slot  `{manifest["slots"]["tunic"]}` - repainted by equipped armor
- blade slot  `{manifest["slots"]["blade"]}` - repainted by weapon rarity
- skin slot   `{manifest["slots"]["skin"]}` - turns green when poisoned

Any other color is left exactly as you painted it.

## Sharing a pack

Zip this folder. Installing a pack = replacing this folder's contents.
`manifest.json` and this README are regenerated by
`python3 scripts/export_textures.py`, which also restores any deleted
default PNGs without touching your edited ones.
"""


if __name__ == "__main__":
    force = "--force" in sys.argv
    root = os.environ.get(TP.PACK_ENV) or os.path.join(GAME_DIR, "textures")
    result = export(root, force=force)
    print(f"textures root: {root}")
    print(f"  wrote {len(result['written'])} PNGs, kept {len(result['kept'])} existing")
    print(f"  manifest: {result['files']} sprite files + {result['hero']} hero pieces")
    if result["kept"] and not force:
        print("  (existing files preserved - use --force to overwrite)")
