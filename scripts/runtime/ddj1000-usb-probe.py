#!/usr/bin/env python3

import argparse
import collections
import ctypes
import ctypes.util
import queue
import signal
import sys
import time


LIBUSB_TRANSFER_TYPE_ISOCHRONOUS = 1
LIBUSB_TRANSFER_TYPE_BULK = 2
LIBUSB_TRANSFER_TYPE_INTERRUPT = 3
LIBUSB_TRANSFER_COMPLETED = 0
LIBUSB_TRANSFER_CANCELLED = 3
LIBUSB_ERROR_NOT_FOUND = -5
LIBUSB_ERROR_TIMEOUT = -7


def usb_midi_event_packet(cin, payload, cable):
    if len(payload) > 3:
        raise ValueError("USB-MIDI event packets support at most 3 data bytes.")
    return bytes([(cable << 4) | cin, *payload, *([0] * (3 - len(payload)))])


def encode_usb_midi_message(payload, cable=0):
    if not payload:
        return b""

    status = payload[0]
    if status == 0xF0:
        if payload[-1] != 0xF7:
            raise ValueError("SysEx payload must terminate with F7.")
        encoded = bytearray()
        offset = 0
        while len(payload) - offset > 3:
            encoded.extend(usb_midi_event_packet(0x4, payload[offset:offset + 3], cable))
            offset += 3
        tail = payload[offset:]
        if len(tail) == 1:
            cin = 0x5
        elif len(tail) == 2:
            cin = 0x6
        else:
            cin = 0x7
        encoded.extend(usb_midi_event_packet(cin, tail, cable))
        return bytes(encoded)

    if 0x80 <= status <= 0xEF:
        cin = status >> 4
        expected_length = 2 if cin in (0xC, 0xD) else 3
        if len(payload) != expected_length:
            raise ValueError(
                f"Channel MIDI status 0x{status:02x} expects {expected_length} bytes, got {len(payload)}."
            )
        return usb_midi_event_packet(cin, payload, cable)

    if status in (0xF1, 0xF3):
        expected_length = 2
        cin = 0x2
    elif status == 0xF2:
        expected_length = 3
        cin = 0x3
    elif status == 0xF6:
        expected_length = 1
        cin = 0x5
    elif 0xF8 <= status <= 0xFF:
        expected_length = 1
        cin = 0xF
    else:
        raise ValueError(f"Unsupported raw MIDI status 0x{status:02x} for USB-MIDI encoding.")

    if len(payload) != expected_length:
        raise ValueError(f"MIDI status 0x{status:02x} expects {expected_length} bytes, got {len(payload)}.")
    return usb_midi_event_packet(cin, payload, cable)


class Timeval(ctypes.Structure):
    _fields_ = [
        ("tv_sec", ctypes.c_long),
        ("tv_usec", ctypes.c_long),
    ]


class LibusbIsoPacketDescriptor(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_uint),
        ("actual_length", ctypes.c_uint),
        ("status", ctypes.c_int),
    ]


class LibusbTransfer(ctypes.Structure):
    pass


TransferCallback = ctypes.CFUNCTYPE(None, ctypes.POINTER(LibusbTransfer))


LibusbTransfer._fields_ = [
    ("dev_handle", ctypes.c_void_p),
    ("flags", ctypes.c_ubyte),
    ("endpoint", ctypes.c_ubyte),
    ("type", ctypes.c_ubyte),
    ("timeout", ctypes.c_uint),
    ("status", ctypes.c_int),
    ("length", ctypes.c_int),
    ("actual_length", ctypes.c_int),
    ("callback", TransferCallback),
    ("user_data", ctypes.c_void_p),
    ("buffer", ctypes.POINTER(ctypes.c_ubyte)),
    ("num_iso_packets", ctypes.c_int),
]


class ProbeState:
    def __init__(self, args):
        self.args = args
        self.running = True
        self.transfer_error = 0
        self.last_payload = None
        self.changed_count = 0
        self.packet_count = 0
        self.in_payload_count = 0
        self.in_length_counts = collections.Counter()
        self.pending_out_budget = 0
        self.qualified_in_payload_count = 0
        self.qualified_in_length_counts = collections.Counter()
        self.completed_out_transfers = queue.SimpleQueue()


def parse_hex_bytes(value):
    normalized = value.replace(",", " ").replace(":", " ")
    parts = [part for part in normalized.split() if part]
    return bytes(int(part, 16) for part in parts)


