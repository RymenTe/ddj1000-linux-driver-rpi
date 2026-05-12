#!/usr/bin/env python3

import argparse
import math
import pathlib
import struct
import subprocess
import sys
import tempfile
from typing import IO


def repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent.parent


def default_payload_file() -> pathlib.Path:
    return repo_root() / "build" / "generated" / "ddj1000-audio-ep01-silence120.txt"


def default_silence_packet_size() -> int:
    return 792


def default_silence_payload_count() -> int:
    return 120


def build_default_silence_payloads() -> list[bytes]:
    return [bytes(default_silence_packet_size()) for _ in range(default_silence_payload_count())]


def parse_hex_bytes(value: str) -> bytes:
    normalized = value.replace(",", " ").replace(":", " ")
    parts = [part for part in normalized.split() if part]
    return bytes(int(part, 16) for part in parts)


def load_payloads(path: pathlib.Path) -> list[bytes]:
    payloads: list[bytes] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            payloads.append(parse_hex_bytes(stripped))
    if not payloads:
        raise ValueError(f"payload file contains no payloads: {path}")
    return payloads


def packet_size_from_payload_file(path: pathlib.Path) -> int:
    return len(load_payloads(path)[0])


def payload_count_from_payload_file(path: pathlib.Path) -> int:
    return len(load_payloads(path))


def write_payload_file(payloads: list[bytes]) -> IO[str]:
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False)
    with handle:
        for payload in payloads:
            handle.write(" ".join(f"{byte:02x}" for byte in payload))
            handle.write("\n")
    return handle


def packet_count_from_timing(duration: float, send_delay_ms: float) -> int:
    safe_delay_ms = max(send_delay_ms, 0.1)
    return max(1, math.ceil((duration * 1000.0) / safe_delay_ms))


def packet_sizes_from_args(args: argparse.Namespace, fallback_packet_size: int | None) -> list[int]:
    if args.packet_pattern == "capture-44k1-10ms":
        base_pattern = [810] + [792] * 9
        pattern_duration = args.packet_pattern_duration_ms / 1000.0
        repeat_count = max(1, math.ceil(args.duration / pattern_duration))
        packet_sizes = (base_pattern * repeat_count)[: max(1, math.ceil(args.duration / pattern_duration * len(base_pattern)))]
        return packet_sizes

    if args.packet_pattern:
        packet_sizes = [int(part.strip()) for part in args.packet_pattern.split(",") if part.strip()]
        if not packet_sizes:
            raise ValueError("packet pattern must contain at least one packet size")
        packet_count = packet_count_from_timing(args.duration, args.send_delay_ms)
        repeated = []
        while len(repeated) < packet_count:
            repeated.extend(packet_sizes)
        return repeated[:packet_count]

    if fallback_packet_size is None:
        raise ValueError("a packet size or packet pattern is required")

    packet_count = packet_count_from_timing(args.duration, args.send_delay_ms)
    return [fallback_packet_size] * packet_count


def parse_packet_size_pattern(value: str) -> list[int]:
    packet_sizes = [int(part.strip()) for part in value.split(",") if part.strip()]
    if not packet_sizes:
        raise ValueError("packet pattern must contain at least one packet size")
    for packet_size in packet_sizes:
        if packet_size <= 0:
            raise ValueError("packet sizes must be greater than 0")
    return packet_sizes


def encode_pcm_sample_s16(value: float) -> bytes:
    clamped = max(-1.0, min(1.0, value))
    scaled = int(round(clamped * 32767.0))
    return struct.pack("<h", scaled)


def encode_pcm_sample_s24(value: float) -> bytes:
    clamped = max(-1.0, min(1.0, value))
    scaled = int(round(clamped * 8388607.0))
    if scaled < 0:
        scaled += 1 << 24
    return scaled.to_bytes(3, byteorder="little", signed=False)


def encode_s16_frame_to_s24(frame_bytes: bytes) -> bytes:
    padded = frame_bytes + bytes(max(0, 4 - len(frame_bytes)))
    left_value = struct.unpack("<h", padded[:2])[0] / 32767.0 if padded[:2] else 0.0
    right_value = struct.unpack("<h", padded[2:4])[0] / 32767.0 if padded[2:4] else 0.0
    return encode_pcm_sample_s24(left_value) + encode_pcm_sample_s24(right_value)


