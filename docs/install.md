# DDJ-1000 Install And Host Stack

This document describes the first installable Linux host-stack layer for the
DDJ-1000 Linux bring-up work in this repository.

## Goal

Expose the current validated DDJ-1000 Linux fallback as normal host-facing
audio endpoints instead of only a raw 6-channel PCM.

Current bus model:

- `1/2` = `Master/Program`
- `3/4` = `Cue/Monitor`
- `5/6` = unresolved third playback target, with `Sampler/Aux` as a plausible
  working hypothesis

## What the first host-stack layer installs

System-wide ALSA PCM names:

- `ddj1000_master`
- `ddj1000_cue`
- `ddj1000_aux`

These names map stereo playback into the current 6-channel DDJ-1000 fallback
PCM `hw:DDJ1000,0`.

User-level session services:

- `ddj1000-host-stack.service`
- `ddj1000-unlock.service`

System-level recovery helper:

- `ddj1000-audio-rebind.path`
- `ddj1000-audio-rebind.service`

When `pactl` is available, the host-stack service creates a named desktop sink
for the DDJ master path.

The desktop-visible sink now uses a distinct DDJ name instead of appearing as a
generic `DDJ-1000` device:

- `DDJ1000-Master-1-2`

The `Cue` and `Aux` paths still exist, but currently only as direct ALSA PCMs:

- `ddj1000_cue`
- `ddj1000_aux`

Current Linux finding: the three routed DDJ stereo paths share one exclusive
hardware endpoint. `module-alsa-sink` can therefore keep only one of them open
at a time. Exporting all three as parallel desktop sinks is not stable today,
so the host-stack exposes only `Master` through PipeWire/Pulse and leaves
`Cue/Aux` as explicit ALSA targets.

The unlock service keeps the validated DDJ session-unlock path alive on Linux.
It uses the already verified USB-MIDI sequence:

- `50 01` keepalive from host
- `11 02` ready reply from the DDJ
- fixed `12 2A` unlock request
- live `13 2A` challenge from the DDJ
- dynamic `14 38` response calculated from the current `SeedE`
- `15 02` acknowledgement from the DDJ

The unlock service now also installs and uses a small device-specific startup-prep
bundle under `/usr/local/lib/ddj1000-linux-driver`:

- best-effort DDJ plug-control reads on interface `3`
- a short interface-`0` silence stream generated at runtime from the current
  built-in default payload shape
- a best-effort system audio rebind trigger plus desktop-sink restart

Current verified order in the Linux service is:

- run plug-control prep reads
- complete the live MIDI unlock path through `15 02`
- run only a short device-specific interface-`0` silence burst
- stop the desktop sink, request the system audio rebind helper, and then recreate the `DDJ1000-Master-1-2` sink

This replaces the earlier desktop-audio `paplay` workaround and keeps the stack
aligned with the previously validated DDJ startup findings.

This is the missing layer between "Linux can already play audio through the
DDJ" and "the controller itself stops showing `NO AUDIO DRIVER`".

Current live state after this update: the DDJ clears `NO AUDIO DRIVER`, the
Master path returns as `DDJ1000-Master-1-2`, and the direct ALSA PCM
`ddj1000_master` is present again after the unlock flow.

## Install

There are now two levels of installation.

### Full Linux stack

Install udev, the DDJ-1000 audio-driver override, and the host-stack layer in
one flow:

```bash
bash scripts/install-ddj1000-linux-stack.sh install
```

Check the combined status:

```bash
bash scripts/install-ddj1000-linux-stack.sh status
```

Remove the combined stack again:

```bash
bash scripts/install-ddj1000-linux-stack.sh uninstall
```

### Host-stack layer only

If the patched DDJ-1000 audio path is already available first, install only the
ALSA plus user-service layer:

```bash
bash scripts/install-ddj1000-host-stack.sh install
```

Check status:

```bash
bash scripts/install-ddj1000-host-stack.sh status
```

Remove it again:

```bash
bash scripts/install-ddj1000-host-stack.sh uninstall
```

### Optional desktop dependency install

The desktop sink helper uses `pactl` when available. On Debian or Ubuntu style
systems you can install the extra host-stack desktop tools with:

```bash
bash scripts/setup-linux.sh install-host-stack-packages
```

## Current scope

This is an early host-stack step, not a finished end-user Linux package yet.

It intentionally does not try to solve all remaining DDJ-1000 questions:

- automatic DKMS packaging for the kernel quirk
- Secure Boot enrollment flow automation beyond the current local MOK flow
- perfect PipeWire integration on machines without `pactl`
- final naming and confirmation of the `5/6` bus

The session-unlock path is now part of the stack, but it is still based on the
current validated MIDI semantics and not yet on a standalone udev-triggered
system service. Today it starts as a user service and follows the DDJ MIDI port
when it appears.

## Intended follow-up

- add DKMS-style installation for the patched audio module
- add richer PipeWire or WirePlumber integration
- move the DDJ unlock keepalive from user-session startup closer to hotplug
- expose `Master`, `Cue`, and later possibly `Sampler/Aux` as regular desktop
  outputs for applications like Spotify or browsers