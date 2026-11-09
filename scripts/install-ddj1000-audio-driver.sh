#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
build_dir="$repo_root/build/ddj1000-driver"
audio_source="$build_dir/snd-usb-audio-ddj1000.ko"
midi_source="$build_dir/snd-usbmidi-lib-test.ko"
der_file="$build_dir/ddj1000-linux-driver-mok.der"
prepare_script="$repo_root/scripts/dev/prepare-ddj1000-snd-usb-audio-module.sh"

kernel_version="$(uname -r)"
target_dir="/lib/modules/$kernel_version/updates/ddj1000-linux-driver"
audio_target="$target_dir/snd-usb-audio.ko"
midi_target="$target_dir/snd-usbmidi-lib.ko"
depmod_conf="/etc/depmod.d/ddj1000-linux-driver.conf"

have_command() {
    command -v "$1" >/dev/null 2>&1
}

run_privileged() {
    if [[ "$EUID" -eq 0 ]]; then
        "$@"
        return
    fi
    if have_command sudo; then
        sudo "$@"
        return
    fi
    echo "[ERROR] Root rights required, but sudo is unavailable: $*" >&2
    exit 1
}

ensure_built_modules() {
    local audio_vermagic
    local midi_vermagic

    if [[ ! -f "$audio_source" || ! -f "$midi_source" ]]; then
        echo "[INFO] Missing built DDJ-1000 modules, rebuilding them now."
        bash "$prepare_script"
    fi

    audio_vermagic="$(modinfo -F vermagic "$audio_source" | awk '{print $1}')"
    midi_vermagic="$(modinfo -F vermagic "$midi_source" | awk '{print $1}')"
    if [[ "$audio_vermagic" != "$kernel_version" || "$midi_vermagic" != "$kernel_version" ]]; then
        echo "[INFO] Built modules target a different kernel, rebuilding for $kernel_version."
        bash "$prepare_script"
    fi
}

show_mok_status() {
    if [[ -f "$der_file" ]] && have_command mokutil; then
        echo
        echo "Secure Boot MOK status:"
        mokutil --test-key "$der_file" || true
    fi
}

reload_modules() {
    run_privileged modprobe -r snd_usb_audio snd_usbmidi_lib || true
    run_privileged modprobe snd_usb_audio
}

install_driver() {
    ensure_built_modules

    run_privileged install -d "$target_dir"
    run_privileged install -m 0644 "$audio_source" "$audio_target"
    run_privileged install -m 0644 "$midi_source" "$midi_target"
    # Make the override explicit. Raspberry Pi OS ships the stock modules as
    # .ko.xz under kernel/; this pins modprobe to our copies regardless of the
    # distro's depmod search order.
    {
        for name in snd_usb_audio snd-usb-audio snd_usbmidi_lib snd-usbmidi-lib; do
            printf 'override %s %s updates/ddj1000-linux-driver\n' "$name" "$kernel_version"
        done
    } | run_privileged tee "$depmod_conf" >/dev/null
    run_privileged depmod -a "$kernel_version"

    reload_modules || true

    echo
    echo "Installed DDJ-1000 audio-driver modules to:"
    echo "  $target_dir"
    show_mok_status
    echo
    echo "Active snd_usb_audio path:"
    modinfo -n snd_usb_audio || true
    echo
    echo "Playback devices:"
    aplay -l || true
}

uninstall_driver() {
    run_privileged modprobe -r snd_usb_audio snd_usbmidi_lib || true
    run_privileged rm -f "$audio_target" "$midi_target"
    run_privileged rmdir "$target_dir" 2>/dev/null || true
    run_privileged rm -f "$depmod_conf"
    run_privileged depmod -a "$kernel_version"
    run_privileged modprobe snd_usb_audio || true

    echo
    echo "Removed DDJ-1000 override modules from:"
    echo "  $target_dir"
    echo
    echo "Active snd_usb_audio path:"
    modinfo -n snd_usb_audio || true
}

status() {
    local active_path
    active_path="$(modinfo -n snd_usb_audio 2>/dev/null || true)"

    echo "DDJ-1000 audio-driver status"
    echo
    printf '%-22s %s\n' "Built audio module" "$( [[ -f "$audio_source" ]] && echo present || echo missing )"
    printf '%-22s %s\n' "Built MIDI module" "$( [[ -f "$midi_source" ]] && echo present || echo missing )"
    printf '%-22s %s\n' "Installed audio module" "$( [[ -f "$audio_target" ]] && echo installed || echo missing )"
    printf '%-22s %s\n' "Installed MIDI module" "$( [[ -f "$midi_target" ]] && echo installed || echo missing )"
    printf '%-22s %s\n' "Active snd_usb_audio" "${active_path:-unknown}"
    if grep -q "snd_usb_audio.lowlatency=0" /proc/cmdline 2>/dev/null; then
        echo "[WARN] snd_usb_audio.lowlatency=0 is on the kernel cmdline; it breaks DDJ-1000 detection. Remove it."
    fi
    show_mok_status
}

usage() {
    cat <<'EOF'
Usage: ./scripts/install-ddj1000-audio-driver.sh <command>

Commands:
  install     Build missing modules if needed, install them system-wide, run depmod, and try to reload snd_usb_audio.
  uninstall   Remove the installed override modules and reload the stock snd_usb_audio path.
  status      Show built, installed, and active module state.
  help        Show this help.

Notes:
    - Modules are installed under /lib/modules/$(uname -r)/updates/ddj1000-linux-driver.
  - With Secure Boot enabled, the local MOK still needs to be enrolled once.
EOF
}

main() {
    case "${1:-help}" in
        install)
            install_driver
            ;;
        uninstall)
            uninstall_driver
            ;;
        status)
            status
            ;;
        help|-h|--help)
            usage
            ;;
        *)
            echo "Unknown command: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
}

main "$@"