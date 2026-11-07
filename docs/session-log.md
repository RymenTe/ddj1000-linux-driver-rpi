# Session-Log

## 2026-11-07 – Modul-Basis repariert (Version-Mismatch)

**Ist-Stand vorher**
- Keine DDJ-Karte in `aplay -l`, `amidi -l` leer, kein `stream0`.
- dmesg: `WARNING ... module_put` in `do_init_module` + 15× aus `snd_ctl_release`;
  `USB device is in the shutdown state, cannot create a card instance`, `probe ... failed with error -5`.
- `lsmod`: Refcount von `snd_usb_audio` negativ (`-667300243`).
- `ddj1000-unlock.service` nie gestartet: systemd hat den Job wegen Ordering-Cycle
  (`ddj1000-usb-probe.service` mit `After=multi-user.target` + `WantedBy=multi-user.target`) gelöscht.
- `ddj1000-usb-probe.service` failed (libusb an Interface 0, verstößt gegen Regel 5).

**Ursache**
- Geladenes Modul (srcversion `857BA36…`) = `~/rpi-linux/sound/usb/snd-usb-audio.ko`:
  `.c`-Quellen aus **6.12.85** (`rpi-6.12.y` HEAD), gebaut gegen Headers **6.12.34**.
- Zusätzlich: `kernel/sound/usb/snd-usbmidi-lib.ko.xz` aus dem Paket fehlte, ersetzt durch Fremd-Build.
- Neuere Builds in `updates/ddj1000-linux-driver/` waren nicht in `modules.dep` (depmod lief nicht).

**Was gemacht wurde**
- Exakten Quell-Commit des laufenden Kernels aus dem Debian-Changelog ermittelt:
  `8f77e03530f65209a377d25023e912b288e039cd` (linux 1:6.12.34-1+rpt1~bookworm).
- Nur `sound/usb` davon per Sparse-Checkout nach `~/kernel-src/rpi-6.12.34-8f77e03/`.
- Gegenprobe: unveränderter Build → srcversion `48C37CC…` = Paket-Original. Quellen passen.
- `patches/linux/snd-usb-audio-ddj1000-composite-quirk.patch` mit `-p2` auf Kopie
  `~/kernel-src/build-ddj/` angewendet (quirks-table.h Fuzz 2, Position manuell geprüft),
  Build ohne Warnungen (`~/build-logs/ddj-6.12.34.log`).
  - `snd-usb-audio.ko` srcversion `A737B3875F7797F71B2717D`
  - `snd-usbmidi-lib.ko` srcversion `AA59DD6A9357B086610D8E7` (unverändert)
- Backup: `~/module-backups/20261107-2044/` (kernel/sound/usb, updates/ddj1000-linux-driver, modules.dep/.alias).
- `kernel/sound/usb/` auf Paketzustand (Originale aus dem .deb), `dpkg --verify` sauber.
- Neue Module nur in `updates/ddj1000-linux-driver/`, `depmod -a`. `modinfo -n` zeigt auf `updates/`.
- Initramfs enthält kein snd-usb-audio → `/boot` unverändert.

**Erwartung nach Reboot**
- Kein `module_put`-WARNING, Refcount von `snd_usb_audio` klein und positiv.
- `cat /sys/module/snd_usb_audio/srcversion` = `A737B3875F7797F71B2717D`.
- DDJ-1000 in `aplay -l`, `amidi -l` zeigt `hw:X,0,0`.
- `/proc/asound/cardX/stream0`: `Implicit Feedback Mode: Yes`.
- Unlock startet weiterhin **nicht** (Ordering-Cycle) – beabsichtigt, Audio wird isoliert getestet.

**Nächste Schritte**
1. Nach Reboot obige Erwartung gegen echte Logs prüfen.
2. Dienst-Graph: `ddj1000-usb-probe.service` aus Abhängigkeit von `unlock` entfernen, Cycle auflösen,
   Trigger per udev/`BindsTo=` auf das DDJ-Device; Status von `ddj1000-host-stack.service` klären.
