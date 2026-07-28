"""Headless test of the browser bridge (web/webbridge.py) - the exact code
Pyodide runs, driven locally without a browser. Run with:
    python3 scripts/web_smoke_test.py
"""
import base64
import io
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
    from ui.spritedata import SPRITE_PX
    atlas = json.loads(webbridge.sprite_atlas_json())
    for key in ("floor", "floor_dim", "wall", "stairs", "goblin", "lich",
                 "sword", "potion", "crown", "trap_spike", "decor_bones", "shopkeeper",
                 "door_rune", "door_rune_dim", "chest", "chest_dim", "mimic", "key",
                 "lever_up", "lever_down", "plate_off", "plate_on", "block",
                 "rune_switch"):
        assert key in atlas, f"atlas missing {key}"
        assert len(atlas[key]["grid"]) == SPRITE_PX
    hero = json.loads(webbridge.hero_sprite_json("axe", "plate", True, False, "legendary"))
    assert len(hero["grid"]) == SPRITE_PX and hero["palette"]
    print(f"OK: sprite atlas exports {len(atlas)} sprites + hero variants at {SPRITE_PX}px")


def test_monster_sprite_completeness():
    """Every monster template must map to a real sprite. Both renderers
    fall back to the goblin sprite for unmapped names, so a forgotten
    MONSTER_KEYS entry would silently ship a deep-floor monster wearing a
    goblin costume rather than crashing anything."""
    from engine.entities import MONSTER_TEMPLATES
    from ui.spritedata import MONSTER_KEYS, SPRITE_DEFS, SPRITE_PX
    for name, *_ in MONSTER_TEMPLATES:
        assert name in MONSTER_KEYS, f"MONSTER_KEYS missing {name!r}"
    assert "Mimic" in MONSTER_KEYS  # not a template; hatches from chests
    for name, key in MONSTER_KEYS.items():
        assert key in SPRITE_DEFS, f"{name!r} maps to unknown sprite {key!r}"
        grid, palette = SPRITE_DEFS[key]
        assert len(grid) == SPRITE_PX and all(len(row) == SPRITE_PX for row in grid), \
            f"sprite {key!r} is not a clean {SPRITE_PX}x{SPRITE_PX} grid"
        used_chars = {ch for row in grid for ch in row if ch != "."}
        missing = used_chars - set(palette)
        assert not missing, f"sprite {key!r} uses unmapped palette chars {missing}"
    print(f"OK: all {len(MONSTER_KEYS)} monster names map to valid "
          f"{SPRITE_PX}x{SPRITE_PX} sprites")


def test_biome_sprite_completeness():
    """Every biome's sprite-key suffix (engine/biomes.py) must resolve to a
    real floor/floor2/floor3/wall/wall2 sprite AND have a DIM_TILES entry -
    the renderer (web/main.js's render()) appends the suffix blind, so a
    missing one would KeyError mid-render instead of falling back to
    anything."""
    from engine.biomes import BIOMES
    from ui.spritedata import SPRITE_DEFS, DIM_TILES, TRAP_KEYS, SPRITE_PX

    tile_bases = ("floor", "floor2", "floor3", "wall", "wall2")
    for _min_depth, biome in BIOMES:
        for base in tile_bases:
            key = base + biome.key
            assert key in SPRITE_DEFS, f"biome {biome.name!r} missing sprite {key!r}"
            assert key in DIM_TILES, f"biome {biome.name!r} sprite {key!r} has no dim variant"
            grid, palette = SPRITE_DEFS[key]
            assert len(grid) == SPRITE_PX and all(len(row) == SPRITE_PX for row in grid), \
                f"sprite {key!r} is not a clean {SPRITE_PX}x{SPRITE_PX} grid"
            used_chars = {ch for row in grid for ch in row if ch != "."}
            missing = used_chars - set(palette)
            assert not missing, f"sprite {key!r} uses unmapped palette chars {missing}"
        for kind in biome.extra_trap_kinds:
            assert kind in TRAP_KEYS and TRAP_KEYS[kind] in SPRITE_DEFS, \
                f"biome {biome.name!r} hazard trap kind {kind!r} has no sprite"
    print(f"OK: all {len(BIOMES)} biomes resolve to valid floor/wall sprites with dim variants")


