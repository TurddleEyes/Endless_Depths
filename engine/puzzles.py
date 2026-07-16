"""Puzzle generation and logic - the sealed rune doors of the depths.

On a puzzle floor the stairs tile is replaced by a sealed door; the puzzle
must be solved to dissolve it. All logic lives here, engine-side: the UIs
are dumb renderers of view() dicts and feed back nothing but button indices
(via GameState.puzzle_input, a recorded action), so desktop, web and replay
playback all behave identically.

A puzzle is a plain dict. Common fields:
    kind, difficulty, reward, solved, attempts, feedback, title, prompt
plus kind-specific state. view(puzzle) projects it into a generic UI dict;
solve_sequence()/bot_hint() are pure helpers for test bots.

Randomness rules: generate() draws only from the floor-generation RNG;
apply_input() draws only inside a recorded action. Both are therefore
bit-reproducible in replays.
"""
from __future__ import annotations

from . import constants as C
from .items import make_key

# ----------------------------------------------------------------------
# Kind registry
# ----------------------------------------------------------------------
EASY = ("riddle", "odd_rune", "counting_eyes", "pattern_next", "echo")
MEDIUM = ("number_lock", "rune_pairs", "lights_out", "lever_order",
          "plates", "hidden_key")
HARD = ("sliding_seal", "rune_code", "scales", "push_block")
IN_DUNGEON = ("lever_order", "plates", "push_block", "hidden_key")

# Hard puzzles always leave a reward chest behind; easy ones almost never.
REWARD_CHANCE = {"easy": 0.15, "medium": 0.5, "hard": 1.0}

RUNE_GLYPHS = ("Ω", "Δ", "Φ", "Ψ", "Σ", "Θ", "Ξ", "Π")
SIMON_GLYPHS = ("◆", "●", "▲", "■")
LEVER_NAMES = ("Serpent", "Moon", "Flame", "Crown", "Skull", "Star")


def eligible_kinds(depth: int) -> tuple:
    kinds = list(EASY) if depth >= C.PUZZLE_MIN_DEPTH else []
    if depth >= C.PUZZLE_MEDIUM_DEPTH:
        kinds += list(MEDIUM)
    if depth >= C.PUZZLE_HARD_DEPTH:
        kinds += list(HARD)
    return tuple(kinds)


def _difficulty(kind: str) -> str:
    if kind in EASY:
        return "easy"
    if kind in MEDIUM:
        return "medium"
    return "hard"


# ----------------------------------------------------------------------
# Question pools (riddles / hard logic)
# ----------------------------------------------------------------------
# (question, correct answer, [three wrong answers])
RIDDLES = [
    ("I have no legs, yet I run downhill;\nno throat, yet the deep drinks me.\nWhat am I?",
     "Water", ["A torch", "A serpent", "Time"]),
    ("The more of me you take,\nthe more you leave behind.\nWhat am I?",
     "Footsteps", ["Gold", "Breath", "Memories"]),
    ("I speak without a mouth and hear without ears.\nI was born in these caves, and I answer only you.\nWhat am I?",
     "An echo", ["A ghost", "A bat", "The wind"]),
    ("The one who makes me does not want me.\nThe one who buys me does not use me.\nThe one who uses me never sees me.\nWhat am I?",
     "A coffin", ["A map", "A trap", "A crown"]),
    ("I have a bed but never sleep,\na mouth but never eat.\nWhat am I?",
     "A river", ["A skeleton", "A cave", "A shadow"]),
    ("Feed me and I live.\nGive me a drink and I die.\nWhat am I?",
     "Fire", ["A mushroom", "A rat", "Moss"]),
    ("What has one eye\nbut cannot see?",
     "A needle", ["A wraith", "A keyhole", "A storm"]),
    ("What has many teeth\nbut cannot bite?",
     "A comb", ["A skull", "A trap", "A gear"]),
    ("What walks on four legs at dawn,\ntwo legs at noon,\nand three legs at dusk?",
     "A man", ["A spider", "A troll", "A lich"]),
    ("What gets wetter\nthe more it dries?",
     "A towel", ["A well", "A cloak", "A candle"]),
]