def encode_triple_stereo_frame_s24(left_value: float,
                                   right_value: float,
                                   channel_mode: str) -> bytes:
    stereo_pair = encode_pcm_sample_s24(left_value) + encode_pcm_sample_s24(right_value)
    silence_pair = bytes(6)
    if channel_mode == "all":
        return stereo_pair * 3
    if channel_mode == "pair0":
        return stereo_pair + silence_pair + silence_pair
    if channel_mode == "pair1":
        return silence_pair + stereo_pair + silence_pair
    if channel_mode == "pair2":
        return silence_pair + silence_pair + stereo_pair
    raise ValueError(f"unsupported triple stereo channel mode: {channel_mode}")


def encode_s16_frame_to_triple_stereo_s24(frame_bytes: bytes, channel_mode: str) -> bytes:
    padded = frame_bytes + bytes(max(0, 4 - len(frame_bytes)))
    left_value = struct.unpack("<h", padded[:2])[0] / 32767.0 if padded[:2] else 0.0
    right_value = struct.unpack("<h", padded[2:4])[0] / 32767.0 if padded[2:4] else 0.0
    return encode_triple_stereo_frame_s24(left_value, right_value, channel_mode)


def validate_slot36_packet_size(packet_size: int) -> int:
    block_size = 36
    if packet_size % block_size != 0:
        raise ValueError(
            f"packet size {packet_size} is not divisible by 36 bytes for slot36 packing"
        )
    return packet_size // block_size


def validate_frame18_packet_size(packet_size: int) -> int:
    frame_size = 18
    if packet_size % frame_size != 0:
        raise ValueError(
            f"packet size {packet_size} is not divisible by 18 bytes for triple-stereo packing"
        )
    return packet_size // frame_size


def validate_frame6_packet_size(packet_size: int) -> int:
    frame_size = 6
    if packet_size % frame_size != 0:
        raise ValueError(
            f"packet size {packet_size} is not divisible by 6 bytes for stereo-s24le packing"
        )
    return packet_size // frame_size


def tone_frame_values(args: argparse.Namespace, frame_index: int) -> tuple[float, float]:
    time_seconds = frame_index / args.sample_rate
    left_value = math.sin(2.0 * math.pi * args.tone_frequency_left * time_seconds)
    right_value = math.sin(2.0 * math.pi * args.tone_frequency_right * time_seconds)
    return left_value * args.tone_amplitude, right_value * args.tone_amplitude


def build_stereo_s24_tone_payloads(args: argparse.Namespace, packet_sizes: list[int]) -> list[bytes]:
    payloads: list[bytes] = []
    frame_index = 0
    for packet_size in packet_sizes:
        frames_per_packet = validate_frame6_packet_size(packet_size)
        packet = bytearray()
        for _ in range(frames_per_packet):
            left_value, right_value = tone_frame_values(args, frame_index)
            packet.extend(encode_pcm_sample_s24(left_value))
            packet.extend(encode_pcm_sample_s24(right_value))
            frame_index += 1
        if len(packet) != packet_size:
            raise ValueError(f"stereo-s24le tone packet has unexpected size {len(packet)}")
        payloads.append(bytes(packet))
    return payloads


def build_triple_stereo_tone_payloads(args: argparse.Namespace, packet_sizes: list[int]) -> list[bytes]:
    payloads: list[bytes] = []
    frame_index = 0
    for packet_size in packet_sizes:
        frames_per_packet = validate_frame18_packet_size(packet_size)
        packet = bytearray()
        for _ in range(frames_per_packet):
            left_value, right_value = tone_frame_values(args, frame_index)
            packet.extend(encode_triple_stereo_frame_s24(
                left_value,
                right_value,
                args.triple_stereo_channel_mode,
            ))
            frame_index += 1
        if len(packet) != packet_size:
            raise ValueError(f"triple-stereo tone packet has unexpected size {len(packet)}")
        payloads.append(bytes(packet))
    return payloads


