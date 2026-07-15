"""Reusable UI building blocks for overlays."""
from __future__ import annotations

import tkinter as tk

from . import theme as T
from .iteminfo import RARITY_COLORS


class ItemListPanel(tk.Frame):
    """A scrollable item list next to a live details pane.

    `formatter(item)` must return (title_color, title, detail_lines).
    Selection changes (mouse or the move_selection/select_index API used by
    keyboard navigation) refresh the details pane automatically.
    """

    def __init__(self, master, formatter, rows: int = 12, list_width: int = 30,
                  details_width_px: int = 250, on_activate=None):
        super().__init__(master, bg=T.PANEL_BG)
        self.formatter = formatter
        self.on_activate = on_activate  # called with the item on double-click
        self.entries: list = []

        left = tk.Frame(self, bg=T.PANEL_BG)
        left.pack(side="left", padx=(0, 10), fill="y")
        self.listbox = tk.Listbox(left, width=list_width, height=rows, font=T.UI_FONT,
                                    bg=T.BG, fg=T.TEXT_MAIN,
                                    selectbackground=T.ACCENT,
                                    selectforeground=T.BG, bd=0,
                                    highlightthickness=1,
                                    highlightbackground=T.PANEL_BORDER,
                                    activestyle="none")
        self.listbox.pack(fill="y", expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self.refresh_details())
        self.listbox.bind("<Double-Button-1>", self._on_double_click)

        right = tk.Frame(self, bg=T.BG, highlightthickness=1,
                          highlightbackground=T.PANEL_BORDER)
        right.pack(side="left", fill="both", expand=True)
        self.name_label = tk.Label(right, text="", font=T.UI_FONT_BOLD, bg=T.BG,
                                     fg=T.TEXT_MAIN, anchor="w", justify="left",
                                     wraplength=details_width_px)
        self.name_label.pack(anchor="w", padx=10, pady=(10, 4))
        self.body_label = tk.Label(right, text="", font=T.UI_FONT, bg=T.BG,
                                     fg=T.TEXT_MAIN, anchor="nw", justify="left",
                                     wraplength=details_width_px, height=rows)
        self.body_label.pack(anchor="nw", padx=10, pady=(0, 10), fill="both", expand=True)

    # -- content ---------------------------------------------------------
    def set_items(self, items: list, labels: list = None, colors: list = None,
                   keep_selection: bool = True):
        old = self.selected_index()
        self.entries = list(items)
        self.listbox.delete(0, tk.END)
        for i, item in enumerate(self.entries):
            self.listbox.insert(tk.END, labels[i] if labels else item.display_name())
            color = (colors[i] if colors else None) or RARITY_COLORS.get(
                getattr(item, "rarity", None), T.TEXT_MAIN)
            try:
                self.listbox.itemconfig(i, foreground=color)
            except tk.TclError:
                pass
        if self.entries:
            idx = old if (keep_selection and old is not None) else 0
            self.select_index(min(idx, len(self.entries) - 1))
        else:
            self.refresh_details()

    # -- selection ---------------------------------------------------------
    def selected_index(self):
        sel = self.listbox.curselection()
        return sel[0] if sel else None

    def selected_item(self):
        idx = self.selected_index()
        if idx is None or idx >= len(self.entries):
            return None
        return self.entries[idx]

    def select_index(self, idx: int):
        if not self.entries:
            return
        idx = max(0, min(idx, len(self.entries) - 1))
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(idx)
        self.listbox.see(idx)
        self.refresh_details()

    def move_selection(self, delta: int):
        if not self.entries:
            return
        cur = self.selected_index()
        cur = 0 if cur is None else cur
        self.select_index((cur + delta) % len(self.entries))

    def _on_double_click(self, _event):
        self.refresh_details()  # ensure details match the clicked row
        item = self.selected_item()
        if item is not None and self.on_activate:
            self.on_activate(item)

    # -- details ---------------------------------------------------------
    def refresh_details(self):
        item = self.selected_item()
        if item is None:
            self.name_label.configure(text="Nothing here", fg=T.TEXT_DIM)
            self.body_label.configure(text="")
            return
        color, title, lines = self.formatter(item)
        self.name_label.configure(text=title, fg=color)
        self.body_label.configure(text="\n".join(lines))
