# Setup Guide: Raspberry Pi + DDJ-1000

This guide covers the hardware hookup and the software stack for running a
Pioneer DJ / AlphaTheta DDJ-1000 standalone on a Raspberry Pi with Mixxx.
Driver build and install details are in `docs/raspberry-pi.md`.

## 1. Hardware

| Part | Recommendation | Why |
|---|---|---|
| Raspberry Pi | Pi 4 Model B, 4 GB or 8 GB (Pi 5 also works) | Mixxx with 4 decks, waveforms and library needs the RAM |
| Pi power supply | Official 5.1 V / 3 A USB-C supply | Undervoltage causes USB dropouts and audio clicks |
| Cooling | Active cooler or fan case | Mixxx keeps the CPU busy; throttling causes xruns |
| Boot medium | 32 GB+ A2 microSD, or boot from SSD | System only, keep music elsewhere |
| Music storage | USB 3 SSD | Fast track loading, spares the SD card |
| Display | HDMI monitor or touchscreen (micro-HDMI on the Pi 4) | Mixxx is a GUI application |
| USB cable | USB-A to USB-B, short and good quality | Isochronous audio is sensitive to cable quality |
| DDJ-1000 power | The controller's own mains power | The DDJ-1000 does not run from USB bus power |
| Optional | Keyboard/mouse for setup, Ethernet for SSH | Headless maintenance over SSH after setup |

## 2. Wiring

```
                      ┌────────────────────────────┐
  mains ─────────────►│ DDJ-1000            AC IN  │
                      │                            │
  Pi USB 2.0 (black) ◄┤ USB-B (rear)               │
                      │                            │
                      │ MASTER OUT (XLR / RCA) ────┼──► PA / active speakers
                      │ BOOTH OUT ─────────────────┼──► booth monitors (optional)
                      │ PHONES (front) ────────────┼──► headphones
                      └────────────────────────────┘

  Raspberry Pi 4
    USB-C  ◄── official PSU
    USB 3.0 (blue)   ──► SSD with music
    USB 2.0 (black)  ──► DDJ-1000
    micro-HDMI 0     ──► display
    Ethernet         ──► network (SSH)
```

Notes:

- All Pi audio goes out through the DDJ-1000. The Pi's own 3.5 mm / HDMI
  audio is not used; you can disable it so it never becomes the default card.
- On the Pi 4 all four USB ports sit behind the same VL805 controller. Putting
  the DDJ on a USB 2.0 (black) port and the SSD on USB 3.0 (blue) keeps them
  on separate ports. If you hear dropouts, try the other USB 2.0 port first.
- Do not use an unpowered USB hub between Pi and DDJ.
- Power order: DDJ-1000 on first, then plug USB (or boot the Pi). The unlock
  service also handles replugging while running.

## 3. Software stack

| Layer | What to use |
|---|---|
| OS | Raspberry Pi OS 64-bit **with desktop**. The Trixie-based release is preferred (see Mixxx below); Bookworm works too |
| Kernel | The stock Raspberry Pi kernel (`6.12.y+rpt-rpi-v8`) plus matching `linux-headers-$(uname -r)` |
| Driver | This repository: patched `snd-usb-audio` + `snd-usbmidi-lib`, udev rules, ALSA names, unlock service |
| DJ software | Mixxx 2.5.x |
| Controller mapping | Community DDJ-1000 mapping for Mixxx (currently `Pioneer-DDJ_1000-scriptsV0_9_9.js` + XML) |
| Tools | `alsa-utils` (`aplay`, `amidi`, `speaker-test`), `git`, build tools (installed by `scripts/setup-linux.sh`) |

### Installing Mixxx

- **Raspberry Pi OS based on Debian Trixie:** Debian Trixie ships Mixxx 2.5.x.
  ```bash
  sudo apt install mixxx
  ```
- **Raspberry Pi OS Bookworm:** the Debian package there is 2.3.x, which is
  too old. Use the Flathub build (it is published for `aarch64`):
  ```bash
  sudo apt install flatpak
  flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
  flatpak install flathub org.mixxx.Mixxx
  ```

Check with `mixxx --version` (or `flatpak info org.mixxx.Mixxx`).

### Installing the driver stack

