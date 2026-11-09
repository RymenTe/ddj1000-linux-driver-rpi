#!/usr/bin/env python3
"""Send a synthetic track to one jog display (needs a running heartbeat, e.g. ddj1000-bridge.py).

Generated with scripts/runtime/ddj1000_display.py, so it tests the decoded format, not a replay.
Example: synth-test.py --deck 1 --bpm 120 --length 200 --start 83 --key 15 --hold 25
  -> expect on deck 1: BPM 120.0 (if the display derives it from the beat grid), time running from 1:23,
     track length 3:20, key code 15 (= G).
--waveform FILE: 4200-byte waveform from a capture (else a synthetic ramp in three colours).
"""

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))
import ddj1000_display as d  # noqa: E402


def synthetic_waveform():
    pts = []
    for i in range(600):
        h = 4 + (i % 100) * 36 // 100
        if i < 200:
            c1, c2 = d.rgb565(0, 60, 200), d.rgb565(80, 140, 255)
        elif i < 400:
            c1, c2 = d.rgb565(200, 120, 0), d.rgb565(255, 190, 60)
        else:
            c1, c2 = d.rgb565(0, 180, 60), d.rgb565(120, 255, 140)
        pts.append(b"\0" + c1 + c2 + bytes([h, h * 2 // 3]))
    return pts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--deck", type=int, default=1)
    ap.add_argument("--bpm", type=float, default=120.0)
    ap.add_argument("--length", type=float, default=200.0, help="track length in s")
    ap.add_argument("--start", type=float, default=83.0, help="start position in s")
    ap.add_argument("--key", type=int, default=15, help="key code 1..24 (MIDI 9n 49 table), 0 = none")
    ap.add_argument("--key-shift", type=int, default=0)
    ap.add_argument("--hold", type=float, default=25.0)
    ap.add_argument("--no-play", action="store_true", help="keep the position still")
    ap.add_argument("--waveform", default="")
    ap.add_argument("--hidraw", default="")
    a = ap.parse_args()

    dev = a.hidraw or d.find_hidraw()
    if not dev:
        sys.exit("DDJ-1000 hidraw not found")
    length_ms = a.length * 1000
    beats = d.constant_beatgrid(a.bpm, length_ms)
    if a.waveform:
        raw = Path(a.waveform).read_bytes()[:4200]
        wf = [raw[i:i + 7] for i in range(0, len(raw), 7)]
    else:
        wf = synthetic_waveform()
    reps = d.track_upload(a.deck, length_ms, beats, wf)
    fd = os.open(dev, os.O_WRONLY)
    print(f"{dev}: deck {a.deck}, {len(beats)} beats @ {a.bpm} BPM, length {a.length}s, {len(reps)} reports")
    pos = a.start * 1000
    st = d.status(a.deck, pos, length_ms, a.key, a.key_shift, bpm=a.bpm)
    for r in reps:
        os.write(fd, b"\0" + r)
        time.sleep(0.001)
    t0 = time.monotonic()
    while time.monotonic() - t0 < a.hold:
        cur = pos + (0 if a.no_play else (time.monotonic() - t0) * 1000)
        os.write(fd, b"\0" + d.status(a.deck, cur, length_ms, a.key, a.key_shift, bpm=a.bpm))
        time.sleep(1 / 60)
    os.close(fd)
    print("done; first status:", st.hex())


if __name__ == "__main__":
    main()
