"""The turn-based game engine: ties dungeon, entities, items and combat
together into a single playable, headless GameState. No UI imports here -
this module can be driven entirely from a script or unit test.

Besides the human-readable message log, the engine emits structured events
(dicts with a "type" key) that a presentation layer can drain via
take_events() to drive sounds and animations. The engine itself never
depends on anyone consuming them.
"""
from __future__ import annotations

import random
from collections import deque

from . import constants as C
from .combat import resolve_attack
from .dungeon import generate_floor, start_position
from .entities import Player
from .fov import compute_fov
from .items import use_item as apply_item_effect
from . import shop as shop_module

MAX_EVENTS = 200


def _bfs_next_step(floor, start, goal, blocked):
    if start == goal:
        return None
    came_from = {start: None}
    queue = deque([start])
    while queue:
        cur = queue.popleft()
        if cur == goal:
            break
        cx, cy = cur
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (cx + dx, cy + dy)
            if nxt in came_from:
                continue
            if not floor.is_walkable(*nxt):
                continue
            if nxt in blocked and nxt != goal:
                continue
            came_from[nxt] = cur
            queue.append(nxt)
    if goal not in came_from:
        return None
    step = goal
    while came_from[step] != start:
        step = came_from[step]
        if step is None:
            return None
    return step