```bash
git clone -b rpi4 https://github.com/RymenTe/ddj1000-linux-driver-rpi ~/ddj1000-linux-driver-rpi
cd ~/ddj1000-linux-driver-rpi
bash scripts/setup-linux.sh all
bash scripts/dev/prepare-ddj1000-snd-usb-audio-module.sh
bash scripts/install-ddj1000-linux-stack.sh install
sudo usermod -aG audio,plugdev "$USER"   # log out and back in afterwards
```

Verify:

```bash
bash scripts/install-ddj1000-linux-stack.sh status
aplay -l | grep DDJ1000          # playback device present
amidi -l | grep DDJ-1000         # MIDI port present
ls /run/ddj1000/unlocked         # unlock + rebind finished
```

The controller display should no longer show `NO AUDIO DRIVER`.

## 4. Mixxx configuration

### Sound hardware (Preferences → Sound Hardware)

| Setting | Value |
|---|---|
| Sound API | ALSA |
| Sample rate | 44100 Hz (the DDJ-1000 path is fixed at 44.1 kHz) |
| Audio buffer | Start at 23 ms, lower step by step while the xrun counter stays at 0 |
| Output → Master | DDJ-1000 device (`hw:DDJ1000,0`), channels **1–2** |
| Output → Headphones | same DDJ-1000 device, channels **3–4** |
| Output → Booth | leave empty (the DDJ derives Booth from Master) |

Use the raw DDJ-1000 device for both Master and Headphones. Do **not** pick
`ddj1000_master` and `ddj1000_cue` as two separate devices: all three named
PCMs share one exclusive hardware endpoint, so Mixxx can only open one of
them.

Channels 5–6 are a third playback pair whose role is not confirmed yet
(`Sampler/Aux` is the working hypothesis), so leave them unused.

### Controller mapping (Preferences → Controllers)

1. Copy the mapping files (`.xml` + `.js`) into Mixxx's controller folder:
   - apt install: `~/.mixxx/controllers/`
   - Flatpak: `~/.var/app/org.mixxx.Mixxx/.mixxx/controllers/`
2. Restart Mixxx, select the DDJ-1000 MIDI device, enable it and load the
   mapping.
3. If the device is listed as "USB Device 0x00:0x00", the module from this
   repository is not loaded yet; check `modinfo -n snd_usb_audio`.

### Start Mixxx after the unlock

The unlock service rebinds the audio driver after the handshake. Mixxx must
not hold the device at that moment. For desktop autostart, wrap Mixxx so it
waits for the ready flag, e.g. `~/.config/autostart/mixxx.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=Mixxx (after DDJ-1000 unlock)
Exec=sh -c 'until [ -e /run/ddj1000/unlocked ]; do sleep 1; done; exec mixxx'
```

(Flatpak: replace `mixxx` with `flatpak run org.mixxx.Mixxx`.) For a systemd
setup see `docs/raspberry-pi.md`.

## 5. Recommended system tuning

These are common low-latency audio settings, not DDJ-specific requirements.
Change one at a time and keep what helps.

- CPU governor on `performance`:
  ```bash
  echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
  ```
  (make it permanent with a small systemd unit or `cpufrequtils`)
- Realtime priority for the `audio` group, `/etc/security/limits.d/audio.conf`:
  ```
  @audio - rtprio 95
  @audio - memlock unlimited
  ```
- Disable the Pi's onboard audio if unused: `dtparam=audio=off` in
  `/boot/firmware/config.txt`.
- Never add `snd_usb_audio.lowlatency=0` to the kernel command line; it
  breaks DDJ-1000 detection.

## 6. Quick troubleshooting

| Symptom | Check |
|---|---|
| `NO AUDIO DRIVER` stays on the DDJ | `journalctl -u ddj1000-unlock.service -f`; run the service manually with `--verbose --once` (see `docs/raspberry-pi.md`) |
| No `DDJ1000` in `aplay -l` | `modinfo -n snd_usb_audio` must point to `updates/ddj1000-linux-driver`; rebuild after kernel updates |
| Mixxx shows no DDJ MIDI device | `amidi -l`; is Mixxx started before the unlock finished? |
| Clicks / dropouts | Raise the Mixxx buffer, check `vcgencmd get_throttled` (power/heat), try the other USB 2.0 port |
| Everything gone after `apt full-upgrade` | New kernel: re-run `prepare-…-module.sh` and `install-ddj1000-linux-stack.sh install` |
