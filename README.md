# Endless Depths

My infinite dungeon roguelike — procedural pixel-art graphics, chiptune
music, and sound effects all generated from code, written in pure Python
with zero external dependencies. Everything here is hand-rolled: the
engine, the pixel art, the music synthesizer, the works.

Playable two ways:

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

```

### Controls

| Key | Action |
| --- | --- |
| Arrows / WASD | Move / attack (bump into monsters) |
| Mouse click | Auto-walk to the clicked tile (browser version) |
| E | Inventory |
| . or Z | Wait a turn |
| M | Toggle sound |
| Enter / double-click | Use, equip, buy or sell the selected item |
| Tab | Switch between Buy and Sell in shops |
| D | Drop the selected inventory item |
| Esc | Close menu |

Walk into the stairs `>` to descend. Walk into the shopkeeper to trade.

**On phones/tablets** the map itself is the controller: tap any explored
tile and the hero walks there (auto-walk stops the moment a monster
appears or you take a hit), tap an adjacent monster/chest/door to bump
it, tap the hero to wait. Swipe to step once; hold and drag to keep
walking. Bag and settings buttons float in the corner, and a classic
on-screen D-pad can be re-enabled in Settings. Tap an item to view its
stats, double-tap (or use the action button) to use, equip, buy or sell
it.

### Architecture

```
engine/     headless game logic - no UI imports, fully testable
ui/         desktop tkinter front-end (spritedata.py + iteminfo.py + audio.py
            are UI-toolkit-free and shared with the web build)
web/        browser front-end: webbridge.py (JSON API run in Pyodide),
            main.js (canvas renderer), style.css
index.html  entry point for the browser version
game.py     entry point for the desktop version
