# Briefing für die nächste Sitzung (Stand 2026-11-08, 15:40)

## Wo wir stehen
- Audio/Unlock/Standalone läuft (siehe `docs/session-log.md`, 2026-11-07). In dieser Sitzung nur **Mixxx-Mapping + Skin**.
- Aktive Mapping-Datei in Mixxx: **`DDJ-1000test`** (`~/.mixxx/controllers/DDJ-1000test.midi.xml`).
  Script `Pioneer-DDJ_1000-scriptsV0_9_9.js` wird von `DDJ-1000` **und** `DDJ-1000test` geteilt.
- Skin: **`Pioneered-4Deck`** (`~/.mixxx/skins/`, Kopie von Pioneered mit 4 Decks; zeigt nur Deck 1/2 an,
  Deck 3/4 laufen über die DDJ-Deck-Umschaltung). Nie das Original-Pioneered wählen (2 Decks → Script-Fehler).
- Repo-Kopien: `config/mixxx/controllers/` (beide XML + JS), `config/mixxx/skins/Pioneered-4Deck.patch`.
- Snapshot: `~/module-backups/20261108-0116-mapping-session/` (mixxx.cfg, effects, Mapping, Skin, MIDI-Mitschnitte).

## Erste Schritte beim Wiedereinstieg
1. Mixxx starten, prüfen: Preferences → Controllers = `DDJ-1000test`, Interface → Skin = `Pioneered-4Deck`.
2. Log auf Script-Fehler prüfen:
   `grep -a "Uncaught\|Invalid script\|has invalid MixxxControl" ~/.mixxx/mixxx.log`
3. MIDI mitschneiden ohne Mixxx zu stören (ALSA-Seq, nicht Rawmidi):
   `timeout 1800 stdbuf -oL aseqdump -p "$(aconnect -l | awk '/DDJ-1000/{print $2}' | tr -d :):0" > ~/build-logs/midi-capture-$(date +%Y%m%d-%H%M).log`

## Offene Punkte (Priorität)
Erledigt 2026-11-08 nachmittags: PAD FX1 (rekordbox-Standard), Loops/Beat Loop alle Decks, Beat FX → Hardware (MST).
1. Shift+Beat Jump (Beat Loop) Noten `97 60–67` nur angenommen → beim Drücken `grep -a "DDJ-1000 BeatLoop" ~/.mixxx/mixxx.log`.
2. „Deck 1/2 teilweise nicht synchron belegt“ – mit Loop-Vereinheitlichung evtl. erledigt, beim User nachfragen.
3. Browse im Pioneered-Skin (Fix eingebaut, ungetestet), siehe Session-Log 2026-11-08 früh.
4. Jog-Display, schnelle Verbesserungen über dokumentiertes MIDI: Tempo `Bn 16/36`, Cue-Marker `Bn 17/37`,
   Key `9n 49/4A`, Sync `9n 59/5A` (`docs/research-jog-display-and-hw-mixer.md`).
5. Noch unbelegt: Kopfhörer-Mix/-Level, Sampler-Vol, BEAT ◀ ▶ (wirken auf Hardware-Beat-FX), Sampler-Pads, SLIP,
   CUE/LOOP MEMORY/CALL, Kanalfader 14 bit.
6. Temporäre Diagnose entfernen, wenn alles passt: `colorFxDump`/`colorFxKnobWatch`, `PadFX`-, `BeatLoop`-Print,
   `padFxSetSuper` (ungenutzt), `beatFx*`-Funktionen (ungenutzt).
7. Wenn stabil: `DDJ-1000test` → `DDJ-1000` übernehmen und im Repo nachziehen; `rpi4` aktualisieren, User pusht.
8. Aus 2026-11-07: Langzeittest > 1 h, Reboot-Test der Kette, Install-Skripte (uncommittete Änderungen klären).

## Spätere Verbesserungen („All-in-One“, macht der User später)
- **Waveform/Cover auf den Jog-Displays**: nur im HID-Modus (proprietär). Nötig: USBPcap-Mitschnitt Windows+rekordbox,
  HID-Reports auf EP 0x06 (64 B) dekodieren. Siehe Recherche-Doku.
- **Beat FX pro Kanal**: nur in Software möglich (Mixxx Unit 1 auf CH1–4/MIC/SP, nie auf Master). Effektliste in
  Pioneer-Reihenfolge, der SELECT-Raste folgen; Display zeigt im MIDI-Modus immer Pioneer-Namen.
- Hardware-Kanalmischen über USB: beim DDJ-1000 nicht vorgesehen (nur DDJ-1000SRT). Offen: Playback 5/6 und
  die 12 Capture-Kanäle zuordnen (`USB: FX SEND …`, `USB: MIX (REC OUT)`?).

## Fakten, die man sonst neu herausfinden muss
- Chain-Preset-Index in Mixxx 2.5.3 = 0-basiert mit „---“ an Position 0 (Quick-Effect- und normale Liste).
- DDJ sendet echte Note-offs (`8x`) – im XML eigene Einträge nötig, wenn das Loslassen zählt.
- Bei jedem Mapping-Laden schickt der DDJ einen Status-Dump (Fader, Regler, Schalter, Beat-FX-Kanal).
- Mixxx überschreibt die Mapping-Datei, wenn im MIDI-Learning gespeichert wird → vorher neu laden.
- Eigene Effekt-Presets mit festen Werten statt super1-Links (Links bewegen die Parameter nicht zuverlässig);
  neue Presets nur bei beendetem Mixxx in `effects.xml` eintragen (Mixxx überschreibt die Datei beim Beenden).
- Mixxx-Log nur mit `--log-flush-level debug` sofort lesbar (ist im Autostart gesetzt).
- Push: Branch `rpi4` auf Fork `RymenTe/ddj1000-linux-driver-rpi`, der User pusht selbst:
  `git -C ~/ddj1000-linux-driver push fork rpi4:rpi4`.
