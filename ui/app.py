"""Tkinter presentation layer for Endless Depths.

This module (and its siblings in ui/) is the only place that imports
tkinter. It talks to the headless engine exclusively through
engine.world.GameState's public methods and drains the engine's structured
event stream (state.take_events()) to drive sounds and animations - it
never reaches into engine internals to mutate state directly.
"""
from __future__ import annotations

import json
import os
import time
import tkinter as tk

from engine import constants as C
from engine import save as save_module
from engine.world import GameState
from engine.replay import (ReplayPlayer, build_replay_dict, replay_from_text,
                            replay_to_code)
from . import theme as T
from . import sprites as sprite_defs
from .audio import AudioManager, track_for_depth
from .iteminfo import RARITY_COLORS, describe_item, sell_price
from .widgets import ItemListPanel
from . import lore as lore_data

MOVE_KEYS = {
    "Up": (0, -1), "w": (0, -1), "W": (0, -1), "k": (0, -1),
    "Down": (0, 1), "s": (0, 1), "S": (0, 1), "j": (0, 1),
    "Left": (-1, 0), "a": (-1, 0), "A": (-1, 0), "h": (-1, 0),
    "Right": (1, 0), "d": (1, 0), "D": (1, 0), "l": (1, 0),
}

WAIT_KEYS = ("period", "z", "Z")

FX_TICK_MS = 33
TITLE_PULSE_COLORS = ("#66d9ef", "#8fe3f5", "#4aa8c0", "#8fe3f5")

REPLAY_SPEEDS = [("1x", 130), ("2x", 45)]  # third option skips to the end


