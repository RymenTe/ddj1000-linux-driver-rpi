# DDJ-1000 bridge: autostart, jog displays, Mixxx

The bridge (`scripts/runtime/ddj1000-bridge.py`) owns the DDJ-1000's rawmidi port while the controller
is plugged in. Mixxx talks to it through a virtual MIDI port instead of the DDJ port.

```
DDJ-1000 ──USB-MIDI── bridge ──snd-virmidi "VirMIDI 7-0"── Mixxx (mapping DDJ-1000)
   │                    │
   └── hidraw (64 B) ◄──┘ jog displays: waveform, beatgrid, BPM, key, time, hot cues, loop, tempo range
```

What the bridge does:

- **Unlock** (challenge-response, one `os.write` per SysEx so the `14 38` answer stays in one USB transfer)
  and the **heartbeat** `50 01` every 200 ms. With the heartbeat the DDJ runs in its rekordbox mode:
  the jog displays only accept HID, and the pad-mode buttons only switch when the host echoes them
  (the bridge does that).
- **MIDI forwarding** in both directions; SysEx `F0 7D 44 42 …` from the mapping (deck state, hot cues,
  loop, tempo range) is consumed by the bridge and drives the jog displays.
- `/run/ddj1000/unlocked` exists while the DDJ is unlocked; `mixxx-after-ddj1000` waits for it before
  it starts Mixxx (otherwise Mixxx opens the audio device before the DDJ delivers audio).
- If the DDJ keeps an old session after a fast restart (no `11 02`), the bridge pauses the heartbeat
  for 3 s after 6 s, which forces a new session.

## Installation

Part of `scripts/install-ddj1000-linux-stack.sh install`; alone:

```bash
bash scripts/install-ddj1000-bridge.sh install          # bridge (default)
bash scripts/install-ddj1000-bridge.sh install --no-bridge   # only the oneshot unlock, no jog displays
bash scripts/install-ddj1000-bridge.sh status
bash scripts/install-ddj1000-mixxx.sh install [--autostart]  # Mixxx closed, as the DJ user
```

| Installed | Purpose |
|---|---|
| `/usr/local/lib/ddj1000-linux-driver/` | runtime scripts, build script and patches (the clone may move) |
| `/etc/systemd/system/ddj1000-bridge@.service` | the bridge, as the DJ user (groups `audio`, `plugdev`) |
| `/etc/udev/rules.d/92-ddj1000-bridge.rules` | starts `ddj1000-bridge@midiCxD0` when the DDJ appears, stops it on unplug |
| `/etc/modprobe.d/ddj1000-virmidi.conf`, `/etc/modules-load.d/ddj1000-virmidi.conf` | `snd-virmidi` at boot: card `DDJBridge`, index 7 → Mixxx port **VirMIDI 7-0** |
| `/etc/kernel/postinst.d/` + `header_postinst.d/zz-ddj1000-snd-usb-audio` | rebuild the patched `snd-usb-audio` for every new kernel |
| `ddj1000-module-check.service` | at boot: build the module if the hooks could not (no headers / no network) |

The Mixxx part (`scripts/ddj1000-mixxx-config.py`, backs up to `~/.mixxx/ddj1000-backup-*`):
controller **VirMIDI 7-0 = DDJ-1000** (the direct `DDJ-1000 MIDI 1` / HID entries are switched off),
PAD FX / Color FX chain presets at fixed positions at the start of the preset lists (the mapping selects
presets by index; Mixxx's built-in names are localised), skin `Pioneered-4Deck`, and – if no DDJ
output is configured yet – sound DDJ-1000 Master 1/2, Headphones 3/4, 44.1 kHz.

## Kernel updates

`apt upgrade` installs a new kernel → the hook builds the module for it (sources of the matching stable
tag via git, patch from `patches/linux/rpi/` for the kernel series). Log: `/var/log/ddj1000-kernel-rebuild.log`.
A new kernel **series** without a patch (e.g. 6.19) fails the build with a clear message; the DDJ then has
no audio with that kernel – boot the previous one or add a patch for the series.

## Troubleshooting

```bash
bash scripts/install-ddj1000-bridge.sh status
journalctl -u 'ddj1000-bridge@*' -b --no-pager | tail -40
cat /proc/asound/cards               # DDJ1000 and DDJBridge (7) present?
```

Manual start for tests (stop the service first): `sudo systemctl stop 'ddj1000-bridge@*'`, then
`python3 -I scripts/runtime/ddj1000-bridge.py --stats-interval-s 30`. After stopping a bridge wait ~5 s
before the next start (or rely on the LOCKED recovery).
