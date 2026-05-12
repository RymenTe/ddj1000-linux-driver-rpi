#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"

setup_script="$repo_root/scripts/setup-linux.sh"
driver_script="$repo_root/scripts/install-ddj1000-audio-driver.sh"
host_stack_script="$repo_root/scripts/install-ddj1000-host-stack.sh"

run_step() {
    echo
    echo "== $1 =="
    shift
    "$@"
}

install_stack() {
    run_step "Install DDJ udev rules" bash "$setup_script" install-udev
    run_step "Install DDJ audio-driver override" bash "$driver_script" install
    run_step "Install DDJ host-stack layer" bash "$host_stack_script" install
}

uninstall_stack() {
    run_step "Remove DDJ host-stack layer" bash "$host_stack_script" uninstall
    run_step "Remove DDJ audio-driver override" bash "$driver_script" uninstall
}

status() {
    run_step "Linux setup status" bash "$setup_script" check
    run_step "DDJ audio-driver status" bash "$driver_script" status
    run_step "DDJ host-stack status" bash "$host_stack_script" status
}

usage() {
    cat <<'EOF'
Usage: ./scripts/install-ddj1000-linux-stack.sh <command>

Commands:
  install     Install the DDJ-1000 Linux stack: udev rules, audio-driver override, and host-stack layer.
  uninstall   Remove the host-stack layer and audio-driver override.
  status      Show the combined Linux stack status.
  help        Show this help.
EOF
}

main() {
    case "${1:-help}" in
        install)
            install_stack
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