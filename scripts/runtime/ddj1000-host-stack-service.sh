#!/usr/bin/env bash

set -euo pipefail

runtime_dir="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
state_dir="$runtime_dir/ddj1000-host-stack"
state_file="$state_dir/pactl-modules"
alsa_devices=(
    "ddj1000_master:ddj1000_master:DDJ1000-Master-1-2"
)

alsa_direct_only_devices=(
    "ddj1000_cue:DDJ Cue direct ALSA path (3/4)"
    "ddj1000_aux:DDJ Aux direct ALSA path (5/6)"
)

have_command() {
    command -v "$1" >/dev/null 2>&1
}

wait_for_pulse() {
    local attempts=40
    local attempt
    for ((attempt = 1; attempt <= attempts; attempt++)); do
        if pactl info >/dev/null 2>&1; then
            return 0
        fi
        sleep 0.25
    done
    return 1
}

device_exists() {
    local pcm_name="$1"
    aplay -L 2>/dev/null | grep -Fxq "$pcm_name"
}

build_sink_properties() {
    local description="$1"
    printf 'device.description=%s node.description=%s node.nick=%s media.name=%s' \
        "$description" "$description" "$description" "$description"
}

load_sinks() {
    local pcm_name
    local sink_name
    local description
    local module_id
    local sink_properties
    local entry
    local attempt

    if ! have_command pactl; then
        echo "[INFO] pactl not found. ALSA PCMs are installed, but no desktop sinks were created." >&2
        return 0
    fi

    if ! wait_for_pulse; then
        echo "[WARN] Pulse/PipeWire server did not become ready. Skipping desktop sink creation." >&2
        return 0
    fi

    mkdir -p "$state_dir"
    : > "$state_file"

    for entry in "${alsa_devices[@]}"; do
        IFS=":" read -r pcm_name sink_name description <<< "$entry"
        module_id=""
        sink_properties="$(build_sink_properties "$description")"
        for ((attempt = 1; attempt <= 10; attempt++)); do
            if device_exists "$pcm_name"; then
                module_id="$(pactl load-module module-alsa-sink device="$pcm_name" sink_name="$sink_name" sink_properties="$sink_properties" 2>/dev/null || true)"
                if [[ -n "$module_id" ]]; then
                    printf '%s %s\n' "$module_id" "$sink_name" >> "$state_file"
                    break
                fi
            fi
            sleep 0.5
        done

        if [[ -z "$module_id" ]]; then
            echo "[WARN] Could not create sink $sink_name from $pcm_name." >&2
        fi
    done

    for entry in "${alsa_direct_only_devices[@]}"; do
        IFS=":" read -r pcm_name description <<< "$entry"
        if device_exists "$pcm_name"; then
            echo "[INFO] $description remains available as ALSA PCM $pcm_name, but is not exported as a parallel desktop sink because the DDJ hardware path is exclusive." >&2
        fi
    done
}

unload_sinks() {
    local module_id
    local _sink_name

    if ! have_command pactl; then
        return 0
    fi

    if [[ ! -f "$state_file" ]]; then
        return 0
    fi

    while read -r module_id _sink_name; do
        [[ -n "$module_id" ]] || continue
        pactl unload-module "$module_id" >/dev/null 2>&1 || true
    done < "$state_file"

    rm -f "$state_file"
}

usage() {
    cat <<'EOF'
Usage: ddj1000-host-stack-service.sh <start|stop|restart>

Creates named desktop sinks for the ALSA PCMs exposed by the DDJ-1000
host-stack. The DDJ currently supports only one concurrently open desktop sink
on the shared hardware path, so this service exports only the Master sink.
Cue and Aux remain available as direct ALSA PCMs. If pactl is unavailable, the
script exits successfully after leaving the ALSA PCMs in place.
EOF
}

main() {
    case "${1:-}" in
        start)
            unload_sinks
            load_sinks
            ;;
        stop)
            unload_sinks
            ;;
        restart)
            unload_sinks
            load_sinks
            ;;
        -h|--help|help|"")
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