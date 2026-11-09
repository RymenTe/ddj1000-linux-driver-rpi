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

## 2026-11-07 (22:06–22:16) – „NO AUDIO DRIVER“ gelöst: Vendor-Read 0xC0/0x00 wIndex 0x8003

- Mixxx mit Heartbeat, aber ohne Handshake: Tasten/LEDs ok, Audio ok, DDJ sendet `11 02` 1×/s,
  Jog-Displays „NO AUDIO DRIVER“. → Ein neu einsetzender Heartbeat gilt dem DDJ als neue Host-Sitzung.
- Tests (Mixxx beendet, User schaut aufs Display):
  1. Unlock + Heartbeat 20 s → weiter NO AUDIO DRIVER
  2. + Audio-Stream (aplay 6 ch, frisches SET_INTERFACE) → weiter NO AUDIO DRIVER
  3. + alte Post-ACK-Startup-State-Nachrichten (35 Stk.) → weiter NO AUDIO DRIVER
  4. **Vendor-IN-Request `0xC0/0x00, wValue 0, wIndex 0x8003, 2 B`** (usbfs USBDEVFS_CONTROL, Device-Recipient,
     **kein** Interface-Claim, alle Treiber bleiben gebunden) → Antwort `00 00`, danach Unlock + Audio →
     **Ladebalken, dann „Pioneer DJ / rekordbox“** auf den Jog-Displays; bleibt auch ohne Heartbeat stehen.
- Unlock-Tool: `--driver-read` (USB-Knoten dynamisch per sysfs vom Rawmidi-Knoten), Unit nutzt es.
  Backup der alten Unit: `~/module-backups/20261107-2055-systemd/ddj1000-unlock@.service.v1`.
- Echter Replug 22:15: Read `00 00` → ACK nach 2,0 s → Ladebalken → „Pioneer DJ / rekordbox“ ✔, Audio ✔.
- Seed-Folge nach Power-up deterministisch (`000053dc`, `27045665`, dann `0daa421f`) – 1. Versuch scheitert reproduzierbar, 2. klappt.
- Beobachtung: nach jedem Stream-Ende `xhci_hcd: ERROR Transfer event for disabled endpoint slot 4 ep 4` (EP 0x82 IN,
  später Iso-Abschluss nach Alt 0). Bisher folgenlos – beobachten (vgl. xHCI-Tod 20:54).
- Nächster Schritt: Mixxx starten → bleibt „Pioneer DJ / rekordbox“ trotz neuem Mixxx-Heartbeat (`11 02`-Schleife)?

## 2026-11-07 (22:20–22:41) – Standalone-Betrieb erreicht ✅

- Mapping: `heartbeatEnabled: false` (beide `50 01`-Stellen in init abgesichert;
  Backup `…scriptsV0_9_9.js.backup-20261107-2221`). Vor Mixxx-Start Unlock-Dienst erneut gelaufen.
- Mixxx-Lauf: 5 s usbmon → 0× `50 01`, 0× `11 02`, 0× Handshake; EP 0x82 12 785 Pakete Status 0; Playback Running.
- **User-Rückmeldung:** Ladekreis weg, „Pioneer DJ / rekordbox“, Tasten/LEDs ok, **Ton klar und deutlich,
  Standalone-DJing möglich.** Noch ohne Funktion: FX-Pads, Beat Jump, Sync (Mapping-Arbeit).
- Gesichert: Snapshot `~/module-backups/20261107-2241-WORKING-standalone/` (Module srcversion `24BF8948…`/`AA59DD6A…`,
  /etc-Units, udev-Regeln, ALSA-Conf, mixxx.cfg, soundconfig.xml, Mapping). Mapping + Setup-Notizen jetzt im Repo
  unter `config/mixxx/`. CLAUDE.md-Fakten aktualisiert.
- Läuft noch: 30-min-Beobachtung ohne Heartbeat (`~/build-logs/mixxx-noheartbeat-*.log`).

