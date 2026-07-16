/* Endless Depths - browser front-end.
 * Loads the pure-Python game engine into Pyodide (WebAssembly) and renders
 * it on a canvas. All game logic stays in Python (web/webbridge.py); this
 * file is rendering, input, audio playback and localStorage persistence.
 */
"use strict";

const TILE = 32;
const SPRITE_PX = 16;

// Touch devices get a smaller viewport (bigger on-screen tiles) and the
// on-screen D-pad; the canvas then scales to the screen width via CSS.
const IS_TOUCH = window.matchMedia("(pointer: coarse)").matches || "ontouchstart" in window;
const IS_SMALL = window.matchMedia("(max-width: 760px)").matches;
let VIEW_COLS = IS_SMALL ? 15 : 26;
let VIEW_ROWS = IS_SMALL ? 13 : 16;

const PY_FILES = [
  "engine/__init__.py", "engine/constants.py", "engine/combat.py",
  "engine/dungeon.py", "engine/entities.py", "engine/fov.py",
  "engine/items.py", "engine/puzzles.py", "engine/replay.py", "engine/save.py",
  "engine/shop.py", "engine/world.py",
  "ui/__init__.py", "ui/spritedata.py", "ui/iteminfo.py", "ui/audio.py", "ui/lore.py",
];

const LS_SAVE = "endless_depths_save";
const LS_SCORES = "endless_depths_scores";
const LS_SPEEDRUN_SCORES = "endless_depths_speedrun_scores";
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

canvas.width = VIEW_COLS * TILE;
canvas.height = VIEW_ROWS * TILE;
if (IS_TOUCH) $("touch-controls").classList.add("enabled");

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
  drawTitleHero();

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
    g.drawImage(atlas[key], 0, 0, 48, 48);
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