3. Unlock isoliert testen (`11 02` → `13 2a` → Antwort → `15 02`).
4. Implicit FB: statischer Quirk vs. DDJ-800-Variante (Parser + `is_pioneer_implicit_fb`) A/B.
5. Kanalzahl (Quirk: 6) gegen `wMaxPacketSize` von EP 0x01/0x82 prüfen (Ziel 8ch).
6. `prepare-ddj1000-snd-usb-audio-module.sh` auf den 6.12.34-Commit-Sparse-Checkout umstellen,
   damit nie wieder gegen fremde Kernel-Quellen gebaut wird.

## 2026-11-07 – Nach Reboot: Modul ok, Karte fehlt wegen libusb-Probe

**Geprüft (Boot 20:50)**
- `snd_usb_audio` srcversion `A737B3875F7797F71B2717D`, `snd_usbmidi_lib` `AA59DD6A…` ✔
- Kein `module_put`-WARNING, Refcount 0 ✔ → Modul-Basis aus voriger Sitzung bestätigt.
- ✘ Keine DDJ-Karte: `usb 1-1.1.2: USB device is in the shutdown state` / `probe … failed with error -5`.

**Ursache**
- `ddj1000-unlock.service` (System-Unit, handgemacht, nicht aus Repo) hatte `Requires=ddj1000-usb-probe.service`.
  systemd löscht wegen Cycle nur den Unlock-Job; der Probe-Job läuft trotzdem.
- `ddj1000-usb-probe.py --interface 0 --alt-setting 1 --endpoint 0x82` claimt per libusb Interface 0
  → Kernel-Treiber detached → `chip->shutdown`; If 1/2 halten die Karte → Re-Probe von If 0 scheitert (-5).
  Zeitlich: xhci `TRB DMA ptr not part of current TD` 20:51:01, Probe-Fehler 20:51:03. (Regel 5!)
- 20:54:12 `USB disconnect` des DDJ + `xhci_hcd: Host System Error / Host halt failed -110`
  (Ursache offen: abgesteckt oder Geräte-Reset). Tastatur/Maus am selben Hub weiter da.

**Was gemacht wurde**
- Backup: `~/module-backups/20261107-2055-systemd/` (alle `ddj1000-*` System-Units).
- `ddj1000-usb-probe.service` entfernt und **maskiert** (→ /dev/null).
- `ddj1000-unlock.service`: `Requires=/After=ddj1000-usb-probe` raus, `After=sound.target`; Unit **disabled**
  (bis Audio isoliert verifiziert ist). Ordering-Cycle damit beseitigt.

**Nächste Schritte**
1. DDJ neu einstecken/einschalten → erwartet: Karte `DDJ1000` in `/proc/asound/cards`, `amidi -l` hw:X,0,0,
   `stream0` mit `Implicit Feedback Mode: Yes`. Falls xhci weiter hängt: Reboot.
2. Danach Unlock isoliert (`11 02` → `13 2a` → Antwort → `15 02`), dann Unit wieder enablen.
3. Offene Punkte 4–6 aus voriger Sitzung (Implicit-FB A/B, 8ch, prepare-Skript auf 6.12.34).

**Nachtrag 20:57 – xHCI tot**
- DDJ wieder eingesteckt → **kein** Kernel-Event; Controller seit 20:54:14 im `Host System Error`.
- xHCI-Rebind (`0000:01:00.0` unbind/bind) → `xHCI host controller not responding, assume dead`,
  `can't setup: -110`, `probe … failed -110`. VL805 nur per Reboot wiederherstellbar → Reboot.
- Verdacht: xhci-Fehler (`TRB DMA ptr not part of current TD ep_index 4`) stammen vom libusb-Iso-Probe auf
  EP 0x82 und haben den VL805 destabilisiert. Nach Reboot (ohne usb-probe) prüfen, ob die xhci-Fehler weg sind.

## 2026-11-07 (21:02–21:12) – Reboot ok, Unlock ok, Capture-Overflow gefunden und behoben

**Nach Reboot (ohne usb-probe)** – alle Erwartungen erfüllt
- Keine xhci-Fehler. DDJ jetzt an Port `1-1.4` (direkt am VIA-Hub). Karte 1 `DDJ1000`, MIDI `hw:1,0,0`,
  `stream0`: Playback 6 ch, Sync EP 0x82, `Implicit Feedback Mode: Yes`. Unlock-Unit disabled, usb-probe masked.

