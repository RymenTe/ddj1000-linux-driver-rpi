# Mixxx 2.5.3 setup for the DDJ-1000 (Raspberry Pi, standalone)

Copy to `~/.mixxx/` while Mixxx is **not** running (Mixxx rewrites its config on exit):

```bash
cp controllers/Pioneer-DDJ_1000-scriptsV0_9_9.js controllers/DDJ-1000.midi.xml ~/.mixxx/controllers/
```

- **MIDI controller:** "DDJ-1000 MIDI 1" with `DDJ-1000.midi.xml`
  (`mixxx.cfg`: `[ControllerPreset] DDJ-1000_MIDI_1 …/DDJ-1000.midi.xml`, `[Controller] DDJ-1000_MIDI_1 1`).
- **Sound hardware:** one device `DDJ-1000: USB Audio`, Master = channels 1/2, Headphones = channels 3/4
  (see `soundconfig.xml.example`). Do **not** use the separate `ddj1000_master`/`ddj1000_cue` PCMs:
  the hw device is exclusive, the second open fails with "Device unavailable".

## Unlock / heartbeat behaviour of the mapping

The DDJ is unlocked **before** Mixxx by `ddj1000-unlock@.service` (udev): vendor driver-presence read
(`0xC0/0x00, wIndex 0x8003`) → MIDI challenge-response over one rawmidi FD → port released.

In the mapping (`PioneerDDJ1000Unlock`):

- `handshakeEnabled: false` – Mixxx cannot complete the handshake: PortMidi/ALSA-seq/snd-usbmidi split the
  66-byte `14 38` response into two USB transfers, and the DDJ only accepts it in one.
- `heartbeatEnabled: false` – any (re)starting `50 01` heartbeat makes the DDJ open a new host session and
  wait for a handshake (`11 02` every second, spinner on the jog screens). Without heartbeat the session from
  the udev service is kept.
- `PioneerDDJ1000.incomingData` routes SysEx to `handleSysex` (Mixxx never uses the XML `0xF0` binding for SysEx).

See `docs/session-log.md` (2026-11-07) for the measurements behind this.
