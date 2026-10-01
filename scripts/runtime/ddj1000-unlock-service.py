#!/usr/bin/env python3

import argparse
import collections
import contextlib
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import sys
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
DDJ_USB_ID = "2b73:0020"
DDJ_ALSA_PCM = "hw:DDJ1000,0"


def format_bytes(payload):
    return " ".join(f"{byte:02x}" for byte in payload)


def parse_hex_bytes_from_line(value):
    matches = HEX_BYTE_RE.findall(value)
    if not matches:
        return b""
    return bytes(int(part, 16) for part in matches)


def detect_ddj_card_index():
    """Find the ALSA card bound to the DDJ-1000 via /proc/asound/card*/usbid.

    Works even when the device reports empty USB strings and shows up as
    "USB Device 0x00:0x00", and survives card numbers shifting on reboot.
    """
    for usbid_file in sorted(Path("/proc/asound").glob("card*/usbid")):
        try:
            if usbid_file.read_text(encoding="ascii").strip().lower() == DDJ_USB_ID:
                return int(usbid_file.parent.name.removeprefix("card"))
        except (OSError, ValueError):
            continue
    return None


def detect_default_midi_port():
    card_index = detect_ddj_card_index()
    if card_index is not None and Path(f"/dev/snd/midiC{card_index}D0").exists():
        return f"hw:{card_index},0,0"

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
        if "DDJ-1000" in name or "DDJ1000" in name:
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


class MidiPortGone(Exception):
    """The rawmidi device vanished (unplug, driver rebind)."""


class MidiStreamParser:
    """Split a raw MIDI byte stream into complete messages.

    `amidi -d` prints whatever one read() returned, so a long SysEx such as
    the 13 2A challenge can arrive split over several lines and was never
    recognised. This parser reassembles messages across reads, honours
    running status and lets realtime bytes pass through SysEx.
    """

    _DATA_LENGTHS = {0x80: 2, 0x90: 2, 0xA0: 2, 0xB0: 2, 0xC0: 1, 0xD0: 1, 0xE0: 2}
    _SYSTEM_COMMON_LENGTHS = {0xF1: 1, 0xF2: 2, 0xF3: 1, 0xF6: 0}
    _MAX_SYSEX = 4096

    def __init__(self):
        self._sysex = None
        self._running_status = 0
        self._message = bytearray()
        self._needed = 0

    def feed(self, data):
        messages = []
        for byte in data:
            if byte >= 0xF8:
                messages.append(bytes((byte,)))
                continue
            if self._sysex is not None:
                if byte == 0xF7:
                    self._sysex.append(byte)
                    messages.append(bytes(self._sysex))
                    self._sysex = None
                    continue
                if not byte & 0x80:
                    if len(self._sysex) < self._MAX_SYSEX:
                        self._sysex.append(byte)
                    continue
                # A status byte inside SysEx: drop the unterminated SysEx
                # and handle the new status byte below.
                self._sysex = None
            if byte == 0xF0:
                self._sysex = bytearray((byte,))
                self._running_status = 0
                self._message.clear()
                continue
            if byte & 0x80:
                if byte in self._SYSTEM_COMMON_LENGTHS:
                    self._running_status = 0
                    needed = self._SYSTEM_COMMON_LENGTHS[byte]
                    if needed == 0:
                        messages.append(bytes((byte,)))
                        self._message.clear()
                        continue
                    self._message = bytearray((byte,))
                    self._needed = needed
                    continue
                if byte == 0xF7:
                    continue
                self._running_status = byte
                self._message = bytearray((byte,))
                self._needed = self._DATA_LENGTHS[byte & 0xF0]
                continue
            if not self._message:
                if not self._running_status:
                    continue
                self._message = bytearray((self._running_status,))
                self._needed = self._DATA_LENGTHS[self._running_status & 0xF0]
            self._message.append(byte)
            if len(self._message) - 1 >= self._needed:
                messages.append(bytes(self._message))
                self._message.clear()
        return messages


def resolve_rawmidi_device(midi_port):
    """Map hw:CARD,DEV[,SUB] (CARD numeric or an ALSA id) to /dev/snd/midiCxDy."""
    if midi_port.startswith("/"):
        return midi_port
    match = re.match(r"^hw:([^,]+)(?:,(\d+))?(?:,\d+)?$", midi_port)
    if not match:
        raise ValueError(f"unsupported MIDI port format: {midi_port}")
    card, device = match.group(1), int(match.group(2) or 0)
    if not card.isdigit():
        link = Path("/proc/asound") / card
        if not link.exists():
            raise MidiPortGone(f"ALSA card {card} not present")
        card = os.path.basename(os.readlink(link)).removeprefix("card")
    return f"/dev/snd/midiC{int(card)}D{device}"


