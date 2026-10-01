# Raspberry Pi 4 (and Pi 5)

This branch adapts the DDJ-1000 stack to Raspberry Pi OS (Bookworm, 64-bit,
`6.12.y+rpt-rpi-v8` kernels) for a headless setup such as MixxxPi, where Mixxx
talks to ALSA directly and there is no desktop session.

## What is different from the Ubuntu flow

| Area | Ubuntu flow | Raspberry Pi flow |
|---|---|---|
| Kernel source | Ubuntu `deb-src` package | `sound/usb` from the upstream stable tag matching `uname -r`, or `--source-dir ~/rpi-linux` |
| Patch | `patches/linux/snd-usb-audio-ddj1000-composite-quirk.patch` (`-p0`) | `patches/linux/rpi/snd-usb-audio-ddj1000-rpi-6.12.patch` (`-p1`, git format) |
| Module signing | local MOK key, Secure Boot enrollment | none (no Secure Boot on the Pi) |
| Module override | `updates/` search order | `updates/` plus an explicit `/etc/depmod.d/ddj1000-linux-driver.conf` override, because the stock modules are `.ko.xz` |
| Unlock service | `systemctl --user` unit + PipeWire sink | root system unit `ddj1000-unlock.service`, no desktop sink |
| MIDI I/O | one `amidi -d` reader plus one `amidi -S` process per message | one `O_RDWR` rawmidi fd with a stream parser |
| Post-ACK silence burst | libusb on interface 0 | `aplay` on the DDJ ALSA PCM when the patched driver is bound (libusb cannot claim interface 0 then) |
| Ready signal | none | `/run/ddj1000/unlocked` once unlock and rebind are done |

## The Raspberry Pi patch

`patches/linux/rpi/snd-usb-audio-ddj1000-rpi-6.12.patch` was generated against
`raspberrypi/linux` branch `rpi-6.12.y` and checked to apply cleanly to upstream
`v6.12.34` and `v6.12.111`. It cross-compiles warning-free (`W=1`) for
`bcm2711_defconfig` (Pi 4).

It differs from the original patch in four ways:

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

After every kernel update (`apt full-upgrade`) rebuild and reinstall the
modules; there is no DKMS packaging yet.

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
