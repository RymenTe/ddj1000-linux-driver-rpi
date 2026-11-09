#!/usr/bin/env bash
#
# Start Mixxx only after the DDJ-1000 unlock + audio rebind has finished.
#
# The unlock service rebinds snd-usb-audio after the handshake. If Mixxx is
# already running at that moment it loses its sound device, and it also holds
# the MIDI port the unlock needs. Images such as mixxx-pi-gen start Mixxx
# straight from the sway config, so their launchers call this wrapper instead
# of /usr/bin/mixxx.
#
# Without a DDJ-1000 attached Mixxx starts immediately, so other controllers
# keep working unchanged.

set -uo pipefail

mixxx_bin="${MIXXX_BIN:-/usr/bin/mixxx}"
ready_flag="${DDJ1000_READY_FLAG:-/run/ddj1000/unlocked}"
timeout_s="${DDJ1000_WAIT_TIMEOUT:-60}"
lock_file="${XDG_RUNTIME_DIR:-/tmp}/mixxx-after-ddj1000.lock"

notify() {
    command -v notify-send >/dev/null 2>&1 && notify-send -a Mixxx "DDJ-1000" "$1" || true
    echo "[mixxx-after-ddj1000] $1" >&2
}

ddj_present() {
    local dev
    for dev in /sys/bus/usb/devices/*; do
        [[ -r "$dev/idVendor" && -r "$dev/idProduct" ]] || continue
        if [[ "$(<"$dev/idVendor")" == "2b73" && "$(<"$dev/idProduct")" == "0020" ]]; then
            return 0
        fi
    done
    return 1
}

# The launcher buttons only check `pgrep -x mixxx`, which does not see this
# wrapper while it waits. Hold a lock so repeated clicks do not queue up
# several Mixxx instances.
exec 9>"$lock_file"
if ! flock -n 9; then
    notify "Mixxx start already pending, waiting for the DDJ-1000 unlock."
    exit 0
fi

if ddj_present && [[ ! -e "$ready_flag" ]]; then
    notify "Waiting for DDJ-1000 unlock before starting Mixxx..."
    waited=0
    while [[ ! -e "$ready_flag" ]]; do
        if (( waited >= timeout_s )); then
            notify "DDJ-1000 not unlocked after ${timeout_s}s, starting Mixxx anyway. Check: journalctl -u ddj1000-unlock.service"
            break
        fi
        sleep 1
        waited=$((waited + 1))
    done
fi

# Release the lock for the Mixxx process itself.
exec 9>&-
exec "$mixxx_bin" "$@"