SCALES_QUESTIONS = [
    ("Two doors: one leads deeper, one to death.\nTwo guards: one always lies, one always tells the truth.\nOne question. What do you ask?",
     "Ask either guard which door the OTHER\nwould point to - then take the opposite",
     ["Ask the taller guard which door is safe",
      "Ask both guards the same question",
      "Ask either guard if they are the liar"]),
    ("Nine identical orbs; one is slightly heavier.\nYou have a balance scale.\nHow few weighings GUARANTEE finding it?",
     "2", ["3", "4", "1"]),
    ("Four adventurers cross a bridge at night: they take\n1, 2, 5 and 10 minutes. The bridge holds two, and they\nshare one torch. What is the fastest total crossing?",
     "17 minutes", ["19 minutes", "16 minutes", "18 minutes"]),
    ("In the race out of the depths\nyou overtake the runner in second place.\nWhat place are you in now?",
     "Second", ["First", "Third", "Last"]),
    ("A treasure chest weighs 10 pounds\nplus half its own weight.\nHow much does it weigh?",
     "20 pounds", ["15 pounds", "12 pounds", "30 pounds"]),
    ("Two fuses each burn for exactly one hour, but unevenly.\nHow do you measure 45 minutes?",
     "Light one fuse at both ends and the other at one end;\nwhen the first dies, light the second's far end",
     ["Fold one fuse in quarters and burn three parts",
      "Light both fuses at one end and wait",
      "Cut one fuse at its midpoint and burn half"]),
    ("Two coins total 15 copper.\nOne of them is not a ten-piece.\nWhat are they?",
     "A ten-piece and a five-piece", ["Two seven-pieces and change",
                                      "Three five-pieces", "It is impossible"]),
]


# ----------------------------------------------------------------------
# Generation
# ----------------------------------------------------------------------
def generate(kind: str, depth: int, rng) -> dict:
    difficulty = _difficulty(kind)
    p = {
        "kind": kind,
        "difficulty": difficulty,
        "reward": rng.random() < REWARD_CHANCE[difficulty],
        "solved": False,
        "attempts": 0,
        "feedback": "",
        "reveal_id": 0,
    }
    _GENERATORS[kind](p, depth, rng)
    return p


def _gen_choice_question(p, pool, rng, title):
    q, correct, wrong = pool[rng.randrange(len(pool))]
    options = [correct] + list(wrong)
    rng.shuffle(options)
    p["title"] = title
    p["prompt"] = q
    p["options"] = options
    p["answer"] = options.index(correct)


def _gen_riddle(p, depth, rng):
    _gen_choice_question(p, RIDDLES, rng, "The Riddle of the Well")


def _gen_scales(p, depth, rng):
    _gen_choice_question(p, SCALES_QUESTIONS, rng, "The Scales of the Deep")


def _gen_odd_rune(p, depth, rng):
    base, odd = rng.sample(RUNE_GLYPHS, 2)
    answer = rng.randrange(8)
    p["title"] = "The Odd Rune"
    p["prompt"] = "Eight runes guard the door.\nOne of them does not belong. Touch it."
    p["options"] = [odd if i == answer else base for i in range(8)]
    p["answer"] = answer


def _counting_roll(p, rng):
    species = [("r", "rats"), ("s", "spiders"), ("g", "goblins")]
    glyph, name = species[rng.randrange(3)]
    rows = []
    count = 0
    for _ in range(4):
        row = ""
        for _ in range(6):
            c = rng.choice(".." + "rsg")
            if c == glyph:
                count += 1
            row += c
        rows.append(row)
    options = {count}
    while len(options) < 4:
        options.add(max(0, count + rng.randint(-3, 3)))
    options = sorted(options)
    p["flash_grid"] = rows
    p["options"] = [str(o) for o in options]
    p["answer"] = options.index(count)
    p["prompt"] = (f"The torchlight flares for a heartbeat.\n"
                   f"How many {name} ({glyph}) did you see?")
    p["reveal_id"] += 1


def _gen_counting(p, depth, rng):
    p["title"] = "Counting Eyes"
    _counting_roll(p, rng)


