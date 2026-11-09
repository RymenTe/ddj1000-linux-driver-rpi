#!/usr/bin/env bash
#
# Hook the DDJ-1000 stack into the mixxx-pi-gen image
# (https://github.com/fayaaz/mixxx-pi-gen).
#
# The image starts Mixxx from the sway config and from the waybar / i3blocks
# "MIXXX" buttons, all via /usr/bin/mixxx. This points those launchers at
# /usr/local/bin/mixxx-after-ddj1000 so Mixxx waits for the unlock + rebind.

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"

wrapper_source="$repo_root/scripts/runtime/mixxx-after-ddj1000.sh"
wrapper_target="/usr/local/bin/mixxx-after-ddj1000"
session_user="${DDJ1000_SESSION_USER:-${SUDO_USER:-$(id -un)}}"

run_privileged() {
    if [[ "$EUID" -eq 0 ]]; then
        "$@"
    else
        sudo "$@"
    fi
}

user_home() {
    getent passwd "$session_user" | cut -d: -f6
}

launcher_files() {
    local home
    home="$(user_home)"
    [[ -n "$home" ]] || return 0
    printf '%s\n' \
        "$home/.config/sway/config" \
        "$home/.config/waybar/mixxx.sh" \
        "$home/.config/i3blocks/scripts/mixxx.sh"
}

is_mixxx_pi_gen() {
    [[ -f /opt/mixxx.tag || -f /opt/mixxx.version ]] && return 0
    local home
    home="$(user_home)"
    [[ -n "$home" && -f "$home/.config/sway/config" ]] &&
        grep -q 'exec /usr/bin/mixxx\|exec /usr/local/bin/mixxx-after-ddj1000' "$home/.config/sway/config"
}

# Rewrite in place without changing owner or mode (the files belong to pi).
rewrite_file() {
    local file="$1" from="$2" to="$3" tmp
    [[ -f "$file" ]] || return 0
    grep -qF "$from" "$file" || return 0
    if [[ ! -f "$file.ddj1000.bak" ]]; then
        run_privileged cp -p "$file" "$file.ddj1000.bak"
    fi
    tmp="$(mktemp)"
    # Only touch launcher lines, never other mentions of mixxx.
    sed "/exec/ s|$from|$to|g" "$file" > "$tmp"
    run_privileged sh -c 'cat "$1" > "$2"' _ "$tmp" "$file"
    rm -f "$tmp"
    echo "  patched $file"
}

install_integration() {
    if ! is_mixxx_pi_gen; then
        echo "mixxx-pi-gen image not detected (no /opt/mixxx.tag, no sway Mixxx autostart); nothing to do."
        return 0
    fi
    run_privileged install -m 0755 "$wrapper_source" "$wrapper_target"
    echo "  installed $wrapper_target"
    local file
    while IFS= read -r file; do
        rewrite_file "$file" "/usr/bin/mixxx" "$wrapper_target"
    done < <(launcher_files)
    echo "Mixxx now starts after the DDJ-1000 unlock (applies from the next login / reboot)."
}

uninstall_integration() {
    local file
    while IFS= read -r file; do
        rewrite_file "$file" "$wrapper_target" "/usr/bin/mixxx"
    done < <(launcher_files)
    run_privileged rm -f "$wrapper_target"
    echo "mixxx-pi-gen launchers point at /usr/bin/mixxx again."
}

status() {
    local file state
    if is_mixxx_pi_gen; then
        printf '%-18s %s\n' "mixxx-pi-gen" "detected ($(cat /opt/mixxx.tag 2>/dev/null || echo 'unknown Mixxx tag'))"
    else
        printf '%-18s %s\n' "mixxx-pi-gen" "not detected"
        return 0
    fi
    printf '%-18s %s\n' "Mixxx wrapper" "$( [[ -x "$wrapper_target" ]] && echo installed || echo missing )"
    while IFS= read -r file; do
        [[ -f "$file" ]] || continue
        if grep -qF "$wrapper_target" "$file"; then
            state="waits for unlock"
        elif grep -q "exec.*/usr/bin/mixxx" "$file"; then
            state="starts Mixxx directly"
        else
            state="no Mixxx launcher"
        fi
        printf '%-18s %s (%s)\n' "Launcher" "$state" "$file"
    done < <(launcher_files)
}

usage() {
    cat <<EOF
Usage: $0 <install|uninstall|status>

Points the mixxx-pi-gen Mixxx launchers (sway autostart, waybar and i3blocks
buttons) at $wrapper_target, which waits for /run/ddj1000/unlocked when a
DDJ-1000 is attached. Originals are kept as *.ddj1000.bak.

DDJ1000_SESSION_USER (default: pi) selects whose sway config is changed.
EOF
}

case "${1:-help}" in
    install) install_integration ;;
    uninstall) uninstall_integration ;;
    status) status ;;
    help|-h|--help) usage ;;
    *) usage >&2; exit 2 ;;
esac