**Audio ohne Unlock**: `aplay`/`arecord` → EIO nach ~0,6 s (= ALSA-Timeout buffer·1100/rate, keine Daten).

**Unlock isoliert** – neues Tool `scripts/dev/ddj1000-unlock-test.py` (ein O_RDWR-FD, Heartbeat 200 ms,
kein libusb/Silence-Stream/Rebind; Protokoll-Logik importiert aus `ddj1000-unlock-service.py`).
- Sequenz exakt wie erwartet in 5 ms: `11 02` → Prelude + `12 2a` → `13 2a` (seedE) → `14 38` → `15 02` ACK.
  Danach sendet das DDJ den Controller-Status (CC/Notes). 126 Heartbeats fehlerfrei.
- ⚠ `ddj1000-unlock-service.py` verletzt Regel 4 (amidi -d + parallele amidi -S) und startet nach ACK
  `ddj1000-audio-stream.py` → `ddj1000-usb-probe.py` = libusb an If 0 (Regel 5, hat xHCI gekillt). Nicht mehr so verwenden.

**Audio nach Unlock**: weiterhin EIO, aber `retire_capture_urb: N callbacks suppressed`.
- usbmon: **jedes** IN-Paket auf EP 0x82 Status `-75` (EOVERFLOW); Kernel reservierte 306 B/Paket (17 × 18 B, 6 ch).
- Windows-Captures (audio-driver-notes): IN 3168/3204 B in 36-B-Blöcken → Capture ist **12 ch S24_3LE (36 B/Frame)**.

**Fix**: Capture-Eintrag im Quirk `.channels = 6` → `12` (Playback bleibt 6).
- Backup: `~/module-backups/20261107-2109-capture12ch/` (alte .ko, quirks-table.h, Patch).
- Build `~/build-logs/ddj-capture12ch.log`, keine Warnungen. `snd-usb-audio` srcversion `24BF8948BFC13B418CF2C2F`,
  `snd-usbmidi-lib` unverändert `AA59DD6A…`. Installiert nach `updates/ddj1000-linux-driver/`, depmod, Reload.
- Repo-Patch angepasst; Gegenprobe: Patch auf `rpi-6.12.34-8f77e03` ergibt byte-identische Build-Quellen.

**Ergebnis (mit Unlock + Heartbeat)**
- usbmon: 7490 IN-Pakete, alle Status 0, je **396 B = 11 Frames × 36 B** (= 44,1 kHz).
- `arecord -c 12` 2 s → 3 175 200 B (exakt 2 × 44100 × 36). `aplay -c 6` 3 s → rc 0, `Status: Running`.
- Kein „carried no payload“-Fallback mehr → echtes Implicit Feedback läuft.
- Capture-Inhalt: pro 12-B-Gruppe `[0, laut, leise, 0]`, Peaks identisch 0x161C00, nonzero = 4/11 bzw. 5/11 Frames/Paket
  → vermutlich strukturierte Daten, kein Audio (keine Eingänge angeschlossen). Slot-Belegung offen.

**Nächste Schritte**
1. Hörtest: `speaker-test -D hw:1,0 -c 6 -r 44100 -F S24_3LE -t sine -f 440 -s 1` bei laufendem Unlock-Test
   → Master 1/2 klar statt dumpf?
2. Unlock-Dienst neu aufsetzen: auf `ddj1000-unlock-test.py`-Logik (ein FD, 200 ms) umstellen, ohne libusb-Silence-Stream;
   Trigger per udev/`BindsTo=` aufs DDJ; MIDI-Port dynamisch. Danach Mixxx: Port-Konflikt (Rawmidi exklusiv!) klären –
   Heartbeat ggf. in Mixxx-Mapping statt separatem Prozess.
3. Capture-Slot-Belegung (12 ch) mit angeschlossener Quelle/Mic klären.
4. `prepare-ddj1000-snd-usb-audio-module.sh` auf den 6.12.34-Commit umstellen (offen).