def parse_length_filter(value):
    if value is None or not value.strip():
        return None
    lengths = set()
    for part in value.split(","):
        stripped = part.strip()
        if not stripped:
            continue
        length = int(stripped, 0)
        if length <= 0:
            raise ValueError("coupled IN lengths must be > 0")
        lengths.add(length)
    return lengths or None


def parse_count_pattern(value):
    if value is None or not value.strip():
        return None
    counts = []
    for part in value.split(","):
        stripped = part.strip()
        if not stripped:
            continue
        count = int(stripped, 0)
        if count < 0:
            raise ValueError("coupled window counts must be >= 0")
        counts.append(count)
    return counts or None


def load_send_file(path, usb_midi_encode=False, usb_midi_cable=0):
    payloads = []
    with open(path, "r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            payload = parse_hex_bytes(stripped)
            if usb_midi_encode:
                try:
                    payload = encode_usb_midi_message(payload, cable=usb_midi_cable)
                except ValueError as error:
                    raise ValueError(f"{path}:{line_number}: {error}") from error
            payloads.append(payload)
    return payloads


def load_libusb():
    library_name = ctypes.util.find_library("usb-1.0") or "libusb-1.0.so.0"
    return ctypes.CDLL(library_name)


def descriptor_array(transfer_ptr):
    transfer = transfer_ptr.contents
    address = ctypes.addressof(transfer) + ctypes.sizeof(LibusbTransfer)
    descriptor_type = LibusbIsoPacketDescriptor * transfer.num_iso_packets
    return descriptor_type.from_address(address)


def format_hex(payload):
    return " ".join(f"{byte:02x}" for byte in payload)


def format_hex_preview(payload, limit):
    if limit == 0:
        return ""
    shown = payload if limit < 0 else payload[:limit]
    suffix = "" if len(shown) == len(payload) else " ..."
    return f": {format_hex(shown)}{suffix}"


def transfer_type_value(name):
    if name == "iso":
        return LIBUSB_TRANSFER_TYPE_ISOCHRONOUS
    if name == "bulk":
        return LIBUSB_TRANSFER_TYPE_BULK
    if name == "interrupt":
        return LIBUSB_TRANSFER_TYPE_INTERRUPT
    raise ValueError(f"Unsupported transfer type: {name}")


def should_release_coupled_budget(args, payload):
    if not payload:
        return False
    if args.coupled_in_lengths is None:
        return True
    return len(payload) in args.coupled_in_lengths


def coupled_budget_for_payload(state, payload):
    if not should_release_coupled_budget(state.args, payload):
        return 0
    state.qualified_in_payload_count += 1
    state.qualified_in_length_counts[len(payload)] += 1
    if state.args.coupled_window_counts is not None:
        pattern_index = (state.qualified_in_payload_count - 1) % len(state.args.coupled_window_counts)
        return state.args.coupled_window_counts[pattern_index]
    return state.args.coupled_out_per_in


def record_in_payload(state, payload, show_zero_changes, print_payload_bytes):
    state.packet_count += 1
    state.in_payload_count += 1
    state.in_length_counts[len(payload)] += 1
    coupled_budget = coupled_budget_for_payload(state, payload)
    if coupled_budget > 0:
        state.pending_out_budget += coupled_budget
    if payload != state.last_payload:
        state.changed_count += 1
        if any(payload) or show_zero_changes:
            timestamp = time.strftime("%H:%M:%S")
            print(
                f"[{timestamp}] changed packet {state.changed_count} "
                f"len={len(payload)}{format_hex_preview(payload, print_payload_bytes)}"
            )
            sys.stdout.flush()
        state.last_payload = payload


def main():
    parser = argparse.ArgumentParser(
        description="Probe the DDJ-1000 vendor USB interface via libusb isochronous IN transfers."
    )
    parser.add_argument("--vendor-id", type=lambda value: int(value, 0), default=0x2B73)
    parser.add_argument("--product-id", type=lambda value: int(value, 0), default=0x0020)
    parser.add_argument("--interface", type=int, default=0)
    parser.add_argument("--alt-setting", type=int, default=1)
    parser.add_argument(
        "--skip-alt-setting",
        action="store_true",
        help="Claim the interface but do not call libusb_set_interface_alt_setting.",
    )
    parser.add_argument("--endpoint", type=lambda value: int(value, 0), default=0x82)
    parser.add_argument(
        "--in-transfer-type",
        choices=("iso", "bulk", "interrupt"),
        default="iso",
        help="Transfer type for the monitored IN endpoint. Default: iso.",
    )
    parser.add_argument("--packet-size", type=int, default=1024)
    parser.add_argument("--iso-packets", type=int, default=8)
    parser.add_argument("--timeout-ms", type=int, default=1000)
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--out-endpoint", type=lambda value: int(value, 0), default=0x01)
    parser.add_argument(
        "--out-transfer-type",
        choices=("iso", "bulk", "interrupt"),
        default="iso",
        help="Transfer type for sent OUT payloads. Use interrupt for HID endpoint 0x06.",
    )
    parser.add_argument(
        "--out-iso-group-size",
        type=int,
        default=1,
        help="How many queued OUT payloads to pack into one isochronous OUT transfer. Default: 1.",
    )
    parser.add_argument(
        "--out-iso-queue-depth",
        type=int,
        default=1,
        help="How many isochronous OUT transfers may remain in flight at once. Default: 1.",
    )
    parser.add_argument(
        "--no-monitor",
        action="store_true",
        help="Only send configured OUT/control payloads and skip IN endpoint monitoring.",
    )
    parser.add_argument(
        "--send-hex",
        action="append",
        default=[],
        help="Space-separated hex bytes to send once on the vendor OUT endpoint. May be passed multiple times.",
    )
    parser.add_argument(
        "--send-file",
        help="Path to a text file containing one vendor OUT payload per line.",
    )
    parser.add_argument(
        "--usb-midi-encode",
        action="store_true",
        help="Encode each --send-file line or --send-hex payload from raw MIDI bytes into USB-MIDI event packets.",
    )
    parser.add_argument(
        "--usb-midi-cable",
        type=int,
        default=0,
        help="USB-MIDI cable number to use with --usb-midi-encode. Default: 0.",
    )
    parser.add_argument(
        "--send-delay-ms",
        type=float,
        default=0.0,
        help="Delay between vendor OUT payloads in milliseconds.",
    )
    parser.add_argument(
        "--send-repeat",
        type=int,
        default=1,
        help="Repeat the configured OUT payload list this many times before monitoring.",
    )
    parser.add_argument(
        "--coupled-out-per-in",
        type=int,
        default=0,
        help="Experimental mode: after each nonempty monitored IN payload, submit this many OUT payloads from the send queue.",
    )
    parser.add_argument(
        "--coupled-prime-out",
        type=int,
        help="Initial OUT payloads to submit before switching to --coupled-out-per-in pacing. Defaults to the coupled count.",
    )
    parser.add_argument(
        "--coupled-in-lengths",
        help=(
            "Optional comma-separated list of monitored IN payload lengths that are allowed to release coupled OUT budget. "
            "Use this to ignore small keepalive-style IN payloads and only couple to capture-relevant audio window sizes."
        ),
    )
    parser.add_argument(
        "--coupled-window-counts",
        help=(
            "Optional comma-separated repeat pattern for how many OUT payloads to release per qualifying IN window, "
            "for example 2,2,2,3,1. When set, this overrides the constant coupled count on each qualifying window."
        ),
    )
    parser.add_argument(
        "--summarize-in-lengths",
        action="store_true",
        help="Print a short summary of monitored IN payload lengths at the end of the run.",
    )
    parser.add_argument(
        "--split-iso-in-descriptors",
        action="store_true",
        help="Process isochronous IN completions per descriptor instead of aggregating the completed transfer.",
    )
    parser.add_argument(
        "--control-request-type",
        type=lambda value: int(value, 0),
        help="Optional bmRequestType for a control transfer to send before monitoring.",
    )
    parser.add_argument(
        "--control-request",
        type=lambda value: int(value, 0),
        help="Optional bRequest for a control transfer to send before monitoring.",
    )
    parser.add_argument(
        "--control-value",
        type=lambda value: int(value, 0),
        help="Optional wValue for a control transfer to send before monitoring.",
    )
    parser.add_argument(
        "--control-index",
        type=lambda value: int(value, 0),
        help="Optional wIndex for a control transfer to send before monitoring.",
    )
    parser.add_argument(
        "--control-data-hex",
        help="Optional space-separated control transfer data bytes to send before monitoring.",
    )
    parser.add_argument(
        "--control-length",
        type=lambda value: int(value, 0),
        help="Optional control transfer length. Required for control IN reads when no control-data-hex is provided.",
    )
    parser.add_argument("--show-zero-changes", action="store_true")
    parser.add_argument(
        "--print-payload-bytes",
        type=int,
        default=96,
        help="Maximum payload bytes to print for IN/OUT logs. Use 0 for summaries only, -1 for full payloads.",
    )
    parser.add_argument(
        "--quiet-out",
        action="store_true",
        help="Suppress per-payload OUT submission logs.",
    )
    args = parser.parse_args()

    control_fields = (
        args.control_request_type,
        args.control_request,
        args.control_value,
        args.control_index,
    )
    if any(field is not None for field in control_fields):
        if any(field is None for field in control_fields):
            parser.error(
                "--control-request-type, --control-request, --control-value, and --control-index must be provided together."
            )
    if args.send_repeat < 1:
        parser.error("--send-repeat must be at least 1.")
    if args.coupled_out_per_in < 0:
        parser.error("--coupled-out-per-in must be >= 0.")
    if args.out_iso_group_size < 1:
        parser.error("--out-iso-group-size must be at least 1.")
    if args.out_iso_queue_depth < 1:
        parser.error("--out-iso-queue-depth must be at least 1.")
    if args.coupled_prime_out is not None and args.coupled_prime_out < 0:
        parser.error("--coupled-prime-out must be >= 0.")
    if not 0 <= args.usb_midi_cable <= 15:
        parser.error("--usb-midi-cable must be in the range 0..15.")
    try:
        args.coupled_window_counts = parse_count_pattern(args.coupled_window_counts)
    except ValueError as exc:
        parser.error(str(exc))
    coupled_mode = args.coupled_out_per_in > 0 or args.coupled_window_counts is not None
    if coupled_mode:
        if args.no_monitor:
            parser.error("coupled OUT pacing requires active monitoring.")
        if args.coupled_prime_out is None:
            if args.coupled_window_counts is not None:
                args.coupled_prime_out = args.coupled_window_counts[0]
            else:
                args.coupled_prime_out = args.coupled_out_per_in
    elif args.coupled_prime_out is not None:
        parser.error("--coupled-prime-out requires coupled OUT pacing.")
    try:
        args.coupled_in_lengths = parse_length_filter(args.coupled_in_lengths)
    except ValueError as exc:
        parser.error(str(exc))

    libusb = load_libusb()
    libusb.libusb_init.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
    libusb.libusb_init.restype = ctypes.c_int
    libusb.libusb_exit.argtypes = [ctypes.c_void_p]
    libusb.libusb_open_device_with_vid_pid.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ushort,
        ctypes.c_ushort,
    ]
    libusb.libusb_open_device_with_vid_pid.restype = ctypes.c_void_p
    libusb.libusb_close.argtypes = [ctypes.c_void_p]
    libusb.libusb_control_transfer.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ubyte,
        ctypes.c_ubyte,
        ctypes.c_ushort,
        ctypes.c_ushort,
        ctypes.POINTER(ctypes.c_ubyte),
        ctypes.c_ushort,
        ctypes.c_uint,
    ]
    libusb.libusb_control_transfer.restype = ctypes.c_int
    libusb.libusb_bulk_transfer.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ubyte,
        ctypes.POINTER(ctypes.c_ubyte),
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_int),
        ctypes.c_uint,
    ]
    libusb.libusb_bulk_transfer.restype = ctypes.c_int
    libusb.libusb_interrupt_transfer.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ubyte,
        ctypes.POINTER(ctypes.c_ubyte),
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_int),
        ctypes.c_uint,
    ]
    libusb.libusb_interrupt_transfer.restype = ctypes.c_int
    libusb.libusb_set_auto_detach_kernel_driver.argtypes = [ctypes.c_void_p, ctypes.c_int]
    libusb.libusb_claim_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
    libusb.libusb_claim_interface.restype = ctypes.c_int
    libusb.libusb_release_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
    libusb.libusb_set_interface_alt_setting.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    libusb.libusb_set_interface_alt_setting.restype = ctypes.c_int
    libusb.libusb_alloc_transfer.argtypes = [ctypes.c_int]
    libusb.libusb_alloc_transfer.restype = ctypes.POINTER(LibusbTransfer)
    libusb.libusb_submit_transfer.argtypes = [ctypes.POINTER(LibusbTransfer)]
    libusb.libusb_submit_transfer.restype = ctypes.c_int
    libusb.libusb_cancel_transfer.argtypes = [ctypes.POINTER(LibusbTransfer)]
    libusb.libusb_cancel_transfer.restype = ctypes.c_int
    libusb.libusb_free_transfer.argtypes = [ctypes.POINTER(LibusbTransfer)]
    libusb.libusb_handle_events_timeout_completed.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(Timeval),
        ctypes.POINTER(ctypes.c_int),
    ]
    libusb.libusb_handle_events_timeout_completed.restype = ctypes.c_int

    context = ctypes.c_void_p()
    result = libusb.libusb_init(ctypes.byref(context))
    if result != 0:
        print(f"libusb_init failed: {result}", file=sys.stderr)
        return 1

    handle = None
    transfer = None
    buffer = None
    active_out_transfers = {}
    state = ProbeState(args)
    completed = ctypes.c_int(0)

    def stop_handler(signum, frame):
        del signum, frame
        state.running = False

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    @TransferCallback
    def on_transfer(transfer_ptr):
        transfer_state = transfer_ptr.contents
        descriptors = descriptor_array(transfer_ptr)
        raw = ctypes.string_at(transfer_state.buffer, transfer_state.length)
        offset = 0

        if transfer_state.status == LIBUSB_TRANSFER_COMPLETED:
            completed_payloads = []
            for descriptor in descriptors:
                payload = raw[offset:offset + descriptor.actual_length]
                offset += descriptor.length
                if descriptor.actual_length <= 0:
                    continue
                completed_payloads.append(payload)

            if args.split_iso_in_descriptors:
                for payload in completed_payloads:
                    record_in_payload(state, payload, args.show_zero_changes, args.print_payload_bytes)
            elif completed_payloads:
                aggregate_payload = b"".join(completed_payloads)
                record_in_payload(state, aggregate_payload, args.show_zero_changes, args.print_payload_bytes)
        elif transfer_state.status != LIBUSB_TRANSFER_CANCELLED:
            state.transfer_error = transfer_state.status
            state.running = False
            return

        if not state.running:
            return

        resubmit = libusb.libusb_submit_transfer(transfer_ptr)
        if resubmit != 0:
            state.transfer_error = resubmit
            state.running = False

    @TransferCallback
    def on_out_transfer(transfer_ptr):
        transfer_state = transfer_ptr.contents
        transfer_address = ctypes.addressof(transfer_state)
        state.completed_out_transfers.put((transfer_address, transfer_state.status))
        if transfer_state.status not in (LIBUSB_TRANSFER_COMPLETED, LIBUSB_TRANSFER_CANCELLED):
            state.transfer_error = transfer_state.status
            state.running = False

    def drain_completed_out_transfers():
        while True:
            try:
                transfer_address, transfer_status = state.completed_out_transfers.get_nowait()
            except queue.Empty:
                break
            transfer_entry = active_out_transfers.pop(transfer_address, None)
            if transfer_entry is None:
                continue
            transfer_ptr = transfer_entry[0]
            libusb.libusb_free_transfer(transfer_ptr)
            if transfer_status not in (LIBUSB_TRANSFER_COMPLETED, LIBUSB_TRANSFER_CANCELLED):
                state.transfer_error = transfer_status
                state.running = False

    def handle_events(timeout_usec, error_label):
        timeout = Timeval(0, timeout_usec)
        result = libusb.libusb_handle_events_timeout_completed(
            context,
            ctypes.byref(timeout),
            ctypes.byref(completed),
        )
        if result != 0:
            print(f"{error_label}: {result}", file=sys.stderr)
            state.transfer_error = result
            state.running = False
            return result
        drain_completed_out_transfers()
        return 0

    def wait_for_out_capacity(timeout_seconds):
        if args.out_transfer_type != "iso":
            return 0
        deadline = time.monotonic() + timeout_seconds
        while state.running and len(active_out_transfers) >= args.out_iso_queue_depth and time.monotonic() < deadline:
            result = handle_events(100000, "libusb_handle_events_timeout_completed failed during OUT")
            if result != 0:
                return 10
        if len(active_out_transfers) >= args.out_iso_queue_depth:
            print("OUT transfer queue did not drain before timeout.", file=sys.stderr)
            return 11
        return 0

    def wait_for_all_out_transfers(timeout_seconds):
        deadline = time.monotonic() + timeout_seconds
        while state.running and active_out_transfers and time.monotonic() < deadline:
            result = handle_events(100000, "libusb_handle_events_timeout_completed failed while draining OUT")
            if result != 0:
                return 10
        if active_out_transfers:
            return 11
        return 0

    try:
        handle = libusb.libusb_open_device_with_vid_pid(context, args.vendor_id, args.product_id)
        if not handle:
            print("DDJ-1000 USB device could not be opened.", file=sys.stderr)
            return 2

        libusb.libusb_set_auto_detach_kernel_driver(handle, 1)

        result = libusb.libusb_claim_interface(handle, args.interface)
        if result != 0:
            print(f"libusb_claim_interface failed: {result}", file=sys.stderr)
            return 3

        if not args.skip_alt_setting:
            result = libusb.libusb_set_interface_alt_setting(handle, args.interface, args.alt_setting)
            if result != 0:
                print(f"libusb_set_interface_alt_setting failed: {result}", file=sys.stderr)
                return 4

        sync_in_poll = not args.no_monitor and args.in_transfer_type in ("bulk", "interrupt")

        def poll_sync_in_once(timeout_ms):
            in_buffer = (ctypes.c_ubyte * max(args.packet_size, 1))()
            transferred = ctypes.c_int(0)
            transfer_fn = (
                libusb.libusb_interrupt_transfer
                if args.in_transfer_type == "interrupt"
                else libusb.libusb_bulk_transfer
            )
            result = transfer_fn(
                handle,
                args.endpoint,
                ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_ubyte)),
                len(in_buffer),
                ctypes.byref(transferred),
                timeout_ms,
            )
            if result == LIBUSB_ERROR_TIMEOUT:
                return 0
            if result != 0:
                state.transfer_error = result
                state.running = False
                return result
            if transferred.value > 0:
                record_in_payload(
                    state,
                    bytes(in_buffer[:transferred.value]),
                    args.show_zero_changes,
                    args.print_payload_bytes,
                )
            return 0

        if not args.no_monitor and args.in_transfer_type == "iso":
            total_length = args.packet_size * args.iso_packets
            buffer = (ctypes.c_ubyte * total_length)()
            transfer = libusb.libusb_alloc_transfer(args.iso_packets)
            if not transfer:
                print("libusb_alloc_transfer failed.", file=sys.stderr)
                return 5

            transfer.contents.dev_handle = handle
            transfer.contents.flags = 0
            transfer.contents.endpoint = args.endpoint
            transfer.contents.type = transfer_type_value(args.in_transfer_type)
            transfer.contents.timeout = args.timeout_ms
            transfer.contents.callback = on_transfer
            transfer.contents.user_data = None
            transfer.contents.buffer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
            transfer.contents.length = total_length
            transfer.contents.num_iso_packets = args.iso_packets

            descriptors = descriptor_array(transfer)
            for descriptor in descriptors:
                descriptor.length = args.packet_size
                descriptor.actual_length = 0
                descriptor.status = 0

            result = libusb.libusb_submit_transfer(transfer)
            if result != 0:
                print(f"libusb_submit_transfer failed: {result}", file=sys.stderr)
                return 6

        if args.control_request_type is not None:
            control_payload = parse_hex_bytes(args.control_data_hex) if args.control_data_hex else b""
            control_length = args.control_length if args.control_length is not None else len(control_payload)
            if control_length < len(control_payload):
                parser.error("--control-length cannot be smaller than the provided control payload length.")

            is_control_in = (args.control_request_type & 0x80) != 0
            control_buffer = (ctypes.c_ubyte * max(control_length, 1))()
            for index, byte_value in enumerate(control_payload):
                control_buffer[index] = byte_value
            transferred = libusb.libusb_control_transfer(
                handle,
                args.control_request_type,
                args.control_request,
                args.control_value,
                args.control_index,
                ctypes.cast(control_buffer, ctypes.POINTER(ctypes.c_ubyte)),
                control_length,
                args.timeout_ms,
            )
            if transferred < 0:
                print(f"libusb_control_transfer failed: {transferred}", file=sys.stderr)
                return 13
            transferred_payload = bytes(control_buffer[:transferred]) if transferred > 0 else b""
            print(
                "submitted control transfer "
                f"bmRequestType=0x{args.control_request_type:02x} "
                f"bRequest=0x{args.control_request:02x} "
                f"wValue=0x{args.control_value:04x} "
                f"wIndex=0x{args.control_index:04x} "
                f"len={control_length}"
                f"{format_hex_preview(transferred_payload if is_control_in else control_payload, args.print_payload_bytes)}"
            )
            sys.stdout.flush()

        send_payloads = []
        if args.send_file:
            send_payloads.extend(
                load_send_file(
                    args.send_file,
                    usb_midi_encode=args.usb_midi_encode,
                    usb_midi_cable=args.usb_midi_cable,
                )
            )
        for send_hex in args.send_hex:
            payload = parse_hex_bytes(send_hex)
            if args.usb_midi_encode:
                payload = encode_usb_midi_message(payload, cable=args.usb_midi_cable)
            send_payloads.append(payload)
        if args.send_repeat > 1 and send_payloads:
            send_payloads = send_payloads * args.send_repeat

        def submit_out_payloads(payload_group, index, total_payloads):
            payload_group = [payload for payload in payload_group if payload]
            if not payload_group:
                return 0
            if args.out_transfer_type in ("bulk", "interrupt"):
                if len(payload_group) != 1:
                    print(
                        f"{args.out_transfer_type} OUT grouping requires exactly one payload per transfer.",
                        file=sys.stderr,
                    )
                    return 9
                payload = payload_group[0]
                out_buffer = (ctypes.c_ubyte * len(payload)).from_buffer_copy(payload)
                transferred = ctypes.c_int(0)
                transfer_fn = (libusb.libusb_interrupt_transfer
                               if args.out_transfer_type == "interrupt"
                               else libusb.libusb_bulk_transfer)
                result = transfer_fn(
                    handle,
                    args.out_endpoint,
                    ctypes.cast(out_buffer, ctypes.POINTER(ctypes.c_ubyte)),
                    len(payload),
                    ctypes.byref(transferred),
                    args.timeout_ms,
                )
                if result != 0 or transferred.value != len(payload):
                    print(
                        f"{args.out_transfer_type} OUT payload {index} failed: "
                        f"result={result} transferred={transferred.value}/{len(payload)}",
                        file=sys.stderr,
                    )
                    return 9
                if not args.quiet_out:
                    print(
                        f"submitted {args.out_transfer_type} OUT payload {index} "
                        f"on endpoint 0x{args.out_endpoint:02x} "
                        f"len={len(payload)}{format_hex_preview(payload, args.print_payload_bytes)}"
                    )
                    sys.stdout.flush()
                if args.send_delay_ms > 0 and index < total_payloads:
                    if sync_in_poll:
                        poll_result = poll_sync_in_once(max(1, min(args.timeout_ms, 5)))
                        if poll_result != 0:
                            print(f"IN poll failed during OUT replay: {poll_result}", file=sys.stderr)
                            return 10
                    time.sleep(args.send_delay_ms / 1000.0)
                return 0

            total_payload_length = sum(len(payload) for payload in payload_group)
            capacity_result = wait_for_out_capacity(max(1.0, args.timeout_ms / 1000.0))
            if capacity_result != 0:
                return capacity_result
            out_buffer = (ctypes.c_ubyte * total_payload_length)()
            offset = 0
            for payload in payload_group:
                payload_length = len(payload)
                out_buffer[offset:offset + payload_length] = payload
                offset += payload_length

            out_transfer = libusb.libusb_alloc_transfer(len(payload_group))
            if not out_transfer:
                print("libusb_alloc_transfer for OUT failed.", file=sys.stderr)
                return 8

            out_transfer.contents.dev_handle = handle
            out_transfer.contents.flags = 0
            out_transfer.contents.endpoint = args.out_endpoint
            out_transfer.contents.type = LIBUSB_TRANSFER_TYPE_ISOCHRONOUS
            out_transfer.contents.timeout = args.timeout_ms
            out_transfer.contents.callback = on_out_transfer
            out_transfer.contents.user_data = None
            out_transfer.contents.buffer = ctypes.cast(out_buffer, ctypes.POINTER(ctypes.c_ubyte))
            out_transfer.contents.length = total_payload_length
            out_transfer.contents.num_iso_packets = len(payload_group)

            out_descriptors = descriptor_array(out_transfer)
            for descriptor, payload in zip(out_descriptors, payload_group):
                descriptor.length = len(payload)
                descriptor.actual_length = 0
                descriptor.status = 0

            result = libusb.libusb_submit_transfer(out_transfer)
            if result != 0:
                print(f"libusb_submit_transfer for OUT failed: {result}", file=sys.stderr)
                libusb.libusb_free_transfer(out_transfer)
                return 9

            transfer_address = ctypes.addressof(out_transfer.contents)
            active_out_transfers[transfer_address] = (out_transfer, out_buffer)
            if not args.quiet_out:
                print(
                    f"submitted OUT payloads {index}-{index + len(payload_group) - 1} on endpoint 0x{args.out_endpoint:02x} "
                    f"count={len(payload_group)} total_len={total_payload_length}"
                )
                sys.stdout.flush()

            if sync_in_poll:
                poll_result = poll_sync_in_once(max(1, min(args.timeout_ms, 5)))
                if poll_result != 0:
                    print(f"IN poll failed during OUT replay: {poll_result}", file=sys.stderr)
                    return 10

            if args.send_delay_ms > 0 and index < total_payloads:
                time.sleep(args.send_delay_ms / 1000.0)
            return 0

        next_send_index = 0

        def submit_next_out_payloads(limit):
            nonlocal next_send_index
            submitted = 0
            while submitted < limit and next_send_index < len(send_payloads) and state.running:
                group_size = 1
                if args.out_transfer_type == "iso":
                    group_size = min(args.out_iso_group_size, limit - submitted)
                payload_group = send_payloads[next_send_index:next_send_index + group_size]
                result = submit_out_payloads(payload_group, next_send_index + 1, len(send_payloads))
                if result != 0:
                    return result
                next_send_index += len(payload_group)
                submitted += len(payload_group)
            return 0

        if coupled_mode:
            prime_result = submit_next_out_payloads(min(args.coupled_prime_out, len(send_payloads)))
            if prime_result != 0:
                return prime_result
        else:
            send_result = submit_next_out_payloads(len(send_payloads))
            if send_result != 0:
                return send_result

        if args.no_monitor:
            drain_result = wait_for_all_out_transfers(max(1.0, args.timeout_ms / 1000.0))
            if drain_result == 11:
                print("Timed out while draining queued OUT transfers.", file=sys.stderr)
                return 11
            if drain_result != 0:
                return drain_result
            print(
                f"Sent payloads on DDJ USB interface {args.interface}; "
                "IN monitoring was skipped."
            )
            sys.stdout.flush()
            state.running = False
        else:
            print(
                f"Monitoring DDJ USB interface {args.interface} alt {args.alt_setting} "
                f"endpoint 0x{args.endpoint:02x} for {args.duration:.1f}s. Press controller buttons now."
            )
            sys.stdout.flush()

        deadline = time.monotonic() + args.duration
        while state.running and time.monotonic() < deadline:
            if sync_in_poll:
                poll_result = poll_sync_in_once(max(1, min(args.timeout_ms, 50)))
                if poll_result != 0:
                    print(f"libusb {args.in_transfer_type} IN polling failed: {poll_result}", file=sys.stderr)
                    break
                continue
            timeout = Timeval(0, 200000)
            result = libusb.libusb_handle_events_timeout_completed(
                context,
                ctypes.byref(timeout),
                ctypes.byref(completed),
            )
            if result != 0:
                print(f"libusb_handle_events_timeout_completed failed: {result}", file=sys.stderr)
                state.transfer_error = result
                break
            drain_completed_out_transfers()

            if coupled_mode and state.pending_out_budget > 0:
                budget = state.pending_out_budget
                state.pending_out_budget = 0
                send_result = submit_next_out_payloads(budget)
                if send_result != 0:
                    return send_result

        state.running = False
        if transfer is not None:
            libusb.libusb_cancel_transfer(transfer)
            for _ in range(10):
                timeout = Timeval(0, 100000)
                libusb.libusb_handle_events_timeout_completed(
                    context,
                    ctypes.byref(timeout),
                    ctypes.byref(completed),
                )

        drain_completed_out_transfers()
        for out_transfer, _ in active_out_transfers.values():
            libusb.libusb_cancel_transfer(out_transfer)

        if active_out_transfers:
            for _ in range(10):
                handle_events(100000, "libusb_handle_events_timeout_completed failed while cancelling OUT")

        print(f"Total packets: {state.packet_count}")
        print(f"Changed packets: {state.changed_count}")
        if args.summarize_in_lengths and state.in_payload_count > 0:
            observed_parts = [
                f"{payload_length}:{count}"
                for payload_length, count in sorted(state.in_length_counts.items())
            ]
            summary_parts = [
                f"{payload_length}:{count}"
                for payload_length, count in sorted(state.qualified_in_length_counts.items())
            ]
            print("Observed IN lengths: " + ", ".join(observed_parts))
            if summary_parts:
                print(
                    "Qualified IN lengths: "
                    + ", ".join(summary_parts)
                    + f" (windows={state.qualified_in_payload_count})"
                )
            else:
                print("Qualified IN lengths: <none>")
        if state.transfer_error:
            print(f"Transfer error/status: {state.transfer_error}", file=sys.stderr)
            return 7

        return 0
    finally:
        for out_transfer, _ in active_out_transfers.values():
            libusb.libusb_free_transfer(out_transfer)
        if transfer is not None:
            libusb.libusb_free_transfer(transfer)
        if handle is not None:
            release_result = libusb.libusb_release_interface(handle, args.interface)
            if release_result not in (0, LIBUSB_ERROR_NOT_FOUND):
                print(f"libusb_release_interface failed: {release_result}", file=sys.stderr)
            libusb.libusb_close(handle)
        libusb.libusb_exit(context)


if __name__ == "__main__":
    raise SystemExit(main())
