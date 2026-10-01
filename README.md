# ddj1000-linux-driver

Experimental Linux audio-driver and host-stack work for the AlphaTheta / Pioneer DJ DDJ-1000.

This repository contains standalone Linux-facing DDJ-1000 transport, install flow, and validation work for discussion, testing, and publication.

## What This Repo Does

- installs a patched `snd-usb-audio` plus `snd-usbmidi-lib` override for DDJ-1000 Linux bring-up
- installs udev rules for `hidraw` and vendor USB access
- exposes named ALSA PCMs for the currently validated playback buses
- runs a user-session unlock keepalive plus a system rebind helper so the controller clears `NO AUDIO DRIVER`
- keeps the Linux-specific driver, patch, and runtime integration work isolated in a dedicated repository

## Current Status

- installable as an experimental bring-up stack
- validated primarily on Debian or Ubuntu style Linux setups
- still hardware-dependent and not yet a polished end-user package
- only the `Master` desktop sink is exported through `pactl`; `Cue` and `Aux` remain ALSA-only today
- licensed as `GPL-2.0-only` for kernel-adjacent patching and redistribution clarity
- static validation exists through `scripts/validate-repo.py` and `.github/workflows/static-checks.yml`

## Raspberry Pi 4 / Pi 5

This `rpi4` branch adds a Raspberry Pi OS flow (64-bit, `6.12.y+rpt` kernels,
headless). The scripts detect the Pi automatically. See `docs/raspberry-pi.md`.

```bash
bash scripts/setup-linux.sh all
bash scripts/dev/prepare-ddj1000-snd-usb-audio-module.sh
bash scripts/install-ddj1000-linux-stack.sh install
```

## Quick Start

Install base Linux dependencies and udev rules:

```bash
bash scripts/setup-linux.sh all
```

Run the repository validation check:

```bash
python3 scripts/validate-repo.py
```

Install the full stack:

```bash
bash scripts/install-ddj1000-linux-stack.sh install
```

Check the current state:

```bash
bash scripts/install-ddj1000-linux-stack.sh status
```

Remove it again:

```bash
bash scripts/install-ddj1000-linux-stack.sh uninstall
```

## Current Limits

- this is not an upstream-quality kernel driver package yet
- there is no DKMS packaging yet
- Secure Boot still requires a manual local MOK enrollment step
- the module build flow is still tailored to Debian or Ubuntu style kernel-source packaging
- there is no proven cross-distro reproducibility yet
- the `5/6` playback bus is still not conclusively named
- end-to-end runtime validation still depends on real DDJ-1000 hardware and a Linux machine with audio, MIDI, and USB access

## Repository Layout

- `scripts/` contains the main user-facing setup and install entry points
- `scripts/runtime/` contains the installed host-stack runtime helpers
- `scripts/dev/` contains developer-only kernel-module prep and test-load helpers
- `config/` contains ALSA, udev, systemd, and runtime assets
- `patches/` contains the Linux kernel patch for the DDJ-1000 composite audio quirk
- `docs/` contains install, audio-driver, and validation notes

## Validation

Run the repository validation check without hardware:

```bash
python3 scripts/validate-repo.py
```

This verifies required files, repo-local references, systemd `ExecStart` targets, and Python shebang consistency.

For real-hardware validation by other Linux developers, use the checklist in `docs/validation.md` so test reports come back in a comparable format.

## Legal And Trademark Notice

This project is an independent interoperability effort. It is not affiliated with, endorsed by, or sponsored by AlphaTheta Corporation, Pioneer DJ, or rekordbox.

`AlphaTheta`, `Pioneer DJ`, `DDJ-1000`, and `rekordbox` are referenced only to identify compatible hardware, software environments, and observed protocol behavior. All third-party product names, logos, and trademarks remain the property of their respective owners.

The implementation in this repository is based on original Linux integration work, protocol observation, device-capture review, and reverse engineering for interoperability and compatibility. This repository is not intended to ship vendor source code, copied rekordbox application code, or proprietary Pioneer / AlphaTheta driver binaries.

## Maintainer

- recommended copyright line: `Copyright (C) 2026 Jan Kaup`
- maintained by `Jan Kaup` / `Kaup Audio Labs`
- this repository stands on its own as a Linux interoperability and bring-up project for the DDJ-1000

## Documents

- `docs/install.md`
- `docs/audio-driver-notes.md`
- `docs/validation.md`
- `docs/raspberry-pi.md`

## Support

- support / updates: `https://ko-fi.com/fourfourmusic`
