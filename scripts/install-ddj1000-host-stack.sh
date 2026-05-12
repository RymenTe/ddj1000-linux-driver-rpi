#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
alsa_source="$repo_root/config/alsa/60-ddj1000-host-stack.conf"
service_source="$repo_root/config/systemd/user/ddj1000-host-stack.service"
unlock_service_source="$repo_root/config/systemd/user/ddj1000-unlock.service"
audio_rebind_service_source="$repo_root/config/systemd/system/ddj1000-audio-rebind.service"
audio_rebind_path_source="$repo_root/config/systemd/system/ddj1000-audio-rebind.path"
service_script_source="$repo_root/scripts/runtime/ddj1000-host-stack-service.sh"
unlock_script_source="$repo_root/scripts/runtime/ddj1000-unlock-service.py"
audio_rebind_script_source="$repo_root/scripts/runtime/ddj1000-audio-rebind.sh"
startup_prep_source="$repo_root/scripts/runtime/ddj1000-startup-prep.sh"
probe_usb_source="$repo_root/scripts/runtime/ddj1000-usb-probe.py"
audio_stream_source="$repo_root/scripts/runtime/ddj1000-audio-stream.py"
docs_source="$repo_root/docs/install.md"

alsa_target_dir="/etc/alsa/conf.d"
alsa_target="$alsa_target_dir/60-ddj1000-host-stack.conf"
service_script_target="/usr/local/bin/ddj1000-host-stack-service.sh"
unlock_script_target="/usr/local/bin/ddj1000-unlock-service.py"
audio_rebind_script_target="/usr/local/bin/ddj1000-audio-rebind.sh"
support_root_target="/usr/local/lib/ddj1000-linux-driver"
support_scripts_target_dir="$support_root_target/scripts"
startup_prep_target="$support_scripts_target_dir/ddj1000-startup-prep.sh"
probe_usb_target="$support_scripts_target_dir/ddj1000-usb-probe.py"
audio_stream_target="$support_scripts_target_dir/ddj1000-audio-stream.py"
user_systemd_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
system_systemd_dir="/etc/systemd/system"
user_service_target="$user_systemd_dir/ddj1000-host-stack.service"
unlock_user_service_target="$user_systemd_dir/ddj1000-unlock.service"
audio_rebind_service_target="$system_systemd_dir/ddj1000-audio-rebind.service"
audio_rebind_path_target="$system_systemd_dir/ddj1000-audio-rebind.path"

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

install_files() {
    if [[ ! -f "$alsa_source" || ! -f "$service_source" || ! -f "$unlock_service_source" || ! -f "$audio_rebind_service_source" || ! -f "$audio_rebind_path_source" || ! -f "$service_script_source" || ! -f "$unlock_script_source" || ! -f "$audio_rebind_script_source" || ! -f "$startup_prep_source" || ! -f "$probe_usb_source" || ! -f "$audio_stream_source" ]]; then
        echo "[ERROR] Host-stack source files missing in repo." >&2
        exit 1
    fi

    run_privileged install -d "$alsa_target_dir"
    run_privileged install -d "$system_systemd_dir"
    run_privileged install -d "$support_scripts_target_dir"
    run_privileged install -m 0644 "$alsa_source" "$alsa_target"
    run_privileged install -m 0755 "$service_script_source" "$service_script_target"
    run_privileged install -m 0755 "$unlock_script_source" "$unlock_script_target"
    run_privileged install -m 0755 "$audio_rebind_script_source" "$audio_rebind_script_target"
    run_privileged install -m 0755 "$startup_prep_source" "$startup_prep_target"
    run_privileged install -m 0644 "$probe_usb_source" "$probe_usb_target"
    run_privileged install -m 0644 "$audio_stream_source" "$audio_stream_target"
    run_privileged install -m 0644 "$audio_rebind_service_source" "$audio_rebind_service_target"
    run_privileged install -m 0644 "$audio_rebind_path_source" "$audio_rebind_path_target"

    mkdir -p "$user_systemd_dir"
    install -m 0644 "$service_source" "$user_service_target"
    install -m 0644 "$unlock_service_source" "$unlock_user_service_target"
}

