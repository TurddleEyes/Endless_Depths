/* Endless Depths - browser front-end.
 * Loads the pure-Python game engine into Pyodide (WebAssembly) and renders
 * it on a canvas. All game logic stays in Python (web/webbridge.py); this
 * file is rendering, input, audio playback and localStorage persistence.
 */
"use strict";

const TILE = 32;
const SPRITE_PX = 32; // grids ship at 32x32 (Scale2x'd from 16x16 sources in ui/spritedata.py)

const IS_TOUCH = window.matchMedia("(pointer: coarse)").matches || "ontouchstart" in window;

// The whole game renders at ONE fixed logical resolution per orientation -
// 1600x900 (16:9) landscape or 900x1600 (9:16) portrait - picked from the
// real window's aspect ratio (not a width breakpoint, so e.g. a phone
// turned sideways gets the landscape layout, and a narrow desktop window
// gets the portrait one). #stage (see index.html/style.css) is uniformly
// scaled via fitStage() to fit whatever the real viewport is - that's the
// ONE mechanism for both "responsive" and "fullscreen"; fullscreen is just
// a bigger scale factor through the same code path, not a separate one.
const STAGE_SIZES = { landscape: [1600, 900], portrait: [900, 1600] };
let orientation = null; // null (not "landscape") guarantees updateOrientation()'s
                         // change-check fires on its very first call at boot
let VIEW_COLS = 26;
let VIEW_ROWS = 16;

function pickOrientation() {
  return window.innerWidth >= window.innerHeight ? "landscape" : "portrait";
}

const PY_FILES = [
  "engine/__init__.py", "engine/bosses.py", "engine/constants.py", "engine/combat.py",
  "engine/dungeon.py", "engine/entities.py", "engine/fov.py",
  "engine/achievements.py", "engine/biomes.py", "engine/items.py", "engine/puzzles.py", "engine/replay.py",
  "engine/save.py", "engine/shop.py", "engine/status.py", "engine/traits.py",
  "engine/lorepages.py", "engine/world.py",
  "ui/__init__.py", "ui/spritedata.py", "ui/iteminfo.py", "ui/audio.py", "ui/lore.py",
  "ui/texturepack.py",
];

const LS_SAVE = "endless_depths_save";
const LS_SCORES = "endless_depths_scores";
const LS_SPEEDRUN_SCORES = "endless_depths_speedrun_scores";
const LS_DAILY = "endless_depths_daily";      // {date, played, depth} - one attempt/day lock
const LS_HISTORY = "endless_depths_history";  // last N runs of any mode, newest first
const HISTORY_MAX = 20;
const LS_SEEN_LORE = "endless_depths_seen_lore";
const LS_SETTINGS = "endless_depths_settings";

const gameSettings = (() => {
  let s = {};
  try { s = JSON.parse(localStorage.getItem(LS_SETTINGS)) || {}; } catch {}
  // Migrate the old single mute flag.
  const legacyMuted = localStorage.getItem("endless_depths_muted") === "1";
  return {
    music_on: s.music_on ?? !legacyMuted,
    sfx_on: s.sfx_on ?? !legacyMuted,
    shake_on: s.shake_on ?? true,
    dpad_on: s.dpad_on ?? false, // tap-to-move is the default; D-pad is the fallback
    feed_mode: s.feed_mode ?? "toasts", // "toasts" (default) or "log" for the message feed
  };
})();

function persistSettings() {
  localStorage.setItem(LS_SETTINGS, JSON.stringify(gameSettings));
}

const REPLAY_SPEEDS = [["1x", 130], ["2x", 45]]; // third press skips to end

let bridge = null;
let atlas = {};            // sprite key -> offscreen canvas
let heroCache = {};        // variant key -> offscreen canvas
let floorData = null;
let snap = null;
let mode = "title";
let cam = { x: 0, y: 0 };
let lastEventTypes = new Set(); // event types from the most recent snapshot

/* Procedural animation state: hero facing follows the last step taken;
 * monsters sway on a slow ambient tick; attacks play a short lunge. */
const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const LUNGE_MS = 200;
let heroFacing = "down";
let animTick = 0;
let lunges = [];        // { who: "hero" | "x,y", dx, dy, t0 }
let lungePumping = false;

function noteFacing(dx, dy) {
  if (dx || dy) {
    heroFacing = dx < 0 ? "left" : dx > 0 ? "right" : dy < 0 ? "up" : "down";
  }
}

function addLunge(who, dx, dy) {
  if (REDUCED_MOTION || (!dx && !dy)) return;
  lunges.push({ who, dx, dy, t0: performance.now() });
  if (!lungePumping) {
    lungePumping = true;
    requestAnimationFrame(pumpLunges);
  }
}

function pumpLunges() {
  const now = performance.now();
  lunges = lunges.filter((l) => now - l.t0 < LUNGE_MS);
  if (mode === "play" || mode === "dying") render();
  if (lunges.length) {
    requestAnimationFrame(pumpLunges);
  } else {
    lungePumping = false;
  }
}

function lungeOffsets() {
  const now = performance.now();
  let heroOff = [0, 0];
  const monsterOffs = {};
  for (const l of lunges) {
    const p = Math.min(1, (now - l.t0) / LUNGE_MS);
    const off = Math.round(Math.sin(p * Math.PI) * 9);
    if (l.who === "hero") heroOff = [l.dx * off, l.dy * off];
    else monsterOffs[l.who] = [l.dx * off, l.dy * off];
  }
  return { heroOff, monsterOffs };
}

setInterval(() => {
  if (REDUCED_MOTION || document.hidden) return;
  if (mode === "play" && snap && floorData && !lunges.length) {
    animTick++;
    render();
  }
}, 420);
let categoryLabels = {}; // category -> display label, fetched once at boot

// Run timing + replay playback state
let liveRun = true;        // false while watching a replay - gates all persistence
let runStartedAt = 0;
let elapsedAtEnd = 0;
let timerInterval = null;
let replayTimer = null;
let replayPaused = false;
let replaySpeedIdx = 0;

