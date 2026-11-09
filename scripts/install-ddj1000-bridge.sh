#!/usr/bin/env bash
#
# DDJ-1000 bridge layer: everything that has to start automatically when the controller is plugged in.
#
#   - runtime scripts -> /usr/local/lib/ddj1000-linux-driver (the repo clone can move or go away)
#   - snd-virmidi at boot (card "DDJBridge", index 7 -> Mixxx port "VirMIDI 7-0")
#   - ddj1000-bridge@.service + udev rule: unlock, heartbeat, MIDI for Mixxx, jog displays
#     (fallback --no-bridge: oneshot ddj1000-unlock@.service, no jog displays)
#   - kernel hooks + boot check: rebuild the patched snd-usb-audio after kernel updates
#
# usage: install-ddj1000-bridge.sh install [--no-bridge] | uninstall | status
#   target user: $DDJ1000_USER, else the sudo caller, else the current user (never root)

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
lib_dir="/usr/local/lib/ddj1000-linux-driver"
systemd_dir="/etc/systemd/system"
udev_dir="/etc/udev/rules.d"
bridge_rule="92-ddj1000-bridge.rules"
unlock_rule="92-ddj1000-unlock.rules"
hook_name="zz-ddj1000-snd-usb-audio"
target_user="${DDJ1000_USER:-${SUDO_USER:-$(id -un)}}"

have_command() { command -v "$1" >/dev/null 2>&1; }

run_privileged() {
    if [[ "$EUID" -eq 0 ]]; then
        "$@"
    elif have_command sudo; then
        sudo "$@"
    else
        echo "[ERROR] root rights required, sudo unavailable: $*" >&2
        exit 1
    fi
}

render_unit() {   # <source> <target>: fill in @USER@ / @LIBDIR@
    local tmp
    tmp="$(mktemp)"
    sed -e "s#@USER@#$target_user#g" -e "s#@LIBDIR@#$lib_dir#g" "$1" > "$tmp"
    run_privileged install -m 0644 "$tmp" "$2"
    rm -f "$tmp"
}

