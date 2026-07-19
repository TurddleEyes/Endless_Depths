#!/usr/bin/env bash
# Packages the Endless Depths browser build (Pyodide/WebAssembly, no build
# step) into an itch.io-ready zip: index.html at the ZIP ROOT, containing
# only the files the web build actually needs.
#
# Usage:
#   ./scripts/build_itch_zip.sh
#
# Output:
#   dist/endless-depths-itch.zip
set -euo pipefail

err() {
    printf 'ERROR: %s\n' "$1" >&2
    exit 1
}

# Locate the repo root from the script's own location, not the caller's
# cwd (mirrors the __file__-based root-finding already used by
# scripts/smoke_test.py / scripts/web_smoke_test.py).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

for marker in index.html web engine ui; do
    [ -e "$REPO_ROOT/$marker" ] || \
        err "'$REPO_ROOT' doesn't look like the Endless Depths repo root (missing '$marker')."
done

for bin in zip unzip zipinfo; do
    command -v "$bin" >/dev/null 2>&1 || \
        err "'$bin' is required but not on PATH (try: sudo apt install zip unzip)."
done

# Authoritative set of files the web build needs. Paths are relative to
# REPO_ROOT and reused verbatim as the zip's internal paths.
#
# Deliberately excluded: game.py, ui/app.py, ui/sprites.py, ui/theme.py,
# ui/widgets.py (desktop-tkinter only), assets/ (desktop wav cache,
# regenerated at runtime, gitignored), save.json/settings.json/
# highscores.json (local dev state), scripts/, .git, __pycache__/,
# .nojekyll, README.md, GUIDE.html (standalone manual, not linked from
# index.html/main.js -- not part of the runnable game; add it below
# explicitly if that ever changes).
FILES=(
    index.html
    web/main.js
    web/style.css
    web/webbridge.py
    web/title_bg.png
    web/title_logo.png
    web/title_icons.png
    engine/__init__.py
    engine/combat.py
    engine/constants.py
    engine/dungeon.py
    engine/entities.py
    engine/fov.py
    engine/items.py
    engine/puzzles.py
    engine/replay.py
    engine/save.py
    engine/shop.py
    engine/world.py
    ui/__init__.py
    ui/spritedata.py
    ui/iteminfo.py
    ui/audio.py
    ui/lore.py
)

MISSING=()
for f in "${FILES[@]}"; do
    [ -f "$REPO_ROOT/$f" ] || MISSING+=("$f")
done
if [ "${#MISSING[@]}" -gt 0 ]; then
    printf 'ERROR: %d required source file(s) missing:\n' "${#MISSING[@]}" >&2
    printf '  %s\n' "${MISSING[@]}" >&2
    exit 1
fi

STAGING_DIR="$REPO_ROOT/dist/_staging"
OUT_ZIP="$REPO_ROOT/dist/endless-depths-itch.zip"

# Fresh staging dir every run so a file dropped from FILES in the past can
# never linger into a new zip.
rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"

echo "Staging ${#FILES[@]} files ..."
for f in "${FILES[@]}"; do
    mkdir -p "$STAGING_DIR/$(dirname "$f")"
    cp -p "$REPO_ROOT/$f" "$STAGING_DIR/$f"
done

# Texture pack (PNG overrides + manifest): shipped when present. The web
# build reads textures/manifest.json at boot and silently skips it if the
# folder was never exported.
if [ -f "$REPO_ROOT/textures/manifest.json" ]; then
    TEX_COUNT="$(find "$REPO_ROOT/textures" -name '*.png' | wc -l)"
    echo "Staging texture pack ($TEX_COUNT PNGs + manifest) ..."
    mkdir -p "$STAGING_DIR/textures"
    cp -rp "$REPO_ROOT/textures/." "$STAGING_DIR/textures/"
fi

# Always delete any previous zip first: `zip -r` merges into an existing
# archive rather than replacing it, which could leave stale entries behind
# even with a clean staging dir.
mkdir -p "$(dirname "$OUT_ZIP")"
rm -f "$OUT_ZIP"

echo "Building $(basename "$OUT_ZIP") ..."
# Zip-root trick: cd INTO the staging dir and zip "." from there, so
# entries come out as "index.html", "web/main.js" -- never
# "_staging/index.html". Zipping "_staging/" from the repo root would
# nest everything a level deep, which itch.io rejects.
( cd "$STAGING_DIR" && zip -rq -D -X "$OUT_ZIP" . )

# Verify the zip actually came out right instead of trusting the
# technique blindly.
zipinfo -1 "$OUT_ZIP" | grep -qx 'index.html' || \
    err "packaging bug: index.html is not at the zip root in $OUT_ZIP"
zipinfo -1 "$OUT_ZIP" | grep -q '^_staging/' && \
    err "packaging bug: zip entries are nested under _staging/ in $OUT_ZIP"

# Report against itch.io's HTML5 limits (1,000 files / 500MB total /
# 200MB per file). Exceeding a hard limit fails the build -- a zip itch
# would reject isn't a successful build.
ENTRY_COUNT="$(zipinfo -1 "$OUT_ZIP" | wc -l)"
TOTAL_BYTES="$(stat -c%s "$OUT_ZIP")"
LARGEST_FILE="" LARGEST_BYTES=0
for f in "${FILES[@]}"; do
    sz="$(stat -c%s "$REPO_ROOT/$f")"
    [ "$sz" -gt "$LARGEST_BYTES" ] && LARGEST_BYTES="$sz" LARGEST_FILE="$f"
done

MAX_FILES=1000
MAX_TOTAL_BYTES=$((500 * 1024 * 1024))
MAX_FILE_BYTES=$((200 * 1024 * 1024))

[ "$ENTRY_COUNT" -le "$MAX_FILES" ]       || err "$ENTRY_COUNT files exceeds itch.io's $MAX_FILES-file limit"
[ "$TOTAL_BYTES" -le "$MAX_TOTAL_BYTES" ] || err "zip is $TOTAL_BYTES bytes, exceeds itch.io's 500MB limit"
[ "$LARGEST_BYTES" -le "$MAX_FILE_BYTES" ] || err "$LARGEST_FILE is $LARGEST_BYTES bytes, exceeds itch.io's 200MB/file limit"

echo
echo "Build OK: dist/$(basename "$OUT_ZIP")"
printf '  Files:        %s  (itch.io limit: %s)\n' "$ENTRY_COUNT" "$MAX_FILES"
printf '  Total size:   %s / %s bytes  (itch.io limit: 500MB)\n' \
    "$(numfmt --to=iec "$TOTAL_BYTES")" "$TOTAL_BYTES"
printf '  Largest file: %s - %s  (itch.io limit: 200MB/file)\n' \
    "$LARGEST_FILE" "$(numfmt --to=iec "$LARGEST_BYTES")"