**Hörtest 21:22–21:24** (Unlock-Testtool `--hold`, `speaker-test -D hw:1,0 -c 6 -r 44100 -F S24_3LE -t sine -f 440 -S 60`)
- Hinweis: `speaker-test -s` nutzt eigene Reihenfolge: `-s 1` = ALSA ch1 (Master L), `-s 3` = ch2 (Master R),
  `-s 2` = ch5 („Mitte“). Erster Versuch mit `-s 2` traf daher Paar 5/6.
- `-s 1` und `-s 3`: rc 0, keine Kernel-Fehler. **Ton am DDJ hörbar** (Rückmeldung User). Klangqualität (klar/dumpf) noch zu bestätigen.

## 2026-11-07 (21:25–21:38) – Unlock ohne Heartbeat stabil, udev-Oneshot-Unlock

- Nach Unlock + 1 s Heartbeat, danach **kein** Heartbeat: Audio (arecord -c 12 / aplay -c 6) ok bei
  5 s, 15 s, 35 s, 2 min, 5 min, 10 min. Passiver MIDI-Monitor 40 s: DDJ sendet von sich aus nichts.
  → DDJ bleibt ohne Heartbeat entsperrt; Unlock-Prozess kann den Port nach dem ACK freigeben.
- Mixxx-Mapping (`Pioneer-DDJ_1000-scriptsV0_9_9.js`) enthält bereits Unlock (handleSysex) + 200-ms-Heartbeat.
  MIDI-Controller in `mixxx.cfg` aber deaktiviert (`USB_Device_0x00:0x00_MIDI_1 0`, Name passt nicht zu „DDJ-1000 MIDI 1“).
- Neu: `config/udev/92-ddj1000-unlock.rules` + `config/systemd/system/ddj1000-unlock@.service`
  (udev → Oneshot `ddj1000-unlock-test.py --device /dev/snd/%I --hold 1`, User pi:audio, BindsTo Device).
  Installiert nach `/etc/udev/rules.d/` bzw. `/etc/systemd/system/`. Altes `ddj1000-unlock.service` bleibt disabled.
- Test per `udevadm trigger --action=add /dev/snd/midiC1D0`: Sequenz bis `15 02` ACK, Exit 0, Port frei, Audio ok.

**Nächste Schritte**
1. Echtes Ab-/Anstecken und Reboot testen (Unlock muss automatisch kommen).
2. Mixxx: MIDI-Controller „DDJ-1000 MIDI 1“ mit `DDJ-1000.midi.xml` aktivieren, Audio-Device hw:DDJ1000 (6 ch out),
   prüfen dass Mixxx nach dem Oneshot den Port bekommt und Heartbeat sendet.
3. Altes `ddj1000-unlock.service`, `ddj1000-usb-probe`-Pfad und `ddj1000-audio-stream.py`-Aufruf aufräumen.

**Echter Replug 21:46** (DDJ ab-/angesteckt)
- Kernel: disconnect 21:46:13, neu enumeriert 21:46:21 an `1-1.4`, Karte 1 mit 6 ch out / 12 ch in, Implicit FB Yes.
- udev → `ddj1000-unlock@midiC1D0` automatisch gestartet (21:46:21.8), **ACK nach 2,0 s**, Port frei, Exit 0.
- Audio danach ohne Zutun ok (arecord -c 12 / aplay -c 6 rc 0).
- Auffällig: 1. Versuch bekam **zwei** `13 2a` auf einen `12 2a` (seedE `000053dc` – identisch zum ersten
  Unlock nach dem Reboot, also vermutlich deterministischer Seed nach Power-up – und `27045665`); beide
  Antworten ohne ACK, Gerät meldet erneut `11 02`. 2. Versuch nach 2-s-Cooldown → ACK. Robust, aber Ursache offen.

## 2026-11-07 (21:49) – Mixxx-Konfiguration
- Mixxx-Log: `ddj1000_cue` → „Error opening stream: Device unavailable“ – master/cue sind zwei route-PCMs
  auf demselben exklusiven hw-Gerät → Kopfhörer lief in Mixxx nie.
- Neu: `pcm.ddj1000_6ch` (plug → `hw:DDJ1000,0`, 6 ch) in `config/alsa/60-ddj1000-host-stack.conf`, installiert;
  `speaker-test -D ddj1000_6ch` ok.
