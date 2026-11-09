#!/usr/bin/env python3
"""Install the DDJ-1000 Mixxx setup into the user's Mixxx settings directory (Mixxx must be closed).

  - controllers: DDJ-1000.midi.xml + Pioneer-DDJ_1000-scriptsV0_9_9.js
  - effects: own chain presets (PadFX ..., DDJ ColorFX ...) and their FIXED positions at the start of
    <ChainPresetList> / <QuickEffectPresetList> in effects.xml - the mapping selects presets by index
    and Mixxx's built-in preset names are localised (e.g. "Weißes Rauschen"), so only own presets
    at the front give the same index on every system
  - skin Pioneered-4Deck (copy of Pioneered with 4 decks)
  - mixxx.cfg: controller "VirMIDI 7-0" (bridge) = DDJ-1000 and enabled, other DDJ controller entries
    off, skin Pioneered-4Deck
  - soundconfig.xml: DDJ-1000 Master = channels 1/2, Headphones = 3/4, 44.1 kHz (only if no DDJ output
    is configured yet; the card number is read from /proc/asound/cards, never hard-coded)

Everything that is changed is backed up first to <settings>/ddj1000-backup-YYYYMMDD-HHMM/.
usage: ddj1000-mixxx-config.py [--settings-dir DIR] [--dry-run]
"""
import argparse
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CTRL_SRC = REPO / "config" / "mixxx" / "controllers"
CHAINS_SRC = REPO / "config" / "mixxx" / "effects" / "chains"
MAPPING = "DDJ-1000.midi.xml"
SCRIPT = "Pioneer-DDJ_1000-scriptsV0_9_9.js"
VIRMIDI_CONTROLLER = "VirMIDI_7-0"          # snd-virmidi index 7 (config/modprobe/ddj1000-virmidi.conf)
SKIN = "Pioneered-4Deck"
# order = index used in the mapping (1-based, 0 = "---"): PAD_FX1_EFFECTS / BEAT_FX_LIST / COLOR_FX_PRESETS
CHAIN_PRESETS = ["PadFX Echo 1-4", "PadFX Echo 1-2", "PadFX Echo 1-2 Long", "PadFX Reverb 50",
                 "PadFX Flanger 16", "PadFX Sweep", "DDJ BeatFX Echo", "DDJ BeatFX Low Cut Echo"]
QUICK_PRESETS = ["DDJ ColorFX Filter", "DDJ ColorFX Filter Echo", "DDJ ColorFX White Noise"]
SYSTEM_SKIN_DIRS = [Path("/usr/share/mixxx/skins"), Path("/usr/local/share/mixxx/skins"),
                    Path("/var/lib/flatpak/app/org.mixxx.Mixxx/current/active/files/share/mixxx/skins")]


def settings_dir(arg):
    if arg:
        return Path(arg).expanduser()
    for d in (Path.home() / ".mixxx", Path.home() / ".var/app/org.mixxx.Mixxx/.mixxx"):
        if (d / "mixxx.cfg").exists():
            return d
    return None


