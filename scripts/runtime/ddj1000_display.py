"""DDJ-1000 jog display HID reports (EP 0x06, 64 B), decoded from rekordbox captures.

See docs/research-jog-display-and-hw-mixer.md ("Zweiter Mitschnitt"). Report layout:
byte 0 = deck << 4 (0x10..0x40), byte 1 = command, byte 2 = block index (1..n), byte 3 = 0,
byte 4 = block count n, byte 5 = 0, payload from byte 6 (58 bytes per block).
Status 0x21 is a single report with its own layout (byte 2 = flags).

Writing to /dev/hidrawN needs a leading 0x00 (no report IDs in the descriptor).
The display only shows this while the host heartbeat (50 01) runs.
"""

import os

REPORT_SIZE = 64
PAYLOAD = 58
WAVEFORM_POINTS = 600

# filler point after the end of the track, as sent by rekordbox (grey/white, height 1)
WAVEFORM_PAD = bytes.fromhex("00 f7 bd ff ff 01 01")
EMPTY_CUE = bytes.fromhex("00 9e 2f 27 01")


def deck_byte(deck):
    return (deck & 0x0F) << 4


def length_field(length_ms):
    """mm ss ms(u16 LE) as used in 0x30 01, 0x2d and 0x21 (bytes 15-18)."""
    length_ms = max(0, int(length_ms))
    minutes, rest = divmod(length_ms, 60000)
    seconds, ms = divmod(rest, 1000)
    return bytes([min(minutes, 255), seconds]) + ms.to_bytes(2, "little")


def single(deck, cmd, payload=b"", index=1, count=1):
    rep = bytes([deck_byte(deck), cmd, index, 0, count, 0]) + payload
    return rep[:REPORT_SIZE].ljust(REPORT_SIZE, b"\0")


def series(deck, cmd, data):
    """Split data into 58-byte blocks of one series (index 1..n, count n)."""
    blocks = [data[i:i + PAYLOAD] for i in range(0, len(data), PAYLOAD)] or [b""]
    n = len(blocks)
    return [single(deck, cmd, blk, i + 1, n) for i, blk in enumerate(blocks)]


def beatgrid_bytes(beats):
    """beats: list of (beat_in_bar 1..4, position_ms)."""
    out = bytearray(len(beats).to_bytes(2, "little"))
    for beat, pos in beats:
        out.append(beat & 0xFF)
        out += int(pos).to_bytes(3, "little")
    return bytes(out)


def constant_beatgrid(bpm, length_ms, first_beat_ms=0.0, first_beat_in_bar=1):
    beats = []
    if bpm <= 0:
        return beats
    step = 60000.0 / bpm
    t = first_beat_ms
    b = first_beat_in_bar
    while t <= length_ms:
        beats.append((b, round(t)))
        t += step
        b = b % 4 + 1
    return beats


def waveform_bytes(points):
    """points: list of 7-byte records [flag, col1 RGB565 LE, col2 RGB565 LE, h1, h2]; padded to 600."""
    pts = list(points[:WAVEFORM_POINTS])
    out = bytearray()
    for i, p in enumerate(pts):
        rec = bytearray(p)
        rec[0] = 0x80 if i == 0 else 0x00
        out += rec
    out += WAVEFORM_PAD * (WAVEFORM_POINTS - len(pts))
    return bytes(out)


def rgb565(r, g, b):
    """r, g, b 0..255 -> 2 bytes little endian."""
    v = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
    return v.to_bytes(2, "little")


def track_upload(deck, length_ms, beats, waveform=None):
    """Report sequence rekordbox sends on track load: 30 01/02, 2f grid, 30 02/01/02, 2d, 2b, 2c waveform."""
    lf = length_field(length_ms)
    reps = [single(deck, 0x30, index=1, count=2), single(deck, 0x30, index=2, count=2)]
    reps += series(deck, 0x2F, beatgrid_bytes(beats))
    reps += [single(deck, 0x30, index=2, count=2),
             single(deck, 0x30, lf, index=1, count=2),
             single(deck, 0x30, index=2, count=2)]
    cues = lf + bytes([10]) + EMPTY_CUE * 10
    reps.append(single(deck, 0x2D, cues))
    reps.append(single(deck, 0x2B))  # 10 2b 01 00 01 (rekordbox sends it before the waveform)
    reps += series(deck, 0x2C, waveform_bytes(waveform or []))
    return reps


def bpm_field(bpm):
    """bytes 21-22 / 38-39: integer BPM, then tenths in the high nibble (0x9f 0x00 = 159.0,
    0x95 0x60 = 149.6) - confirmed on the device for the integer part, tenths assumed."""
    bpm = max(0.0, min(255.9, float(bpm)))
    whole = int(bpm)
    tenth = int(round((bpm - whole) * 10))
    if tenth == 10:
        whole, tenth = min(255, whole + 1), 0
    return bytes([whole, tenth << 4])


def status(deck, position_ms, length_ms, key_code=0, key_shift=0, bpm=0.0, tempo_pct=0.0,
           loaded=True, master=False, sync=False, flags=0x18, flags3=0x0A):
    """0x21 deck status (fields confirmed on the device 2026-11-09 unless noted):
    9 = 0xb4 track loaded (0 -> "not loaded"), 11-14 position mm ss ms16, 15-18 length,
    21-22 (and 38-39) BPM, 23-24 tempo in 0.01 % (int16 LE), 60 = 0x80 | key code (MIDI 9n 49 table,
    shown in Camelot notation), 61 = key variation (0x0D = 0).
    5 = 0x01 | 0x80 "MASTER" | 0x10 "SYNC" (0x20 also lights SYNC; "BEAT SYNC" bit not found yet).
    Unknown/copied from rekordbox: 2 (18, 1a when parked at cue), 3, 4, 27 (0x80, no visible effect), 58."""
    rep = bytearray(REPORT_SIZE)
    rep[0] = deck_byte(deck)
    rep[1] = 0x21
    rep[2] = flags
    rep[3] = flags3
    rep[4] = 0x11
    rep[5] = 0x01 | (0x80 if master else 0) | (0x10 if sync else 0)
    rep[9] = 0xB4 if loaded else 0x00
    rep[11:15] = length_field(position_ms)
    rep[15:19] = length_field(length_ms)
    rep[21:23] = bpm_field(bpm)
    rep[38:40] = rep[21:23]
    rep[23:25] = int(round(max(-100.0, min(100.0, tempo_pct)) * 100)).to_bytes(2, "little", signed=True)
    rep[27] = 0x80   # as rekordbox sends it; no visible effect found (2026-11-09)
    rep[58] = 0x01
    rep[60] = (0x80 | (key_code & 0x1F)) if key_code else 0x80
    rep[61] = max(1, min(0x19, 0x0D + int(key_shift)))
    return bytes(rep)


def find_hidraw(vid="2B73", pid="0020"):
    for name in sorted(os.listdir("/sys/class/hidraw")):
        try:
            uevent = open(f"/sys/class/hidraw/{name}/device/uevent").read()
        except OSError:
            continue
        if f"HID_ID=0003:0000{vid.upper()}:0000{pid.upper()}" in uevent.upper():
            return f"/dev/{name}"
    return None