def test_hero_facings():
    """The hero has four facings; left is a mirror of right, up hides the
    weapon, and the bridge accepts the facing argument (with a default,
    so older calls keep working)."""
    from ui.spritedata import SPRITE_PX
    grids = {}
    for facing in ("down", "up", "left", "right"):
        hero = json.loads(webbridge.hero_sprite_json(
            "sword", "plate", True, False, "rare", facing))
        assert len(hero["grid"]) == SPRITE_PX
        grids[facing] = hero["grid"]
    assert grids["left"] == [row[::-1] for row in grids["right"]], \
        "left must be the mirror of right"
    assert grids["up"] != grids["down"], "up and down must differ"
    assert grids["right"] != grids["down"], "side and down must differ"
    # Facing up hides the blade: no 's' (blade slot) pixels in the up grid.
    assert not any("s" in row for row in grids["up"]), \
        "the weapon should be hidden when facing up"
    print("OK: hero facings - four poses, left mirrors right, weapon hidden "
          "when facing up")


def test_texture_codec_and_pack():
    """Pure-stdlib PNG codec + textures/ pack loader (ui/texturepack.py)."""
    import struct
    import tempfile
    import zlib as _zlib
    from ui import spritedata as S
    from ui import texturepack as TP

    # Round-trip: our encoder -> our decoder, on a real shipped sprite.
    rows = TP.grid_to_px(*S.SPRITE_DEFS["rat"])
    assert TP.decode_png(TP.encode_png(rows)) == rows

    # Decoder handles all five scanline filters (editors use them freely).
    w, h = 4, 5
    pixels = [[(x * 40 + y, 255 - x * 30, (x * y * 17) % 256, 255)
               for x in range(w)] for y in range(h)]
    raw = bytearray()
    prev = bytes(w * 4)
    for y, ftype in enumerate((0, 1, 2, 3, 4)):
        line = bytes(v for px in pixels[y] for v in px)
        raw.append(ftype)
        for i in range(len(line)):
            left = line[i - 4] if i >= 4 else 0
            up = prev[i]
            ul = prev[i - 4] if i >= 4 else 0
            if ftype == 0:
                pred = 0
            elif ftype == 1:
                pred = left
            elif ftype == 2:
                pred = up
            elif ftype == 3:
                pred = (left + up) // 2
            else:
                p = left + up - ul
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - ul)
                pred = left if (pa <= pb and pa <= pc) else (up if pb <= pc else ul)
            raw.append((line[i] - pred) & 0xFF)
        prev = line

    def chunk(tag, body):
        return (struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", _zlib.crc32(tag + body)))

    filtered_png = (b"\x89PNG\r\n\x1a\n"
                    + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                    + chunk(b"IDAT", _zlib.compress(bytes(raw)))
                    + chunk(b"IEND", b""))
    assert TP.decode_png(filtered_png) == pixels, "filter reconstruction failed"

    # Palettized (color type 3) with transparency - Aseprite-style output.
    plte = bytes((255, 0, 0, 0, 255, 0))       # red, green
    trns = bytes((0,))                          # palette index 0 transparent
    idx_raw = b"".join(b"\x00" + bytes(row) for row in ((0, 1), (1, 0)))
    pal_png = (b"\x89PNG\r\n\x1a\n"
               + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 3, 0, 0, 0))
               + chunk(b"PLTE", plte) + chunk(b"tRNS", trns)
               + chunk(b"IDAT", _zlib.compress(idx_raw))
               + chunk(b"IEND", b""))
    assert TP.decode_png(pal_png) == [
        [(255, 0, 0, 0), (0, 255, 0, 255)],
        [(0, 255, 0, 255), (255, 0, 0, 0)],
    ]

    # Pack loader: size normalization, hero routing, and rejection paths.
    with tempfile.TemporaryDirectory() as root:
        def put(name, size, color=(10, 20, 30, 255)):
            grid = [[color] * size for _ in range(size)]
            path = os.path.join(root, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(TP.encode_png(grid))
            return grid

        native = put("monsters/rat.png", 32)
        small = put("tiles/floor.png", 16, (50, 60, 70, 255))
        big = put("monsters/lich.png", 64, (1, 2, 3, 255))
        put("hero/hero_base.png", 32, (99, 98, 97, 255))
        put("hero/weapon_axe.png", 32, (96, 95, 94, 255))
        put("bad/wrongsize.png", 20)
        with open(os.path.join(root, "bad", "corrupt.png"), "wb") as f:
            f.write(b"not a png at all")

        sprites, hero, warnings = TP.load_pack(root, for_desktop=True)
        assert sprites["rat"] == native
        assert sprites["floor"] == TP.scale2x_px(small) and len(sprites["floor"]) == 32
        assert len(sprites["lich"]) == 32, "64px should downsample on desktop"
        assert hero["base"] is not None and "axe" in hero["weapons"]
        assert "wrongsize" not in sprites and "corrupt" not in sprites
        assert len(warnings) == 2, f"expected 2 warnings, got: {warnings}"

        web_sprites, _h, _w = TP.load_pack(root, for_desktop=False)
        assert len(web_sprites["lich"]) == 64, "64px should stay native on web"
        assert web_sprites["lich"] == big

    # The real exported textures/ (when present) must decode back to
    # exactly the built-in art it was generated from.
    real_root = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "textures")
    if os.path.isdir(real_root):
        sprites, hero, warnings = TP.load_pack(real_root)
        assert not warnings, f"shipped textures have problems: {warnings}"
        for probe in ("rat", "wall", "chest"):
            assert sprites[probe] == TP.grid_to_px(*S.SPRITE_DEFS[probe])
        assert hero["base"] is not None and len(hero["weapons"]) == 5
    print("OK: PNG codec round-trips (all filters + palette), pack loader "
          "normalizes 16/32/64 and rejects bad files")