function fmtTime(seconds) {
  seconds = Math.max(0, Math.floor(seconds));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
           : `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function finalElapsed() {
  return elapsedAtEnd || (performance.now() - runStartedAt) / 1000;
}

const $ = (id) => document.getElementById(id);
const canvas = $("game-canvas");
const ctx = canvas.getContext("2d");
const minimap = $("minimap");
const mmCtx = minimap.getContext("2d");

if (IS_TOUCH) $("touch-controls").classList.add("enabled");
if (!IS_TOUCH) $("setting-dpad").classList.add("hidden");

// The D-pad is opt-in. It's now a big, semi-transparent overlay that FLOATS
// over the bottom of the play area (see the CSS) rather than sitting in a
// reserved band, so enabling it no longer shrinks the map - portrait keeps
// the full 15x17 viewport either way. (landscape is always a fixed 26x16.)
function applyDpadSetting() {
  const on = IS_TOUCH && gameSettings.dpad_on;
  $("dpad").classList.toggle("hidden", !on);
  document.body.classList.toggle("dpad-off", !on);
  VIEW_COLS = orientation === "landscape" ? 26 : 15;
  VIEW_ROWS = orientation === "landscape" ? 16 : 17;
  const w = VIEW_COLS * TILE, h = VIEW_ROWS * TILE;
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
    if (snap && floorData) render();
  }
}

// Messages feed: "toasts" (default) hides the persistent log and surfaces
// gains as transient right-side popups; "log" shows the classic bottom log
// and suppresses toasts. Purely presentational - it's just a body class the
// CSS keys off of, plus the guard showToast() checks.
function applyFeedSetting() {
  document.body.classList.toggle("feed-toasts", gameSettings.feed_mode === "toasts");
}
applyFeedSetting();

// Single entry point for both orientation switches and window resizes:
// picks landscape/portrait from the real aspect ratio, flips the body
// classes the CSS keys off of, resizes the tile grid if orientation
// actually changed, and rescales #stage to fit.
function updateOrientation() {
  const next = pickOrientation();
  const changed = next !== orientation;
  orientation = next;
  document.body.classList.toggle("landscape", orientation === "landscape");
  document.body.classList.toggle("portrait", orientation === "portrait");
  if (changed) applyDpadSetting();
  fitStage();
}
updateOrientation();
window.addEventListener("resize", updateOrientation);
window.addEventListener("orientationchange", updateOrientation);

/* ---------------------------------------------------------------- boot */
async function boot() {
  const status = $("loading-status");
  status.textContent = "Loading Python engine…";
  const pyodide = await loadPyodide();

  status.textContent = "Loading game code…";
  pyodide.FS.mkdirTree("/game/engine");
  pyodide.FS.mkdirTree("/game/ui");
  // cache: "no-cache" revalidates with the server (ETag) on every load, so
  // a stale cached engine can never mismatch a freshly deployed one.
  for (const path of PY_FILES) {
    const resp = await fetch(path, { cache: "no-cache" });
    if (!resp.ok) throw new Error("failed to fetch " + path);
    pyodide.FS.writeFile("/game/" + path, await resp.text());
  }
  const wb = await fetch("web/webbridge.py", { cache: "no-cache" });
  pyodide.FS.writeFile("/game/webbridge.py", await wb.text());
  pyodide.runPython("import sys; sys.path.insert(0, '/game')");
  bridge = pyodide.pyimport("webbridge");

  status.textContent = "Building sprites…";
  buildAtlas(JSON.parse(bridge.sprite_atlas_json()));
  await applyTexturePack(); // PNG overrides, if a textures/ folder is deployed
  drawTitleHero();
  categoryLabels = JSON.parse(bridge.category_labels_json());

  status.textContent = "";
  $("title-buttons").classList.remove("hidden");
  $("btn-continue").disabled = !localStorage.getItem(LS_SAVE);
  renderTitleHighscores();

  lore.data = JSON.parse(bridge.lore_json());
  $("lore-title").textContent = lore.data.title;

  // Title flair: a lineup of the things waiting below, plus rotating
  // taglines from the shared lore module.
  const monsterRow = $("title-monsters");
  for (const key of ["rat", "goblin", "skeleton", "wraith", "knight", "lich"]) {
    const c = document.createElement("canvas");
    c.width = 48;
    c.height = 48;
    const g = c.getContext("2d");
    g.imageSmoothingEnabled = false;
    drawSpriteCentered(g, atlas[key], 48, 48, 4);
    monsterRow.appendChild(c);
  }
  let taglineIdx = 0;
  setInterval(() => {
    if (mode === "title" && lore.data.taglines) {
      taglineIdx = (taglineIdx + 1) % lore.data.taglines.length;
      $("title-tagline").textContent = lore.data.taglines[taglineIdx];
    }
  }, 3000);

  if (!localStorage.getItem(LS_SEEN_LORE)) {
    showLore(true);
  } else {
    toTitle();
  }

  audio.init();
}

/* ------------------------------------------------------------- sprites */
// Sprites are authored with varying amounts of transparent padding baked
// into their grid (a ghost with a long trailing hem, a squat rat, a tall
// knight) - drawing the full source square into a fixed box therefore
// centers each sprite's CANVAS, not its actual silhouette, so a lineup of
// them (e.g. the title screen) reads as inconsistently placed. This finds
// the opaque bounding box and fits+centers THAT instead.
const spriteBBoxCache = new Map();

function spriteOpaqueBBox(src) {
  if (spriteBBoxCache.has(src)) return spriteBBoxCache.get(src);
  const w = src.width, h = src.height;
  const data = src.getContext("2d").getImageData(0, 0, w, h).data;
  let minX = w, minY = h, maxX = -1, maxY = -1;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      if (data[(y * w + x) * 4 + 3] > 10) {
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;
      }
    }
  }
  const box = maxX < minX ? { x: 0, y: 0, w, h } // fully transparent: fall back
    : { x: minX, y: minY, w: maxX - minX + 1, h: maxY - minY + 1 };
  spriteBBoxCache.set(src, box);
  return box;
}

function drawSpriteCentered(ctx, src, dw, dh, pad = 0) {
  const box = spriteOpaqueBBox(src);
  const availW = dw - pad * 2, availH = dh - pad * 2;
  const scale = Math.min(availW / box.w, availH / box.h);
  const w = box.w * scale, h = box.h * scale;
  ctx.drawImage(src, box.x, box.y, box.w, box.h,
                (dw - w) / 2, (dh - h) / 2, w, h);
}

function spriteCanvas(grid, palette) {
  const c = document.createElement("canvas");
  c.width = SPRITE_PX;
  c.height = SPRITE_PX;
  const g = c.getContext("2d");
  for (let y = 0; y < Math.min(grid.length, SPRITE_PX); y++) {
    const row = grid[y];
    for (let x = 0; x < Math.min(row.length, SPRITE_PX); x++) {
      const ch = row[x];
      if (ch === ".") continue;
      g.fillStyle = palette[ch] || "#ff00ff";
      g.fillRect(x, y, 1, 1);
    }
  }
  return c;
}

function buildAtlas(data) {
  for (const [key, def] of Object.entries(data)) {
    atlas[key] = spriteCanvas(def.grid, def.palette);
  }
}

/* ------------------------------------------------------- texture pack */
// A textures/ folder of PNGs (exported/edited by the developer or a pack
// author) overrides built-in sprites one file at a time. Anything missing
// or invalid keeps the generated art. See scripts/export_textures.py.
const texPack = { hero: null, manifest: null };

function imageToCanvas(img) {
  const c = document.createElement("canvas");
  c.width = img.width;
  c.height = img.height;
  const g = c.getContext("2d");
  g.imageSmoothingEnabled = false;
  g.drawImage(img, 0, 0);
  return c;
}

// Scale2x/EPX for 16px pack textures - same upscale the Python side uses,
// so a 16px file looks identical on desktop and web.
function epx2x(src) {
  const w = src.width, h = src.height;
  const sd = src.getContext("2d").getImageData(0, 0, w, h);
  const s = new Uint32Array(sd.data.buffer);
  const out = document.createElement("canvas");
  out.width = w * 2;
  out.height = h * 2;
  const og = out.getContext("2d");
  const od = og.createImageData(w * 2, h * 2);
  const o = new Uint32Array(od.data.buffer);
  const at = (x, y) => s[y * w + x];
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const p = at(x, y);
      const a = y > 0 ? at(x, y - 1) : p;
      const d = y < h - 1 ? at(x, y + 1) : p;
      const c = x > 0 ? at(x - 1, y) : p;
      const b = x < w - 1 ? at(x + 1, y) : p;
      const row0 = y * 2 * w * 2, row1 = (y * 2 + 1) * w * 2;
      o[row0 + x * 2] = (c === a && c !== d && a !== b) ? a : p;
      o[row0 + x * 2 + 1] = (a === b && a !== c && b !== d) ? b : p;
      o[row1 + x * 2] = (d === c && d !== b && c !== a) ? c : p;
      o[row1 + x * 2 + 1] = (b === d && b !== a && d !== c) ? d : p;
    }
  }
  og.putImageData(od, 0, 0);
  return out;
}

function darkenCanvas(src, factor) {
  const c = document.createElement("canvas");
  c.width = src.width;
  c.height = src.height;
  const g = c.getContext("2d");
  const d = src.getContext("2d").getImageData(0, 0, src.width, src.height);
  for (let i = 0; i < d.data.length; i += 4) {
    d.data[i] = Math.floor(d.data[i] * factor);
    d.data[i + 1] = Math.floor(d.data[i + 1] * factor);
    d.data[i + 2] = Math.floor(d.data[i + 2] * factor);
  }
  g.putImageData(d, 0, 0);
  return c;
}

function packLoadImage(path) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = "textures/" + path;
  });
}

function packPrep(img, what) {
  if (!img) return null;
  if (![16, 32, 64].includes(img.width) || img.width !== img.height) {
    console.warn(`texture pack: ${what} is ${img.width}x${img.height} - ` +
                 "textures must be square 16, 32 or 64 px - using built-in art");
    return null;
  }
  const c = imageToCanvas(img);
  return img.width === 16 ? epx2x(c) : c;
}

async function applyTexturePack() {
  let manifest;
  try {
    const resp = await fetch("textures/manifest.json", { cache: "no-cache" });
    if (!resp.ok) return;
    manifest = await resp.json();
  } catch {
    return; // no pack - built-in art everywhere
  }
  await applyManifest(manifest, packLoadImage);
}

// Shared by the boot-time fetched pack (loadImage fetches "textures/"+path)
// and the runtime Import button (loadImage reads bytes out of a parsed
// in-memory .edtp zip instead) - everything past "how do I get an Image for
// this path" is identical between the two.
async function applyManifest(manifest, loadImage) {
  texPack.manifest = manifest;
  const dimKeys = new Set(manifest.dim_keys || []);
  const dimFactor = manifest.dim_factor || 0.45;

  const entries = Object.entries(manifest.files || {});
  const images = await Promise.all(entries.map(([, path]) => loadImage(path)));
  let applied = 0;
  entries.forEach(([key, path], i) => {
    if (!atlas[key]) return; // unknown key: harmless leftover in the folder
    const prepped = packPrep(images[i], path);
    if (!prepped) return;
    atlas[key] = prepped;
    if (dimKeys.has(key)) atlas[key + "_dim"] = darkenCanvas(prepped, dimFactor);
    applied++;
  });

  texPack.hero = null;
  const h = manifest.hero || {};
  if (h.base) {
    const base = packPrep(await loadImage(h.base), h.base);
    if (base) {
      const loadPiece = async (path) =>
        path ? packPrep(await loadImage(path), path) : null;
      const weapons = {}, weaponsSide = {};
      for (const [kind, path] of Object.entries(h.weapons || {})) {
        weapons[kind] = await loadPiece(path);
      }
      for (const [kind, path] of Object.entries(h.weapons_side || {})) {
        weaponsSide[kind] = await loadPiece(path);
      }
      texPack.hero = {
        base,
        baseUp: await loadPiece(h.base_up),
        baseSide: await loadPiece(h.base_side),
        weapons,
        weaponsSide,
        accessory: await loadPiece(h.accessory),
      };
    }
  }
  heroCache = {}; // rebuild hero variants (pack or reverted-to-built-in)
  if (applied || texPack.hero) {
    console.log(`texture pack: ${applied} sprite overrides` +
                (texPack.hero ? " + hero" : ""));
  }
  return applied;
}

// Reads a STORED-only (uncompressed) zip's Central Directory directly out
// of an ArrayBuffer - no DEFLATE decompressor needed since scripts/export
// _textures.py / ui/texturepack.py only ever write ZIP_STORED entries.
// Returns a Map of zip-internal path -> Uint8Array of that entry's raw
// bytes. Throws with a user-facing message on anything that isn't a
// well-formed, all-STORED zip (a hand-edited or foreign .edtp file).
function parseStoredZip(buf) {
  const data = new Uint8Array(buf);
  const dv = new DataView(buf);
  const EOCD_SIG = 0x06054b50;
  const maxBack = Math.min(data.length, 65557); // EOCD (22B) + max 65535B comment
  let eocdOffset = -1;
  for (let i = data.length - 22; i >= data.length - maxBack; i--) {
    if (i >= 0 && dv.getUint32(i, true) === EOCD_SIG) { eocdOffset = i; break; }
  }
  if (eocdOffset < 0) {
    throw new Error("that isn't a valid .edtp file (no zip end-of-directory record)");
  }
  const totalEntries = dv.getUint16(eocdOffset + 10, true);
  let offset = dv.getUint32(eocdOffset + 16, true);

  const CFH_SIG = 0x02014b50, LFH_SIG = 0x04034b50;
  const decoder = new TextDecoder();
  const files = new Map();
  for (let i = 0; i < totalEntries; i++) {
    if (dv.getUint32(offset, true) !== CFH_SIG) {
      throw new Error("that .edtp file's central directory is corrupt");
    }
    const method = dv.getUint16(offset + 10, true);
    const compSize = dv.getUint32(offset + 20, true);
    const nameLen = dv.getUint16(offset + 28, true);
    const extraLen = dv.getUint16(offset + 30, true);
    const commentLen = dv.getUint16(offset + 32, true);
    const localOffset = dv.getUint32(offset + 42, true);
    const name = decoder.decode(data.subarray(offset + 46, offset + 46 + nameLen));
    if (method !== 0) {
      throw new Error(`that .edtp file is compressed ("${name}") - only ` +
                       "uncompressed packs exported by this game are supported");
    }
    if (dv.getUint32(localOffset, true) !== LFH_SIG) {
      throw new Error("that .edtp file's local file header is corrupt");
    }
    const lNameLen = dv.getUint16(localOffset + 26, true);
    const lExtraLen = dv.getUint16(localOffset + 28, true);
    const dataStart = localOffset + 30 + lNameLen + lExtraLen;
    files.set(name, data.subarray(dataStart, dataStart + compSize));
    offset += 46 + nameLen + extraLen + commentLen;
  }
  return files;
}

function packLoadImageFromZip(zipFiles) {
  return (path) => new Promise((resolve) => {
    const bytes = zipFiles.get(path);
    if (!bytes) { resolve(null); return; }
    const url = URL.createObjectURL(new Blob([bytes], { type: "image/png" }));
    const img = new Image();
    img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
    img.onerror = () => { URL.revokeObjectURL(url); resolve(null); };
    img.src = url;
  });
}

function setSettingsStatus(text) {
  $("settings-status").textContent = text;
}

function exportTexturePack() {
  const b64 = bridge.export_texture_pack_b64();
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const blob = new Blob([bytes], { type: "application/octet-stream" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "endless_depths_textures.edtp";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);
  setSettingsStatus("Exported endless_depths_textures.edtp.");
}

async function importTexturePackFile(file) {
  let manifest, zipFiles;
  try {
    const buf = await file.arrayBuffer();
    zipFiles = parseStoredZip(buf);
    const manifestBytes = zipFiles.get("manifest.json");
    if (!manifestBytes) throw new Error("missing manifest.json - not an Endless Depths texture pack");
    manifest = JSON.parse(new TextDecoder().decode(manifestBytes));
  } catch (err) {
    setSettingsStatus(`Import failed: ${err.message}`);
    return;
  }
  const applied = await applyManifest(manifest, packLoadImageFromZip(zipFiles));
  drawTitleHero();
  setSettingsStatus(`Imported ${applied} sprite override(s)` +
                     (texPack.hero ? " + hero art" : "") +
                     " for this session (not saved across reloads).");
}

function resetTexturePack() {
  buildAtlas(JSON.parse(bridge.sprite_atlas_json()));
  texPack.hero = null;
  texPack.manifest = null;
  heroCache = {};
  drawTitleHero();
  setSettingsStatus("Reset to built-in art.");
}

function packHeroBase(facing) {
  // The pack piece the given facing needs, or null if the pack lacks it
  // (caller then falls back to the bridge's generated art).
  if (facing === "up") return texPack.hero.baseUp;
  if (facing === "left" || facing === "right") return texPack.hero.baseSide;
  return texPack.hero.base;
}

function heroFromPack(hero, facing) {
  const m = texPack.manifest;
  const base = packHeroBase(facing);
  const side = facing === "left" || facing === "right";
  const c = document.createElement("canvas");
  c.width = base.width;
  c.height = base.height;
  const g = c.getContext("2d");
  g.imageSmoothingEnabled = false;
  g.drawImage(base, 0, 0, c.width, c.height);
  if (hero.weapon !== "none" && facing !== "up") {
    // Fall back to the sword overlay for unpacked weapon kinds, mirroring
    // HELD_WEAPONS.get(kind, HELD_SWORD) on the Python side.
    const pool = side ? texPack.hero.weaponsSide : texPack.hero.weapons;
    const ov = pool[hero.weapon] || pool.sword;
    if (ov) g.drawImage(ov, 0, 0, c.width, c.height);
  }
  if (hero.accessory && texPack.hero.accessory && facing !== "up") {
    g.drawImage(texPack.hero.accessory, 0, 0, c.width, c.height);
  }
  if (facing === "left") {
    // Mirror the composed right-facing sprite.
    const mc = document.createElement("canvas");
    mc.width = c.width;
    mc.height = c.height;
    const mg = mc.getContext("2d");
    mg.imageSmoothingEnabled = false;
    mg.translate(c.width, 0);
    mg.scale(-1, 1);
    mg.drawImage(c, 0, 0);
    return finishHeroRecolor(mc, hero, m);
  }
  return finishHeroRecolor(c, hero, m);
}

function finishHeroRecolor(c, hero, m) {
  const g = c.getContext("2d");
  // Recolor the slot colors (exact RGB matches only).
  const hexRgb = (s) => [parseInt(s.slice(1, 3), 16), parseInt(s.slice(3, 5), 16),
                          parseInt(s.slice(5, 7), 16)];
  const remap = [];
  const tunic = (m.colors.tunic_by_armor[hero.armor] || m.slots.tunic);
  if (tunic !== m.slots.tunic) remap.push([hexRgb(m.slots.tunic), hexRgb(tunic)]);
  const blade = (m.colors.blade_by_rarity[hero.rarity] || m.slots.blade);
  if (blade !== m.slots.blade) remap.push([hexRgb(m.slots.blade), hexRgb(blade)]);
  if (hero.poisoned) remap.push([hexRgb(m.slots.skin), hexRgb(m.colors.poisoned_skin)]);
  if (remap.length) {
    const d = g.getImageData(0, 0, c.width, c.height);
    for (let i = 0; i < d.data.length; i += 4) {
      for (const [from, to] of remap) {
        if (d.data[i] === from[0] && d.data[i + 1] === from[1] && d.data[i + 2] === from[2]) {
          d.data[i] = to[0]; d.data[i + 1] = to[1]; d.data[i + 2] = to[2];
          break;
        }
      }
    }
    g.putImageData(d, 0, 0);
  }
  return c;
}

function heroSprite(hero, facing = "down") {
  const key = [hero.weapon, hero.armor, hero.accessory, hero.poisoned,
               hero.rarity, facing].join("|");
  if (!heroCache[key]) {
    if (texPack.hero && packHeroBase(facing)) {
      heroCache[key] = heroFromPack(hero, facing);
    } else {
      // No pack, or the pack lacks this facing's base: generated art.
      const def = JSON.parse(bridge.hero_sprite_json(
        hero.weapon, hero.armor, hero.accessory, hero.poisoned, hero.rarity,
        facing));
      heroCache[key] = spriteCanvas(def.grid, def.palette);
    }
  }
  return heroCache[key];
}

function drawTitleHero() {
  const c = $("title-hero");
  const g = c.getContext("2d");
  g.imageSmoothingEnabled = false;
  g.clearRect(0, 0, c.width, c.height);
  g.drawImage(atlas["player"], 0, 0, 128, 128);
}

/* --------------------------------------------------------------- audio */
const AUDIO_POOL_SIZE = 4;  // per sound name - enough for rapid overlapping hits

const audio = {
  cache: {},
  pools: {},  // name -> HTMLAudioElement[], reused round-robin instead of cloning fresh every play()
  musicEl: null,
  currentTrack: null,
  ready: false,

  get muted() {
    return !gameSettings.music_on && !gameSettings.sfx_on;
  },

  init() {
    // Pre-synthesize SFX one at a time so the UI stays responsive;
    // music tracks (bigger) come last.
    const names = JSON.parse(bridge.sfx_names_json());
    const queue = [...names.sfx, ...names.music];
    const step = () => {
      const name = queue.shift();
      if (!name) { this.ready = true; return; }
      this.synth(name);
      setTimeout(step, 30);
    };
    setTimeout(step, 100);
  },

  synth(name) {
    if (this.cache[name]) return this.cache[name];
    const b64 = bridge.synth_wav_b64(name);
    if (!b64) return null;
    const el = new Audio("data:audio/wav;base64," + b64);
    this.cache[name] = el;
    return el;
  },

  play(name) {
    if (!gameSettings.sfx_on) return;
    const el = this.synth(name);
    if (!el) return;
    // A brand-new HTMLAudioElement per play() (the old cloneNode()-every-
    // time approach) meant walking - which fires a "step" sound on every
    // plain move and nothing else - constructed and discarded one forever,
    // a real source of browser audio-pipeline/GC hitching. Reuse a small
    // pool instead; still supports overlapping playback (rapid hits) up to
    // the pool cap, just without unbounded element churn.
    const pool = this.pools[name] || (this.pools[name] = []);
    let inst = pool.find((a) => a.paused);
    if (!inst) {
      inst = el.cloneNode();
      if (pool.length < AUDIO_POOL_SIZE) pool.push(inst);
    }
    inst.currentTime = 0;
    inst.volume = 0.7;
    inst.play().catch(() => {});
  },

  playMusic(track) {
    if (this.currentTrack === track && this.musicEl && !this.musicEl.paused) return;
    this.stopMusic();
    this.currentTrack = track;
    if (!track || !gameSettings.music_on) return;
    const el = this.synth(track);
    if (!el) return;
    this.musicEl = el.cloneNode();
    this.musicEl.loop = true;
    this.musicEl.volume = 0.45;
    this.musicEl.play().catch(() => {});
  },

  stopMusic() {
    if (this.musicEl) { this.musicEl.pause(); this.musicEl = null; }
  },

  setMuted(m) {
    gameSettings.music_on = !m;
    gameSettings.sfx_on = !m;
    persistSettings();
    if (m) this.stopMusic();
    else this.playMusic(this.currentTrack);
  },

  applySettings() {
    if (!gameSettings.music_on) this.stopMusic();
    else this.playMusic(this.currentTrack);
  },
};

/* ------------------------------------------------------------ screens */
function showScreen(name) {
  for (const id of ["title-screen", "lore-screen", "journal-screen", "play-screen",
                     "gameover-screen", "victory-screen", "replay-picker",
                     "bestiary-screen", "achievements-screen"]) {
    $(id).classList.toggle("hidden", id !== name);
  }
  $("inventory-overlay").classList.add("hidden");
  $("shop-overlay").classList.add("hidden");
  $("settings-overlay").classList.add("hidden");
  $("puzzle-overlay").classList.add("hidden");
  $("lore-page-overlay").classList.add("hidden");
  $("replay-controls").classList.toggle("hidden", mode !== "replay");
}

function toTitle() {
  mode = "title";
  showScreen("title-screen");
  $("btn-continue").disabled = !localStorage.getItem(LS_SAVE);
  refreshDailyButton();
  renderTitleScores();
  audio.playMusic("depths");
}

// The delver's field manual (GUIDE.html) ships next to index.html but was
// never linked in-app; open it in a new tab from the title menu.
function openGuide() {
  window.open("GUIDE.html", "_blank", "noopener");
}

/* ------------------------------------------------------------------ lore */
const lore = { data: null, page: 0 };

function showLore(firstTime) {
  mode = "lore";
  lore.firstTime = firstTime;
  lore.page = 0;
  renderLorePage();
  showScreen("lore-screen");
}

function renderLorePage() {
  const pages = lore.data.pages;
  $("lore-text").textContent = pages[lore.page];
  $("lore-page-label").textContent = `Page ${lore.page + 1} / ${pages.length}`;
  $("lore-next").textContent = lore.page === pages.length - 1 ? "Begin >" : "Next >";
}

function loreStep(delta) {
  const pages = lore.data.pages;
  if (delta > 0 && lore.page === pages.length - 1) {
    finishLore();
    return;
  }
  lore.page = Math.max(0, Math.min(lore.page + delta, pages.length - 1));
  renderLorePage();
}

/* ------------------------------------------------------------- bestiary */
// Web owns its OWN persistence in localStorage (like scores/history/daily
// above) rather than the desktop's bestiary.json - the bridge only ever
// supplies pure data (templates, this run's sightings), never touches disk.
const LS_BESTIARY = "endless_depths_bestiary";
let bestiaryTemplates = null;  // static breed list, fetched from the bridge once

function loadBestiaryData() {
  try { return JSON.parse(localStorage.getItem(LS_BESTIARY)) || {}; }
  catch { return {}; }
}

function mergeBestiaryFromRun() {
  // Folds this run's newly-seen breeds/kills into the PERSISTENT bestiary -
  // called once at run-end (gameOver/victory), same cadence as recordHistory.
  const runData = JSON.parse(bridge.bestiary_run_data_json());
  const data = loadBestiaryData();
  for (const name of runData.seen) {
    const entry = data[name] || { seen: false, kills: 0 };
    entry.seen = true;
    data[name] = entry;
  }
  for (const [name, count] of Object.entries(runData.kills)) {
    const entry = data[name] || { seen: false, kills: 0 };
    entry.kills = (entry.kills || 0) + count;
    data[name] = entry;
  }
  localStorage.setItem(LS_BESTIARY, JSON.stringify(data));
}

function openBestiary() {
  mode = "bestiary";
  if (!bestiaryTemplates) bestiaryTemplates = JSON.parse(bridge.bestiary_templates_json());
  renderBestiary();
  showScreen("bestiary-screen");
}

function renderBestiary() {
  const data = loadBestiaryData();
  const grid = $("bestiary-grid");
  grid.innerHTML = "";
  let seenCount = 0;
  for (const t of bestiaryTemplates) {
    const entry = data[t.name];
    const cell = document.createElement("div");
    cell.className = "bestiary-cell" + (entry && entry.seen ? "" : " unseen");
    if (entry && entry.seen) {
      seenCount++;
      const c = document.createElement("canvas");
      c.width = 48;
      c.height = 48;
      const g = c.getContext("2d");
      g.imageSmoothingEnabled = false;
      if (atlas[t.sprite]) drawSpriteCentered(g, atlas[t.sprite], 48, 48, 4);
      cell.appendChild(c);
      const name = document.createElement("div");
      name.className = "bname";
      name.textContent = t.name;
      cell.appendChild(name);
      const kills = document.createElement("div");
      kills.className = "bkills";
      kills.textContent = `Kills: ${entry.kills || 0}`;
      cell.appendChild(kills);
    } else {
      const ph = document.createElement("div");
      ph.className = "bplaceholder";
      ph.textContent = "?";
      cell.appendChild(ph);
      const name = document.createElement("div");
      name.className = "bname";
      name.textContent = "???";
      cell.appendChild(name);
    }
    grid.appendChild(cell);
  }
  $("bestiary-progress").textContent = `Discovered: ${seenCount} / ${bestiaryTemplates.length}`;
}

/* --------------------------------------------------------- achievements */
const LS_ACHIEVEMENTS = "endless_depths_achievements";
let achievementDefs = null;  // static defs, fetched from the bridge once

function loadUnlockedAchievements() {
  try { return JSON.parse(localStorage.getItem(LS_ACHIEVEMENTS)) || {}; }
  catch { return {}; }
}

function checkAchievementsFromRun(ctx) {
  // Returns newly-unlocked {id, name, description} entries and persists
  // them (with today's date) into localStorage - the actual milestone
  // CHECK logic is shared with desktop via the bridge (engine/achievements.py),
  // only the persistence layer differs.
  const unlocked = loadUnlockedAchievements();
  const newly = JSON.parse(bridge.check_achievement_unlocks_json(
    JSON.stringify(ctx), JSON.stringify(Object.keys(unlocked))));
  if (newly.length) {
    const now = new Date().toISOString();
    for (const a of newly) unlocked[a.id] = now;
    localStorage.setItem(LS_ACHIEVEMENTS, JSON.stringify(unlocked));
  }
  return newly;
}

function openAchievements() {
  mode = "achievements";
  if (!achievementDefs) achievementDefs = JSON.parse(bridge.achievements_defs_json());
  renderAchievements();
  showScreen("achievements-screen");
}

function renderAchievements() {
  const unlocked = loadUnlockedAchievements();
  const list = $("achievements-list");
  list.innerHTML = "";
  let doneCount = 0;
  for (const a of achievementDefs) {
    const done = !!unlocked[a.id];
    if (done) doneCount++;
    const row = document.createElement("div");
    row.className = "achievement-row " + (done ? "done" : "locked");
    row.textContent = `${done ? "[x]" : "[ ]"} ${a.name} - ${a.description}`;
    list.appendChild(row);
  }
  $("achievements-progress").textContent = `Unlocked: ${doneCount} / ${achievementDefs.length}`;
}

function finishLore() {
  localStorage.setItem(LS_SEEN_LORE, "1");
  toTitle();
}

/* ---------------------------------------------------------------
 * Found-page popup (mid-run) + the Journal screen (title menu, via
 * the Lore screen's "View Found Pages" link). Web owns its own
 * persistence in localStorage, same split as bestiary/achievements
 * above - the bridge only ever supplies pure data (the static 54-page
 * catalog, this run's newly-found ids), never touches disk. */
const LS_LORE_JOURNAL = "endless_depths_lore_journal";
let lorePagesCatalog = null;  // static {id: {author, text}}, fetched from the bridge once
let journalSel = 0;

function loadLoreJournalData() {
  try { return JSON.parse(localStorage.getItem(LS_LORE_JOURNAL)) || []; }
  catch { return []; }
}

function mergeLoreJournalFromRun() {
  const foundThisRun = JSON.parse(bridge.lore_journal_run_data_json());
  const found = new Set(loadLoreJournalData());
  for (const id of foundThisRun) found.add(id);
  localStorage.setItem(LS_LORE_JOURNAL, JSON.stringify([...found].sort()));
}

function openLorePagePopup(author, text) {
  mode = "lore_page";
  $("lore-page-author").textContent = author;
  $("lore-page-text").textContent = text;
  $("lore-page-overlay").classList.remove("hidden");
}

function closeLorePagePopup() {
  $("lore-page-overlay").classList.add("hidden");
  mode = "play";
}

function openJournal() {
  mode = "journal";
  if (!lorePagesCatalog) lorePagesCatalog = JSON.parse(bridge.lore_pages_catalog_json());
  journalSel = 0;
  renderJournal();
  showScreen("journal-screen");
}

function journalEntries() {
  // Fully progressive: an author's category header only appears here once
  // at least one of their pages has been found - renderItemList already
  // only emits a header when it hits the first entry of a new category,
  // so filtering to found ids before grouping is all this needs.
  const found = new Set(loadLoreJournalData());
  return Object.entries(lorePagesCatalog)
    .filter(([id]) => found.has(id))
    .map(([id, p]) => ({ id, category: p.author, label: id, text: p.text, color: "#e0d356" }));
}

function renderJournal() {
  const entries = journalEntries();
  journalSel = Math.max(0, Math.min(journalSel, entries.length - 1));
  renderItemList($("journal-list"), entries, journalSel,
    (i) => { journalSel = i; renderJournal(); }, () => {},
    (e) => e.label, (e) => e.color);
  renderDetails("journal-detail-name", "journal-detail-body", entries[journalSel],
    (e) => e.text.split("\n"));
  // No denominator on purpose - the whole point of "fully progressive" is
  // that the corpus's total size stays a mystery too, not just the content.
  $("journal-progress").textContent = `Pages found: ${entries.length}`;
}

function loadScores() {
  try { return JSON.parse(localStorage.getItem(LS_SCORES)) || []; }
  catch { return []; }
}

function loadSpeedrunScores() {
  try { return JSON.parse(localStorage.getItem(LS_SPEEDRUN_SCORES)) || []; }
  catch { return []; }
}

function speedrunCompare(a, b) {
  // Finishers first (fastest wins), then DNFs by deepest floor, then time.
  if (a.finished !== b.finished) return a.finished ? -1 : 1;
  if (a.finished) return a.elapsed_seconds - b.elapsed_seconds;
  if (a.depth_reached !== b.depth_reached) return b.depth_reached - a.depth_reached;
  return a.elapsed_seconds - b.elapsed_seconds;
}

function recordSpeedrunRun() {
  const p = snap.player;
  const runs = loadSpeedrunScores();
  runs.push({
    date: new Date().toISOString(),
    finished: snap.game_won,
    depth_reached: snap.depth,
    elapsed_seconds: Math.round(finalElapsed() * 100) / 100,
    level: p.level, gold: p.gold, kills: p.kills, turns: p.turns,
    seed: snap.seed,
  });
  runs.sort(speedrunCompare);
  localStorage.setItem(LS_SPEEDRUN_SCORES, JSON.stringify(runs.slice(0, 10)));
  return runs;
}

function speedrunScoreLines(runs, count) {
  return runs.slice(0, count).map((r) =>
    `  ${r.finished ? "WIN " : "F" + String(r.depth_reached).padEnd(3)} ` +
    `${fmtTime(r.elapsed_seconds).padStart(8)}  seed ${r.seed}`);
}

function renderTitleHighscores() {
  const runs = loadScores();
  const trim = (text) => (text && text.length > 24 ? text.slice(0, 23) + "…" : text || "");
  $("title-highscores").textContent = runs.length
    ? "Top runs:\n" + runs.slice(0, 5).map((r) =>
        `  Floor ${String(r.depth_reached).padStart(3)}  Lv ${String(r.level).padEnd(3)} ` +
        `Gold ${String(r.gold).padEnd(5)} ${trim(r.cause)}`).join("\n")
    : "No runs recorded yet - descend and see how far you get.";
  const speedruns = loadSpeedrunScores();
  $("title-speedrun-scores").textContent = speedruns.length
    ? `Speedrun (goal: floor ${snap ? snap.target_floor : 100}):\n` +
      speedrunScoreLines(speedruns, 5).join("\n")
    : "Speedrun: race to floor 100.\nNo attempts yet.";
}

/* -------------------------------------------------- daily + run history */
let dailyToday = null;          // {date, seed} for today, from the engine
let titleScoreView = "top";     // "top" | "recent" - the title panel toggle

function getDailyToday() {
  // Cache today's (date, seed) from the same engine helper the desktop uses.
  if (!dailyToday || dailyToday.date !== new Date().toISOString().slice(0, 10)) {
    try { dailyToday = JSON.parse(bridge.daily_seed_json()); }
    catch { dailyToday = null; }
  }
  return dailyToday;
}

function loadDaily() {
  try { return JSON.parse(localStorage.getItem(LS_DAILY)) || {}; }
  catch { return {}; }
}

function dailyPlayedToday() {
  const d = getDailyToday();
  const st = loadDaily();
  return !!(d && st.date === d.date && st.played);
}

function loadHistory() {
  try { return JSON.parse(localStorage.getItem(LS_HISTORY)) || []; }
  catch { return []; }
}

function recordHistory(entry) {
  const runs = loadHistory();
  runs.unshift(entry);                         // newest first
  localStorage.setItem(LS_HISTORY, JSON.stringify(runs.slice(0, HISTORY_MAX)));
}

function historyLines(runs, count) {
  const tag = { normal: "  ", speedrun: "SR", daily: "D " };
  return runs.slice(0, count).map((r) => {
    const when = (r.date || "").slice(5, 10);  // MM-DD
    const win = r.mode === "speedrun" && r.finished ? " WIN" : "";
    return `  ${when} ${tag[r.mode] || "  "} Floor ${String(r.depth_reached).padStart(3)}` +
           `  Lv ${String(r.level).padEnd(2)}${win}`;
  });
}

function startDaily() {
  const d = getDailyToday();
  if (!d || dailyPlayedToday()) return;
  localStorage.setItem(LS_DAILY, JSON.stringify({ date: d.date, played: true, depth: null }));
  applySnapshot(JSON.parse(bridge.new_game(d.seed, "normal")));
  liveRun = true;
  startRunTimer();
  mode = "play";
  showScreen("play-screen");
  persistSave();
  updateMusic();
}

function isDailyRun() {
  const d = getDailyToday();
  return !!(snap && d && snap.run_mode === "normal" && Number(snap.seed) === Number(d.seed));
}

function refreshDailyButton() {
  const btn = $("btn-daily");
  if (!btn) return;
  const played = dailyPlayedToday();
  btn.disabled = played;
  const st = loadDaily();
  btn.title = played
    ? `Daily done — reached Floor ${st.depth != null ? st.depth : "?"}. Come back tomorrow.`
    : "Daily Challenge (D)";
}

function setTitleScoreView(view) {
  titleScoreView = view;
  const top = $("score-view-top"), recent = $("score-view-recent");
  if (top) top.classList.toggle("active", view === "top");
  if (recent) recent.classList.toggle("active", view === "recent");
  renderTitleScores();
}

function renderTitleScores() {
  if (titleScoreView === "recent") {
    const runs = loadHistory();
    $("title-highscores").textContent = runs.length
      ? "Recent runs:\n" + historyLines(runs, 10).join("\n")
      : "No runs yet - descend and see how far you get.";
    $("title-speedrun-scores").textContent = "";
  } else {
    renderTitleHighscores();
  }
}

function seedInputValue() {
  const text = $("seed-input").value.trim();
  return text === "" ? null : text;
}

function startRunTimer() {
  runStartedAt = performance.now();
  elapsedAtEnd = 0;
  clearInterval(timerInterval);
  if (snap.run_mode === "speedrun") {
    timerInterval = setInterval(() => {
      if (snap && !snap.game_over && liveRun) {
        $("stat-timer").textContent =
          `Time: ${fmtTime((performance.now() - runStartedAt) / 1000)} ` +
          `(goal: floor ${snap.target_floor})`;
      }
    }, 250);
  }
}

function stopRunTimer() {
  clearInterval(timerInterval);
  timerInterval = null;
}

function startNewGame() {
  applySnapshot(JSON.parse(bridge.new_game(seedInputValue(), "normal")));
  liveRun = true;
  startRunTimer();
  mode = "play";
  showScreen("play-screen");
  persistSave();
  updateMusic();
}

function startSpeedrun() {
  applySnapshot(JSON.parse(bridge.new_game(seedInputValue(), "speedrun")));
  liveRun = true;
  startRunTimer();
  mode = "play";
  showScreen("play-screen");
  persistSave();
  updateMusic();
}

function continueGame() {
  const saved = localStorage.getItem(LS_SAVE);
  if (!saved) return;
  const result = JSON.parse(bridge.load_game(saved));
  if (result.error) { localStorage.removeItem(LS_SAVE); toTitle(); return; }
  applySnapshot(result);
  liveRun = true;
  startRunTimer();
  mode = "play";
  showScreen("play-screen");
  updateMusic();
}

// Shared by gameOver() (a normal/daily-mode death) and victory() (a
// normal/daily-mode floor-100 win): records to the highscore + rolling
// history storage, and stamps today's daily done if this was a daily run.
// Returns the score-panel text to show.
function recordNormalModeRun(cause, finished) {
  const p = snap.player;
  const daily = isDailyRun();
  const runs = loadScores();
  runs.push({
    date: new Date().toISOString(), depth_reached: snap.depth,
    turns_survived: p.turns, level: p.level, gold: p.gold, kills: p.kills,
    cause,
  });
  runs.sort((a, b) => (b.depth_reached - a.depth_reached) || (b.gold - a.gold));
  localStorage.setItem(LS_SCORES, JSON.stringify(runs.slice(0, 10)));
  const heading = daily ? "Daily Challenge — done!" : "High Scores:";
  const text = heading + "\n" +
    runs.slice(0, 5).map((r) =>
      `  Floor ${String(r.depth_reached).padStart(3)}  Lv ${String(r.level).padEnd(3)} Gold ${r.gold}`).join("\n");
  if (daily) {  // stamp today's daily result for the title-menu status line
    const st = loadDaily();
    localStorage.setItem(LS_DAILY, JSON.stringify({ ...st, played: true, depth: snap.depth }));
  }
  recordHistory({
    date: new Date().toISOString(), mode: daily ? "daily" : snap.run_mode,
    depth_reached: snap.depth, level: p.level, gold: p.gold, kills: p.kills,
    turns: p.turns, cause, seed: snap.seed, finished,
  });
  return text;
}

function finishRunMetaTracking(finished) {
  // Bestiary + achievements (M6) - applies to every mode/outcome (unlike
  // recordNormalModeRun's leaderboard, which is normal/daily-only). Returns
  // a "New achievement: X!" suffix to append to the stats text, or "".
  mergeBestiaryFromRun();
  mergeLoreJournalFromRun();
  const ctx = {
    depth_reached: snap.depth, level: snap.player.level, gold: snap.player.gold,
    kills: snap.player.kills, mode: snap.run_mode, finished,
    is_daily: isDailyRun(),
    breeds_seen: snap.player.breeds_seen, boss_kills: snap.player.boss_kills,
  };
  const newly = checkAchievementsFromRun(ctx);
  if (!newly.length) return "";
  return "\n\nNew achievement" + (newly.length > 1 ? "s" : "") + ": " +
    newly.map((a) => a.name).join(", ") + "!";
}

function gameOver() {
  mode = "gameover";
  stopRunTimer();
  const p = snap.player;
  const cause = snap.cause_of_death || "Unknown causes.";
  const achievementLine = finishRunMetaTracking(false);
  $("gameover-stats").textContent =
    `Cause of death: ${cause}\n\nDepth reached: ${snap.depth}\nLevel: ${p.level}\n` +
    `Gold collected: ${p.gold}\nMonsters slain: ${p.kills}\nTurns survived: ${p.turns}\n` +
    `Time: ${fmtTime(finalElapsed())}\nSeed: ${snap.seed}` + achievementLine;
  if (snap.run_mode === "speedrun") {
    const runs = recordSpeedrunRun();
    $("gameover-highscores").textContent =
      "Speedrun Leaderboard:\n" + speedrunScoreLines(runs, 5).join("\n");
    recordHistory({
      date: new Date().toISOString(), mode: "speedrun", depth_reached: snap.depth,
      level: p.level, gold: p.gold, kills: p.kills, turns: p.turns,
      cause, seed: snap.seed, finished: false,
    });
  } else {
    $("gameover-highscores").textContent = recordNormalModeRun(cause, false);
  }
  localStorage.removeItem(LS_SAVE);
  setReplayButtonsVisible("gameover");
  showScreen("gameover-screen");
  audio.stopMusic();
}

function victory() {
  mode = "victory";
  stopRunTimer();
  const p = snap.player;
  const achievementLine = finishRunMetaTracking(true);
  if (snap.run_mode === "speedrun") {
    $("victory-stats").textContent =
      `Floor ${snap.target_floor} reached in ${fmtTime(finalElapsed())}!\n\n` +
      `Level: ${p.level}\nGold collected: ${p.gold}\nMonsters slain: ${p.kills}\n` +
      `Turns taken: ${p.turns}\nSeed: ${snap.seed}` + achievementLine;
    const runs = recordSpeedrunRun();
    $("victory-scores").textContent =
      "Speedrun Leaderboard:\n" + speedrunScoreLines(runs, 5).join("\n");
    recordHistory({
      date: new Date().toISOString(), mode: "speedrun", depth_reached: snap.depth,
      level: p.level, gold: p.gold, kills: p.kills, turns: p.turns,
      cause: "Escaped the depths.", seed: snap.seed, finished: true,
    });
  } else {
    $("victory-stats").textContent =
      `You conquered floor ${snap.depth}!\n\n` +
      `Level: ${p.level}\nGold collected: ${p.gold}\nMonsters slain: ${p.kills}\n` +
      `Turns taken: ${p.turns}\nTime: ${fmtTime(finalElapsed())}\nSeed: ${snap.seed}` + achievementLine;
    $("victory-scores").textContent = recordNormalModeRun("Conquered the depths.", true);
  }
  localStorage.removeItem(LS_SAVE);
  setReplayButtonsVisible("victory");
  showScreen("victory-screen");
  audio.stopMusic();
}

function setReplayButtonsVisible(prefix) {
  const show = snap.replayable;
  $(`${prefix}-replay-row`).classList.toggle("hidden", !show);
  $(`${prefix}-replay-status`).textContent =
    show ? "" : "(replay unavailable for continued runs)";
}

/* ----------------------------------------------------------- snapshot */
function persistSave() {
  if (snap && !snap.game_over) localStorage.setItem(LS_SAVE, bridge.save_json());
}

function updateMusic() {
  audio.playMusic(snap ? snap.music_track : "depths");
}

/* ---------------------------------------------------------- fullscreen */
function toggleFullscreen() {
  if (document.fullscreenElement) {
    document.exitFullscreen().catch(() => {});
  } else {
    document.documentElement.requestFullscreen().catch(() => {});
  }
}

// #stage is ALWAYS scaled to fit the real viewport (see updateOrientation()
// near the top of this file, and STAGE_SIZES) - fullscreen just changes
// how much viewport there is to fit into, through the exact same code path
// as an ordinary window resize. No separate "desktop fullscreen" special
// case needed here anymore.
function fitStage() {
  const [stageW, stageH] = STAGE_SIZES[orientation];
  const scale = Math.min(window.innerWidth / stageW, window.innerHeight / stageH);
  $("stage").style.transform = `scale(${scale.toFixed(4)})`;
}

document.addEventListener("fullscreenchange", fitStage);

function applySnapshot(s) {
  // Replays have no input events to read facing from - infer it from
  // single-tile position deltas instead (teleports don't count).
  if (snap && snap.player && s.player && !s.floor_changed) {
    const ddx = s.player.x - snap.player.x, ddy = s.player.y - snap.player.y;
    if (Math.abs(ddx) + Math.abs(ddy) === 1) noteFacing(ddx, ddy);
  }
  snap = s;
  // Re-fetch the cached floor data on a new floor OR when the map mutated
  // mid-floor (chest opened, rune door dissolved, block pushed).
  if (s.floor_changed || !floorData || s.tiles_version !== floorData.tiles_version) {
    floorData = JSON.parse(bridge.floor_data_json());
  }
  handleEvents(s.events || []);
  render();
}

function afterAction(snapJson) {
  applySnapshot(JSON.parse(snapJson));
  persistSave();
  if (snap.game_over) {
    elapsedAtEnd = (performance.now() - runStartedAt) / 1000;
    mode = "dying";
    setTimeout(snap.game_won ? victory : gameOver, 900);
    return;
  }
  if (snap.shop_open && mode === "play") openShop();
  else if (snap.puzzle_open && mode === "play") openPuzzle();
  else if (mode === "play") {
    if (snap.player.hp <= snap.player.max_hp * 0.25) audio.play("heartbeat");
    updateMusic();
  }
}

/* ------------------------------------------------------------- replays */
function downloadReplay() {
  const text = bridge.save_replay(finalElapsed());
  const blob = new Blob([text], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `endless-depths-replay-seed${snap.seed}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);
}

