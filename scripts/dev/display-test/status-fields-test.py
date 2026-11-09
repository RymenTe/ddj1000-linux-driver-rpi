#!/usr/bin/env python3
"""Upload a synthetic 120-BPM track once, then show status phases with patched bytes (field hunting).
Each phase: fixed position (so the user can tell phases apart by the displayed time), N seconds.
usage: status-fields-test.py --deck 1 --phase "10:21=9f,22=00,38=9f,39=00" --phase "20:21=95,22=60" ...
  phase = "<start s>:<byte>=<hex>,..." (bytes of the 0x21 status report)."""
import argparse, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))
import ddj1000_display as d

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--deck", type=int, default=1)
ap.add_argument("--bpm", type=float, default=120.0)
ap.add_argument("--length", type=float, default=200.0)
ap.add_argument("--seconds", type=float, default=8.0)
ap.add_argument("--phase", action="append", default=[])
a = ap.parse_args()
dev = d.find_hidraw(); fd = os.open(dev, os.O_WRONLY)
L = a.length * 1000
for r in d.track_upload(a.deck, L, d.constant_beatgrid(a.bpm, L), []):
    os.write(fd, b"\0" + r); time.sleep(0.001)
for ph in a.phase:
    start, _, patch = ph.partition(":")
    st = bytearray(d.status(a.deck, float(start) * 1000, L, 15, 0, bpm=a.bpm, tempo_pct=6.0))
    for kv in filter(None, patch.split(",")):
        k, v = kv.split("="); st[int(k)] = int(v, 16)
    print(f"phase start={start}s: {st.hex(' ')}", flush=True)
    t0 = time.monotonic()
    while time.monotonic() - t0 < a.seconds:
        os.write(fd, b"\0" + bytes(st)); time.sleep(1 / 60)
os.close(fd)