deploy_lib() {
    echo "[INFO] runtime files -> $lib_dir"
    run_privileged install -d "$lib_dir/scripts/runtime" "$lib_dir/scripts/dev" "$lib_dir/patches" "$lib_dir/docs"
    local f
    for f in "$repo_root"/scripts/runtime/*.py "$repo_root"/scripts/runtime/*.sh; do
        run_privileged install -m 0755 "$f" "$lib_dir/scripts/runtime/"
    done
    run_privileged install -m 0755 "$repo_root/scripts/dev/ddj1000-unlock-test.py" "$lib_dir/scripts/dev/"
    run_privileged install -m 0755 "$repo_root/scripts/dev/prepare-ddj1000-snd-usb-audio-module.sh" "$lib_dir/scripts/dev/"
    run_privileged install -m 0755 "$repo_root/scripts/ddj1000-kernel-rebuild.sh" "$lib_dir/scripts/"
    run_privileged rm -rf "$lib_dir/patches/linux"
    run_privileged cp -r "$repo_root/patches/linux" "$lib_dir/patches/"
    [[ -f "$repo_root/docs/bridge.md" ]] && run_privileged install -m 0644 "$repo_root/docs/bridge.md" "$lib_dir/docs/"
    # the build script resolves the repo root as scripts/dev/../.. -> $lib_dir: patches/ must sit there
    return 0
}

install_virmidi() {
    echo "[INFO] snd-virmidi at boot (card DDJBridge, index 7)"
    run_privileged install -m 0644 "$repo_root/config/modprobe/ddj1000-virmidi.conf" /etc/modprobe.d/ddj1000-virmidi.conf
    run_privileged install -m 0644 "$repo_root/config/modprobe/ddj1000-virmidi-load.conf" /etc/modules-load.d/ddj1000-virmidi.conf
    if ! grep -q "\[DDJBridge" /proc/asound/cards 2>/dev/null; then
        run_privileged modprobe snd-virmidi || echo "[WARN] modprobe snd-virmidi failed (card index 7 taken?)" >&2
    fi
}

install_kernel_hooks() {
    echo "[INFO] kernel hooks: rebuild the patched snd-usb-audio after kernel updates"
    local d
    for d in /etc/kernel/postinst.d /etc/kernel/header_postinst.d; do
        run_privileged install -D -m 0755 "$repo_root/config/kernel/$hook_name" "$d/$hook_name"
    done
    run_privileged install -m 0644 "$repo_root/config/systemd/system/ddj1000-module-check.service" \
        "$systemd_dir/ddj1000-module-check.service"
}

disable_keepalive_unlock() {
    # the old permanent unlock services hold the rawmidi port the bridge needs
    run_privileged systemctl disable --now ddj1000-unlock.service >/dev/null 2>&1 || true
    if [[ "$(id -un)" == "$target_user" ]]; then
        systemctl --user disable --now ddj1000-unlock.service >/dev/null 2>&1 || true
    else
        echo "[INFO] if $target_user has a user unit ddj1000-unlock.service: systemctl --user disable --now ddj1000-unlock.service"
    fi
}

install_all() {
    local mode="bridge"
    [[ "${1:-}" == "--no-bridge" ]] && mode="unlock"
    if [[ "$target_user" == "root" ]]; then
        echo "[ERROR] target user is root - run as the DJ user (with sudo) or set DDJ1000_USER" >&2
        exit 1
    fi
    echo "[INFO] target user: $target_user, mode: $mode"
    deploy_lib
    render_unit "$repo_root/config/systemd/system/ddj1000-bridge@.service" "$systemd_dir/ddj1000-bridge@.service"
    render_unit "$repo_root/config/systemd/system/ddj1000-unlock@.service" "$systemd_dir/ddj1000-unlock@.service"
    install_virmidi
    install_kernel_hooks
    if [[ "$mode" == "bridge" ]]; then
        run_privileged rm -f "$udev_dir/$unlock_rule"
        run_privileged install -m 0644 "$repo_root/config/udev/$bridge_rule" "$udev_dir/$bridge_rule"
        disable_keepalive_unlock
    else
        run_privileged rm -f "$udev_dir/$bridge_rule"
        run_privileged install -m 0644 "$repo_root/config/udev/$unlock_rule" "$udev_dir/$unlock_rule"
    fi
    run_privileged usermod -aG audio,plugdev "$target_user"
    run_privileged systemctl daemon-reload
    run_privileged systemctl enable ddj1000-module-check.service
    run_privileged udevadm control --reload-rules
    if [[ "$mode" == "bridge" ]] && ! systemctl is-active --quiet 'ddj1000-bridge@*'; then
        # start now if the DDJ is already plugged in (otherwise udev starts it on plug-in)
        run_privileged udevadm trigger --action=add --subsystem-match=sound \
            --attr-match=idVendor=2b73 --attr-match=idProduct=0020 2>/dev/null || true
    fi
    echo
    echo "Done. Groups changed? log out and in again. Check: bash $0 status"
}

uninstall_all() {
    run_privileged systemctl stop 'ddj1000-bridge@*.service' 'ddj1000-unlock@*.service' >/dev/null 2>&1 || true
    run_privileged systemctl disable ddj1000-module-check.service >/dev/null 2>&1 || true
    run_privileged rm -f "$udev_dir/$bridge_rule" "$udev_dir/$unlock_rule" \
        "$systemd_dir/ddj1000-bridge@.service" "$systemd_dir/ddj1000-unlock@.service" \
        "$systemd_dir/ddj1000-module-check.service" \
        /etc/modprobe.d/ddj1000-virmidi.conf /etc/modules-load.d/ddj1000-virmidi.conf \
        "/etc/kernel/postinst.d/$hook_name" "/etc/kernel/header_postinst.d/$hook_name"
    run_privileged rm -rf "$lib_dir/scripts/runtime" "$lib_dir/scripts/dev" "$lib_dir/patches" "$lib_dir/docs" \
        "$lib_dir/scripts/ddj1000-kernel-rebuild.sh"
    run_privileged systemctl daemon-reload
    run_privileged udevadm control --reload-rules
    echo "Removed the bridge layer (installed kernel modules stay; remove with install-ddj1000-audio-driver.sh uninstall)."
}

status() {
    local kver mod
    kver="$(uname -r)"
    printf '%-26s %s\n' "target user" "$target_user"
    printf '%-26s %s\n' "runtime files" "$( [[ -f $lib_dir/scripts/runtime/ddj1000-bridge.py ]] && echo "$lib_dir" || echo missing)"
    printf '%-26s %s\n' "udev mode" "$( [[ -f $udev_dir/$bridge_rule ]] && echo bridge || { [[ -f $udev_dir/$unlock_rule ]] && echo "unlock (no bridge)" || echo "none"; })"
    printf '%-26s %s\n' "snd-virmidi card" "$(grep -o '^ *[0-9]* \[DDJBridge' /proc/asound/cards | tr -s ' ' || echo 'not loaded')"
    printf '%-26s %s\n' "snd-virmidi at boot" "$( [[ -f /etc/modules-load.d/ddj1000-virmidi.conf ]] && echo yes || echo no)"
    mod="$(modinfo -n snd_usb_audio 2>/dev/null || true)"
    printf '%-26s %s\n' "snd-usb-audio ($kver)" "${mod:-missing} $( [[ $mod == */updates/ddj1000-linux-driver/* ]] && echo '(patched)' || echo '(STOCK - DDJ audio will fail)')"
    printf '%-26s %s\n' "kernel hooks" "$( [[ -x /etc/kernel/postinst.d/$hook_name && -x /etc/kernel/header_postinst.d/$hook_name ]] && echo installed || echo missing)"
    printf '%-26s %s\n' "module check at boot" "$(systemctl is-enabled ddj1000-module-check.service 2>/dev/null || echo missing)"
    printf '%-26s %s\n' "bridge service" "$(systemctl list-units --no-legend 'ddj1000-bridge@*' 2>/dev/null | awk '{print $1" "$3"/"$4}' | head -1)"
    printf '%-26s %s\n' "unlocked flag" "$( [[ -e /run/ddj1000/unlocked ]] && echo "yes (/run/ddj1000/unlocked)" || echo no)"
    printf '%-26s %s\n' "groups of $target_user" "$(id -nG "$target_user" 2>/dev/null | tr ' ' '\n' | grep -E '^(audio|plugdev)$' | tr '\n' ' ')"
    echo
    echo "bridge log: journalctl -u 'ddj1000-bridge@*' -b --no-pager | tail -30"
}

case "${1:-help}" in
    install) shift; install_all "$@" ;;
    uninstall) uninstall_all ;;
    status) status ;;
    *) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//' ;;
esac