**Nächste Schritte**
1. Ergebnis 30-min-Beobachtung auswerten; danach Langzeit (> 1 h DJ-Session) ohne Heartbeat.
2. Mapping: FX-Pads, Beat Jump, Sync.
3. Reboot-Test der ganzen Kette (udev-Unlock beim Booten vor Mixxx-Autostart).
4. Aufräumen: altes `ddj1000-unlock.service`, `ddj1000-usb-probe.py`/`ddj1000-audio-stream.py`-Pfad, uncommittete
   Änderungen an `prepare-…-module.sh`/`install-…-stack.sh` prüfen; Install-Skript auf neue Units/Regeln umstellen;
   Unlock-Tool von `scripts/dev/` nach `scripts/runtime/` übernehmen.
5. Optional robust: snd-usbmidi-lib so ändern, dass SysEx nicht über zwei URBs verteilt wird (Mixxx-Handshake + Heartbeat).

## 2026-11-07 (22:24–22:55) – 30 min ohne Heartbeat stabil; Mapping: Filter, Beat FX, Sync

- 30-min-Beobachtung mit Mixxx, Heartbeat aus (`~/build-logs/mixxx-noheartbeat-222425.log`):
  **0× `11 02`**, Stream alle 5 min `Running`, keine Kernel-Fehler. User: Ton klar, Standalone-DJing möglich.
- Fehlende Funktionen: Mapping v0.9.9 hat **keine** Einträge für Filter, Beat FX, Beat Jump; „Sync“ war `sync_key` (Tonart).
- Gemessen per usbmon (`~/build-logs/midi-controls2-225010.txt`):
  Filter CH1 `B6 17/37`, CH2 `B6 18/38` (14 bit) · Beat FX CH-Wahl `94 10…16`, physische Reihenfolge
  `14-13-11-10-12-15-16` · Beat FX Auswahl `94 20/21/22` (3-Phasen) · LEVEL/DEPTH `B4 02/22` · ON/OFF `94 47` ·
  Sync D1 `90 58` · Sound Color FX `96 00…03` · unklar: Beat Jump (`90 20`?), `90/93 55↔56`, FX Release.
- Mapping ergänzt (Backup `~/.mixxx/controllers/*.backup-20261107-2254`): Filter CH1–4 → QuickEffect super1
  (CH3/4 `19/39`, `1A/3A` nach Muster, ungeprüft), LEVEL → EffectUnit1 mix, ON/OFF → Unit1 Effect1 enabled (+LED),
  Auswahl → next/prev_effect, Sync D1–4 `9x 58` → sync_enabled (+LED). Wirksam nach Mixxx-Neustart.
- Beat FX Kanal-Wahl (User: im Uhrzeigersinn SP MIC 3 1 2 4 MASTER; gemessen 14-13-11-10-12-15-16 → rückwärts):
  `94 10`=CH1 `11`=CH2 `12`=CH3 `13`=CH4 `14`=MASTER `15`=MIC `16`=SP → EffectUnit1 exklusiv routen.
  FX RELEASE = Beat FX ON/OFF (`94 47`, schon gemappt). Beat Jump sitzt im Pad-Modus (Hotcue-Pads) → separat messen.
- Push: Pi 4 → Fork `RymenTe/ddj1000-linux-driver-rpi` Branch `rpi4` (Merge statt Force, Fork-Commits bleiben);
  beide rpi-Patches (6.12/6.18) ebenfalls auf 12 ch Capture. Pi 5 später (RP1 statt VL805, ungetestet).

## 2026-11-08 (00:00–01:20) – Mapping-Ausbau in `DDJ-1000test.midi.xml`, Pioneered-Skin

Arbeitsweise: MIDI parallel zu Mixxx per `aseqdump -p 20:0` (ALSA-Seq, kein Rawmidi-FD) mitgeschnitten
(`~/build-logs/midi-capture-20261108*.log`); Mixxx-Verhalten per `print()`-Diagnose in `~/.mixxx/mixxx.log`.
Alle Änderungen nur in der Testkonfiguration `DDJ-1000test.midi.xml` (+ gemeinsames JS). Backups
`~/.mixxx/controllers/*.backup-20261108-{0003,0018,0030,0050,0054,0116}`, Snapshot
`~/module-backups/20261108-0116-mapping-session/`.

