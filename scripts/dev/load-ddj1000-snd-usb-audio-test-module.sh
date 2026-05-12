#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd -- "$script_dir/../.." && pwd)"
build_dir="$repo_dir/build/ddj1000-driver"
audio_module="$build_dir/snd-usb-audio-ddj1000.ko"
midi_module="$build_dir/snd-usbmidi-lib-test.ko"
running_kernel="$(uname -r)"

if [[ ! -f "$audio_module" ]]; then
    echo "Missing test module: $audio_module" >&2
    echo "Run scripts/dev/prepare-ddj1000-snd-usb-audio-module.sh first." >&2
    exit 1
fi

if [[ ! -f "$midi_module" ]]; then
  echo "Missing companion MIDI test module: $midi_module" >&2
  echo "Run scripts/dev/prepare-ddj1000-snd-usb-audio-module.sh first." >&2
  exit 1
fi

audio_vermagic="$(modinfo -F vermagic "$audio_module" | awk '{print $1}')"
midi_vermagic="$(modinfo -F vermagic "$midi_module" | awk '{print $1}')"

if [[ "$audio_vermagic" != "$running_kernel" || "$midi_vermagic" != "$running_kernel" ]]; then
  echo "Test modules were built for a different kernel." >&2
  echo "  running kernel: $running_kernel" >&2
  echo "  audio module:   $audio_vermagic" >&2
  echo "  midi module:    $midi_vermagic" >&2
  echo "Rebuild them against the current kernel first:" >&2
  echo "  bash scripts/dev/prepare-ddj1000-snd-usb-audio-module.sh" >&2
  exit 1
fi

echo "Unloading stock snd-usb-audio and snd-usbmidi-lib..."
sudo modprobe -r snd_usb_audio snd_usbmidi_lib || true

echo "Loading dependency modules..."
sudo modprobe mc
sudo modprobe videodev
sudo modprobe snd_ump

echo "Loading patched DDJ-1000 snd-usbmidi-lib test module..."
sudo insmod "$midi_module"

echo "Loading patched DDJ-1000 snd-usb-audio test module..."
sudo insmod "$audio_module"

echo
echo "Loaded module:"
lsmod | grep -E '^snd_usb_audio|^snd_usbmidi_lib|^snd_ump|^mc|^videodev' || true

echo
echo "ALSA cards:"
cat /proc/asound/cards || true

echo
echo "Playback devices:"
aplay -l || true

echo
echo "Raw MIDI ports:"
amidi -l || true

echo
echo "DDJ stream descriptors:"
for stream in /proc/asound/card*/stream0; do
    [[ -e "$stream" ]] || continue
    if grep -q "DDJ-1000" "$stream"; then
        echo "== $stream =="
        cat "$stream"
    fi
done

cat <<'EOF'

If DDJ1000 playback and MIDI are both visible, run:
  python3 scripts/runtime/ddj1000-unlock-service.py --once --send-post-ack-startup-state
  speaker-test -D hw:DDJ1000,0 -c 6 -r 44100 -F S24_3LE -t sine -f 440 -l 1 -b 20000 -p 10000 -S 60

For a fuller staged validation flow, see:
  docs/validation.md

Current validated playback-bus interpretation on the stable fallback path:
  channels 1/2 -> Master/Program
  channels 3/4 -> Cue/Monitor
  channels 5/6 -> unresolved third playback target (Sampler/Aux is only a working hypothesis)

Quick verification commands:
  speaker-test -D hw:DDJ1000,0 -c 6 -r 44100 -F S24_3LE -t sine -f 440 -s 1 -l 1 -b 20000 -p 10000 -S 60
  speaker-test -D hw:DDJ1000,0 -c 6 -r 44100 -F S24_3LE -t sine -f 440 -s 2 -l 1 -b 20000 -p 10000 -S 60
  speaker-test -D hw:DDJ1000,0 -c 6 -r 44100 -F S24_3LE -t sine -f 440 -s 3 -l 1 -b 20000 -p 10000 -S 60
  speaker-test -D hw:DDJ1000,0 -c 6 -r 44100 -F S24_3LE -t sine -f 440 -s 4 -l 1 -b 20000 -p 10000 -S 60
  speaker-test -D hw:DDJ1000,0 -c 6 -r 44100 -F S24_3LE -t sine -f 440 -s 5 -l 1 -b 20000 -p 10000 -S 60
  speaker-test -D hw:DDJ1000,0 -c 6 -r 44100 -F S24_3LE -t sine -f 440 -s 6 -l 1 -b 20000 -p 10000 -S 60

To restore the stock driver:
  sudo modprobe -r snd_usb_audio snd_usbmidi_lib
  sudo modprobe snd_usb_audio
EOF