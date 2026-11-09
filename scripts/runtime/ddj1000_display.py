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


def cue_entry(position_ms=None, kind=0):
    """one of the 10 cue slots in 0x2d: assumed [kind][position ms u32 LE]; empty = 00 9e 2f 27 01."""
    if position_ms is None:
        return EMPTY_CUE
    return bytes([kind & 0xFF]) + int(position_ms).to_bytes(4, "little")


def track_upload(deck, length_ms, beats, waveform=None, cues=None):
    """Report sequence rekordbox sends on track load: 30 01/02, 2f grid, 30 02/01/02, 2d, 2b, 2c waveform."""
    lf = length_field(length_ms)
    reps = [single(deck, 0x30, index=1, count=2), single(deck, 0x30, index=2, count=2)]
    reps += series(deck, 0x2F, beatgrid_bytes(beats))
    reps += [single(deck, 0x30, index=2, count=2),
             single(deck, 0x30, lf, index=1, count=2),
             single(deck, 0x30, index=2, count=2)]
    slots = (list(cues or []) + [EMPTY_CUE] * 10)[:10]
    reps.append(single(deck, 0x2D, lf + bytes([10]) + b"".join(slots)))
    reps.append(single(deck, 0x2B))  # 10 2b 01 00 01 (rekordbox sends it before the waveform)
    reps += series(deck, 0x2C, waveform_bytes(waveform or []))
    return reps


# Hot-cue colour byte = index on a hue wheel (device photos 2026-11-09): code -> approx. hue in degrees,
# unwrapped downwards from blue (01 blue, 0C turquoise, 12 blue-green, 16 green, 1A yellow-green, 1E yellow,
# 24 orange, 2A red, 30 pink, 36 magenta-pink, 3C lavender). Hues are estimates from photos.
CUE_HUE_ANCHORS = ((230, 0x01), (175, 0x0C), (160, 0x12), (120, 0x16), (85, 0x1A), (60, 0x1E),
                   (35, 0x24), (0, 0x2A), (-30, 0x30), (-45, 0x36), (-80, 0x3C))
CUE_COLOUR_DEFAULT = 0x16   # green, as rekordbox uses for hot cues


def cue_colour(rgb):
    """Mixxx hot-cue colour (0xRRGGBB) -> DDJ colour code via hue, linear between the anchors."""
    import colorsys
    r, g, b = ((rgb >> 16) & 0xFF) / 255.0, ((rgb >> 8) & 0xFF) / 255.0, (rgb & 0xFF) / 255.0
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if s < 0.15 or v < 0.1:
        return CUE_COLOUR_DEFAULT
    hue = h * 360.0
    if hue > 230.0:
        hue -= 360.0
        if hue < -80.0:   # between lavender (280) and blue (230): nearest end
            return 0x01 if hue < -105.0 else 0x3C
    for (h1, c1), (h2, c2) in zip(CUE_HUE_ANCHORS, CUE_HUE_ANCHORS[1:]):
        if h2 <= hue <= h1:
            return int(c1 + (c2 - c1) * (h1 - hue) / (h1 - h2) + 0.5)   # = JS Math.round (mapping)
    return 0x01


def hotcue_reports(deck, length_ms, cues):
    """30 01 (length + 8 slots A-H [type][colour][mm][ss][ms16]) + empty 30 02. The pair alone updates
    the markers live; 30 01 without 30 02 clears them (device tests 2026-11-09).
    cues: list of 8 entries, None or (type, colour code, position ms)."""
    payload = bytearray(length_field(length_ms))
    for c in (list(cues) + [None] * 8)[:8]:
        payload += bytes(6) if c is None else bytes([c[0] & 0xFF, c[1] & 0xFF]) + length_field(c[2])
    return [single(deck, 0x30, bytes(payload), index=1, count=2), single(deck, 0x30, index=2, count=2)]


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
           loaded=True, master=False, sync=False, flags=0x18, flags3=0x0A, loop=None):
    """0x21 deck status (fields confirmed on the device 2026-11-09 unless noted):
    9 = 0xb4 track loaded (0 -> "not loaded"), 11-14 position mm ss ms16, 15-18 length,
    21-22 (and 38-39) BPM, 23-24 tempo in 0.01 % (int16 LE), 60 = 0x80 | key code (MIDI 9n 49 table,
    shown in Camelot notation), 61 = key variation (0x0D = 0).
    5 = 0x01 | 0x80 "MASTER" | 0x10 "SYNC" (0x20 also lights SYNC; "BEAT SYNC" bit not found yet).
    9 bit 3 (0xbc) = loop active,
    25-27 loop start ms (u24 LE, bit 7 of byte 27 = loop not active), 28-30 loop end ms (u24 LE); no loop =
    00 00 80 / 0 (rekordbox capture DDJ1000-Hotcue: LOOP IN -> start|0x800000, LOOP OUT -> end, running -> bit cleared).
    loop = None or (start ms or None, end ms or None, active).
    Unknown/copied from rekordbox: 2 (18, 1a when parked at cue), 3, 4, 58."""
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
    start, end, active = loop if loop else (None, None, False)
    start_field = (int(start) & 0x7FFFFF) if start is not None else 0
    if not (active and start is not None and end is not None):
        start_field |= 0x800000
    elif loaded:
        rep[9] |= 0x08   # loop active: rekordbox sets b4 -> bc right before filling the loop field
    rep[25:28] = start_field.to_bytes(3, "little")
    rep[28:31] = (int(end) & 0xFFFFFF).to_bytes(3, "little") if (start is not None and end is not None) else bytes(3)
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
