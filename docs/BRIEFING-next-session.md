# Briefing für die nächste Sitzung (Stand 2026-11-08, 01:20)

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
1. **PAD FX1 Pads 1–5 ohne Wirkung** (Reverb, Echoverb HP, Sweep, Noise, Smooth Growl über `[EffectRack1_EffectUnit2]`).
   Diagnosezeile beim Drücken: `grep -a "DDJ-1000 PadFX" ~/.mixxx/mixxx.log`. Prüfen: `preset` = `want`?
   `E1.loaded/enabled` = 1? `route` = 1? Verdacht: Chain-Index (Liste in `effects.xml` `<ChainPresetList>` + 1 wegen „---“)
   oder Effekt-Slot nicht enabled. Alternative ohne Effect Unit: weitere Deck-Funktionen (z. B. `beatlooproll`, Echo-Out).
2. **„Deck 1 und 2 teilweise nicht synchron belegt“** (User-Aussage, noch nicht geklärt – nachfragen, was genau).
   Bekannte Asymmetrie: Loop IN/OUT CH1 läuft über `LoopScaleDividePer2CH1`/`MultiplyPer2CH1` (Script),
   CH2–4 direkt `loop_in`/`loop_out`. Shift+Sync für Deck 3/4 (`92/93 5C`) nur angenommen, nicht gemessen.
3. **Browse im Pioneered-Skin** (Fix eingebaut, **ungetestet**): `[Sidebar],sidebar_visible` folgt dem Fokus.
   Soll: Regler drehen öffnet Browse-Tab; BACK = Ordnerbaum ↔ Trackliste; Push im Baum = Ordner auf/zu,
   auf Playlist → Tracks (Mixxx `GoToItem`, `librarycontrol.cpp:1018`); Push in Liste = LOAD auf das Deck.
4. Color FX: Noise (bipolar über Script) und Dub Echo (Filter Echo) gegenhören; PITCH ist absichtlich frei.
5. Noch unbelegt: Kopfhörer-Mix/-Level, Sampler-Vol (`B6 08/09/0C/0D`?), BEAT ◀ ▶, AUTO/TAP, Sampler-Pads,
   SLIP, CUE/LOOP MEMORY/CALL, Shift+BACK/VIEW (`96 66/68`), Kanalfader 14 bit (`Bx 33` ungenutzt).
6. Temporäre Diagnose wieder entfernen, wenn alles passt: `colorFxDump`/`colorFxKnobWatch`,
   `BeatFX route`-Print, `PadFX`-Print.
7. Wenn stabil: `DDJ-1000test` → `DDJ-1000` übernehmen (oder umbenennen) und im Repo nachziehen.
8. Aus 2026-11-07 weiterhin offen: Langzeittest > 1 h, Reboot-Test der ganzen Kette, Aufräumen der Install-Skripte
   (uncommittete Änderungen an `prepare-…-module.sh` / `install-…-stack.sh` – nicht von Claude, erst klären).

## Fakten, die man sonst neu herausfinden muss
- Chain-Preset-Index in Mixxx 2.5.3 = 0-basiert mit „---“ an Position 0 (Quick-Effect- und normale Liste).
- DDJ sendet echte Note-offs (`8x`) – im XML eigene Einträge nötig, wenn das Loslassen zählt.
- Bei jedem Mapping-Laden schickt der DDJ einen Status-Dump (Fader, Regler, Schalter, Beat-FX-Kanal).
- Mixxx überschreibt die Mapping-Datei, wenn im MIDI-Learning gespeichert wird → vorher neu laden.
- Push: Branch `rpi4` auf Fork `RymenTe/ddj1000-linux-driver-rpi`, der User pusht selbst:
  `git -C ~/ddj1000-linux-driver push fork rpi4:rpi4`.
