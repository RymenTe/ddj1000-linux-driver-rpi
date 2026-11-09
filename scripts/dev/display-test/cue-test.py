#!/usr/bin/env python3
"""Re-upload the track currently on a deck (looked up in the Mixxx DB) with test cue slots in 0x2d.
Run while ddj1000-bridge.py runs (heartbeat). Slot k gets position (k+1)*step seconds.
usage: cue-test.py --deck 1 --length-ms 304615 --bpm 155.84 --kinds 0,0,0,0,0,1,1,1,1,1 --step 20"""
import argparse, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))
import ddj1000_display as d
import ddj1000_mixxx_track as mt

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--deck", type=int, default=1)
ap.add_argument("--length-ms", type=float, required=True)
ap.add_argument("--bpm", type=float, required=True)
ap.add_argument("--kinds", default="0,0,0,0,0,1,1,1,1,1")
ap.add_argument("--step", type=float, default=20.0)
a = ap.parse_args()
info = mt.TrackLookup(print).find(a.length_ms, a.bpm)
if not info:
    sys.exit("track not found")
kinds = [int(k, 0) for k in a.kinds.split(",")]
cues = [d.cue_entry((i + 1) * a.step * 1000, k) for i, k in enumerate(kinds)]
reps = d.track_upload(a.deck, a.length_ms, info["beats"], info["waveform"], cues)
fd = os.open(d.find_hidraw(), os.O_WRONLY)
for r in reps:
    os.write(fd, b"\0" + r); time.sleep(0.001)
os.close(fd)
print(f"uploaded '{info['title']}' with cues:", " | ".join(c.hex(" ") for c in cues))