function copyReplayCode(prefix) {
  const text = bridge.save_replay(finalElapsed());
  const code = btoa(unescape(encodeURIComponent(text)));  // UTF-8-safe base64
  navigator.clipboard.writeText(code).then(() => {
    $(`${prefix}-replay-status`).textContent =
      `Replay code copied to clipboard (${code.length} characters).`;
  }).catch(() => {
    $(`${prefix}-replay-status`).textContent = "Clipboard blocked - use Save Replay File instead.";
  });
}

function openReplayPicker() {
  mode = "replay-picker";
  $("replay-error").textContent = "";
  $("replay-code-input").value = "";
  $("replay-file-input").value = "";
  showScreen("replay-picker");
}

function startReplayPlayback(text) {
  const result = JSON.parse(bridge.load_replay(text));
  if (result.error) {
    $("replay-error").textContent = "That is not a valid replay file or code.";
    return;
  }
  liveRun = false;
  stopRunTimer();
  mode = "replay";
  replayPaused = false;
  replaySpeedIdx = 0;
  $("replay-pause-btn").textContent = "Pause";
  $("replay-speed-btn").textContent = "Speed: 1x";
  applySnapshot(result);
  showScreen("play-screen");
  updateMusic();
  scheduleReplayStep();
}

function scheduleReplayStep() {
  clearTimeout(replayTimer);
  if (mode !== "replay" || replayPaused) return;
  replayTimer = setTimeout(() => {
    // Read-only playback: applySnapshot only - never persistSave/scoring.
    applySnapshot(JSON.parse(bridge.replay_step()));
    updateMusic();
    const prog = JSON.parse(bridge.replay_progress());
    $("replay-progress").textContent = `${prog.cursor}/${prog.total}`;
    if (prog.finished) {
      setTimeout(stopReplay, 1500);
      return;
    }
    scheduleReplayStep();
  }, REPLAY_SPEEDS[replaySpeedIdx][1]);
}

