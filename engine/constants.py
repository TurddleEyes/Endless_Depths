"""Shared constants and tuning knobs for the roguelike engine."""

# --- Map geometry -----------------------------------------------------
# Fixed physical map size for every floor. Infinite depth is expressed
# through scaling stats/loot/monster-count rather than an ever-growing
# grid, which keeps rendering and generation simple at any depth.
MAP_WIDTH = 60
MAP_HEIGHT = 32

MIN_ROOMS = 8
MAX_ROOMS = 14
MIN_ROOM_SIZE = 4
MAX_ROOM_SIZE = 10

FOV_RADIUS = 7

# Every SHOP_INTERVAL floors (starting at the first one) a shop room is
# guaranteed to spawn somewhere on the floor.
SHOP_INTERVAL = 3

# Every BOSS_INTERVAL floors spawns one tough boss-tier monster.
BOSS_INTERVAL = 10

# --- Tile types ---------------------------------------------------------
TILE_WALL = "#"
TILE_FLOOR = "."
TILE_STAIRS = ">"
TILE_SHOPKEEPER = "$"
TILE_DOOR = "+"    # sealed rune door; sits on the stairs tile of puzzle floors
TILE_BOSS_DOOR = "=" # sealed arena door; sits on the stairs tile of boss floors
TILE_CHEST = "&"   # closed chest (every kind looks identical - mimics included)
TILE_LEVER = "L"   # bump-interactable puzzle lever
TILE_PLATE = "_"   # walkable pressure plate (lit state lives in the puzzle)
TILE_BLOCK = "B"   # pushable block

# Tiles that block movement and pathing. Interactables (door, chest, lever,
# block) are solid so the player triggers them by bumping, exactly like the
# shopkeeper - and monsters route around them.
SOLID_TILES = (TILE_WALL, TILE_SHOPKEEPER, TILE_DOOR, TILE_BOSS_DOOR, TILE_CHEST,
               TILE_LEVER, TILE_BLOCK)

# --- Puzzles ---------------------------------------------------------------
# A puzzle seals the stairs behind a rune door on ~PUZZLE_CHANCE of floors.
# Never on floor 1 (let people learn to walk first) or boss floors (the boss
# IS that floor's gate). Difficulty pools unlock as the depths grow.
PUZZLE_CHANCE = 0.40
PUZZLE_MIN_DEPTH = 2
PUZZLE_MEDIUM_DEPTH = 8
PUZZLE_HARD_DEPTH = 16

# --- Chests ----------------------------------------------------------------
CHEST_CHANCE = 0.40         # chance a floor spawns a chest at all
CHEST_SECOND_CHANCE = 0.20  # chance of a second chest, depth >= 10

# --- Rarity tiers ---------------------------------------------------------
RARITIES = [
    # name,        multiplier, weight, color
    ("common", 1.0, 100, "#c9c9c9"),
    ("uncommon", 1.5, 45, "#3ecf4a"),
    ("rare", 2.2, 18, "#3ea1cf"),
    ("epic", 3.2, 6, "#b25ce0"),
    ("legendary", 4.5, 1, "#e0a83a"),
]

# --- Colors (tkinter hex) ---------------------------------------------
COLOR_WALL = "#2b2b33"
COLOR_WALL_DIM = "#17171b"
COLOR_FLOOR = "#4a4a55"
COLOR_FLOOR_DIM = "#232328"
COLOR_UNKNOWN = "#000000"
COLOR_PLAYER = "#ffe45e"
COLOR_STAIRS = "#66d9ef"
COLOR_SHOPKEEPER = "#f2c94c"
COLOR_GOLD = "#f2c94c"
COLOR_LOG_TEXT = "#d8d8d8"

CATEGORY_COLORS = {
    "weapon": "#e05656",
    "armor": "#5691e0",
    "accessory": "#c956e0",
    "potion": "#56e0a0",
    "scroll": "#e0d356",
    "gold": "#f2c94c",
    "food": "#d9924a",
}

MONSTER_COLOR = "#ff6b6b"
BOSS_COLOR = "#ff2e2e"

# --- Gold/economy scaling ------------------------------------------------
# Combat stats (hp/attack/defense/xp) scale linearly forever - that's what
# keeps an infinite dungeon meaningfully harder floor after floor. Currency
# is different: unbounded gold growth just produces silly numbers late-game
# without adding anything to the challenge, so it uses a soft cap that
# approaches (1 + GOLD_SCALE_MAX)x baseline instead of growing forever.
GOLD_SCALE_MAX = 4.0
GOLD_SCALE_HALF_DEPTH = 8


def gold_scale(depth: int) -> float:
    d = max(1, depth)
    return 1 + GOLD_SCALE_MAX * (1 - 1 / (1 + (d - 1) / GOLD_SCALE_HALF_DEPTH))


# Player base stats
PLAYER_BASE_HP = 20
PLAYER_BASE_ATTACK = 4
PLAYER_BASE_DEFENSE = 1
PLAYER_XP_BASE = 20
PLAYER_XP_GROWTH = 1.35

MAX_LOG_LINES = 200
SAVE_FILE = "save.json"
HIGHSCORE_FILE = "highscores.json"
MAX_HIGHSCORES = 10

# --- Speedrun mode ---------------------------------------------------------
SPEEDRUN_TARGET_FLOOR = 100
SPEEDRUN_SCORE_FILE = "speedrun_scores.json"
MAX_SPEEDRUN_SCORES = 10
