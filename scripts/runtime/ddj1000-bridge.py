#!/usr/bin/env python3
"""DDJ-1000 bridge: owns the DDJ rawmidi port and forwards MIDI to Mixxx via a snd-virmidi port.

Why: the jog displays only show HID data while the host heartbeat (50 01) runs without a gap,
and a heartbeat that starts anew forces a new unlock (docs/research-jog-display-and-hw-mixer.md).
So one process must do unlock + heartbeat + (later) display, and therefore owns the rawmidi FD
(rawmidi is exclusive, CLAUDE.md rule 4). Mixxx talks to the kernel virtual MIDI port of the
snd-virmidi card (id "DDJBridge", e.g. `modprobe snd-virmidi index=7 id=DDJBridge midi_devs=1`),
which the bridge reads/writes as a second rawmidi device (python-rtmidi virtual ports lost their
input thread under Mixxx's startup burst, 2026-11-09).

Step 1 (this version): unlock, gapless heartbeat, MIDI forwarding in both directions.
- exactly one rawmidi FD (O_RDWR) for reading and writing; every message is written with one
  os.write, so SysEx from Mixxx reaches the DDJ in one USB bulk transfer
- messages from Mixxx are only queued by the reader; one writer thread sends heartbeat first, then
  the queue, and only when the DDJ rawmidi buffer is writable. While a backlog exists, a newer short
  message with the same status+data1 (e.g. jog display time/position) replaces the queued one.
- unlock SysEx (11 02, 13 2a, 15 02) is handled here and not forwarded; heartbeat/handshake SysEx
  coming from Mixxx is dropped (the bridge owns the session)
- no libusb, no interface claim (rule 5); the optional driver-presence read uses usbfs only
"""

import argparse
import importlib.util
import os
import select
import signal
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path

HERE = Path(__file__).resolve().parent
UNLOCK_TEST_PATH = HERE.parent / "dev" / "ddj1000-unlock-test.py"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ut = load_module("ddj1000_unlock_test", UNLOCK_TEST_PATH)
p = ut.load_protocol()

SYSEX_HEAD = bytes.fromhex("f0 00 40 05 00 00 02 00 00")
# SysEx commands (byte after the header) the bridge owns; never forwarded from Mixxx to the DDJ
HOST_SESSION_COMMANDS = {0x50, 0x12, 0x14}
# Pad mode buttons (DDJ-1000RB MIDI Messages, 9n): HOT CUE 1B, PAD FX1 1E, BEAT JUMP 20, SAMPLER 22,
# +SHIFT: BEAT LOOP 69, PAD FX2 6B, KEY SHIFT 6D, KEYBOARD 6F. In a heartbeat (rekordbox-style) session
# the DDJ only switches the pad mode when the host echoes the button (MIDI-OUT "same as MIDI-IN").
PAD_MODE_NOTES = (0x1B, 0x1E, 0x20, 0x22, 0x69, 0x6B, 0x6D, 0x6F)


def channel_message_length(status):
    high = status & 0xF0
    if high in (0xC0, 0xD0):
        return 2
    if 0x80 <= high <= 0xE0:
        return 3
    return {0xF1: 2, 0xF2: 3, 0xF3: 2}.get(status, 1)


class MidiParser:
    """Turn the rawmidi byte stream into complete MIDI messages (with running status)."""

    def __init__(self):
        self.sysex = None
        self.running = None
        self.msg = []

    def feed(self, data):
        out = []
        for b in data:
            if b >= 0xF8:  # realtime, may appear anywhere
                out.append(bytes([b]))
                continue
            if b == 0xF0:
                self.sysex = bytearray([b])
                continue
            if self.sysex is not None:
                if b == 0xF7:
                    self.sysex.append(b)
                    out.append(bytes(self.sysex))
                    self.sysex = None
                elif b & 0x80:  # status byte aborts sysex
                    self.sysex = None
                else:
                    self.sysex.append(b)
                    continue
            if b & 0x80:
                self.running = b if b < 0xF0 else None
                self.msg = [b]
            elif self.msg or self.running is not None:
                if not self.msg:
                    self.msg = [self.running]
                self.msg.append(b)
            else:
                continue
            if self.msg and len(self.msg) >= channel_message_length(self.msg[0]):
                out.append(bytes(self.msg))
                self.msg = []
        return out