function toggleReplayPause() {
  replayPaused = !replayPaused;
  $("replay-pause-btn").textContent = replayPaused ? "Resume" : "Pause";
  scheduleReplayStep();
}

function cycleReplaySpeed() {
  if (replaySpeedIdx < REPLAY_SPEEDS.length - 1) {
    replaySpeedIdx += 1;
    $("replay-speed-btn").textContent = `Speed: ${REPLAY_SPEEDS[replaySpeedIdx][0]}`;
    scheduleReplayStep();
  } else {
    clearTimeout(replayTimer);
    applySnapshot(JSON.parse(bridge.replay_skip_to_end()));
    const prog = JSON.parse(bridge.replay_progress());
    $("replay-progress").textContent = `${prog.cursor}/${prog.total}`;
    setTimeout(stopReplay, 1200);
  }
}

function stopReplay() {
  if (mode !== "replay") return;
  clearTimeout(replayTimer);
  liveRun = true;
  toTitle();
}

/* ------------------------------------------------------ puzzle overlay */
let puzzleLocked = false;   // true while a reveal animation plays
let puzzleRevealShown = -1;

function openPuzzle() {
  mode = "puzzle";
  puzzleRevealShown = -1;  // replay the intro reveal on reopen
  $("puzzle-overlay").classList.remove("hidden");
  renderPuzzle();
}