class RawMidiPort:
    """One O_RDWR file descriptor for both directions of the DDJ rawmidi port.

    Replaces the earlier `amidi -d` reader process plus one `amidi -S` process
    per outgoing message, which raced for the same rawmidi device.
    """

    def __init__(self, midi_port, write_timeout_seconds=2.0):
        self.name = midi_port
        self.path = resolve_rawmidi_device(midi_port)
        self._write_timeout = write_timeout_seconds
        self._parser = MidiStreamParser()
        self._pending = collections.deque()
        try:
            self._fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
        except FileNotFoundError as exc:
            raise MidiPortGone(str(exc)) from exc

    def send(self, payload):
        view = memoryview(payload)
        deadline = time.monotonic() + self._write_timeout
        while view:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"MIDI write timed out on {self.path}")
            _, writable, _ = select.select([], [self._fd], [], remaining)
            if not writable:
                continue
            try:
                written = os.write(self._fd, view)
            except BlockingIOError:
                continue
            except OSError as exc:
                raise MidiPortGone(f"{self.path}: {exc}") from exc
            view = view[written:]

    def next_message(self, timeout_seconds):
        deadline = time.monotonic() + timeout_seconds
        while not self._pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return b""
            readable, _, _ = select.select([self._fd], [], [], remaining)
            if not readable:
                return b""
            try:
                data = os.read(self._fd, 4096)
            except BlockingIOError:
                continue
            except OSError as exc:
                raise MidiPortGone(f"{self.path}: {exc}") from exc
            if not data:
                raise MidiPortGone(f"{self.path}: end of stream")
            self._pending.extend(self._parser.feed(data))
        return self._pending.popleft()

    def close(self):
        if self._fd is not None:
            with contextlib.suppress(OSError):
                os.close(self._fd)
            self._fd = None


def send_amidi_message(midi_port, payload, timeout_seconds=None):
    # Kept under the old name so the call sites stay readable; midi_port is
    # now a RawMidiPort instance instead of an hw: string.
    midi_port.send(payload)


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


def ddj_alsa_playback_available():
    card_index = detect_ddj_card_index()
    return card_index is not None and Path(f"/proc/asound/card{card_index}/pcm0p").exists()