def test_texture_pack_export():
    """build_pack_files/build_pack_zip_bytes/write_pack_to_dir (ui/texture
    pack.py) and webbridge's export_texture_pack_b64 wrapper - the shared
    logic behind scripts/export_textures.py and both front-ends' "Export
    Texture Pack" button."""
    import tempfile
    import zipfile
    from ui import spritedata as S
    from ui import texturepack as TP

    files = TP.build_pack_files()
    assert "manifest.json" in files and "README.md" in files
    for key in S.SPRITE_DEFS:
        assert f"{TP.category_for_key(key)}/{key}.png" in files, f"missing {key}"
    for stem in (TP.HERO_BASE_STEM, TP.HERO_BASE_UP_STEM, TP.HERO_BASE_SIDE_STEM,
                 TP.HERO_ACCESSORY_STEM):
        assert f"hero/{stem}.png" in files, f"missing hero/{stem}.png"
    for kind in S.HELD_WEAPONS:
        assert f"hero/{TP.HERO_WEAPON_PREFIX}{kind}.png" in files

    # The zip is STORED-only (the web import path relies on this to skip a
    # DEFLATE decompressor) and round-trips through Python's own reader.
    zip_bytes = TP.build_pack_zip_bytes()
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = set(zf.namelist())
        assert names == set(files), "zip contents must match build_pack_files()"
        for info in zf.infolist():
            assert info.compress_type == zipfile.ZIP_STORED, f"{info.filename} isn't STORED"
        assert zf.read("manifest.json") == files["manifest.json"]

    # write_pack_to_dir: writes everything fresh, then never clobbers an
    # edited file on a second pass unless force=True.
    with tempfile.TemporaryDirectory() as root:
        result = TP.write_pack_to_dir(root)
        assert not result["kept"] and len(result["written"]) == len(files)
        edited = os.path.join(root, "manifest.json")
        with open(edited, "wb") as f:
            f.write(b"hand-edited")
        result2 = TP.write_pack_to_dir(root)
        assert "manifest.json" in result2["kept"] and "manifest.json" not in result2["written"]
        with open(edited, "rb") as f:
            assert f.read() == b"hand-edited"
        result3 = TP.write_pack_to_dir(root, force=True)
        assert "manifest.json" in result3["written"]

    # The web bridge just base64-wraps a fresh build_pack_zip_bytes() - not
    # byte-identical (zipfile stamps each entry with the current time), but
    # same members and same manifest content.
    b64 = webbridge.export_texture_pack_b64()
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(b64))) as zf:
        assert set(zf.namelist()) == set(files)
        assert zf.read("manifest.json") == files["manifest.json"]
    print(f"OK: build_pack_files/build_pack_zip_bytes/write_pack_to_dir cover "
          f"all {len(files)} files; export_texture_pack_b64 matches")


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

    # inventory/shop_stock were split out of snapshot_json() (a perf fix -
    # they were being re-sorted/re-described on every move/wait even while
    # the overlay was closed) into their own on-demand endpoints.
    inv = json.loads(webbridge.inventory_json())
    entry = next(e for e in inv if e["id"] == weapon.id)
    assert entry["details"], "inventory entries must include stat details"
    assert any("Attack" in line for line in entry["details"])

    snap = json.loads(webbridge.equip_item(weapon.id))
    inv = json.loads(webbridge.inventory_json())
    entry = next(e for e in inv if e["id"] == weapon.id)
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
    shop = json.loads(webbridge.shop_json())
    assert shop and shop[0]["affordable"]
    stock_id = shop[0]["id"]
    snap = json.loads(webbridge.buy_item(stock_id))
    inv = json.loads(webbridge.inventory_json())
    assert any(e["id"] == stock_id for e in inv)
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