function closePuzzle() {
  if (snap && snap.puzzle_open) afterAction(bridge.close_puzzle());
  $("puzzle-overlay").classList.add("hidden");
  puzzleLocked = false;
  mode = "play";
}

function puzzlePress(i) {
  if (mode !== "puzzle" || puzzleLocked) return;
  afterAction(bridge.puzzle_input(i));
  if (!snap.puzzle_open) {  // solved - the door is gone
    $("puzzle-overlay").classList.add("hidden");
    mode = "play";
    return;
  }
  renderPuzzle();
}

function renderPuzzle() {
  const v = snap.puzzle;
  if (!v) return;
  $("puzzle-title").textContent = v.title;
  $("puzzle-prompt").textContent = v.prompt;
  $("puzzle-feedback").textContent = v.feedback || "";
  const hist = $("puzzle-history");
  hist.textContent = (v.history || []).join("\n");
  hist.classList.toggle("hidden", !(v.history && v.history.length));
  const grid = $("puzzle-buttons");
  grid.innerHTML = "";
  grid.style.gridTemplateColumns = `repeat(${v.grid_cols}, minmax(48px, 1fr))`;
  v.buttons.forEach((b, i) => {
    const btn = document.createElement("button");
    btn.className = "puzzle-btn" + (b.state === "lit" ? " lit" : "");
    btn.textContent = b.label;
    btn.disabled = b.state === "disabled";
    btn.addEventListener("click", () => puzzlePress(i));
    grid.appendChild(btn);
  });
  maybePlayReveal(v);
}

function maybePlayReveal(v) {
  // Client-side flash animations (Simon melody, Counting Eyes grid, Rune
  // Pairs flip-back). The engine bumps reveal_id when a new one should play.
  if (v.reveal_id === puzzleRevealShown) return;
  puzzleRevealShown = v.reveal_id;
  const flash = $("puzzle-flash");
  const btnAt = (i) => $("puzzle-buttons").children[i];
  if (v.kind === "counting_eyes" && v.flash_grid) {
    puzzleLocked = true;
    flash.textContent = v.flash_grid.join("\n");
    flash.classList.remove("hidden");
    setTimeout(() => { flash.classList.add("hidden"); puzzleLocked = false; }, 2000);
  } else if (v.kind === "echo" && v.reveal) {
    puzzleLocked = true;
    v.reveal.forEach((idx, k) => {
      setTimeout(() => { const b = btnAt(idx); if (b) b.classList.add("lit"); audio.play("menu"); },
                 350 + k * 450);
      setTimeout(() => { const b = btnAt(idx); if (b) b.classList.remove("lit"); },
                 350 + k * 450 + 330);
    });
    setTimeout(() => { puzzleLocked = false; }, 400 + v.reveal.length * 450);
  } else if (v.kind === "rune_pairs" && v.reveal && v.reveal_cards) {
    puzzleLocked = true;
    v.reveal.forEach((idx, k) => {
      const b = btnAt(idx);
      if (b) { b.textContent = v.reveal_cards[k]; b.classList.add("lit"); }
    });
    setTimeout(() => {
      v.reveal.forEach((idx) => {
        const b = btnAt(idx);
        if (b) { b.textContent = "?"; b.classList.remove("lit"); }
      });
      puzzleLocked = false;
    }, 900);
  }
}

/* -------------------------------------------------------------- events */
const EVENT_SFX = {
  gold: "gold", pickup: "pickup", step: "step", drop: "drop", potion: "potion",
  strength: "strength", cure: "cure", enchant: "enchant", scroll: "scroll",
  equip: "equip", teleport: "teleport", buy: "buy", sell: "sell",
  poisoned: "splat", poison_tick: "poison_tick",
  puzzle_open: "puzzle_open", puzzle_solved: "unlock", unlock: "unlock",
  chest_open: "chest_open", chest_locked: "locked",
  lever: "lever", plate: "plate", push: "push",
};

function handleEvents(events) {
  lastEventTypes = new Set(events.map((ev) => ev.type));
  for (const ev of events) {
    // Any event the engine tagged with a `toast` string surfaces as a
    // right-side popup (in Toasts mode). The engine is the single source of
    // both the wording and which events are toast-worthy - see world.py.
    if (ev.toast) showToast(ev.toast, ev.cat);
    switch (ev.type) {
      case "hit":
        audio.play(ev.crit ? "crit" : "hit");
        floatNum(ev.x, ev.y, String(ev.dmg), ev.crit ? "#ffd24a" : "#ffffff");
        addLunge("hero", Math.sign(ev.x - snap.player.x),
                 Math.sign(ev.y - snap.player.y));
        break;
      case "player_hit":
        audio.play("player_hurt");
        floatNum(snap.player.x, snap.player.y, String(ev.dmg), "#ff6b6b");
        shake();
        if (ev.x !== undefined) {
          addLunge(ev.x + "," + ev.y, Math.sign(snap.player.x - ev.x),
                   Math.sign(snap.player.y - ev.y));
        }
        break;
      case "kill":
        audio.play(ev.boss ? "boss_kill" : "kill");
        if (ev.boss) shake();
        break;
      case "levelup":
        audio.play("levelup");
        floatNum(snap.player.x, snap.player.y, "LEVEL UP!", "#f2c94c");
        break;
      case "fireball":
        audio.play("fireball");
        shake();
        break;
      case "trap":
        audio.play("trap");
        if (ev.dmg !== undefined) floatNum(snap.player.x, snap.player.y, String(ev.dmg), "#e07030");
        break;
      case "descend":
        audio.play("stairs");
        if (ev.boss_floor) audio.play("boss_intro");
        fadeIn();
        break;
      case "player_death":
        audio.play("death");
        shake();
        break;
      case "puzzle_fail":
        audio.play("puzzle_fail");
        shake();
        break;
      case "summon":
        audio.play("summon");
        floatNum(ev.x, ev.y, "!", "#b060e0");
        break;
      case "mimic":
        audio.play("mimic");
        shake();
        break;
      case "lore_page":
        audio.play("pickup");
        openLorePagePopup(ev.author, ev.text);
        break;
      case "boss_awaken_countdown":
        audio.play("boss_telegraph");
        break;
      case "boss_awaken":
        audio.play("boss_phase");
        floatNum(ev.x, ev.y, "!", "#ff3b3b");
        shake();
        break;
      case "boss_telegraph":
        audio.play("boss_telegraph");
        floatNum(ev.x, ev.y, "!", "#ff3b3b");
        break;
      case "boss_phase":
        audio.play("boss_phase");
        floatNum(ev.x, ev.y, "ENRAGED!", "#ff3b3b");
        shake();
        break;
      case "boss_ability":
        audio.play("boss_ability");
        break;
      case "boss_ability_miss":
        audio.play("boss_ability_miss");
        floatNum(snap.player.x, snap.player.y, "miss!", "#8fd9ef");
        break;
      case "boss_door_sealed":
        audio.play("locked");
        break;
      case "boss_arena_open":
        audio.play("unlock");
        break;
      default:
        if (EVENT_SFX[ev.type]) audio.play(EVENT_SFX[ev.type]);
        if (ev.type === "poisoned") floatNum(snap.player.x, snap.player.y, "poison!", "#58c058");
        if (ev.type === "poison_tick") floatNum(snap.player.x, snap.player.y, String(ev.dmg), "#58c058");
        if (ev.type === "status_tick") {
          audio.play("poison_tick");
          floatNum(snap.player.x, snap.player.y, String(ev.dmg), ev.status === "burn" ? "#e05656" : "#c94a4a");
        }
        if (ev.type === "status_expired") floatNum(snap.player.x, snap.player.y, `${ev.status} fades`, "#9a9a9a");
        if (ev.type === "status_applied") {
          audio.play("splat");
          floatNum(snap.player.x, snap.player.y, `${ev.status}!`, ev.status === "burn" ? "#e05656" : "#c94a4a");
        }
        if (ev.type === "monster_status_tick") {
          floatNum(ev.x, ev.y, String(ev.dmg), ev.status === "burn" ? "#e05656" : "#c94a4a");
        }
        if (ev.type === "monster_status_applied") {
          audio.play("splat");
          floatNum(ev.x, ev.y, `${ev.status}!`, ev.status === "burn" ? "#e05656" : "#c94a4a");
        }
        if (ev.type === "lifesteal") {
          audio.play("potion");
          floatNum(snap.player.x, snap.player.y, `+${ev.amount}`, "#58c058");
        }
        if (ev.type === "strength") floatNum(snap.player.x, snap.player.y, "+STR", "#e0a83a");
    }
  }
}

function floatNum(x, y, text, color) {
  const sx = (x - cam.x) * TILE + TILE / 2;
  const sy = (y - cam.y) * TILE;
  if (sx < 0 || sx > canvas.width || sy < 0 || sy > canvas.height) return;
  // The canvas may be CSS-scaled (phone layout); fx-layer uses CSS pixels.
  const k = canvas.clientWidth ? canvas.clientWidth / canvas.width : 1;
  const div = document.createElement("div");
  div.className = "dmg-num";
  div.style.left = sx * k - 10 + "px";
  div.style.top = sy * k - 6 + "px";
  div.style.color = color;
  div.textContent = text;
  $("fx-layer").appendChild(div);
  setTimeout(() => div.remove(), 850);
}

function shake() {
  if (!gameSettings.shake_on) return;
  const wrap = $("canvas-wrap");
  wrap.classList.remove("shake");
  void wrap.offsetWidth; // restart animation
  wrap.classList.add("shake");
}

// Transient right-side toast (Toasts mode only). Newest on top; the stack is
// capped so a burst (a chest dumping several items) can't fill the screen.
// Each toast fades itself out after a few seconds, mirroring floatNum/fadeIn's
// create-append-timeout-remove pattern.
function showToast(text, cat) {
  if (gameSettings.feed_mode !== "toasts") return;
  const layer = $("toast-layer");
  if (!layer) return;
  const div = document.createElement("div");
  div.className = "toast" + (cat ? " cat-" + cat : "");
  div.textContent = text;
  layer.insertBefore(div, layer.firstChild);
  while (layer.children.length > 5) layer.lastChild.remove();
  setTimeout(() => {
    div.classList.add("leaving");
    setTimeout(() => div.remove(), 400);
  }, 3000);
}

/* ------------------------------------------------------------ settings */
let settingsReturnMode = "title";

function refreshSettingsLabels() {
  $("setting-music").textContent = `Music: ${gameSettings.music_on ? "On" : "Off"}`;
  $("setting-sfx").textContent = `Sound Effects: ${gameSettings.sfx_on ? "On" : "Off"}`;
  $("setting-shake").textContent = `Screen Shake: ${gameSettings.shake_on ? "On" : "Off"}`;
  $("setting-feed").textContent = `Messages: ${gameSettings.feed_mode === "toasts" ? "Toasts" : "Log"}`;
  $("setting-dpad").textContent = `Touch D-pad: ${gameSettings.dpad_on ? "On" : "Off"}`;
}

function openSettings() {
  settingsReturnMode = mode;
  mode = "settings";
  refreshSettingsLabels();
  $("settings-overlay").classList.remove("hidden");
}

function closeSettings() {
  $("settings-overlay").classList.add("hidden");
  mode = settingsReturnMode;
  if (mode === "play") render(); // picks up any texture pack change made while open
}

function toggleSetting(key) {
  gameSettings[key] = !gameSettings[key];
  persistSettings();
  if (key === "music_on") audio.applySettings();
  refreshSettingsLabels();
}

