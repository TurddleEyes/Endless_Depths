"""JSON persistence: single-slot autosave and a high-score history file."""
from __future__ import annotations

import json
import os
from datetime import datetime

from . import constants as C

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAVE_PATH = os.path.join(_BASE_DIR, C.SAVE_FILE)
HIGHSCORE_PATH = os.path.join(_BASE_DIR, C.HIGHSCORE_FILE)
SPEEDRUN_SCORE_PATH = os.path.join(_BASE_DIR, C.SPEEDRUN_SCORE_FILE)
SETTINGS_PATH = os.path.join(_BASE_DIR, "settings.json")


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
