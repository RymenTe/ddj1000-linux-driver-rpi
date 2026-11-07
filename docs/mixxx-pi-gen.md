# Running on the mixxx-pi-gen image

[mixxx-pi-gen](https://github.com/fayaaz/mixxx-pi-gen) is a ready-made Raspberry
Pi image that boots straight into Mixxx. This fork is developed and tested
against it. This page lists what the image already does, what conflicts with the
DDJ-1000 stack, and the exact install steps on the image.

## Image versions

| Image | Base | Kernel | Mixxx | Patch used |
|---|---|---|---|---|
| `v1.2` (Sep 2025, latest tagged release) | Raspberry Pi OS 64-bit, Debian 12 Bookworm | 6.12.y (`6.12.x+rpt-rpi-v8`) | 2.5 branch, built from source | `rpi-6.12` |
| `nightly` (current `main`, Debian 13) | Raspberry Pi OS 64-bit, Debian 13 Trixie | 6.18.y (`6.18.x+rpt-rpi-v8`) | 2.5 branch, built from source | `rpi-6.18` |

The image uses the stock Raspberry Pi kernel (only `preempt=full` is added on
the command line), so the regular `linux-headers-$(uname -r)` package matches
and the module build works unchanged.

Check what you are running:

```bash
cat /opt/mixxx.tag          # Mixxx version the image was built with
uname -r                    # kernel
grep VERSION_CODENAME /etc/os-release
```

## What the image already does (nothing to add)

| Image setting | Effect for the DDJ-1000 stack |
|---|---|
| `preempt=full` on the kernel command line | low-latency kernel; no RT kernel needed |
| performance CPU governor | no extra tuning needed |
| `pi - rtprio 99`, `memlock unlimited` | Mixxx may use realtime priority |
| PipeWire / PulseAudio masked | Mixxx talks to ALSA directly; the fork's headless "system" service mode (default on the Pi) fits, no desktop sink is created |
| `69-mixxx-usb-uaccess.rules` incl. AlphaTheta `2b73` hidraw | coexists with the fork's `99-ddj1000-hid.rules` |
| passwordless `sudo` for `pi` | install scripts run without prompts |

Skip the tuning section of `docs/setup-guide.md` on this image.

## What conflicts, and how the fork handles it

The image starts Mixxx immediately at login (sway config:
`exec swaymsg 'workspace "1:Mixxx"; exec /usr/bin/mixxx'`), and again from the
**MIXXX** buttons in waybar / i3blocks. The DDJ-1000 unlock service needs the
MIDI port free, and it rebinds `snd-usb-audio` after the handshake. A Mixxx
that is already running holds the MIDI port and loses its sound device during
the rebind.

`scripts/install-ddj1000-linux-stack.sh install` detects the image and runs
`scripts/install-mixxx-pi-gen-integration.sh install`, which:

- installs `/usr/local/bin/mixxx-after-ddj1000`, a wrapper that waits for
  `/run/ddj1000/unlocked` (shows a notification while waiting) and then starts
  `/usr/bin/mixxx`
- starts Mixxx immediately if no DDJ-1000 is plugged in, so other controllers
  behave exactly as before
- gives up waiting after 60 s and starts Mixxx anyway, with a hint to the
  unlock service log (`DDJ1000_WAIT_TIMEOUT` changes the limit)
- ignores repeated clicks on the MIXXX button while a start is pending
- points these launchers at the wrapper, keeping `*.ddj1000.bak` copies:
  - `~pi/.config/sway/config`
  - `~pi/.config/waybar/mixxx.sh`
  - `~pi/.config/i3blocks/scripts/mixxx.sh`

Undo with `bash scripts/install-mixxx-pi-gen-integration.sh uninstall`.

## Install on the image

On the Pi (SSH as `pi`, default password `mixxx`, or a terminal with
`super+enter`):

```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

After the reboot:

```bash
git clone -b rpi4 https://github.com/RymenTe/ddj1000-linux-driver-rpi ~/ddj1000-linux-driver-rpi
cd ~/ddj1000-linux-driver-rpi

bash scripts/setup-linux.sh all                       # build deps + linux-headers-$(uname -r)
bash scripts/dev/prepare-ddj1000-snd-usb-audio-module.sh
bash scripts/install-ddj1000-linux-stack.sh install   # driver, unlock service, image integration
bash scripts/install-ddj1000-linux-stack.sh status
sudo reboot
```

If you built modules earlier from a hand-patched `~/rpi-linux`, do not pass
it as `--source-dir` unless it is clean (`git -C ~/rpi-linux checkout -- sound/usb`)
and on the same version as `uname -r`. Without `--source-dir` the script fetches
the matching sources itself.

The expected boot sequence is: unlock service starts → handshake → audio rebind
→ `/run/ddj1000/unlocked` → the "Waiting for DDJ-1000 unlock" notification
disappears → Mixxx opens fullscreen.

## Mixxx settings on the image

Mixxx keeps its settings in `/home/pi/.mixxx/` (log: `/home/pi/.mixxx/mixxx.log`).

- Preferences → Sound Hardware: API **ALSA**, 44100 Hz,
  Master = DDJ-1000 channels 1–2, Headphones = the same device, channels 3–4
  (details in `docs/setup-guide.md`, section 4)
- Controller mapping files go to `/home/pi/.mixxx/controllers/`

## Replugging the DDJ-1000 while Mixxx runs

A replug triggers a new unlock and rebind, and the running Mixxx loses the
device. Close Mixxx, wait for the unlock (`journalctl -u ddj1000-unlock.service -f`
shows "DDJ unlock cycle complete"), then start it again with the **MIXXX**
button.

## Image updates

Re-flashing or updating to a newer image replaces the sway/waybar files and
the kernel. Run the install steps above again afterwards. On a gig machine,
hold the kernel as described in `docs/raspberry-pi.md`.
