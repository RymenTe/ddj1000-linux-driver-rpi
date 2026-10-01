# ddj1000-linux-driver-rpi

Run a Pioneer DJ / AlphaTheta DDJ-1000 standalone on a Raspberry Pi with Mixxx.

This is a Raspberry Pi focused fork of
[`jan0803/ddj1000-linux-driver`](https://github.com/jan0803/ddj1000-linux-driver).
It keeps the original DDJ-1000 driver and unlock work and adapts it to
Raspberry Pi OS (64-bit, `6.12.y+rpt` kernels): kernel module build without an
Ubuntu source package, a headless system service instead of a desktop session,
and Mixxx on plain ALSA.

## Start Here

1. **Hardware, wiring and software:** `docs/setup-guide.md`
2. **Driver build, install and debugging on the Pi:** `docs/raspberry-pi.md`
3. **Hardware test checklist:** `docs/validation.md`

## Quick Start

```bash
git clone -b rpi4 https://github.com/RymenTe/ddj1000-linux-driver-rpi ~/ddj1000-linux-driver-rpi
cd ~/ddj1000-linux-driver-rpi

bash scripts/setup-linux.sh all                     # packages, kernel headers, udev rules
bash scripts/dev/prepare-ddj1000-snd-usb-audio-module.sh
bash scripts/install-ddj1000-linux-stack.sh install
bash scripts/install-ddj1000-linux-stack.sh status
```

Rebuild and reinstall the modules after every kernel update. Remove everything
again with `bash scripts/install-ddj1000-linux-stack.sh uninstall`.

## What It Installs

- a patched `snd-usb-audio` plus `snd-usbmidi-lib` with a DDJ-1000 quirk
  (6-channel playback at 44.1 kHz, implicit feedback, MIDI kept available)
- udev rules for the DDJ-1000 `hidraw` and USB device
- named ALSA PCMs `ddj1000_master` (1/2), `ddj1000_cue` (3/4), `ddj1000_aux` (5/6)
- `ddj1000-unlock.service`: performs the MIDI unlock handshake so the
  controller clears `NO AUDIO DRIVER`, then signals readiness via
  `/run/ddj1000/unlocked`
- `ddj1000-audio-rebind.path`: rebinds the audio driver after the unlock

## Current Status

- builds and cross-compiles for the Pi 4 (`bcm2711_defconfig`, kernel 6.12)
- runtime on real Pi + DDJ-1000 hardware is being validated
- the `5/6` playback bus is not conclusively identified yet
- no DKMS packaging yet

The Ubuntu/desktop flow from upstream still exists in the scripts (selected
automatically when not on a Pi), but this fork does not test or develop it.

## Repository Layout

- `scripts/` setup and install entry points
- `scripts/runtime/` installed runtime helpers (unlock service, rebind, probes)
- `scripts/dev/` kernel-module build and test-load helpers
- `config/` ALSA, udev and systemd files
- `patches/linux/rpi/` kernel patch used on the Pi
- `patches/linux/` original upstream patch (Ubuntu flow)
- `docs/` guides and notes

## Validation

```bash
python3 scripts/validate-repo.py
```

Checks required files, repo-local references, systemd `ExecStart` targets and
Python shebangs, without hardware.

## Legal And Trademark Notice

This project is an independent interoperability effort. It is not affiliated with, endorsed by, or sponsored by AlphaTheta Corporation, Pioneer DJ, or rekordbox.

`AlphaTheta`, `Pioneer DJ`, `DDJ-1000`, and `rekordbox` are referenced only to identify compatible hardware, software environments, and observed protocol behavior. All third-party product names, logos, and trademarks remain the property of their respective owners.

The implementation in this repository is based on original Linux integration work, protocol observation, device-capture review, and reverse engineering for interoperability and compatibility. This repository is not intended to ship vendor source code, copied rekordbox application code, or proprietary Pioneer / AlphaTheta driver binaries.

## Credits And License

- original DDJ-1000 Linux driver and unlock research: Jan Kaup / Kaup Audio Labs
  (`jan0803/ddj1000-linux-driver`, `Copyright (C) 2026 Jan Kaup`,
  support: `https://ko-fi.com/fourfourmusic`)
- Raspberry Pi adaptation: F. Rymen
- licensed `GPL-2.0-only`, see `LICENSE`

## Documents

- `docs/setup-guide.md`
- `docs/raspberry-pi.md`
- `docs/install.md`
- `docs/audio-driver-notes.md`
- `docs/validation.md`
