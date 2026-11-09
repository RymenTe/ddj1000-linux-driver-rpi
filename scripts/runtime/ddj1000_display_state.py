"""Deck state from Mixxx -> DDJ-1000 jog displays (HID), used by ddj1000-bridge.py.

The Mixxx mapping sends one SysEx per deck about 20x/s (never forwarded to the DDJ):
  F0 7D 44 42 01 <deck 0-3> <flags> <pos ms:4> <len ms:4> <file bpm*100:3> <bpm*100:3>
     <tempo*100 + 2^20:3> <key 0-24 (Mixxx)> <key shift + 12> <first beat ms:3> F7
  numbers as little-endian 7-bit groups; flags bit0 loaded, bit1 playing, bit2 sync leader, bit3 sync on.
"""

import os
import threading
import time

import ddj1000_display as d
import ddj1000_mixxx_track as mt

SYSEX_PREFIX = bytes([0xF0, 0x7D, 0x44, 0x42])
TEMPO_OFFSET = 1 << 20


def dec7(data, pos, n):
    v = 0
    for i in range(n):
        v |= (data[pos + i] & 0x7F) << (7 * i)
    return v, pos + n


def mixxx_key_to_ddj(key):
    """Mixxx key 1-12 = C..B major, 13-24 = C..B minor -> DDJ table (*3): 1 C, 2 Am, 3 Db, 4 Bbm ..."""
    key = int(key)
    if 1 <= key <= 12:
        return 1 + 2 * (key - 1)
    if 13 <= key <= 24:
        return 2 + 2 * (((key - 13) + 3) % 12)
    return 0


def parse_state(msg):
    if not msg.startswith(SYSEX_PREFIX) or len(msg) < 30 or msg[4] != 0x01:
        return None
    p = 5
    deck = msg[p]; p += 1
    flags = msg[p]; p += 1
    pos, p = dec7(msg, p, 4)
    length, p = dec7(msg, p, 4)
    fbpm, p = dec7(msg, p, 3)
    bpm, p = dec7(msg, p, 3)
    tempo, p = dec7(msg, p, 3)
    key = msg[p]; p += 1
    shift = msg[p] - 12; p += 1
    first, p = dec7(msg, p, 3)
    return {"deck": deck + 1, "loaded": bool(flags & 1), "playing": bool(flags & 2), "leader": bool(flags & 4), "sync": bool(flags & 8),
            "pos": float(pos), "len": float(length), "file_bpm": fbpm / 100.0, "bpm": bpm / 100.0,
            "tempo": (tempo - TEMPO_OFFSET) / 100.0, "key": key, "shift": shift, "first_beat": float(first),
            "t": time.monotonic()}


class DisplayManager:
    def __init__(self, log, rate_hz=30.0):
        self.log = log
        self.rate = rate_hz
        self.states = {}
        self.uploaded = {}
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.fd = None
        self.dev = None
        self.stats = {"state_msgs": 0, "uploads": 0, "status_reports": 0, "hid_errors": 0}
        self.tracks = mt.TrackLookup(log)
        self.retry = {}   # deck -> (next try, give up at) while the waveform is missing

    def on_sysex(self, msg):
        st = parse_state(msg)
        if st is None:
            return False
        with self.lock:
            self.states[st["deck"]] = st
        self.stats["state_msgs"] += 1
        return True

    def open(self):
        self.dev = d.find_hidraw()
        if not self.dev:
            self.log("display: DDJ-1000 hidraw not found - jog displays disabled")
            return False
        self.fd = os.open(self.dev, os.O_WRONLY)
        self.log(f"display: {self.dev} opened")
        return True

    def write(self, rep):
        try:
            os.write(self.fd, b"\0" + rep)
        except OSError as exc:
            self.stats["hid_errors"] += 1
            if self.stats["hid_errors"] < 5:
                self.log(f"display: WARN hid write failed: {exc}")

    def signature(self, st):
        if not st["loaded"]:
            return None
        # first_beat is not part of it: Mixxx's beat_closest jitters (and wraps at the beat length),
        # which re-uploaded the track every few seconds (2026-11-09)
        return (round(st["len"]), round(st["file_bpm"], 2))

    def upload(self, st):
        info = self.tracks.find(st["len"], st["file_bpm"])
        beats = info["beats"] if info and info["beats"] else None
        if not beats:
            beats = d.constant_beatgrid(st["file_bpm"], st["len"], st["first_beat"])
        waveform = info["waveform"] if info else None
        reps = d.track_upload(st["deck"], st["len"], beats, waveform)
        for rep in reps:
            self.write(rep)
            time.sleep(0.001)
        self.stats["uploads"] += 1
        what = (f"'{info['title']}' (id {info['id']}, {info['matches']} match(es), "
                f"waveform {'yes' if waveform else 'no'}, beatmap {'yes' if info['beats'] else 'no'})"
                if info else "not found in Mixxx DB (constant grid, no waveform)")
        self.log(f"display: deck {st['deck']} upload {st['len'] / 1000:.1f} s {st['file_bpm']:.2f} BPM: {what}")
        now = time.monotonic()
        if waveform:
            self.retry.pop(st["deck"], None)
        elif st["deck"] not in self.retry:
            self.retry[st["deck"]] = (now + 2.0, now + 120.0)
        else:
            self.retry[st["deck"]] = (now + 2.0, self.retry[st["deck"]][1])

    def run(self):
        if not self.open():
            return
        period = 1.0 / self.rate
        while not self.stop.is_set():
            t_next = time.monotonic() + period
            with self.lock:
                states = dict(self.states)
            for deck, st in sorted(states.items()):
                sig = self.signature(st)
                if sig != self.uploaded.get(deck):
                    self.retry.pop(deck, None)
                    if sig is not None:
                        self.upload(st)
                    self.uploaded[deck] = sig
                elif sig is not None and deck in self.retry:
                    nxt, give_up = self.retry[deck]
                    now = time.monotonic()
                    if now >= give_up:
                        self.retry.pop(deck, None)
                    elif now >= nxt:
                        info = self.tracks.find(st["len"], st["file_bpm"])
                        if info and info["waveform"]:
                            self.upload(st)
                        else:
                            self.retry[deck] = (now + 2.0, give_up)
                pos = st["pos"]
                if st["playing"] and st["file_bpm"] > 0:
                    pos += (time.monotonic() - st["t"]) * 1000.0 * (st["bpm"] / st["file_bpm"])
                pos = max(0.0, min(pos, st["len"]))
                self.write(d.status(deck, pos, st["len"], mixxx_key_to_ddj(st["key"]), st["shift"],
                                    bpm=st["bpm"], tempo_pct=st["tempo"], loaded=st["loaded"],
                                    master=st["leader"], sync=st["sync"]))
                self.stats["status_reports"] += 1
            self.stop.wait(max(0.0, t_next - time.monotonic()))
        if self.fd is not None:
            os.close(self.fd)
