#!/usr/bin/env bash
# Build + install the patched snd-usb-audio / snd-usbmidi-lib (always both, CLAUDE.md rule 7) for one kernel.
# Called as root by the kernel hooks (/etc/kernel/{postinst,header_postinst}.d/zz-ddj1000-snd-usb-audio)
# and at boot by ddj1000-module-check.service. Idempotent: does nothing if the module for that kernel exists.
#   usage: ddj1000-kernel-rebuild.sh <kernel-version> [--load]
#   --load: afterwards reload snd-usb-audio if <kernel-version> is the running kernel
set -uo pipefail

version="${1:?usage: $0 <kernel-version> [--load]}"
load=0
[[ "${2:-}" == "--load" ]] && load=1
lib="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
target="/lib/modules/$version/updates/ddj1000-linux-driver"
build="${DDJ1000_BUILD_DIR:-/var/lib/ddj1000/build}"
log() { echo "$(date '+%F %T') [ddj1000 $version] $*"; }

if [[ "$EUID" -ne 0 ]]; then
    log "must run as root"
    exit 1
fi
if [[ -f "$target/snd-usb-audio.ko" && -f "$target/snd-usbmidi-lib.ko" ]] &&
   [[ "$(modinfo -F vermagic "$target/snd-usb-audio.ko" 2>/dev/null | awk '{print $1}')" == "$version" ]]; then
    log "patched module already installed ($target)"
    exit 0
fi
if [[ ! -d "/lib/modules/$version/build" ]]; then
    log "kernel headers missing (/lib/modules/$version/build) - skipped; the header hook or the boot check retries"
    exit 0
fi

log "building patched snd-usb-audio (needs network for the kernel source of the matching stable tag)"
mkdir -p "$build"
if ! DDJ1000_BUILD_DIR="$build" DDJ1000_WORK_DIR="/var/lib/ddj1000/src" \
        bash "$lib/scripts/dev/prepare-ddj1000-snd-usb-audio-module.sh" --kernel-version "$version"; then
    log "BUILD FAILED - the DDJ-1000 will have no audio with this kernel until it is fixed"
    exit 1
fi
install -d "$target"
install -m 0644 "$build/snd-usb-audio-ddj1000.ko" "$target/snd-usb-audio.ko"
install -m 0644 "$build/snd-usbmidi-lib-test.ko" "$target/snd-usbmidi-lib.ko"
depmod -a "$version"
log "installed to $target"

if (( load )) && [[ "$version" == "$(uname -r)" ]]; then
    log "reloading snd-usb-audio"
    modprobe -r snd_usb_audio snd_usbmidi_lib 2>/dev/null || log "WARN: snd-usb-audio busy, active after reboot/replug"
    modprobe snd_usb_audio || true
fi
exit 0