def build_slot36_tone_payloads(args: argparse.Namespace, packet_sizes: list[int]) -> list[bytes]:
    payloads: list[bytes] = []
    frame_index = 0

    for packet_size in packet_sizes:
        blocks_per_packet = validate_slot36_packet_size(packet_size)
        packet = bytearray()
        for _ in range(blocks_per_packet):
            for _ in range(4):
                left_value, right_value = tone_frame_values(args, frame_index)
                packet.extend(encode_pcm_sample_s24(left_value))
                packet.extend(encode_pcm_sample_s24(right_value))
                frame_index += 1
            packet.extend(bytes(12))
        if len(packet) != packet_size:
            raise ValueError(f"slot36 tone packet has unexpected size {len(packet)}")
        payloads.append(bytes(packet))

    return payloads


def build_plain_s16_tone_payloads(args: argparse.Namespace, packet_sizes: list[int]) -> list[bytes]:
    bytes_per_frame = 4
    payloads: list[bytes] = []
    frame_index = 0

    for packet_size in packet_sizes:
        if packet_size % bytes_per_frame != 0:
            raise ValueError(
                f"packet size {packet_size} is not divisible by 4 bytes for stereo s16le samples"
            )
        frames_per_packet = packet_size // bytes_per_frame
        packet = bytearray()
        for _ in range(frames_per_packet):
            left_value, right_value = tone_frame_values(args, frame_index)
            packet.extend(encode_pcm_sample_s16(left_value))
            packet.extend(encode_pcm_sample_s16(right_value))
            frame_index += 1
        payloads.append(bytes(packet))

    return payloads


def build_tone_payloads(args: argparse.Namespace, packet_sizes: list[int]) -> list[bytes]:
    if args.packing == "stereo-s24le":
        return build_stereo_s24_tone_payloads(args, packet_sizes)

    if args.packing == "triple-stereo-s24le":
        return build_triple_stereo_tone_payloads(args, packet_sizes)

    if args.packing == "slot36-s24le":
        return build_slot36_tone_payloads(args, packet_sizes)

    return build_plain_s16_tone_payloads(args, packet_sizes)


def read_raw_payload_input(args: argparse.Namespace) -> bytes:
    if args.raw_file is None:
        raise ValueError("raw mode requires --raw-file")

    raw_data = args.raw_file.read_bytes()
    if not raw_data:
        raise ValueError(f"raw file is empty: {args.raw_file}")

    return raw_data


def read_padded_s16_input_frame(raw_data: bytes,
                                frame_offset: int,
                                bytes_per_input_frame: int = 4) -> bytes:
    frame = raw_data[frame_offset:frame_offset + bytes_per_input_frame]
    if len(frame) < bytes_per_input_frame:
        return frame + bytes(bytes_per_input_frame - len(frame))
    return frame


def build_stereo_s24_raw_payloads(args: argparse.Namespace,
                                  packet_sizes: list[int],
                                  raw_data: bytes) -> list[bytes]:
    payloads: list[bytes] = []
    frame_offset = 0
    bytes_per_input_frame = 4

    for packet_size in packet_sizes:
        frames_per_packet = validate_frame6_packet_size(packet_size)
        packet = bytearray()
        for _ in range(frames_per_packet):
            packet.extend(
                encode_s16_frame_to_s24(
                    read_padded_s16_input_frame(raw_data, frame_offset, bytes_per_input_frame)
                )
            )
            frame_offset += bytes_per_input_frame
        if len(packet) != packet_size:
            raise ValueError(f"stereo-s24le raw packet has unexpected size {len(packet)}")
        payloads.append(bytes(packet))
        if frame_offset >= len(raw_data):
            break
    return payloads


def build_triple_stereo_raw_payloads(args: argparse.Namespace,
                                     packet_sizes: list[int],
                                     raw_data: bytes) -> list[bytes]:
    payloads: list[bytes] = []
    frame_offset = 0
    bytes_per_input_frame = 4

    for packet_size in packet_sizes:
        frames_per_packet = validate_frame18_packet_size(packet_size)
        packet = bytearray()
        for _ in range(frames_per_packet):
            packet.extend(
                encode_s16_frame_to_triple_stereo_s24(
                    read_padded_s16_input_frame(raw_data, frame_offset, bytes_per_input_frame),
                    args.triple_stereo_channel_mode,
                )
            )
            frame_offset += bytes_per_input_frame
        if len(packet) != packet_size:
            raise ValueError(f"triple-stereo raw packet has unexpected size {len(packet)}")
        payloads.append(bytes(packet))
        if frame_offset >= len(raw_data):
            break
    return payloads


