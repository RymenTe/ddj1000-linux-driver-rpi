#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd -- "$script_dir/../.." && pwd)"

run_audio_stream=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --with-audio-stream)
            run_audio_stream=1
            shift
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 2
            ;;
    esac
done

cd "$repo_dir"

run_optional_probe() {
    local attempt
    for attempt in 1 2 3; do
        if python3 scripts/runtime/ddj1000-usb-probe.py "$@"; then
            return 0
        fi
        if [[ "$attempt" -lt 3 ]]; then
            sleep 0.2
        fi
    done
    return 1
}

run_optional_probe \
    --interface 3 \
    --skip-alt-setting \
    --no-monitor \
    --control-request-type 0x81 \
    --control-request 0x06 \
    --control-value 0x2200 \
    --control-index 0x0003 \
    --control-length 0x74 \
    --print-payload-bytes 0 \
    --duration 0.2 || true

run_optional_probe \
    --interface 3 \
    --skip-alt-setting \
    --no-monitor \
    --control-request-type 0xc0 \
    --control-request 0x00 \
    --control-value 0x0000 \
    --control-index 0x8003 \
    --control-length 0x0002 \
    --print-payload-bytes 0 \
    --duration 0.2 || true

if [[ "$run_audio_stream" -eq 1 ]]; then
    python3 scripts/runtime/ddj1000-audio-stream.py \
        --send-delay-ms 1 \
        --quiet-out \
        --duration 32 \
        --print-payload-bytes 0
fi
