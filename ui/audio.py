"""Procedural chiptune audio: synthesizes all music and sound effects into
WAV files at first launch (cached under assets/), then plays them through
whatever command-line audio player the system provides (paplay, pw-play,
aplay, ffplay, play). Pure stdlib - no tkinter, no external packages.

Set ENDLESS_DEPTHS_NO_AUDIO=1 to disable the whole subsystem (used by the
headless test harness).
"""
from __future__ import annotations

import array
import math
import os
import random
import shutil
import subprocess
import sys
import threading
import wave

SAMPLE_RATE = 22050
AUDIO_VERSION = 3

_TWO_PI = 2.0 * math.pi


def _midi(note: int) -> float:
    return 440.0 * 2 ** ((note - 69) / 12)


class Buffer:
    """A float mix buffer with a tiny additive synth."""

    def __init__(self, seconds: float):
        self.data = [0.0] * int(seconds * SAMPLE_RATE)

    def tone(self, start: float, dur: float, freq: float, vol: float,
             wave_: str = "square", duty: float = 0.5, sweep: float = 0.0,
             seed: int = 1):
        """Add one note. sweep = fractional frequency change per second
        (e.g. -0.5 halves the pitch over one second)."""
        data = self.data
        n0 = int(start * SAMPLE_RATE)
        n = int(dur * SAMPLE_RATE)
        end = min(n0 + n, len(data))
        n = end - n0
        if n <= 0:
            return
        rng = random.Random(seed)
        attack = max(1, int(0.004 * SAMPLE_RATE))
        release = max(1, int(n * 0.35))
        phase = 0.0
        for i in range(n):
            t = i / SAMPLE_RATE
            f = freq * (1.0 + sweep * t)
            phase += f / SAMPLE_RATE
            frac = phase - int(phase)
            if wave_ == "square":
                s = 1.0 if frac < duty else -1.0
            elif wave_ == "triangle":
                s = 4.0 * abs(frac - 0.5) - 1.0
            elif wave_ == "saw":
                s = 2.0 * frac - 1.0
            elif wave_ == "sine":
                s = math.sin(_TWO_PI * frac)
            else:  # noise
                s = rng.uniform(-1.0, 1.0)
            env = 1.0
            if i < attack:
                env = i / attack
            if i >= n - release:
                env = min(env, (n - i) / release)
            data[n0 + i] += s * vol * env

    def wav_bytes(self) -> bytes:
        import io
        samples = array.array("h")
        for v in self.data:
            v = max(-1.0, min(1.0, v))
            samples.append(int(v * 32000))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(SAMPLE_RATE)
            f.writeframes(samples.tobytes())
        return buf.getvalue()

    def write(self, path: str):
        with open(path, "wb") as f:
            f.write(self.wav_bytes())


# ----------------------------------------------------------------------
# Sound effects
# ----------------------------------------------------------------------
def _sfx_hit():
    b = Buffer(0.14)
    b.tone(0, 0.06, 0, 0.28, "noise", seed=11)
    b.tone(0, 0.09, 110, 0.22, "square", sweep=-2.0)
    return b


def _sfx_crit():
    b = Buffer(0.2)
    b.tone(0, 0.08, 0, 0.32, "noise", seed=13)
    b.tone(0, 0.13, 240, 0.26, "square", sweep=-2.5)
    b.tone(0.02, 0.1, 170, 0.18, "saw", sweep=-2.0)
    return b


def _sfx_player_hurt():
    b = Buffer(0.22)
    b.tone(0, 0.16, 170, 0.26, "square", sweep=-2.4)
    b.tone(0, 0.06, 0, 0.16, "noise", seed=17)
    return b


def _sfx_kill():
    b = Buffer(0.3)
    b.tone(0, 0.22, 320, 0.24, "square", sweep=-3.2)
    b.tone(0.04, 0.1, 0, 0.14, "noise", seed=19)
    return b


def _sfx_boss_kill():
    b = Buffer(0.8)
    for i, note in enumerate((50, 53, 57, 62)):
        b.tone(i * 0.12, 0.3, _midi(note), 0.2, "square", duty=0.4)
    b.tone(0, 0.5, 0, 0.1, "noise", seed=23)
    return b


def _sfx_levelup():
    b = Buffer(0.6)
    for i, note in enumerate((72, 76, 79, 84)):
        b.tone(i * 0.09, 0.22, _midi(note), 0.2, "square", duty=0.35)
    return b


