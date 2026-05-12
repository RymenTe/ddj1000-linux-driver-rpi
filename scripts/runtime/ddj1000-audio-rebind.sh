#!/usr/bin/env bash

set -euo pipefail

request_file="/tmp/ddj1000-audio-rebind-request"

rm -f "$request_file"

modprobe -r snd_usb_audio snd_usbmidi_lib || true
modprobe snd_usb_audio || true
udevadm settle || true