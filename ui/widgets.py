"""Reusable UI building blocks for overlays."""
from __future__ import annotations

import tkinter as tk

from . import theme as T
from .iteminfo import RARITY_COLORS, category_label


class ItemListPanel(tk.Frame):
    """A scrollable item list next to a live details pane.

    `formatter(item)` must return (title_color, title, detail_lines).
    Selection changes (mouse or the move_selection/select_index API used by
    keyboard navigation) refresh the details pane automatically.

    Pass `categories` to set_items to render non-selectable category header
    rows above each run of same-category items (the caller is expected to
    have already grouped/sorted `items` accordingly, e.g. via
    iteminfo.sort_items - this widget just draws the dividers). Header rows
    exist in the underlying Listbox but never become the selection: mouse
    clicks on one redirect to the nearest real row, and keyboard navigation
    (move_selection) only ever walks entry indices, which skip headers by
    construction.
    """

    def __init__(self, master, formatter, rows: int = 12, list_width: int = 30,
                  details_width_px: int = 250, on_activate=None):
        super().__init__(master, bg=T.PANEL_BG)
        self.formatter = formatter
        self.on_activate = on_activate  # called with the item on double-click
        self.entries: list = []
        self._entry_to_row: list = []   # entries index -> listbox row
        self._row_to_entry: list = []   # listbox row -> entries index, or None (header)

        left = tk.Frame(self, bg=T.PANEL_BG)
        left.pack(side="left", padx=(0, 10), fill="y")
        self.listbox = tk.Listbox(left, width=list_width, height=rows, font=T.UI_FONT,
                                    bg=T.BG, fg=T.TEXT_MAIN,
                                    selectbackground=T.SELECT_BG,
                                    selectforeground=T.SELECT_FG, bd=0,
                                    highlightthickness=1,
                                    highlightbackground=T.PANEL_BORDER,
                                    activestyle="none")
        self.listbox.pack(fill="y", expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self.refresh_details())
        self.listbox.bind("<Button-1>", self._on_click)
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
                   categories: list = None, keep_selection: bool = True):
        old_item = self.selected_item() if keep_selection else None
        self.entries = list(items)
        self.listbox.delete(0, tk.END)
        self._entry_to_row = []
        self._row_to_entry = []
        last_cat = object()  # sentinel that can't equal any real category
        for i, item in enumerate(self.entries):
            cat = categories[i] if categories else None
            if categories and cat != last_cat:
                last_cat = cat
                self.listbox.insert(tk.END, f"── {category_label(cat).upper()} ──")
                header_row = self.listbox.size() - 1
                self.listbox.itemconfig(header_row, foreground=T.TEXT_DIM,
                                          selectbackground=T.PANEL_BG,
                                          selectforeground=T.TEXT_DIM)
                self._row_to_entry.append(None)
            self.listbox.insert(tk.END, labels[i] if labels else item.display_name())
            row = self.listbox.size() - 1
            color = (colors[i] if colors else None) or RARITY_COLORS.get(
                getattr(item, "rarity", None), T.TEXT_MAIN)
            try:
                self.listbox.itemconfig(row, foreground=color)
            except tk.TclError:
                pass
            self._entry_to_row.append(row)
            self._row_to_entry.append(i)
        if self.entries:
            idx = 0
            if old_item is not None:
                for i, it in enumerate(self.entries):
                    if it is old_item:
                        idx = i
                        break
            self.select_index(idx)
        else:
            self.refresh_details()

    # -- selection ---------------------------------------------------------
    def selected_index(self):
        sel = self.listbox.curselection()
        if not sel or sel[0] >= len(self._row_to_entry):
            return None
        return self._row_to_entry[sel[0]]

    def selected_item(self):
        idx = self.selected_index()
        if idx is None or idx >= len(self.entries):
            return None
        return self.entries[idx]

    def select_index(self, idx: int):
        if not self.entries:
            return
        idx = max(0, min(idx, len(self.entries) - 1))
        row = self._entry_to_row[idx]
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(row)
        self.listbox.see(row)
        self.refresh_details()

    def move_selection(self, delta: int):
        if not self.entries:
            return
        cur = self.selected_index()
        cur = 0 if cur is None else cur
        self.select_index((cur + delta) % len(self.entries))

    def _on_click(self, event):
        """Redirect clicks on a (non-selectable) category header to the
        nearest real row, instead of leaving the list with no selection."""
        row = self.listbox.nearest(event.y)
        if row >= len(self._row_to_entry) or self._row_to_entry[row] is not None:
            return  # a real item row - let the default click-to-select run
        nxt = next((r for r in range(row + 1, self.listbox.size())
                    if self._row_to_entry[r] is not None), None)
        prv = next((r for r in range(row - 1, -1, -1)
                    if self._row_to_entry[r] is not None), None)
        target = nxt if nxt is not None else prv
        if target is not None:
            self.select_index(self._row_to_entry[target])
        return "break"

    def _on_double_click(self, event):
        row = self.listbox.nearest(event.y)
        if row < len(self._row_to_entry) and self._row_to_entry[row] is None:
            return  # header row - not activatable
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
