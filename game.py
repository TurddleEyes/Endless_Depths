"""Entry point for Endless Depths - an infinite dungeon roguelike.

Run with:
    python3 game.py
"""
from ui.app import App


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