def _gen_pattern(p, depth, rng):
    style = rng.randrange(4)
    if style == 0:  # arithmetic
        a, d = rng.randint(1, 9), rng.randint(2, 9)
        seq = [a + d * i for i in range(5)]
    elif style == 1:  # geometric
        a, r = rng.randint(1, 4), rng.choice([2, 3])
        seq = [a * r ** i for i in range(5)]
    elif style == 2:  # fibonacci-like
        a, b = rng.randint(1, 5), rng.randint(2, 6)
        seq = [a, b]
        for _ in range(3):
            seq.append(seq[-1] + seq[-2])
    else:  # growing steps: +1, +2, +3, ...
        a = rng.randint(1, 6)
        seq = [a]
        for i in range(1, 5):
            seq.append(seq[-1] + i)
    answer_val = seq[4]
    options = {answer_val}
    step = max(1, (seq[4] - seq[3]) // 2)
    while len(options) < 4:
        options.add(max(1, answer_val + rng.choice([-2, -1, 1, 2]) * step
                        + rng.randint(-1, 1)))
    options = sorted(options)
    p["title"] = "The Pattern"
    p["prompt"] = ("Carved into the door:\n  " +
                   ", ".join(str(n) for n in seq[:4]) + ", ?\nWhat comes next?")
    p["options"] = [str(o) for o in options]
    p["answer"] = options.index(answer_val)


def _echo_roll(p, rng):
    p["seq"] = [rng.randrange(4) for _ in range(4)]
    p["progress"] = 0
    p["reveal_id"] += 1


def _gen_echo(p, depth, rng):
    p["title"] = "The Echo Sequence"
    p["prompt"] = ("The door chimes four notes.\n"
                   "Repeat them in order.")
    _echo_roll(p, rng)


def _gen_number_lock(p, depth, rng):
    digits = rng.sample(range(1, 10), 3)
    p["title"] = "The Number Lock"
    p["target"] = sum(digits)
    p["solution"] = sorted(digits)
    p["selected"] = []
    p["prompt"] = (f"Three tumblers, nine numbered keys.\n"
                   f"Choose three that together make {p['target']}.")


def _gen_rune_pairs(p, depth, rng):
    symbols = rng.sample(RUNE_GLYPHS, 4) * 2
    rng.shuffle(symbols)
    p["title"] = "The Rune Pairs"
    p["prompt"] = ("Eight tiles, four sigil pairs.\n"
                   "Match them all. Three mismatches wake the dark.")
    p["cards"] = symbols
    p["matched"] = []
    p["first"] = None
    p["mistakes"] = 0


_LO_AFFECTS = [[i] + [j for j in range(9)
                      if (abs(j % 3 - i % 3) + abs(j // 3 - i // 3)) == 1]
               for i in range(9)]


def _lights_roll(p, rng):
    grid = [False] * 9
    for i in rng.sample(range(9), rng.randint(3, 6)):
        for j in _LO_AFFECTS[i]:
            grid[j] = not grid[j]
    p["grid"] = grid
    p["presses"] = 0


def _gen_lights_out(p, depth, rng):
    p["title"] = "The Nine Lanterns"
    p["prompt"] = ("Touching a lantern flips it and its neighbors.\n"
                   "Darken all nine before your torch burns low.")
    p["budget"] = 18
    _lights_roll(p, rng)


_SLIDE_GOAL = (1, 2, 3, 4, 5, 6, 7, 8, 0)


def _slide_roll(p, rng):
    board = list(_SLIDE_GOAL)
    prev = -1
    k = rng.randint(25, 45)
    for _ in range(k):
        z = board.index(0)
        zx, zy = z % 3, z // 3
        moves = [zy * 3 + zx + off for off, ok in
                 ((1, zx < 2), (-1, zx > 0), (3, zy < 2), (-3, zy > 0)) if ok]
        moves = [m for m in moves if m != prev] or moves
        j = rng.choice(moves)
        board[z], board[j] = board[j], board[z]
        prev = z
    p["board"] = board
    p["moves"] = 0
    p["budget"] = max(80, k * 3)


def _gen_sliding(p, depth, rng):
    p["title"] = "The Sliding Seal"
    p["prompt"] = ("The seal is shattered into eight numbered shards.\n"
                   "Slide them back into order, 1 through 8.")
    _slide_roll(p, rng)


def _gen_rune_code(p, depth, rng):
    p["title"] = "The Rune Code"
    p["symbols"] = list(RUNE_GLYPHS[:5])
    p["secret"] = [rng.randrange(5) for _ in range(3)]
    p["guess"] = []
    p["history"] = []
    p["submits"] = 0
    p["budget"] = 7
    p["prompt"] = ("Three runes seal the lock, in order.\n"
                   "After each guess: + = right rune, right place;\n"
                   "~ = right rune, wrong place. Seven tries.")


def _gen_lever_order(p, depth, rng):
    names = rng.sample(LEVER_NAMES, 3)
    order = list(range(3))
    rng.shuffle(order)
    p["title"] = "The Three Levers"
    p["levers"] = [{"x": 0, "y": 0, "name": n, "pulled": False} for n in names]
    p["order"] = order
    p["progress"] = 0
    a, b, c = (p["levers"][i]["name"] for i in order)
    p["prompt"] = (f"An inscription reads:\n"
                   f"\"The {a} wakes first; the {b} follows;\n"
                   f"the {c} comes last.\"\n"
                   f"Three levers stand somewhere on this floor.\n"
                   f"Pull them in that order.")


def _gen_plates(p, depth, rng):
    n = rng.randint(4, 6)
    p["title"] = "The Pressure Plates"
    p["plates"] = [{"x": 0, "y": 0, "lit": False} for _ in range(n)]
    p["prompt"] = (f"{n} stone plates lie before the door.\n"
                   f"Light every one - but step on a lit plate\n"
                   f"and the floor resets, and something wakes.")


def _gen_push_block(p, depth, rng):
    p["title"] = "The Ancient Block"
    p["block"] = None       # (x, y), set by place_props
    p["block_start"] = None
    p["switch"] = None
    p["prompt"] = ("A great stone block and a floor-switch of rune-glass.\n"
                   "Push the block onto the switch to break the seal.\n"
                   "(Blocks only move away from you - if it jams,\n"
                   "turn the winch here to reset it.)")


def _gen_hidden_key(p, depth, rng):
    p["title"] = "The Hidden Key"
    p["key_pos"] = None  # set by place_props
    p["prompt"] = ("The door bears a keyhole shaped like a rune.\n"
                   "Somewhere on this floor, its key lies waiting.")


_GENERATORS = {
    "riddle": _gen_riddle,
    "scales": _gen_scales,
    "odd_rune": _gen_odd_rune,
    "counting_eyes": _gen_counting,
    "pattern_next": _gen_pattern,
    "echo": _gen_echo,
    "number_lock": _gen_number_lock,
    "rune_pairs": _gen_rune_pairs,
    "lights_out": _gen_lights_out,
    "sliding_seal": _gen_sliding,
    "rune_code": _gen_rune_code,
    "lever_order": _gen_lever_order,
    "plates": _gen_plates,
    "push_block": _gen_push_block,
    "hidden_key": _gen_hidden_key,
}


# ----------------------------------------------------------------------
# Prop placement for in-dungeon kinds (called from generate_floor)
# ----------------------------------------------------------------------
def _interior_spot(room, tiles, occupied, rng, floor_tile, attempts=10):
    """A random strict-interior floor tile of a room. Interior tiles always
    have an open ring around them, so a solid prop there can never seal a
    corridor mouth (those live on the room's boundary ring)."""
    for _ in range(attempts):
        x = rng.randint(room.x + 1, room.x + room.w - 2)
        y = rng.randint(room.y + 1, room.y + room.h - 2)
        if tiles[y][x] == floor_tile and (x, y) not in occupied:
            return x, y
    return None


def place_props(puzzle, rooms, tiles, occupied, stairs_pos, stairs_room,
                start_room, ground_items, rng) -> bool:
    """Place an in-dungeon puzzle's physical props. Returns False if no
    valid placement exists (caller falls back to a pop-up kind)."""
    from .dungeon import GroundItem  # deferred: dungeon imports this module

    kind = puzzle["kind"]
    puzzle["door_pos"] = tuple(stairs_pos)

    if kind == "lever_order":
        candidates = [r for r in rooms if r is not start_room]
        rng.shuffle(candidates)
        placed = 0
        for room in candidates:
            if placed == 3:
                break
            spot = _interior_spot(room, tiles, occupied, rng, C.TILE_FLOOR)
            if spot is None:
                continue
            occupied.add(spot)
            tiles[spot[1]][spot[0]] = C.TILE_LEVER
            puzzle["levers"][placed]["x"], puzzle["levers"][placed]["y"] = spot
            placed += 1
        return placed == 3

    if kind == "plates":
        n = len(puzzle["plates"])
        sx, sy = stairs_pos
        # A straight horizontal or vertical run of interior tiles in the
        # stairs room, skipping the stairs tile's own row/column so the run
        # never overlaps the door.
        runs = []
        for y in range(stairs_room.y + 1, stairs_room.y + stairs_room.h - 1):
            if y == sy:
                continue
            xs = range(stairs_room.x + 1, stairs_room.x + stairs_room.w - 1)
            cells = [(x, y) for x in xs]
            runs.append(cells)
        for x in range(stairs_room.x + 1, stairs_room.x + stairs_room.w - 1):
            if x == sx:
                continue
            ys = range(stairs_room.y + 1, stairs_room.y + stairs_room.h - 1)
            runs.append([(x, y) for y in ys])
        rng.shuffle(runs)
        for cells in runs:
            free = [c for c in cells
                    if tiles[c[1]][c[0]] == C.TILE_FLOOR and c not in occupied]
            # need n CONSECUTIVE free cells
            for start in range(len(cells) - n + 1):
                window = cells[start:start + n]
                if all(c in free for c in window):
                    for plate, (x, y) in zip(puzzle["plates"], window):
                        plate["x"], plate["y"] = x, y
                        occupied.add((x, y))
                        tiles[y][x] = C.TILE_PLATE
                    return True
        # fall back to a shorter run of 4
        if n > 4:
            puzzle["plates"] = puzzle["plates"][:4]
            return place_props(puzzle, rooms, tiles, occupied, stairs_pos,
                               stairs_room, start_room, ground_items, rng)
        return False

    if kind == "push_block":
        sx, sy = stairs_pos
        # Four consecutive interior floor cells in a straight line inside the
        # stairs room, not through the door tile: [approach, block, path,
        # switch]. Pushing from the approach side walks the block onto the
        # switch in two shoves.
        lines = []
        for y in range(stairs_room.y + 1, stairs_room.y + stairs_room.h - 1):
            if y == sy:
                continue
            cells = [(x, y) for x in
                     range(stairs_room.x + 1, stairs_room.x + stairs_room.w - 1)]
            lines.append(cells)
        for x in range(stairs_room.x + 1, stairs_room.x + stairs_room.w - 1):
            if x == sx:
                continue
            cells = [(x, y) for y in
                     range(stairs_room.y + 1, stairs_room.y + stairs_room.h - 1)]
            lines.append(cells)
        rng.shuffle(lines)
        for cells in lines:
            for start in range(len(cells) - 3):
                window = cells[start:start + 4]
                if all(tiles[c[1]][c[0]] == C.TILE_FLOOR and c not in occupied
                       for c in window):
                    _approach, block, _path, switch = window
                    puzzle["block"] = list(block)
                    puzzle["block_start"] = list(block)
                    puzzle["switch"] = list(switch)
                    occupied.add(block)
                    occupied.add(switch)
                    tiles[block[1]][block[0]] = C.TILE_BLOCK
                    return True
        return False

    if kind == "hidden_key":
        # Hide the Rune Key in the room farthest from the stairs.
        candidates = sorted(
            (r for r in rooms if r is not stairs_room),
            key=lambda r: -(abs(r.center[0] - stairs_pos[0])
                            + abs(r.center[1] - stairs_pos[1])))
        for room in candidates:
            spot = _interior_spot(room, tiles, occupied, rng, C.TILE_FLOOR)
            if spot is None:
                continue
            occupied.add(spot)
            ground_items.append(GroundItem(spot[0], spot[1],
                                           make_key("Rune Key")))
            puzzle["key_pos"] = list(spot)
            return True
        return False

    return False


# ----------------------------------------------------------------------
# Input handling: returns "solved" | "failed" | "continue" | "reset_block"
# ----------------------------------------------------------------------
def apply_input(puzzle, index, rng) -> str:
    if puzzle["solved"]:
        return "continue"
    handler = _HANDLERS.get(puzzle["kind"])
    if handler is None:
        return "continue"
    result = handler(puzzle, int(index), rng)
    if result == "solved":
        puzzle["solved"] = True
        puzzle["feedback"] = "The runes flare white - the seal breaks!"
    elif result == "failed":
        puzzle["attempts"] += 1
    return result


def _in_choices(puzzle, index) -> bool:
    return 0 <= index < len(puzzle["options"])


def _h_choice(puzzle, index, rng):
    """Riddle / scales / odd rune / pattern: one right answer, board kept."""
    if not _in_choices(puzzle, index):
        return "continue"
    if index == puzzle["answer"]:
        return "solved"
    puzzle["feedback"] = "The door hums in cold disapproval."
    return "failed"


def _h_counting(puzzle, index, rng):
    if not _in_choices(puzzle, index):
        return "continue"
    if index == puzzle["answer"]:
        return "solved"
    _counting_roll(puzzle, rng)  # new grid, new flash
    puzzle["feedback"] = "Wrong. The torchlight flares again..."
    return "failed"


def _h_echo(puzzle, index, rng):
    if not 0 <= index < 4:
        return "continue"
    if index == puzzle["seq"][puzzle["progress"]]:
        puzzle["progress"] += 1
        if puzzle["progress"] == len(puzzle["seq"]):
            return "solved"
        puzzle["feedback"] = f"...{puzzle['progress']} of {len(puzzle['seq'])}..."
        return "continue"
    _echo_roll(puzzle, rng)  # brand-new melody
    puzzle["feedback"] = "A sour note. The door sings a new tune..."
    return "failed"


def _h_number_lock(puzzle, index, rng):
    if not 0 <= index < 9:
        return "continue"
    puzzle["selected"].append(index + 1)
    if len(puzzle["selected"]) < 3:
        puzzle["feedback"] = "Chosen: " + " + ".join(map(str, puzzle["selected"]))
        return "continue"
    total = sum(puzzle["selected"])
    picked = puzzle["selected"]
    puzzle["selected"] = []
    if total == puzzle["target"]:
        return "solved"
    puzzle["feedback"] = (f"{' + '.join(map(str, picked))} = {total}. "
                          f"The tumblers reset.")
    return "failed"


def _h_rune_pairs(puzzle, index, rng):
    cards, matched = puzzle["cards"], puzzle["matched"]
    if not 0 <= index < len(cards) or index in matched:
        return "continue"
    first = puzzle["first"]
    if first is None or first == index:
        puzzle["first"] = index
        puzzle["feedback"] = "The tile glows..."
        return "continue"
    puzzle["first"] = None
    if cards[first] == cards[index]:
        matched.extend([first, index])
        if len(matched) == len(cards):
            return "solved"
        puzzle["feedback"] = "A pair! The sigils sink into the stone."
        return "continue"
    puzzle["mistakes"] += 1
    puzzle["reveal"] = [first, index]
    puzzle["reveal_id"] += 1
    if puzzle["mistakes"] % 3 == 0:
        puzzle["feedback"] = "The third mismatch rings out like a bell..."
        return "failed"
    puzzle["feedback"] = "No match. The tiles turn back over."
    return "continue"


def _h_lights_out(puzzle, index, rng):
    if not 0 <= index < 9:
        return "continue"
    for j in _LO_AFFECTS[index]:
        puzzle["grid"][j] = not puzzle["grid"][j]
    puzzle["presses"] += 1
    if not any(puzzle["grid"]):
        return "solved"
    if puzzle["presses"] > puzzle["budget"]:
        _lights_roll(puzzle, rng)
        puzzle["feedback"] = "Your torch gutters - the lanterns rekindle themselves."
        return "failed"
    puzzle["feedback"] = f"{puzzle['budget'] - puzzle['presses']} touches left."
    return "continue"


def _h_sliding(puzzle, index, rng):
    board = puzzle["board"]
    if not 0 <= index < 9:
        return "continue"
    z = board.index(0)
    if not (abs(index % 3 - z % 3) + abs(index // 3 - z // 3)) == 1:
        puzzle["feedback"] = "That shard cannot move."
        return "continue"
    board[z], board[index] = board[index], board[z]
    puzzle["moves"] += 1
    if list(_SLIDE_GOAL) == board:
        return "solved"
    if puzzle["moves"] > puzzle["budget"]:
        _slide_roll(puzzle, rng)
        puzzle["feedback"] = "The seal shudders and re-shatters itself..."
        return "failed"
    return "continue"


def _h_rune_code(puzzle, index, rng):
    n_sym = len(puzzle["symbols"])
    if index < n_sym:
        if len(puzzle["guess"]) < 3:
            puzzle["guess"].append(index)
            puzzle["feedback"] = "Guess: " + "".join(
                puzzle["symbols"][i] for i in puzzle["guess"])
        return "continue"
    if index == n_sym:  # clear
        puzzle["guess"] = []
        puzzle["feedback"] = "You wipe the slate."
        return "continue"
    if index == n_sym + 1 and len(puzzle["guess"]) == 3:  # submit
        guess, secret = puzzle["guess"], puzzle["secret"]
        puzzle["guess"] = []
        exact = sum(1 for a, b in zip(secret, guess) if a == b)
        if exact == 3:
            return "solved"
        common = sum(min(secret.count(s), guess.count(s)) for s in set(guess))
        puzzle["history"].append(["".join(puzzle["symbols"][i] for i in guess),
                                  exact, common - exact])
        puzzle["submits"] += 1
        if puzzle["submits"] >= puzzle["budget"]:
            puzzle["secret"] = [rng.randrange(n_sym) for _ in range(3)]
            puzzle["history"] = []
            puzzle["submits"] = 0
            puzzle["feedback"] = "The lock clicks ominously and re-runes itself."
            return "failed"
        puzzle["feedback"] = f"{puzzle['budget'] - puzzle['submits']} tries left."
        return "continue"
    return "continue"


def _h_push_block(puzzle, index, rng):
    if index == 0:
        return "reset_block"  # the winch; GameState moves the block home
    return "continue"


def _h_inert(puzzle, index, rng):
    return "continue"  # in-dungeon kinds ignore popup input


_HANDLERS = {
    "riddle": _h_choice,
    "scales": _h_choice,
    "odd_rune": _h_choice,
    "pattern_next": _h_choice,
    "counting_eyes": _h_counting,
    "echo": _h_echo,
    "number_lock": _h_number_lock,
    "rune_pairs": _h_rune_pairs,
    "lights_out": _h_lights_out,
    "sliding_seal": _h_sliding,
    "rune_code": _h_rune_code,
    "push_block": _h_push_block,
    "lever_order": _h_inert,
    "plates": _h_inert,
    "hidden_key": _h_inert,
}


# ----------------------------------------------------------------------
# In-dungeon interactions (called from GameState)
# ----------------------------------------------------------------------
def on_lever(puzzle, x, y) -> str:
    if puzzle["kind"] != "lever_order" or puzzle["solved"]:
        return "continue"
    idx = next((i for i, lv in enumerate(puzzle["levers"])
                if (lv["x"], lv["y"]) == (x, y)), None)
    if idx is None:
        return "continue"
    lever = puzzle["levers"][idx]
    if lever["pulled"]:
        puzzle["feedback"] = f"The {lever['name']} lever is already thrown."
        return "continue"
    expected = puzzle["order"][puzzle["progress"]]
    if idx == expected:
        lever["pulled"] = True
        puzzle["progress"] += 1
        if puzzle["progress"] == len(puzzle["order"]):
            return "solved"
        puzzle["feedback"] = f"The {lever['name']} lever locks into place."
        return "continue"
    for lv in puzzle["levers"]:
        lv["pulled"] = False
    puzzle["progress"] = 0
    puzzle["attempts"] += 1
    puzzle["feedback"] = "Every lever springs back with a CLANG!"
    return "failed"


def on_plate(puzzle, x, y) -> str:
    if puzzle["kind"] != "plates" or puzzle["solved"]:
        return "continue"
    plate = next((pl for pl in puzzle["plates"]
                  if (pl["x"], pl["y"]) == (x, y)), None)
    if plate is None:
        return "continue"
    if plate["lit"]:
        for pl in puzzle["plates"]:
            pl["lit"] = False
        puzzle["attempts"] += 1
        puzzle["feedback"] = "The plates go dark with a hollow boom!"
        return "failed"
    plate["lit"] = True
    if all(pl["lit"] for pl in puzzle["plates"]):
        return "solved"
    return "continue"


def on_block_moved(puzzle, x, y) -> str:
    if puzzle["kind"] != "push_block" or puzzle["solved"]:
        return "continue"
    puzzle["block"] = [x, y]
    if [x, y] == list(puzzle["switch"]):
        return "solved"
    return "continue"


# ----------------------------------------------------------------------
# View: the generic dict both UIs render
# ----------------------------------------------------------------------
def view(puzzle) -> dict:
    kind = puzzle["kind"]
    v = {
        "kind": kind,
        "title": puzzle["title"],
        "prompt": puzzle["prompt"],
        "feedback": puzzle.get("feedback", ""),
        "attempts": puzzle["attempts"],
        "solved": puzzle["solved"],
        "buttons": [],
        "grid_cols": 1,
        "reveal": None,
        "reveal_id": puzzle.get("reveal_id", 0),
        "flash_grid": None,
        "history": None,
    }
    if kind in ("riddle", "scales"):
        v["buttons"] = [{"label": o, "state": "normal"} for o in puzzle["options"]]
    elif kind in ("odd_rune",):
        v["buttons"] = [{"label": o, "state": "normal"} for o in puzzle["options"]]
        v["grid_cols"] = 4
    elif kind in ("pattern_next",):
        v["buttons"] = [{"label": o, "state": "normal"} for o in puzzle["options"]]
        v["grid_cols"] = 2
    elif kind == "counting_eyes":
        v["buttons"] = [{"label": o, "state": "normal"} for o in puzzle["options"]]
        v["grid_cols"] = 2
        v["flash_grid"] = list(puzzle["flash_grid"])
    elif kind == "echo":
        v["buttons"] = [{"label": g, "state": "normal"} for g in SIMON_GLYPHS]
        v["grid_cols"] = 4
        v["reveal"] = list(puzzle["seq"])
    elif kind == "number_lock":
        v["buttons"] = [{"label": str(d), "state":
                         "lit" if d in puzzle["selected"] else "normal"}
                        for d in range(1, 10)]
        v["grid_cols"] = 3
    elif kind == "rune_pairs":
        v["buttons"] = []
        for i, sym in enumerate(puzzle["cards"]):
            if i in puzzle["matched"]:
                v["buttons"].append({"label": sym, "state": "disabled"})
            elif i == puzzle["first"]:
                v["buttons"].append({"label": sym, "state": "lit"})
            else:
                v["buttons"].append({"label": "?", "state": "normal"})
        v["grid_cols"] = 4
        if puzzle.get("reveal"):
            v["reveal"] = list(puzzle["reveal"])
            v["reveal_cards"] = [puzzle["cards"][i] for i in puzzle["reveal"]]
    elif kind == "lights_out":
        v["buttons"] = [{"label": "◉" if lit else "○",
                         "state": "lit" if lit else "normal"}
                        for lit in puzzle["grid"]]
        v["grid_cols"] = 3
    elif kind == "sliding_seal":
        v["buttons"] = [{"label": str(n) if n else " ",
                         "state": "disabled" if n == 0 else "normal"}
                        for n in puzzle["board"]]
        v["grid_cols"] = 3
    elif kind == "rune_code":
        v["buttons"] = ([{"label": s, "state": "normal"} for s in puzzle["symbols"]]
                        + [{"label": "Clear", "state": "normal"},
                           {"label": "Open", "state": "normal"}])
        v["grid_cols"] = 5
        v["history"] = [f"{g}   +{e}  ~{m}" for g, e, m in puzzle["history"]]
        current = "".join(puzzle["symbols"][i] for i in puzzle["guess"])
        v["prompt"] = puzzle["prompt"] + f"\n\nGuess so far: {current or '---'}"
    elif kind == "push_block":
        v["buttons"] = [{"label": "Turn the winch (reset the block)",
                         "state": "normal"}]
    # lever_order / plates / hidden_key: prompt only, no buttons
    return v


# ----------------------------------------------------------------------
# Bot / test helpers (pure; no GameState access)
# ----------------------------------------------------------------------
def solve_sequence(puzzle) -> list:
    """Button presses that solve a POP-UP puzzle from its current state.
    Recompute after every apply_input - stateful kinds shift underfoot."""
    kind = puzzle["kind"]
    if puzzle["solved"]:
        return []
    if kind in ("riddle", "scales", "odd_rune", "pattern_next", "counting_eyes"):
        return [puzzle["answer"]]
    if kind == "echo":
        return list(puzzle["seq"][puzzle["progress"]:])
    if kind == "number_lock":
        need = 3 - len(puzzle["selected"])
        have = sum(puzzle["selected"])
        remaining = puzzle["target"] - have
        # complete the current selection if possible (digits may repeat)
        combo = _sum_combo(remaining, need)
        if combo is None:
            # doomed selection: burn it (one fail), then enter the solution
            return ([1] * need) + [d - 1 for d in puzzle["solution"]]
        return [d - 1 for d in combo]
    if kind == "rune_pairs":
        seq = []
        first = puzzle["first"]
        cards, matched = puzzle["cards"], set(puzzle["matched"])
        if first is not None:
            partner = next(i for i in range(len(cards))
                           if i != first and i not in matched
                           and cards[i] == cards[first])
            seq.append(partner)
            matched |= {first, partner}
        seen = {}
        for i, sym in enumerate(cards):
            if i in matched:
                continue
            if sym in seen:
                seq += [seen[sym], i]
                del seen[sym]
            else:
                seen[sym] = i
        return seq
    if kind == "lights_out":
        return _lights_solve(puzzle["grid"])
    if kind == "sliding_seal":
        return _slide_solve(puzzle["board"])
    if kind == "rune_code":
        guess, secret = puzzle["guess"], puzzle["secret"]
        submit = len(puzzle["symbols"]) + 1
        if guess == secret[:len(guess)]:  # correct prefix: keep going
            return list(secret[len(guess):]) + [submit]
        return [len(puzzle["symbols"])] + list(secret) + [submit]  # clear first
    return []


def _sum_combo(target, count):
    """`count` digits 1-9 (repeats fine) summing to target, or None."""
    if count == 0:
        return [] if target == 0 else None
    for d in range(1, 10):
        rest = _sum_combo(target - d, count - 1)
        if rest is not None:
            return [d] + rest
    return None


def _lights_solve(grid) -> list:
    for mask in range(512):
        g = list(grid)
        for i in range(9):
            if mask >> i & 1:
                for j in _LO_AFFECTS[i]:
                    g[j] = not g[j]
        if not any(g):
            return [i for i in range(9) if mask >> i & 1]
    return []


def _slide_solve(board) -> list:
    """A* with Manhattan distance; returns pressed-cell indices."""
    import heapq
    start = tuple(board)
    if start == _SLIDE_GOAL:
        return []

    def h(b):
        d = 0
        for i, val in enumerate(b):
            if val:
                gi = val - 1
                d += abs(i // 3 - gi // 3) + abs(i % 3 - gi % 3)
        return d

    heap = [(h(start), 0, start, [])]
    best = {start: 0}
    while heap:
        _f, g, b, path = heapq.heappop(heap)
        if b == _SLIDE_GOAL:
            return path
        if best.get(b, 1 << 30) < g:
            continue
        z = b.index(0)
        zx, zy = z % 3, z // 3
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = zx + dx, zy + dy
            if 0 <= nx < 3 and 0 <= ny < 3:
                j = ny * 3 + nx
                nb = list(b)
                nb[z], nb[j] = nb[j], nb[z]
                nb = tuple(nb)
                ng = g + 1
                if ng < best.get(nb, 1 << 30):
                    best[nb] = ng
                    heapq.heappush(heap, (ng + h(nb), ng, nb, path + [j]))
    return []


def bot_hint(puzzle, player_pos, inventory_names) -> tuple:
    """Next physical objective for an IN-DUNGEON puzzle:
    ("bump", (x, y)) - walk adjacent and step into it
    ("goto", (x, y)) - walk onto that tile
    ("done",)        - nothing left to do"""
    kind = puzzle["kind"]
    if puzzle["solved"]:
        return ("done",)
    if kind == "lever_order":
        lv = puzzle["levers"][puzzle["order"][puzzle["progress"]]]
        return ("bump", (lv["x"], lv["y"]))
    if kind == "plates":
        for pl in puzzle["plates"]:
            if not pl["lit"]:
                return ("goto", (pl["x"], pl["y"]))
        return ("done",)
    if kind == "hidden_key":
        if "Rune Key" in inventory_names:
            return ("bump", tuple(puzzle["door_pos"]))
        return ("goto", tuple(puzzle["key_pos"])) if puzzle["key_pos"] else ("done",)
    if kind == "push_block":
        bx, by = puzzle["block"]
        sx, sy = puzzle["switch"]
        if (bx, by) == (sx, sy):
            return ("done",)
        dx = (sx > bx) - (sx < bx)
        dy = (sy > by) - (sy < by)
        behind = (bx - dx, by - dy)
        if tuple(player_pos) == behind:
            return ("bump", (bx, by))
        return ("goto", behind)
    return ("done",)