def _fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Endless Depths")
        self.configure(bg=T.BG)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.state: GameState | None = None
        self.mode = "title"
        self._closing = False
        self._fullscreen = False
        self._inventory_items: list = []
        self._shop_stock_items: list = []
        self._shop_inventory_items: list = []
        self._cam = (0, 0)
        self._fx: list = []
        self._fx_running = False
        self._shake_applied = (0, 0)
        self._title_pulse_idx = 0

        self.settings = save_module.load_settings()
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.audio = AudioManager(
            cache_dir=os.path.join(base_dir, "assets"),
            muted=bool(self.settings.get("muted", False)),
        )

        # Pixel-art sprites (must be built after the Tk root exists).
        self.sprites = sprite_defs.build_sprites(zoom=T.TILE_SIZE // sprite_defs.SPRITE_PX)
        self.big_hero = sprite_defs.build_sprite("player", zoom=8)
        self._hero_cache: dict = {}

        self.bind("<Key>", self._on_key)

        self._lore_page = 0
        self._lore_return_to = "title"
        self._run_started_at = time.monotonic()
        self._elapsed_at_end = 0.0
        self._replay: ReplayPlayer | None = None
        self._replay_paused = False
        self._replay_speed_idx = 0

        self._build_title_screen()
        self._build_lore_screen()
        self._build_play_screen()
        self._build_inventory_overlay()
        self._build_shop_overlay()
        self._build_gameover_screen()
        self._build_victory_screen()
        self._build_replay_picker()

        if self.settings.get("seen_lore"):
            self._show_title()
        else:
            self._show_lore(first_time=True)
        self.after(400, self._audio_tick)
        self.after(500, self._title_tick)
        self.after(300, self._stopwatch_tick)

    # ------------------------------------------------------------------
    # Screen construction
    # ------------------------------------------------------------------
    def _build_title_screen(self):
        self.title_frame = tk.Frame(self, bg=T.BG, width=880, height=760)
        self.title_frame.pack_propagate(False)

        self.title_label = tk.Label(self.title_frame, text="ENDLESS DEPTHS",
                                      font=T.TITLE_FONT, bg=T.BG, fg=T.ACCENT)
        self.title_label.pack(pady=(22, 4))
        tk.Label(self.title_frame, text="An infinite dungeon roguelike",
                  font=T.UI_FONT, bg=T.BG, fg=T.TEXT_DIM).pack(pady=(0, 8))

        tk.Label(self.title_frame, image=self.big_hero, bg=T.BG).pack(pady=(0, 8))

        btn_style = dict(font=T.UI_FONT_BOLD, width=22, bg=T.PANEL_BG, fg=T.TEXT_MAIN,
                          activebackground=T.ACCENT, activeforeground=T.BG,
                          relief="flat", bd=0, highlightthickness=1,
                          highlightbackground=T.PANEL_BORDER)

        seed_row = tk.Frame(self.title_frame, bg=T.BG)
        seed_row.pack(pady=(0, 8))
        tk.Label(seed_row, text="Seed (optional):", font=T.UI_FONT, bg=T.BG,
                  fg=T.TEXT_DIM).pack(side="left", padx=(0, 6))
        self.seed_entry = tk.Entry(seed_row, width=14, font=T.UI_FONT, bg=T.PANEL_BG,
                                     fg=T.TEXT_MAIN, insertbackground=T.TEXT_MAIN,
                                     relief="flat", highlightthickness=1,
                                     highlightbackground=T.PANEL_BORDER)
        self.seed_entry.pack(side="left")

        tk.Button(self.title_frame, text="New Game (N)", command=self._start_new_game,
                   **btn_style).pack(pady=5)
        tk.Button(self.title_frame, text="Speedrun to Floor 100 (R)",
                   command=self._start_speedrun, **btn_style).pack(pady=5)
        self.continue_button = tk.Button(self.title_frame, text="Continue (C)",
                                           command=self._continue_game, **btn_style)
        self.continue_button.pack(pady=5)
        tk.Button(self.title_frame, text="Watch Replay (V)",
                   command=self._open_replay_picker, **btn_style).pack(pady=5)
        tk.Button(self.title_frame, text="Lore (L)", command=lambda: self._show_lore(first_time=False),
                   **btn_style).pack(pady=5)
        tk.Button(self.title_frame, text="Quit", command=self._on_close,
                   **btn_style).pack(pady=5)

        scores_row = tk.Frame(self.title_frame, bg=T.BG)
        scores_row.pack(pady=(16, 0))
        self.highscore_label = tk.Label(scores_row, text="", font=T.UI_FONT,
                                          bg=T.BG, fg=T.TEXT_DIM, justify="left")
        self.highscore_label.pack(side="left", padx=12, anchor="n")
        self.speedrun_score_label = tk.Label(scores_row, text="", font=T.UI_FONT,
                                               bg=T.BG, fg=T.TEXT_DIM, justify="left")
        self.speedrun_score_label.pack(side="left", padx=12, anchor="n")

        self.title_status_label = tk.Label(self.title_frame, text="", font=T.UI_FONT,
                                             bg=T.BG, fg=T.TEXT_BAD)
        self.title_status_label.pack(pady=(8, 0))

    def _build_lore_screen(self):
        self.lore_frame = tk.Frame(self, bg=T.BG, width=860, height=640)
        self.lore_frame.pack_propagate(False)

        tk.Label(self.lore_frame, text=lore_data.TITLE, font=T.HEADER_FONT,
                  bg=T.BG, fg=T.ACCENT).pack(pady=(50, 20))

        self.lore_text_label = tk.Label(self.lore_frame, text="", font=T.UI_FONT,
                                          bg=T.BG, fg=T.TEXT_MAIN, justify="left",
                                          wraplength=620, height=10)
        self.lore_text_label.pack(pady=(0, 16))

        self.lore_page_label = tk.Label(self.lore_frame, text="", font=("Courier", 9),
                                          bg=T.BG, fg=T.TEXT_DIM)
        self.lore_page_label.pack(pady=(0, 14))

        btn_style = dict(font=T.UI_FONT_BOLD, width=14, bg=T.PANEL_BG, fg=T.TEXT_MAIN,
                          activebackground=T.ACCENT, activeforeground=T.BG,
                          relief="flat", bd=0, highlightthickness=1,
                          highlightbackground=T.PANEL_BORDER)
        nav_row = tk.Frame(self.lore_frame, bg=T.BG)
        nav_row.pack()
        tk.Button(nav_row, text="< Back", command=lambda: self._lore_step(-1),
                   **btn_style).pack(side="left", padx=6)
        self.lore_next_button = tk.Button(nav_row, text="Next >",
                                            command=lambda: self._lore_step(1), **btn_style)
        self.lore_next_button.pack(side="left", padx=6)

    def _show_lore(self, first_time: bool):
        self._hide_all()
        self.mode = "lore"
        self._lore_return_to = "first_launch" if first_time else "title"
        self._lore_page = 0
        self._render_lore_page()
        self.lore_frame.pack(expand=True)

    def _render_lore_page(self):
        n = len(lore_data.PAGES)
        self.lore_text_label.configure(text=lore_data.PAGES[self._lore_page])
        self.lore_page_label.configure(text=f"Page {self._lore_page + 1} / {n}")
        self.lore_next_button.configure(
            text="Begin >" if self._lore_page == n - 1 else "Next >")

    def _lore_step(self, delta: int):
        n = len(lore_data.PAGES)
        if delta > 0 and self._lore_page == n - 1:
            self._finish_lore()
            return
        self._lore_page = max(0, min(self._lore_page + delta, n - 1))
        self._render_lore_page()

    def _finish_lore(self):
        if not self.settings.get("seen_lore"):
            self.settings["seen_lore"] = True
            save_module.save_settings(self.settings)
        self._show_title()

    def _build_play_screen(self):
        self.play_frame = tk.Frame(self, bg=T.BG)

        top = tk.Frame(self.play_frame, bg=T.BG)
        top.pack(side="top")

        canvas_w = T.VIEWPORT_COLS * T.TILE_SIZE
        canvas_h = T.VIEWPORT_ROWS * T.TILE_SIZE
        self.canvas = tk.Canvas(top, width=canvas_w, height=canvas_h,
                                  bg=T.BG, highlightthickness=1,
                                  highlightbackground=T.PANEL_BORDER)
        self.canvas.pack(side="left")

        panel = tk.Frame(top, width=260, height=canvas_h, bg=T.PANEL_BG)
        panel.pack(side="right", fill="y")
        panel.pack_propagate(False)
        self._build_stat_panel(panel)

        log_frame = tk.Frame(self.play_frame, bg=T.PANEL_BG, width=canvas_w + 260, height=120)
        log_frame.pack(side="top", pady=(6, 0))
        log_frame.pack_propagate(False)
        self.log_text = tk.Text(log_frame, bg=T.PANEL_BG, fg=T.TEXT_MAIN,
                                  font=T.UI_FONT, wrap="word", state="disabled",
                                  bd=0, highlightthickness=0)
        self.log_text.pack(fill="both", expand=True, padx=8, pady=6)

        self.footer_label = tk.Label(self.play_frame, text="", font=("Courier", 9),
                                       bg=T.BG, fg=T.TEXT_DIM)
        self.footer_label.pack(side="top", pady=(4, 4))
        self._update_footer()

    def _update_footer(self):
        sound = "off" if self.audio.muted else "on"
        self.footer_label.configure(
            text=("Move: arrows/WASD/hjkl  |  E: inventory  |  .: wait  |  "
                  f"M: sound ({sound})  |  F11: fullscreen  |  walk into stairs to descend"))

    def _build_stat_panel(self, panel: tk.Frame):
        tk.Label(panel, text="ENDLESS DEPTHS", font=T.HEADER_FONT,
                  bg=T.PANEL_BG, fg=T.ACCENT).pack(anchor="w", padx=10, pady=(8, 4))

        self.depth_label = self._panel_label(panel, "Depth: 1")
        self.timer_label = self._panel_label(panel, "")
        self.timer_label.configure(fg=T.TEXT_WARN)
        self.level_label = self._panel_label(panel, "Level: 1")
        self.seed_label = self._panel_label(panel, "Seed: -")
        self.seed_label.configure(fg=T.TEXT_DIM)
        self.seed_label.bind("<Button-1>", lambda _e: self._copy_seed())

        self.hp_bar = tk.Canvas(panel, width=220, height=18, bg=T.PANEL_BG, highlightthickness=0)
        self.hp_bar.pack(anchor="w", padx=10, pady=(4, 2))
        self.xp_bar = tk.Canvas(panel, width=220, height=12, bg=T.PANEL_BG, highlightthickness=0)
        self.xp_bar.pack(anchor="w", padx=10, pady=(2, 4))

        self.status_label = self._panel_label(panel, "")
        self.attack_label = self._panel_label(panel, "Attack: 0")
        self.defense_label = self._panel_label(panel, "Defense: 0")
        self.gold_label = self._panel_label(panel, "Gold: 0")

        tk.Frame(panel, bg=T.PANEL_BORDER, height=1).pack(fill="x", padx=10, pady=6)

        self.weapon_label = self._panel_label(panel, "Weapon: (none)", wrap=240)
        self.armor_label = self._panel_label(panel, "Armor: (none)", wrap=240)
        self.accessory_label = self._panel_label(panel, "Accessory: (none)", wrap=240)

        tk.Frame(panel, bg=T.PANEL_BORDER, height=1).pack(fill="x", padx=10, pady=6)

        self.kills_label = self._panel_label(panel, "Kills: 0    Turns: 0")

        tk.Label(panel, text="Map", font=T.UI_FONT_BOLD, bg=T.PANEL_BG,
                  fg=T.TEXT_MAIN).pack(anchor="w", padx=10, pady=(4, 0))
        self.minimap = tk.Canvas(panel, width=240, height=80, bg=T.BG,
                                   highlightthickness=0)
        self.minimap.pack(anchor="w", padx=10, pady=(2, 6))

    def _panel_label(self, parent, text, wrap=None):
        lbl = tk.Label(parent, text=text, font=T.UI_FONT, bg=T.PANEL_BG, fg=T.TEXT_MAIN,
                         anchor="w", justify="left")
        if wrap:
            lbl.configure(wraplength=wrap)
        lbl.pack(anchor="w", padx=10, pady=1)
        return lbl

    def _build_inventory_overlay(self):
        self.inventory_frame = tk.Frame(self, bg=T.PANEL_BG, highlightthickness=2,
                                          highlightbackground=T.ACCENT)
        f = self.inventory_frame

        header = tk.Frame(f, bg=T.PANEL_BG)
        header.pack(fill="x", padx=14, pady=(10, 2))
        tk.Label(header, text="Inventory", font=T.HEADER_FONT, bg=T.PANEL_BG,
                  fg=T.ACCENT).pack(side="left")
        self.inventory_gold_label = tk.Label(header, text="Gold: 0", font=T.UI_FONT_BOLD,
                                               bg=T.PANEL_BG, fg=T.TEXT_WARN)
        self.inventory_gold_label.pack(side="right")

        self.inventory_equipped_label = tk.Label(f, text="", font=T.UI_FONT,
                                                    bg=T.PANEL_BG, fg=T.TEXT_DIM,
                                                    justify="left", anchor="w")
        self.inventory_equipped_label.pack(fill="x", padx=14, pady=(0, 6))

        self.inv_panel = ItemListPanel(f, self._inventory_formatter, rows=12,
                                         list_width=32, details_width_px=250,
                                         on_activate=lambda _item: self._inventory_activate())
        self.inv_panel.pack(padx=14, pady=4, fill="both", expand=True)

        btn_row = tk.Frame(f, bg=T.PANEL_BG)
        btn_row.pack(pady=(6, 4))
        style = dict(font=T.UI_FONT, bg=T.BG, fg=T.TEXT_MAIN, relief="flat",
                      activebackground=T.ACCENT, activeforeground=T.BG)
        tk.Button(btn_row, text="Use / Equip (Enter)", command=self._inventory_activate,
                   **style).pack(side="left", padx=6)
        tk.Button(btn_row, text="Drop (D)", command=self._inventory_drop, **style).pack(side="left", padx=6)
        tk.Button(btn_row, text="Close (Esc)", command=self._close_overlay, **style).pack(side="left", padx=6)

        tk.Label(f, text="Click: view   Double-click/Enter: use or equip   D: drop   Esc: close",
                  font=("Courier", 9), bg=T.PANEL_BG, fg=T.TEXT_DIM).pack(pady=(0, 10))

    def _build_shop_overlay(self):
        self.shop_frame = tk.Frame(self, bg=T.PANEL_BG, highlightthickness=2,
                                     highlightbackground=T.ACCENT)
        f = self.shop_frame
        self._shop_tab = "buy"

        header = tk.Frame(f, bg=T.PANEL_BG)
        header.pack(fill="x", padx=14, pady=(10, 2))
        tk.Label(header, text="Shop", font=T.HEADER_FONT, bg=T.PANEL_BG,
                  fg=T.ACCENT).pack(side="left")
        self.shop_gold_label = tk.Label(header, text="Gold: 0", font=T.UI_FONT_BOLD,
                                          bg=T.PANEL_BG, fg=T.TEXT_WARN)
        self.shop_gold_label.pack(side="right")

        tabs = tk.Frame(f, bg=T.PANEL_BG)
        tabs.pack(pady=(4, 6))
        self.shop_buy_tab = tk.Label(tabs, text="  Buy  ", font=T.UI_FONT_BOLD,
                                       bg=T.ACCENT, fg=T.BG)
        self.shop_buy_tab.pack(side="left", padx=2)
        self.shop_buy_tab.bind("<Button-1>", lambda _e: self._shop_set_tab("buy"))
        self.shop_sell_tab = tk.Label(tabs, text="  Sell  ", font=T.UI_FONT_BOLD,
                                        bg=T.BG, fg=T.TEXT_DIM)
        self.shop_sell_tab.pack(side="left", padx=2)
        self.shop_sell_tab.bind("<Button-1>", lambda _e: self._shop_set_tab("sell"))

        self.shop_panel = ItemListPanel(f, self._shop_formatter, rows=12,
                                          list_width=32, details_width_px=250,
                                          on_activate=lambda _item: self._shop_activate())
        self.shop_panel.pack(padx=14, pady=4, fill="both", expand=True)

        btn_row = tk.Frame(f, bg=T.PANEL_BG)
        btn_row.pack(pady=(6, 4))
        style = dict(font=T.UI_FONT, bg=T.BG, fg=T.TEXT_MAIN, relief="flat",
                      activebackground=T.ACCENT, activeforeground=T.BG)
        self.shop_action_button = tk.Button(btn_row, text="Buy (Enter)",
                                              command=self._shop_activate, **style)
        self.shop_action_button.pack(side="left", padx=6)
        tk.Button(btn_row, text="Switch (Tab)",
                   command=lambda: self._shop_set_tab("sell" if self._shop_tab == "buy" else "buy"),
                   **style).pack(side="left", padx=6)
        tk.Button(btn_row, text="Leave Shop (Esc)", command=self._close_shop,
                   **style).pack(side="left", padx=6)

        tk.Label(f, text="Click: view   Double-click/Enter: buy or sell   Tab: switch pane   Esc: leave",
                  font=("Courier", 9), bg=T.PANEL_BG, fg=T.TEXT_DIM).pack(pady=(0, 10))

    def _terminal_screen_buttons(self, frame):
        """Save/Copy replay buttons + return button, shared by the game-over
        and victory screens. Returns (replay_row, status_label)."""
        style = dict(font=T.UI_FONT, bg=T.PANEL_BG, fg=T.TEXT_MAIN, relief="flat",
                      activebackground=T.ACCENT, activeforeground=T.BG)
        replay_row = tk.Frame(frame, bg=T.BG)
        replay_row.pack(pady=(0, 8))
        tk.Button(replay_row, text="Save Replay File",
                   command=self._save_replay_file, **style).pack(side="left", padx=5)
        tk.Button(replay_row, text="Copy Replay Code",
                   command=self._copy_replay_code, **style).pack(side="left", padx=5)
        status = tk.Label(frame, text="", font=("Courier", 9), bg=T.BG, fg=T.TEXT_GOOD)
        status.pack(pady=(0, 8))
        tk.Button(frame, text="Return to Title", font=T.UI_FONT_BOLD,
                   command=self._show_title, bg=T.PANEL_BG, fg=T.TEXT_MAIN,
                   activebackground=T.ACCENT, relief="flat", width=22).pack()
        return replay_row, status

    def _build_gameover_screen(self):
        self.gameover_frame = tk.Frame(self, bg=T.BG, width=880, height=680)
        self.gameover_frame.pack_propagate(False)
        tk.Label(self.gameover_frame, text="YOU DIED", font=T.TITLE_FONT,
                  bg=T.BG, fg=T.TEXT_BAD).pack(pady=(40, 10))
        self.gameover_stats_label = tk.Label(self.gameover_frame, text="", font=T.UI_FONT,
                                               bg=T.BG, fg=T.TEXT_MAIN, justify="left")
        self.gameover_stats_label.pack(pady=(0, 14))
        self.gameover_highscores_label = tk.Label(self.gameover_frame, text="", font=T.UI_FONT,
                                                     bg=T.BG, fg=T.TEXT_DIM, justify="left")
        self.gameover_highscores_label.pack(pady=(0, 14))
        self.gameover_replay_row, self.gameover_replay_status = \
            self._terminal_screen_buttons(self.gameover_frame)

    def _build_victory_screen(self):
        self.victory_frame = tk.Frame(self, bg=T.BG, width=880, height=680)
        self.victory_frame.pack_propagate(False)
        tk.Label(self.victory_frame, text="VICTORY!", font=T.TITLE_FONT,
                  bg=T.BG, fg=T.TEXT_WARN).pack(pady=(40, 2))
        tk.Label(self.victory_frame, text="You escaped the Endless Depths.",
                  font=T.UI_FONT, bg=T.BG, fg=T.TEXT_MAIN).pack(pady=(0, 12))
        self.victory_stats_label = tk.Label(self.victory_frame, text="", font=T.UI_FONT,
                                              bg=T.BG, fg=T.TEXT_MAIN, justify="left")
        self.victory_stats_label.pack(pady=(0, 14))
        self.victory_scores_label = tk.Label(self.victory_frame, text="", font=T.UI_FONT,
                                               bg=T.BG, fg=T.TEXT_DIM, justify="left")
        self.victory_scores_label.pack(pady=(0, 14))
        self.victory_replay_row, self.victory_replay_status = \
            self._terminal_screen_buttons(self.victory_frame)

    def _build_replay_picker(self):
        self.replay_picker_frame = tk.Frame(self, bg=T.PANEL_BG, highlightthickness=2,
                                              highlightbackground=T.ACCENT)
        f = self.replay_picker_frame
        tk.Label(f, text="Watch Replay", font=T.HEADER_FONT, bg=T.PANEL_BG,
                  fg=T.ACCENT).pack(pady=(10, 6))
        style = dict(font=T.UI_FONT, bg=T.BG, fg=T.TEXT_MAIN, relief="flat",
                      activebackground=T.ACCENT, activeforeground=T.BG)
        tk.Button(f, text="Load Replay File...", command=self._load_replay_file,
                   **style).pack(pady=4)
        tk.Label(f, text="or paste a replay code:", font=T.UI_FONT, bg=T.PANEL_BG,
                  fg=T.TEXT_DIM).pack(pady=(8, 2))
        self.replay_code_text = tk.Text(f, width=52, height=6, font=("Courier", 9),
                                          bg=T.BG, fg=T.TEXT_MAIN,
                                          insertbackground=T.TEXT_MAIN, bd=0,
                                          highlightthickness=1,
                                          highlightbackground=T.PANEL_BORDER)
        self.replay_code_text.pack(padx=14, pady=4)
        self.replay_picker_status = tk.Label(f, text="", font=T.UI_FONT, bg=T.PANEL_BG,
                                               fg=T.TEXT_BAD)
        self.replay_picker_status.pack(pady=(2, 0))
        btn_row = tk.Frame(f, bg=T.PANEL_BG)
        btn_row.pack(pady=(6, 12))
        tk.Button(btn_row, text="Play Pasted Code", command=self._play_pasted_code,
                   **style).pack(side="left", padx=6)
        tk.Button(btn_row, text="Cancel (Esc)", command=self._close_replay_picker,
                   **style).pack(side="left", padx=6)

    # ------------------------------------------------------------------
    # Screen switching
    # ------------------------------------------------------------------
    def _hide_all(self):
        for frame in (self.title_frame, self.lore_frame, self.play_frame,
                       self.gameover_frame, self.victory_frame):
            frame.pack_forget()
        self.inventory_frame.place_forget()
        self.shop_frame.place_forget()
        self.replay_picker_frame.place_forget()

    def _show_title(self):
        self._hide_all()
        self.mode = "title"
        has_save = save_module.has_save()
        self.continue_button.configure(state="normal" if has_save else "disabled")
        runs = save_module.load_highscores()
        if runs:
            lines = ["Top runs:"]
            for r in runs[:5]:
                lines.append(f"  Floor {r['depth_reached']:>3}  Lv {r['level']:<3} "
                              f"Gold {r['gold']:<5} - {r['cause']}")
            self.highscore_label.configure(text="\n".join(lines))
        else:
            self.highscore_label.configure(text="No runs recorded yet - descend and see how far you get.")

        speedruns = save_module.load_speedrun_scores()
        if speedruns:
            lines = [f"Speedrun (goal: floor {C.SPEEDRUN_TARGET_FLOOR}):"]
            for r in speedruns[:5]:
                mark = "WIN " if r.get("finished") else f"F{r['depth_reached']:<3}"
                lines.append(f"  {mark} {_fmt_time(r['elapsed_seconds']):>8}  seed {r['seed']}")
            self.speedrun_score_label.configure(text="\n".join(lines))
        else:
            self.speedrun_score_label.configure(
                text=f"Speedrun: race to floor {C.SPEEDRUN_TARGET_FLOOR}.\nNo attempts yet.")

        self.title_status_label.configure(text="")
        self.title_frame.pack(expand=True)
        self.audio.play_music("depths")

    def _read_seed_input(self):
        """Returns (ok, seed_or_None) from the title-screen seed field."""
        text = self.seed_entry.get().strip()
        if not text:
            return True, None
        try:
            return True, int(text)
        except ValueError:
            self.title_status_label.configure(text="Seed must be a whole number.")
            return False, None

    def _start_new_game(self):
        self._begin_run("normal")

    def _start_speedrun(self):
        self._begin_run("speedrun")

    def _begin_run(self, mode: str):
        ok, seed = self._read_seed_input()
        if not ok:
            return
        self.state = GameState(seed=seed, mode=mode)
        self.state.new_game()
        self.state.take_events()  # discard setup events
        self._run_started_at = time.monotonic()
        self._elapsed_at_end = 0.0
        save_module.save_game(self.state)
        self._enter_play_mode()

    def _continue_game(self):
        loaded = save_module.load_game()
        if loaded is None:
            self.title_status_label.configure(text="No valid save found.")
            return
        self.state = loaded
        self.state.take_events()
        self._run_started_at = time.monotonic()
        self._elapsed_at_end = 0.0
        self._enter_play_mode()

    def _enter_play_mode(self):
        self._hide_all()
        self.mode = "play"
        self._fx = []
        self.play_frame.pack(expand=True)
        self.focus_set()
        self._render()
        self._update_music()

    def _final_elapsed(self) -> float:
        return self._elapsed_at_end or (time.monotonic() - self._run_started_at)

    def _show_gameover(self):
        self._hide_all()
        self.mode = "gameover"
        p = self.state.player
        cause = self.state.log[-2] if len(self.state.log) >= 2 else "Unknown causes."
        self.gameover_stats_label.configure(
            text=(f"Cause of death: {cause}\n\n"
                  f"Depth reached: {self.state.depth}\n"
                  f"Level: {p.level}\n"
                  f"Gold collected: {p.gold}\n"
                  f"Monsters slain: {p.kills}\n"
                  f"Turns survived: {p.turns}\n"
                  f"Time: {_fmt_time(self._final_elapsed())}\n"
                  f"Seed: {self.state.seed}")
        )
        if self.state.mode == "speedrun":
            runs = save_module.record_speedrun_run(self.state, self._final_elapsed())
            lines = ["Speedrun Leaderboard:"]
            for r in runs[:5]:
                mark = "WIN " if r.get("finished") else f"F{r['depth_reached']:<3}"
                lines.append(f"  {mark} {_fmt_time(r['elapsed_seconds']):>8}")
        else:
            runs = save_module.record_run(self.state, cause)
            lines = ["High Scores:"]
            for r in runs[:5]:
                lines.append(f"  Floor {r['depth_reached']:>3}  Lv {r['level']:<3} Gold {r['gold']:<5}")
        save_module.delete_save()
        self.gameover_highscores_label.configure(text="\n".join(lines))
        self._set_replay_buttons_visible(self.gameover_replay_row, self.gameover_replay_status)
        self.gameover_frame.pack(expand=True)
        self.audio.play_music(None)

    def _show_victory(self):
        self._hide_all()
        self.mode = "gameover"
        p = self.state.player
        elapsed = self._final_elapsed()
        self.victory_stats_label.configure(
            text=(f"Floor {self.state.target_floor} reached in {_fmt_time(elapsed)}!\n\n"
                  f"Level: {p.level}\n"
                  f"Gold collected: {p.gold}\n"
                  f"Monsters slain: {p.kills}\n"
                  f"Turns taken: {p.turns}\n"
                  f"Seed: {self.state.seed}")
        )
        runs = save_module.record_speedrun_run(self.state, elapsed)
        save_module.delete_save()
        lines = ["Speedrun Leaderboard:"]
        for r in runs[:5]:
            mark = "WIN " if r.get("finished") else f"F{r['depth_reached']:<3}"
            lines.append(f"  {mark} {_fmt_time(r['elapsed_seconds']):>8}")
        self.victory_scores_label.configure(text="\n".join(lines))
        self._set_replay_buttons_visible(self.victory_replay_row, self.victory_replay_status)
        self.victory_frame.pack(expand=True)
        self.audio.play_music(None)

    def _set_replay_buttons_visible(self, row, status_label):
        status_label.configure(text="", fg=T.TEXT_GOOD)
        if self.state.replayable:
            row.pack(pady=(0, 8))
        else:
            row.pack_forget()
            status_label.configure(text="(replay unavailable for continued runs)",
                                    fg=T.TEXT_DIM)
        self._active_replay_status = status_label

    # ------------------------------------------------------------------
    # Replay save / share / watch
    # ------------------------------------------------------------------
    def _save_replay_file(self):
        from tkinter import filedialog
        replay = build_replay_dict(self.state, self._final_elapsed())
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            initialfile=f"endless-depths-replay-seed{self.state.seed}.json",
            filetypes=[("Replay files", "*.json")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(replay, f, separators=(",", ":"))
            self._active_replay_status.configure(text=f"Saved to {os.path.basename(path)}",
                                                  fg=T.TEXT_GOOD)
        except OSError as exc:
            self._active_replay_status.configure(text=f"Could not save: {exc}", fg=T.TEXT_BAD)

    def _copy_replay_code(self):
        replay = build_replay_dict(self.state, self._final_elapsed())
        code = replay_to_code(replay)
        self.clipboard_clear()
        self.clipboard_append(code)
        self.update()
        self._active_replay_status.configure(
            text=f"Replay code copied to clipboard ({len(code)} characters).", fg=T.TEXT_GOOD)

    def _open_replay_picker(self):
        self.mode = "replay_picker"
        self.replay_picker_status.configure(text="")
        self.replay_code_text.delete("1.0", tk.END)
        self.replay_picker_frame.place(relx=0.5, rely=0.5, anchor="center")

    def _close_replay_picker(self):
        self.replay_picker_frame.place_forget()
        self.mode = "title"

    def _load_replay_file(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(filetypes=[("Replay files", "*.json"),
                                                       ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            self._start_watch_replay(replay_from_text(text))
        except (OSError, ValueError) as exc:
            self.replay_picker_status.configure(text=f"Could not load replay: {exc}")

    def _play_pasted_code(self):
        text = self.replay_code_text.get("1.0", tk.END).strip()
        if not text:
            self.replay_picker_status.configure(text="Paste a replay code first.")
            return
        try:
            self._start_watch_replay(replay_from_text(text))
        except ValueError as exc:
            self.replay_picker_status.configure(text=str(exc))

    def _start_watch_replay(self, replay_dict: dict):
        try:
            self._replay = ReplayPlayer(replay_dict)
        except (ValueError, KeyError, TypeError) as exc:
            self.replay_picker_status.configure(text=f"Invalid replay: {exc}")
            return
        self.state = self._replay.state
        self._hide_all()
        self.mode = "replay"
        self._replay_paused = False
        self._replay_speed_idx = 0
        self._fx = []
        self.play_frame.pack(expand=True)
        self.focus_set()
        self._render()
        self._update_music()
        self.after(400, self._replay_tick)

    def _replay_tick(self):
        if self._closing or self.mode != "replay" or self._replay_paused:
            return
        if self._replay.finished:
            self.after(1200, self._stop_replay)
            return
        self._replay.step()
        # Read-only playback: same event->sound/fx pipeline as live play,
        # but never save_game / record_run / record_speedrun_run.
        self._drain_events()
        self._render()
        self._update_music()
        self._update_replay_footer()
        self.after(REPLAY_SPEEDS[self._replay_speed_idx][1], self._replay_tick)

    def _update_replay_footer(self):
        speed = REPLAY_SPEEDS[self._replay_speed_idx][0]
        state_txt = "PAUSED" if self._replay_paused else "PLAYING"
        self.footer_label.configure(
            text=(f"REPLAY {state_txt} {self._replay.cursor}/{len(self._replay.actions)} "
                  f"({speed})  |  Space: pause  |  S: speed/skip  |  Esc: stop"))

    def _toggle_replay_pause(self):
        self._replay_paused = not self._replay_paused
        self._update_replay_footer()
        if not self._replay_paused:
            self._replay_tick()

    def _cycle_replay_speed(self):
        if self._replay_speed_idx < len(REPLAY_SPEEDS) - 1:
            self._replay_speed_idx += 1
            self._update_replay_footer()
        else:
            self._replay.run_to_end()
            self.state.take_events()
            self._render()
            self.after(1200, self._stop_replay)

    def _stop_replay(self):
        if self.mode != "replay":
            return
        self._replay = None
        self._update_footer()
        self._show_title()

    def _on_close(self):
        self._closing = True
        if self.mode in ("play", "inventory", "shop") and self.state and not self.state.game_over:
            save_module.save_game(self.state)
        self.audio.shutdown()
        self.destroy()

    # ------------------------------------------------------------------
    # Background loops
    # ------------------------------------------------------------------
    def _audio_tick(self):
        if self._closing:
            return
        self.audio.tick()
        self.after(400, self._audio_tick)

    def _title_tick(self):
        if self._closing:
            return
        if self.mode == "title":
            self._title_pulse_idx = (self._title_pulse_idx + 1) % len(TITLE_PULSE_COLORS)
            self.title_label.configure(fg=TITLE_PULSE_COLORS[self._title_pulse_idx])
        self.after(500, self._title_tick)

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------
    def _on_key(self, event):
        if self._closing or self.mode == "dying":
            return
        # While a text-entry widget has focus, don't treat letters as
        # shortcuts (typing a seed or pasting a replay code must be safe).
        focused = self.focus_get()
        if focused is getattr(self, "seed_entry", None):
            if event.keysym == "Return":
                self._start_new_game()
            elif event.keysym == "Escape":
                self.focus_set()
            return
        if focused is getattr(self, "replay_code_text", None):
            if event.keysym == "Escape":
                self._close_replay_picker()
            return
        if event.keysym in ("m", "M"):
            self._toggle_mute()
            return
        if event.keysym == "F11":
            self._toggle_fullscreen()
            return
        if self.mode == "play":
            self._handle_play_key(event)
        elif self.mode == "inventory":
            ks = event.keysym
            if ks == "Escape":
                self._close_overlay()
            elif ks in ("Up", "k"):
                self.inv_panel.move_selection(-1)
            elif ks in ("Down", "j"):
                self.inv_panel.move_selection(1)
            elif ks == "Return":
                self._inventory_activate()
            elif ks in ("d", "D"):
                self._inventory_drop()
        elif self.mode == "shop":
            ks = event.keysym
            if ks == "Escape":
                self._close_shop()
            elif ks == "Tab":
                self._shop_set_tab("sell" if self._shop_tab == "buy" else "buy")
            elif ks in ("Up", "k"):
                self.shop_panel.move_selection(-1)
            elif ks in ("Down", "j"):
                self.shop_panel.move_selection(1)
            elif ks == "Return":
                self._shop_activate()
        elif self.mode == "title":
            if event.keysym in ("Return", "n", "N"):
                self._start_new_game()
            elif event.keysym in ("r", "R"):
                self._start_speedrun()
            elif event.keysym in ("c", "C") and str(self.continue_button["state"]) == "normal":
                self._continue_game()
            elif event.keysym in ("v", "V"):
                self._open_replay_picker()
            elif event.keysym in ("l", "L"):
                self._show_lore(first_time=False)
        elif self.mode == "replay_picker":
            if event.keysym == "Escape":
                self._close_replay_picker()
        elif self.mode == "replay":
            ks = event.keysym
            if ks == "space":
                self._toggle_replay_pause()
            elif ks in ("s", "S"):
                self._cycle_replay_speed()
            elif ks == "Escape":
                self._stop_replay()
        elif self.mode == "lore":
            ks = event.keysym
            if ks in ("Right", "Return", "space"):
                self._lore_step(1)
            elif ks in ("Left", "BackSpace"):
                self._lore_step(-1)
            elif ks == "Escape":
                self._finish_lore()
        elif self.mode == "gameover":
            # Only deliberate keys leave the end screen - a stray keypress
            # shouldn't skip past the Save Replay buttons.
            if event.keysym in ("Return", "Escape"):
                self._show_title()

    def _toggle_fullscreen(self):
        self._fullscreen = not self._fullscreen
        try:
            self.attributes("-fullscreen", self._fullscreen)
        except tk.TclError:
            self._fullscreen = False

    def _toggle_mute(self):
        self.audio.set_muted(not self.audio.muted)
        self.settings["muted"] = self.audio.muted
        save_module.save_settings(self.settings)
        self._update_footer()
        if not self.audio.muted:
            self._update_music()

    def _handle_play_key(self, event):
        ks = event.keysym
        if ks in ("e", "E"):
            self._open_inventory()
            self.audio.play("menu")
            return
        if ks in WAIT_KEYS:
            self.state.wait()
            self._after_player_action()
            return
        if ks in MOVE_KEYS:
            dx, dy = MOVE_KEYS[ks]
            self.state.try_move_player(dx, dy)
            self._after_player_action()

    def _after_player_action(self):
        save_module.save_game(self.state)
        self._drain_events()
        if self.state.game_over:
            self._elapsed_at_end = time.monotonic() - self._run_started_at
            self.mode = "dying"
            self._render()
            self.after(900, self._show_victory if self.state.game_won else self._show_gameover)
            return
        if self.state.pending_shop:
            self._open_shop()
            self.audio.play("shop_bell")
            return
        p = self.state.player
        if p.hp <= p.max_hp * 0.25:
            self.audio.play("heartbeat")
        self._render()
        self._update_music()

    # ------------------------------------------------------------------
    # Engine events -> sound + animation
    # ------------------------------------------------------------------
    def _drain_events(self):
        p = self.state.player
        for ev in self.state.take_events():
            et = ev["type"]
            if et == "hit":
                self.audio.play("crit" if ev.get("crit") else "hit")
                color = "#ffd24a" if ev.get("crit") else "#ffffff"
                self._add_fx("num", x=ev["x"], y=ev["y"], text=str(ev["dmg"]), color=color)
                self._add_fx("flash", x=ev["x"], y=ev["y"], color="#ffffff", ttl=3)
            elif et == "player_hit":
                self.audio.play("player_hurt")
                self._add_fx("num", x=p.x, y=p.y, text=str(ev["dmg"]), color="#ff6b6b")
                self._add_fx("flash", x=p.x, y=p.y, color="#e04848", ttl=3)
                self._shake(5 if ev.get("crit") else 3)
            elif et == "kill":
                self.audio.play("boss_kill" if ev.get("boss") else "kill")
                self._add_fx("poof", x=ev["x"], y=ev["y"],
                              color="#f2c94c" if ev.get("boss") else "#c9c9c9",
                              ttl=14 if ev.get("boss") else 10)
                if ev.get("boss"):
                    self._shake(6)
            elif et == "levelup":
                self.audio.play("levelup")
                self._add_fx("sparkle", x=p.x, y=p.y, ttl=16)
            elif et == "gold":
                self.audio.play("gold")
            elif et == "pickup":
                self.audio.play("pickup")
            elif et == "step":
                self.audio.play("step")
            elif et == "drop":
                self.audio.play("drop")
            elif et == "potion":
                self.audio.play("potion")
            elif et == "strength":
                self.audio.play("strength")
                self._add_fx("num", x=p.x, y=p.y, text="+STR", color="#e0a83a")
            elif et == "cure":
                self.audio.play("cure")
                self._add_fx("poof", x=p.x, y=p.y, color="#58c058", ttl=10)
            elif et == "enchant":
                self.audio.play("enchant")
                self._add_fx("sparkle", x=p.x, y=p.y, ttl=14)
            elif et == "scroll":
                self.audio.play("scroll")
            elif et == "equip":
                self.audio.play("equip")
            elif et == "teleport":
                self.audio.play("teleport")
                self._add_fx("poof", x=p.x, y=p.y, color="#b060e0", ttl=12)
            elif et == "fireball":
                self.audio.play("fireball")
                self._shake(4)
            elif et == "trap":
                self.audio.play("trap")
                self._add_fx("flash", x=ev["x"], y=ev["y"], color="#e07030", ttl=4)
                if "dmg" in ev:
                    self._add_fx("num", x=p.x, y=p.y, text=str(ev["dmg"]), color="#e07030")
            elif et == "poisoned":
                self.audio.play("splat")
                self._add_fx("num", x=p.x, y=p.y, text="poison!", color="#58c058")
            elif et == "poison_tick":
                self.audio.play("poison_tick")
                self._add_fx("num", x=p.x, y=p.y, text=str(ev["dmg"]), color="#58c058")
            elif et == "descend":
                self.audio.play("stairs")
                if ev.get("boss_floor"):
                    self.audio.play("boss_intro")
                self._add_fx("fade", ttl=8)
            elif et == "buy":
                self.audio.play("buy")
            elif et == "sell":
                self.audio.play("sell")
            elif et == "player_death":
                self.audio.play("death")
                self._add_fx("flash", x=p.x, y=p.y, color="#e04848", ttl=8)
                self._shake(7)

    def _update_music(self):
        if self.audio.muted or self.state is None:
            return
        boss_alive = any(m.is_boss and m.is_alive() for m in self.state.floor.monsters)
        self.audio.play_music(track_for_depth(self.state.depth, boss_alive))

    # ------------------------------------------------------------------
    # Animation system
    # ------------------------------------------------------------------
    def _add_fx(self, kind: str, **data):
        fx = {"kind": kind, "age": 0}
        fx.update(data)
        fx.setdefault("ttl", 15)
        self._fx.append(fx)
        if not self._fx_running:
            self._fx_running = True
            self.after(FX_TICK_MS, self._fx_tick)

    def _fx_tick(self):
        if self._closing:
            return
        self.canvas.delete("fx")
        if not self._fx or self.mode not in ("play", "dying", "inventory", "shop"):
            self._fx_running = False
            self._unshake()
            return
        keep = []
        for fx in self._fx:
            fx["age"] += 1
            if fx["age"] <= fx["ttl"]:
                self._draw_fx(fx)
                keep.append(fx)
        self._fx = keep
        if self._fx:
            self.after(FX_TICK_MS, self._fx_tick)
        else:
            self._fx_running = False
            self._unshake()

    def _fx_screen_pos(self, x: int, y: int):
        cam_x, cam_y = self._cam
        ts = T.TILE_SIZE
        col, row = x - cam_x, y - cam_y
        if not (0 <= col < T.VIEWPORT_COLS and 0 <= row < T.VIEWPORT_ROWS):
            return None
        return col * ts, row * ts

    def _draw_fx(self, fx):
        ts = T.TILE_SIZE
        kind = fx["kind"]
        if kind == "fade":
            # Reveal effect after descending: black overlay thins out.
            stipples = ["", "", "gray75", "gray75", "gray50", "gray50", "gray25", "gray12"]
            idx = min(fx["age"] - 1, len(stipples) - 1)
            stipple = stipples[idx]
            w = T.VIEWPORT_COLS * ts
            h = T.VIEWPORT_ROWS * ts
            if stipple == "":
                self.canvas.create_rectangle(0, 0, w, h, fill="#000000", outline="", tags="fx")
            else:
                self.canvas.create_rectangle(0, 0, w, h, fill="#000000", outline="",
                                              stipple=stipple, tags="fx")
            return
        if kind == "shake":
            seq = fx["seq"]
            idx = fx["age"] - 1
            if idx < len(seq):
                target = seq[idx]
            else:
                target = (0, 0)
            ax, ay = self._shake_applied
            dx, dy = target[0] - ax, target[1] - ay
            if dx or dy:
                self.canvas.move("all", dx, dy)
                self._shake_applied = target
            return

        pos = self._fx_screen_pos(fx.get("x", 0), fx.get("y", 0))
        if pos is None:
            return
        sx, sy = pos
        age, ttl = fx["age"], fx["ttl"]

        if kind == "num":
            rise = age * 2
            self.canvas.create_text(sx + ts // 2, sy - 2 - rise, text=fx["text"],
                                     font=T.UI_FONT_BOLD, fill=fx["color"], tags="fx")
        elif kind == "flash":
            self.canvas.create_rectangle(sx, sy, sx + ts, sy + ts, fill=fx["color"],
                                          outline="", stipple="gray50", tags="fx")
        elif kind == "poof":
            r = 2 + age * 2
            cx, cy = sx + ts // 2, sy + ts // 2
            self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                     outline=fx["color"], width=2, tags="fx")
        elif kind == "sparkle":
            cx, cy = sx + ts // 2, sy + ts // 2
            for i in range(5):
                px = cx + ((i * 37 + age * 7) % (ts + 10)) - (ts + 10) // 2
                py = cy - age * 2 + ((i * 23) % 8)
                self.canvas.create_rectangle(px, py, px + 3, py + 3,
                                              fill="#f2c94c", outline="", tags="fx")

    def _shake(self, intensity: int):
        seq = []
        sign = 1
        for step in range(intensity, 0, -1):
            seq.append((sign * step, 0))
            sign = -sign
        seq.append((0, 0))
        self._add_fx("shake", seq=seq, ttl=len(seq))

    def _unshake(self):
        ax, ay = self._shake_applied
        if ax or ay:
            self.canvas.move("all", -ax, -ay)
            self._shake_applied = (0, 0)

    # ------------------------------------------------------------------
    # Inventory overlay
    # ------------------------------------------------------------------
    def _inventory_formatter(self, item):
        title = item.display_name() + self._equip_tag(item)
        lines = describe_item(item, self.state.player)
        lines.append(f"Sells for {sell_price(item)} gold.")
        return RARITY_COLORS.get(item.rarity, T.TEXT_MAIN), title, lines

    def _open_inventory(self):
        self.mode = "inventory"
        self.inventory_frame.place(relx=0.5, rely=0.5, anchor="center")
        self._refresh_inventory()

    def _refresh_inventory(self):
        p = self.state.player
        self._inventory_items = list(p.inventory)
        labels = [f"{item.display_name()}{self._equip_tag(item)}"
                  for item in self._inventory_items]
        self.inv_panel.set_items(self._inventory_items, labels)
        self.inventory_gold_label.configure(text=f"Gold: {p.gold}")

        def slot(eq, stat):
            return f"{eq.name} ({stat})" if eq else "(none)"
        self.inventory_equipped_label.configure(text=(
            f"Weapon: {slot(p.equipped_weapon, f'+{p.equipped_weapon.bonus_attack} atk' if p.equipped_weapon else '')}   "
            f"Armor: {slot(p.equipped_armor, f'+{p.equipped_armor.bonus_defense} def' if p.equipped_armor else '')}   "
            f"Accessory: {slot(p.equipped_accessory, f'+{p.equipped_accessory.bonus_attack}/+{p.equipped_accessory.bonus_defense}' if p.equipped_accessory else '')}"))

    def _equip_tag(self, item) -> str:
        p = self.state.player
        if item is p.equipped_weapon or item is p.equipped_armor or item is p.equipped_accessory:
            return " [equipped]"
        return ""

    def _inventory_activate(self):
        """Enter key / button: use consumables, equip gear."""
        item = self.inv_panel.selected_item()
        if item is None:
            return
        if item.category in ("potion", "scroll"):
            self._inventory_use()
        elif item.category in ("weapon", "armor", "accessory"):
            self._inventory_equip()

    def _inventory_use(self):
        item = self.inv_panel.selected_item()
        if item and item.category in ("potion", "scroll"):
            self.state.use_item(item)
            save_module.save_game(self.state)
            self._drain_events()
            self._refresh_inventory()
            self._render()
            if self.state.game_over:
                self._elapsed_at_end = time.monotonic() - self._run_started_at
                self._close_overlay()
                self.mode = "dying"
                self.after(900, self._show_victory if self.state.game_won else self._show_gameover)

    def _inventory_equip(self):
        item = self.inv_panel.selected_item()
        if item and item.category in ("weapon", "armor", "accessory"):
            self.state.equip_item(item)
            save_module.save_game(self.state)
            self._drain_events()
            self._refresh_inventory()
            self._render_panel()

    def _inventory_drop(self):
        item = self.inv_panel.selected_item()
        if item:
            self.state.drop_item(item)
            save_module.save_game(self.state)
            self._drain_events()
            self._refresh_inventory()

    def _close_overlay(self):
        self.inventory_frame.place_forget()
        if self.mode == "inventory":
            self.mode = "play"
        self._render()

    # ------------------------------------------------------------------
    # Shop overlay
    # ------------------------------------------------------------------
    def _shop_formatter(self, item):
        p = self.state.player
        lines = describe_item(item, p)
        if self._shop_tab == "buy":
            lines.append(f"Price: {item.value} gold.")
            if p.gold < item.value:
                lines.append("You can't afford this!")
        else:
            lines.append(f"Sells for {sell_price(item)} gold.")
            if self._equip_tag(item):
                lines.append("Selling will unequip it.")
        return RARITY_COLORS.get(item.rarity, T.TEXT_MAIN), item.display_name(), lines

    def _open_shop(self):
        self.mode = "shop"
        self.shop_frame.place(relx=0.5, rely=0.5, anchor="center")
        self._shop_set_tab("buy")

    def _shop_set_tab(self, tab: str):
        self._shop_tab = tab
        active = dict(bg=T.ACCENT, fg=T.BG)
        idle = dict(bg=T.BG, fg=T.TEXT_DIM)
        self.shop_buy_tab.configure(**(active if tab == "buy" else idle))
        self.shop_sell_tab.configure(**(active if tab == "sell" else idle))
        self.shop_action_button.configure(text="Buy (Enter)" if tab == "buy" else "Sell (Enter)")
        self._refresh_shop(keep_selection=False)

    def _refresh_shop(self, keep_selection: bool = True):
        p = self.state.player
        self.shop_gold_label.configure(text=f"Gold: {p.gold}")
        if self._shop_tab == "buy":
            items = list(self.state.floor.shop_stock)
            labels = [f"{i.display_name()} - {i.value}g" for i in items]
            colors = [(T.TEXT_BAD if p.gold < i.value
                        else RARITY_COLORS.get(i.rarity, T.TEXT_MAIN)) for i in items]
        else:
            items = list(p.inventory)
            labels = [f"{i.display_name()}{self._equip_tag(i)} - {sell_price(i)}g" for i in items]
            colors = None
        self.shop_panel.set_items(items, labels, colors, keep_selection=keep_selection)

    def _shop_activate(self):
        item = self.shop_panel.selected_item()
        if item is None:
            return
        if self._shop_tab == "buy":
            self.state.buy_item(item)
        else:
            self.state.sell_item(item)
        save_module.save_game(self.state)
        self._drain_events()
        self._refresh_shop()

    def _close_shop(self):
        self.state.close_shop()
        self.shop_frame.place_forget()
        self.mode = "play"
        save_module.save_game(self.state)
        self._render()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _render(self):
        self._render_canvas()
        self._render_panel()
        self._render_log()

    def _tile_sprite_key(self, tile: str, visible: bool) -> str:
        if tile == C.TILE_WALL:
            base = "wall"
        elif tile == C.TILE_STAIRS:
            base = "stairs"
        else:
            base = "floor"  # shopkeeper stands on a floor tile
        return base if visible else base + "_dim"

    def _monster_sprite_key(self, monster) -> str:
        base_name = monster.name[:-5] if monster.name.endswith(" Boss") else monster.name
        return sprite_defs.MONSTER_KEYS.get(base_name, "goblin")

    def _hero_variant_key(self) -> tuple:
        p = self.state.player
        weapon, rarity = "none", "common"
        if p.equipped_weapon:
            name = p.equipped_weapon.name.lower()
            rarity = p.equipped_weapon.rarity
            if "dagger" in name:
                weapon = "dagger"
            elif "axe" in name:
                weapon = "axe"
            elif "hammer" in name:
                weapon = "hammer"
            elif "spear" in name:
                weapon = "spear"
            else:
                weapon = "sword"
        armor = "none"
        if p.equipped_armor:
            name = p.equipped_armor.name.lower()
            if "leather" in name or "vest" in name:
                armor = "leather"
            elif "plate" in name:
                armor = "plate"
            else:
                armor = "chain"
        accessory = p.equipped_accessory is not None
        poisoned = any(e.get("type") == "poison" for e in p.status_effects)
        return (weapon, armor, accessory, poisoned, rarity)

    def _hero_sprite(self):
        key = self._hero_variant_key()
        if key not in self._hero_cache:
            weapon, armor, accessory, poisoned, rarity = key
            self._hero_cache[key] = sprite_defs.build_hero(
                weapon=weapon, armor=armor, accessory=accessory,
                poisoned=poisoned, weapon_rarity=rarity,
                zoom=T.TILE_SIZE // sprite_defs.SPRITE_PX)
        return self._hero_cache[key]

    @staticmethod
    def _decor_key(depth: int, x: int, y: int):
        h = (x * 2654435761 ^ y * 97531 ^ depth * 8191) & 0xFFFFFFFF
        if h % 13 == 0:
            return sprite_defs.DECOR_SPRITES[(h >> 8) % len(sprite_defs.DECOR_SPRITES)]
        return None

    def _render_canvas(self):
        canvas = self.canvas
        self._shake_applied = (0, 0)
        canvas.delete("all")
        floor = self.state.floor
        player = self.state.player
        ts = T.TILE_SIZE
        sprites = self.sprites

        cam_x = min(max(player.x - T.VIEWPORT_COLS // 2, 0), max(0, floor.width - T.VIEWPORT_COLS))
        cam_y = min(max(player.y - T.VIEWPORT_ROWS // 2, 0), max(0, floor.height - T.VIEWPORT_ROWS))
        self._cam = (cam_x, cam_y)

        for row in range(T.VIEWPORT_ROWS):
            fy = cam_y + row
            if fy >= floor.height:
                continue
            for col in range(T.VIEWPORT_COLS):
                fx = cam_x + col
                if fx >= floor.width:
                    continue
                if not floor.explored[fy][fx]:
                    continue
                visible = floor.visible[fy][fx]
                tile = floor.tiles[fy][fx]
                sx, sy = col * ts, row * ts
                suffix = "" if visible else "_dim"

                canvas.create_image(sx, sy, image=sprites[self._tile_sprite_key(tile, visible)],
                                     anchor="nw")

                trap = floor.trap_at(fx, fy)
                if tile == C.TILE_FLOOR and not (trap and trap.triggered):
                    decor = self._decor_key(floor.depth, fx, fy)
                    if decor:
                        canvas.create_image(sx, sy, image=sprites[decor + suffix], anchor="nw")

                if trap and trap.triggered:
                    key = sprite_defs.TRAP_KEYS[trap.kind]
                    canvas.create_image(sx, sy, image=sprites[key + suffix], anchor="nw")

                if tile == C.TILE_SHOPKEEPER and visible:
                    canvas.create_image(sx, sy, image=sprites["shopkeeper"], anchor="nw")

                if visible:
                    gi = floor.ground_item_at(fx, fy)
                    if gi:
                        key = sprite_defs.ITEM_KEYS.get(gi.item.category)
                        if key:
                            canvas.create_image(sx, sy, image=sprites[key], anchor="nw")
                        else:
                            canvas.create_text(sx + ts // 2, sy + ts // 2, text=gi.item.glyph,
                                                font=T.GLYPH_FONT, fill=gi.item.color)
                    monster = floor.monster_at(fx, fy)
                    if monster:
                        canvas.create_image(sx, sy, image=sprites[self._monster_sprite_key(monster)],
                                             anchor="nw")
                        if monster.is_boss:
                            canvas.create_image(sx, sy, image=sprites["crown"], anchor="nw")
                        if monster.hp < monster.max_hp:
                            frac = max(0.0, monster.hp / monster.max_hp)
                            bar_w = ts - 8
                            canvas.create_rectangle(sx + 4, sy + 1, sx + 4 + bar_w, sy + 4,
                                                     fill="#20141a", outline="")
                            canvas.create_rectangle(sx + 4, sy + 1, sx + 4 + int(bar_w * frac),
                                                     sy + 4, fill="#e04848", outline="")

        px, py = (player.x - cam_x) * ts, (player.y - cam_y) * ts
        canvas.create_image(px, py, image=self._hero_sprite(), anchor="nw")

    def _copy_seed(self):
        if self.state is None:
            return
        self.clipboard_clear()
        self.clipboard_append(str(self.state.seed))
        self.update()
        self.seed_label.configure(text=f"Seed: {self.state.seed} (copied!)")

    def _stopwatch_tick(self):
        if self._closing:
            return
        if (self.mode in ("play", "inventory", "shop") and self.state
                and self.state.mode == "speedrun" and not self.state.game_over):
            elapsed = time.monotonic() - self._run_started_at
            self.timer_label.configure(
                text=f"Time: {_fmt_time(elapsed)}  (goal: floor {self.state.target_floor})")
        self.after(300, self._stopwatch_tick)

    def _render_panel(self):
        p = self.state.player
        self.depth_label.configure(text=f"Depth: {self.state.depth}")
        self.seed_label.configure(text=f"Seed: {self.state.seed} (click to copy)")
        if self.state.mode != "speedrun":
            self.timer_label.configure(text="")
        self.level_label.configure(text=f"Level: {p.level}   XP: {p.xp}/{p.xp_to_next}")
        self._draw_bar(self.hp_bar, p.hp / max(1, p.max_hp), "#e05656",
                        "#3a2020", f"HP  {p.hp}/{p.max_hp}")
        self._draw_bar(self.xp_bar, p.xp / max(1, p.xp_to_next), "#66d9ef", "#20303a", "")

        poison = next((e for e in p.status_effects if e.get("type") == "poison"), None)
        if poison:
            self.status_label.configure(text=f"Status: Poisoned ({poison['turns']})", fg="#58c058")
        else:
            self.status_label.configure(text="Status: Healthy", fg=T.TEXT_DIM)

        self.attack_label.configure(text=f"Attack: {p.attack_power}")
        self.defense_label.configure(text=f"Defense: {p.defense_power}")
        self.gold_label.configure(text=f"Gold: {p.gold}")
        self.weapon_label.configure(
            text=f"Weapon: {p.equipped_weapon.name if p.equipped_weapon else '(none)'}")
        self.armor_label.configure(
            text=f"Armor: {p.equipped_armor.name if p.equipped_armor else '(none)'}")
        self.accessory_label.configure(
            text=f"Accessory: {p.equipped_accessory.name if p.equipped_accessory else '(none)'}")
        self.kills_label.configure(text=f"Kills: {p.kills}    Turns: {p.turns}")
        self._render_minimap()

    def _render_minimap(self):
        mm = self.minimap
        mm.delete("all")
        floor = self.state.floor
        scale = 3
        ox = (240 - floor.width * scale) // 2
        oy = (80 - floor.height * scale) // 2
        for y in range(floor.height):
            for x in range(floor.width):
                if not floor.explored[y][x]:
                    continue
                tile = floor.tiles[y][x]
                if tile == C.TILE_WALL:
                    color = "#2a2a33"
                elif tile == C.TILE_STAIRS:
                    color = "#66d9ef"
                elif tile == C.TILE_SHOPKEEPER:
                    color = "#f2c94c"
                else:
                    color = "#4a4a58"
                mm.create_rectangle(ox + x * scale, oy + y * scale,
                                     ox + x * scale + scale, oy + y * scale + scale,
                                     fill=color, outline="")
        p = self.state.player
        mm.create_rectangle(ox + p.x * scale - 1, oy + p.y * scale - 1,
                             ox + p.x * scale + scale + 1, oy + p.y * scale + scale + 1,
                             fill="#ffe45e", outline="")

    def _draw_bar(self, bar_canvas: tk.Canvas, fraction: float, fg: str, bg: str, label: str):
        bar_canvas.delete("all")
        w = int(bar_canvas["width"])
        h = int(bar_canvas["height"])
        fraction = max(0.0, min(1.0, fraction))
        bar_canvas.create_rectangle(0, 0, w, h, fill=bg, outline="")
        bar_canvas.create_rectangle(0, 0, int(w * fraction), h, fill=fg, outline="")
        if label:
            bar_canvas.create_text(w // 2, h // 2, text=label, font=("Courier", 9, "bold"),
                                    fill=T.TEXT_MAIN)

    def _render_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        for line in self.state.log[-12:]:
            self.log_text.insert(tk.END, line + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")