function fadeIn() {
  const div = document.createElement("div");
  div.className = "fade-in";
  $("fx-layer").appendChild(div);
  setTimeout(() => div.remove(), 550);
}

/* -------------------------------------------------------------- render */
function render() {
  if (!snap || !floorData) return;
  const p = snap.player;
  cam.x = Math.min(Math.max(p.x - Math.floor(VIEW_COLS / 2), 0), Math.max(0, floorData.width - VIEW_COLS));
  cam.y = Math.min(Math.max(p.y - Math.floor(VIEW_ROWS / 2), 0), Math.max(0, floorData.height - VIEW_ROWS));

  ctx.imageSmoothingEnabled = false;
  ctx.fillStyle = "#111114";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const blit = (key, col, row) =>
    ctx.drawImage(atlas[key], col * TILE, row * TILE, TILE, TILE);

  const decorAt = {};
  for (const [dx, dy, key] of floorData.decor) decorAt[dx + "," + dy] = key;
  const trapAt = {};
  for (const t of snap.traps) trapAt[t.x + "," + t.y] = t.sprite;
  const propOn = {};   // lever/plate on-state by position
  const switchAt = {}; // the push-block rune switch (an overlay, not a tile)
  for (const pr of snap.puzzle_props || []) {
    if (pr.kind === "switch") switchAt[pr.x + "," + pr.y] = true;
    else propOn[pr.x + "," + pr.y] = pr.on;
  }

  for (let row = 0; row < VIEW_ROWS; row++) {
    const fy = cam.y + row;
    if (fy >= floorData.height) continue;
    for (let col = 0; col < VIEW_COLS; col++) {
      const fx = cam.x + col;
      if (fx >= floorData.width) continue;
      if (snap.explored[fy][fx] !== "1") continue;
      const visible = snap.visible[fy][fx] === "1";
      const tile = floorData.tiles[fy][fx];
      const dim = visible ? "" : "_dim";

      const variant = floorData.variants ? floorData.variants[fy][fx] : "0";
      const key = fx + "," + fy;
      let base = "floor";
      if (tile === "#") base = variant === "1" ? "wall2" : "wall";
      else if (tile === ">") base = "stairs";
      else if (tile === "+") base = "door_rune";
      else if (tile === "=") base = "door_boss";
      else if (tile === "&") base = "chest";
      else if (tile === "B") base = "block";
      else if (tile === "L") base = propOn[key] ? "lever_down" : "lever_up";
      else if (tile === "_") base = propOn[key] ? "plate_on" : "plate_off";
      else if (variant === "1") base = "floor2";
      else if (variant === "2") base = "floor3";
      // Biome palette (engine/biomes.py) only applies to plain floor/wall
      // tiles - stairs/doors/chests/etc keep their fixed look everywhere.
      if (base === "floor" || base === "floor2" || base === "floor3" || base === "wall" || base === "wall2") {
        base += floorData.biome || "";
      }
      blit(base + dim, col, row);

      if (trapAt[key]) blit(trapAt[key] + dim, col, row);
      else if (tile === "." && decorAt[key]) blit(decorAt[key] + dim, col, row);

      if (tile === "." && switchAt[key]) blit("rune_switch" + dim, col, row);
      if (tile === "$" && visible) blit("shopkeeper", col, row);
    }
  }

  for (const it of snap.items) {
    if (inView(it.x, it.y) && snap.visible[it.y][it.x] === "1") {
      blit(it.sprite, it.x - cam.x, it.y - cam.y);
    }
  }
  const { heroOff, monsterOffs } = lungeOffsets();
  for (const m of snap.monsters) {
    if (!inView(m.x, m.y) || snap.visible[m.y][m.x] !== "1") continue;
    const col = m.x - cam.x, row = m.y - cam.y;
    let [mox, moy] = monsterOffs[m.x + "," + m.y] || [0, 0];
    if (!mox && !moy && !REDUCED_MOTION) {
      moy = (m.x * 7 + m.y * 13 + animTick) % 2; // ambient sway
    }
    const mx = col * TILE + mox, my = row * TILE + moy;
    ctx.drawImage(atlas[m.sprite], mx, my, TILE, TILE);
    if (m.boss) ctx.drawImage(atlas["crown"], mx, my, TILE, TILE);
    else if (m.elite) ctx.drawImage(atlas["elite_mark"], mx, my, TILE, TILE);
    if (m.hp < m.max_hp) {
      const w = TILE - 8;
      ctx.fillStyle = "#20141a";
      ctx.fillRect(mx + 4, my + 1, w, 3);
      ctx.fillStyle = "#e04848";
      ctx.fillRect(mx + 4, my + 1, Math.floor(w * m.hp / m.max_hp), 3);
    }
  }

  let [hox, hoy] = heroOff;
  if (!hox && !hoy && !REDUCED_MOTION) hoy = animTick % 2; // idle breathing
  ctx.drawImage(heroSprite(p.hero, heroFacing),
                (p.x - cam.x) * TILE + hox, (p.y - cam.y) * TILE + hoy, TILE, TILE);

  if (autoWalk.target && mode === "play") {
    const tc = autoWalk.target.x - cam.x, tr = autoWalk.target.y - cam.y;
    if (tc >= 0 && tr >= 0 && tc < VIEW_COLS && tr < VIEW_ROWS) {
      ctx.strokeStyle = "#ffe45e";
      ctx.lineWidth = 2;
      ctx.strokeRect(tc * TILE + 2, tr * TILE + 2, TILE - 4, TILE - 4);
    }
  }

  renderPanel();
  renderLog();
  renderMinimap();
}

function inView(x, y) {
  return x >= cam.x && x < cam.x + VIEW_COLS && y >= cam.y && y < cam.y + VIEW_ROWS;
}

function renderPanel() {
  const p = snap.player;
  $("stat-depth").textContent = `Depth: ${snap.depth}`;
  $("stat-level").textContent = `Level: ${p.level}   XP: ${p.xp}/${p.xp_to_next}`;
  $("hp-fill").style.width = (100 * p.hp / Math.max(1, p.max_hp)) + "%";
  $("hp-text").textContent = `HP  ${p.hp}/${p.max_hp}`;
  $("xp-fill").style.width = (100 * p.xp / Math.max(1, p.xp_to_next)) + "%";
  $("boss-nameplate").classList.toggle("hidden", !snap.boss);
  if (snap.boss) {
    $("boss-name").textContent = `${snap.boss.title}  -  ${snap.boss.status}`;
    $("boss-fill").style.width = (100 * snap.boss.hp / Math.max(1, snap.boss.max_hp)) + "%";
    $("boss-text").textContent = `${snap.boss.hp}/${snap.boss.max_hp}`;
  }
  const st = $("stat-status");
  if (p.poisoned) {
    st.textContent = "Status: POISONED - find a cure!";
    st.style.color = "#58c058";
  } else {
    st.textContent = "Status: Healthy";
    st.style.color = "var(--dim)";
  }
  $("stat-attack").textContent = `Attack: ${p.attack}`;
  $("stat-defense").textContent = `Defense: ${p.defense}`;
  $("stat-gold").textContent = `Gold: ${p.gold}`;
  $("stat-weapon").textContent = `Weapon: ${p.weapon || "(none)"}`;
  $("stat-armor").textContent = `Armor: ${p.armor || "(none)"}`;
  $("stat-accessory").textContent = `Accessory: ${p.accessory || "(none)"}`;
  $("stat-kills").textContent = `Kills: ${p.kills}   Turns: ${p.turns}`;
  $("stat-seed").textContent = `Seed: ${snap.seed} (tap to copy)`;
  $("stat-timer").classList.toggle("hidden", snap.run_mode !== "speedrun");
}

function renderLog() {
  if (gameSettings.feed_mode === "toasts") return; // log is hidden; skip the work
  $("log").innerHTML = snap.log.map((l) => `<div>${escapeHtml(l)}</div>`).join("");
  $("log").scrollTop = $("log").scrollHeight;
}

// The terrain layer only changes when a tile newly becomes explored (or the
// floor changes) - which is rare compared to how often render() runs (every
// single move). Cache it to an offscreen canvas and skip the full 60x32
// fillRect loop entirely when nothing new was revealed; only the player
// marker (one cheap fillRect) needs to be redrawn every frame regardless.
let minimapCache = null;
let minimapCacheDepth = null;
let minimapCacheExplored = null;

function renderMinimap() {
  const scale = Math.max(1, Math.min(Math.floor(minimap.width / floorData.width),
                                     Math.floor(minimap.height / floorData.height)));
  const ox = Math.floor((minimap.width - floorData.width * scale) / 2);
  const oy = Math.floor((minimap.height - floorData.height * scale) / 2);
  const exploredKey = snap.explored.join("");
  if (!minimapCache || minimapCacheDepth !== floorData.depth || minimapCacheExplored !== exploredKey) {
    if (!minimapCache) {
      minimapCache = document.createElement("canvas");
      minimapCache.width = minimap.width;
      minimapCache.height = minimap.height;
    }
    const g = minimapCache.getContext("2d");
    g.fillStyle = "#111114";
    g.fillRect(0, 0, minimap.width, minimap.height);
    for (let y = 0; y < floorData.height; y++) {
      for (let x = 0; x < floorData.width; x++) {
        if (snap.explored[y][x] !== "1") continue;
        const tile = floorData.tiles[y][x];
        g.fillStyle = tile === "#" ? "#2a2a33" : tile === ">" ? "#66d9ef"
          : tile === "$" || tile === "&" ? "#f2c94c" : tile === "+" ? "#e0a83a"
          : tile === "=" ? "#ff3b3b"
          : tile === "L" || tile === "B" ? "#5a5a68" : "#4a4a58";
        g.fillRect(ox + x * scale, oy + y * scale, scale, scale);
      }
    }
    minimapCacheDepth = floorData.depth;
    minimapCacheExplored = exploredKey;
  }
  mmCtx.drawImage(minimapCache, 0, 0);
  mmCtx.fillStyle = "#ffe45e";
  mmCtx.fillRect(ox + snap.player.x * scale - 1, oy + snap.player.y * scale - 1, scale + 2, scale + 2);
}

function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/* ------------------------------------------------- inventory overlay */
let invSel = 0;
// Fetched on demand (only while the inventory/shop overlay is open or just
// changed) rather than on every move/wait snapshot - see webbridge.py
// inventory_json()/shop_json().
let invItems = [];
let shopItems = [];

function refreshItemLists() {
  invItems = JSON.parse(bridge.inventory_json());
  shopItems = JSON.parse(bridge.shop_json());
}

function openInventory() {
  stopAutoWalk();
  mode = "inventory";
  invSel = 0;
  refreshItemLists();
  $("inventory-overlay").classList.remove("hidden");
  renderInventory();
  audio.play("menu");
}

function closeInventory() {
  $("inventory-overlay").classList.add("hidden");
  mode = "play";
  render();
}

function renderInventory() {
  const items = invItems;
  invSel = Math.max(0, Math.min(invSel, items.length - 1));
  $("inv-gold").textContent = `Gold: ${snap.player.gold}`;
  const p = snap.player;
  $("inv-equipped").textContent =
    `Weapon: ${p.weapon || "(none)"}   Armor: ${p.armor || "(none)"}   Accessory: ${p.accessory || "(none)"}`;
  renderItemList($("inv-list"), items, invSel, (i) => { invSel = i; renderInventory(); },
    () => inventoryActivate(),
    (e) => e.label + (e.equipped ? " [equipped]" : ""));
  renderDetails("inv-detail-name", "inv-detail-body", items[invSel],
    (e) => [...e.details, `Sells for ${e.sell_price} gold.`]);
}

function inventoryActivate() {
  const entry = invItems[invSel];
  if (!entry) return;
  if (entry.category === "potion" || entry.category === "scroll") {
    afterAction(bridge.use_item(entry.id));
  } else if (["weapon", "armor", "accessory"].includes(entry.category)) {
    afterAction(bridge.equip_item(entry.id));
  }
  if (mode === "inventory") { refreshItemLists(); renderInventory(); }
}

function inventoryDrop() {
  const entry = invItems[invSel];
  if (!entry) return;
  afterAction(bridge.drop_item(entry.id));
  if (mode === "inventory") { refreshItemLists(); renderInventory(); }
}

/* ------------------------------------------------------ shop overlay */
let shopTab = "buy";
let shopSel = 0;

function openShop() {
  mode = "shop";
  shopTab = "buy";
  shopSel = 0;
  refreshItemLists();
  $("shop-overlay").classList.remove("hidden");
  renderShop();
  audio.play("shop_bell");
}

function closeShopOverlay() {
  bridge.close_shop();
  $("shop-overlay").classList.add("hidden");
  mode = "play";
  persistSave();
  render();
}

function shopSetTab(tab) {
  shopTab = tab;
  shopSel = 0;
  renderShop();
}

function shopEntries() {
  return shopTab === "buy" ? shopItems : invItems;
}

function renderShop() {
  const items = shopEntries();
  shopSel = Math.max(0, Math.min(shopSel, items.length - 1));
  $("shop-gold").textContent = `Gold: ${snap.player.gold}`;
  $("tab-buy").classList.toggle("active", shopTab === "buy");
  $("tab-sell").classList.toggle("active", shopTab === "sell");
  $("shop-action").textContent = shopTab === "buy" ? "Buy (Enter)" : "Sell (Enter)";
  renderItemList($("shop-list"), items, shopSel, (i) => { shopSel = i; renderShop(); },
    () => shopActivate(),
    (e) => shopTab === "buy"
      ? `${e.label} - ${e.price}g`
      : `${e.label}${e.equipped ? " [equipped]" : ""} - ${e.sell_price}g`,
    (e) => (shopTab === "buy" && !e.affordable) ? "#e05f5f" : e.color);
  renderDetails("shop-detail-name", "shop-detail-body", items[shopSel], (e) => {
    const lines = [...e.details];
    if (shopTab === "buy") {
      lines.push(`Price: ${e.price} gold.`);
      if (!e.affordable) lines.push("You can't afford this!");
    } else {
      lines.push(`Sells for ${e.sell_price} gold.`);
      if (e.equipped) lines.push("Selling will unequip it.");
    }
    return lines;
  });
}