def test_puzzle_via_bridge():
    from engine import puzzles as puzzle_module

    json.loads(webbridge.new_game(seed=11))
    state = webbridge.STATE
    # Skim down floors until a pop-up puzzle gates the stairs.
    for _ in range(200):
        pz = state.floor.puzzle
        if pz is not None and pz["kind"] not in puzzle_module.IN_DUNGEON:
            break
        state.depth += 1
        state._enter_floor(regenerate=True)
    else:
        raise AssertionError("no pop-up puzzle floor found")
    state.floor.monsters.clear()
    state.floor.traps.clear()
    state.player.hp = state.player.max_hp = 10 ** 6

    floor_data = json.loads(webbridge.floor_data_json())
    sx, sy = state.floor.stairs_pos
    assert floor_data["tiles"][sy][sx] == "+", "the sealed door must ship in floor data"
    tiles_v0 = floor_data["tiles_version"]

    # Stand beside the door and bump it through the JSON API.
    spot = next((sx + dx, sy + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                if state.floor.is_walkable(sx + dx, sy + dy))
    state.player.x, state.player.y = spot
    snap = json.loads(webbridge.move(sx - spot[0], sy - spot[1]))
    assert snap["puzzle_open"] is True
    assert snap["puzzle"]["title"] and isinstance(snap["puzzle"]["buttons"], list)

    # Movement is refused while the popup is open.
    turns = snap["player"]["turns"]
    snap = json.loads(webbridge.move(1, 0))
    assert snap["player"]["turns"] == turns, "popup must freeze the world"

    # Walking away and bumping again works over the bridge too.
    snap = json.loads(webbridge.close_puzzle())
    assert snap["puzzle_open"] is False and snap["puzzle"] is None
    snap = json.loads(webbridge.move(sx - spot[0], sy - spot[1]))
    assert snap["puzzle_open"] is True

    # Solve via recorded inputs; the tile mutation must bump tiles_version
    # so the JS renderer knows to re-fetch its cached floor data.
    pz = state.floor.puzzle
    for _ in range(200):
        if pz["solved"]:
            break
        snap = json.loads(webbridge.puzzle_input(puzzle_module.solve_sequence(pz)[0]))
    assert pz["solved"] and snap["puzzle_open"] is False
    assert snap["tiles_version"] > tiles_v0, "solving must invalidate cached tiles"
    floor_data = json.loads(webbridge.floor_data_json())
    assert floor_data["tiles"][sy][sx] == ">", "the door must dissolve into stairs"
    print("OK: sealed-door puzzle drives end-to-end through the JSON bridge")


def test_all_engine_modules_shipped_to_browser():
    """Every engine/*.py on disk must appear in main.js's PY_FILES fetch
    list, or the Pyodide build breaks with an ImportError while the
    filesystem-based tests keep passing (this exact bug shipped once)."""
    import re
    game_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(game_dir, "web", "main.js"), encoding="utf-8") as f:
        source = f.read()
    match = re.search(r"const PY_FILES = \[(.*?)\];", source, re.DOTALL)
    assert match, "could not find PY_FILES in web/main.js"
    listed = set(re.findall(r'"([^"]+\.py)"', match.group(1)))

    on_disk = {f"engine/{name}" for name in os.listdir(os.path.join(game_dir, "engine"))
               if name.endswith(".py")}
    missing = on_disk - listed
    assert not missing, f"engine modules missing from PY_FILES in web/main.js: {sorted(missing)}"

    # And everything listed must actually exist (catches stale entries).
    for path in listed:
        assert os.path.exists(os.path.join(game_dir, path)), f"PY_FILES lists nonexistent {path}"
    print(f"OK: all {len(on_disk)} engine modules are shipped to the browser build")


