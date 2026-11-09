# Raspberry Pi 4 (and Pi 5)

This branch adapts the DDJ-1000 stack to Raspberry Pi OS 64-bit for a setup
such as MixxxPi, where Mixxx
talks to ALSA directly and there is no desktop session.

## Supported Raspberry Pi OS releases

| Raspberry Pi OS | Debian | Kernel | Patch |
|---|---|---|---|
| current (since the 2026-06-18 images) | 13 Trixie | 6.18.y LTS (`6.18.x+rpt-rpi-v8`) | `snd-usb-audio-ddj1000-rpi-6.18.patch` |
| Legacy | 12 Bookworm | 6.12.y LTS (`6.12.x+rpt-rpi-v8`) | `snd-usb-audio-ddj1000-rpi-6.12.patch` |

The build script picks the patch from the running kernel's `X.Y` series and
stops with a clear message if there is none (e.g. a future 6.24 kernel).

## What is different from the Ubuntu flow

| Area | Ubuntu flow | Raspberry Pi flow |
|---|---|---|
| Kernel source | Ubuntu `deb-src` package | `sound/usb` from the upstream stable tag matching `uname -r`, or `--source-dir ~/rpi-linux` |
| Patch | `patches/linux/snd-usb-audio-ddj1000-composite-quirk.patch` (`-p0`) | one patch per kernel series in `patches/linux/rpi/` (`-p1`, git format) |
| Module signing | local MOK key, Secure Boot enrollment | none (no Secure Boot on the Pi) |
| Module override | `updates/` search order | `updates/` plus an explicit `/etc/depmod.d/ddj1000-linux-driver.conf` override, because the stock modules are `.ko.xz` |
| Unlock service | `systemctl --user` unit + PipeWire sink | root system unit `ddj1000-unlock.service`, no desktop sink |
| MIDI I/O | one `amidi -d` reader plus one `amidi -S` process per message | one `O_RDWR` rawmidi fd with a stream parser |
| Post-ACK silence burst | libusb on interface 0 | `aplay` on the DDJ ALSA PCM when the patched driver is bound (libusb cannot claim interface 0 then) |
| Ready signal | none | `/run/ddj1000/unlocked` once unlock and rebind are done |

## The Raspberry Pi patches

| Patch | Generated against | Checked to apply to | Build check |
|---|---|---|---|
| `rpi-6.12` | `raspberrypi/linux` `rpi-6.12.y` | upstream `v6.12.34`, `v6.12.111` | Pi 4 cross-compile, `W=1`, no warnings |
| `rpi-6.18` | `raspberrypi/linux` `rpi-6.18.y` (6.18.59) | upstream `v6.18.34`, `v6.18.59` | Pi 4 cross-compile, `W=1`, no warnings; full build script run |

Both carry the same change; the implicit-feedback code they touch is
identical in 6.12 and 6.18.

They differ from the original upstream patch in four ways:

- **The endpoint fix actually applies.** In the original patch the last
  `sound/usb/endpoint.c` hunk has no `+`/`-`/space prefixes, so `patch` skips
  it silently and only the quirk-table, flag and log-level hunks land. A module
  built from it has the DDJ quirk but not the empty-implicit-feedback fallback
  described in `docs/audio-driver-notes.md`. Here the fallback is a proper hunk.
- **The fallback is DDJ-1000 only.** Empty implicit-feedback URBs are still
  skipped for every other device (the upstream behaviour that protects e.g. the
  M-Audio Fast Track Ultra); only `2b73:0020` keeps queueing with nominal pacing.
- **Rate-limited logging.** The "carried no payload" message uses
  `dev_info_ratelimited` instead of logging every URB, which would otherwise
  flood the journal on an SD card. The other `dbg` → `info` changes are left
  out; use dynamic debug if you need them:
  `echo 'module snd_usb_audio +p' | sudo tee /sys/kernel/debug/dynamic_debug/control`
- **Pinned card names.** The quirk sets `vendor_name = "Pioneer DJ"` and
  `product_name = "DDJ-1000"`. On hosts where the device reports empty strings
  this replaces "USB Device 0x00:0x00", so the ALSA card id is always
  `DDJ1000` (what `config/alsa/60-ddj1000-host-stack.conf` expects) and the
  MIDI port is named `DDJ-1000 MIDI 1`.

## Install