def _sfx_gold():
    b = Buffer(0.16)
    b.tone(0, 0.05, 1250, 0.2, "sine")
    b.tone(0.06, 0.07, 1650, 0.2, "sine")
    return b


def _sfx_pickup():
    b = Buffer(0.1)
    b.tone(0, 0.07, 900, 0.2, "sine")
    return b


def _sfx_potion():
    b = Buffer(0.3)
    b.tone(0, 0.07, 420, 0.2, "sine")
    b.tone(0.08, 0.07, 520, 0.2, "sine")
    b.tone(0.16, 0.1, 340, 0.2, "sine")
    return b


def _sfx_scroll():
    b = Buffer(0.3)
    for i, f in enumerate((800, 950, 1100, 1300)):
        b.tone(i * 0.05, 0.09, f, 0.12, "triangle")
    return b


def _sfx_equip():
    b = Buffer(0.15)
    b.tone(0, 0.03, 0, 0.2, "noise", seed=29)
    b.tone(0.02, 0.09, 210, 0.22, "square", duty=0.3)
    return b


def _sfx_stairs():
    b = Buffer(0.5)
    b.tone(0, 0.12, 420, 0.18, "triangle")
    b.tone(0.14, 0.12, 320, 0.18, "triangle")
    b.tone(0.28, 0.16, 230, 0.18, "triangle")
    return b


def _sfx_buy():
    b = Buffer(0.18)
    b.tone(0, 0.06, 1000, 0.2, "sine")
    b.tone(0.07, 0.08, 1400, 0.2, "sine")
    return b


def _sfx_sell():
    b = Buffer(0.18)
    b.tone(0, 0.06, 1400, 0.2, "sine")
    b.tone(0.07, 0.08, 1000, 0.2, "sine")
    return b


def _sfx_death():
    b = Buffer(1.1)
    b.tone(0, 0.9, 300, 0.24, "square", sweep=-0.95)
    b.tone(0.1, 0.7, 0, 0.1, "noise", seed=31)
    return b


def _sfx_trap():
    b = Buffer(0.18)
    b.tone(0, 0.05, 0, 0.26, "noise", seed=37)
    b.tone(0.02, 0.1, 150, 0.22, "square", sweep=-1.5)
    return b


def _sfx_teleport():
    b = Buffer(0.4)
    b.tone(0, 0.18, 300, 0.18, "sine", sweep=3.0)
    b.tone(0.18, 0.2, 900, 0.18, "sine", sweep=-0.85)
    return b


def _sfx_fireball():
    b = Buffer(0.45)
    b.tone(0, 0.35, 0, 0.3, "noise", seed=41)
    b.tone(0, 0.25, 180, 0.16, "saw", sweep=-1.6)
    return b


def _sfx_menu():
    b = Buffer(0.06)
    b.tone(0, 0.04, 700, 0.14, "sine")
    return b


def _sfx_step():
    b = Buffer(0.05)
    b.tone(0, 0.025, 0, 0.05, "noise", seed=51)
    b.tone(0, 0.02, 95, 0.05, "sine")
    return b


def _sfx_drop():
    b = Buffer(0.14)
    b.tone(0, 0.09, 90, 0.2, "sine", sweep=-1.2)
    b.tone(0, 0.03, 0, 0.08, "noise", seed=53)
    return b


def _sfx_enchant():
    b = Buffer(0.5)
    b.tone(0, 0.14, 880, 0.12, "sine")
    b.tone(0.08, 0.14, 1320, 0.12, "sine")
    b.tone(0.18, 0.2, 1760, 0.1, "sine")
    return b


def _sfx_cure():
    b = Buffer(0.4)
    b.tone(0, 0.28, 600, 0.14, "sine", sweep=1.8)
    b.tone(0.06, 0.14, 900, 0.08, "triangle")
    return b


def _sfx_strength():
    b = Buffer(0.45)
    b.tone(0, 0.3, 110, 0.2, "saw", sweep=1.4)
    b.tone(0.12, 0.18, 220, 0.12, "square", duty=0.4)
    return b


def _sfx_heartbeat():
    b = Buffer(0.4)
    b.tone(0, 0.08, 58, 0.3, "sine", sweep=-1.0)
    b.tone(0.17, 0.08, 52, 0.26, "sine", sweep=-1.0)
    return b


