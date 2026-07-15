"""Headless test of the browser bridge (web/webbridge.py) - the exact code
Pyodide runs, driven locally without a browser. Run with:
    python3 scripts/web_smoke_test.py
"""
import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web"))

import webbridge  # noqa: E402


def test_no_tkinter():
    assert "tkinter" not in sys.modules, "web bridge must never touch tkinter"
    print("OK: bridge import chain is tkinter-free")


def test_atlas():
    atlas = json.loads(webbridge.sprite_atlas_json())
    for key in ("floor", "floor_dim", "wall", "stairs", "goblin", "lich",
                 "sword", "potion", "crown", "trap_spike", "decor_bones", "shopkeeper"):
        assert key in atlas, f"atlas missing {key}"
        assert len(atlas[key]["grid"]) == 16
    hero = json.loads(webbridge.hero_sprite_json("axe", "plate", True, False, "legendary"))
    assert len(hero["grid"]) == 16 and hero["palette"]
    print(f"OK: sprite atlas exports {len(atlas)} sprites + hero variants")


def test_game_flow():
    snap = json.loads(webbridge.new_game())
    assert snap["depth"] == 1 and not snap["game_over"]
    assert snap["floor_changed"] is True
    floor = json.loads(webbridge.floor_data_json())
    assert floor["width"] > 0 and len(floor["tiles"]) == floor["height"]

    # Walk toward the stairs using the engine's own BFS until we descend.
    from engine.world import _bfs_next_step
    state = webbridge.STATE
    descended = False
    for _ in range(600):
        pos = (state.player.x, state.player.y)
        step = _bfs_next_step(state.floor, pos, state.floor.stairs_pos, blocked=set())
        if step is None:
            break
        snap = json.loads(webbridge.move(step[0] - pos[0], step[1] - pos[1]))
        if snap["game_over"]:
            break
        if snap["shop_open"]:
            webbridge.close_shop()
            continue
        if snap["depth"] > 1:
            descended = True
            assert snap["floor_changed"] is True
            assert any(e["type"] == "descend" for e in snap["events"])
            break
    assert descended or snap["game_over"], "should reach floor 2 or die trying"
    print("OK: new_game -> move -> descend flow works through the JSON API")


def test_inventory_and_shop():
    import random
    from engine.items import generate_item
    from engine.dungeon import generate_floor

    json.loads(webbridge.new_game())
    state = webbridge.STATE
    rng = random.Random(5)
    weapon = generate_item(3, rng)
    while weapon.category != "weapon":
        weapon = generate_item(3, rng)
    state.player.inventory.append(weapon)

    snap = json.loads(webbridge.snapshot_json())
    entry = next(e for e in snap["inventory"] if e["id"] == weapon.id)
    assert entry["details"], "inventory entries must include stat details"
    assert any("Attack" in line for line in entry["details"])

    snap = json.loads(webbridge.equip_item(weapon.id))
    entry = next(e for e in snap["inventory"] if e["id"] == weapon.id)
    assert entry["equipped"] is True
    assert snap["player"]["hero"]["weapon"] != "none"

    # Shop: force a shop floor and buy/sell through the API.
    depth = 3
    shop_rng = random.Random(6)
    while True:
        floor = generate_floor(depth, shop_rng)
        if floor.shop_pos is not None and floor.shop_stock:
            break
        depth += 1
    state.floor = floor
    state.player.gold = 100000
    snap = json.loads(webbridge.snapshot_json())
    assert snap["shop_stock"] and snap["shop_stock"][0]["affordable"]
    stock_id = snap["shop_stock"][0]["id"]
    snap = json.loads(webbridge.buy_item(stock_id))
    assert any(e["id"] == stock_id for e in snap["inventory"])
    gold_after_buy = snap["player"]["gold"]
    snap = json.loads(webbridge.sell_item(stock_id))
    assert snap["player"]["gold"] > gold_after_buy
    print("OK: inventory equip + shop buy/sell work through the JSON API")


def test_save_load_roundtrip():
    json.loads(webbridge.new_game())
    webbridge.STATE.player.gold = 777
    saved = webbridge.save_json()
    snap = json.loads(webbridge.load_game(saved))
    assert "error" not in snap
    assert snap["player"]["gold"] == 777
    bad = json.loads(webbridge.load_game("{corrupt"))
    assert bad.get("error") == "bad_save"
    print("OK: save/load round-trips through JSON; corrupt saves are rejected")


def test_seed_and_mode_in_snapshot():
    snap = json.loads(webbridge.new_game(seed=42, mode="speedrun"))
    assert snap["seed"] == 42
    assert snap["run_mode"] == "speedrun"
    assert snap["target_floor"] == 100
    assert snap["replayable"] is True
    snap = json.loads(webbridge.new_game())
    assert isinstance(snap["seed"], int) and snap["run_mode"] == "normal"
    print("OK: snapshots expose seed, run mode, target floor and replayability")


def test_replay_round_trip_through_bridge():
    from engine.world import _bfs_next_step

    json.loads(webbridge.new_game(seed=7, mode="speedrun"))
    state = webbridge.STATE
    state.target_floor = 2  # tiny race for the test
    # Walk to the stairs via the bridge API so actions are recorded.
    for _ in range(400):
        if state.game_over:
            break
        if state.pending_shop:
            webbridge.close_shop()
            continue
        pos = (state.player.x, state.player.y)
        step = _bfs_next_step(state.floor, pos, state.floor.stairs_pos, blocked=set())
        if step is None:
            break
        webbridge.move(step[0] - pos[0], step[1] - pos[1])
    snap = json.loads(webbridge.snapshot_json())
    assert snap["game_won"], "test bot should win the 2-floor race"

    replay_text = webbridge.save_replay(9.5)
    replay = json.loads(replay_text)
    assert replay["seed"] == 7 and replay["result"]["outcome"] == "victory"

    result = json.loads(webbridge.load_replay(replay_text))
    assert "error" not in result
    steps = 0
    while not json.loads(webbridge.replay_progress())["finished"]:
        webbridge.replay_step()
        steps += 1
        assert steps < 10000
    final = json.loads(webbridge.snapshot_json())
    assert final["game_won"] is True, "replayed run must reach the same victory"
    assert final["player"]["gold"] == snap["player"]["gold"]
    assert json.loads(webbridge.load_replay("garbage!!!")).get("error") == "bad_replay"
    print(f"OK: bridge replay round-trip reproduces the victory in {steps} steps")


def test_lore():
    data = json.loads(webbridge.lore_json())
    assert data["title"]
    assert len(data["pages"]) >= 3
    print(f"OK: lore_json exposes {len(data['pages'])} pages")


def test_audio_synth():
    names = json.loads(webbridge.sfx_names_json())
    assert "hit" in names["sfx"] and "depths" in names["music"]
    b64 = webbridge.synth_wav_b64("hit")
    raw = base64.b64decode(b64)
    assert raw[:4] == b"RIFF" and raw[8:12] == b"WAVE", "must be a valid WAV"
    assert webbridge.synth_wav_b64("nonsense") == ""
    print(f"OK: audio synth produces valid WAV base64 ({len(names['sfx'])} sfx, "
          f"{len(names['music'])} tracks at {webbridge.audio_synth.SAMPLE_RATE} Hz)")


if __name__ == "__main__":
    test_no_tkinter()
    test_atlas()
    test_game_flow()
    test_inventory_and_shop()
    test_save_load_roundtrip()
    test_seed_and_mode_in_snapshot()
    test_replay_round_trip_through_bridge()
    test_lore()
    test_audio_synth()
    print("\nAll web-bridge smoke tests passed.")
