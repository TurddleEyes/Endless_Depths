"""Export every built-in sprite as an editable PNG under textures/.

    python3 scripts/export_textures.py            # write missing files only
    python3 scripts/export_textures.py --force    # overwrite everything

The default mode NEVER overwrites a PNG that already exists, so your
hand-edited textures survive re-running the export after a game update
(new sprites get added alongside them). The manifest.json and README.md
are regenerated every run from what is actually on disk - they carry the
data the browser build needs (file list, hero slot colors, dim factor).

Deleting textures/ entirely just restores the built-in art everywhere.

The actual export logic lives in ui/texturepack.py (write_pack_to_dir),
shared with the in-app "Export Texture Pack" button on both front-ends -
this script is just a thin CLI wrapper around it.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import texturepack as TP  # noqa: E402

GAME_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


if __name__ == "__main__":
    force = "--force" in sys.argv
    root = os.environ.get(TP.PACK_ENV) or os.path.join(GAME_DIR, "textures")
    result = TP.write_pack_to_dir(root, force=force)
    print(f"textures root: {root}")
    print(f"  wrote {len(result['written'])} PNGs, kept {len(result['kept'])} existing")
    print(f"  manifest: {result['files']} sprite files + {result['hero']} hero pieces")
    if result["kept"] and not force:
        print("  (existing files preserved - use --force to overwrite)")