class Installer:
    def __init__(self, sdir, dry):
        self.sdir = sdir
        self.dry = dry
        self.backup = sdir / time.strftime("ddj1000-backup-%Y%m%d-%H%M")
        self.changes = []

    def save(self, path):
        """back up a file once before it is changed"""
        if path.exists():
            dst = self.backup / path.relative_to(self.sdir)
            if not dst.exists() and not self.dry:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dst)

    def write(self, path, data, what):
        old = path.read_bytes() if path.exists() else None
        new = data.encode() if isinstance(data, str) else data
        if old == new:
            return
        self.changes.append(what)
        if self.dry:
            return
        self.save(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(new)

    # --- files
    def controllers(self):
        for name in (MAPPING, SCRIPT):
            self.write(self.sdir / "controllers" / name, (CTRL_SRC / name).read_bytes(), f"controllers/{name}")

    def chains(self):
        for src in sorted(CHAINS_SRC.glob("*.xml")):
            self.write(self.sdir / "effects" / "chains" / src.name, src.read_bytes(), f"effects/chains/{src.name}")

    def skin(self):
        src = next((d / "Pioneered" for d in SYSTEM_SKIN_DIRS if (d / "Pioneered" / "skin.xml").exists()), None)
        if src is None:
            print("[WARN] system skin 'Pioneered' not found - skin not installed (Mixxx keeps its skin)")
            return False
        dst = self.sdir / "skins" / SKIN
        xml = (src / "skin.xml").read_text()
        xml = xml.replace("<title>Pioneered</title>", "<title>Pioneered (4 Deck)</title>")
        xml = xml.replace('<attribute config_key="[Master],num_decks">2</attribute>',
                          '<attribute config_key="[App],num_decks">4</attribute>')
        if not dst.exists():
            self.changes.append(f"skins/{SKIN} (copy of {src})")
            if not self.dry:
                shutil.copytree(src, dst)
        self.write(dst / "skin.xml", xml, f"skins/{SKIN}/skin.xml")
        return True

    # --- effects.xml
    def effects(self):
        path = self.sdir / "effects.xml"
        if not path.exists():
            print("[WARN] effects.xml missing - start Mixxx once, close it and run this again")
            return
        tree = ET.parse(path)
        root = tree.getroot()
        for tag, own in (("ChainPresetList", CHAIN_PRESETS), ("QuickEffectPresetList", QUICK_PRESETS)):
            lst = root.find(tag)
            if lst is None:
                lst = ET.SubElement(root, tag)
            names = [e.text for e in lst.findall("ChainPresetName")]
            rest = [n for n in names if n not in own]
            for e in list(lst):
                lst.remove(e)
            for n in own + rest:
                ET.SubElement(lst, "ChainPresetName").text = n
        ET.indent(tree, space=" ")
        data = ET.tostring(root, encoding="unicode", xml_declaration=False)
        self.write(path, "<?xml version='1.0' encoding='utf-8'?>\n" + data + "\n", "effects.xml preset lists")

    # --- mixxx.cfg ("[Section]" + "key value" lines)
    def mixxx_cfg(self, skin_ok):
        path = self.sdir / "mixxx.cfg"
        lines = path.read_text().splitlines()
        wanted = {("ControllerPreset", VIRMIDI_CONTROLLER): str(self.sdir / "controllers" / MAPPING),
                  ("Controller", VIRMIDI_CONTROLLER): "1"}
        if skin_ok:
            wanted[("Config", "ResizableSkin")] = SKIN
        out, section, seen = [], None, set()

        def flush(sec):
            for (s, k), v in wanted.items():
                if s == sec and (s, k) not in seen:
                    out.append(f"{k} {v}")
                    seen.add((s, k))

        for line in lines:
            m = re.fullmatch(r"\[(.+)\]", line.strip())
            if m:
                if out and out[-1] == "":
                    out.pop()
                    flush(section)
                    out.append("")
                else:
                    flush(section)
                section = m.group(1)
                out.append(line)
                continue
            key, _, val = line.partition(" ")
            if (section, key) in wanted:
                out.append(f"{key} {wanted[(section, key)]}")
                seen.add((section, key))
            elif section == "Controller" and key.startswith("DDJ-1000") and val.strip() != "0":
                out.append(f"{key} 0")   # direct MIDI/HID port of the DDJ: owned by the bridge
            else:
                out.append(line)
        flush(section)
        for (s, k), v in wanted.items():   # sections that did not exist
            if (s, k) not in seen:
                out += ["", f"[{s}]", f"{k} {v}"]
                seen.add((s, k))
        self.write(path, "\n".join(out) + "\n", "mixxx.cfg (controller VirMIDI 7-0 = DDJ-1000, skin)")

    # --- soundconfig.xml
    def soundconfig(self):
        path = self.sdir / "soundconfig.xml"
        if path.exists() and "DDJ-1000" in path.read_text():
            print("[INFO] soundconfig.xml already uses the DDJ-1000 - left unchanged")
            return
        card = None
        for line in Path("/proc/asound/cards").read_text().splitlines():
            m = re.match(r"\s*(\d+) \[DDJ1000\s*\]", line)
            if m:
                card = m.group(1)
        if card is None:
            print("[WARN] DDJ-1000 sound card not present - soundconfig.xml not written "
                  "(plug in + unlock the DDJ, then run again, or set it in Mixxx Preferences -> Sound Hardware)")
            return
        xml = f"""<!DOCTYPE SoundManagerConfig>
<SoundManagerConfig deck_count="4" api="ALSA" sync_buffers="0" force_network_clock="0" latency="2" samplerate="44100">
 <SoundDevice portAudioIndex="-1" name="DDJ-1000: USB Audio" alsaHwDevice="hw:{card},0">
  <output channel="0" type="Master" channel_count="2" index="0"/>
  <output channel="2" type="Headphones" channel_count="2" index="0"/>
 </SoundDevice>
</SoundManagerConfig>
"""
        self.write(path, xml, f"soundconfig.xml (DDJ-1000 hw:{card},0, Master 1/2, Headphones 3/4)")


def mixxx_running():
    return subprocess.run(["pgrep", "-x", "mixxx"], stdout=subprocess.DEVNULL).returncode == 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--settings-dir", default="", help="Mixxx settings dir (default ~/.mixxx or the Flatpak one)")
    ap.add_argument("--dry-run", action="store_true", help="only show what would change")
    a = ap.parse_args()
    sdir = settings_dir(a.settings_dir)
    if sdir is None or not (sdir / "mixxx.cfg").exists():
        sys.exit("Mixxx settings not found - start Mixxx once, close it and run this again")
    real = sdir.resolve() in (p.resolve() for p in (Path.home() / ".mixxx", Path.home() / ".var/app/org.mixxx.Mixxx/.mixxx"))
    if real and mixxx_running() and not a.dry_run:
        sys.exit("Mixxx is running - close it first (it rewrites its settings on exit)")
    inst = Installer(sdir, a.dry_run)
    inst.controllers()
    inst.chains()
    skin_ok = inst.skin()
    inst.effects()
    inst.mixxx_cfg(skin_ok)
    inst.soundconfig()
    print(f"Mixxx settings: {sdir}")
    for c in inst.changes:
        print(f"  {'would change' if a.dry_run else 'changed'}: {c}")
    if not inst.changes:
        print("  nothing to change")
    elif not a.dry_run and inst.backup.exists():
        print(f"  backup: {inst.backup}")


if __name__ == "__main__":
    main()
