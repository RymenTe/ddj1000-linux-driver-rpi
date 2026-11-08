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

Status im Script `Pioneer-DDJ_1000-scriptsV0_9_9.js`: Zeit (`42/43/44`), Position (`Bn 14`), BPM (`Bn 15`),
Ring (`5B`), Anzeige (`5D`) werden gesendet. **Noch nicht:** Tempo `Bn 16/36`, Cue-Marker `Bn 17/37`,
Key `49/4A`, Sync `59/5A` → schnelle Verbesserungen ohne Reverse Engineering.
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

## Quellen
- [Mixxx-Wiki DDJ-1000](https://github.com/mixxxdj/mixxx/wiki/ddj-1000)
- [pestrela/ddj](https://github.com/pestrela/ddj): MIDI-Tabelle DDJ-1000RB, Signalflüsse, Handbücher, offizielle Mappings
- DDJ-1000 Bedienungsanleitung (DRI1516A), "Verwendung externer Eingänge", "Signalfluss"