def _sfx_boss_intro():
    b = Buffer(1.1)
    b.tone(0, 0.5, _midi(33), 0.2, "square", duty=0.3)   # low A
    b.tone(0, 0.5, _midi(40), 0.14, "square", duty=0.3)  # fifth
    b.tone(0.1, 0.45, 0, 0.1, "noise", seed=61)
    b.tone(0.55, 0.4, _midi(45), 0.18, "square", duty=0.3)
    b.tone(0.55, 0.4, _midi(51), 0.12, "saw")            # tritone menace
    return b


def _sfx_shop_bell():
    b = Buffer(0.4)
    b.tone(0, 0.16, 1568, 0.14, "sine")
    b.tone(0.09, 0.24, 2093, 0.11, "sine")
    return b


def _sfx_splat():
    b = Buffer(0.16)
    b.tone(0, 0.08, 0, 0.22, "noise", seed=67)
    b.tone(0.01, 0.1, 300, 0.16, "sine", sweep=-2.2)
    return b


def _sfx_poison_tick():
    b = Buffer(0.14)
    b.tone(0, 0.05, 250, 0.08, "sine")
    b.tone(0.06, 0.06, 200, 0.07, "sine")
    return b


SFX_BUILDERS = {
    "hit": _sfx_hit,
    "crit": _sfx_crit,
    "player_hurt": _sfx_player_hurt,
    "kill": _sfx_kill,
    "boss_kill": _sfx_boss_kill,
    "levelup": _sfx_levelup,
    "gold": _sfx_gold,
    "pickup": _sfx_pickup,
    "potion": _sfx_potion,
    "scroll": _sfx_scroll,
    "equip": _sfx_equip,
    "stairs": _sfx_stairs,
    "buy": _sfx_buy,
    "sell": _sfx_sell,
    "death": _sfx_death,
    "trap": _sfx_trap,
    "teleport": _sfx_teleport,
    "fireball": _sfx_fireball,
    "menu": _sfx_menu,
    "step": _sfx_step,
    "drop": _sfx_drop,
    "enchant": _sfx_enchant,
    "cure": _sfx_cure,
    "strength": _sfx_strength,
    "heartbeat": _sfx_heartbeat,
    "boss_intro": _sfx_boss_intro,
    "shop_bell": _sfx_shop_bell,
    "splat": _sfx_splat,
    "poison_tick": _sfx_poison_tick,
}


# ----------------------------------------------------------------------
# Music
# ----------------------------------------------------------------------
def _music_depths():
    """Slow, moody minor-key dungeon loop: Am - F - C - E."""
    bpm = 105
    eighth = 60 / bpm / 2
    #        arp notes (midi),         bass midi, lead half-note pair
    bars = [
        ([57, 60, 64, 69], 45, (76, 72)),   # Am
        ([53, 57, 60, 65], 41, (72, 69)),   # F
        ([48, 52, 55, 60], 36, (67, 64)),   # C
        ([52, 56, 59, 64], 40, (71, 68)),   # E
    ]
    passes = 2
    total = len(bars) * 8 * eighth * passes
    b = Buffer(total + 0.4)
    t = 0.0
    for p in range(passes):
        lead_shift = 12 if p == 1 else 0
        lead_vol = 0.07 if p == 1 else 0.09
        for arp, bass, lead in bars:
            bass_f = _midi(bass)
            for e in range(8):
                b.tone(t + e * eighth, eighth * 0.9, bass_f, 0.14, "square", duty=0.25)
                b.tone(t + e * eighth, eighth * 0.95, _midi(arp[e % 4]), 0.09, "triangle")
                if e % 2 == 1:
                    b.tone(t + e * eighth, 0.02, 6000, 0.035, "noise", seed=100 + e)
            b.tone(t, eighth * 4 * 0.95, _midi(lead[0] + lead_shift), lead_vol, "square")
            b.tone(t + 4 * eighth, eighth * 4 * 0.95, _midi(lead[1] + lead_shift), lead_vol, "square")
            t += 8 * eighth
    return b


