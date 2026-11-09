#!/usr/bin/env bash
#
# DDJ-1000 Mixxx setup for the current user (run as the DJ user, not as root; Mixxx must be closed):
#   mapping DDJ-1000 on the bridge port "VirMIDI 7-0", PAD FX / Color FX presets, skin Pioneered-4Deck,
#   sound DDJ-1000 Master 1/2 + Headphones 3/4 (via scripts/ddj1000-mixxx-config.py which backs up first)
#   start wrapper /usr/local/bin/mixxx-after-ddj1000 (starts Mixxx once the DDJ is unlocked).
#
# usage: install-ddj1000-mixxx.sh install [--autostart] [--dry-run] | status
#   --autostart: XDG autostart entry (Raspberry Pi OS desktop: labwc/wayfire) that runs the wrapper.
#                sway images (mixxx-pi-gen) are handled by install-mixxx-pi-gen-integration.sh.

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
wrapper_target="/usr/local/bin/mixxx-after-ddj1000"
autostart_file="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/mixxx-ddj1000.desktop"

run_privileged() {
    if [[ "$EUID" -eq 0 ]]; then "$@"; else sudo "$@"; fi
}

install_mixxx() {
    local autostart=0 dry=()
    for arg in "$@"; do
        case "$arg" in
            --autostart) autostart=1 ;;
            --dry-run) dry=(--dry-run) ;;
        esac
    done
    if [[ "$EUID" -eq 0 ]]; then
        echo "[ERROR] run as the DJ user (Mixxx settings live in that user's home)" >&2
        exit 1
    fi
    python3 -I "$repo_root/scripts/ddj1000-mixxx-config.py" "${dry[@]}"
    [[ ${#dry[@]} -gt 0 ]] && return 0
    run_privileged install -m 0755 "$repo_root/scripts/runtime/mixxx-after-ddj1000.sh" "$wrapper_target"
    echo "start wrapper: $wrapper_target"
    if (( autostart )); then
        mkdir -p "$(dirname "$autostart_file")"
        cat > "$autostart_file" <<EOT
[Desktop Entry]
Type=Application
Name=Mixxx (DDJ-1000)
Comment=Starts Mixxx once the DDJ-1000 is unlocked by the bridge
Exec=$wrapper_target
X-GNOME-Autostart-enabled=true
EOT
        echo "autostart: $autostart_file"
    fi
}

status() {
    python3 -I "$repo_root/scripts/ddj1000-mixxx-config.py" --dry-run
    printf '%-18s %s\n' "start wrapper" "$( [[ -x $wrapper_target ]] && echo "$wrapper_target" || echo missing)"
    printf '%-18s %s\n' "XDG autostart" "$( [[ -f $autostart_file ]] && echo "$autostart_file" || echo no)"
}

case "${1:-help}" in
    install) shift; install_mixxx "$@" ;;
    status) status ;;
    *) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//' ;;
esac
