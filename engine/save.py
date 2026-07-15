"""JSON persistence: single-slot autosave and a high-score history file."""
from __future__ import annotations

import json
import os
from datetime import datetime

from . import constants as C

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAVE_PATH = os.path.join(_BASE_DIR, C.SAVE_FILE)
HIGHSCORE_PATH = os.path.join(_BASE_DIR, C.HIGHSCORE_FILE)
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
