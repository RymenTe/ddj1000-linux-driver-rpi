#!/usr/bin/env python3
# usage: hid-replay.py <dump.txt> <hidraw> <deck-prefix 10/20> <t_from> <t_to> <hold_seconds>
# Replays HID-OUT reports of one deck from a usbpcap dump with original timing; then repeats the
# last 0x21 status report at ~60 Hz for hold_seconds. Only writes to hidraw (EP 0x06), no MIDI.
import os, sys, time
dump, dev, dk, a, b, hold = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4]), float(sys.argv[5]), float(sys.argv[6])
seq = []
for line in open(dump):
    t, ep, h = line.split()
    if ep == '06' and h.startswith(dk) and a <= float(t) <= b:
        seq.append((float(t), bytes.fromhex(h)))
print('reports', len(seq), 'span %.2fs' % (seq[-1][0] - seq[0][0]))
fd = os.open(dev, os.O_WRONLY)
t0 = time.monotonic(); c0 = seq[0][0]; last21 = None; n = 0
for t, d in seq:
    dt = (t - c0) - (time.monotonic() - t0)
    if dt > 0: time.sleep(dt)
    os.write(fd, b'\x00' + d); n += 1
    if d[1] == 0x21: last21 = d
print('sent', n)
end = time.monotonic() + hold
while last21 and time.monotonic() < end:
    os.write(fd, b'\x00' + last21); time.sleep(1/60)
os.close(fd); print('done')