function heroSprite(hero) {
  const key = [hero.weapon, hero.armor, hero.accessory, hero.poisoned, hero.rarity].join("|");
  if (!heroCache[key]) {
    const def = JSON.parse(bridge.hero_sprite_json(
      hero.weapon, hero.armor, hero.accessory, hero.poisoned, hero.rarity));
    heroCache[key] = spriteCanvas(def.grid, def.palette);
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
const audio = {
  cache: {},
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
    const inst = el.cloneNode();
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
  for (const id of ["title-screen", "lore-screen", "play-screen",
                     "gameover-screen", "victory-screen", "replay-picker"]) {
    $(id).classList.toggle("hidden", id !== name);
  }
  $("inventory-overlay").classList.add("hidden");
  $("shop-overlay").classList.add("hidden");
  $("settings-overlay").classList.add("hidden");
  $("puzzle-overlay").classList.add("hidden");
  $("replay-controls").classList.toggle("hidden", mode !== "replay");
}

function toTitle() {
  mode = "title";
  showScreen("title-screen");
  $("btn-continue").disabled = !localStorage.getItem(LS_SAVE);
  renderTitleHighscores();
  audio.playMusic("depths");
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

function finishLore() {
  localStorage.setItem(LS_SEEN_LORE, "1");
  toTitle();
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

function gameOver() {
  mode = "gameover";
  stopRunTimer();
  const p = snap.player;
  const cause = snap.cause_of_death || "Unknown causes.";
  $("gameover-stats").textContent =
    `Cause of death: ${cause}\n\nDepth reached: ${snap.depth}\nLevel: ${p.level}\n` +
    `Gold collected: ${p.gold}\nMonsters slain: ${p.kills}\nTurns survived: ${p.turns}\n` +
    `Time: ${fmtTime(finalElapsed())}\nSeed: ${snap.seed}`;
  if (snap.run_mode === "speedrun") {
    const runs = recordSpeedrunRun();
    $("gameover-highscores").textContent =
      "Speedrun Leaderboard:\n" + speedrunScoreLines(runs, 5).join("\n");
  } else {
    const runs = loadScores();
    runs.push({
      date: new Date().toISOString(), depth_reached: snap.depth,
      turns_survived: p.turns, level: p.level, gold: p.gold, kills: p.kills,
      cause,
    });
    runs.sort((a, b) => (b.depth_reached - a.depth_reached) || (b.gold - a.gold));
    localStorage.setItem(LS_SCORES, JSON.stringify(runs.slice(0, 10)));
    $("gameover-highscores").textContent = "High Scores:\n" +
      runs.slice(0, 5).map((r) =>
        `  Floor ${String(r.depth_reached).padStart(3)}  Lv ${String(r.level).padEnd(3)} Gold ${r.gold}`).join("\n");
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
  $("victory-stats").textContent =
    `Floor ${snap.target_floor} reached in ${fmtTime(finalElapsed())}!\n\n` +
    `Level: ${p.level}\nGold collected: ${p.gold}\nMonsters slain: ${p.kills}\n` +
    `Turns taken: ${p.turns}\nSeed: ${snap.seed}`;
  const runs = recordSpeedrunRun();
  $("victory-scores").textContent =
    "Speedrun Leaderboard:\n" + speedrunScoreLines(runs, 5).join("\n");
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
const BASE_W = 1120;
const BASE_H = 730;

function toggleFullscreen() {
  if (document.fullscreenElement) {
    document.exitFullscreen().catch(() => {});
  } else {
    document.documentElement.requestFullscreen().catch(() => {});
  }
}

function fitScale() {
  const app = $("app");
  // Phones already scale via responsive CSS - the transform trick is for
  // desktop fullscreen only.
  if (document.fullscreenElement && !IS_SMALL) {
    const scale = Math.min(window.innerWidth / BASE_W, window.innerHeight / BASE_H);
    app.style.transform = `scale(${scale.toFixed(3)})`;
    app.style.transformOrigin = "top center";
    document.body.style.overflow = "hidden";
  } else {
    app.style.transform = "";
    document.body.style.overflow = "";
  }
}

document.addEventListener("fullscreenchange", fitScale);
window.addEventListener("resize", fitScale);

function applySnapshot(s) {
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
  for (const ev of events) {
    switch (ev.type) {
      case "hit":
        audio.play(ev.crit ? "crit" : "hit");
        floatNum(ev.x, ev.y, String(ev.dmg), ev.crit ? "#ffd24a" : "#ffffff");
        break;
      case "player_hit":
        audio.play("player_hurt");
        floatNum(snap.player.x, snap.player.y, String(ev.dmg), "#ff6b6b");
        shake();
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
      default:
        if (EVENT_SFX[ev.type]) audio.play(EVENT_SFX[ev.type]);
        if (ev.type === "poisoned") floatNum(snap.player.x, snap.player.y, "poison!", "#58c058");
        if (ev.type === "poison_tick") floatNum(snap.player.x, snap.player.y, String(ev.dmg), "#58c058");
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

/* ------------------------------------------------------------ settings */
let settingsReturnMode = "title";

function refreshSettingsLabels() {
  $("setting-music").textContent = `Music: ${gameSettings.music_on ? "On" : "Off"}`;
  $("setting-sfx").textContent = `Sound Effects: ${gameSettings.sfx_on ? "On" : "Off"}`;
  $("setting-shake").textContent = `Screen Shake: ${gameSettings.shake_on ? "On" : "Off"}`;
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
      else if (tile === "&") base = "chest";
      else if (tile === "B") base = "block";
      else if (tile === "L") base = propOn[key] ? "lever_down" : "lever_up";
      else if (tile === "_") base = propOn[key] ? "plate_on" : "plate_off";
      else if (variant === "1") base = "floor2";
      else if (variant === "2") base = "floor3";
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
  for (const m of snap.monsters) {
    if (!inView(m.x, m.y) || snap.visible[m.y][m.x] !== "1") continue;
    const col = m.x - cam.x, row = m.y - cam.y;
    blit(m.sprite, col, row);
    if (m.boss) blit("crown", col, row);
    if (m.hp < m.max_hp) {
      const w = TILE - 8;
      ctx.fillStyle = "#20141a";
      ctx.fillRect(col * TILE + 4, row * TILE + 1, w, 3);
      ctx.fillStyle = "#e04848";
      ctx.fillRect(col * TILE + 4, row * TILE + 1, Math.floor(w * m.hp / m.max_hp), 3);
    }
  }

  ctx.drawImage(heroSprite(p.hero), (p.x - cam.x) * TILE, (p.y - cam.y) * TILE, TILE, TILE);

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
  $("log").innerHTML = snap.log.map((l) => `<div>${escapeHtml(l)}</div>`).join("");
  $("log").scrollTop = $("log").scrollHeight;
}

function renderMinimap() {
  const scale = Math.max(1, Math.min(Math.floor(minimap.width / floorData.width),
                                     Math.floor(minimap.height / floorData.height)));
  const ox = Math.floor((minimap.width - floorData.width * scale) / 2);
  const oy = Math.floor((minimap.height - floorData.height * scale) / 2);
  mmCtx.fillStyle = "#111114";
  mmCtx.fillRect(0, 0, minimap.width, minimap.height);
  for (let y = 0; y < floorData.height; y++) {
    for (let x = 0; x < floorData.width; x++) {
      if (snap.explored[y][x] !== "1") continue;
      const tile = floorData.tiles[y][x];
      mmCtx.fillStyle = tile === "#" ? "#2a2a33" : tile === ">" ? "#66d9ef"
        : tile === "$" || tile === "&" ? "#f2c94c" : tile === "+" ? "#e0a83a"
        : tile === "L" || tile === "B" ? "#5a5a68" : "#4a4a58";
      mmCtx.fillRect(ox + x * scale, oy + y * scale, scale, scale);
    }
  }
  mmCtx.fillStyle = "#ffe45e";
  mmCtx.fillRect(ox + snap.player.x * scale - 1, oy + snap.player.y * scale - 1, scale + 2, scale + 2);
}

function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/* ------------------------------------------------- inventory overlay */
let invSel = 0;

function openInventory() {
  mode = "inventory";
  invSel = 0;
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
  const items = snap.inventory;
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
  const entry = snap.inventory[invSel];
  if (!entry) return;
  if (entry.category === "potion" || entry.category === "scroll") {
    afterAction(bridge.use_item(entry.id));
  } else if (["weapon", "armor", "accessory"].includes(entry.category)) {
    afterAction(bridge.equip_item(entry.id));
  }
  if (mode === "inventory") renderInventory();
}

function inventoryDrop() {
  const entry = snap.inventory[invSel];
  if (!entry) return;
  afterAction(bridge.drop_item(entry.id));
  if (mode === "inventory") renderInventory();
}

/* ------------------------------------------------------ shop overlay */
let shopTab = "buy";
let shopSel = 0;

function openShop() {
  mode = "shop";
  shopTab = "buy";
  shopSel = 0;
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
  return shopTab === "buy" ? snap.shop_stock : snap.inventory;
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
  if (mode === "shop" || snap.shop_open) renderShop();
}

/* ------------------------------------------------ shared list helpers */
function renderItemList(ul, items, sel, onSelect, onActivate, labelFn, colorFn) {
  ul.innerHTML = "";
  if (!items.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "(empty)";
    ul.appendChild(li);
    return;
  }
  items.forEach((entry, i) => {
    const li = document.createElement("li");
    li.textContent = labelFn ? labelFn(entry) : entry.label;
    li.style.color = colorFn ? colorFn(entry) : entry.color;
    if (i === sel) li.classList.add("selected");
    li.addEventListener("click", () => onSelect(i));
    li.addEventListener("dblclick", () => { onSelect(i); onActivate(); });
    ul.appendChild(li);
  });
  const selected = ul.children[sel];
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
  switch (mode) {
    case "title":
      if (e.key === "n" || e.key === "N" || e.key === "Enter") startNewGame();
      else if (e.key === "r" || e.key === "R") startSpeedrun();
      else if ((e.key === "c" || e.key === "C") && !$("btn-continue").disabled) continueGame();
      else if (e.key === "v" || e.key === "V") openReplayPicker();
      else if (e.key === "l" || e.key === "L") showLore(false);
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
      else if (e.key === "." || e.key === "z" || e.key === "Z") afterAction(bridge.wait_turn());
      else if (MOVE_KEYS[e.key]) {
        const [dx, dy] = MOVE_KEYS[e.key];
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

/* ------------------------------------------------------ touch controls */
const TOUCH_DIRS = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] };
let holdTimer = null;

function touchAct(dir) {
  if (!bridge || mode !== "play") return;
  if (dir === "wait") afterAction(bridge.wait_turn());
  else afterAction(bridge.move(...TOUCH_DIRS[dir]));
}

for (const btn of document.querySelectorAll(".dpad-btn")) {
  const dir = btn.dataset.dir;
  const start = (e) => {
    e.preventDefault();
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
$("touch-mute").addEventListener("click", () => {
  audio.setMuted(!audio.muted);
  if (mode === "play" || mode === "shop" || mode === "inventory") updateMusic();
});
$("touch-full").addEventListener("click", toggleFullscreen);

/* --------------------------------------------------------- UI buttons */
$("btn-new").addEventListener("click", startNewGame);
$("btn-continue").addEventListener("click", continueGame);
$("btn-title").addEventListener("click", toTitle);
$("btn-lore").addEventListener("click", () => showLore(false));
$("lore-next").addEventListener("click", () => loreStep(1));
$("lore-back").addEventListener("click", () => loreStep(-1));
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