class GameState:
    def __init__(self, seed=None, mode="normal", target_floor=None):
        if seed is None:
            # Mint a concrete, displayable seed. SystemRandom is used ONLY
            # here - all gameplay randomness flows through self.rng, so a
            # run is fully reproducible from (seed, action_log).
            seed = random.SystemRandom().randrange(1, 2**31 - 1)
        self.seed = int(seed)
        self.rng = random.Random(self.seed)
        self.mode = mode  # "normal" | "speedrun"
        self.target_floor = target_floor or C.SPEEDRUN_TARGET_FLOOR
        self.game_won = False
        # False only for states rebuilt via from_dict() - those regenerate
        # their floor with a fresh RNG, so they can never replay faithfully.
        self.replayable = True
        self.action_log: list = []  # full history, never trimmed
        self.player = Player()
        self.depth = 0
        self.floor = None
        self.log: list = []
        self.events: list = []
        self.game_over = False
        self.pending_shop = False

    def _record(self, code: str, *params):
        self.action_log.append([code, *params] if params else [code])

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    def new_game(self):
        self.depth = 1
        self._enter_floor(regenerate=True)
        self._log("You descend into the dungeon.")
        self._log(f"-- Floor {self.depth} --")

    def _enter_floor(self, regenerate: bool):
        if regenerate:
            self.floor = generate_floor(self.depth, self.rng)
        sx, sy = start_position(self.floor)
        self.player.x, self.player.y = sx, sy
        compute_fov(self.floor, sx, sy)

    def _log(self, message: str):
        self.log.append(message)
        if len(self.log) > C.MAX_LOG_LINES:
            self.log = self.log[-C.MAX_LOG_LINES:]

    def _emit(self, etype: str, **data):
        self.events.append({"type": etype, **data})
        if len(self.events) > MAX_EVENTS:
            self.events = self.events[-MAX_EVENTS:]

    def take_events(self) -> list:
        events, self.events = self.events, []
        return events

    # ------------------------------------------------------------------
    # Player actions
    # ------------------------------------------------------------------
    def try_move_player(self, dx: int, dy: int):
        self._record("m", dx, dy)
        if self.game_over or self.pending_shop:
            return
        floor = self.floor
        nx, ny = self.player.x + dx, self.player.y + dy
        if not floor.in_bounds(nx, ny):
            return

        if floor.shop_pos == (nx, ny):
            self.pending_shop = True
            return

        monster = floor.monster_at(nx, ny)
        if monster:
            self._player_attack(monster)
            self._end_turn()
            return

        if not floor.is_walkable(nx, ny):
            return

        self.player.x, self.player.y = nx, ny
        compute_fov(floor, nx, ny)
        self._emit("step")

        trap = floor.trap_at(nx, ny)
        if trap and not trap.triggered:
            trap.triggered = True
            self._trigger_trap(trap)
            if self.game_over:
                return
            if trap.kind == "teleport":
                self._end_turn()
                return

        self._pickup_at(self.player.x, self.player.y)

        if floor.stairs_pos == (self.player.x, self.player.y):
            self._descend()
            return

        self._end_turn()

    def wait(self):
        """Pass a turn without moving."""
        self._record("w")
        if self.game_over or self.pending_shop:
            return
        self._end_turn()

    def _trigger_trap(self, trap):
        if trap.kind == "spike":
            damage = max(1, round(3 + self.depth * 1.1) - self.player.defense_power // 2)
            self.player.hp -= damage
            self._log(f"Spikes shoot up from the floor! You take {damage} damage.")
            self._emit("trap", kind="spike", x=trap.x, y=trap.y, dmg=damage)
            if self.player.hp <= 0:
                self._die()
        elif trap.kind == "poison":
            self._apply_poison(dmg=max(1, 1 + self.depth // 6))
            self._log("A cloud of toxic gas bursts from a hidden vent!")
            self._emit("trap", kind="poison", x=trap.x, y=trap.y)
        elif trap.kind == "teleport":
            self._log("A rune flares beneath your feet - the world lurches!")
            self._emit("trap", kind="teleport", x=trap.x, y=trap.y)
            self._teleport_player()
            self._emit("teleport")

    def _apply_poison(self, dmg: int):
        # Poison never wears off on its own - only a Potion of Cure (or
        # dying) ends it. Re-poisoning just keeps the strongest dose.
        for eff in self.player.status_effects:
            if eff.get("type") == "poison":
                eff["dmg"] = max(eff["dmg"], dmg)
                return
        self.player.status_effects.append({"type": "poison", "dmg": dmg})
        self._emit("poisoned")

    def _pickup_at(self, x: int, y: int):
        gi = self.floor.ground_item_at(x, y)
        if not gi:
            return
        item = gi.item
        self.floor.ground_items.remove(gi)
        if item.category == "gold":
            self.player.gold += item.quantity
            self._log(f"You pick up {item.quantity} gold.")
            self._emit("gold")
        else:
            self.player.inventory.append(item)
            self._log(f"You pick up {item.display_name()}.")
            self._emit("pickup")

    def _player_attack(self, monster):
        damage, crit, msg = resolve_attack(
            "You", monster.name, self.player.attack_power, monster.defense, self.rng
        )
        monster.hp -= damage
        self._log(msg)
        self._emit("hit", x=monster.x, y=monster.y, dmg=damage, crit=crit)
        if not monster.is_alive():
            self._kill_monster(monster)

    def _kill_monster(self, monster):
        if monster in self.floor.monsters:
            self.floor.monsters.remove(monster)
        self.player.kills += 1
        self._log(f"You defeated the {monster.name}! (+{monster.xp_reward} XP, +{monster.gold_reward} gold)")
        self.player.gold += monster.gold_reward
        self._emit("kill", x=monster.x, y=monster.y, boss=monster.is_boss)
        levelup_msgs = self.player.gain_xp(monster.xp_reward)
        for m in levelup_msgs:
            self._log(m)
        if levelup_msgs:
            self._emit("levelup")

    def _descend(self):
        self.depth += 1
        self._enter_floor(regenerate=True)
        self._log(f"You descend the stairs...")
        self._log(f"-- Floor {self.depth} --")
        boss_floor = any(m.is_boss for m in self.floor.monsters)
        self._emit("descend", boss_floor=boss_floor)
        if boss_floor:
            self._log("A terrible presence stirs on this floor...")
        if self.mode == "speedrun" and self.depth >= self.target_floor and not self.game_over:
            # Victory reuses game_over as the "run has ended, stop accepting
            # input" flag; game_won distinguishes escape from death.
            self.game_won = True
            self.game_over = True
            self._log(f"You reach floor {self.target_floor} and escape the depths with your life!")
            self._emit("victory")

    def _die(self):
        self.player.hp = 0
        self.game_over = True
        self._log("You have died...")
        self._emit("player_death")

    def use_item(self, item):
        if item not in self.player.inventory or self.game_over:
            return
        # Replays reference items by list index (item.id is a process-global
        # counter and not reproducible across runs).
        self._record("u", self.player.inventory.index(item))
        msg = apply_item_effect(self.player, item)
        if msg == "__TELEPORT__":
            self._teleport_player()
            msg = "Reality twists - you are teleported elsewhere on the floor."
            self._emit("teleport")
        elif msg == "__FIREBALL__":
            hits = 0
            for m in list(self.floor.monsters):
                if self.floor.visible[m.y][m.x] and m.is_alive():
                    dmg = max(1, item.magnitude)
                    m.hp -= dmg
                    hits += 1
                    self._emit("hit", x=m.x, y=m.y, dmg=dmg, crit=True)
                    if not m.is_alive():
                        self._kill_monster(m)
            self._emit("fireball")
            if hits:
                msg = f"The scroll erupts in flame, searing {hits} foe{'s' if hits != 1 else ''}!"
            else:
                msg = "The scroll erupts in flame, but nothing is close enough to burn."
        elif item.category == "potion":
            self._emit({"heal": "potion", "strength": "strength",
                        "cure": "cure"}.get(item.effect, "potion"))
        elif item.category == "scroll":
            self._emit("enchant" if item.effect == "enchant" else "scroll")
        self._log(msg)
        if item.category in ("potion", "scroll"):
            self.player.inventory.remove(item)
        self._end_turn()

    def equip_item(self, item):
        if item not in self.player.inventory:
            return
        self._record("e", self.player.inventory.index(item))
        self._log(self.player.equip(item))
        self._emit("equip")

    def drop_item(self, item):
        if item not in self.player.inventory:
            return
        self._record("d", self.player.inventory.index(item))
        if self.player.equipped_weapon is item:
            self.player.equipped_weapon = None
        if self.player.equipped_armor is item:
            self.player.equipped_armor = None
        if self.player.equipped_accessory is item:
            self.player.equipped_accessory = None
        self.player.inventory.remove(item)
        self._log(f"You drop the {item.name}.")
        self._emit("drop")

    def _teleport_player(self):
        floor = self.floor
        candidates = [
            (x, y)
            for y in range(floor.height)
            for x in range(floor.width)
            if floor.is_walkable(x, y) and floor.monster_at(x, y) is None
        ]
        x, y = self.rng.choice(candidates)
        self.player.x, self.player.y = x, y
        compute_fov(floor, x, y)

    # ------------------------------------------------------------------
    # Shop
    # ------------------------------------------------------------------
    def buy_item(self, item):
        if item in self.floor.shop_stock:
            # Record even if the purchase then fails (e.g. not enough gold):
            # the failure is deterministic, so replay fails identically.
            self._record("b", self.floor.shop_stock.index(item))
        ok, msg = shop_module.buy(self.player, self.floor.shop_stock, item)
        self._log(msg)
        if ok:
            self._emit("buy")

    def sell_item(self, item):
        if item in self.player.inventory:
            self._record("s", self.player.inventory.index(item))
        ok, msg = shop_module.sell(self.player, item)
        self._log(msg)
        if ok:
            self._emit("sell")

    def close_shop(self):
        self._record("c")
        self.pending_shop = False

    # ------------------------------------------------------------------
    # Turn resolution
    # ------------------------------------------------------------------
    def _end_turn(self):
        self.player.turns += 1
        self._tick_status_effects()
        if self.game_over:
            return
        self._process_monsters()

    def _tick_status_effects(self):
        for eff in list(self.player.status_effects):
            if eff.get("type") == "poison":
                # Ticks every other turn: poison is permanent until cured,
                # so the drain is slow enough to actually reach a shop.
                if self.player.turns % 2 == 0:
                    continue
                # Poison grinds you down to death's door but never lands the
                # killing blow itself - monsters will happily finish the job.
                # Permanent-until-cured poison would otherwise be a
                # guaranteed death sentence before the first shop.
                if self.player.hp > 1:
                    dealt = min(eff["dmg"], self.player.hp - 1)
                    self.player.hp -= dealt
                    self._log(f"Poison courses through you ({dealt} damage).")
                    self._emit("poison_tick", dmg=dealt)
                    if self.player.hp == 1:
                        self._log("The poison leaves you clinging to life - find a cure!")

    def _process_monsters(self):
        floor = self.floor
        player = self.player
        occupied = {(m.x, m.y) for m in floor.monsters if m.is_alive()}
        for m in list(floor.monsters):
            if not m.is_alive():
                continue
            dist = abs(m.x - player.x) + abs(m.y - player.y)
            if floor.visible[m.y][m.x] or dist <= 1:
                m.state = "chasing"

            if m.state != "chasing":
                if self.rng.random() < 0.3:
                    self._wander(m, occupied)
                continue

            if dist <= 1:
                damage, crit, msg = resolve_attack(
                    m.name, "you", m.attack, player.defense_power, self.rng
                )
                player.hp -= damage
                self._log(msg)
                self._emit("player_hit", dmg=damage, crit=crit)
                if "Spider" in m.name and self.rng.random() < 0.2:
                    self._apply_poison(dmg=max(1, 1 + self.depth // 8))
                    self._log("The spider's venom seeps into the wound!")
                if player.hp <= 0:
                    self._die()
                    return
                continue

            occupied.discard((m.x, m.y))
            step = _bfs_next_step(floor, (m.x, m.y), (player.x, player.y), occupied)
            if step:
                m.x, m.y = step
            occupied.add((m.x, m.y))

    def _wander(self, monster, occupied):
        floor = self.floor
        options = []
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = monster.x + dx, monster.y + dy
            if floor.is_walkable(nx, ny) and (nx, ny) not in occupied:
                options.append((nx, ny))
        if options:
            occupied.discard((monster.x, monster.y))
            monster.x, monster.y = self.rng.choice(options)
            occupied.add((monster.x, monster.y))

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "player": self.player.to_dict(),
            "depth": self.depth,
            "log": self.log[-30:],
        }

    @staticmethod
    def from_dict(data: dict) -> "GameState":
        state = GameState()
        state.player = Player.from_dict(data["player"])
        state.depth = data["depth"]
        state._enter_floor(regenerate=True)
        state.log = list(data.get("log", []))
        # The floor was regenerated with a fresh RNG, so this run can no
        # longer be reproduced from a seed - replay saving is disabled.
        state.replayable = False
        state._log(f"-- Welcome back. Resuming on floor {state.depth}. --")
        return state