class Bridge:
    def __init__(self, args):
        self.args = args
        self.start = time.monotonic()
        self.lock = threading.Lock()
        self.fd = None
        self.vfd = None
        self.ack_at = None
        self.handshake_at = -1e9
        self.heartbeats = 0
        self.stats = {"ddj_to_mixxx": 0, "mixxx_to_ddj": 0, "dropped_from_mixxx": 0, "coalesced": 0,
                      "max_backlog": 0, "unlocks": 0}
        self.queue = OrderedDict()   # key -> bytes; short msgs keyed by (status, data1)
        self.queue_cv = threading.Condition()
        self.seq = 0
        self.stop = threading.Event()

    def log(self, msg):
        print(f"[{time.monotonic() - self.start:9.3f}] {msg}", flush=True)

    def write(self, payload):
        """Blocking write of one complete message with a single os.write where possible."""
        with self.lock:
            view = memoryview(payload)
            while view:
                select.select([], [self.fd], [], 0.1)
                try:
                    view = view[os.write(self.fd, view):]
                except BlockingIOError:
                    continue

    def enqueue(self, msg):
        with self.queue_cv:
            if msg[0] < 0xF0 and len(msg) == 3:
                key = (msg[0], msg[1])
                if key in self.queue:
                    self.stats["coalesced"] += 1
                self.queue[key] = msg          # keeps position of the first queued one
            else:
                self.seq += 1
                self.queue[("x", self.seq)] = msg
            if len(self.queue) > self.stats["max_backlog"]:
                self.stats["max_backlog"] = len(self.queue)
            self.queue_cv.notify()

    def writer(self):
        interval = self.args.heartbeat_ms / 1000.0
        next_hb = 0.0
        while not self.stop.is_set():
            now = time.monotonic()
            if now >= next_hb:
                self.write(p.KEEPALIVE_MESSAGE)
                self.heartbeats += 1
                next_hb = now + interval
                continue
            with self.queue_cv:
                if not self.queue:
                    self.queue_cv.wait(timeout=max(0.0, next_hb - now))
                    continue
                _key, msg = self.queue.popitem(last=False)
            try:
                self.write(msg)
                self.stats["mixxx_to_ddj"] += 1
            except OSError as exc:
                self.log(f"WARN write to DDJ failed: {exc}")

    # --- Mixxx -> DDJ: only queue, never block
    def from_mixxx(self, msg):
        if msg.startswith(SYSEX_HEAD) and len(msg) > len(SYSEX_HEAD) and msg[len(SYSEX_HEAD)] in HOST_SESSION_COMMANDS:
            self.stats["dropped_from_mixxx"] += 1
            return
        self.enqueue(msg)

    def set_pad_mode(self, deck, note):
        for n in PAD_MODE_NOTES:
            self.write(bytes([0x90 | deck, n, 0x7F if n == note else 0x00]))

    # --- DDJ -> bridge / Mixxx
    def handle_ddj_message(self, msg):
        if msg == p.READY_MESSAGE:
            if self.ack_at is not None:
                self.log("RX 11 02 ready although unlocked -> session lost, unlocking again")
                self.ack_at = None
            if time.monotonic() - self.handshake_at >= self.args.handshake_cooldown_s:
                for prelude in p.PRELUDE_MESSAGES:
                    self.write(prelude)
                self.write(p.HANDSHAKE_REQUEST)
                self.handshake_at = time.monotonic()
                self.log("RX 11 02 ready -> TX prelude + 12 2a")
            return
        if p.is_ddj_device_challenge(msg):
            seed_e = p.extract_ddj_seed_e(msg)
            if seed_e:
                self.write(p.build_ddj_handshake_response(seed_e))
                self.log("RX 13 2a challenge -> TX 14 38")
            return
        if msg.startswith(p.DDJ_ACK_PREFIX):
            self.ack_at = time.monotonic()
            self.stats["unlocks"] += 1
            self.log("RX 15 02 ACK -> UNLOCKED")
            for deck in range(4):
                self.set_pad_mode(deck, 0x1B)
            self.log("pad mode HOT CUE set on deck 1-4")
            return
        if (len(msg) == 3 and msg[0] & 0xF0 == 0x90 and (msg[0] & 0x0F) < 4
                and msg[1] in PAD_MODE_NOTES and msg[2] == 0x7F):
            self.set_pad_mode(msg[0] & 0x0F, msg[1])
            if self.args.log_pad_mode:
                self.log(f"pad mode deck {(msg[0] & 0x0F) + 1} -> 0x{msg[1]:02X}")
        self.to_mixxx(msg)

    def to_mixxx(self, msg):
        view = memoryview(msg)
        deadline = time.monotonic() + 0.05
        while view and time.monotonic() < deadline:
            try:
                view = view[os.write(self.vfd, view):]
            except BlockingIOError:
                select.select([], [self.vfd], [], 0.01)
        if view:
            self.stats["dropped_to_mixxx"] = self.stats.get("dropped_to_mixxx", 0) + 1
        else:
            self.stats["ddj_to_mixxx"] += 1

    def run(self):
        a = self.args
        port = a.midi_port or ut.detect_midi_port()
        if not port:
            self.log("No DDJ-1000 MIDI port found (amidi -l)")
            return 2
        path = ut.rawmidi_path(port)
        if a.driver_read:
            try:
                reply = ut.driver_presence_read(ut.usb_device_node_for_rawmidi(path))
                self.log(f"driver-presence read: {reply.hex(' ') or '(empty)'}")
            except OSError as exc:
                self.log(f"WARN driver-presence read failed: {exc}")

        self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        self.log(f"opened {path} ({port}) O_RDWR")

        vcard = find_card(a.virmidi_id)
        if vcard is None:
            self.log(f"No snd-virmidi card with id '{a.virmidi_id}' (/proc/asound/cards) - load snd-virmidi first")
            os.close(self.fd)
            return 2
        vpath = f"/dev/snd/midiC{vcard}D0"
        self.vfd = os.open(vpath, os.O_RDWR | os.O_NONBLOCK)
        self.log(f"opened {vpath} (snd-virmidi '{a.virmidi_id}', Mixxx port 'VirMIDI {vcard}-0')")

        signal.signal(signal.SIGINT, lambda *_: self.stop.set())
        signal.signal(signal.SIGTERM, lambda *_: self.stop.set())
        writer = threading.Thread(target=self.writer, name="writer", daemon=True)
        writer.start()

        parser = MidiParser()
        vparser = MidiParser()
        next_stats = time.monotonic() + a.stats_interval_s
        rc = 0
        try:
            while not self.stop.is_set():
                now = time.monotonic()
                if a.stats_interval_s > 0 and now >= next_stats:
                    state = "unlocked" if self.ack_at is not None else "LOCKED"
                    self.log(f"stats {state} heartbeats={self.heartbeats} backlog={len(self.queue)} {self.stats}")
                    next_stats = now + a.stats_interval_s
                readable, _, _ = select.select([self.fd, self.vfd], [], [], 0.05)
                for rfd in readable:
                    try:
                        data = os.read(rfd, 4096)
                    except BlockingIOError:
                        continue
                    if rfd == self.fd:
                        for msg in parser.feed(data):
                            self.handle_ddj_message(msg)
                    else:
                        for msg in vparser.feed(data):
                            self.from_mixxx(msg)
        except OSError as exc:
            self.log(f"ERROR rawmidi: {exc}")
            rc = 1
        finally:
            self.stop.set()
            with self.queue_cv:
                self.queue_cv.notify_all()
            writer.join(timeout=1.0)
            os.close(self.vfd)
            os.close(self.fd)
            self.log(f"closed; heartbeats={self.heartbeats} {self.stats}")
        return rc


def find_card(card_id):
    """Card number for an ALSA card id from /proc/asound/cards (rule 6: never hard-code numbers)."""
    for line in Path("/proc/asound/cards").read_text().splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].isdigit() and parts[1] == f"[{card_id}":
            return int(parts[0])
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].startswith("[") and parts[1].strip("[]") == card_id:
            return int(parts[0])
    return None


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--midi-port", default="", help="DDJ rawmidi port, e.g. hw:3,0,0 (default: amidi -l)")
    ap.add_argument("--virmidi-id", default="DDJBridge", help="ALSA card id of the snd-virmidi card for Mixxx")
    ap.add_argument("--heartbeat-ms", type=float, default=200.0)
    ap.add_argument("--handshake-cooldown-s", type=float, default=2.0)
    ap.add_argument("--driver-read", action="store_true", help="vendor driver-presence read before opening MIDI")
    ap.add_argument("--log-pad-mode", action="store_true", help="log every pad mode change")
    ap.add_argument("--stats-interval-s", type=float, default=30.0, help="0 = no periodic stats")
    return ap.parse_args()


if __name__ == "__main__":
    sys.exit(Bridge(parse_args()).run())