def build_slot36_raw_payloads(packet_sizes: list[int], raw_data: bytes) -> list[bytes]:
    payloads: list[bytes] = []
    frame_offset = 0
    bytes_per_input_frame = 4

    for packet_size in packet_sizes:
        blocks_per_packet = validate_slot36_packet_size(packet_size)
        packet = bytearray()
        for _ in range(blocks_per_packet):
            for _ in range(4):
                packet.extend(
                    encode_s16_frame_to_s24(
                        read_padded_s16_input_frame(raw_data, frame_offset, bytes_per_input_frame)
                    )
                )
                frame_offset += bytes_per_input_frame
            packet.extend(bytes(12))
        if len(packet) != packet_size:
            raise ValueError(f"slot36 raw packet has unexpected size {len(packet)}")
        payloads.append(bytes(packet))
        if frame_offset >= len(raw_data):
            break
    return payloads


def build_plain_s16_raw_payloads(packet_sizes: list[int], raw_data: bytes) -> list[bytes]:
    payloads: list[bytes] = []
    offset = 0
    for packet_size in packet_sizes:
        chunk = raw_data[offset:offset + packet_size]
        if len(chunk) < packet_size:
            chunk = chunk + bytes(packet_size - len(chunk))
        payloads.append(chunk)
        offset += packet_size
        if offset >= len(raw_data):
            break
    return payloads


def build_raw_payloads(args: argparse.Namespace, packet_sizes: list[int]) -> list[bytes]:
    raw_data = read_raw_payload_input(args)

    if args.packing == "stereo-s24le":
        return build_stereo_s24_raw_payloads(args, packet_sizes, raw_data)

    if args.packing == "triple-stereo-s24le":
        return build_triple_stereo_raw_payloads(args, packet_sizes, raw_data)

    if args.packing == "slot36-s24le":
        return build_slot36_raw_payloads(packet_sizes, raw_data)

    return build_plain_s16_raw_payloads(packet_sizes, raw_data)


def append_coupled_probe_args(command: list[str], args: argparse.Namespace) -> None:
    if args.coupled_out_per_in > 0:
        command.extend([
            "--coupled-out-per-in",
            str(args.coupled_out_per_in),
        ])

    if args.coupled_out_per_in <= 0 and not args.coupled_window_counts:
        return

    if args.coupled_prime_out is not None:
        command.extend([
            "--coupled-prime-out",
            str(args.coupled_prime_out),
        ])
    if args.coupled_in_lengths:
        command.extend([
            "--coupled-in-lengths",
            args.coupled_in_lengths,
        ])
    if args.coupled_window_counts:
        command.extend([
            "--coupled-window-counts",
            args.coupled_window_counts,
        ])


def append_probe_mode_args(command: list[str], args: argparse.Namespace) -> None:
    if args.summarize_in_lengths:
        command.append("--summarize-in-lengths")

    if not args.monitor_in:
        command.append("--no-monitor")

    if args.quiet_out:
        command.append("--quiet-out")


def build_probe_command(args: argparse.Namespace, payload_file: pathlib.Path, repeat: int) -> list[str]:
    command = [
        sys.executable,
        str(repo_root() / "scripts" / "runtime" / "ddj1000-usb-probe.py"),
        "--vendor-id",
        hex(args.vendor_id),
        "--product-id",
        hex(args.product_id),
        "--interface",
        str(args.interface),
        "--alt-setting",
        str(args.alt_setting),
        "--endpoint",
        hex(args.in_endpoint),
        "--out-endpoint",
        hex(args.out_endpoint),
        "--out-transfer-type",
        args.out_transfer_type,
        "--out-iso-group-size",
        str(args.out_iso_group_size),
        "--out-iso-queue-depth",
        str(args.out_iso_queue_depth),
        "--send-file",
        str(payload_file),
        "--send-repeat",
        str(repeat),
        "--send-delay-ms",
        str(args.send_delay_ms),
        "--duration",
        str(args.duration),
        "--print-payload-bytes",
        str(args.print_payload_bytes),
    ]

    append_coupled_probe_args(command, args)
    append_probe_mode_args(command, args)

    return command