def _music_boss():
    """Faster, driving boss loop: Dm - Bb - Gm - A with percussion."""
    bpm = 140
    eighth = 60 / bpm / 2
    bars = [
        ([62, 65, 69, 74], 38, (77, 74)),   # Dm
        ([58, 62, 65, 70], 34, (74, 70)),   # Bb
        ([55, 58, 62, 67], 31, (70, 67)),   # Gm
        ([57, 61, 64, 69], 33, (73, 69)),   # A
    ]
    passes = 2
    total = len(bars) * 8 * eighth * passes
    b = Buffer(total + 0.4)
    t = 0.0
    for p in range(passes):
        for arp, bass, lead in bars:
            bass_f = _midi(bass)
            for e in range(8):
                b.tone(t + e * eighth, eighth * 0.85, bass_f, 0.16, "square", duty=0.3)
                b.tone(t + e * eighth, eighth * 0.9, _midi(arp[(e * 3) % 4]), 0.08, "saw")
                if e in (0, 4):  # kick
                    b.tone(t + e * eighth, 0.07, 70, 0.3, "sine", sweep=-4.0)
                if e in (2, 6):  # snare
                    b.tone(t + e * eighth, 0.05, 0, 0.16, "noise", seed=200 + e)
            b.tone(t, eighth * 3, _midi(lead[0]), 0.08, "square", duty=0.4)
            b.tone(t + 4 * eighth, eighth * 3, _midi(lead[1]), 0.08, "square", duty=0.4)
            t += 8 * eighth
    return b


def _music_caverns():
    """Dreamy, echoing caves: Cmaj7 - Am7 - Fmaj7 - G."""
    bpm = 92
    eighth = 60 / bpm / 2
    bars = [
        ([48, 52, 55, 59], 36, (72, 71)),   # Cmaj7
        ([57, 60, 64, 67], 33, (69, 67)),   # Am7
        ([53, 57, 60, 64], 41, (65, 64)),   # Fmaj7
        ([55, 59, 62, 67], 43, (67, 71)),   # G
    ]
    passes = 2
    total = len(bars) * 8 * eighth * passes
    b = Buffer(total + 0.4)
    t = 0.0
    for p in range(passes):
        for arp, bass, lead in bars:
            bass_f = _midi(bass)
            for e in range(8):
                if e % 4 == 0:
                    b.tone(t + e * eighth, eighth * 3.8, bass_f, 0.13, "sine")
                b.tone(t + e * eighth, eighth * 1.1, _midi(arp[e % 4]), 0.08, "triangle")
                if e == 6:
                    b.tone(t + e * eighth, 0.02, 7000, 0.02, "noise", seed=300 + e)
            b.tone(t, eighth * 4 * 0.9, _midi(lead[0]), 0.06, "sine")
            b.tone(t + 4 * eighth, eighth * 4 * 0.9, _midi(lead[1]), 0.06, "sine")
            t += 8 * eighth
    return b


