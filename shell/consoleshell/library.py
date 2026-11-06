"""Bibliothèque d'émulation : systèmes, jeux récents (listes ES-DE + lancements depuis
l'accueil), jaquettes téléchargées par ES-DE, lancement direct d'un jeu."""
import os
import re
import time
import unicodedata
import xml.etree.ElementTree as ET

from . import resume
from .config import BIN_DIR, HOME, RECENTS_PATH, ROMS_DIR
from .util import atomic_write, log, read_json, write_json

ESDE_DIR = os.environ.get("ESDE_APPDATA_DIR", os.path.join(HOME, "ES-DE"))
MEDIA_DIR = os.path.join(ESDE_DIR, "downloaded_media")
GAMELISTS = os.path.join(ESDE_DIR, "gamelists")
SETTINGS_XML = os.path.join(ESDE_DIR, "settings", "es_settings.xml")
RA_CORES = os.path.join(HOME, ".var/app/org.libretro.RetroArch/config/retroarch/cores")

# (id ES-DE, nom, sigle, couleur d'accent, extensions)
SYSTEMS = [
    ("nes", "NES", "NES", "#e0393e", ".fds .nes .unf .unif .7z .zip"),
    ("snes", "Super Nintendo", "SNES", "#8a74d6", ".bin .bs .fig .sfc .smc .swc .7z .zip"),
    ("n64", "Nintendo 64", "N64", "#2fa84f", ".bin .n64 .ndd .v64 .z64 .7z .zip"),
    ("gb", "Game Boy", "GB", "#8bac0f", ".gb .sgb .7z .zip"),
    ("gbc", "Game Boy Color", "GBC", "#d1365d", ".gbc .cgb .7z .zip"),
    ("gba", "Game Boy Advance", "GBA", "#7b5cff", ".agb .bin .gba .7z .zip"),
    ("nds", "Nintendo DS", "DS", "#9aa4b5", ".app .bin .dsi .ids .nds .7z .zip"),
    ("n3ds", "Nintendo 3DS", "3DS", "#e5383b", ".3ds .3dsx .app .axf .cci .cxi .elf .z3dsx .zcci .zcxi .7z .zip"),
    ("gc", "GameCube", "GC", "#6c4ee0", ".ciso .dol .elf .gcm .gcz .iso .m3u .rvz .tgc .wbfs .wia"),
    ("wii", "Wii", "Wii", "#3fb6e8", ".ciso .dol .elf .gcm .gcz .iso .m3u .rvz .tgc .wad .wbfs .wia"),
    ("mastersystem", "Master System", "SMS", "#c0392b", ".bin .sms .7z .zip"),
    ("megadrive", "Mega Drive", "MD", "#4b5d78", ".bin .gen .md .smd .7z .zip"),
    ("gamegear", "Game Gear", "GG", "#5c6b7a", ".gg .7z .zip"),
    ("psx", "PlayStation", "PS1", "#b0b4bd", ".bin .cbn .ccd .chd .cue .ecm .exe .img .iso .m3u .mdf .mds .pbp .toc .7z .zip"),
    ("ps2", "PlayStation 2", "PS2", "#2f6bff", ".bin .chd .ciso .cso .elf .gz .m3u .mdf .img .iso .isz .zso"),
]
SYSTEM_INDEX = {s[0]: s for s in SYSTEMS}

# Commandes de lancement direct (mêmes émulateurs que dans ES-DE), via console-emu pour la reprise.
EMU = os.path.join(BIN_DIR, "console-emu")
def _ra(core):
    return lambda rom: [EMU, "retroarch", "-L", f"{RA_CORES}/{core}_libretro.so", rom]