function shopActivate() {
  const entry = shopEntries()[shopSel];
  if (!entry) return;
  afterAction(shopTab === "buy" ? bridge.buy_item(entry.id) : bridge.sell_item(entry.id));
  if (mode === "shop" || snap.shop_open) { refreshItemLists(); renderShop(); }
}

/* ------------------------------------------------ shared list helpers */
// Items arrive from webbridge.py already grouped by category and sorted
// best-to-worst within each group (ui/iteminfo.py:sort_items) - this just
// draws a header whenever the category changes and keeps click handlers
// wired to the item's real index in `items` despite the extra header rows.
function renderItemList(ul, items, sel, onSelect, onActivate, labelFn, colorFn) {
  ul.innerHTML = "";
  if (!items.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "(empty)";
    ul.appendChild(li);
    return;
  }
  let lastCategory = null;
  const itemLis = [];
  items.forEach((entry, i) => {
    if (entry.category !== lastCategory) {
      lastCategory = entry.category;
      const header = document.createElement("li");
      header.className = "cat-header";
      header.textContent = categoryLabels[entry.category] || entry.category;
      ul.appendChild(header);
    }
    const li = document.createElement("li");
    li.textContent = labelFn ? labelFn(entry) : entry.label;
    li.style.color = colorFn ? colorFn(entry) : entry.color;
    if (i === sel) li.classList.add("selected");
    li.addEventListener("click", () => onSelect(i));
    li.addEventListener("dblclick", () => { onSelect(i); onActivate(); });
    ul.appendChild(li);
    itemLis[i] = li;
  });
  const selected = itemLis[sel];
  if (selected) selected.scrollIntoView({ block: "nearest" });
}

function renderDetails(nameId, bodyId, entry, linesFn) {
  if (!entry) {
    $(nameId).textContent = "Nothing here";
    $(nameId).style.color = "var(--dim)";
    $(bodyId).textContent = "";
    return;
  }
  $(nameId).textContent = entry.label + (entry.equipped ? " [equipped]" : "");
  $(nameId).style.color = entry.color;
  $(bodyId).textContent = linesFn(entry).join("\n");
}

/* --------------------------------------------------------------- input */
const MOVE_KEYS = {
  ArrowUp: [0, -1], w: [0, -1], W: [0, -1],
  ArrowDown: [0, 1], s: [0, 1], S: [0, 1],
  ArrowLeft: [-1, 0], a: [-1, 0], A: [-1, 0],
  ArrowRight: [1, 0], d: [1, 0], D: [1, 0],
};

document.addEventListener("keydown", (e) => {
  if (!bridge) return;
  // While typing in the seed field or replay-code box, letters are text,
  // not shortcuts.
  const el = document.activeElement;
  if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA")) {
    if (e.key === "Escape") el.blur();
    else if (e.key === "Enter" && el.id === "seed-input") startNewGame();
    return;
  }
  if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Tab"].includes(e.key)) {
    e.preventDefault();
  }
  if (e.key === "m" || e.key === "M") {
    audio.setMuted(!audio.muted);
    if (mode === "play" || mode === "shop" || mode === "inventory") updateMusic();
    return;
  }
  if ((e.key === "f" || e.key === "F") && mode !== "inventory" && mode !== "shop") {
    toggleFullscreen();
    return;
  }
  if ((e.key === "o" || e.key === "O") && (mode === "title" || mode === "play")) {
    openSettings();
    return;
  }
  if (mode === "settings") {
    if (e.key === "Escape") closeSettings();
    return;
  }
  if (mode === "lore_page") {
    if (e.key === "Escape" || e.key === "Enter" || e.key === " ") closeLorePagePopup();
    return;
  }
  switch (mode) {
    case "title":
      if (e.key === "n" || e.key === "N" || e.key === "Enter") startNewGame();
      else if (e.key === "r" || e.key === "R") startSpeedrun();
      else if (e.key === "d" || e.key === "D") startDaily();
      else if ((e.key === "c" || e.key === "C") && !$("btn-continue").disabled) continueGame();
      else if (e.key === "v" || e.key === "V") openReplayPicker();
      else if (e.key === "l" || e.key === "L") showLore(false);
      else if (e.key === "h" || e.key === "H") openGuide();
      else if (e.key === "b" || e.key === "B") openBestiary();
      else if (e.key === "a" || e.key === "A") openAchievements();
      break;
    case "bestiary":
    case "achievements":
    case "journal":
      if (e.key === "Escape") toTitle();
      break;
    case "replay-picker":
      if (e.key === "Escape") toTitle();
      break;
    case "replay":
      if (e.key === " ") toggleReplayPause();
      else if (e.key === "s" || e.key === "S") cycleReplaySpeed();
      else if (e.key === "Escape") stopReplay();
      break;
    case "victory":
      if (e.key === "Enter" || e.key === "Escape") toTitle();
      break;
    case "lore":
      if (e.key === "ArrowRight" || e.key === "Enter" || e.key === " ") loreStep(1);
      else if (e.key === "ArrowLeft" || e.key === "Backspace") loreStep(-1);
      else if (e.key === "Escape") finishLore();
      break;
    case "play":
      if (e.key === "e" || e.key === "E") openInventory();
      else if (e.key === "." || e.key === "z" || e.key === "Z") {
        stopAutoWalk();
        afterAction(bridge.wait_turn());
      } else if (MOVE_KEYS[e.key]) {
        if (e.repeat) {
          const now = performance.now();
          if (now - lastKeyMoveAt < KEY_REPEAT_MS) break;
          lastKeyMoveAt = now;
        } else {
          lastKeyMoveAt = performance.now();
        }
        stopAutoWalk();
        const [dx, dy] = MOVE_KEYS[e.key];
        noteFacing(dx, dy);
        afterAction(bridge.move(dx, dy));
      }
      break;
    case "inventory":
      if (e.key === "Escape") closeInventory();
      else if (e.key === "ArrowUp" || e.key === "k") { invSel--; renderInventory(); }
      else if (e.key === "ArrowDown" || e.key === "j") { invSel++; renderInventory(); }
      else if (e.key === "Enter") inventoryActivate();
      else if (e.key === "d" || e.key === "D") inventoryDrop();
      break;
    case "shop":
      if (e.key === "Escape") closeShopOverlay();
      else if (e.key === "Tab") shopSetTab(shopTab === "buy" ? "sell" : "buy");
      else if (e.key === "ArrowUp" || e.key === "k") { shopSel--; renderShop(); }
      else if (e.key === "ArrowDown" || e.key === "j") { shopSel++; renderShop(); }
      else if (e.key === "Enter") shopActivate();
      break;
    case "puzzle":
      if (e.key === "Escape") closePuzzle();
      else if (e.key >= "1" && e.key <= "9") {
        const index = +e.key - 1;
        if (index < $("puzzle-buttons").children.length) puzzlePress(index);
      }
      break;
    case "gameover":
      // Deliberate keys only, so a stray keypress can't skip the
      // Save Replay buttons.
      if (e.key === "Enter" || e.key === "Escape") toTitle();
      break;
  }
});

/* ------------------------------------------- tap-to-move + auto-walk */
// The canvas is the primary touch control surface: tap a tile to walk
// there (BFS over explored tiles, one recorded bridge.move per step, so
// replays are unaffected), tap an adjacent monster/chest/door to bump it,
// tap the hero to wait. Swiping steps once; holding a drag keeps walking.
const DIRS4 = [[1, 0], [-1, 0], [0, 1], [0, -1]];
const WALKABLE_TILES = new Set([".", ">", "_"]);
const BUMPABLE_TILES = new Set(["$", "+", "=", "&", "L", "B"]); // mirror SOLID_TILES
const AUTO_STEP_MS = 150;
// Tap/drag/D-pad/gamepad all self-throttle to ~150-170ms between moves;
// held-key OS auto-repeat was the one input path with no cap at all, able
// to re-enter the full move pipeline faster than the engine/render loop
// can keep up. KeyboardEvent.repeat lets the FIRST press stay instant
// (unchanged feel) while gating only the OS-repeated events that follow.
const KEY_REPEAT_MS = 150;
let lastKeyMoveAt = 0;
// Anything that should snap the player out of an auto-walk. poison_tick is
// deliberately absent: permanent poison would otherwise cancel every other
// step, and its damage can never be lethal.
const AUTOWALK_CANCEL = ["player_hit", "trap", "teleport", "poisoned",
                         "summon", "mimic", "descend", "player_death",
                         "puzzle_fail"];

const autoWalk = { target: null, timer: null, monsterBaseline: 0 };

function countVisibleMonsters() {
  let n = 0;
  for (const m of snap.monsters) {
    if (snap.visible[m.y][m.x] === "1") n++;
  }
  return n;
}

function stopAutoWalk() {
  clearTimeout(autoWalk.timer);
  autoWalk.timer = null;
  if (autoWalk.target) {
    autoWalk.target = null;
    if (snap && floorData && mode === "play") render(); // clear the marker
  }
}

// Next step from (sx,sy) toward (tx,ty), or null. Interior tiles must be
// explored, walkable, free of visible monsters and lit pressure plates;
// the goal tile itself may be solid or occupied (final step = bump).
function bfsNextStep(sx, sy, tx, ty) {
  if (sx === tx && sy === ty) return null;
  const W = floorData.width, H = floorData.height;
  const tiles = floorData.tiles;
  const blocked = new Set();
  for (const m of snap.monsters) {
    if (snap.visible[m.y][m.x] === "1") blocked.add(m.x + "," + m.y);
  }
  for (const pr of snap.puzzle_props || []) {
    if (pr.kind === "plate" && pr.on) blocked.add(pr.x + "," + pr.y);
  }
  const startK = sx + "," + sy, goalK = tx + "," + ty;
  const cameFrom = new Map([[startK, null]]);
  const queue = [[sx, sy]];
  let qi = 0;
  while (qi < queue.length) {
    const [cx, cy] = queue[qi++];
    if (cx === tx && cy === ty) break;
    for (const [dx, dy] of DIRS4) {
      const nx = cx + dx, ny = cy + dy;
      if (nx < 0 || ny < 0 || nx >= W || ny >= H) continue;
      const k = nx + "," + ny;
      if (cameFrom.has(k)) continue;
      if (snap.explored[ny][nx] !== "1") continue;
      if (k !== goalK && (!WALKABLE_TILES.has(tiles[ny][nx]) || blocked.has(k))) continue;
      cameFrom.set(k, cx + "," + cy);
      queue.push([nx, ny]);
    }
  }
  if (!cameFrom.has(goalK)) return null;
  let k = goalK;
  while (cameFrom.get(k) !== startK) {
    k = cameFrom.get(k);
    if (!k) return null;
  }
  return k.split(",").map(Number);
}

function autoWalkStep() {
  autoWalk.timer = null;
  if (!snap || mode !== "play" || snap.game_over || !autoWalk.target) {
    stopAutoWalk();
    return;
  }
  const t = autoWalk.target;
  const px = snap.player.x, py = snap.player.y;
  const step = bfsNextStep(px, py, t.x, t.y);
  if (!step) {
    stopAutoWalk();
    return;
  }
  noteFacing(step[0] - px, step[1] - py);
  afterAction(bridge.move(step[0] - px, step[1] - py));
  const p = snap.player;
  const arrived = p.x === t.x && p.y === t.y;
  const bumped = p.x === px && p.y === py; // attacked/opened/pushed something
  const visNow = countVisibleMonsters();
  const danger = visNow > autoWalk.monsterBaseline ||
                 AUTOWALK_CANCEL.some((e) => lastEventTypes.has(e));
  autoWalk.monsterBaseline = visNow;
  if (arrived || bumped || danger || mode !== "play" || snap.game_over) {
    stopAutoWalk();
    return;
  }
  autoWalk.timer = setTimeout(autoWalkStep, AUTO_STEP_MS);
}

function startAutoWalk(x, y) {
  stopAutoWalk();
  autoWalk.target = { x, y };
  autoWalk.monsterBaseline = countVisibleMonsters();
  autoWalkStep();
}

function tileAtClient(clientX, clientY) {
  const rect = canvas.getBoundingClientRect();
  if (!floorData || !rect.width || !rect.height) return null;
  const col = Math.floor((clientX - rect.left) / rect.width * VIEW_COLS);
  const row = Math.floor((clientY - rect.top) / rect.height * VIEW_ROWS);
  if (col < 0 || row < 0 || col >= VIEW_COLS || row >= VIEW_ROWS) return null;
  const x = cam.x + col, y = cam.y + row;
  if (x >= floorData.width || y >= floorData.height) return null;
  return { x, y };
}

function tapAt(clientX, clientY) {
  const t = tileAtClient(clientX, clientY);
  const prev = autoWalk.target;
  stopAutoWalk();
  if (!t || !snap || mode !== "play") return;
  if (t.x === snap.player.x && t.y === snap.player.y) {
    afterAction(bridge.wait_turn());
    return;
  }
  if (prev && prev.x === t.x && prev.y === t.y) return; // tap target = cancel
  if (snap.explored[t.y][t.x] !== "1") return;
  const tile = floorData.tiles[t.y][t.x];
  const monsterThere = snap.monsters.some(
    (m) => m.x === t.x && m.y === t.y && snap.visible[m.y][m.x] === "1");
  if (!WALKABLE_TILES.has(tile) && !BUMPABLE_TILES.has(tile) && !monsterThere) return;
  startAutoWalk(t.x, t.y);
}