def apply_preroll_payloads(args: argparse.Namespace, payloads: list[bytes]) -> list[bytes]:
    preroll_payloads: list[bytes] = []

    if args.preroll_zero_pattern:
        preroll_payloads.extend(bytes(packet_size) for packet_size in parse_packet_size_pattern(args.preroll_zero_pattern))

    if args.preroll_payload_file is None:
        return preroll_payloads + payloads

    preroll_payloads.extend(load_payloads(args.preroll_payload_file) * args.preroll_repeat)
    return preroll_payloads + payloads


def validate_and_normalize_args(parser: argparse.ArgumentParser,
                                args: argparse.Namespace) -> argparse.Namespace:
    if args.duration <= 0.0:
        parser.error("--duration must be greater than 0.")

    if args.send_delay_ms <= 0.0:
        parser.error("--send-delay-ms must be greater than 0.")

    if args.out_iso_group_size < 1:
        parser.error("--out-iso-group-size must be at least 1.")

    if args.out_iso_queue_depth < 1:
        parser.error("--out-iso-queue-depth must be at least 1.")

    if args.sample_rate <= 0.0:
        parser.error("--sample-rate must be greater than 0.")

    if args.coupled_out_per_in < 0:
        parser.error("--coupled-out-per-in must be >= 0.")
    if args.coupled_prime_out is not None and args.coupled_prime_out < 0:
        parser.error("--coupled-prime-out must be >= 0.")
    coupled_mode = args.coupled_out_per_in > 0 or bool(args.coupled_window_counts)
    if coupled_mode:
        args.monitor_in = True
    elif args.coupled_prime_out is not None:
        parser.error("--coupled-prime-out requires coupled OUT pacing.")

    if args.packet_pattern_duration_ms <= 0.0:
        parser.error("--packet-pattern-duration-ms must be greater than 0.")

    if not 0.0 < args.tone_amplitude <= 1.0:
        parser.error("--tone-amplitude must be in the range (0, 1].")

    args.payload_file = args.payload_file.resolve()
    if not args.payload_file.is_file() and args.payload_file != default_payload_file().resolve():
        parser.error(f"payload file not found: {args.payload_file}")

    if args.raw_file is not None:
        args.raw_file = args.raw_file.resolve()
        if not args.raw_file.is_file():
            parser.error(f"raw file not found: {args.raw_file}")

    if args.preroll_payload_file is not None:
        args.preroll_payload_file = args.preroll_payload_file.resolve()
        if not args.preroll_payload_file.is_file():
            parser.error(f"preroll payload file not found: {args.preroll_payload_file}")
        if args.source == "file":
            parser.error("--preroll-payload-file is only supported with generated tone/raw sources.")
        if args.preroll_repeat < 1:
            parser.error("--preroll-repeat must be at least 1.")

    if args.preroll_zero_pattern:
        if args.source == "file":
            parser.error("--preroll-zero-pattern is only supported with generated tone/raw sources.")
        try:
            parse_packet_size_pattern(args.preroll_zero_pattern)
        except ValueError as exc:
            parser.error(str(exc))

    if args.keep_generated_payload is not None:
        args.keep_generated_payload = args.keep_generated_payload.resolve()
        if args.keep_generated_payload.exists() and args.keep_generated_payload.is_dir():
            parser.error(f"--keep-generated-payload must be a file path: {args.keep_generated_payload}")

    if args.repeat is None:
        if args.source == "file":
            if args.payload_file.is_file():
                payload_count = payload_count_from_payload_file(args.payload_file)
            else:
                payload_count = default_silence_payload_count()
            required_packets = packet_count_from_timing(args.duration, args.send_delay_ms)
            args.repeat = max(1, math.ceil(required_packets / max(1, payload_count)))
        else:
            args.repeat = 1
    if args.repeat < 1:
        parser.error("--repeat must be at least 1.")

    if args.packet_pattern == "capture-44k1-10ms" and args.source != "file" and args.sample_rate == 48000.0:
        args.sample_rate = 44100.0

    return args