Gemessen (neu):
- Sound Color FX `96 00–03` (DUB ECHO, PITCH, NOISE, FILTER); DDJ macht die Radio-Auswahl selbst:
  Druck = `86 alt` (echter Note-off) + `96 neu`; leuchtende Taste erneut = nur `86`.
- Beat FX CH-Wahl `94 10–16` je Raste `84 alt` + `94 neu`; Status-Dump beim Mapping-Laden meldet Stellung.
- Pads: PAD FX1 `97 10–17`, PAD FX2 `97 50–57`, Beat Jump `97 20–27` (PAGE ▶: `28–2F`), Sampler `97 30–37`.
  Pad-Modus-Tasten `90 1B/1E/20/22/6B` (DDJ-intern, kein Mapping nötig).
- Crossfader `B6 1F/3F` (14 bit). Shift+BEAT SYNC `90/91 5C`. Browse: Push = LOAD `96 46–49`,
  Shift+Push `96 6D`, BACK `96 65`, Shift+BACK `96 66`, VIEW `96 7A`, Shift+VIEW `96 68`.
- Unbelegt gesehen: `B6 08/09/0C/0D` (Kopfhörer/Sampler-Regler?), `94 2B/2C/4A/4B/66/6B`, `90 16/17/40/5F`, `96 63`.

Ursachen / Fixes:
- Quick-Effect- **und** normale Chain-Preset-Listen haben bei Index 0 das leere Preset „---“ → Indizes =
  Position in `effects.xml` + 1 (per Parameter-Fingerprint bestätigt: 3=Loudness, 6=Echoverb HP, 14=Echo).
- Loop-LED blieb an: `LoopSetFeedbackCH1–4` sendete immer `0x7F`.
- Pioneered-Skin setzt `num_decks=2` → Deck 3/4 fehlen → Output-Warnung, `init` bricht bei `[Channel3] VuMeter` ab
  und das Script ist danach gestört („Invalid script function colorKnob“). Fix: Skin-Kopie
  `~/.mixxx/skins/Pioneered-4Deck` mit `[App],num_decks=4` (Patch im Repo: `config/mixxx/skins/`).
- Pioneered zeigt Track-Liste **oder** Ordnerbaum (`[Sidebar],sidebar_visible`) → BACK fokussierte einen
  unsichtbaren Baum. Fix (ungetestet): `sidebar_visible` folgt `[Library],focused_widget`.

Mapping-Stand (User: „funktioniert jetzt alles relativ fein“): Pitch-Richtung Pioneer (oben −), 4-Beat-Loop
CH1–4 + LED, Beat Jump ¼/½/1/2 (Seite 2: 4/8/16/32) alle Decks, Color FX Dub Echo/Noise/Filter (Pitch entfernt –
Pitch Shift destabilisierte Audio), Color-Regler per Script (12 Uhr = aus), PAD FX1 6–8 Censor/Spinback/Brake,
PAD FX2 Loop-Roll 1/16–8, Crossfader, Shift+Sync = Sync-Leader, VIEW/BACK/Push-Browse.

Offen → siehe `docs/BRIEFING-next-session.md`.

## 2026-11-08 (12:50–15:40) – PAD FX nach rekordbox-Standard, Loops alle Decks, Beat FX → Hardware

- Mixxx startet jetzt mit `--log-flush-level debug` (`~/.config/sway/config:247`, `~/.config/waybar/mixxx.sh`),
  sonst landen `print()`-Zeilen erst beim Beenden im Log (32-KB-Puffer).
