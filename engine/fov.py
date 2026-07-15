"""Field-of-view / fog-of-war via per-tile Bresenham line-of-sight."""
from __future__ import annotations

from . import constants as C


def _line(x0, y0, x1, y1):
    points = []
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    x, y = x0, y0
    while True:
        points.append((x, y))
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy
    return points


def compute_fov(floor, px: int, py: int, radius: int = C.FOV_RADIUS):
    """Update floor.visible in place and OR it into floor.explored."""
    for row in floor.visible:
        for i in range(len(row)):
            row[i] = False

    floor.visible[py][px] = True
    floor.explored[py][px] = True

    for y in range(max(0, py - radius), min(floor.height, py + radius + 1)):
        for x in range(max(0, px - radius), min(floor.width, px + radius + 1)):
            if (x - px) ** 2 + (y - py) ** 2 > radius * radius:
                continue
            blocked = False
            for lx, ly in _line(px, py, x, y):
                if (lx, ly) == (px, py):
                    continue
                floor.visible[ly][lx] = True
                floor.explored[ly][lx] = True
                if floor.tiles[ly][lx] == C.TILE_WALL:
                    blocked = True
                    break
            if blocked:
                continue