def _music_catacombs():
    """Slow, funereal organ tones: Em - C - Am - B."""
    bpm = 80
    eighth = 60 / bpm / 2
    bars = [
        ([52, 55, 59, 64], 40, (76, 74)),   # Em
        ([48, 52, 55, 60], 36, (72, 71)),   # C
        ([57, 60, 64, 69], 45, (69, 67)),   # Am
        ([59, 63, 66, 71], 47, (66, 64)),   # B
    ]
    passes = 2
    total = len(bars) * 8 * eighth * passes
    b = Buffer(total + 0.4)
    t = 0.0
    for p in range(passes):
        for arp, bass, lead in bars:
            # organ-ish: sustained root + fifth all bar
            b.tone(t, eighth * 8 * 0.95, _midi(bass), 0.12, "square", duty=0.2)
            b.tone(t, eighth * 8 * 0.95, _midi(bass + 7), 0.07, "triangle")
            for e in range(0, 8, 2):
                b.tone(t + e * eighth, eighth * 1.8, _midi(arp[(e // 2) % 4]), 0.07, "triangle")
            b.tone(t, eighth * 4 * 0.9, _midi(lead[0]), 0.06, "square", duty=0.35)
            b.tone(t + 4 * eighth, eighth * 4 * 0.9, _midi(lead[1]), 0.06, "square", duty=0.35)
            t += 8 * eighth
    return b


def _music_forge():
    """Driving, industrial: Dm - Dm - Gm - A with anvil clangs."""
    bpm = 132
    eighth = 60 / bpm / 2
    bars = [
        ([62, 65, 69, 74], 38, (74, 72)),   # Dm
        ([62, 65, 69, 74], 38, (70, 72)),   # Dm again
        ([55, 58, 62, 67], 31, (70, 67)),   # Gm
        ([57, 61, 64, 69], 33, (73, 69)),   # A
    ]
    passes = 2
    total = len(bars) * 8 * eighth * passes
    b = Buffer(total + 0.4)
    t = 0.0
    for p in range(passes):
        for arp, bass, lead in bars:
            bass_f = _midi(bass)
            for e in range(8):
                b.tone(t + e * eighth, eighth * 0.8, bass_f, 0.15, "saw")
                if e % 2 == 1:
                    b.tone(t + e * eighth, eighth * 0.7, _midi(arp[(e // 2) % 4]), 0.07, "square", duty=0.3)
                if e in (0, 4):  # anvil clang
                    b.tone(t + e * eighth, 0.05, 0, 0.12, "noise", seed=400 + e)
                    b.tone(t + e * eighth, 0.08, 1200, 0.06, "sine", sweep=-2.0)
            b.tone(t + 2 * eighth, eighth * 2, _midi(lead[0]), 0.07, "square", duty=0.4)
            b.tone(t + 6 * eighth, eighth * 2, _midi(lead[1]), 0.07, "square", duty=0.4)
            t += 8 * eighth
    return b


def _music_abyss():
    """Vast, slow dread: deep drones with a lonely melody."""
    bpm = 60
    eighth = 60 / bpm / 2
    bars = [
        (34, (65, 63)),   # Bb
        (32, (63, 61)),   # Ab
        (29, (61, 60)),   # F
        (31, (58, 56)),   # G
    ]
    passes = 1  # long bars already; keep the loop tight
    total = len(bars) * 8 * eighth * passes
    b = Buffer(total + 0.5)
    t = 0.0
    for bass, lead in bars:
        b.tone(t, eighth * 8 * 0.98, _midi(bass), 0.16, "sine")
        b.tone(t, eighth * 8 * 0.98, _midi(bass + 12), 0.06, "triangle")
        b.tone(t + eighth, eighth * 3, _midi(lead[0]), 0.055, "triangle")
        b.tone(t + 5 * eighth, eighth * 2.5, _midi(lead[1]), 0.05, "triangle")
        b.tone(t + 7 * eighth, 0.03, 5000, 0.015, "noise", seed=500)
        t += 8 * eighth
    return b


def _music_crystal():
    """Bright, glittering: A - D - F#m - E with bell tones."""
    bpm = 112
    eighth = 60 / bpm / 2
    bars = [
        ([57, 61, 64, 69], 45, (81, 80)),   # A
        ([62, 66, 69, 74], 38, (78, 76)),   # D
        ([54, 58, 61, 66], 42, (76, 73)),   # F#m
        ([52, 56, 59, 64], 40, (73, 76)),   # E
    ]
    passes = 2
    total = len(bars) * 8 * eighth * passes
    b = Buffer(total + 0.4)
    t = 0.0
    for p in range(passes):
        for arp, bass, lead in bars:
            bass_f = _midi(bass)
            for e in range(8):
                if e % 2 == 0:
                    b.tone(t + e * eighth, eighth * 1.6, bass_f, 0.11, "triangle")
                b.tone(t + e * eighth, eighth * 0.9, _midi(arp[e % 4] + 12), 0.06, "triangle")
                if e % 4 == 2:
                    b.tone(t + e * eighth, 0.02, 8000, 0.025, "noise", seed=600 + e)
            # bell lead: sine with a faint octave shimmer
            b.tone(t, eighth * 3, _midi(lead[0]), 0.07, "sine")
            b.tone(t, eighth * 3, _midi(lead[0] + 12), 0.02, "sine")
            b.tone(t + 4 * eighth, eighth * 3, _midi(lead[1]), 0.07, "sine")
            b.tone(t + 4 * eighth, eighth * 3, _midi(lead[1] + 12), 0.02, "sine")
            t += 8 * eighth
    return b


MUSIC_BUILDERS = {
    "depths": _music_depths,
    "boss": _music_boss,
    "caverns": _music_caverns,
    "catacombs": _music_catacombs,
    "forge": _music_forge,
    "abyss": _music_abyss,
    "crystal": _music_crystal,
}

# The soundtrack rotates as the player descends: each 3-floor band gets its
# own track, cycling forever. Boss floors override with the boss theme.
TRACK_ROTATION = ["depths", "caverns", "catacombs", "forge", "abyss", "crystal"]


def track_for_depth(depth: int, boss_alive: bool = False) -> str:
    if boss_alive:
        return "boss"
    return TRACK_ROTATION[((max(1, depth) - 1) // 3) % len(TRACK_ROTATION)]


# ----------------------------------------------------------------------
# Manager
# ----------------------------------------------------------------------
class AudioManager:
    def __init__(self, cache_dir: str, muted: bool = False, autostart: bool = True,
                  music_on: bool = True, sfx_on: bool = True):
        self.cache_dir = cache_dir
        self.music_on = music_on and not muted
        self.sfx_on = sfx_on and not muted
        self.disabled = os.environ.get("ENDLESS_DEPTHS_NO_AUDIO") == "1"
        self.ready = False
        self._player_cmd = None if self.disabled else self._detect_player()
        self._music_proc = None
        self._want_music = None
        self._sfx_procs: list = []
        if not self.disabled and autostart:
            threading.Thread(target=self.generate_all, daemon=True).start()

    @property
    def muted(self) -> bool:
        """Master-mute view over the two channel toggles."""
        return not (self.music_on or self.sfx_on)

    @staticmethod
    def _detect_player():
        if sys.platform == "win32":
            return None  # winsound handled separately in play()
        candidates = [
            ["paplay"],
            ["pw-play"],
            ["aplay", "-q"],
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],
            ["play", "-q"],
            ["afplay"],
        ]
        for cmd in candidates:
            if shutil.which(cmd[0]):
                return cmd
        return None

    def _path(self, name: str) -> str:
        return os.path.join(self.cache_dir, f"{name}_v{AUDIO_VERSION}.wav")

    def generate_all(self):
        """Synthesize every missing WAV into the cache dir (idempotent)."""
        os.makedirs(self.cache_dir, exist_ok=True)
        suffix = f"_v{AUDIO_VERSION}.wav"
        for fname in os.listdir(self.cache_dir):
            if fname.endswith(".wav") and not fname.endswith(suffix):
                try:
                    os.remove(os.path.join(self.cache_dir, fname))
                except OSError:
                    pass
        for name, builder in list(SFX_BUILDERS.items()) + list(MUSIC_BUILDERS.items()):
            path = self._path(name)
            if not os.path.exists(path):
                builder().write(path)
        self.ready = True

    def _base_ok(self) -> bool:
        return not self.disabled and self.ready

    def play(self, name: str):
        if not self._base_ok() or not self.sfx_on or name not in SFX_BUILDERS:
            return
        path = self._path(name)
        if sys.platform == "win32":
            try:
                import winsound
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            except Exception:
                pass
            return
        if not self._player_cmd:
            return
        self._reap()
        try:
            proc = subprocess.Popen(self._player_cmd + [path],
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
            self._sfx_procs.append(proc)
        except OSError:
            pass

    def play_music(self, name):
        """Set the looping background track (None = stop music)."""
        self._want_music = name
        if name is None or not self.music_on:
            self._stop_music_proc()
            return
        self.tick()

    def tick(self):
        """Call periodically: reaps finished SFX and keeps music looping."""
        self._reap()
        if self.disabled or sys.platform == "win32":
            return
        if self._want_music and self._base_ok() and self.music_on and self._player_cmd:
            if self._music_proc is None or self._music_proc.poll() is not None:
                try:
                    self._music_proc = subprocess.Popen(
                        self._player_cmd + [self._path(self._want_music)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except OSError:
                    self._music_proc = None

    def set_muted(self, muted: bool):
        """Master mute: flips both channels together (the M key)."""
        self.music_on = not muted
        self.sfx_on = not muted
        if muted:
            self._stop_music_proc()
        else:
            self.tick()

    def set_music(self, on: bool):
        self.music_on = on
        if not on:
            self._stop_music_proc()
        else:
            self.tick()

    def set_sfx(self, on: bool):
        self.sfx_on = on

    def _stop_music_proc(self):
        if self._music_proc and self._music_proc.poll() is None:
            try:
                self._music_proc.terminate()
            except OSError:
                pass
        self._music_proc = None

    def _reap(self):
        self._sfx_procs = [p for p in self._sfx_procs if p.poll() is None]

    def shutdown(self):
        self._stop_music_proc()
        for p in self._sfx_procs:
            if p.poll() is None:
                try:
                    p.terminate()
                except OSError:
                    pass
        self._sfx_procs = []
