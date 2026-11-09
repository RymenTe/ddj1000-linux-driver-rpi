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

## Quellen
- Upstream [jan0803/ddj1000-linux-driver](https://github.com/jan0803/ddj1000-linux-driver) (`origin/main`)
- [Mixxx-Wiki DDJ-1000](https://github.com/mixxxdj/mixxx/wiki/ddj-1000)
- [pestrela/ddj](https://github.com/pestrela/ddj): MIDI-Tabelle DDJ-1000RB, Signalflüsse, Handbücher, offizielle Mappings
- DDJ-1000 Bedienungsanleitung (DRI1516A), "Verwendung externer Eingänge", "Signalfluss"
