#!/usr/bin/env python3
"""Isolated DDJ-1000 unlock test.

- exactly one rawmidi FD (os.open O_RDWR) for reading and writing (CLAUDE.md rule 4)
- no libusb, no silence stream, no rebind: MIDI only
- SysEx heartbeat every 200 ms
- logs every RX/TX SysEx with a timestamp

Expected sequence: RX 11 02 (ready) -> TX prelude + 12 2a -> RX 13 2a (challenge)
-> TX 14 38 (response) -> RX 15 02 (ACK). After the ACK the heartbeat keeps running
for --hold seconds (0 = until Ctrl+C) so audio can be tested in parallel.
"""

import argparse
import importlib.util
import os
import re
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

UNLOCK_MODULE_PATH = Path(__file__).resolve().parents[1] / "runtime" / "ddj1000-unlock-service.py"


def load_protocol():
    spec = importlib.util.spec_from_file_location("ddj1000_unlock_service", UNLOCK_MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def detect_midi_port():
    out = subprocess.run(["amidi", "-l"], check=True, capture_output=True, text=True).stdout
    for line in out.splitlines():
        match = re.match(r"^IO\s+(hw:\d+,\d+,\d+)\s+(.*DDJ-1000.*)$", line.strip())
        if match:
            return match.group(1)
    return ""


def rawmidi_path(port):
    match = re.fullmatch(r"hw:(\d+),(\d+)(?:,(\d+))?", port)
    if not match:
        raise SystemExit(f"Unsupported MIDI port format: {port}")
    card, device, sub = match.group(1), match.group(2), match.group(3) or "0"
    if sub != "0":
        raise SystemExit("Only subdevice 0 is supported (raw device node)")
    return f"/dev/snd/midiC{card}D{device}"


class Session:
    def __init__(self, fd, protocol, start):
        self.fd = fd
        self.p = protocol
        self.start = start
        self.buf = bytearray()
        self.in_sysex = False

    def log(self, msg):
        print(f"[{time.monotonic() - self.start:8.3f}] {msg}", flush=True)

    def send(self, payload, label, quiet=False):
        view = memoryview(payload)
        while view:
            written = os.write(self.fd, view)
            view = view[written:]
        if not quiet:
            self.log(f"TX {label}: {self.p.format_bytes(payload)}")

    def read_messages(self, timeout):
        """Return complete SysEx messages; short messages are reported but not returned."""
        readable, _, _ = select.select([self.fd], [], [], timeout)
        if not readable:
            return []
        data = os.read(self.fd, 4096)
        messages = []
        for byte in data:
            if byte == 0xF0:
                self.buf = bytearray([byte])
                self.in_sysex = True
            elif self.in_sysex:
                self.buf.append(byte)
                if byte == 0xF7:
                    messages.append(bytes(self.buf))
                    self.in_sysex = False
            elif byte >= 0xF8:
                continue  # realtime, ignore
        if not self.in_sysex and not messages and data:
            self.log(f"RX (non-sysex) {self.p.format_bytes(data)}")
        return messages


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--midi-port", default="", help="e.g. hw:1,0,0 (default: detect via amidi -l)")
    parser.add_argument("--device", default="", help="rawmidi node, e.g. /dev/snd/midiC1D0 (overrides --midi-port)")
    parser.add_argument("--heartbeat-ms", type=float, default=200.0)
    parser.add_argument("--timeout-s", type=float, default=20.0, help="give up if no ACK within this time")
    parser.add_argument("--hold", type=float, default=0.0, help="keep heartbeat after ACK for N s (0 = until Ctrl+C)")
    parser.add_argument("--handshake-cooldown-s", type=float, default=2.0)
    args = parser.parse_args()

    p = load_protocol()
    if args.device:
        if not re.fullmatch(r"/dev/snd/midiC\d+D\d+", args.device):
            raise SystemExit(f"Unsupported rawmidi device: {args.device}")
        path = port = args.device
    else:
        port = args.midi_port or detect_midi_port()
        if not port:
            print("No DDJ-1000 MIDI port found (amidi -l)", file=sys.stderr)
            return 2
        path = rawmidi_path(port)

    stop = {"flag": False}
    signal.signal(signal.SIGINT, lambda *_: stop.update(flag=True))
    signal.signal(signal.SIGTERM, lambda *_: stop.update(flag=True))

    fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
    start = time.monotonic()
    s = Session(fd, p, start)
    s.log(f"opened {path} ({port}) O_RDWR, heartbeat {args.heartbeat_ms:.0f} ms")

    heartbeat_interval = args.heartbeat_ms / 1000.0
    next_heartbeat = 0.0
    heartbeats = 0
    handshake_at = -1e9
    ack_at = None
    rc = 1
    try:
        while not stop["flag"]:
            now = time.monotonic()
            if now >= next_heartbeat:
                s.send(p.KEEPALIVE_MESSAGE, "heartbeat 50 01", quiet=heartbeats > 0)
                heartbeats += 1
                next_heartbeat = now + heartbeat_interval

            if ack_at is None and now - start > args.timeout_s:
                s.log(f"TIMEOUT: no ACK after {args.timeout_s:.0f} s")
                break
            if ack_at is not None and args.hold > 0 and now - ack_at >= args.hold:
                s.log(f"hold of {args.hold:.0f} s finished ({heartbeats} heartbeats total)")
                break

            for msg in s.read_messages(timeout=max(0.0, min(0.05, next_heartbeat - time.monotonic()))):
                if msg == p.READY_MESSAGE:
                    s.log("RX 11 02 ready")
                    if ack_at is None and time.monotonic() - handshake_at >= args.handshake_cooldown_s:
                        for i, prelude in enumerate(p.PRELUDE_MESSAGES):
                            s.send(prelude, f"prelude {i}")
                        s.send(p.HANDSHAKE_REQUEST, "12 2a handshake request")
                        handshake_at = time.monotonic()
                elif p.is_ddj_device_challenge(msg):
                    seed_e = p.extract_ddj_seed_e(msg)
                    s.log(f"RX 13 2a challenge seedE={seed_e.hex() or '?'}: {p.format_bytes(msg)}")
                    if seed_e:
                        s.send(p.build_ddj_handshake_response(seed_e), "14 38 response")
                elif msg.startswith(p.DDJ_ACK_PREFIX):
                    ack_at = time.monotonic()
                    s.log(f"RX 15 02 ACK -> UNLOCKED; holding heartbeat ({'Ctrl+C' if args.hold <= 0 else f'{args.hold:.0f} s'})")
                    rc = 0
                else:
                    s.log(f"RX sysex {p.format_bytes(msg)}")
    finally:
        os.close(fd)
        s.log(f"closed {path}; heartbeats sent: {heartbeats}; result: {'UNLOCKED' if rc == 0 else 'NOT UNLOCKED'}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