def test_itch_zip_script_ships_everything_main_js_needs():
    """scripts/build_itch_zip.sh keeps its own hardcoded FILES array,
    separate from main.js's PY_FILES - the exact same class of drift as
    test_all_engine_modules_shipped_to_browser, but for the itch.io
    package instead of the live site (engine/bosses.py shipped without
    an itch entry once: the itch build silently omitted it, and the
    deployed page failed with "failed to fetch engine/bosses.py")."""
    import re
    game_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(game_dir, "web", "main.js"), encoding="utf-8") as f:
        main_js = f.read()
    match = re.search(r"const PY_FILES = \[(.*?)\];", main_js, re.DOTALL)
    assert match, "could not find PY_FILES in web/main.js"
    needed = set(re.findall(r'"([^"]+\.py)"', match.group(1)))
    needed |= {"web/webbridge.py", "index.html", "web/main.js", "web/style.css"}

    with open(os.path.join(game_dir, "scripts", "build_itch_zip.sh"), encoding="utf-8") as f:
        script = f.read()
    match = re.search(r"FILES=\(\n(.*?)\n\)", script, re.DOTALL)
    assert match, "could not find FILES=(...) in scripts/build_itch_zip.sh"
    packaged = {line.strip() for line in match.group(1).splitlines()
                if line.strip() and not line.strip().startswith("#")}

    missing = needed - packaged
    assert not missing, (
        f"files main.js needs but scripts/build_itch_zip.sh doesn't package: "
        f"{sorted(missing)} - the itch build will 404 fetching these")
    print(f"OK: itch build script packages all {len(needed)} files the browser build needs")


def test_lore():
    data = json.loads(webbridge.lore_json())
    assert data["title"]
    assert len(data["pages"]) >= 3
    print(f"OK: lore_json exposes {len(data['pages'])} pages")


def test_lore_pages_bridge():
    from engine import lorepages

    catalog = json.loads(webbridge.lore_pages_catalog_json())
    assert len(catalog) == 54
    assert "A-6" not in catalog and "X-6" not in catalog
    assert catalog["W-5"]["author"] == "The Well"
    assert catalog["W-5"]["text"] == lorepages.PAGES_BY_ID["W-5"].text

    webbridge.new_game()
    webbridge.STATE.pages_found = {"F-1", "S-3"}
    run_data = json.loads(webbridge.lore_journal_run_data_json())
    assert run_data == ["F-1", "S-3"]
    print(f"OK: lore_pages_catalog_json exposes all {len(catalog)} pages; "
          "lore_journal_run_data_json reports this run's finds")


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
    test_monster_sprite_completeness()
    test_biome_sprite_completeness()
    test_hero_facings()
    test_texture_codec_and_pack()
    test_texture_pack_export()
    test_game_flow()
    test_inventory_and_shop()
    test_save_load_roundtrip()
    test_seed_and_mode_in_snapshot()
    test_replay_round_trip_through_bridge()
    test_puzzle_via_bridge()
    test_all_engine_modules_shipped_to_browser()
    test_itch_zip_script_ships_everything_main_js_needs()
    test_lore()
    test_lore_pages_bridge()
    test_audio_synth()
    print("\nAll web-bridge smoke tests passed.")
