#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"

setup_script="$repo_root/scripts/setup-linux.sh"
driver_script="$repo_root/scripts/install-ddj1000-audio-driver.sh"
host_stack_script="$repo_root/scripts/install-ddj1000-host-stack.sh"
mixxx_pi_gen_script="$repo_root/scripts/install-mixxx-pi-gen-integration.sh"
bridge_script="$repo_root/scripts/install-ddj1000-bridge.sh"
mixxx_script="$repo_root/scripts/install-ddj1000-mixxx.sh"

run_step() {
    echo
    echo "== $1 =="
    shift
    "$@"
}

install_stack() {
    run_step "Install DDJ udev rules" bash "$setup_script" install-udev
    run_step "Install DDJ audio-driver override" bash "$driver_script" install
    run_step "Install DDJ host-stack layer" env DDJ1000_UNLOCK_MODE="${DDJ1000_UNLOCK_MODE:-bridge}" \
        bash "$host_stack_script" install
    run_step "Install DDJ bridge (autostart, snd-virmidi, kernel hooks)" bash "$bridge_script" install "$@"
    run_step "mixxx-pi-gen integration" bash "$mixxx_pi_gen_script" install
    if pgrep -x mixxx >/dev/null; then
        echo
        echo "[WARN] Mixxx is running - Mixxx settings skipped. Close Mixxx, then run:"
        echo "       bash $mixxx_script install"
    else
        run_step "Mixxx settings (mapping, presets, skin, sound)" bash "$mixxx_script" install
    fi
}

uninstall_stack() {
    run_step "Remove mixxx-pi-gen integration" bash "$mixxx_pi_gen_script" uninstall
    run_step "Remove DDJ bridge layer" bash "$bridge_script" uninstall
    run_step "Remove DDJ host-stack layer" bash "$host_stack_script" uninstall
    run_step "Remove DDJ audio-driver override" bash "$driver_script" uninstall
}

status() {
    run_step "Linux setup status" bash "$setup_script" check
    run_step "DDJ audio-driver status" bash "$driver_script" status
    run_step "DDJ host-stack status" bash "$host_stack_script" status
    run_step "DDJ bridge status" bash "$bridge_script" status
    run_step "mixxx-pi-gen integration" bash "$mixxx_pi_gen_script" status
    run_step "Mixxx settings" bash "$mixxx_script" status
}

usage() {
    cat <<'EOF'
Usage: ./scripts/install-ddj1000-linux-stack.sh <command>

Commands:
  install [--no-bridge]
              Install the DDJ-1000 Linux stack: udev rules, audio-driver override, host-stack layer,
              bridge (autostart on plug-in, jog displays; --no-bridge = unlock only), kernel-update
              hooks, mixxx-pi-gen integration and the Mixxx settings (Mixxx must be closed).
  uninstall   Remove the host-stack layer and audio-driver override.
  status      Show the combined Linux stack status.
  help        Show this help.
EOF
}

main() {
    case "${1:-help}" in
        install)
            shift
            install_stack "$@"
            ;;
        uninstall)
            uninstall_stack
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