# Recherche: Jog-Display-Waveform und Hardware-Mixer/FX (Stand 2026-11-08)

Ziel für später ("All-in-One"): Built-in-Effekte des DDJ-1000 und Waveform auf den Jog-Displays nutzen.
Ergebnis kurz: **Hardware-FX pro USB-Kanal gibt es beim DDJ-1000 (rekordbox-Version) nicht**; Waveform
nur im (undokumentierten) HID-Modus. Zeit/BPM/Position/Key/Sync gehen dokumentiert über MIDI.

## 1. Audio-Weg im "Internal Mode" (DDJ-1000 = Software mischt)

Offizieller Signalfluss (Pioneer, gesammelt in [pestrela/ddj](https://github.com/pestrela/ddj),
`3 Signal flows/DDJ 1000 RB - Signal Flow - Internal mode.JPG`):

- Vom Rechner kommt Audio nur an zwei Stellen in die Hardware:
  - **`USB: MASTER OUT`** → Summenpunkt **vor BEAT FX MASTER** → Talk Over → Master/Booth.
  - **`USB: CUE CHx`** → Cue-Weg (Kopfhörer).
- Die Kanalzüge CH1–4 (TRIM → SOUND COLOR FX → BEAT FX CHx → EQ → Fader → Crossfader) bekommen nur
  **PHONO/LINE**. Für Line-Quellen gibt es `USB: FX SEND/RETURN` (Software kann FX für Line-Eingänge rechnen).
- Passt zu unseren Windows-Mitschnitten (`docs/audio-driver-notes.md`): rekordbox sendet auf EP 0x01 nur
  ein aktives Stereopaar → auch rekordbox mischt in Software und rechnet Kanal-FX selbst.

Mixxx-Wiki [ddj-1000](https://github.com/mixxxdj/mixxx/wiki/ddj-1000), Tabelle Hardware-FX:

| Setup             | ColorFX | BeatFX Kanal | BeatFX Master |
|-------------------|---------|--------------|---------------|
| 1000 + Software   | nein    | nein         | **ja**        |
| 1000 + Line-In    | ja      | ja           | ja            |
| 1000SRT + Software| ja      | ja           | ja            |

Folgen für uns:
- **Beat FX MST** = Hardware-DSP (LOW CUT ECHO usw., Name auf dem FX-Display) – funktioniert schon, ohne Mapping.
- **Beat FX CH1–4/MIC/SP** nur in Software (Mixxx Effect Unit), so wie rekordbox. Dabei **nie** auf `[Master]`
  routen (sonst doppelt mit der Hardware). Im MIDI-Modus kann Software das Beat-FX-Display nicht beschreiben
  (zeigt immer die Pioneer-Effekte), ON/OFF hat eine eigene Zustandsmaschine (jeder Druck = Toggle).
  Idee: Mixxx-Effektliste in Pioneer-Reihenfolge führen und der SELECT-Raste (94 20/21/22) folgen, damit das
  Display halbwegs passt; Startposition unbekannt (prüfen, ob der Status-Dump sie meldet).
- **Sound Color FX und Filter** bleiben in Software (Mixxx QuickEffect) – die Hardware wirkt nur auf Line-Eingänge.
  Unsere Mappings werden also nicht "überschrieben", es gibt nichts Doppeltes.
- Echtes Hardware-Kanalmischen über USB (pro Deck ein Stereopaar in die Kanalzüge) hat nur der **DDJ-1000SRT**
  (External Mode). Für den DDJ-1000 gibt es dafür keinen Hinweis (auch kein zweites Altsetting, s. audio-driver-notes).
- Offen: Rolle von Playback 5/6 (evtl. weiterer `USB: CUE CHx`-Weg?) und der 12 Capture-Kanäle
  (`USB: FX SEND CHx/MASTER/MIC`, `USB: MIX (REC OUT)`?) – mit `arecord -c 12` + Line-Quelle zuordnen.

## 2. Jog-Displays

### MIDI-Modus (dokumentiert, offizielles "DDJ-1000RB – MIDI Messages", S. 8, MIDI-OUT vom Rechner)

| Funktion            | Nachricht                       | Werte |
|---------------------|---------------------------------|-------|
| Positionsbalken     | `Bn 14` MSB / `Bn 34` LSB       | 0–359 Grad (max MSB 0x02, LSB 0x67) |
| BPM                 | `Bn 15` / `Bn 35`               | 0.0–999.9 (Zehntel, max 0x4E/0x0F) |
| Tempo (Playing speed)| `Bn 16` / `Bn 36`              | −100.0 … +100.0 % |
| Zeit Minuten        | `9n 42 hh`                      | 0–99 |
| Zeit Sekunden       | `9n 43 hh`                      | 0–59 |
| Zeitmodus           | `9n 44 hh`                      | Elapsed 0x00, Remaining 0x7F |
| Cue-Marker          | `Bn 17` / `Bn 37`               | 0–359 Grad, ausblenden 0x7F/0x7F |
| Key                 | `9n 49 hh`                      | 0x00–0x18 (Tabelle *3) |
| Key-Variation       | `9n 4A hh`                      | 0x01–0x0C = −12…−1, 0x0D = 0, 0x0E–0x19 = +1…+12 |
| Sync Master         | `9n 59 hh`                      | 0x00/0x7F |
| Sync State          | `9n 5A hh`                      | 0x00/0x7F |
| Jog-Ring-LED        | `9n 5B hh`                      | 0x00 aus, 0x01 weiß |
| Infos zeigen/verbergen | `9n 5D hh`                   | 0x00 zeigen, 0x7F verbergen |

Status im Script `Pioneer-DDJ_1000-scriptsV0_9_9.js` (seit 2026-11-09): Zeit (`42/43/44`), Position (`Bn 14`),
BPM (`Bn 15`), Tempo (`Bn 16`, jetzt aus `bpm/file_bpm`, negative Werte vorher falsch), Cue-Marker (`Bn 17`,
Main-Cue), Key/Key-Variation (`49/4A`, aus `key`/`pitch_adjust`), Sync Master/State (`59/5A`), Ring (`5B`),
Anzeige (`5D`). Tempo-Kodierung angenommen: 1000 = 0,0 %, 0,1-%-Schritte (Spezifikation nennt nur Min/Max).
Key-Tabelle (*3, nur als Bild im PDF): `00` = ---, dann je Dur + parallele Moll aufsteigend:
`01` C, `02` Am, `03` Db, `04` Bbm, `05` D, `06` Bm, `07` Eb, `08` Cm, `09` E, `0A` Dbm, `0B` F, `0C` Dm,
`0D` F#, `0E` Ebm, `0F` G, `10` Em, `11` Ab, `12` Fm, `13` A, `14` F#m, `15` Bb, `16` Gm, `17` B, `18` Abm.
Undokumentiert laut Wiki: "PC APP Connect" = Kanal 16, Note A-1 → DDJ meldet Fader-/Reglerstellungen.

### HID-Modus (Waveform, Cuescope, Cover, Tempo-Bereich)

- Laut Mixxx-Wiki nur im **HID-Modus** (rekordbox, VirtualDJ). Protokoll proprietär, **nicht öffentlich dokumentiert**.
- Gerät: Interface 3 = HID, EP 0x06 OUT / EP 0x87 IN, je 64 Byte (`lsusb -v -d 2b73:0020`).
- Im HID-Modus übernimmt die Software auch Beat-FX-Display, ON/OFF und Pad-Seiten.
- Vorgehen später: Windows + rekordbox mit USBPcap mitschneiden (Track laden, abspielen, Cue setzen),
  HID-OUT-Reports auf EP 0x06 auswerten (Init-Sequenz, Waveform-Blöcke, Cover). Unsere vorhandenen
  Windows-Mitschnitte liegen **nicht** auf dem Pi und nicht im Repo.
- Risiko: HID-Modus ändert vermutlich das Verhalten von MIDI/Pads – erst getrennt testen (CLAUDE.md: Subsysteme einzeln).

### Erster Windows-Mitschnitt (rekordbox, HID-Modus) – Auswertung 2026-11-08

Datei auf dem Pi (nicht im Repo, 48 MB): `~/ddj1000-captures/windows-rekordbox-20260505/DDJ1000_laenger.pcapng`
(SHA-256 `f37027c5…1a49428`, USBPcap, ~30 s). Analyse ohne tshark mit `scripts/dev/analysis/usbpcap-*.py`
(`python3 -I <skript> <datei>`; der DDJ ist dort Gerät 6, ggf. im Skript anpassen).

- Gerät 6 = DDJ-1000: ISO EP 0x01 (792/810 B) und EP 0x82 (3168/3204 B) wie bekannt; Bulk EP 0x04 (MIDI-OUT,
  meist 4 B), **HID-OUT EP 0x06: 696 Reports à 64 B**, **HID-IN EP 0x87: 20 189 Reports à 64 B** (~680/s, meist
  Nullen; nicht-null alle mit Präfix `00 20`).
- HID-OUT-Aufbau: **Byte 0 = Deck** (`0x10/0x20/0x30/0x40` = Deck 1–4), **Byte 1 = Befehl**, ab Byte 2 Index/Daten.

| Befehl | Anzahl | Beobachtung |
|--------|--------|-------------|
| `0x21` | 76     | Deck-Status, nur Deck 1/2, bis 62 Byte genutzt, ~2,5/s (z. B. `10 21 18 0a 11 01 00 00 00 10 … 80 … 80 0d`) – Kandidat für Zeit/BPM/Position/Tempo |
| `0x2c` | 584    | Blockserie Index `01…49` (73 Blöcke) je Deck, Byte 4 = `0x49` (= Anzahl). **In diesem Mitschnitt leer** → vermutlich Waveform-Blöcke, hier nur gelöscht |
| `0x2d`, `0x2f`, `0x30` | 8/8/16 | je Deck einmal nach der `0x2c`-Serie (`…01 00 01`, `…01/02 00 02`) – Abschluss/Commit? |
| `0x2b` | 4      | je Deck einmal am Ende (`x0 2b 01 00 01`) |

- Folgerung: Der Mitschnitt zeigt Init/Leeren der Displays, aber **keinen geladenen Track mit Waveform** (alle
  `0x2c`-Blöcke ohne Nutzdaten). Für die Waveform nötig: neuer Mitschnitt mit klar getrennten Schritten und Notizen
  der Uhrzeit: (1) rekordbox starten, (2) Track auf Deck 1 laden, 5 s warten, (3) Play 10 s, (4) Cue setzen,
  (5) zweiten Track auf Deck 2 laden. Dann `0x2c`-Nutzdaten gegen die Waveform-Form vergleichen und `0x21` gegen
  Zeit/BPM. Cover-Art vermutlich ebenfalls über eine Blockserie.

### MIDI-Startsequenz von rekordbox (gleicher Mitschnitt, EP 0x04/0x85) und Abgleich mit jan0803

`scripts/dev/analysis/usbpcap-midi-sysex.py <pcapng> 6` dekodiert USB-MIDI zu SysEx. Ablauf (Zeit in s):

| t | Richtung | SysEx (nach `f0 00 40 05 00 00 02 00 00`) | Deutung |
|---|---|---|---|
| 16.106 | OUT/IN | `50 01` → `11 02` | Heartbeat / ready (bekannt) |
| 16.207 | OUT | `00 0a 00 28 00 26 00 <12 Byte, wechselnd> 00…` (57 B) | ? Inhalt ändert sich pro Sitzung (Zeitstempel/Token?) |
| 16.210 | OUT | `00 0b 2b 68 00 00 00 00` | ? |
| 16.213 | OUT | `00 0c 00 00 02 0e 0e 00 00 00` | ? konstant |
| 16.446 | OUT | **`03 01`** | neu, mehrfach vor dem HID-Verkehr |
| 17.108–17.111 | OUT/IN | `12 2a` → `13 2a` → `14 38` → `15 02` | Unlock (bekannt) |
| 17.114–17.123 | OUT | `0b 2b 68…`, `0a …`, `0c …` erneut | |
| 18.600 | OUT | `03 01` | danach erster HID-OUT `10 21 …` bei 18.729 |
| 18.733 | OUT | `00 0a …` mit anderem Inhalt, dann `00 0b 31 00 00 00 00` + `00 0c …` mehrfach | |
| 19.638 | OUT | `03 01` + `00 0a …` | direkt danach HID-`0x2c`-Blockserie (19.65 s) |
| danach | OUT | `50 01` alle ~200 ms | Heartbeat läuft bei rekordbox dauerhaft (5 Hz) |

Abgleich mit dem Upstream-Repo **jan0803/ddj1000-linux-driver** (`origin/main`, `scripts/runtime/ddj1000-unlock-service.py`):
- Dort heißen genau diese Nachrichten `DDJ_JOGSCREEN_ENABLE_MESSAGES` (`00 0a …`, `00 0b 35 60 14 01 00 00`, `00 0c 00 00 02 0e 0e …`)
  und `DDJ_JOGSCREEN_ENABLE_6_MESSAGES` (`00 0b 31 …`, `00 0a …`, `00 0c …`); gesendet nach dem ACK per `amidi`.
  Die 12 wechselnden Bytes in `00 0a` sind bei jan0803 andere als in unserem Mitschnitt → Bedeutung offen.
- Außerdem: `DDJ_BROWSER_STARTUP_MESSAGES` (`9f 40 7f`, `9f 41 00`, `9f 42 7f`, `bf 41…4a …`) und je Deck Noten
  `0B/47/0C/50` = 0; HID-Report-Deskriptor wird gelesen (`0x81/0x06 wValue 0x2200 wIndex 3 len 0x74`).
- **`03 01` fehlt bei jan0803** und in unserem Unlock-Tool. Hypothese: schaltet den DDJ in den HID-/Display-Modus
  (HID-OUT beginnt jeweils kurz danach). Nicht getestet – Risiko: im HID-Modus verhalten sich MIDI/Pads/Beat FX
  anders (Mixxx-Wiki), daher zuerst isoliert ohne Mixxx probieren und mit `aseqdump` vergleichen.
- Unser Unlock-Tool sendet keine dieser Nachrichten; Jog-Displays zeigen trotzdem Zeit/BPM über das MIDI-Mapping.

### Zweiter Mitschnitt mit geladenen Tracks – Auswertung 2026-11-09

Datei (nicht im Repo, 289 MB): `~/ddj1000-captures/windows-rekordbox-20261109/DDJ1000-Wavform.pcapng`
(SHA-256 `ec6d6d6ab040a337…`, 97,5 s, DDJ = **Gerät 7**). Werkzeuge: `usbpcap-hid-dump.py` (→ Textdump),
`usbpcap-hid-series.py`, `ddj-hid-decode.py <dump> <deck> <t_von> <t_bis>`. Ohne Notizen des Users, Ablauf
aus den Daten: Init/Leeren ~35,6 s, Track auf Deck 1 ~51,7 s, Deck 2 ~54,1 s, beide erneut geladen ~59 s.

**Blockaufbau HID-OUT (EP 0x06, 64 B):** Byte 0 = Deck (`x0`), Byte 1 = Befehl, Byte 2 = Blockindex (ab 1),
Byte 3 = 0, Byte 4 = Blockanzahl, Byte 5 = 0, **Nutzdaten ab Byte 6 (58 B)**.

Ablauf beim Track-Laden je Deck: `30 01` (Kopf) → `30 02` → `2f`-Serie → `2d` → `2c`-Serie → `2b 01 00 01` (Abschluss).

| Befehl | Inhalt (entschlüsselt) |
|---|---|
| `30 01` | `00 mm ss <ms u16 LE>` = **Tracklänge** (Deck 1 `05 02 90 01` = 5:02,400; Deck 2 `06 06 b0 03` = 6:06,944) |
| `2f` (53/60 Blöcke) | **Beatgrid**: u16 LE Anzahl, dann je Beat 4 B `[Taktschlag 1–4][Position ms, 24 bit LE]`. Deck 1: 756 Beats à 400 ms = 150 BPM; Deck 2: 863 Beats, 425/426 ms ≈ 141,1 BPM; erster Beat 0 bzw. 159 ms |
| `2d` | Tracklänge wie `30 01`, dann `0a 00` + 10× `00 9e 2f 27 01` – vermutlich 10 leere Hot-Cue/Memory-Slots |
| `2c` (73 Blöcke = 4234 B) | **Overview-Waveform: 600 Punkte à 7 B** `[Flag (0x80 nur am 1. Punkt)][Farbe 1 RGB565 LE][Farbe 2 RGB565 LE][Höhe 1][Höhe 2]`; Höhe 0–40, Höhe 1 ≥ Höhe 2, Farbe 2 = hellere Variante von Farbe 1 (zwei Ebenen wie CDJ-Farbwaveform). Nach Trackende Füllpunkte `00 f7 bd ff ff 01 01` (grau/weiß, Höhe 1) |
| `21` (~60/s) | **Deck-Status**: Byte 2 Flags (`18` läuft, `1a` = Stand am Cue?), Byte 3 Flags (`02/08/0a`), Byte 5 Bit 7 ?, **Byte 11–14 = Abspielposition `mm ss ms(u16 LE)`**, Byte 15–18 = Tracklänge, Byte 21/38 = `9f`?, Byte 60 = `0x80 \| Key` (Key-Code wie MIDI `9n 49`, z. B. `94` = F#m, `88` = Cm), **Byte 61 = Key-Variation** (`0d` = 0, wie MIDI `9n 4A`) |

Beispiel `21`: `10 21 1a 08 11 01 00 00 00 b4 00 03 11 9e 00 05 02 90 01 00 00 9f 00 58 02 00 00 80 … 9f … 01 00 94 0d`
→ Deck 1 steht bei 3:17,158 von 5:02,400, Key F#m.

Offen/zu prüfen: Hot-Cue-/Memory-Einträge mit Inhalt (`2d`), Cover (in diesem Mitschnitt kein eigener Befehl
gesehen), Bedeutung `30 02`, die Flags in `21`. Dazu kommt die MIDI-Startsequenz (`03 01`, `00 0a/0b/0c`), die rekordbox
vor dem HID-Verkehr sendet. **Nächster Schritt:** Prototyp unter Linux, der für einen Track aus Mixxx Beatgrid +
Waveform + Status nach diesem Schema sendet. Zuerst nur mit Testdaten an EP 0x06, ohne Mixxx, mit Rawmidi-Init.
Risiko HID-Modus siehe oben.

### Display-Test unter Linux – 2026-11-09 (ohne Erfolg, Ergebnis festgehalten)

HID-Interface 3 ist unter Linux `/dev/hidrawN` (hid-generic, Gruppe plugdev, für `pi` schreibbar). Der
Report-Deskriptor hat keine Report-IDs und 64-B-Reports, also beim Schreiben `0x00` + 64 B voranstellen.
Kein libusb und kein Claim an Interface 0 nötig. Skripte: `scripts/dev/display-test/`.

- **Stufe 1** (Mixxx läuft): Deck-1-Upload aus dem Mitschnitt (51,70–52,50 s, 240 Reports, Originaltiming)
  + `0x21` 15 s mit 60 Hz über hidraw → Schreiben fehlerfrei, **Display unverändert**.
- **Stufe 2** (Mixxx beendet): vorher per Rawmidi (ein FD, ein `os.write` je SysEx) `00 0a`, `00 0b 31 00…`,
  `00 0b 31 5e 50 01…`, `00 0c`, `03 01` (3×), dann wie Stufe 1 + `03 01` 1×/s → **Display unverändert** (2× getestet).
  Erkenntnis: **`03 01` = Status-Dump-Anforderung** (DDJ antwortet mit allen Fader/Gain/EQ-CCs), kein HID-Modus.
  `00 0a/0b/0c` ohne Antwort. Kernel-Log ruhig, Audio unbeeinflusst.
- Noch nicht gemacht: Heartbeat `50 01` (5 Hz) + Unlock-Handshake **in derselben Sitzung** vor dem Upload, wie
  rekordbox es tut. Risiko: ersetzt die Unlock-Sitzung des Dienstes (Audio weg, falls der Handshake scheitert →
  `ddj1000-unlock.service` neu starten bzw. DDJ aus/an).
- **Stufe 3 – ERFOLG** (Mixxx beendet, `scripts/dev/display-test/display-stage3.py hw:X,0,0 /dev/hidrawN <dump> 30`):
  Heartbeat `50 01` alle 200 ms + eigener Unlock-Handshake über einen Rawmidi-FD (1. Versuch scheitert, 2. nach
  2 s → `15 02`), 0,1 s nach dem ACK Display-Init (`00 0a`, `00 0b 31 00…`, `00 0b 31 5e 50 01…`, `00 0c`,
  `03 01`), 1 s nach dem ACK der HID-Upload Deck 1 aus dem Mitschnitt, dann `0x21` mit 60 Hz bei laufendem
  Heartbeat. **User: „ein Track mit allem wie bei rekordbox, sogar farbig“** → das dekodierte Format
  (Waveform/Beatgrid/Status) wird vom DDJ unter Linux angezeigt.
  **Voraussetzung:** eine Host-Sitzung mit laufendem Heartbeat bzw. eigenem Unlock. Welcher Teil davon nötig ist
  (Heartbeat allein, frischer Unlock oder Init kurz nach dem ACK), ist noch offen → einzeln eingrenzen.
  Folge für die Architektur: Der Display-Dienst muss den Heartbeat halten. Damit startet er selbst die
  Sitzung, und das passt nicht mehr zu „Unlock-Dienst einmalig, danach ohne Heartbeat“. Einen gemeinsamen
  Dienst für Unlock + Heartbeat + Display (Rawmidi-FD exklusiv) planen; Mixxx liefert die Daten über eine
  Schnittstelle (z. B. Datei/Socket aus dem Controller-Script).
- **Mindestbedingung (2026-11-09, je Test mit „go“ des Users):**
  - T1 Deck 2, Heartbeat läuft, eigener Unlock, **ohne** rekordbox-Init (`--no-init`) → Track + Waveform angezeigt.
    Die Init-SysEx (`00 0b 31…`, `03 01`) ist also nicht nötig. Der Unlock-Vorspann (`00 0a/0b 2b 68/0c`) wird trotzdem gesendet.
  - T2 Deck 1, Heartbeat stoppt 0,5 s nach dem ACK (`--hb-stop-after-ack 0.5`), Upload ohne Heartbeat → Track
    erscheint kurz und **fällt nach etwa 1 s auf „Pioneer DJ“ zurück** (User-Angabe). Nach jedem Testende (Heartbeat aus) zeigen
    beide Displays wieder „Pioneer DJ“.
  - **Ergebnis: Die Display-Anzeige braucht einen dauerhaft laufenden Heartbeat.** Ein neu einsetzender Heartbeat
    startet eine neue Sitzung (CLAUDE.md), also gilt: **Unlock + Heartbeat ohne Lücke + HID**, alles im selben
    Prozess. Mit dem bisherigen Konzept (Unlock-Dienst einmalig, Mixxx ohne Heartbeat) geht es nicht.

### Brückendienst (Weg A), Schritt 1 – 2026-11-09

`scripts/runtime/ddj1000-bridge.py`: hält den DDJ-Rawmidi-FD (Unlock, Heartbeat dauerhaft) und leitet MIDI über
**snd-virmidi** an Mixxx weiter (`modprobe snd-virmidi index=7 id=DDJBridge midi_devs=1`, Mixxx-Port „VirMIDI 7-0“,
Controller „DDJ-1000 MIDI 1“ und DDJ-HID in Mixxx aus). Gemessen und vom User bestätigt: Grundfunktionen, LEDs,
VU-Meter, Pads, Pad-Modus-Wechsel.
- python-rtmidi (virtuelle ALSA-Ports) verworfen: Beim Startschwall von Mixxx stirbt der rtmidi-Eingangsthread
  („MidiInAlsa::alsaMidiHandler: unknown MIDI input error … Resource temporarily unavailable“), danach meldet
  Mixxx jede Ausgabe als Fehler. snd-virmidi = zweites Rawmidi-Gerät, kein Thread.
- Ausgabe zum DDJ: Schreib-Thread, Heartbeat zuerst, Schreiben nur bei schreibbarem Puffer; Warteschlange
  fasst gleiche `status+data1` zusammen. Mixxx sendet ~2000–3000 Nachrichten/s (v. a. Jog-Anzeige),
  maximale Warteschlange 32, null Sendefehler.
- **Heartbeat-Sitzung = rekordbox-Modus:** (1) Die Jog-Displays zeigen „Pioneer DJ rekordbox“ mit Ladekringel
  und ignorieren die MIDI-Anzeige (Zeit/BPM/Key) → Anzeige nur noch per HID. (2) Pad-Modus-Tasten
  (`9n 1B/1E/20/22`, Shift `69/6B/6D/6F`) schalten erst, wenn der Host die Note zurückschickt (MIDI-OUT „same as
  MIDI-IN“) → die Brücke macht das selbst (Echo + andere Modi aus, nach dem Unlock HOT CUE).

### Brückendienst Schritt 2a – Jog-Display-Status per HID (2026-11-09)

Feldsuche am Gerät (`scripts/dev/display-test/status-fields-test.py`, Phasen an der angezeigten Zeit erkennbar):
- `0x21` Byte 21 = BPM ganzzahlig (`0x9f` → 159, `0x95` → 149), Byte 22 oberes Nibble = Zehntel (angenommen),
  dasselbe in Byte 38–39. Im rekordbox-Mitschnitt standen beide Decks auf +6 % (150 × 1,06 = 159, 141,1 × 1,06 = 149,6).
- `0x21` Byte 23–24 = **Tempo in 0,01 %** (int16 LE): 0 → 0.0 %, −300 → −3.0 %, +300 → +3.0 % (bestätigt).
  Vorher für die Zahl der Waveform-Punkte gehalten (600 = +6,00 %).
- `0x21` Byte 9 = `0xb4` Track geladen (0 → „not loaded“). Byte 5 Bit 7 hat keinen Einfluss auf das Tempo.
- Key wird in **Camelot-Schreibweise** angezeigt (Code 15 = G → „9B“). Die Beat-Leiste (−4 … 16) kommt aus dem Beatgrid,
  die BPM-Zahl nicht.
- Synthetischer Upload aus `scripts/runtime/ddj1000_display.py` ist bis auf ein doppeltes `2d` identisch mit rekordbox.

Umsetzung: Das Mapping sendet alle 50 ms je Deck eine SysEx `F0 7D 44 42 01 …` (Zustand: geladen, spielt, Position,
Länge, Track-/aktuelle BPM, Tempo, Key, Key-Shift, erster Beat), die Brücke fängt sie ab
(`ddj1000_display_state.py`). Sie lädt bei neuem Track (Länge/BPM geändert) Länge und Beatgrid hoch (Waveform noch leer)
und sendet `0x21` mit 30 Hz pro Deck, die Position wird zwischen zwei Nachrichten hochgerechnet. Mit `bridgeMode` lässt
das Mapping die MIDI-Jog-Ausgabe (Zeit/Position, BPM/Tempo) weg, die der DDJ in diesem Modus ignoriert:
Mixxx → DDJ von ~1700/s auf ~86/s.
- Fehler unterwegs: Upload-Signatur mit „erstem Beat“ (aus `beat_closest`, wackelt) → Upload alle 2–3 s, Ruckeln.
- Sync/MASTER (Feldtests 2026-11-09): `0x21` **Byte 5 Bit 7 = „MASTER“**, **Bit 4 (und Bit 5) = „SYNC“**; Byte 27 und
  Byte 3 (`08`/`02`) ohne sichtbare Wirkung, „BEAT SYNC“-Bit nicht gefunden. Mapping meldet `sync_enabled`
  (Flag-Bit 3) und `sync_leader` (Bit 2) → vom User bestätigt.
- User: BPM, Zeit, Key, Tempo laufen. Offen: Beat FX
  wirkt nicht, Pad-Farben zum Teil falsch (Sampler kurz grün), Waveform (2b), Performance im Auge behalten (Mini-PC als
  Option).

### Schritt 2b – Waveform aus der Mixxx-Analyse (2026-11-09)

`scripts/runtime/ddj1000_mixxx_track.py`: Track-Suche in `~/.mixxx/mixxxdb.sqlite` (nur lesend) über Länge (±60 ms)
und Track-BPM (±0,02) aus der Deck-Zustand-SysEx. Waveform aus `~/.mixxx/analysis/<track_analysis.id>`
(„WaveformSummary-5.0“: 4 Byte Länge + zlib + Protobuf; 1 visual_sample_rate ≈ 5,9 Hz, 2 audio_visual_ratio,
3 signal_all, 4 gefiltert {1 low, 2 mid, 3 high, 4–6 Filtergrenzen 600/600/4000 Hz}; Werte 0–255 Stereo
verschachtelt). Beatgrid aus `library.beats` („BeatMap-1.0“: wiederholtes Feld 1 = Beat{1 frame_position}).
Umrechnung: 600 Punkte, außen = Gesamtsignal, innen = Bass, Farbe aus Bass/Mitten/Höhen (Bass blau, Mitten
bernstein, Höhen weiß), dunkle/helle Variante als Farbpaar. Suche ~70 ms.
- Mixxx legt neue Tracks erst beim Laden an und analysiert sie dann → die Brücke sucht bis zu 2 min alle 2 s nach
  und lädt die Waveform nach (vorher: „nicht gefunden“ dauerhaft gemerkt, Waveform blieb leer).
- User: Waveform sichtbar (Foto), Beat-Leiste im Takt, kein Ruckeln.
- **Cues/Loops noch nicht:** `2d` hat 10 Plätze à 5 B (leer `00 9e 2f 27 01`). Test mit `[Typ][Position ms u32]`:
  10 Plätze (Typ 0/1) → genau **ein** lila Marker bei ~1/3; 4 Plätze (Typ 0–3) → keiner. Format unklar →
  neuer rekordbox-Mitschnitt mit bekannten Hot Cues/Memory Cue/Loop nötig. Mixxx-Cues stehen in Tabelle `cues`
  (type, position, length, hotcue, label, color).

### Hot Cues auf dem Jog-Display (2026-11-09, Mitschnitt `DDJ1000-Hotcue.pcapng`)

- Die Hot Cues stehen **nicht in `2d`**, sondern in **`30 01`**: Nutzdaten = Länge (`mm ss ms16`) + **8 Plätze à 6 B**
  `[Typ][Farbe][mm][ss][ms u16 LE]` für **A–H** (Report-Byte 10, 16, … 52). Der Platz bestimmt den Buchstaben,
  nicht die Zeit (rekordbox: A 3:27,6, B 2:38,8, C 1:32,8, D 3:55,2, E = Typ `02` 4:11,6).
- Gerätetest (`scripts/dev/display-test/cue30-test.py`, Foto): `01 16` @ 0:30 → **A grün**, `01 01` @ 1:00 → **B blau**,
  `01 24` @ 1:30 → **C orange**, `02 24` @ 2:00 → **D orange** (sieht aus wie ein Hot Cue), Byte 52 `01 16` @ 0:10 →
  **H grün**. Marker auf der Übersicht und auf dem Beat-Lineal (Einheit = Takte) an der richtigen Stelle.
- `0x21` (aus dem Mitschnitt, noch nicht am Gerät getestet): Byte 25–27 / 28–30 = aktiver Loop Start/Ende in ms (u24 LE,
  4:11,600–4:14,800); Byte 55–57 = nächster Cue in ms (u24 LE), 58 = Typ?, 59 = Farbe.
- **Live-Update:** `30 01` allein löscht alle Marker; **`30 01` + leeres `30 02`** setzt sie neu – ohne Waveform-/
  Beatgrid-Upload (Gerätetest `cue30-test.py --only30 --with3002`).
- **Farbcode = Farbkreis-Index** (alle getesteten Codes `01`–`3C` gültig, Fotos 2026-11-09): `01`–`09` blau→cyan,
  `0C` türkis, `12` blaugrün, `16` grün, `1A` gelbgrün, `1E` gelb, `24` orange, `2A` rot, `30` rosa, `36` magenta-rosa,
  `3C` lavendel. Für Mixxx: RGB → Farbton → nächster Code (Stützpunkte oben).
- **Loop (gerätegetestet 2026-11-09):** `0x21` Byte 25–27 Start ms (u24 LE, Bit 7 von Byte 27 = Loop nicht aktiv; ohne
  Loop `00 00 80`), Byte 28–30 Ende ms, **und Byte 9 Bit 3 (`b4` → `bc`) = Loop aktiv** – ohne dieses Flag ignoriert das
  Display das Loop-Feld. rekordbox-Folge: `bc` → Start|0x800000 → Ende → Bit 7 gelöscht. Anzeige: rot-oranger Block auf
  dem Beat-Lineal, Abspielmarke rot. Quelle in Mixxx: `loop_start_position`/`loop_end_position`/`loop_enabled`
  (mit in der Hot-Cue-SysEx `F0 7D 44 42 02`).
- Brücke: Hot Cues A–H live (`30 01` + `30 02` nach Upload und bei Änderung), Farbe RGB → Farbkreis-Code (User: „Colors passen“).
- Offen: Memory Cues/Haupt-Cue, Typ `02` (gespeicherte Loops) optisch, Byte 55–59 (nächster Cue),
  Display folgt nicht dem Deck-Wechsel 1↔3 / 2↔4, Hot-Cue-Farbe im Pioneered-Skin nicht editierbar.
- Brücke bleibt nach schnellem Neustart (< 1 s) `LOCKED` (DDJ sendet kein `11 02`) → 5 s warten; später: Heartbeat bei
  LOCKED kurz aussetzen, um eine neue Sitzung zu erzwingen.

## Quellen
- Upstream [jan0803/ddj1000-linux-driver](https://github.com/jan0803/ddj1000-linux-driver) (`origin/main`)
- [Mixxx-Wiki DDJ-1000](https://github.com/mixxxdj/mixxx/wiki/ddj-1000)
- [pestrela/ddj](https://github.com/pestrela/ddj): MIDI-Tabelle DDJ-1000RB, Signalflüsse, Handbücher, offizielle Mappings
- DDJ-1000 Bedienungsanleitung (DRI1516A), "Verwendung externer Eingänge", "Signalfluss"
