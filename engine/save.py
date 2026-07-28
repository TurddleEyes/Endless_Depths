"""JSON persistence: single-slot autosave and a high-score history file."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

from . import constants as C


def daily_seed(now=None) -> tuple:
    """(date_str, seed) for today's daily challenge. UTC date so every player
    shares the same dungeon on the same calendar day. Uses a portable
    sha256 of the date (NOT Python's salted hash(), which varies run to
    run) so every player deriving this independently gets the exact same
    seed. Seed is a positive int in the same range GameState mints."""
    dt = now or datetime.now(timezone.utc)
    date_str = dt.strftime("%Y-%m-%d")
    digest = hashlib.sha256(date_str.encode("utf-8")).hexdigest()
    return date_str, (int(digest[:8], 16) % (2 ** 31 - 1)) or 1

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAVE_PATH = os.path.join(_BASE_DIR, C.SAVE_FILE)
HIGHSCORE_PATH = os.path.join(_BASE_DIR, C.HIGHSCORE_FILE)
SPEEDRUN_SCORE_PATH = os.path.join(_BASE_DIR, C.SPEEDRUN_SCORE_FILE)
SETTINGS_PATH = os.path.join(_BASE_DIR, "settings.json")
DAILY_PATH = os.path.join(_BASE_DIR, C.DAILY_FILE)
RUN_HISTORY_PATH = os.path.join(_BASE_DIR, C.RUN_HISTORY_FILE)
BESTIARY_PATH = os.path.join(_BASE_DIR, C.BESTIARY_FILE)
ACHIEVEMENTS_PATH = os.path.join(_BASE_DIR, C.ACHIEVEMENTS_FILE)
LORE_JOURNAL_PATH = os.path.join(_BASE_DIR, C.LORE_JOURNAL_FILE)


def load_settings() -> dict:
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(settings: dict) -> None:
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except OSError:
        pass


def has_save() -> bool:
    return os.path.exists(SAVE_PATH)


def save_game(state) -> None:
    try:
        with open(SAVE_PATH, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f)
    except OSError:
        pass


def load_game():
    from .world import GameState
    try:
        with open(SAVE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return GameState.from_dict(data)
    except (OSError, json.JSONDecodeError, KeyError):
        return None


def delete_save() -> None:
    try:
        os.remove(SAVE_PATH)
    except OSError:
        pass


def load_highscores() -> list:
    try:
        with open(HIGHSCORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("runs", [])
    except (OSError, json.JSONDecodeError):
        return []


def load_speedrun_scores() -> list:
    try:
        with open(SPEEDRUN_SCORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("runs", [])
    except (OSError, json.JSONDecodeError):
        return []


def speedrun_sort_key(r):
    """Finishers first (fastest time wins), then non-finishers by deepest
    floor, tie-broken by time."""
    if r.get("finished"):
        return (0, r.get("elapsed_seconds", 0))
    return (1, -r.get("depth_reached", 0), r.get("elapsed_seconds", 0))


def record_speedrun_run(state, elapsed_seconds: float) -> list:
    runs = load_speedrun_scores()
    runs.append({
        "date": datetime.now().isoformat(timespec="seconds"),
        "finished": bool(state.game_won),
        "depth_reached": state.depth,
        "elapsed_seconds": round(elapsed_seconds, 2),
        "level": state.player.level,
        "gold": state.player.gold,
        "kills": state.player.kills,
        "turns": state.player.turns,
        "seed": state.seed,
    })
    runs.sort(key=speedrun_sort_key)
    runs = runs[:C.MAX_SPEEDRUN_SCORES]
    try:
        with open(SPEEDRUN_SCORE_PATH, "w", encoding="utf-8") as f:
            json.dump({"runs": runs}, f, indent=2)
    except OSError:
        pass
    return runs


def load_daily() -> dict:
    try:
        with open(DAILY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_daily(data: dict) -> None:
    try:
        with open(DAILY_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


def daily_played_today() -> bool:
    """True once today's daily has been started (one attempt per day)."""
    date_str, _ = daily_seed()
    st = load_daily()
    return st.get("date") == date_str and bool(st.get("played"))


def load_run_history() -> list:
    try:
        with open(RUN_HISTORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("runs", [])
    except (OSError, json.JSONDecodeError):
        return []


def record_run_history(entry: dict) -> list:
    """Append one finished run (any mode) to the rolling history, newest first."""
    runs = load_run_history()
    runs.insert(0, entry)
    runs = runs[:C.MAX_RUN_HISTORY]
    try:
        with open(RUN_HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump({"runs": runs}, f, indent=2)
    except OSError:
        pass
    return runs


def load_bestiary() -> dict:
    try:
        with open(BESTIARY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def merge_bestiary(seen, kills: dict) -> dict:
    """Folds one run's newly-seen breeds/kill counts into the PERSISTENT
    cross-run bestiary file - flushed once at run-end (same cadence as
    run_history.json), not written continuously during play."""
    data = load_bestiary()
    for name in seen:
        entry = data.setdefault(name, {"seen": True, "kills": 0})
        entry["seen"] = True
    for name, count in kills.items():
        entry = data.setdefault(name, {"seen": True, "kills": 0})
        entry["kills"] = entry.get("kills", 0) + count
    try:
        with open(BESTIARY_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass
    return data


def load_lore_journal() -> list:
    try:
        with open(LORE_JOURNAL_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def merge_lore_journal(pages_found) -> list:
    """Folds one run's newly-found page ids into the PERSISTENT cross-run
    lore journal - flushed once at run-end, same cadence as
    merge_bestiary. A page, once found, stays found (plain union)."""
    found = set(load_lore_journal())
    found |= set(pages_found)
    data = sorted(found)
    try:
        with open(LORE_JOURNAL_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass
    return data


def load_achievements() -> dict:
    try:
        with open(ACHIEVEMENTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def unlock_achievements(ctx: dict) -> list:
    """Checks `ctx` (a run summary - see engine/achievements.py) against
    every not-yet-unlocked achievement, persists any newly-earned ones with
    today's timestamp, and returns just the newly-earned Achievement
    objects (for a "you unlocked X!" notification - already-unlocked ones
    are silent)."""
    from . import achievements as achievements_module
    data = load_achievements()
    newly = achievements_module.check_unlocks(ctx, data)
    if newly:
        now = datetime.now().isoformat(timespec="seconds")
        for a in newly:
            data[a.id] = now
        try:
            with open(ACHIEVEMENTS_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass
    return newly


def record_run(state, cause: str) -> list:
    runs = load_highscores()
    runs.append({
        "date": datetime.now().isoformat(timespec="seconds"),
        "depth_reached": state.depth,
        "turns_survived": state.player.turns,
        "level": state.player.level,
        "gold": state.player.gold,
        "kills": state.player.kills,
        "cause": cause,
    })
    runs.sort(key=lambda r: (r["depth_reached"], r["gold"]), reverse=True)
    runs = runs[:C.MAX_HIGHSCORES]
    try:
        with open(HIGHSCORE_PATH, "w", encoding="utf-8") as f:
            json.dump({"runs": runs}, f, indent=2)
    except OSError:
        pass
    return runs
