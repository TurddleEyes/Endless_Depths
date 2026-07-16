"""Replay recording format + playback driver.

A replay is (seed, mode, ordered action list): since every bit of gameplay
randomness flows through GameState's single seeded RNG, feeding the same
actions to a fresh GameState with the same seed reproduces the entire run
exactly. Items are referenced by list index at the moment of the action
(never by item.id, which is a process-global counter and not reproducible).

Depends on engine.world; engine.world does not import this module.
"""
from __future__ import annotations

import json
from datetime import datetime

from . import constants as C
from .world import GameState

# Bump whenever engine generation/logic changes in a way that would make
# previously recorded replays play back differently - old replays are then
# cleanly rejected instead of silently desyncing.
REPLAY_VERSION = 4


def build_replay_dict(state: GameState, elapsed_seconds: float) -> dict:
    cause = state.log[-2] if state.game_over and len(state.log) >= 2 else None
    return {
        "version": REPLAY_VERSION,
        "game": "endless_depths",
        "seed": state.seed,
        "mode": state.mode,
        "target_floor": state.target_floor if state.mode == "speedrun" else None,
        "actions": list(state.action_log),
        "result": {
            "outcome": "victory" if state.game_won else ("death" if state.game_over else "in_progress"),
            "depth_reached": state.depth,
            "level": state.player.level,
            "gold": state.player.gold,
            "kills": state.player.kills,
            "turns": state.player.turns,
            "elapsed_seconds": round(elapsed_seconds, 2),
            "cause": cause,
        },
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
    }


def replay_to_code(replay: dict) -> str:
    """Compact shareable text code (standard base64, matches JS btoa/atob)."""
    import base64
    return base64.b64encode(
        json.dumps(replay, separators=(",", ":")).encode("utf-8")).decode("ascii")


def replay_from_text(text: str) -> dict:
    """Accepts either raw replay JSON or a base64 code produced by
    replay_to_code / the web build. Raises ValueError if neither parses."""
    import base64
    text = text.strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError):
        try:
            data = json.loads(base64.b64decode(text.encode("ascii")).decode("utf-8"))
        except Exception:
            raise ValueError("not a valid replay file or code")
    if not isinstance(data, dict):
        raise ValueError("not a valid replay file or code")
    return data


def _dispatch(state: GameState, action: list) -> None:
    code = action[0]
    try:
        if code == "m":
            _, dx, dy = action
            state.try_move_player(dx, dy)
        elif code == "w":
            state.wait()
        elif code == "u":
            state.use_item(state.player.inventory[action[1]])
        elif code == "e":
            state.equip_item(state.player.inventory[action[1]])
        elif code == "d":
            state.drop_item(state.player.inventory[action[1]])
        elif code == "b":
            state.buy_item(state.floor.shop_stock[action[1]])
        elif code == "s":
            state.sell_item(state.player.inventory[action[1]])
        elif code == "c":
            state.close_shop()
        elif code == "p":
            state.puzzle_input(action[1])
        elif code == "q":
            state.close_puzzle()
    except (IndexError, ValueError, TypeError):
        # Tolerate corrupt/hand-edited replays without crashing playback;
        # a bad action simply does nothing (which is itself deterministic).
        pass


class ReplayPlayer:
    """Drives a fresh GameState through a recorded action list one step at
    a time. The UI calls step() on a timer and drains state.take_events()
    exactly as it does during live play - same renderer, same sounds."""

    def __init__(self, data: dict):
        if data.get("game") != "endless_depths" or data.get("version") != REPLAY_VERSION:
            raise ValueError("unsupported replay format")
        self.seed = int(data["seed"])
        self.mode = data.get("mode", "normal")
        self.target_floor = data.get("target_floor") or C.SPEEDRUN_TARGET_FLOOR
        self.actions = data.get("actions", [])
        self.result_header = data.get("result", {})
        self.state = GameState(seed=self.seed, mode=self.mode,
                                target_floor=self.target_floor)
        self.state.new_game()
        self.state.take_events()  # discard setup events, like live new-game
        self.cursor = 0

    @property
    def finished(self) -> bool:
        return self.cursor >= len(self.actions) or self.state.game_over

    def step(self) -> bool:
        if self.finished:
            return False
        _dispatch(self.state, self.actions[self.cursor])
        self.cursor += 1
        return True

    def run_to_end(self) -> None:
        while self.step():
            pass