COMMANDS = {
    "nes": _ra("mesen"), "snes": _ra("snes9x"), "n64": _ra("mupen64plus_next"),
    "gb": _ra("gambatte"), "gbc": _ra("gambatte"),
    "mastersystem": _ra("genesis_plus_gx"), "megadrive": _ra("genesis_plus_gx"), "gamegear": _ra("genesis_plus_gx"),
    "gba": lambda rom: [EMU, "retroarch", "-L", f"{RA_CORES}/mgba_libretro.so", rom],
    "nds": lambda rom: [EMU, "retroarch", "-L", f"{RA_CORES}/melondsds_libretro.so", rom],
    "psx": lambda rom: [EMU, "retroarch", "-L", f"{RA_CORES}/mednafen_psx_hw_libretro.so", rom],
    "gc": lambda rom: [EMU, "dolphin", "-b", "-e", rom],
    "wii": lambda rom: [EMU, "dolphin", "-b", "-e", rom],
    "ps2": lambda rom: [EMU, "pcsx2", "-batch", "-fullscreen", "--", rom],
    "n3ds": lambda rom: [EMU, "azahar", "-f", rom],
}
# Libellés ES-DE compatibles avec le lancement direct.
SUPPORTED_LABELS = {
    "nes": {"Mesen"}, "snes": {"Snes9x - Current"}, "n64": {"Mupen64Plus-Next"},
    "gb": {"Gambatte"}, "gbc": {"Gambatte"},
    "mastersystem": {"Genesis Plus GX"}, "megadrive": {"Genesis Plus GX"}, "gamegear": {"Genesis Plus GX"},
    "gba": {"mGBA"}, "nds": {"melonDS DS"}, "psx": {"Beetle PSX HW"},
    "gc": {"Dolphin (Standalone)"}, "wii": {"Dolphin (Standalone)"},
    "ps2": {"PCSX2 (Standalone)"}, "n3ds": {"Azahar (Standalone)"},
}
MEDIA_TYPES = ("covers", "miximages", "3dboxes", "screenshots", "titlescreens")


def _exts(system):
    return set(SYSTEM_INDEX[system][4].split())


def dir_as_file(path, exts=None):
    """Dossier qu'ES-DE montre comme un seul jeu : nommé avec une extension de jeu (« Jeu.m3u ») et
    contenant le fichier du même nom, qui est celui passé à l'émulateur."""
    name = os.path.basename(path)
    ext = os.path.splitext(name)[1].lower()
    return bool(ext) and (exts is None or ext in exts) and os.path.isfile(os.path.join(path, name))


def launch_target(path):
    """Fichier à donner à l'émulateur (le fichier homonyme pour un dossier vu comme un fichier)."""
    return os.path.join(path, os.path.basename(path)) if os.path.isdir(path) and dir_as_file(path) else path


def count_games(system):
    folder = os.path.join(ROMS_DIR, system)
    exts, n = _exts(system), 0
    try:
        for entry in os.scandir(folder):
            if entry.name.startswith((".", "_")):
                continue
            if entry.is_file() and os.path.splitext(entry.name)[1].lower() in exts:
                n += 1
            elif entry.is_dir() and dir_as_file(entry.path, exts):
                n += 1
            elif entry.is_dir():
                for f in os.listdir(entry.path):
                    sub = os.path.join(entry.path, f)
                    if os.path.splitext(f)[1].lower() in exts and (os.path.isfile(sub) or dir_as_file(sub, exts)):
                        n += 1
    except OSError:
        return 0
    return n


