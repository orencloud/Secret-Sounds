"""Decode and prepare short clips off the Blender thread. Audaspace owns the voices."""

from collections import OrderedDict, deque
from concurrent.futures import ThreadPoolExecutor
from math import exp, hypot, log2
from pathlib import Path
from random import choice
from time import perf_counter

import aud
import numpy as np

from .catalog import MOTION

PACKAGE = Path(__file__).resolve().parent
IDLE = 0.045
FADE = 0.05
SAMPLE_RATE = 24000
CACHE_LIMIT = 16 * 1024 * 1024
WHEEL_SPACING = 0.020
WHEEL_BATCH = 12
WHEEL_CUES = ("zoom", "loopCutCount", "bevelSegments")


def decode(path):
    sound = aud.Sound.file(str(path)).limit(0, 8).rechannel(1).resample(SAMPLE_RATE)
    return np.ascontiguousarray(sound.data().reshape(-1), dtype=np.float32)


def loop_samples(pcm):
    if pcm.size < 32:
        return pcm
    scan = min(960, pcm.size // 4)
    threshold = float(np.max(np.abs(pcm))) / 180
    a = np.flatnonzero(np.abs(pcm[:scan]) > threshold)
    b = np.flatnonzero(np.abs(pcm[-scan:]) > threshold)
    begin = int(a[0]) if a.size else scan
    end = pcm.size - scan + int(b[-1]) + 1 if b.size else pcm.size - scan
    seam = min(192, (end - begin) // 8)
    if seam < 2:
        return pcm
    t = np.linspace(0, 1, seam, dtype=np.float32)
    gain = t * t * (3 - 2 * t)
    blend = pcm[end - seam:end] * (1 - gain) + pcm[begin:begin + seam] * gain
    return np.concatenate((pcm[begin + seam:end - seam], blend))


def stretch(pcm, tempo):
    """Overlap aligned grains around the tempo cursor. Grain pitch stays fixed."""
    if tempo == 1 or pcm.size < 32:
        return pcm
    length = max(16, min(SAMPLE_RATE * 8, round(pcm.size / tempo)))
    seam = min(96, length // 8)
    size = length + seam
    hop = min(240, max(8, size // 8), max(8, pcm.size // 4))
    sample = np.arange(hop)
    probes = np.arange(0, hop, max(1, hop // 24))
    radius = min(hop // 2, pcm.size // 4)
    shifts = np.arange(-radius, radius + 1, max(1, radius // 8))
    envelope = np.linspace(0, 1, hop, endpoint=False, dtype=np.float32)
    out = np.empty(size, dtype=np.float32)
    tail = None
    for index in range(0, size, hop):
        start = round(index * tempo)
        if tail is not None:
            candidates = pcm[(start + shifts[:, None] + probes) % pcm.size]
            ref = tail[probes]
            score = (candidates * ref).sum(axis=1)
            score /= np.sqrt(np.maximum((candidates * candidates).sum(axis=1), 1e-12))
            score -= abs(shifts) * 1e-6
            start += int(shifts[int(score.argmax())])
        grain = pcm[(start + sample) % pcm.size]
        if tail is not None:
            grain = tail * (1 - envelope) + grain * envelope
        count = min(hop, size - index)
        out[index:index + count] = grain[:count]
        tail = pcm[(start + hop + sample) % pcm.size]
    if seam >= 2:
        fade = np.linspace(0, 1, seam, dtype=np.float32)
        out[-seam:] = out[-seam:] * (1 - fade) + out[:seam] * fade
        return np.ascontiguousarray(out[seam:])
    return out


class Audio:
    def __init__(self):
        self.device = None
        self.worker = None
        self.jobs = {}
        self.cache = OrderedDict()
        self.failed = set()
        self.cache_size = 0
        self.pending = []
        self.wheel = deque()
        self.next_wheel = 0.0
        self.shots = []
        self.tails = []
        self.paths = {}
        self.volume = 0
        self.bounds = (80, 5000, 0, 0, 1, 1)
        self.gesture = None
        self.error = ""
        self.warming = deque()

    def configure(self, paths, bounds, volume):
        self.clear()
        self.paths = paths
        self.bounds = bounds
        self.volume = volume
        self.failed.clear()
        self.error = ""
        priority_paths = (path for cue in WHEEL_CUES for path in paths.get(cue, ()))
        other_paths = (path for items in paths.values() for path in items)
        self.warming = deque(dict.fromkeys((*priority_paths, *other_paths)))

    def warm(self):
        if self.volume <= 0:
            return
        # Shared paths are decoded once, and loading is bounded outside input.
        while self.warming and len(self.jobs) < 6:
            key = (self.warming.popleft(), None)
            if key not in self.cache and key not in self.failed and key not in self.jobs:
                self.request(key)
                break

    def request(self, key):
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        if key in self.failed or key in self.jobs or len(self.jobs) >= 6:
            return None
        path, tempo = key
        if tempo is not None:
            original = self.request((path, None))
            if original is None or len(self.jobs) >= 6:
                return None
        if self.worker is None:
            self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="Secret Sounds")
        self.jobs[key] = (self.worker.submit(decode, path) if tempo is None else
                          self.worker.submit(self.prepare_loop, original[1], tempo))
        return None

    @staticmethod
    def prepare_loop(pcm, tempo):
        return stretch(loop_samples(pcm), 2.0 ** (tempo / 12))

    def collect(self):
        for key, job in tuple(self.jobs.items()):
            if not job.done():
                continue
            del self.jobs[key]
            try:
                pcm = job.result()
                if not pcm.size:
                    raise ValueError("Empty clip")
                sound = aud.Sound.buffer(pcm.reshape(-1, 1), SAMPLE_RATE)
            except (OSError, RuntimeError, ValueError, aud.error):
                self.failed.add(key)
                self.error = f"Could not load {Path(key[0]).name}"
                continue
            self.cache[key] = (sound, pcm)
            self.cache_size += pcm.nbytes
            while self.cache_size > CACHE_LIMIT and len(self.cache) > 1:
                _, (_, dropped) = self.cache.popitem(last=False)
                self.cache_size -= dropped.nbytes

    def voice(self, sound):
        try:
            if self.device is None:
                self.device = aud.Device()
            return self.device.play(sound)
        except (RuntimeError, aud.error) as exc:
            self.error = f"Audio output unavailable ({exc})"
            return None

    def play(self, cue, count=1, preview=None, *, wheel=False):
        paths = (preview,) if preview is not None else self.paths.get(cue, ())
        if self.volume <= 0 or not paths:
            return
        now = perf_counter()
        for _ in range(count):
            path = choice(paths)
            if wheel:
                self.wheel.append((now, path))
                continue
            prepared = self.request((path, None))
            if prepared is None:
                if (path, None) not in self.failed:
                    self.pending.append((now + 1.5, path))
            else:
                self.one_shot(prepared[0])

    def one_shot(self, sound, delay=0):
        if delay > 0:
            sound = sound.delay(delay)
        voice = self.voice(sound)
        if voice is not None:
            voice.volume = self.volume
            self.shots.append(voice)

    def motion(self, cue, dx, dy, now):
        paths = self.paths.get(cue, ())
        if self.volume <= 0 or not paths or (dx == 0 and dy == 0):
            return
        if self.gesture is None or self.gesture["cue"] != cue:
            self.stop_motion(now)
            self.gesture = {
                "cue": cue, "path": choice(paths), "last": now, "sample": now,
                "distance": 0.0, "pitch": None, "rate": None, "turn_until": 0.0,
                "restart": False, "heading": None, "leg": (0, 0), "voice": None,
                "band": None, "length": 0.0, "started": now,
            }
        state = self.gesture
        state["last"] = now
        state["distance"] += hypot(dx, dy)
        if cue == "move":
            x, y = state["leg"]
            x += dx
            y += dy
            if x * x + y * y < 16:
                state["leg"] = (x, y)
                return
            prior = state["heading"]
            state["heading"], state["leg"] = (x, y), (0, 0)
            if prior:
                cosine = (x * prior[0] + y * prior[1]) / (hypot(x, y) * hypot(*prior))
                if cosine < -0.35:
                    state["turn_until"] = now + FADE
                    state["restart"] |= cosine < -0.9396926208

    def stop_motion(self, now=None):
        if self.gesture and self.gesture["voice"]:
            handle = self.gesture["voice"]
            self.tails.append((handle, now if now is not None else perf_counter(), handle.volume))
        self.gesture = None

    def update_motion(self, now):
        state = self.gesture
        if not state:
            return
        if now - state["last"] >= IDLE:
            self.stop_motion(now)
            return
        dt = max(0.008, now - state["sample"])
        if state["distance"]:
            speed = state["distance"] / dt
            lo, hi, p0, p1, r0, r1 = self.bounds
            turning = now < state["turn_until"]
            amount = 0 if turning else min(1, max(0, (speed - lo) / max(1, hi - lo)))
            pitch = 2 ** min(16, max(-16, (p0 + (p1 - p0) * amount) / 12))
            rate = max(0.05, r0 + (r1 - r0) * amount)
            mix = 1 if turning or state["pitch"] is None else 1 - exp(-dt / FADE)
            state["pitch"] = (state["pitch"] or pitch) * (1 - mix) + pitch * mix
            state["rate"] = (state["rate"] or rate) * (1 - mix) + rate * mix
            state["distance"], state["sample"] = 0.0, now
        if state["pitch"] is None:
            return
        turning = now < state["turn_until"]
        old = state["voice"]
        if turning and state["restart"]:
            if old:
                self.tails.append((old, now - FADE * 0.6, old.volume))
                state["voice"] = None
            return
        if state["restart"]:
            state["restart"] = False
            state["band"] = None
        # Native pitch can change continuously. Compensate its effect on tempo
        # with a cached time-stretched version of the same source loop.
        band = max(-48, min(48, round(12 * log2(state["rate"] / state["pitch"]))))
        ready = self.request((state["path"], band))
        actual_band = band
        if not ready and not old:
            ready = self.request((state["path"], 0))
            actual_band = 0
        if ready and (not old or state["band"] != actual_band):
            new = self.voice(ready[0])
            if new:
                new.loop_count = -1
                new.volume = 0
                length = ready[1].size / SAMPLE_RATE
                if old and old.status:
                    new.position = (old.position / state["length"]) % 1.0 * length
                    self.tails.append((old, now, old.volume))
                state["voice"], state["band"], state["length"], state["started"] = new, actual_band, length, now
                old = new
        if old:
            old.pitch = state["pitch"]
            gain = 0.2 if turning else 1
            old.volume = self.volume * 0.55 * gain * min(1, (now - state["started"]) / FADE)

    def play_wheel(self, now):
        # Real notches can arrive in a single Blender input batch. Offset their
        # starts in the mixer so the transients stay distinct even when they overlap.
        for _ in range(min(WHEEL_BATCH, len(self.wheel))):
            queued, path = self.wheel[0]
            key = path, None
            if key not in self.failed:
                prepared = self.request(key)
                if not prepared and now < queued + 1.5:
                    break
                if prepared:
                    start = max(self.next_wheel, now)
                    self.one_shot(prepared[0], start - now)
                    self.next_wheel = start + WHEEL_SPACING
            self.wheel.popleft()

    def tick(self, now):
        if self.jobs:
            self.collect()
        if self.wheel:
            self.play_wheel(now)
        if self.pending:
            rest = []
            for expiry, path in self.pending:
                if now > expiry or (path, None) in self.failed:
                    continue
                prepared = self.request((path, None))
                if prepared:
                    self.one_shot(prepared[0])
                else:
                    rest.append((expiry, path))
            self.pending = rest
        if self.shots:
            self.shots = [handle for handle in self.shots if handle.status]
        if self.gesture:
            self.update_motion(now)
        if not self.tails:
            return
        tails = []
        for handle, start, gain in self.tails:
            remaining = 1 - (now - start) / FADE
            if remaining <= 0 or not handle.status:
                handle.stop()
            else:
                handle.volume = gain * remaining
                tails.append((handle, start, gain))
        self.tails = tails

    def clear(self):
        self.stop_motion()
        for handle in self.shots:
            handle.stop()
        for handle, _, _ in self.tails:
            handle.stop()
        self.shots.clear()
        self.tails.clear()
        self.pending.clear()
        self.wheel.clear()
        self.next_wheel = 0.0

    def close(self):
        self.clear()
        if self.worker:
            self.worker.shutdown(wait=False, cancel_futures=True)
        self.worker = None
        self.jobs.clear()
        self.cache.clear()
        self.cache_size = 0
        self.device = None
