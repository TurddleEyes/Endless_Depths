"""Procedural dungeon (single-floor) generation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import constants as C
from .entities import Monster, generate_monster
from .items import Item, generate_item


@dataclass
class Room:
    x: int
    y: int
    w: int
    h: int

    @property
    def center(self):
        return self.x + self.w // 2, self.y + self.h // 2

    def intersects(self, other: "Room", padding: int = 1) -> bool:
        return (
            self.x - padding < other.x + other.w
            and self.x + self.w + padding > other.x
            and self.y - padding < other.y + other.h
            and self.y + self.h + padding > other.y
        )


@dataclass
class GroundItem:
    x: int
    y: int
    item: Item


@dataclass
class Trap:
    x: int
    y: int
    kind: str  # spike, poison, teleport
    triggered: bool = False


@dataclass
class Floor:
    depth: int
    width: int
    height: int
    tiles: list  # list[list[str]] rows of chars
    rooms: list
    stairs_pos: tuple
    monsters: list = field(default_factory=list)
    ground_items: list = field(default_factory=list)
    traps: list = field(default_factory=list)
    shop_pos: Optional[tuple] = None
    shop_stock: list = field(default_factory=list)
    explored: list = field(default_factory=list)
    visible: list = field(default_factory=list)

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def is_walkable(self, x: int, y: int) -> bool:
        # The shopkeeper's tile is not walkable: the player opens the shop by
        # bumping into it (handled before this check), and monsters/pathing
        # must route around it rather than standing on the shopkeeper.
        return self.in_bounds(x, y) and self.tiles[y][x] not in (C.TILE_WALL, C.TILE_SHOPKEEPER)

    def monster_at(self, x: int, y: int) -> Optional[Monster]:
        for m in self.monsters:
            if m.x == x and m.y == y and m.is_alive():
                return m
        return None

    def ground_item_at(self, x: int, y: int) -> Optional[GroundItem]:
        for gi in self.ground_items:
            if gi.x == x and gi.y == y:
                return gi
        return None

    def trap_at(self, x: int, y: int) -> Optional[Trap]:
        for t in self.traps:
            if t.x == x and t.y == y:
                return t
        return None


def _carve_room(tiles, room: Room):
    for yy in range(room.y, room.y + room.h):
        for xx in range(room.x, room.x + room.w):
            tiles[yy][xx] = C.TILE_FLOOR


def _carve_corridor(tiles, x1, y1, x2, y2, rng):
    if rng.random() < 0.5:
        _carve_h(tiles, x1, x2, y1)
        _carve_v(tiles, y1, y2, x2)
    else:
        _carve_v(tiles, y1, y2, x1)
        _carve_h(tiles, x1, x2, y2)


def _carve_h(tiles, x1, x2, y):
    for x in range(min(x1, x2), max(x1, x2) + 1):
        tiles[y][x] = C.TILE_FLOOR


def _carve_v(tiles, y1, y2, x):
    for y in range(min(y1, y2), max(y1, y2) + 1):
        tiles[y][x] = C.TILE_FLOOR


def _generate_rooms(rng) -> tuple:
    width, height = C.MAP_WIDTH, C.MAP_HEIGHT
    tiles = [[C.TILE_WALL for _ in range(width)] for _ in range(height)]
    rooms: list[Room] = []
    n_rooms = rng.randint(C.MIN_ROOMS, C.MAX_ROOMS)

    attempts = 0
    while len(rooms) < n_rooms and attempts < n_rooms * 20:
        attempts += 1
        w = rng.randint(C.MIN_ROOM_SIZE, C.MAX_ROOM_SIZE)
        h = rng.randint(C.MIN_ROOM_SIZE, C.MAX_ROOM_SIZE)
        x = rng.randint(1, width - w - 2)
        y = rng.randint(1, height - h - 2)
        room = Room(x, y, w, h)
        if any(room.intersects(r) for r in rooms):
            continue
        _carve_room(tiles, room)
        if rooms:
            px, py = rooms[-1].center
            cx, cy = room.center
            _carve_corridor(tiles, px, py, cx, cy, rng)
        rooms.append(room)

    return tiles, rooms


def generate_floor(depth: int, rng) -> Floor:
    tiles, rooms = _generate_rooms(rng)
    width, height = C.MAP_WIDTH, C.MAP_HEIGHT

    start_room = rooms[0]
    stairs_room = rooms[-1] if len(rooms) > 1 else rooms[0]
    stairs_pos = stairs_room.center
    tiles[stairs_pos[1]][stairs_pos[0]] = C.TILE_STAIRS

    shop_pos = None
    shop_stock = []
    has_shop = depth % C.SHOP_INTERVAL == 0 and len(rooms) > 2
    usable_rooms = [r for r in rooms if r is not start_room and r is not stairs_room]

    if has_shop and usable_rooms:
        shop_room = rng.choice(usable_rooms)
        usable_rooms.remove(shop_room)
        shop_pos = shop_room.center
        tiles[shop_pos[1]][shop_pos[0]] = C.TILE_SHOPKEEPER
        from .shop import generate_shop_inventory
        shop_stock = generate_shop_inventory(depth, rng)

    monsters = []
    is_boss_floor = depth % C.BOSS_INTERVAL == 0
    monster_rooms = usable_rooms or [r for r in rooms if r is not start_room]
    n_monsters = min(len(monster_rooms) + rng.randint(0, 2), max(1, 2 + depth // 2))
    n_monsters = min(n_monsters, 10)

    occupied = set()
    for i in range(n_monsters):
        room = rng.choice(monster_rooms) if monster_rooms else start_room
        for _ in range(10):
            mx = rng.randint(room.x, room.x + room.w - 1)
            my = rng.randint(room.y, room.y + room.h - 1)
            if tiles[my][mx] == C.TILE_FLOOR and (mx, my) not in occupied and (mx, my) != start_room.center:
                occupied.add((mx, my))
                force_boss = is_boss_floor and i == 0
                monsters.append(generate_monster(depth, rng, mx, my, force_boss=force_boss))
                break

    ground_items = []
    n_items = rng.randint(2, 4) + depth // 4
    n_items = min(n_items, 8)
    for _ in range(n_items):
        room = rng.choice(rooms)
        for _ in range(10):
            ix = rng.randint(room.x, room.x + room.w - 1)
            iy = rng.randint(room.y, room.y + room.h - 1)
            if tiles[iy][ix] == C.TILE_FLOOR and (ix, iy) not in occupied and (ix, iy) != start_room.center:
                occupied.add((ix, iy))
                ground_items.append(GroundItem(ix, iy, generate_item(depth, rng)))
                break

    traps = []
    start_center = start_room.center
    n_traps = min(rng.randint(0, 2) + depth // 5, 5)
    trap_kinds = ["spike", "spike", "spike", "poison", "poison", "teleport"]
    for _ in range(n_traps):
        room = rng.choice(rooms)
        for _ in range(10):
            tx = rng.randint(room.x, room.x + room.w - 1)
            ty = rng.randint(room.y, room.y + room.h - 1)
            if tiles[ty][tx] == C.TILE_FLOOR and (tx, ty) not in occupied and (tx, ty) != start_center:
                occupied.add((tx, ty))
                traps.append(Trap(tx, ty, rng.choice(trap_kinds)))
                break

    explored = [[False] * width for _ in range(height)]
    visible = [[False] * width for _ in range(height)]

    return Floor(
        depth=depth,
        width=width,
        height=height,
        tiles=tiles,
        rooms=rooms,
        stairs_pos=stairs_pos,
        monsters=monsters,
        ground_items=ground_items,
        traps=traps,
        shop_pos=shop_pos,
        shop_stock=shop_stock,
        explored=explored,
        visible=visible,
    )


def start_position(floor: Floor) -> tuple:
    return floor.rooms[0].center