def start_startup_silence_stream(backend="auto", duration_seconds=1.2):
    if backend == "auto":
        # With the patched snd-usb-audio bound, interface 0 belongs to the
        # kernel and libusb cannot claim it (urb -75 / disconnects on the Pi).
        backend = "alsa" if ddj_alsa_playback_available() else "libusb"

    if backend == "alsa":
        card_index = detect_ddj_card_index()
        device = f"hw:{card_index},0" if card_index is not None else DDJ_ALSA_PCM
        frames = max(1, int(44100 * duration_seconds))
        try:
            process = subprocess.Popen(
                ["aplay", "-q", "-D", device, "-c", "6", "-f", "S24_3LE", "-r", "44100",
                 "-t", "raw", "-s", str(frames), "/dev/zero"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except FileNotFoundError:
            log("[WARN] aplay not found; install alsa-utils")
            return None
        log(f"[INFO] Started DDJ startup silence stream via ALSA on {device}")
        return process

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
            str(duration_seconds),
            "--print-payload-bytes",
            "0",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    log("[INFO] Started DDJ startup silence stream via libusb on interface 0")
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


def wait_for_audio_rebind(timeout_seconds=20.0):
    """The rebind helper removes the request file only after the driver is back."""
    deadline = time.monotonic() + timeout_seconds
    while AUDIO_REBIND_REQUEST_FILE.exists():
        if time.monotonic() >= deadline:
            log("[WARN] Audio rebind helper did not finish in time; is ddj1000-audio-rebind.path enabled?")
            return False
        time.sleep(0.2)
    log("[INFO] DDJ audio rebind finished")
    return True


def stop_host_stack_service(scope="user"):
    if scope == "none":
        return
    subprocess.run(
        ["systemctl", "--user", "stop", HOST_STACK_SERVICE_NAME],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    log("[INFO] Stopped DDJ host-stack desktop sink service")


def restart_host_stack_service(scope="user"):
    if scope == "none":
        return
    subprocess.run(
        ["systemctl", "--user", "restart", HOST_STACK_SERVICE_NAME],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    log("[INFO] Restarted DDJ host-stack desktop sink service")


def write_unlock_state(state_file, unlocked):
    if not state_file:
        return
    path = Path(state_file)
    with contextlib.suppress(OSError):
        if unlocked:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("unlocked\n", encoding="utf-8")
        else:
            path.unlink(missing_ok=True)


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
            silence_stream_process = start_startup_silence_stream(
                args.silence_backend, args.silence_duration_s
            )
            time.sleep(args.silence_duration_s + 0.2)
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
    port = RawMidiPort(midi_port, args.send_timeout_s)
    silence_stream_process = None
    last_rx = time.monotonic()
    try:
        log(f"[INFO] DDJ unlock session attached to {midi_port} ({port.path})")
        while True:
            now = time.monotonic()
            if now - last_rx > max(5.0, args.monitor_timeout_s):
                log("[WARN] No MIDI input from DDJ within monitor timeout; restarting session")
                break
            keepalive_deadline = send_keepalive_if_due(
                port,
                now,
                keepalive_deadline,
                args.keepalive_interval_s,
                args.send_timeout_s,
            )

            payload = port.next_message(timeout_seconds=0.1)
            if not payload:
                continue
            last_rx = time.monotonic()
            if args.verbose and payload[0] == 0xF0:
                log(f"[DEBUG] rx {format_bytes(payload)}")

            if payload == READY_MESSAGE:
                ready_seen = True
                if now - handshake_requested_at >= args.handshake_cooldown_s:
                    send_unlock_request(port, args.send_timeout_s)
                    handshake_requested_at = time.monotonic()
                    acknowledged = False
                continue

            if handle_device_challenge(port, payload, args.send_timeout_s):
                continue

            if payload.startswith(DDJ_ACK_PREFIX):
                acknowledged = True
                silence_stream_process, ack_rebind_requested = handle_unlock_ack(
                    args,
                    port,
                    silence_stream_process,
                )
                rebind_requested = rebind_requested or ack_rebind_requested
                return acknowledged, rebind_requested

        if ready_seen or acknowledged:
            log("[WARN] DDJ unlock monitor ended; waiting for reconnect")
        return acknowledged, rebind_requested
    finally:
        stop_process_group(silence_stream_process)
        port.close()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Keep the DDJ-1000 session unlocked on Linux by replaying the validated MIDI ready/challenge/response path."
    )
    parser.add_argument("--midi-port", default="",
                        help="hw:CARD,DEV[,SUB] or /dev/snd/midiCxDy; auto-detected from the USB ID when empty")
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
    parser.add_argument("--silence-backend", choices=("auto", "alsa", "libusb"), default="auto",
                        help="post-ACK silence burst: ALSA aplay (patched driver bound) or raw libusb")
    parser.add_argument("--silence-duration-s", type=float, default=1.2)
    parser.add_argument("--host-stack-scope", choices=("user", "none"), default="user",
                        help="'none' skips the desktop sink user service (headless / system service)")
    parser.add_argument("--state-file", default="",
                        help="written once the unlock + rebind cycle is done, removed on disconnect")
    parser.add_argument("--verbose", action="store_true", help="log every received SysEx message")
    return parser.parse_args()


def port_present(midi_port):
    try:
        return Path(resolve_rawmidi_device(midi_port)).exists()
    except (MidiPortGone, ValueError, OSError):
        return False


def main():
    args = parse_args()
    host_stack_restart_pending = False
    wait_for_real_reconnect = False
    wait_started_at = time.monotonic()
    write_unlock_state(args.state_file, False)

    while True:
        midi_port = args.midi_port or detect_default_midi_port()
        if not midi_port or not port_present(midi_port):
            if (args.wait_for_port_timeout_s > 0.0 and
                    time.monotonic() - wait_started_at >= args.wait_for_port_timeout_s):
                log("[WARN] Timed out while waiting for DDJ-1000 MIDI port")
                return 2
            if wait_for_real_reconnect:
                log("[INFO] DDJ MIDI port disappeared; next appearance will allow a new unlock cycle")
                wait_for_real_reconnect = False
                write_unlock_state(args.state_file, False)
            log("[INFO] Waiting for DDJ-1000 MIDI port...")
            time.sleep(args.retry_interval_s)
            continue

        wait_started_at = time.monotonic()

        if host_stack_restart_pending:
            restart_host_stack_service(args.host_stack_scope)
            host_stack_restart_pending = False
            wait_for_real_reconnect = True
            write_unlock_state(args.state_file, True)
            log("[INFO] DDJ unlock cycle complete")

        if wait_for_real_reconnect:
            time.sleep(args.retry_interval_s)
            continue

        try:
            acknowledged, rebind_requested = run_session(args, midi_port)
            if rebind_requested:
                stop_host_stack_service(args.host_stack_scope)
                request_audio_rebind()
                host_stack_restart_pending = True
                wait_for_audio_rebind()
            elif acknowledged:
                wait_for_real_reconnect = True
                write_unlock_state(args.state_file, True)
            if args.once:
                return 0 if acknowledged else 1
        except MidiPortGone as exc:
            log(f"[INFO] DDJ MIDI port went away ({exc}); waiting for it to return")
        except (TimeoutError, OSError) as exc:
            log(f"[WARN] MIDI I/O failed on {midi_port}: {exc}; retrying")
        except KeyboardInterrupt:
            return 0

        time.sleep(args.retry_interval_s)


if __name__ == "__main__":
    raise SystemExit(main())