- PAD FX1 stumm/zu laut: (1) Effekt-Slots von Unit 2 standen auf `enabled=0`; (2) super1→meta→Parameter-Links
  bewegten die Parameter nicht (Reverb blieb bei Send 0, Noise bei 1). Lösung: eigene Chain-Presets
  `PadFX …` mit festen Werten, ohne Links (`config/mixxx/effects/chains/`, in `effects.xml` nur bei beendetem Mixxx
  eintragen, Index = Listenposition + 1). Belegung = rekordbox-Standard: Roll 1/2, Sweep, Flanger 16, V.Brake 3/4,
  Echo 1/4, Echo 1/2, Reverb 50, Echo 1/2 lang. User: „Sehr geil, geht alles.“
- Loop IN/OUT (Halbieren/Verdoppeln bei aktivem Loop) für Deck 1–4; 4-BEAT-LOOP beendet jeden aktiven Loop;
  Beat Loop (Shift+Beat Jump) `97/99/9B/9D 60–67` (Noten angenommen, Diagnose `DDJ-1000 BeatLoop`).
- Beat FX: wirkte nur auf MST. Ursache: DDJ-1000 im Internal Mode – Hardware-Beat-FX nur im Master-Weg
  (`USB: MASTER OUT` läuft vor BEAT FX MASTER), Kanalzüge bekommen nur Line/Phono. Software-Versuch in Mixxx
  (Unit 1) hatte zusätzlich Autopan geladen. **Mixxx-Beat-FX-Mapping zurückgebaut** (Unit 1 wird beim Init
  ausgeschaltet); Hardware macht Beat FX auf MST. Details: `docs/research-jog-display-and-hw-mixer.md`.
- Backups: `~/.mixxx/controllers/*.backup-20261108-{1254,1305,1330,1419,1532}`,
  `~/.mixxx/effects.xml.backup-20261108-133122`, `~/.config/{sway/config,waybar/mixxx.sh}.backup-20261108-1305`.

## 2026-11-09 (13:20–13:45) – Jog-Display: Cue-Marker, Key, Sync, Tempo

- Quelle: offizielles PDF „DDJ-1000RB – MIDI Messages“ (pestrela/ddj), S. 8; Key-Tabelle (*3) nur als Bild →
  ausgelesen, in `docs/research-jog-display-and-hw-mixer.md` übernommen.
- Script: Cue-Marker `Bn 17/37` (Main-Cue, ausblenden `7F/7F`), Key `9n 49` + Variation `9n 4A` (`key`/`pitch_adjust`),
  Sync `9n 59/5A`; Tempo `Bn 16/36` aus `bpm/file_bpm` (negative Werte wurden wie positive gesendet);
  Positionsbalken aus voller Zeit (vorher 180°-Sprung je Minute). Backup `…scriptsV0_9_9.js.backup-20261109-1327`.
- Mixxx lädt das Script beim Speichern selbst neu; ein Zwischenstand beim Editieren erzeugte kurz
  „JogDisplayConnect is not a function“ – letzter Ladevorgang fehlerfrei.
- User-Test: „geht alles“. Kleine Abweichung der Tempo-%-Anzeige an den Pitch-Enden zwischen Mixxx und Display.
- `rpi4` per Worktree-Cherry-Pick auf `9ffbf0f` (3 Commits vor `fork/rpi4`), Push durch User.

## 2026-11-09 (13:45–14:30) – Crossfader-Assign, HID-Display dekodiert und unter Linux angezeigt

- Crossfader-Assign-Schalter `9n 16/1D/18` → `orientation` 0/1/2, vom User bestätigt (`674ee3f`).
- User bestätigt: Browse im Pioneered-Skin, Deck 1/2 gleich belegt, Beat Loop (Shift+Beat Jump).
- Zweiter rekordbox-Mitschnitt (`~/ddj1000-captures/windows-rekordbox-20261109/`, DDJ = Gerät 7): HID-OUT
  dekodiert – `0x2c` Waveform (600 × 7 B, RGB565-Paar + 2 Höhen), `0x2f` Beatgrid (ms), `0x30/0x2d` Länge,
  `0x21` Status (Position, Key). `03 01` = Status-Dump-Anforderung.