enable_service() {
    if ! have_command systemctl; then
        echo "[WARN] systemctl not found. Installed files only." >&2
        return 0
    fi

    systemctl --user daemon-reload
    systemctl --user enable --now ddj1000-host-stack.service || true
    systemctl --user enable --now ddj1000-unlock.service || true
    run_privileged systemctl daemon-reload
    run_privileged systemctl enable --now ddj1000-audio-rebind.path || true
}

disable_service() {
    if have_command systemctl; then
        systemctl --user disable --now ddj1000-host-stack.service >/dev/null 2>&1 || true
        systemctl --user disable --now ddj1000-unlock.service >/dev/null 2>&1 || true
        systemctl --user daemon-reload >/dev/null 2>&1 || true
        run_privileged systemctl disable --now ddj1000-audio-rebind.path >/dev/null 2>&1 || true
        run_privileged systemctl daemon-reload >/dev/null 2>&1 || true
    fi
}

remove_files() {
    disable_service
    rm -f "$user_service_target"
    rm -f "$unlock_user_service_target"
    run_privileged rm -f "$service_script_target" "$unlock_script_target" "$audio_rebind_script_target" "$startup_prep_target" "$probe_usb_target" "$audio_stream_target" "$audio_rebind_service_target" "$audio_rebind_path_target" "$alsa_target"
    run_privileged rmdir "$support_scripts_target_dir" 2>/dev/null || true
    run_privileged rmdir "$support_root_target" 2>/dev/null || true
}

status() {
    echo "DDJ-1000 host-stack status"
    echo
    printf '%-18s %s\n' "ALSA config" "$( [[ -f "$alsa_target" ]] && echo installed || echo missing )"
    printf '%-18s %s\n' "Service script" "$( [[ -f "$service_script_target" ]] && echo installed || echo missing )"
    printf '%-18s %s\n' "Unlock script" "$( [[ -f "$unlock_script_target" ]] && echo installed || echo missing )"
    printf '%-18s %s\n' "Rebind helper" "$( [[ -f "$audio_rebind_script_target" && -f "$audio_rebind_service_target" && -f "$audio_rebind_path_target" ]] && echo installed || echo missing )"
    printf '%-18s %s\n' "Prep bundle" "$( [[ -f "$startup_prep_target" && -f "$probe_usb_target" && -f "$audio_stream_target" ]] && echo installed || echo missing )"
    printf '%-18s %s\n' "User service" "$( [[ -f "$user_service_target" ]] && echo installed || echo missing )"
    printf '%-18s %s\n' "Unlock service" "$( [[ -f "$unlock_user_service_target" ]] && echo installed || echo missing )"
    printf '%-18s %s\n' "Docs" "$docs_source"
    echo
    echo "Named ALSA devices expected after install:"
    echo "  ddj1000_master"
    echo "  ddj1000_cue"
    echo "  ddj1000_aux"
}

usage() {
    cat <<'EOF'
Usage: ./scripts/install-ddj1000-host-stack.sh <command>

Commands:
    install     Install ALSA mappings, the DDJ unlock keepalive, and the optional user-level desktop sink service.
    uninstall   Remove installed ALSA mappings, the DDJ unlock keepalive, and the optional desktop sink service.
  status      Show installed host-stack components.
  help        Show this help.

Notes:
  - This host-stack layer assumes the patched DDJ-1000 snd-usb-audio path is already available.
  - ALSA mappings are system-wide under /etc/alsa/conf.d.
    - The unlock service keeps the validated `50 01 -> 11 02 -> 12 2A -> 13 2A -> 14 38 -> 15 02` MIDI path alive.
    - A system-level rebind helper restores `snd_usb_audio` after the short proprietary post-unlock burst.
        - The unlock service also installs the startup-prep helper bundle under /usr/local/lib/ddj1000-linux-driver.
  - The user service creates desktop sinks only when pactl is available.
EOF
}

main() {
    case "${1:-help}" in
        install)
            install_files
            enable_service
            status
            ;;
        uninstall)
            remove_files
            status
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