# Endless Depths

An infinite dungeon roguelike with procedural pixel-art graphics, chiptune
music, and synthesized sound effects — written in pure Python with zero
external dependencies. Playable two ways:

- **In the browser** (GitHub Pages + [Pyodide](https://pyodide.org)) — the
  same Python engine runs as WebAssembly
- **On the desktop** (Python + tkinter)

## Features

- Infinite procedurally generated floors — difficulty, loot and monsters
  scale forever
- 12 monster types plus crowned boss monsters every 10 floors (with their
  own battle music)
- Weapons, armor, accessories, potions and scrolls across 5 rarity tiers
- Your hero's sprite changes with what you equip: weapon type in hand,
  blade color by rarity, tunic by armor class, amulet, green skin when
  poisoned
- Shops every 3 floors with a buy/sell interface and full item stat
  comparisons
- Traps (spikes, poison gas, teleport runes), poison status effects,
  fireball scrolls
- Fog of war, minimap, floating damage numbers, screen shake, level-up
  sparkles
- All music and sound effects are synthesized from code at first launch —
  no asset files
- Single-slot autosave (permadeath deletes it) and a local high-score table
- A lore intro, seed sharing (type a friend's seed to play their exact
  dungeon), and a **speedrun mode**: race to floor 100 against a live
  stopwatch with its own leaderboard
- **Full replay recording**: every run can be saved as a small file or
  copied as a text code, shared anywhere, and watched back like a movie
  (pause, 2x speed, skip to end) - replays are bit-exact because all game
  randomness flows from one seed

## Play in the browser

Once this repo is on GitHub with Pages enabled (see below), the game runs at:

```
https://<your-username>.github.io/<repo-name>/
```

To try it locally without GitHub:

```
python3 -m http.server 8000
# then open http://localhost:8000
```

(A server is required — opening index.html directly with file:// won't work
because the page fetches the Python engine files.)

## Play on the desktop

Requires Python 3.10+ with tkinter (Debian/Ubuntu/Zorin: `sudo apt install python3-tk`).

```
python3 game.py
```

### Controls

| Key | Action |
| --- | --- |
| Arrows / WASD | Move / attack (bump into monsters) |
| E | Inventory |
| . or Z | Wait a turn |
| M | Toggle sound |
| Enter / double-click | Use, equip, buy or sell the selected item |
| Tab | Switch between Buy and Sell in shops |
| D | Drop the selected inventory item |
| Esc | Close menu |

Walk into the stairs `>` to descend. Walk into the shopkeeper to trade.

**On phones/tablets** the browser version shows an on-screen D-pad
(hold a direction to keep walking, center dot waits a turn) plus Bag /
Sound / Fullscreen buttons, and the layout reflows to fit the screen.
Tap an item to view its stats, double-tap (or use the action button) to
use, equip, buy or sell it.

## Publishing to GitHub Pages

1. Create a new repository on <https://github.com/new> (e.g. `endless-depths`).
   Don't initialize it with a README.
2. Push this folder:

   ```
   git remote add origin https://github.com/<your-username>/<repo-name>.git
   git push -u origin main
   ```

3. On GitHub: **Settings → Pages → Build and deployment** — set *Source* to
   **Deploy from a branch**, choose branch **main** and folder **/ (root)**,
   then save.
4. After a minute, the game is live at
   `https://<your-username>.github.io/<repo-name>/`.

## Development

```
python3 scripts/smoke_test.py       # headless engine tests (no tkinter needed)
python3 scripts/web_smoke_test.py   # tests the browser JSON bridge
```

### Architecture

```
engine/     headless game logic - no UI imports, fully testable
ui/         desktop tkinter front-end (spritedata.py + iteminfo.py + audio.py
            are UI-toolkit-free and shared with the web build)
web/        browser front-end: webbridge.py (JSON API run in Pyodide),
            main.js (canvas renderer), style.css
index.html  entry point for the browser version
game.py     entry point for the desktop version
scripts/    test suites
```

The engine communicates with both front-ends the same way: they call its
public methods and drain a structured event stream (`take_events()`) to
drive sounds and animations. Saves live in `save.json` on desktop and in
`localStorage` in the browser.
