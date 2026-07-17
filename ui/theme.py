"""Pure presentation constants for the tkinter UI - no widgets created here."""

TILE_SIZE = 32          # must be a multiple of sprites.SPRITE_PX (16)
VIEWPORT_COLS = 26
VIEWPORT_ROWS = 16

FONT_FAMILY = "Courier"
GLYPH_FONT = (FONT_FAMILY, 13, "bold")
UI_FONT = (FONT_FAMILY, 11)
UI_FONT_BOLD = (FONT_FAMILY, 12, "bold")
TITLE_FONT = (FONT_FAMILY, 28, "bold")
HEADER_FONT = (FONT_FAMILY, 15, "bold")

BG = "#111114"
PANEL_BG = "#1b1b21"
PANEL_BORDER = "#3a3a45"
TEXT_MAIN = "#e6e6e6"
TEXT_DIM = "#8a8a95"
TEXT_GOOD = "#5fe07f"
TEXT_WARN = "#e0c85f"
TEXT_BAD = "#e05f5f"
ACCENT = "#66d9ef"
# A softer selection highlight for scrollable lists - the full-saturation
# ACCENT block with near-black text reads harsh over long browsing sessions;
# this keeps the same hue but as a muted fill with normal readable text.
SELECT_BG = "#1f3844"
SELECT_FG = TEXT_MAIN

HP_BAR_BG = "#3a2020"
HP_BAR_FG = "#e05656"
XP_BAR_BG = "#20303a"
XP_BAR_FG = "#66d9ef"

PLAYER_GLYPH = "@"
STAIRS_GLYPH = ">"
SHOPKEEPER_GLYPH = "$"
