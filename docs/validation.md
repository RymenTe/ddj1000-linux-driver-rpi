# Validation

This document describes a practical validation path for this DDJ-1000 Linux stack repository.

## What Can Be Validated Without Hardware

On any machine, including CI:

```bash
python3 scripts/validate-repo.py
python3 -m py_compile scripts/*.py scripts/runtime/*.py
bash -n scripts/*.sh scripts/runtime/*.sh scripts/dev/*.sh
```

This only validates repository consistency, not the real DDJ runtime path.

## What Needs Real Hardware

The following checks require a Linux machine with a real DDJ-1000 attached:

- USB access to the DDJ-1000 vendor interface
- `hidraw` access
- `amidi`, `aplay`, and `speaker-test`
- systemd user and system services
- PipeWire or Pulse if the desktop sink path is part of the test

## Recommended Validation Environment

The normal developer setup for real runtime validation is simply a native Linux machine with direct DDJ-1000 access.

If your main working machine is currently a trusted Windows capture box, then a second Linux machine or a separate Linux SSD is the safer option.

Why:

- native Linux is the simplest environment for day-to-day driver and host-stack work
- a second machine or separate Linux disk avoids touching the current Windows capture environment
- Secure Boot can be disabled for Linux validation without changing the Windows test flow if the Linux install is separate
- rollback is easier if the Linux experiment goes wrong

## Minimal Real-Hardware Validation Sequence

1. Use any native Linux machine with direct DDJ-1000 access.
2. If Secure Boot is enabled and you want to avoid MOK enrollment, disable it for the Linux validation run.
3. Clone the repo and run:

```bash
bash scripts/setup-linux.sh all
python3 scripts/validate-repo.py
bash scripts/install-ddj1000-linux-stack.sh install
```

4. Check status:

```bash
bash scripts/install-ddj1000-linux-stack.sh status
```

5. Run the unlock flow once:

```bash
python3 scripts/runtime/ddj1000-unlock-service.py --once --send-post-ack-startup-state
```

6. Confirm ALSA and MIDI presence:

```bash
aplay -l
amidi -l
aplay -L | grep ddj1000_
```

7. Confirm audio playback path:

```bash
speaker-test -D hw:DDJ1000,0 -c 6 -r 44100 -F S24_3LE -t sine -f 440 -l 1 -b 20000 -p 10000 -S 60
```

## Success Criteria

- `aplay -l` shows `DDJ1000`
- `amidi -l` still shows the DDJ MIDI port
- `ddj1000_master` is visible in `aplay -L`
- the DDJ clears `NO AUDIO DRIVER`
- the first `speaker-test` run does not die with immediate `Input/output error`

## External Tester Checklist

If another Linux developer wants to validate this repository on real hardware, ask them to report at least the following:

1. Linux distribution and kernel version.
2. Whether Secure Boot was enabled, disabled, or handled through MOK enrollment.
3. Whether `bash scripts/setup-linux.sh all` completed cleanly.
4. Whether `python3 scripts/validate-repo.py` passed.
5. Whether `bash scripts/install-ddj1000-linux-stack.sh install` completed without manual fixes.
6. The output of `bash scripts/install-ddj1000-linux-stack.sh status`.
7. Whether `aplay -l`, `amidi -l`, and `aplay -L | grep ddj1000_` show the expected DDJ devices.
8. Whether `python3 scripts/runtime/ddj1000-unlock-service.py --once --send-post-ack-startup-state` clears `NO AUDIO DRIVER`.
9. Whether the first `speaker-test -D hw:DDJ1000,0 -c 6 -r 44100 -F S24_3LE -t sine -f 440 -l 1 -b 20000 -p 10000 -S 60` run succeeds or fails.
10. Any kernel log lines around `snd_usb_audio`, implicit-feedback pacing, or immediate playback errors.

For useful bug reports, ask external testers to paste the exact failing command, the exact error text, and whether they are using a native Linux machine, dual-boot install, or separate Linux SSD.

## Windows-First Machine Note

If your current trusted setup is a Windows capture machine, avoid treating dual-boot as the default requirement for this repo.

Use dual-boot only if that machine is the one you must validate on. In that case, keep full backups and avoid overwriting the current Windows disk layout unless you are prepared to repair the bootloader.

For that specific case, a second disk is preferable to an in-place repartition of the current Windows test machine.