/* Canvas gestures: tap = walk/bump/wait, swipe = one step, held drag =
 * keep stepping in the drag direction (a floating 4-way joystick). */
const SWIPE_PX = 24;
const DRAG_REPEAT_MS = 170;
let gesture = null;

function quantizeDir(dx, dy) {
  return Math.abs(dx) > Math.abs(dy) ? [Math.sign(dx), 0] : [0, Math.sign(dy)];
}

function dragStep() {
  if (!gesture || !gesture.dir || !bridge || mode !== "play") return;
  const [dx, dy] = gesture.dir;
  if (!dx && !dy) return; // finger back at the origin: no direction, no turn
  noteFacing(dx, dy);
  afterAction(bridge.move(dx, dy));
}

canvas.addEventListener("pointerdown", (e) => {
  if (!bridge || mode !== "play" || !snap || gesture) return;
  e.preventDefault();
  try { canvas.setPointerCapture(e.pointerId); } catch {}
  gesture = { id: e.pointerId, x0: e.clientX, y0: e.clientY,
              dragging: false, dir: null, timer: null };
});

canvas.addEventListener("pointermove", (e) => {
  if (!gesture || e.pointerId !== gesture.id) return;
  const dx = e.clientX - gesture.x0, dy = e.clientY - gesture.y0;
  if (gesture.dragging) {
    gesture.dir = quantizeDir(dx, dy);
  } else if (Math.hypot(dx, dy) >= SWIPE_PX) {
    gesture.dragging = true;
    stopAutoWalk();
    gesture.dir = quantizeDir(dx, dy);
    dragStep();
    gesture.timer = setInterval(dragStep, DRAG_REPEAT_MS);
  }
});

function endGesture(e) {
  if (!gesture || e.pointerId !== gesture.id) return null;
  clearInterval(gesture.timer);
  const g = gesture;
  gesture = null;
  return g;
}

canvas.addEventListener("pointerup", (e) => {
  const g = endGesture(e);
  if (g && !g.dragging) tapAt(g.x0, g.y0);
});
canvas.addEventListener("pointercancel", endGesture);

/* ------------------------------------------------------ touch controls */
const TOUCH_DIRS = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] };
let holdTimer = null;

function touchAct(dir) {
  if (!bridge || mode !== "play") return;
  stopAutoWalk();
  if (dir === "wait") {
    afterAction(bridge.wait_turn());
  } else {
    noteFacing(...TOUCH_DIRS[dir]);
    afterAction(bridge.move(...TOUCH_DIRS[dir]));
  }
}

for (const btn of document.querySelectorAll(".dpad-btn")) {
  const dir = btn.dataset.dir;
  const start = (e) => {
    e.preventDefault();
    // Capture so a thumb drifting off the button doesn't stop the walk.
    try { btn.setPointerCapture(e.pointerId); } catch {}
    touchAct(dir);
    clearInterval(holdTimer);
    holdTimer = setInterval(() => touchAct(dir), 170); // hold to keep walking
  };
  const stop = () => { clearInterval(holdTimer); holdTimer = null; };
  btn.addEventListener("pointerdown", start);
  btn.addEventListener("pointerup", stop);
  btn.addEventListener("pointercancel", stop);
  btn.addEventListener("pointerleave", stop);
}

$("touch-inv").addEventListener("click", () => {
  if (mode === "play") openInventory();
  else if (mode === "inventory") closeInventory();
});
$("touch-settings").addEventListener("click", () => {
  if (mode === "play") openSettings();
});

/* ------------------------------------------------------------ gamepad */
// Standard Gamepad API mapping (https://www.w3.org/TR/gamepad/#remapping) -
// works for any paired controller (Bluetooth/USB) on both desktop and
// mobile browsers, no extra permissions or setup. Polled on a timer since
// the browser only fires connect/disconnect events, never per-input
// changes. Directions repeat like the touch D-pad/drag (170ms cadence);
// face buttons are edge-triggered, firing once per press.
const GAMEPAD_POLL_MS = 60;
const GAMEPAD_DEADZONE = 0.5;
const GAMEPAD_REPEAT_MS = 170;
const GAMEPAD_BTN = { A: 0, B: 1, X: 2, Y: 3, LB: 4, RB: 5, START: 9,
                      DPAD_UP: 12, DPAD_DOWN: 13, DPAD_LEFT: 14, DPAD_RIGHT: 15 };
const GAMEPAD_EDGE_BUTTONS = ["A", "B", "X", "Y", "LB", "RB", "START"];

let gamepadIndex = null;
let gamepadPrevButtons = [];
let gamepadDirTimer = null;
let gamepadLastDirKey = null;

window.addEventListener("gamepadconnected", (e) => {
  gamepadIndex = e.gamepad.index;
  gamepadPrevButtons = [];
  const badge = $("gamepad-badge");
  badge.textContent = `\u{1F3AE} ${e.gamepad.id.slice(0, 40)} connected`;
  badge.classList.add("show");
  clearTimeout(badge._hideTimer);
  badge._hideTimer = setTimeout(() => badge.classList.remove("show"), 2500);
});
window.addEventListener("gamepaddisconnected", (e) => {
  if (e.gamepad.index !== gamepadIndex) return;
  gamepadIndex = null;
  clearInterval(gamepadDirTimer);
  gamepadDirTimer = null;
  gamepadLastDirKey = null;
});

function gamepadDirection(gp) {
  if (gp.buttons[GAMEPAD_BTN.DPAD_UP]?.pressed) return [0, -1];
  if (gp.buttons[GAMEPAD_BTN.DPAD_DOWN]?.pressed) return [0, 1];
  if (gp.buttons[GAMEPAD_BTN.DPAD_LEFT]?.pressed) return [-1, 0];
  if (gp.buttons[GAMEPAD_BTN.DPAD_RIGHT]?.pressed) return [1, 0];
  const ax = gp.axes[0] || 0, ay = gp.axes[1] || 0;
  if (Math.abs(ax) > GAMEPAD_DEADZONE || Math.abs(ay) > GAMEPAD_DEADZONE) {
    return quantizeDir(ax, ay); // shared with the touch swipe/drag gesture
  }
  return null;
}

// Whether a direction should auto-repeat while held, or fire once per
// press. Movement and list-scrolling feel right repeating (like OS key
// repeat); one-shot toggles (shop tab, lore page) would just flicker.
function gamepadDirRepeats(dir) {
  if (mode === "play") return true;
  if ((mode === "inventory" || mode === "shop") && dir[1] !== 0) return true;
  return false;
}

function gamepadDirAct(dir) {
  if (!bridge || !dir) return;
  if (mode === "play") {
    stopAutoWalk();
    noteFacing(dir[0], dir[1]);
    afterAction(bridge.move(dir[0], dir[1]));
  } else if (mode === "inventory") {
    if (dir[1] < 0) { invSel--; renderInventory(); }
    else if (dir[1] > 0) { invSel++; renderInventory(); }
  } else if (mode === "shop") {
    if (dir[1] < 0) { shopSel--; renderShop(); }
    else if (dir[1] > 0) { shopSel++; renderShop(); }
    else if (dir[0] !== 0) shopSetTab(shopTab === "buy" ? "sell" : "buy");
  } else if (mode === "lore") {
    if (dir[0] > 0) loreStep(1);
    else if (dir[0] < 0) loreStep(-1);
  }
}

function gamepadButtonPress(name) {
  switch (name) {
    case "A":
      if (mode === "play") afterAction(bridge.wait_turn());
      else if (mode === "inventory") inventoryActivate();
      else if (mode === "shop") shopActivate();
      else if (mode === "title") startNewGame();
      else if (mode === "victory" || mode === "gameover") toTitle();
      else if (mode === "lore") loreStep(1);
      break;
    case "B":
      if (mode === "inventory") closeInventory();
      else if (mode === "shop") closeShopOverlay();
      else if (mode === "puzzle") closePuzzle();
      else if (mode === "settings") closeSettings();
      else if (mode === "replay-picker") toTitle();
      else if (mode === "replay") stopReplay();
      else if (mode === "lore") finishLore();
      break;
    case "X":
      if (mode === "inventory") inventoryDrop();
      break;
    case "Y":
      if (mode === "play") openInventory();
      break;
    case "LB": case "RB":
      if (mode === "shop") shopSetTab(shopTab === "buy" ? "sell" : "buy");
      break;
    case "START":
      if (mode === "play") openSettings();
      break;
  }
}

function pollGamepad() {
  if (gamepadIndex !== null && bridge) {
    const gp = navigator.getGamepads()[gamepadIndex];
    if (gp) {
      for (const name of GAMEPAD_EDGE_BUTTONS) {
        const idx = GAMEPAD_BTN[name];
        const pressed = gp.buttons[idx]?.pressed || false;
        if (pressed && !gamepadPrevButtons[idx]) gamepadButtonPress(name);
        gamepadPrevButtons[idx] = pressed;
      }
      const dir = gamepadDirection(gp);
      const dirKey = dir ? dir.join(",") : null;
      if (dirKey !== gamepadLastDirKey) {
        clearInterval(gamepadDirTimer);
        gamepadDirTimer = null;
        gamepadLastDirKey = dirKey;
        if (dir) {
          gamepadDirAct(dir);
          if (gamepadDirRepeats(dir)) {
            gamepadDirTimer = setInterval(() => gamepadDirAct(dir), GAMEPAD_REPEAT_MS);
          }
        }
      }
    }
  }
  setTimeout(pollGamepad, GAMEPAD_POLL_MS);
}
pollGamepad();

/* --------------------------------------------------------- UI buttons */
$("btn-new").addEventListener("click", startNewGame);
$("btn-continue").addEventListener("click", continueGame);
$("btn-title").addEventListener("click", toTitle);
$("btn-lore").addEventListener("click", () => showLore(false));
$("btn-help").addEventListener("click", openGuide);
$("btn-bestiary").addEventListener("click", openBestiary);
$("btn-achievements").addEventListener("click", openAchievements);
$("bestiary-back").addEventListener("click", toTitle);
$("achievements-back").addEventListener("click", toTitle);
$("btn-daily").addEventListener("click", startDaily);
$("score-view-top").addEventListener("click", () => setTitleScoreView("top"));
$("score-view-recent").addEventListener("click", () => setTitleScoreView("recent"));
$("lore-next").addEventListener("click", () => loreStep(1));
$("lore-back").addEventListener("click", () => loreStep(-1));
$("lore-journal-link").addEventListener("click", openJournal);
$("journal-back").addEventListener("click", toTitle);
$("lore-page-close").addEventListener("click", closeLorePagePopup);
$("btn-speedrun").addEventListener("click", startSpeedrun);
$("btn-watch").addEventListener("click", openReplayPicker);
$("victory-title-btn").addEventListener("click", toTitle);

$("gameover-save-replay").addEventListener("click", downloadReplay);
$("gameover-copy-replay").addEventListener("click", () => copyReplayCode("gameover"));
$("victory-save-replay").addEventListener("click", downloadReplay);
$("victory-copy-replay").addEventListener("click", () => copyReplayCode("victory"));

$("replay-cancel-btn").addEventListener("click", toTitle);
$("replay-play-btn").addEventListener("click", () => {
  const text = $("replay-code-input").value.trim();
  if (!text) { $("replay-error").textContent = "Paste a replay code first."; return; }
  try {
    startReplayPlayback(decodeURIComponent(escape(atob(text))));
  } catch {
    startReplayPlayback(text); // maybe it's raw JSON pasted directly
  }
});
$("replay-file-input").addEventListener("change", (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => startReplayPlayback(reader.result);
  reader.readAsText(file);
});
$("replay-pause-btn").addEventListener("click", toggleReplayPause);
$("replay-speed-btn").addEventListener("click", cycleReplaySpeed);
$("replay-stop-btn").addEventListener("click", stopReplay);

$("stat-seed").addEventListener("click", () => {
  if (snap) navigator.clipboard.writeText(String(snap.seed)).catch(() => {});
});

$("btn-settings").addEventListener("click", openSettings);
$("settings-close").addEventListener("click", closeSettings);
$("puzzle-close").addEventListener("click", closePuzzle);
$("setting-music").addEventListener("click", () => toggleSetting("music_on"));
$("setting-sfx").addEventListener("click", () => toggleSetting("sfx_on"));
$("setting-shake").addEventListener("click", () => toggleSetting("shake_on"));
$("setting-feed").addEventListener("click", () => {
  gameSettings.feed_mode = gameSettings.feed_mode === "toasts" ? "log" : "toasts";
  persistSettings();
  applyFeedSetting();
  refreshSettingsLabels();
  if (snap && floorData) renderLog(); // repopulate the log immediately if just switched to Log mode
});
$("setting-dpad").addEventListener("click", () => {
  toggleSetting("dpad_on");
  applyDpadSetting();
});
$("setting-full").addEventListener("click", toggleFullscreen);
$("setting-export-pack").addEventListener("click", exportTexturePack);
$("setting-import-pack").addEventListener("click", () => $("texture-pack-input").click());
$("setting-reset-pack").addEventListener("click", resetTexturePack);
$("texture-pack-input").addEventListener("change", (e) => {
  const file = e.target.files[0];
  e.target.value = ""; // allow re-selecting the same file later
  if (file) importTexturePackFile(file);
});
$("inv-action").addEventListener("click", inventoryActivate);
$("inv-drop").addEventListener("click", inventoryDrop);
$("inv-close").addEventListener("click", closeInventory);
$("shop-action").addEventListener("click", shopActivate);
$("shop-switch").addEventListener("click", () => shopSetTab(shopTab === "buy" ? "sell" : "buy"));
$("shop-close").addEventListener("click", closeShopOverlay);
$("tab-buy").addEventListener("click", () => shopSetTab("buy"));
$("tab-sell").addEventListener("click", () => shopSetTab("sell"));

boot().catch((err) => {
  $("loading-status").textContent = "Failed to load: " + err.message;
  console.error(err);
});
