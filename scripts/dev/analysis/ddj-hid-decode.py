#!/usr/bin/env python3
# usage: python3 -I ddj-hid-decode.py <dump.txt from usbpcap-hid-dump.py> <deck 1-4> <t_from> <t_to>
# Decodes one HID-OUT upload (EP 0x06) of a track load (rekordbox -> DDJ-1000 jog display), see
# docs/research-jog-display-and-hw-mixer.md - Blocks: byte0 deck<<4, byte1 cmd, byte2 index, byte4 count, payload from byte 6.
import sys
dump, deck, a, b = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
pre = '%x0' % deck
def series(cmd):
    out = b''
    for line in open(dump):
        t, ep, h = line.split()
        if ep == '06' and h.startswith(pre + cmd) and a < float(t) < b:
            out += bytes.fromhex(h)[6:]
    return out
g = series('2f')
if g:
    n = int.from_bytes(g[0:2], 'little')
    beats = [(g[i], int.from_bytes(g[i+1:i+4], 'little')) for i in range(2, 2 + 4*n, 4)]
    span = beats[-1][1] - beats[0][1]
    print('beatgrid: %d beats, first %s, last %s, avg %.2f BPM' % (n, beats[0], beats[-1], 60000.0*(n-1)/span if span else 0))
w = series('2c')
if w:
    recs = [w[i:i+7] for i in range(0, min(len(w), 4200), 7)]
    h1 = [r[5] for r in recs]
    print('waveform: %d points, height max %d' % (len(recs), max(h1)))
    print(''.join(' .:-=+*#%@'[min(9, v*10//(max(h1)+1))] for v in h1[::5]))