- Backup `~/module-backups/20261107-2149-mixxx/` (mixxx.cfg, soundconfig.xml, ALSA-Conf).
- `soundconfig.xml`: ein Gerät `ddj1000_6ch`, Master ch 1/2, Headphones ch 3/4.
- `mixxx.cfg`: Controller-Key `USB_Device_0x00:0x00_MIDI_1` → `DDJ-1000_MIDI_1` (Mixxx-Name „DDJ-1000 MIDI 1“), aktiviert.
- Offen: PortAudio-Index (7 eingetragen) – Mixxx-Log beim ersten Start prüfen.

**Erster Mixxx-Start 21:51**
- Mixxx fand `ddj1000_6ch` nicht (PortAudio listet die conf.d-PCMs hier nicht) und schrieb `soundconfig.xml` neu:
  `DDJ-1000: USB Audio` (hw:1,0) **nur Master** → Playback Running, EP 0x82 IN fehlerfrei 396 B. Kopfhörer fehlt noch.
- MIDI-Controller „DDJ-1000 MIDI 1“ geöffnet (PortMidi via ALSA-Seq → fuser zeigt nichts am midiC1D0), Mapping sendet
  bei init `handshake sent`, aber **kein ACK**; ~1/s `TypeError: Property 'incomingData' … is not a function`.
  Ursache: Mixxx liefert SysEx nur an `<prefix>.incomingData`, die XML-Bindung `<status>0xF0</status>` greift nicht.
- Fix im Mapping (Backup `Pioneer-DDJ_1000-scriptsV0_9_9.js.backup-20261107-2156`):
  `PioneerDDJ1000.incomingData = function(data, length) { PioneerDDJ1000.handleSysex(data, length); };` – `node --check` ok.
- Nächster Schritt: Mixxx neu starten → erwartet „challenge response sent“ + „ACK 15 02 received“, keine TypeErrors;
  Headphones (ch 3/4) im selben Gerät `DDJ-1000: USB Audio` ergänzen (nur bei beendetem Mixxx).

## 2026-11-07 (21:58–22:05) – Warum das Mixxx-Mapping kein ACK bekommt

- Mit `incomingData`-Fix: kein TypeError mehr, Mapping beantwortet `13 2a`, aber **nie `15 02`**; DDJ sendet `11 02` 1×/s.
- Binäres usbmon (`/dev/usbmon1`, MON_IOCX_GETX, ungekürzt): Mixxx-Antworten **byte-identisch** zur Python-Referenz.
  Rohe URBs: Antwort geht als **zwei Bulk-URBs** raus (21 Events/84 B + `07 09 00 f7`/4 B), keine Fremd-Events dazwischen.
- Variantentest (`/tmp`-Skript, ein FD; Log `~/build-logs/unlock-variants-2202*.log`, `-2203*.log`):
  Basis ✔ · Mixxx-Init-Block (`03 01`, `0B 31`, `0C 00`) + Handshake ohne `11 02` ✔ · Antwort +2 ms/+5 ms ✔ ·
  **Antwort in zwei Writes (63 + 3 B) ✘** – danach exakt das Mixxx-Bild (`11 02` 1×/s, jeder Retry scheitert).
- **Ursache:** DDJ-1000 akzeptiert `14 38` nur, wenn das ganze SysEx in **einem** USB-Transfer ankommt.
  PortMidi → ALSA-Seq → snd-usbmidi zerlegt es; aus dem JS-Mapping nicht steuerbar.
- Konsequenz: Unlock nur über `ddj1000-unlock@.service` (rawmidi, eine `os.write`). Mapping:
  `handshakeEnabled: false` → `sendHandshake()` ist No-op (Backup `…scriptsV0_9_9.js.backup-20261107-2204`);
  Heartbeat 200 ms bleibt. Nach dem letzten Variantentest ist das DDJ entsperrt (ACK).
- Offen: Mapping liegt nur in `~/.mixxx/controllers/`, nicht im Repo → versionieren.
  Möglicher Kernel-Fix später: snd-usbmidi-lib SysEx-Ende nicht in separatem URB senden (nur falls nötig).
