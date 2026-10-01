#!/usr/bin/env bash

set -euo pipefail

request_file="/tmp/ddj1000-audio-rebind-request"

# Remove the request only once the driver is back, so the unlock service can
# wait on it instead of guessing how long the rebind takes. The trap also
# clears it on failure so the path unit does not retrigger in a loop.
trap 'rm -f "$request_file"' EXIT

modprobe -r snd_usb_audio snd_usbmidi_lib || true
modprobe snd_usb_audio || true
udevadm settle --timeout=10 || true