```bash
git clone -b rpi4 <your fork> ~/ddj1000-linux-driver
cd ~/ddj1000-linux-driver

bash scripts/setup-linux.sh all        # build deps, kernel headers, udev rules
bash scripts/dev/prepare-ddj1000-snd-usb-audio-module.sh
bash scripts/install-ddj1000-linux-stack.sh install
bash scripts/install-ddj1000-linux-stack.sh status
```

To build from your own kernel checkout instead of downloading the stable tag:

```bash
git -C ~/rpi-linux checkout -- sound/usb   # must be unpatched; the script copies it
bash scripts/dev/prepare-ddj1000-snd-usb-audio-module.sh --source-dir ~/rpi-linux
```

The script refuses a tree that already contains a DDJ-1000 quirk, so an older
hand-patched `~/rpi-linux` cannot be mixed in by accident. It also warns when
the checkout's version differs from the running kernel.

### Kernel updates (important for live use)

There is no DKMS packaging yet. After a kernel update the override module is
missing for the new kernel, the stock driver binds the DDJ without a playback
device, and the unlock service logs
`[ERROR] No DDJ-1000 snd-usb-audio module installed for running kernel ...`.

For a gig machine, hold the kernel and update it deliberately:

```bash
sudo apt-mark hold linux-image-rpi-v8 linux-headers-rpi-v8 linux-image-rpi-2712 linux-headers-rpi-2712
```

When you do update: `sudo apt-mark unhold ...`, `sudo apt full-upgrade`,
reboot, then rebuild and reinstall:

```bash
bash scripts/dev/prepare-ddj1000-snd-usb-audio-module.sh
bash scripts/install-ddj1000-audio-driver.sh install
```

## Starting Mixxx after the unlock

The unlock service rebinds `snd-usb-audio` after the handshake. Mixxx must not
hold the device at that moment, so start it only once the ready flag exists.
For a systemd-managed Mixxx, add a drop-in:

```ini
# /etc/systemd/system/mixxx.service.d/wait-ddj1000.conf
[Unit]
After=ddj1000-unlock.service
Wants=ddj1000-unlock.service

[Service]
ExecStartPre=/bin/sh -c 'until [ -e /run/ddj1000/unlocked ]; do sleep 1; done'
```

## Debugging

```bash
journalctl -u ddj1000-unlock.service -f
sudo systemctl stop ddj1000-unlock.service
sudo /usr/local/bin/ddj1000-unlock-service.py --host-stack-scope none --verbose --once
```

`--verbose` logs every SysEx received from the controller, so you can see
whether `13 2a` arrives at all. The expected order is:

```
11 02 (ready) → 12 2a sent → 13 2a challenge → 14 38 sent → 15 02 ack
→ silence burst via ALSA → audio rebind → "DDJ unlock cycle complete"
```

## Known Pi-specific constraints

- Never set `snd_usb_audio.lowlatency=0` on the kernel command line; it breaks
  DDJ-1000 detection. `scripts/setup-linux.sh check` warns about it.
- ALSA card numbers move between boots. Everything here resolves the card from
  `/proc/asound/card*/usbid` (`2b73:0020`) or the `DDJ1000` id; nothing
  hardcodes `hw:3`.
- Validated so far: patch application and cross-compilation only. Runtime on
  real DDJ-1000 + Pi 4 hardware still needs the checklist in
  `docs/validation.md`.

## Validation status (2026-11-07)

| Board | OS / kernel | Patch | Result |
|---|---|---|---|
| Raspberry Pi 4 Model B Rev 1.5 | Bookworm, `6.12.34+rpt-rpi-v8` | `rpi-6.12` with **12-channel capture** | ✔ audio clear, implicit FB, Mixxx standalone |
| Raspberry Pi 4 | Trixie, 6.18 | `rpi-6.18` with 12-channel capture | not yet tested on hardware |
| Raspberry Pi 5 | – | – | not yet tested (RP1 USB instead of VL805; kernel `rpi-2712`) |

Capture must be **12 channels** (36-byte frames, 396 B per 250 µs packet). With 6 channels every
IN packet on EP 0x82 fails with `-EOVERFLOW` and implicit feedback never starts. Details, the udev
unlock path (vendor read `0xC0/0x00 wIndex 0x8003` against "NO AUDIO DRIVER") and the Mixxx mapping
settings are in `docs/session-log.md`, `config/mixxx/README.md` and `CLAUDE.md`.
