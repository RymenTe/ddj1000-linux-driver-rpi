#!/usr/bin/env python3

import argparse
import contextlib
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import sys
import threading
import time


AMIDI_LIST_RE = re.compile(r"^(?:IO|I|O)\s+(hw:[^\s]+)\s+(.+)$")
HEX_BYTE_RE = re.compile(r"\b[0-9A-Fa-f]{2}\b")

DDJ_SECRET_INPUT = 0x680131FB
FNV_OFFSET_BASIS = 0x811C9DC5
FNV_PRIME = 0x01000193

KEEPALIVE_MESSAGE = bytes.fromhex("f0 00 40 05 00 00 02 00 00 50 01 f7")
READY_MESSAGE = bytes.fromhex("f0 00 40 05 00 00 02 00 00 11 02 f7")
HANDSHAKE_REQUEST = bytes.fromhex(
    "f0 00 40 05 00 00 02 00 00 12 2a 01 0b 50 69 6f 6e 65 65 72 44 4a "
    "02 0b 72 65 6b 6f 72 64 62 6f 78 03 12 0c 0d 08 04 05 09 03 07 04 "
    "00 00 04 03 0e 00 0a f7"
)
PRELUDE_MESSAGES = (
    bytes.fromhex("f0 00 40 05 00 00 02 00 00 00 0b 2b 68 00 00 00 00 f7"),
    bytes.fromhex(
        "f0 00 40 05 00 00 02 00 00 00 0a 00 28 00 26 00 0a 39 4a 74 28 53 20 20 "
        "14 15 22 05 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
        "00 00 00 00 00 00 00 00 00 f7"
    ),
    bytes.fromhex("f0 00 40 05 00 00 02 00 00 00 0b 2b 68 00 00 00 00 f7"),
    bytes.fromhex("f0 00 40 05 00 00 02 00 00 00 0c 00 00 02 0e 0e 00 00 00 f7"),
)
DDJ_HANDSHAKE_DEVICE_CHALLENGE_PREFIX = bytes.fromhex(
    "f0 00 40 05 00 00 02 00 00 13 2a 01 0b 50 69 6f 6e 65 65 72 44 4a 02 09 44 44 4a 31 30 30 30 04 0a"
)
DDJ_HANDSHAKE_RESPONSE_PREFIX = bytes.fromhex(
    "f0 00 40 05 00 00 02 00 00 14 38 01 0b 50 69 6f 6e 65 65 72 44 4a 02 0b 72 65 6b 6f 72 64 62 6f 78 04 0a"
)
DDJ_VENDOR_DEVICE_ID_SPREAD = bytes.fromhex("08 07 0a 00 08 0e 0e 0a 0c 00 09 00 03 04 07 06 00 0b 09 00")
DDJ_ACK_PREFIX = bytes.fromhex("f0 00 40 05 00 00 02 00 00 15 02")
DDJ_JOGSCREEN_ENABLE_MESSAGES = (
    bytes.fromhex(
        "f0 00 40 05 00 00 02 00 00 00 0a 00 28 00 26 00 24 15 32 55 48 14 21 00 "
        "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
        "00 00 00 00 00 00 f7"
    ),
    bytes.fromhex("f0 00 40 05 00 00 02 00 00 00 0b 35 60 14 01 00 00 f7"),
    bytes.fromhex("f0 00 40 05 00 00 02 00 00 00 0c 00 00 02 0e 0e 00 00 00 f7"),
)
DDJ_JOGSCREEN_ENABLE_6_MESSAGES = (
    bytes.fromhex("f0 00 40 05 00 00 02 00 00 00 0b 31 00 00 00 00 00 f7"),
    bytes.fromhex(
        "f0 00 40 05 00 00 02 00 00 00 0a 00 28 00 26 00 28 49 0a 64 69 14 00 00 "
        "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
        "00 00 00 00 00 00 f7"
    ),
    bytes.fromhex("f0 00 40 05 00 00 02 00 00 00 0b 31 00 00 00 00 00 f7"),
    bytes.fromhex("f0 00 40 05 00 00 02 00 00 00 0c 00 00 02 0e 0e 00 00 00 f7"),
)
DDJ_BROWSER_STARTUP_MESSAGES = (
    bytes.fromhex("9f 40 7f"),
    bytes.fromhex("9f 41 00"),
    bytes.fromhex("9f 42 7f"),
    bytes.fromhex("bf 46 30"),
    bytes.fromhex("bf 41 00"),
    bytes.fromhex("bf 42 00"),
    bytes.fromhex("bf 43 00"),
    bytes.fromhex("bf 44 30"),
    bytes.fromhex("bf 47 20"),
    bytes.fromhex("bf 48 40"),
    bytes.fromhex("bf 49 10"),
    bytes.fromhex("bf 4a 20"),
)
DDJ_DECK_STARTUP_NOTES = (0x0B, 0x47, 0x0C, 0x50)
SUPPORT_ROOT = Path("/usr/local/lib/ddj1000-linux-driver")
PROBE_USB_SCRIPT = SUPPORT_ROOT / "scripts" / "ddj1000-usb-probe.py"
DDJ_AUDIO_STREAM_SCRIPT = SUPPORT_ROOT / "scripts" / "ddj1000-audio-stream.py"
AUDIO_REBIND_REQUEST_FILE = Path("/tmp/ddj1000-audio-rebind-request")
HOST_STACK_SERVICE_NAME = "ddj1000-host-stack.service"


