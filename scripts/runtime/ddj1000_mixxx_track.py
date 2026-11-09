#!/usr/bin/env python3
"""Look up the track loaded in Mixxx and build jog-display data from Mixxx's own analysis.

- track: matched in ~/.mixxx/mixxxdb.sqlite (read-only) by duration and file BPM, which the mapping
  sends in its deck-state SysEx (Mixxx scripts cannot see the file path)
- waveform: "WaveformSummary-5.0" analysis file ~/.mixxx/analysis/<track_analysis.id>
  (4-byte length + zlib + protobuf: 1 visual_sample_rate, 2 audio_visual_ratio, 3 signal_all,
  4 filtered {1 low, 2 mid, 3 high}; every signal = repeated field 1 values 0..255, stereo interleaved)
- beat grid: library.beats, "BeatMap-1.0" (protobuf, repeated field 1 Beat{1 frame_position}) or
  "BeatGrid-*" (first beat + BPM, handled via the constant grid fallback)
No external dependencies (own minimal protobuf reader).
"""

import os
import sqlite3
import struct
import zlib

import ddj1000_display as d

MIXXX_DIR = os.path.expanduser("~/.mixxx")
DB_PATH = os.path.join(MIXXX_DIR, "mixxxdb.sqlite")
HEIGHT_MAX = 40          # highest value seen from rekordbox
OUTER_GAIN = 1.0


def _varint(b, i):
    v = s = 0
    while True:
        x = b[i]
        i += 1
        v |= (x & 0x7F) << s
        s += 7
        if x < 0x80:
            return v, i


def pb_fields(b):
    i, out = 0, []
    while i < len(b):
        key, i = _varint(b, i)
        f, w = key >> 3, key & 7
        if w == 0:
            v, i = _varint(b, i)
        elif w == 1:
            v, i = b[i:i + 8], i + 8
        elif w == 5:
            v, i = b[i:i + 4], i + 4
        elif w == 2:
            n, i = _varint(b, i)
            v, i = b[i:i + n], i + n
        else:
            raise ValueError(f"protobuf wire type {w}")
        out.append((f, w, v))
    return out


def pb_signal(b):
    """Signal message: repeated field 1, packed or not."""
    vals = []
    for f, w, v in pb_fields(b):
        if f != 1:
            continue
        if w == 0:
            vals.append(v)
        elif w == 2:  # packed
            i = 0
            while i < len(v):
                x, i = _varint(v, i)
                vals.append(x)
    return vals


def read_summary(path):
    raw = open(path, "rb").read()
    data = zlib.decompress(raw[4:])
    out = {"all": [], "low": [], "mid": [], "high": []}
    for f, w, v in pb_fields(data):
        if f == 3 and w == 2:
            out["all"] = pb_signal(v)
        elif f == 4 and w == 2:
            for ff, ww, vv in pb_fields(v):
                if ww == 2 and ff in (1, 2, 3):
                    out[("low", "mid", "high")[ff - 1]] = pb_signal(vv)
    return out


def _mono(vals):
    """stereo interleaved -> max(L, R) per frame"""
    return [max(vals[i], vals[i + 1]) for i in range(0, len(vals) - 1, 2)]


def _bucket_max(vals, n):
    if not vals:
        return [0] * n
    out = []
    for k in range(n):
        a = k * len(vals) // n
        b = max(a + 1, (k + 1) * len(vals) // n)
        out.append(max(vals[a:b]))
    return out


def _colour(low, mid, high):
    """rekordbox-like: bass -> blue, mids -> amber, highs -> white; returns (dark, bright) RGB565."""
    tot = float(low + mid + high) or 1.0
    l, m, h = low / tot, mid / tot, high / tot
    r = int(255 * (0.10 * l + 1.00 * m + 0.95 * h))
    g = int(255 * (0.45 * l + 0.55 * m + 0.95 * h))
    b = int(255 * (1.00 * l + 0.10 * m + 0.95 * h))
    peak = max(r, g, b, 1)
    r, g, b = (min(255, x * 255 // peak) for x in (r, g, b))
    dark = d.rgb565(r * 6 // 10, g * 6 // 10, b * 6 // 10)
    bright = d.rgb565(r, g, b)
    return dark, bright


def waveform_points(summary, n=d.WAVEFORM_POINTS):
    allv = _bucket_max(_mono(summary["all"]), n)
    low = _bucket_max(_mono(summary["low"]), n)
    mid = _bucket_max(_mono(summary["mid"]), n)
    high = _bucket_max(_mono(summary["high"]), n)
    top = max(allv) or 1
    pts = []
    for k in range(n):
        outer = min(HEIGHT_MAX, max(1, round(allv[k] / top * HEIGHT_MAX * OUTER_GAIN)))
        inner = min(outer, max(1, round(low[k] / top * HEIGHT_MAX * OUTER_GAIN)))
        dark, bright = _colour(low[k], mid[k], high[k])
        pts.append(b"\0" + dark + bright + bytes([outer, inner]))
    return pts


def beatmap_ms(blob, samplerate):
    beats = []
    for f, w, v in pb_fields(blob):
        if f == 1 and w == 2:
            frame = None
            enabled = True
            for ff, ww, vv in pb_fields(v):
                if ff == 1 and ww == 0:
                    frame = vv
                elif ff == 2 and ww == 0:
                    enabled = bool(vv)
            if frame is not None and enabled:
                beats.append(frame * 1000.0 / samplerate)
    return [((i % 4) + 1, round(t)) for i, t in enumerate(beats)]


class TrackLookup:
    def __init__(self, log):
        self.log = log
        self.cache = {}

    def find(self, length_ms, file_bpm):
        key = (round(length_ms), round(file_bpm, 2))
        if key in self.cache:
            return self.cache[key]
        result = None
        try:
            con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=1.0)
            rows = con.execute(
                "select id, samplerate, beats_version, beats, title from library "
                "where mixxx_deleted = 0 and abs(duration * 1000 - ?) < 60 and abs(bpm - ?) < 0.02 "
                "order by last_played_at desc", (length_ms, file_bpm)).fetchall()
            if rows:
                tid, rate, bver, beats, title = rows[0]
                arow = con.execute("select id from track_analysis where track_id = ? and description like "
                                   "'WaveformSummary%' order by id desc limit 1", (tid,)).fetchone()
                result = {"id": tid, "title": title, "matches": len(rows), "waveform": None, "beats": None}
                if arow:
                    path = os.path.join(MIXXX_DIR, "analysis", str(arow[0]))
                    if os.path.exists(path):
                        result["waveform"] = waveform_points(read_summary(path))
                if beats and bver and bver.startswith("BeatMap") and rate:
                    result["beats"] = beatmap_ms(beats, rate)
            con.close()
        except (sqlite3.Error, OSError, zlib.error, ValueError, IndexError) as exc:
            self.log(f"display: WARN track lookup failed: {exc}")
        if result is not None and result["waveform"]:
            self.cache[key] = result   # not found / not analysed yet: ask again later (Mixxx adds and
        return result                  # analyses new tracks only when they are loaded)
