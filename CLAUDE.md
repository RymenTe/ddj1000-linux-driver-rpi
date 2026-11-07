# CLAUDE.md – DDJ-1000 Linux-Treiber auf MixxxPi

Diese Datei liest Claude Code beim Start automatisch. Sie beschreibt das System, die harten Grenzen
und wie hier gearbeitet wird. Bitte vor jeder Änderung an Treiber-, MIDI- oder Audio-Code beachten.

## Ziel
Pioneer DDJ-1000 (USB `2b73:0020`) läuft standalone am Raspberry Pi mit Mixxx 2.5.3:
Unlock-Handshake → ALSA-Stream → Rebind → saubere 8ch-Ausgabe ohne dumpfen Klang.

## System
- Host: `pi@mixxxpi` (192.168.178.99), Kernel `6.12.34+rpt-rpi-v8`
- Kernel-Source: `~/rpi-linux/` (Branch `rpi-6.12.y`), relevante Dateien in `sound/usb/`:
  `quirks-table.h`, `quirks.c`, `implicit.c`, `endpoint.c`, `pcm.c`
- Installiertes Modul: `/lib/modules/6.12.34+rpt-rpi-v8/kernel/sound/usb/snd-usb-audio.ko.xz`
- Treiber-Repo: `~/ddj1000-linux-driver/` (Fork `RymenTe/ddj1000-linux-driver-rpi`, Branch `rpi4`)
- Dienste: `ddj1000-unlock.service`, `ddj1000-audio-rebind.service/.path`, `ddj1000-host-stack.service`
- Mixxx-Mapping: `~/.mixxx/controllers/Pioneer-DDJ_1000-scriptsV0_9_9.js`, `DDJ-1000.midi.xml`

## Harte Regeln (nicht verhandelbar)
1. **Vor jeder Änderung an Modul oder Kernel-Source ein Backup** anlegen
   (`*.backup-YYYYMMDD-HHMM`), und den Backup-Pfad im Chat nennen.
2. **Niemals** `snd_usb_audio.lowlatency=0` in `cmdline.txt` – zerstört die Geräteerkennung.
3. `cmdline.txt`, `config.txt`, Bootloader, `/boot/*`: **nur mit ausdrücklicher Freigabe** ändern.
4. Rawmidi ist exklusiv pro FD: **ein** `os.open(O_RDWR)`-FD für Lesen und Schreiben,
   nie zwei Prozesse (`amidi`) parallel am selben Port.
5. Mit vorgeladenem `snd-usb-audio` kann libusb Interface 0 nicht claimen →
   Silence-Stream immer über ALSA/`aplay`, nicht libusb.
6. ALSA-Kartennummern nie hart codieren → dynamisch über `aplay -l` / `/proc/asound/cards`.
   MIDI-Port explizit übergeben (`--midi-port hw:X,0,0`, dynamisch ermittelt).
7. Bei Symbol-CRC-Fehlern immer `snd-usb-audio.ko` **und** `snd-usbmidi-lib.ko` zusammen bauen.
8. Kein `--force`, kein `git push` ohne Freigabe. Commits klein und beschreibend.

## Bekannte technische Fakten
- Unlock: proprietärer MIDI-Challenge-Response (FNV1a32, Secret `0x680131FB`).
  Erwartete Folge: `11 02` (ready) → `13 2a` (Challenge vom Gerät) → Antwort → `15 02` (ACK).
  Ohne Unlock kein DSP/Audio-Routing.
- SysEx-Heartbeat `F0 00 40 05 00 00 02 00 00 50 01 F7` alle 200 ms hält den DSP aktiv.
- Klang dumpf = fehlendes Implicit Feedback über EP 0x82.
  Erfolgskriterium: `Implicit Feedback Mode: Yes` in `/proc/asound/card*/stream0`.
- `QUIRK_DATA_COMPOSITE` umgeht den normalen Implicit-FB-Parsing-Pfad.

## Arbeitsweise
- Subsysteme **einzeln** testen (Audio-Stream, Rawmidi, Rebind), erst dann integrieren.
- Vor jedem Test die **erwartete Log-Sequenz** aufschreiben, danach mit der echten vergleichen.
- Logs als Wahrheit: `journalctl -u <dienst> -b --no-pager`, `dmesg -T | tail -100`,
  `cat /proc/asound/card*/stream0`, `aplay -l`, `amidi -l`, `lsusb -t`.
- Lange Builds im Hintergrund laufen lassen und Log in Datei schreiben
  (`make ... 2>&1 | tee ~/build-logs/<name>.log`).
- Erkenntnisse am Ende einer Sitzung in `docs/session-log.md` festhalten
  (Datum, was getestet, Ergebnis, nächster Schritt).

## Nützliche Befehle
```bash
# Modul neu laden (DDJ vorher abstecken oder Dienste stoppen)
sudo systemctl stop ddj1000-unlock.service ddj1000-audio-rebind.service
sudo modprobe -r snd-usb-audio && sudo modprobe snd-usb-audio
# Status prüfen
cat /proc/asound/cards; aplay -l; amidi -l
grep -A3 "Implicit" /proc/asound/card*/stream0
journalctl -u ddj1000-unlock.service -b -f
```