def format_bytes(payload):
    return " ".join(f"{byte:02x}" for byte in payload)


def parse_hex_bytes_from_line(value):
    matches = HEX_BYTE_RE.findall(value)
    if not matches:
        return b""
    return bytes(int(part, 16) for part in matches)


def detect_default_midi_port():
    try:
        completed = subprocess.run(["amidi", "-l"], check=True, capture_output=True, text=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ""

    fallback_port = ""
    for line in completed.stdout.splitlines():
        match = AMIDI_LIST_RE.match(line.strip())
        if not match:
            continue
        port, name = match.groups()
        if fallback_port == "":
            fallback_port = port
        if "DDJ-1000" in name:
            return port
    return fallback_port


def read_big_endian_uint32(payload):
    return int.from_bytes(payload[:4], byteorder="big")


def append_big_endian_uint32(payload, value):
    payload.extend(value.to_bytes(4, byteorder="big"))


def fnv1a32(payload):
    hash_value = FNV_OFFSET_BASIS
    for value in payload:
        hash_value = ((hash_value ^ value) * FNV_PRIME) & 0xFFFFFFFF
    return hash_value


def ddj_handshake_hash(seed, seed_e):
    secret_input = bytearray(seed)
    secret = read_big_endian_uint32(seed_e) ^ DDJ_SECRET_INPUT
    append_big_endian_uint32(secret_input, secret)
    return fnv1a32(secret_input)


def compact_spread_buffer(message, offset, spread_size):
    compact = bytearray()
    for index in range(0, spread_size, 2):
        high = message[offset + index]
        low = message[offset + index + 1]
        if high > 0x0F or low > 0x0F:
            return b""
        compact.append((high << 4) | low)
    return bytes(compact)


def append_spread_byte(message, value):
    message.append((value >> 4) & 0x0F)
    message.append(value & 0x0F)


def append_spread_uint32(message, value):
    append_spread_byte(message, (value >> 24) & 0xFF)
    append_spread_byte(message, (value >> 16) & 0xFF)
    append_spread_byte(message, (value >> 8) & 0xFF)
    append_spread_byte(message, value & 0xFF)


def is_ddj_device_challenge(message):
    if not message.startswith(DDJ_HANDSHAKE_DEVICE_CHALLENGE_PREFIX):
        return False
    tail_offset = len(DDJ_HANDSHAKE_DEVICE_CHALLENGE_PREFIX)
    return (
        len(message) >= tail_offset + 18 + 1
        and message[-1] == 0xF7
        and message[tail_offset + 8] == 0x03
        and message[tail_offset + 9] == 0x0A
    )


def extract_ddj_seed_e(message):
    tail_offset = len(DDJ_HANDSHAKE_DEVICE_CHALLENGE_PREFIX)
    seed_e = compact_spread_buffer(message, tail_offset + 10, 8)
    return seed_e if len(seed_e) == 4 else b""


def build_ddj_handshake_response(seed_e):
    hash_e = ddj_handshake_hash(seed_e, seed_e)
    response = bytearray(DDJ_HANDSHAKE_RESPONSE_PREFIX)
    append_spread_uint32(response, hash_e)
    response.extend(bytes.fromhex("05 16"))
    response.extend(DDJ_VENDOR_DEVICE_ID_SPREAD)
    response.append(0xF7)
    return bytes(response)


class MidiInputMonitor:
    def __init__(self, midi_port, timeout_seconds):
        self._queue = queue.Queue()
        self._process = subprocess.Popen(
            ["amidi", "-p", midi_port, "-d", "-a", "-t", str(timeout_seconds)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self):
        assert self._process.stdout is not None
        for line in self._process.stdout:
            payload = parse_hex_bytes_from_line(line)
            if payload:
                self._queue.put(payload)

    def next_message(self, timeout_seconds):
        try:
            return self._queue.get(timeout=timeout_seconds)
        except queue.Empty:
            return b""

    def is_alive(self):
        return self._process.poll() is None

    def close(self):
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=1.0)
        self._thread.join(timeout=1.0)


def send_amidi_message(midi_port, payload, timeout_seconds):
    subprocess.run(
        ["amidi", "-p", midi_port, "-S", format_bytes(payload)],
        check=True,
        timeout=timeout_seconds,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def send_startup_state_messages(midi_port, timeout_seconds):
    for payload in DDJ_JOGSCREEN_ENABLE_MESSAGES:
        send_amidi_message(midi_port, payload, timeout_seconds)

    for payload in DDJ_BROWSER_STARTUP_MESSAGES:
        send_amidi_message(midi_port, payload, timeout_seconds)

    for deck_channel in range(4):
        status = 0x90 | deck_channel
        for note in DDJ_DECK_STARTUP_NOTES:
            send_amidi_message(midi_port, bytes((status, note, 0x00)), timeout_seconds)

    for payload in DDJ_JOGSCREEN_ENABLE_6_MESSAGES:
        send_amidi_message(midi_port, payload, timeout_seconds)

    log("[INFO] Sent DDJ post-ACK startup-state messages for basic UI")


def run_startup_prep_control_reads():
    if not PROBE_USB_SCRIPT.is_file():
        log(f"[WARN] DDJ USB probe helper not installed at {PROBE_USB_SCRIPT}")
        return

    control_commands = (
        [
            sys.executable,
            str(PROBE_USB_SCRIPT),
            "--interface",
            "3",
            "--skip-alt-setting",
            "--no-monitor",
            "--control-request-type",
            "0x81",
            "--control-request",
            "0x06",
            "--control-value",
            "0x2200",
            "--control-index",
            "0x0003",
            "--control-length",
            "0x74",
            "--print-payload-bytes",
            "0",
            "--duration",
            "0.2",
        ],
        [
            sys.executable,
            str(PROBE_USB_SCRIPT),
            "--interface",
            "3",
            "--skip-alt-setting",
            "--no-monitor",
            "--control-request-type",
            "0xc0",
            "--control-request",
            "0x00",
            "--control-value",
            "0x0000",
            "--control-index",
            "0x8003",
            "--control-length",
            "0x0002",
            "--print-payload-bytes",
            "0",
            "--duration",
            "0.2",
        ],
    )

    for command in control_commands:
        try:
            subprocess.run(command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5.0)
        except subprocess.TimeoutExpired:
            log("[WARN] DDJ startup prep control read timed out; continuing")

    log("[INFO] Ran DDJ plug-control prep reads")


def start_startup_silence_stream():
    if not DDJ_AUDIO_STREAM_SCRIPT.is_file():
        log("[WARN] DDJ audio helper bundle missing; cannot start startup silence stream")
        return None

    process = subprocess.Popen(
        [
            sys.executable,
            str(DDJ_AUDIO_STREAM_SCRIPT),
            "--send-delay-ms",
            "1",
            "--quiet-out",
            "--duration",
            "1.2",
            "--print-payload-bytes",
            "0",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    log("[INFO] Started DDJ startup silence stream on interface 0")
    return process


def stop_process_group(process):
    if process is None:
        return
    with contextlib.suppress(ProcessLookupError):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=1.0)


def request_audio_rebind():
    AUDIO_REBIND_REQUEST_FILE.write_text("rebind\n", encoding="utf-8")
    log("[INFO] Requested system DDJ audio rebind")


def stop_host_stack_service():
    subprocess.run(
        ["systemctl", "--user", "stop", HOST_STACK_SERVICE_NAME],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    log("[INFO] Stopped DDJ host-stack desktop sink service")


def restart_host_stack_service():
    subprocess.run(
        ["systemctl", "--user", "restart", HOST_STACK_SERVICE_NAME],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    log("[INFO] Restarted DDJ host-stack desktop sink service")


def log(message):
    print(message, flush=True)


def send_unlock_request(midi_port, timeout_seconds):
    for message in PRELUDE_MESSAGES:
        send_amidi_message(midi_port, message, timeout_seconds)
    send_amidi_message(midi_port, HANDSHAKE_REQUEST, timeout_seconds)
    log("[INFO] DDJ reported ready; sent unlock request")


def send_keepalive_if_due(midi_port, now, keepalive_deadline, interval_seconds, timeout_seconds):
    if now < keepalive_deadline:
        return keepalive_deadline

    send_amidi_message(midi_port, KEEPALIVE_MESSAGE, timeout_seconds)
    return now + interval_seconds


def handle_device_challenge(midi_port, payload, timeout_seconds):
    if not is_ddj_device_challenge(payload):
        return False

    seed_e = extract_ddj_seed_e(payload)
    if not seed_e:
        return True

    response = build_ddj_handshake_response(seed_e)
    send_amidi_message(midi_port, response, timeout_seconds)
    log(f"[INFO] DDJ challenge received; sent dynamic 14 38 for seedE={seed_e.hex()}")
    return True


def handle_unlock_ack(args, midi_port, silence_stream_process):
    rebind_requested = False

    if not args.skip_post_ack_audio:
        stream_is_running = silence_stream_process is not None and silence_stream_process.poll() is None
        if not stream_is_running:
            silence_stream_process = start_startup_silence_stream()
            time.sleep(1.4)
            rebind_requested = True

    if args.send_post_ack_startup_state:
        send_startup_state_messages(midi_port, args.send_timeout_s)

    log("[INFO] DDJ unlock acknowledged with 15 02")
    return silence_stream_process, rebind_requested


def run_session(args, midi_port):
    keepalive_deadline = 0.0
    handshake_requested_at = 0.0
    acknowledged = False
    ready_seen = False
    rebind_requested = False

    if not args.skip_startup_prep:
        run_startup_prep_control_reads()
    monitor = MidiInputMonitor(midi_port, max(5.0, args.monitor_timeout_s))
    silence_stream_process = None
    try:
        log(f"[INFO] DDJ unlock session attached to {midi_port}")
        while monitor.is_alive():
            now = time.monotonic()
            keepalive_deadline = send_keepalive_if_due(
                midi_port,
                now,
                keepalive_deadline,
                args.keepalive_interval_s,
                args.send_timeout_s,
            )

            payload = monitor.next_message(timeout_seconds=0.1)
            if not payload:
                continue

            if payload == READY_MESSAGE:
                ready_seen = True
                if now - handshake_requested_at >= args.handshake_cooldown_s:
                    send_unlock_request(midi_port, args.send_timeout_s)
                    handshake_requested_at = time.monotonic()
                    acknowledged = False
                continue

            if handle_device_challenge(midi_port, payload, args.send_timeout_s):
                continue

            if payload.startswith(DDJ_ACK_PREFIX):
                acknowledged = True
                silence_stream_process, ack_rebind_requested = handle_unlock_ack(
                    args,
                    midi_port,
                    silence_stream_process,
                )
                rebind_requested = rebind_requested or ack_rebind_requested
                return acknowledged, rebind_requested

        if ready_seen or acknowledged:
            log("[WARN] DDJ unlock monitor ended; waiting for reconnect")
        return acknowledged, rebind_requested
    finally:
        stop_process_group(silence_stream_process)
        monitor.close()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Keep the DDJ-1000 session unlocked on Linux by replaying the validated MIDI ready/challenge/response path."
    )
    parser.add_argument("--midi-port", default="")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--skip-startup-prep", action="store_true")
    parser.add_argument("--skip-post-ack-audio", action="store_true")
    parser.add_argument("--send-post-ack-startup-state", action="store_true")
    parser.add_argument("--keepalive-interval-s", type=float, default=1.0)
    parser.add_argument("--retry-interval-s", type=float, default=2.0)
    parser.add_argument("--wait-for-port-timeout-s", type=float, default=0.0)
    parser.add_argument("--monitor-timeout-s", type=float, default=60.0)
    parser.add_argument("--send-timeout-s", type=float, default=2.0)
    parser.add_argument("--handshake-cooldown-s", type=float, default=2.0)
    return parser.parse_args()


def main():
    args = parse_args()
    host_stack_restart_pending = False
    wait_for_real_reconnect = False
    wait_started_at = time.monotonic()

    while True:
        midi_port = args.midi_port or detect_default_midi_port()
        if not midi_port:
            if (args.wait_for_port_timeout_s > 0.0 and
                    time.monotonic() - wait_started_at >= args.wait_for_port_timeout_s):
                log("[WARN] Timed out while waiting for DDJ-1000 MIDI port")
                return 2
            if wait_for_real_reconnect:
                log("[INFO] DDJ MIDI port disappeared; next appearance will allow a new unlock cycle")
                wait_for_real_reconnect = False
            log("[INFO] Waiting for DDJ-1000 MIDI port...")
            time.sleep(args.retry_interval_s)
            continue

        wait_started_at = time.monotonic()

        if host_stack_restart_pending:
            restart_host_stack_service()
            host_stack_restart_pending = False
            wait_for_real_reconnect = True

        if wait_for_real_reconnect:
            time.sleep(args.retry_interval_s)
            continue

        try:
            acknowledged, rebind_requested = run_session(args, midi_port)
            if rebind_requested:
                stop_host_stack_service()
                request_audio_rebind()
                host_stack_restart_pending = True
            if args.once:
                return 0 if acknowledged else 1
        except FileNotFoundError:
            log("[ERROR] amidi not found; install alsa-utils")
            return 1
        except subprocess.CalledProcessError as exc:
            log(f"[WARN] MIDI send/monitor failed on {midi_port}: {exc}; retrying")
        except subprocess.TimeoutExpired:
            log(f"[WARN] MIDI operation timed out on {midi_port}; retrying")
        except KeyboardInterrupt:
            return 0

        time.sleep(args.retry_interval_s)


if __name__ == "__main__":
    raise SystemExit(main())