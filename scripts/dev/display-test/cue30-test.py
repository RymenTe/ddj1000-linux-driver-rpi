#!/usr/bin/env python3
"""Re-upload the track on a deck with test cues in report 0x30 01 (format from DDJ1000-Hotcue.pcapng):
payload = length(mm ss ms16) + up to 7 entries [type][colour][mm][ss][ms u16 LE] (from byte 10),
own slot at byte 52 (assumed main cue). Run while ddj1000-bridge.py runs (heartbeat).
Cue spec: type:colour:seconds, hex type/colour, e.g. 01:16:30 = type 1, colour 0x16 at 0:30.
usage: cue30-test.py --length-ms 304615 --bpm 155.84 --cues 01:16:30,01:01:60,01:24:90,02:24:120 --main 01:16:10"""
import argparse, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))
import ddj1000_display as d
import ddj1000_mixxx_track as mt


def entry(spec):
    t, c, sec = spec.split(":")
    return bytes([int(t, 16), int(c, 16)]) + d.length_field(float(sec) * 1000)


ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--deck", type=int, default=1)
ap.add_argument("--length-ms", type=float, required=True)
ap.add_argument("--bpm", type=float, required=True)
ap.add_argument("--cues", default="01:16:30,01:01:60,01:24:90,02:24:120")
ap.add_argument("--main", default="01:16:10", help="entry at byte 52, '' = none")
a = ap.parse_args()
info = mt.TrackLookup(print).find(a.length_ms, a.bpm)
if not info:
    sys.exit("track not found")
entries = [entry(s) for s in a.cues.split(",") if s][:7]
payload = bytearray(d.length_field(a.length_ms) + b"".join(entries))
if a.main:
    payload = payload.ljust(46, b"\0") + entry(a.main)   # byte 52 of the report = payload byte 46
reps = d.track_upload(a.deck, a.length_ms, info["beats"], info["waveform"])
lf_only = d.single(a.deck, 0x30, d.length_field(a.length_ms), index=1, count=2)
reps = [d.single(a.deck, 0x30, bytes(payload), index=1, count=2) if r == lf_only else r for r in reps]
fd = os.open(d.find_hidraw(), os.O_WRONLY)
for r in reps:
    os.write(fd, b"\0" + r); time.sleep(0.001)
os.close(fd)
print(f"uploaded '{info['title']}', 30 01 =", d.single(a.deck, 0x30, bytes(payload), 1, 2)[:58].hex(" "))