- Display-Test: Stufe 1 (nur hidraw) und Stufe 2 (+ MIDI-Init, ohne Heartbeat) ohne Anzeige; **Stufe 3 (Heartbeat
  + eigener Unlock + Init + Upload) zeigt den Track farbig wie in rekordbox.**
- Nächster Schritt: eingrenzen, was nötig ist (Heartbeat vs. frischer Unlock); dann Generator für eigene
  Tracks (Waveform/Beatgrid aus Mixxx) und Dienst-Architektur (ein Rawmidi-FD für Unlock + Heartbeat + Display).

## 2026-11-09 (14:15–15:40) – Mindestbedingung Display, Brückendienst Schritt 1

- T1/T2: rekordbox-Init unnötig; Display braucht dauerhaften Heartbeat (ohne ihn nach ~1 s „Pioneer DJ“).
- Weg A gewählt (User): `scripts/runtime/ddj1000-bridge.py` – Unlock + Heartbeat + MIDI-Weiterleitung über
  snd-virmidi (temporär geladen, Karte 7). rtmidi-Variante verworfen (Eingangsthread stirbt beim Mixxx-Start).
- `python3-rtmidi` per apt installiert (nur noch für Tests genutzt).
- Mixxx-Konfiguration: Controller „VirMIDI 7-0“ = DDJ-1000test, „DDJ-1000 MIDI 1“ und DDJ-HID aus.
  Backups `~/.mixxx/mixxx.cfg.backup-20261109-{1424,1534}`.
- User: Grundfunktionen, LEDs, VU, Pads und Pad-Modus-Wechsel laufen; Jog-Displays zeigen „rekordbox“ +
  Ladekringel (MIDI-Anzeige wird in diesem Modus ignoriert).
- Offen: Schritt 2 (HID-Display aus der Brücke), snd-virmidi dauerhaft laden (`/etc/modules-load.d`, Freigabe
  nötig), systemd-Dienst statt `ddj1000-unlock@`, Mixxx-Jog-MIDI-Ausgabe abschalten (unnötige Last).

## 2026-11-09 (19:10–19:30) – Reboot-Test Autostart bestanden, rpi4 in main gemergt

- Erwartete Sequenz nach Reboot: `ddj1000-module-check` ok → snd-virmidi Karte 7 → udev startet
  `ddj1000-bridge@midiC3D0` → 1. Unlock scheitert, 2. nach 2 s `15 02 ACK` → `/run/ddj1000/unlocked` →
  `mixxx-after-ddj1000` startet Mixxx auf „VirMIDI 7-0“ (Mapping DDJ-1000, Skin Pioneered-4Deck).
- Echt: genau so (Journal `-t ddj1000-bridge`), `Implicit Feedback Mode: Yes`, Playback Running,
  Track-Uploads mit Waveform/Beatgrid/Hot Cues auf die Jog-Displays. User: Hardware „alles ok“.
- Unkritisch: 32× „VirMIDI 7-0 not open for output“ beim Mapping-Init (gleich mit direktem Port, ältere
  Logs); udev-Warnungen aus Alt-Regeln außerhalb des Repos (`/etc/udev/rules.d/99-ddj1000.rules` Tippfehler
  `ATTRES`, `91-ddj1000.rules` setzt `ATTR{id}` auf jedem Unterknoten).
- Cherry-Pick der Autostart-Commits nach `main` scheiterte (Pi-Schicht des Forks fehlte) → User-Entscheidung:
  `rpi4` in `main` mergen. Konflikte nur durch doppelte Cherry-Picks; `main` hatte nichts Eigenes →
  `rpi4`-Fassung übernommen, `DDJ-1000test.midi.xml` entfällt. Baum `main` = `rpi4`, `validate-repo.py` grün.
- Nächster Schritt: User pusht `rpi4`; danach Alt-udev-Regeln aufräumen (Freigabe), Langzeittest > 1 h,
  offene Display-Punkte (Deck-Umschaltung 1↔3/2↔4, Beat FX).