def resolve_file_payload_source(args: argparse.Namespace) -> tuple[pathlib.Path, int, IO[str] | None]:
    if args.payload_file.is_file():
        return args.payload_file, args.repeat, None

    temp_payload_file = write_payload_file(build_default_silence_payloads())
    return pathlib.Path(temp_payload_file.name), args.repeat, temp_payload_file


def resolve_generated_packet_size(args: argparse.Namespace) -> int:
    if args.packet_bytes is not None:
        packet_size = args.packet_bytes
    elif args.payload_file.is_file():
        packet_size = packet_size_from_payload_file(args.payload_file)
    else:
        packet_size = default_silence_packet_size()

    if packet_size <= 0:
        raise ValueError("packet size must be greater than 0")

    return packet_size


def build_generated_payloads(args: argparse.Namespace) -> list[bytes]:
    packet_sizes = packet_sizes_from_args(args, resolve_generated_packet_size(args))

    if args.source == "tone":
        payloads = build_tone_payloads(args, packet_sizes)
    else:
        payloads = build_raw_payloads(args, packet_sizes)

    return apply_preroll_payloads(args, payloads)


def write_generated_payload_output(args: argparse.Namespace,
                                   payloads: list[bytes]) -> tuple[pathlib.Path, int, IO[str] | None]:
    if args.keep_generated_payload is not None:
        args.keep_generated_payload.parent.mkdir(parents=True, exist_ok=True)
        with args.keep_generated_payload.open("w", encoding="utf-8") as handle:
            for payload in payloads:
                handle.write(" ".join(f"{byte:02x}" for byte in payload))
                handle.write("\n")
        return args.keep_generated_payload, args.repeat, None

    temp_payload_file = write_payload_file(payloads)
    return pathlib.Path(temp_payload_file.name), args.repeat, temp_payload_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Send the DDJ-1000 proprietary vendor audio transport on interface 0 alt-setting 1. "
            "Besides the verified silence payload, the wrapper can generate simple s16le stereo test tones "
            "or stream raw PCM packets with the same vendor transport parameters. The capture-matched DDJ "
            "output hypothesis is triple-stereo-s24le plus the capture-44k1-10ms packet pattern: 45 or 44 "
            "sample frames per packet, 18 bytes per frame, 24-bit little-endian across three stereo pairs."
        )
    )
    parser.add_argument("--vendor-id", type=lambda value: int(value, 0), default=0x2B73)
    parser.add_argument("--product-id", type=lambda value: int(value, 0), default=0x0020)
    parser.add_argument("--interface", type=int, default=0)
    parser.add_argument("--alt-setting", type=int, default=1)
    parser.add_argument("--in-endpoint", type=lambda value: int(value, 0), default=0x82)
    parser.add_argument("--out-endpoint", type=lambda value: int(value, 0), default=0x01)
    parser.add_argument("--out-transfer-type", choices=("iso", "bulk", "interrupt"), default="iso")
    parser.add_argument("--out-iso-group-size", type=int, default=1)
    parser.add_argument("--out-iso-queue-depth", type=int, default=1)
    parser.add_argument("--source", choices=("file", "tone", "raw"), default="file")
    parser.add_argument(
        "--packing",
        choices=("plain-s16le", "stereo-s24le", "triple-stereo-s24le", "slot36-s24le"),
        default="plain-s16le",
        help="Packing for generated tone/raw payloads. File mode always sends the payload file as-is.",
    )
    parser.add_argument(
        "--triple-stereo-channel-mode",
        choices=("all", "pair0", "pair1", "pair2"),
        default="all",
        help="Channel placement for triple-stereo-s24le packing. Use all for the first audibility test.",
    )
    parser.add_argument("--payload-file", type=pathlib.Path, default=default_payload_file())
    parser.add_argument("--raw-file", type=pathlib.Path)
    parser.add_argument(
        "--preroll-payload-file",
        type=pathlib.Path,
        help="Optional capture-derived payload file to prepend once or multiple times before generated tone/raw payloads in the same session.",
    )
    parser.add_argument(
        "--preroll-zero-pattern",
        default="",
        help=(
            "Optional comma-separated packet-size pattern of all-zero payloads to prepend before generated tone/raw payloads, "
            "for example 810,792 to reproduce the capture-like activation start."
        ),
    )
    parser.add_argument(
        "--preroll-repeat",
        type=int,
        default=1,
        help="How many times to prepend --preroll-payload-file before generated payloads.",
    )
    parser.add_argument("--packet-bytes", type=int)
    parser.add_argument(
        "--packet-pattern",
        default="",
        help=(
            "Optional comma-separated packet-size pattern for generated tone/raw payloads, "
            "or the preset capture-44k1-10ms for 810,792x9 repetition."
        ),
    )
    parser.add_argument(
        "--packet-pattern-duration-ms",
        type=float,
        default=10.0,
        help="Pattern duration in milliseconds for preset packet patterns.",
    )
    parser.add_argument(
        "--keep-generated-payload",
        type=pathlib.Path,
        help="Optional path to keep the generated tone/raw payload file for inspection instead of using a temporary file.",
    )
    parser.add_argument("--repeat", type=int)
    parser.add_argument("--send-delay-ms", type=float, default=1.0)
    parser.add_argument("--duration", type=float, default=32.0)
    parser.add_argument("--print-payload-bytes", type=int, default=0)
    parser.add_argument("--quiet-out", action="store_true")
    parser.add_argument(
        "--monitor-in",
        action="store_true",
        help="Keep the paired interface-0 IN endpoint active during the send instead of forcing send-only mode.",
    )
    parser.add_argument(
        "--coupled-out-per-in",
        type=int,
        default=0,
        help="Experimental capture-paced mode: submit this many OUT packets after each nonempty monitored IN packet.",
    )
    parser.add_argument(
        "--coupled-prime-out",
        type=int,
        help="Initial OUT packets before coupled pacing. Use 0 to wait for the first IN packet.",
    )
    parser.add_argument(
        "--coupled-in-lengths",
        default="",
        help=(
            "Optional comma-separated list of IN payload lengths that may release coupled OUT budget, "
            "for example 3384,3204,3168 to ignore short keepalive-style packets."
        ),
    )
    parser.add_argument(
        "--coupled-window-counts",
        default="",
        help=(
            "Optional comma-separated repeat pattern for how many OUT payloads to release per qualifying IN window, "
            "for example 2,2,2,3,1."
        ),
    )
    parser.add_argument(
        "--summarize-in-lengths",
        action="store_true",
        help="Print a short summary of monitored IN payload lengths at the end of the probe run.",
    )
    parser.add_argument("--sample-rate", type=float, default=48000.0)
    parser.add_argument("--tone-frequency-left", type=float, default=440.0)
    parser.add_argument("--tone-frequency-right", type=float, default=440.0)
    parser.add_argument("--tone-amplitude", type=float, default=0.18)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the underlying probe-ddj-usb command without executing it.",
    )
    return validate_and_normalize_args(parser, parser.parse_args())


def resolve_payload_source(args: argparse.Namespace) -> tuple[pathlib.Path, int, IO[str] | None]:
    if args.source == "file":
        return resolve_file_payload_source(args)

    return write_generated_payload_output(args, build_generated_payloads(args))


def remove_temp_payload_file(temp_payload_file: IO[str] | None) -> None:
    if temp_payload_file is None:
        return

    try:
        pathlib.Path(temp_payload_file.name).unlink(missing_ok=True)
    except OSError:
        pass


def run_probe_command(args: argparse.Namespace) -> int:
    payload_path, repeat, temp_payload_file = resolve_payload_source(args)
    try:
        command = build_probe_command(args, payload_path, repeat)

        if args.dry_run:
            print(" ".join(command))
            return 0

        completed = subprocess.run(command, cwd=repo_root(), check=False)
        return completed.returncode
    finally:
        remove_temp_payload_file(temp_payload_file)


def main() -> int:
    args = parse_args()
    return run_probe_command(args)


if __name__ == "__main__":
    raise SystemExit(main())
