# Briefing für die nächste Sitzung (Stand 2026-11-09, 21:45)

## Wo wir stehen
- **Komplette Kette läuft im Autostart** (Reboot-Test 2026-11-09 19:10 bestanden):
  `ddj1000-module-check` → snd-virmidi (Karte 7) → udev startet `ddj1000-bridge@midiCXD0` (Unlock, Heartbeat,
  MIDI-Weiterleitung, Jog-Displays per HID) → `/run/ddj1000/unlocked` → `mixxx-after-ddj1000` startet Mixxx.
- Mixxx: Controller **„VirMIDI 7-0“** mit Mapping **`DDJ-1000`** (das alte `DDJ-1000test` ist abgelöst),
  Skin **`Pioneered-4Deck`**. Script `Pioneer-DDJ_1000-scriptsV0_9_9.js`.
- Jog-Displays: Waveform, Beatgrid, Hot Cues, BPM/Zeit/Key/Tempo aus Mixxx (über die Brücke).
- **Beat FX (neu, `c98fb78`)**: MASTER = Hardware-DSP des DDJ; CH1–4/MIC/SP = Mixxx Effect Unit 1 mit
  LOW CUT ECHO (`94 20`) und ECHO (`94 21`), BEAT ◀/▶ = Echo-Zeit, LEVEL/DEPTH = Unit-`mix`. User: „Das geht“.
- Branches: `main` = `rpi4` = `c98fb78` (lokal). Fork `rpi4` steht auf `7627f80` → **User pusht**:
  `git -C ~/ddj1000-linux-driver push fork rpi4:rpi4`
- Snapshot der Live-Konfiguration vor dem Live-Test: `~/module-backups/20261109-2145-live-test/`.

## Zuerst beim Wiedereinstieg
1. **Ergebnis des Live-Tests beim User abfragen** (Aussetzer? Xruns? Display hängt? Beat FX? Hitze/Last?).
2. Logs der Live-Session sichern und lesen:
   - `journalctl -t ddj1000-bridge -b --no-pager | tail -200` (Unlock, Heartbeat, Statistik)
   - `grep -a "Uncaught\|Invalid script\|underflow\|xrun" ~/.mixxx/mixxx.log`
   - `dmesg -T | tail -100` (USB-Fehler, `-75`, Disconnects)
   - `grep -A3 Implicit /proc/asound/card*/stream0`
   Bei Reboot zwischendurch: `journalctl -b -1 …` und `~/.mixxx/mixxx.log.1`.

## Offene Punkte (Priorität)
1. Befunde aus dem Live-Test.
2. Beat FX: beim Ausschalten steht `mix` im Log auf 0 – klären, ob LEVEL-Regler oder DDJ-Nachricht
   (`aseqdump` auf VirMIDI 7-0 mitlaufen lassen, ON/OFF drücken, auf `B4 02/22` achten).
3. Langzeittest > 1 h mit Statistik der Brücke (`--stats-interval-s`).
4. Alt-udev-Regeln außerhalb des Repos aufräumen (**Freigabe nötig**): `/etc/udev/rules.d/99-ddj1000.rules`
   (Tippfehler `ATTRES`), `91-ddj1000.rules` (setzt `ATTR{id}` auf jedem Unterknoten).
5. Jog-Display: Deck-Umschaltung 1↔3 / 2↔4 prüfen; kleine Tempo-%-Abweichung an den Pitch-Enden (Rundung).
6. Noch unbelegt: Kopfhörer-Mix/-Level, Sampler-Vol, Sampler-Pads, SLIP, CUE/LOOP MEMORY/CALL, Kanalfader 14 bit.
7. Diagnose-Prints aufräumen, wenn alles stabil ist (`colorFxDump`/`colorFxKnobWatch`, PadFX, BeatLoop, BeatFX).
8. Optional: Rolle von Playback 5/6 und der 12 Capture-Kanäle (`USB: FX SEND …`, `USB: MIX (REC OUT)`?) mit
   `arecord -c 12` + Line-Quelle zuordnen.

## Hardware des Users (nicht in Software debuggen)
- Beat FX SELECT defekt ab MT DELAY (Deck 1 zeigt dann „external input“) → nur ECHO / LOW CUT ECHO nutzen.
- Verlassen der MIC-Stellung am CH-Wahlschalter → DDJ setzt die FX-Sektion zurück (`94 20` + `94 46` +
  Status-Dump, Anzeige ENIGMA JET). Das Script folgt der Knopfstellung, nicht der Anzeige.

## Hardware-Mischen pro Kanal (Frage des Users 2026-11-09)
- Laut Pioneer-Signalfluss „Internal Mode“ und Mixxx-Wiki: USB-Audio kommt beim DDJ-1000 nur als Summe
  (`USB: MASTER OUT`, vor BEAT FX MASTER) und als Cue in die Hardware; die Kanalzüge (Color FX, Beat FX CHx)
  bekommen nur LINE/PHONO. Mit externer Quelle an LINE wirken die Hardware-Effekte pro Kanal.
- DDJ-1000SRT (Serato) hat laut Wiki Hardware-FX auch für Software-Decks. Bei uns: nur ein aktives
  Stereopaar in den rekordbox-Mitschnitten, kein zweites Altsetting. **Nicht geprüft**: ob der DDJ-1000 per
  undokumentiertem Befehl/Firmware doch einen External Mode kann – wäre nur mit Mitschnitt/Firmware-Analyse
  zu klären.

## Fakten, die man sonst neu herausfinden muss
- Chain-Preset-Index in Mixxx 2.5.3 = Position in `<ChainPresetList>` + 1 („---“ = 0);
  Reihenfolge legt `scripts/ddj1000-mixxx-config.py` fest (Beat FX: Echo = 7, Low Cut Echo = 8).
- Eigene Effekt-Presets mit festen Werten statt super1-Links; neue Presets nur bei beendetem Mixxx in
  `effects.xml` eintragen (Mixxx überschreibt die Datei beim Beenden).
- DDJ sendet echte Note-offs (`8x`); bei jedem Mapping-Laden ein Status-Dump (inkl. Beat-FX-Kanal/-Phase/ON).
- Beat FX ON/OFF im Brückenmodus: `94 46` meldet den Zustand, Host muss ihn zurückschicken (sonst driftet der Toggle).
- Mixxx lädt das Script beim Speichern selbst neu. Log sofort lesbar dank `--log-flush-level debug`.
- Bridge-Neustart geht ohne Mixxx-Neustart (VirMIDI-Port gehört dem Kernel); danach neuer Unlock.
- Rawmidi exklusiv: Mitschnitte nur über ALSA-Seq (`aseqdump`) am VirMIDI-Port, nie `amidi` parallel.