def _fold(text):
    """Minuscules sans accents, pour comparer des noms de jeux."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))


def find_game(query):
    """(système, chemin, nom) du premier jeu dont le nom contient tous les mots de query, ou None."""
    words = _fold(query).split()
    if not words:
        return None
    for system, *_ in SYSTEMS:
        exts = _exts(system)
        folders = [os.path.join(ROMS_DIR, system)]
        while folders:
            folder = folders.pop(0)
            try:
                entries = sorted(os.scandir(folder), key=lambda e: e.name.casefold())
            except OSError:
                continue
            for entry in entries:
                if entry.name.startswith((".", "_")):
                    continue
                stem, ext = os.path.splitext(entry.name)
                is_game = ext.lower() in exts and (entry.is_file() or dir_as_file(entry.path, exts))
                if is_game and all(w in _fold(stem) for w in words):
                    return system, entry.path, stem
                if entry.is_dir() and not is_game and folder == os.path.join(ROMS_DIR, system):
                    folders.append(entry.path)              # un niveau de sous-dossiers, comme ES-DE
    return None


def systems():
    return [{"id": s, "name": name, "short": short, "color": color, "count": count_games(s)}
            for s, name, short, color, _ in SYSTEMS]


def media(system, rom_path):
    """Image du jeu rangée par ES-DE (ou par les jaquettes automatiques) : même chemin que le jeu dans
    son dossier de système, sans l'extension (« psx/covers/Final Fantasy VII/Disc 1.png »). Pour un
    dossier vu comme un fichier, ES-DE garde son « extension » : « psx/covers/FF7.m3u.png »."""
    stem = rom_path if os.path.isdir(rom_path) else os.path.splitext(rom_path)[0]
    rel = os.path.relpath(stem, os.path.join(ROMS_DIR, system))
    names = [rel] if not rel.startswith("..") else []
    if os.path.basename(stem) not in names:
        names.append(os.path.basename(stem))
    for mtype in MEDIA_TYPES:
        for name in names:
            for ext in (".png", ".jpg", ".webp"):
                p = os.path.join(MEDIA_DIR, system, mtype, name + ext)
                if os.path.exists(p):
                    return p
    return None


def _parse_gamelist(system):
    path = os.path.join(GAMELISTS, system, "gamelist.xml")
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None, []
    # gamelist.xml d'ES-DE contient plusieurs éléments racine (alternativeEmulator + gameList)
    try:
        root = ET.fromstring("<root>" + re.sub(r"<\?xml[^>]*\?>", "", text) + "</root>")
    except ET.ParseError as exc:
        log.debug("gamelist %s illisible : %s", system, exc)
        return None, []
    label = root.findtext("./alternativeEmulator/label") or root.findtext(".//gameList/alternativeEmulator/label")
    games = []
    for g in root.iter("game"):
        rel = g.findtext("path") or ""
        if not rel:
            continue
        rom = os.path.normpath(os.path.join(ROMS_DIR, system, rel))
        games.append({"system": system, "path": rom, "name": g.findtext("name") or os.path.splitext(os.path.basename(rom))[0],
                      "lastplayed": g.findtext("lastplayed") or "", "altemulator": g.findtext("altemulator") or ""})
    return label, games


def _ts(lastplayed):
    try:
        return time.mktime(time.strptime(lastplayed, "%Y%m%dT%H%M%S"))
    except (ValueError, TypeError):
        return 0


def recent(limit=12):
    games = {}
    labels = {}
    for system, *_ in SYSTEMS:
        label, glist = _parse_gamelist(system)
        labels[system] = label
        for g in glist:
            ts = _ts(g["lastplayed"])
            if ts:
                games[g["path"]] = dict(g, ts=ts)
    for g in read_json(RECENTS_PATH, []) or []:
        prev = games.get(g.get("path"))
        if prev is None or g.get("ts", 0) > prev["ts"]:
            games[g["path"]] = dict(prev or {}, **g)
    out = []
    for g in sorted(games.values(), key=lambda g: -g["ts"]):
        if not os.path.exists(g["path"]):
            continue
        system = g["system"]
        direct = g.get("altemulator") in ("", None) and (labels.get(system) in (None, "") or
                                                        labels.get(system) in SUPPORTED_LABELS.get(system, ()))
        meta = SYSTEM_INDEX.get(system)
        out.append({"system": system, "systemName": meta[1] if meta else system, "short": meta[2] if meta else "",
                    "color": meta[3] if meta else "#888", "path": g["path"], "name": g["name"],
                    "ts": g["ts"], "cover": media(system, g["path"]), "direct": direct,
                    "resume": resume.has_resume(launch_target(g["path"]))})
        if len(out) >= limit:
            break
    return out


def remember(system, path, name):
    items = [g for g in (read_json(RECENTS_PATH, []) or []) if g.get("path") != path]
    items.insert(0, {"system": system, "path": path, "name": name, "ts": time.time()})
    write_json(RECENTS_PATH, items[:50])


def command(system, path):
    fn = COMMANDS.get(system)
    return fn(launch_target(path)) if fn else None


def set_startup(system=None):
    """Ouvre ES-DE directement sur un système (StartupSystem) ou sur la liste des systèmes."""
    try:
        with open(SETTINGS_XML, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        text = '<?xml version="1.0"?>\n'

    def put(text, kind, name, value):
        line = f'<{kind} name="{name}" value="{value}" />'
        pattern = re.compile(rf'<{kind} name="{re.escape(name)}" value="[^"]*" />')
        if pattern.search(text):
            return pattern.sub(line, text)
        return text.rstrip("\n") + "\n" + line + "\n"
    text = put(text, "string", "StartupSystem", system or "")
    text = put(text, "string", "StartupView", "gamelist" if system else "system")
    atomic_write(SETTINGS_XML, text)
