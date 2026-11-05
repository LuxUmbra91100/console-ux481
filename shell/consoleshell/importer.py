"""Ajout de jeux et de BIOS : reconnaissance et rangement automatiques.

Sert à l'envoi depuis un téléphone ou un PC (uploader.py) et à l'import depuis une clé USB (usb.py).

Un jeu est reconnu par son extension et, quand elle ne suffit pas (.iso, .chd, .bin…), par son
contenu : en-tête des disques GameCube/Wii (ISO, RVZ, WIA, GCZ, WBFS), SYSTEM.CNF des disques
PlayStation (BOOT = PS1, BOOT2 = PS2), type de disque d'un CHD (CD ou DVD). Les BIOS sont reconnus
par leur empreinte (PS1, GBA, DS) ou par leur table interne (PS2), quel que soit leur nom.

Rangement, comme ES-DE l'attend :
    ~/ROMs/<système>/<jeu>.<ext>                    un fichier par jeu
    ~/ROMs/psx/<jeu>.cue/   (le .cue et ses pistes)  un jeu en plusieurs fichiers ou sur plusieurs
    ~/ROMs/psx/<jeu>.m3u/   (le .m3u et les disques) disques : un dossier qu'ES-DE montre comme un
                                                     seul jeu (« dossier vu comme un fichier »)
    ~/BIOS/<nom attendu par l'émulateur>
    ~/ROMs/_À trier/                                 ce qui ressemble à un jeu sans être reconnu
"""
import hashlib
import os
import re
import shutil
import subprocess
import uuid
import zipfile
from dataclasses import dataclass, field

from .config import BIOS_DIR, ROMS_DIR, XDG_CACHE
from .util import log

TO_SORT = os.path.join(ROMS_DIR, "_À trier")
WORK_DIR = os.path.join(XDG_CACHE, "console", "import")
SYSTEM_NAMES = {"nes": "NES", "snes": "Super Nintendo", "n64": "Nintendo 64", "gb": "Game Boy",
                "gbc": "Game Boy Color", "gba": "Game Boy Advance", "nds": "Nintendo DS", "n3ds": "Nintendo 3DS",
                "gc": "GameCube", "wii": "Wii", "mastersystem": "Master System", "megadrive": "Mega Drive",
                "gamegear": "Game Gear", "psx": "PlayStation", "ps2": "PlayStation 2"}

# Extensions qui suffisent à reconnaître le système
EXT_SYSTEM = {
    ".nes": "nes", ".fds": "nes", ".unf": "nes", ".unif": "nes",
    ".sfc": "snes", ".smc": "snes", ".swc": "snes", ".fig": "snes",
    ".z64": "n64", ".n64": "n64", ".v64": "n64", ".ndd": "n64",
    ".gb": "gb", ".sgb": "gb", ".gbc": "gbc", ".cgb": "gbc",
    ".sms": "mastersystem", ".md": "megadrive", ".gen": "megadrive", ".smd": "megadrive", ".gg": "gamegear",
    ".gba": "gba", ".agb": "gba",
    ".nds": "nds", ".dsi": "nds", ".ids": "nds",
    ".3ds": "n3ds", ".cci": "n3ds", ".cxi": "n3ds", ".3dsx": "n3ds", ".z3dsx": "n3ds", ".zcci": "n3ds",
    ".zcxi": "n3ds",
    ".wbfs": "wii", ".wad": "wii", ".gcm": "gc", ".tgc": "gc",
    ".pbp": "psx", ".ecm": "psx", ".toc": "psx", ".cbn": "psx",
    ".cso": "ps2", ".zso": "ps2", ".isz": "ps2",
}
NINTENDO_DISC = {".rvz", ".wia", ".gcz", ".ciso"}          # GameCube ou Wii : en-tête
CONTENT = {".iso", ".bin", ".img", ".chd", ".mdf"}          # à lire pour savoir
GROUPS = {".cue", ".m3u", ".ccd"}
ARCHIVES = {".zip", ".7z"}
UNSUPPORTED = {
    ".rar": "archive .rar : décompresse-la d'abord sur ton PC",
    ".cia": "les .cia s'installent dans Azahar (Fichier › Installer un CIA)",
    ".nsp": "jeu Switch : pas pris en charge", ".xci": "jeu Switch : pas pris en charge",
}
# Sans rapport avec un jeu : ignoré sans bruit
JUNK = {".txt", ".nfo", ".diz", ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".svg", ".pdf",
        ".url", ".htm", ".html", ".sfv", ".md5", ".sha1", ".dat", ".xml", ".ini", ".cfg", ".log", ".db", ".lnk",
        ".exe", ".dll", ".msi", ".bat", ".sh", ".ds_store", ".torrent", ".srm", ".sav", ".state", ".mp4",
        ".mkv", ".avi", ".mov", ".wmv", ".webm", ".m4v", ".mp3", ".flac", ".wav", ".ogg", ".m4a", ".aac",
        ".wma", ".doc", ".docx", ".odt", ".rtf", ".xls", ".xlsx", ".ods", ".csv", ".ppt", ".pptx", ".odp",
        ".json", ".yml", ".yaml", ".md", ".py", ".js", ".css", ".epub", ".apk", ".deb", ".rpm", ".dmg",
        ".pkg", ".msu", ".pcm", ".srt", ".ass", ".ico", ".icns", ".tmp", ".bak", ".part", ".crdownload"}
SKIP_DIRS = {"system volume information", "$recycle.bin", "lost+found", ".trashes", ".spotlight-v100",
             ".fseventsd", ".trash-1000", "__macosx"}
MULTI_DISC = {"psx", "gc", "wii"}                             # émulateurs qui gèrent les .m3u
PS2_COMPANIONS = {".erom", ".rom1", ".rom2", ".nvm", ".mec"}

# BIOS reconnus à leur empreinte : (système, nom attendu, description)
BIOS_MD5 = {
    "8dd7d5296a650fac7319bce665a6a53c": ("psx", "scph5500.bin", "PS1 Japon"),
    "490f666e1afb15b7362b406ed1cea246": ("psx", "scph5501.bin", "PS1 USA"),
    "32736f17079d0b2b7024407c39bd3050": ("psx", "scph5502.bin", "PS1 Europe"),
    "c53ca5908936d412331790f4426c6c33": ("psx", "PSXONPSP660.bin", "PS1 (PSP, toutes régions)"),
    "81bbe60ba7a3d1cea1d48c14cbcc647b": ("psx", "ps1_rom.bin", "PS1 (PS3, toutes régions)"),
    "a860e8c0b6d573d191e4ec7db1b1e4f6": ("gba", "gba_bios.bin", "Game Boy Advance"),
    "df692a80a5b1bc90728bc3dfc76cd948": ("nds", "bios7.bin", "DS ARM7"),
    "a392174eb3e572fed6447e956bde4b25": ("nds", "bios9.bin", "DS ARM9"),
}
PS1_BIOS_REGION = {"scph5500.bin": "jp", "scph5501.bin": "us", "scph5502.bin": "eu"}
PS2_ZONES = {"J": "Japon", "A": "USA", "E": "Europe", "H": "Asie", "C": "Chine"}


def _read(path, offset, size):
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            return f.read(size)
    except OSError:
        return b""


def md5(path, limit=16 << 20):
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(1 << 20):
                h.update(chunk)
                limit -= len(chunk)
                if limit < 0:
                    return None
    except OSError:
        return None
    return h.hexdigest()


# ---------------------------------------------------------------- disques
def nintendo_disc(path):
    """« gc », « wii » ou None d'après l'en-tête (ISO, RVZ/WIA, GCZ, WBFS, CISO de Dolphin)."""
    head = _read(path, 0, 0x20)
    if head[:4] in (b"RVZ\x01", b"WIA\x01"):
        return {1: "gc", 2: "wii"}.get(int.from_bytes(_read(path, 0x48, 4), "big"))
    if head[:4] == b"\x01\xc0\x0b\xb1":                       # GCZ (0xB10BC001, petit-boutiste)
        return {0: "gc", 1: "wii"}.get(int.from_bytes(head[4:8], "little"))
    if head[:4] == b"WBFS":
        return "wii"
    if head[:4] == b"\xae\x0f\x38\xa2":                       # TGC
        return "gc"
    disc = _read(path, 0x8000, 0x20) if head[:4] == b"CISO" else head
    if disc[0x18:0x1c] == b"\x5d\x1c\x9e\xa3":
        return "wii"
    if disc[0x1c:0x20] == b"\xc2\x33\x9f\x3d":
        return "gc"
    return None


def _iso_layout(path):
    """(taille de secteur, décalage des données) d'une image ISO 9660 : 2048, ou 2352 brut (mode 2/1)."""
    for sector, offset in ((2048, 0), (2352, 24), (2352, 16)):
        if _read(path, 16 * sector + offset + 1, 5) == b"CD001":
            return sector, offset
    return None


def playstation_disc(path):
    """« psx », « ps2 » ou None : SYSTEM.CNF dit BOOT (PS1) ou BOOT2 (PS2)."""
    layout = _iso_layout(path)
    if not layout:
        return None
    sector, offset = layout

    def sectors(lba, count=1):
        return b"".join(_read(path, (lba + i) * sector + offset, 2048) for i in range(count))
    pvd = sectors(16)
    system_id = pvd[8:40].decode("ascii", "replace").strip()
    root = pvd[156:190]
    lba, size = int.from_bytes(root[2:6], "little"), int.from_bytes(root[10:14], "little")
    data = sectors(lba, max(1, min((size + 2047) // 2048, 8)))
    i, cnf = 0, None
    while i < len(data):
        n = data[i]
        if n == 0:
            i = (i // 2048 + 1) * 2048
            continue
        name = data[i + 33:i + 33 + data[i + 32]].decode("ascii", "replace").upper().split(";")[0]
        if name == "SYSTEM.CNF":
            flba, fsize = int.from_bytes(data[i + 2:i + 6], "little"), int.from_bytes(data[i + 10:i + 14], "little")
            cnf = sectors(flba)[:min(fsize, 2048)].decode("ascii", "replace")
            break
        i += n
    if cnf:
        if re.search(r"^\s*BOOT2\s*=", cnf, re.M | re.I):
            return "ps2"
        if re.search(r"^\s*BOOT\s*=", cnf, re.M | re.I):
            return "psx"
    if system_id.startswith("PLAYSTATION"):
        return "ps2" if os.path.getsize(path) > 900e6 else "psx"
    return None


def chd_system(path):
    """CHD : un DVD est un jeu PS2, un CD un jeu PS1 (sauf s'il est trop gros pour un CD)."""
    h = _read(path, 0, 124)
    if h[:8] != b"MComprHD":
        return None
    if int.from_bytes(h[12:16], "big") != 5:
        return "psx"
    logical = int.from_bytes(h[32:40], "big")
    meta, kind = int.from_bytes(h[48:56], "big"), None
    for _ in range(32):
        if not meta:
            break
        entry = _read(path, meta, 16)
        if entry[:4] in (b"CHT2", b"CHTR", b"CHCD", b"CHGT", b"CHGD"):
            kind = "cd"
            break
        if entry[:4] == b"DVD ":
            kind = "dvd"
            break
        meta = int.from_bytes(entry[8:16], "big")
    if kind == "dvd" or logical > 900e6:
        return "ps2"
    return "psx" if kind == "cd" else None


def disc_system(path):
    """Système d'un fichier de jeu seul, ou None s'il n'est pas reconnu."""
    ext = os.path.splitext(path)[1].lower()
    if ext in EXT_SYSTEM:
        return EXT_SYSTEM[ext]
    if ext in NINTENDO_DISC:
        return nintendo_disc(path) or ("ps2" if ext == ".ciso" else None)
    if ext == ".chd":
        return chd_system(path)
    if ext == ".bin" and _read(path, 0x100, 4) == b"SEGA":   # « SEGA MEGA DRIVE » / « SEGA GENESIS »
        return "megadrive"
    if ext == ".bin" and _read(path, 0, 4) in (b"\x80\x37\x12\x40", b"\x37\x80\x40\x12", b"\x40\x12\x37\x80"):
        return "n64"                                          # en-tête N64 (z64, v64, n64)
    if ext in (".iso", ".img", ".mdf", ".bin"):
        return (nintendo_disc(path) if ext == ".iso" else None) or playstation_disc(path)
    return None


# ---------------------------------------------------------------- BIOS
def ps2_bios(path):
    """Table interne d'un BIOS PS2 (comme PCSX2) : {« zone », « version », « date »} ou None."""
    size = os.path.getsize(path)
    if not 256 << 10 <= size <= 16 << 20:
        return None
    data = _read(path, 0, min(size, 8 << 20))
    for pos in range(0, len(data) - 16, 16):
        if data[pos:pos + 10] == b"RESET\x00\x00\x00\x00\x00":
            break
    else:
        return None
    offset, romver = 0, None
    for entry in range(pos, min(len(data) - 16, pos + 16 * 256), 16):
        name = data[entry:entry + 10]
        if not name[:1].strip(b"\x00") or b"\x00" not in name:
            break
        fsize = int.from_bytes(data[entry + 12:entry + 16], "little")
        if name.rstrip(b"\x00") == b"ROMVER":
            romver = data[offset:offset + 14].decode("ascii", "replace")
        offset += fsize if fsize % 16 == 0 else (fsize + 16) & ~15
    if not romver or not romver[:4].isdigit():
        return None
    return {"zone": PS2_ZONES.get(romver[4], romver[4]), "version": f"{int(romver[:2])}.{romver[2:4]}",
            "date": f"{romver[12:14]}/{romver[10:12]}/{romver[6:10]}"}


def bios_info(path):
    """{system, name, desc} si le fichier est un BIOS connu, sinon None."""
    size = os.path.getsize(path)
    ext = os.path.splitext(path)[1].lower()
    if ext in PS2_COMPANIONS:
        return {"system": "ps2", "name": os.path.basename(path), "desc": "PS2 (fichier complémentaire)"}
    if size <= 1 << 20:
        known = BIOS_MD5.get(md5(path) or "")
        if known:
            return {"system": known[0], "name": known[1], "desc": known[2]}
        if size == 512 << 10 and re.fullmatch(r"scph\d{3,5}[a-z]?\.bin", os.path.basename(path).lower()):
            return {"system": "psx", "name": os.path.basename(path).lower(), "desc": "PS1 (version non vérifiée)"}
    ps2 = ps2_bios(path) if ext in (".bin", ".rom", "") or size in (4 << 20, 8 << 20) else None
    if ps2:
        return {"system": "ps2", "name": os.path.basename(path), "desc": f"PS2 {ps2['zone']} v{ps2['version']}",
                **ps2}
    return None


# ---------------------------------------------------------------- plan
@dataclass
class Item:
    kind: str                       # game | bios | archive | to_sort | ignored | unsupported
    label: str
    sources: list                   # fichiers d'origine
    system: str = None
    dest: str = None                # fichier ou dossier final
    rel: dict = field(default_factory=dict)   # source → chemin relatif dans le dossier du jeu
    write: dict = field(default_factory=dict)  # fichiers générés (.m3u, .cue) : nom → texte
    note: str = ""
    status: str = "new"             # new | present

    @property
    def size(self):
        total = 0
        for s in self.sources:
            try:
                total += os.path.getsize(s)
            except OSError:
                pass
        return total

    def public(self):
        return {"kind": self.kind, "label": self.label, "system": self.system, "status": self.status,
                "note": self.note, "size": self.size}


def _files(root):
    if os.path.isfile(root):
        return [root]
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        depth = dirpath[len(root):].count(os.sep)
        dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS and not d.startswith(".") and depth < 6]
        out += [os.path.join(dirpath, f) for f in filenames if not f.startswith((".", "._"))]
    return sorted(out)


def _find(base_dir, name):
    """Fichier référencé par un .cue ou un .m3u (casse ignorée si besoin)."""
    path = os.path.normpath(os.path.join(base_dir, name.replace("\\", "/")))
    if os.path.exists(path):
        return path
    folder, wanted = os.path.dirname(path), os.path.basename(path).lower()
    try:
        for f in os.listdir(folder):
            if f.lower() == wanted:
                return os.path.join(folder, f)
    except OSError:
        pass
    return None


def cue_files(cue):
    try:
        with open(cue, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return []
    names = re.findall(r'^\s*FILE\s+(?:"([^"]+)"|(\S+))', text, re.M | re.I)
    return [_find(os.path.dirname(cue), a or b) for a, b in names]


def m3u_files(m3u):
    try:
        with open(m3u, encoding="utf-8", errors="replace") as f:
            lines = [ln.strip() for ln in f]
    except OSError:
        return []
    return [_find(os.path.dirname(m3u), ln) for ln in lines if ln and not ln.startswith("#")]


DISC_TAG = re.compile(r"\s*[\(\[](?:disc|disk|cd)\s*(\d+)(?:\s*of\s*\d+)?[\)\]]", re.I)


def _disc(name):
    m = DISC_TAG.search(name)
    return int(m.group(1)) if m else None


def _title(name):
    """Nom d'un jeu sans extension ni mention de disque : « Final Fantasy VII (France) »."""
    return DISC_TAG.sub("", os.path.splitext(os.path.basename(name))[0]).strip()


def _present_size(path):
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for dirpath, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def _place(item, dest):
    """Destination libre : identique et déjà là → « présent » ; sinon nom suivi de « (2) »…"""
    if os.path.lexists(dest):
        if _present_size(dest) == item.size + sum(len(t.encode()) for t in item.write.values()):
            item.status = "present"
            return dest
        stem, ext = os.path.splitext(dest)
        n = 2
        while os.path.lexists(f"{stem} ({n}){ext}"):
            n += 1
        dest = f"{stem} ({n}){ext}"
    return dest


def plan(root):
    """Ce qu'il y a à importer depuis un dossier ou un fichier : liste d'Item."""
    files = _files(root)
    used, items, groups = set(), [], []

    def group_of(kind_files, main):
        """Fichiers d'un jeu en plusieurs morceaux, ou None si un morceau manque."""
        if not kind_files or any(f is None for f in kind_files):
            return None
        return [main] + [f for f in kind_files if f != main]

    # 1) Listes de disques (.m3u), puis .cue et .ccd : un jeu = un groupe de fichiers
    for f in files:
        ext = os.path.splitext(f)[1].lower()
        if f in used or ext not in GROUPS:
            continue
        if ext == ".m3u":
            refs = m3u_files(f)
            parts = list(refs)
            for r in refs:
                if r and r.lower().endswith(".cue"):
                    parts += cue_files(r)
        elif ext == ".cue":
            parts = cue_files(f)
        else:                                               # CloneCD : .ccd + .img + .sub
            stem = os.path.splitext(f)[0]
            parts = [p for p in (stem + ".img", stem + ".sub") if os.path.exists(p)]
        members = group_of(parts, f)
        if members is None:
            items.append(Item("to_sort", os.path.basename(f), [f], note="fichiers du jeu incomplets"))
            used.add(f)
            continue
        used.update(members)
        groups.append((ext, f, members))
    for ext, main, members in groups:
        # Le système se lit sur le premier disque (première piste d'un .cue, image d'un .ccd).
        probe = m3u_files(main)[0] if ext == ".m3u" else main
        if probe.lower().endswith(".cue"):
            probe = (cue_files(probe) or [probe])[0]
        elif probe.lower().endswith(".ccd"):
            probe = os.path.splitext(probe)[0] + ".img"
        system = disc_system(probe)
        if not system:
            items.append(Item("to_sort", os.path.basename(main), members, note="disque non reconnu"))
            continue
        items.append(Item("game", _title(main) if ext == ".m3u" else os.path.splitext(os.path.basename(main))[0],
                          members, system=system, note=ext))

    # 2) Fichiers seuls
    for f in files:
        if f in used:
            continue
        ext = os.path.splitext(f)[1].lower()
        name = os.path.basename(f)
        if ext in JUNK or name.lower() in ("thumbs.db", "desktop.ini"):
            items.append(Item("ignored", name, [f]))
            continue
        if ext in UNSUPPORTED:
            items.append(Item("unsupported", name, [f], note=UNSUPPORTED[ext]))
            continue
        if ext in ARCHIVES:
            item = Item("archive", name, [f])
            if archive_present(f):
                item.status = "present"                      # déjà importée (ou rien d'utile dedans)
            items.append(item)
            continue
        bios = bios_info(f) if ext not in EXT_SYSTEM and ext not in NINTENDO_DISC and ext != ".chd" else None
        if bios:
            items.append(Item("bios", bios["desc"], [f], system=bios["system"], note=bios["name"]))
            continue
        system = disc_system(f)
        if system:
            items.append(Item("game", os.path.splitext(name)[0], [f], system=system))
        elif ext in CONTENT or ext in (".elf", ".app", ".dol", ".mds", ".gz", ".sub"):
            items.append(Item("to_sort", name, [f], note="pas reconnu"))
        elif ext and len(ext) <= 6 and os.path.getsize(f) >= 4096:
            # Extension inconnue : peut-être un jeu d'une console pas encore prise en charge. Mieux vaut
            # le garder de côté (et le dire) que de l'écarter sans prévenir.
            items.append(Item("to_sort", name, [f], note=f"format {ext} pas pris en charge"))
        else:
            items.append(Item("ignored", name, [f]))

    # 3) Jeux sur plusieurs disques : un .m3u, pour changer de disque depuis l'émulateur
    discs = {}
    for it in items:
        if it.kind == "game" and it.system in MULTI_DISC and it.note != ".m3u" and _disc(it.label):
            discs.setdefault((it.system, _title(it.label)), []).append(it)
    for (system, title), parts in discs.items():
        numbers = sorted(_disc(p.label) for p in parts)
        if len(parts) < 2 or len(set(numbers)) != len(numbers):
            continue
        parts.sort(key=lambda p: _disc(p.label))
        merged = Item("game", title, [s for p in parts for s in p.sources], system=system, note=".m3u")
        merged.write = {title + ".m3u": "".join(os.path.basename(p.sources[0]) + "\n" for p in parts)}
        for p in parts:
            items.remove(p)
        items.append(merged)

    # 4) Destinations
    for it in items:
        main = it.sources[0]
        if it.kind == "game":
            sysdir = os.path.join(ROMS_DIR, it.system)
            if len(it.sources) == 1 and not it.write:
                it.dest = _place(it, os.path.join(sysdir, os.path.basename(main)))
                continue
            # Plusieurs fichiers : « dossier vu comme un fichier », nommé comme le fichier à lancer
            # (.cue, .m3u…), qui garde les chemins relatifs attendus par le .cue ou le .m3u.
            if it.write:                                    # .m3u créé ici : disques à plat
                it.rel = {s: os.path.basename(s) for s in it.sources}
                launch = next(iter(it.write))
            else:
                base = os.path.dirname(main)
                for s in it.sources:
                    rel = os.path.relpath(s, base)
                    it.rel[s] = rel if not rel.startswith("..") else os.path.basename(s)
                launch = os.path.basename(main)
            it.dest = _place(it, os.path.join(sysdir, launch))
        elif it.kind == "bios":
            it.dest = os.path.join(BIOS_DIR, it.note)
            if os.path.exists(it.dest) and md5(it.dest) == md5(main):
                it.status = "present"
            elif os.path.exists(it.dest):
                it.dest = _place(it, it.dest)
        elif it.kind == "to_sort":
            if len(it.sources) > 1:
                it.rel = {s: os.path.basename(s) for s in it.sources}
                it.dest = _place(it, os.path.join(TO_SORT, os.path.splitext(os.path.basename(main))[0]))
            else:
                it.dest = _place(it, os.path.join(TO_SORT, os.path.basename(main)))
    return items


def summary(items, keep_unknown=True):
    """Résumé pour l'écran de la TV : jeux par système, BIOS, à trier, taille à copier."""
    games, bios, size = {}, [], 0
    for it in items:
        if it.kind == "game" and it.status == "new":
            games[it.system] = games.get(it.system, 0) + 1
            size += it.size
        elif it.kind == "bios" and it.status == "new":
            bios.append(it.label)
            size += it.size
        elif it.status == "new" and (it.kind == "archive" or (it.kind == "to_sort" and keep_unknown)):
            size += it.size
    return {"games": games, "bios": bios, "size": size,
            "archives": sum(1 for it in items if it.kind == "archive" and it.status == "new"),
            "present": sum(1 for it in items if it.kind in ("game", "bios") and it.status == "present"),
            "to_sort": sum(1 for it in items if it.kind == "to_sort"),
            "unsupported": [it.note for it in items if it.kind == "unsupported"]}


# ---------------------------------------------------------------- copie
class Cancelled(Exception):
    pass


class Progress:
    """Octets copiés sur le total, rapportés au plus 4 fois par seconde."""

    def __init__(self, total, callback=None, cancel=None):
        import time
        self.time = time
        self.total, self.done, self.callback, self.cancel = max(total, 1), 0, callback, cancel
        self.label, self._last, self.cancelled = "", 0.0, False

    def add(self, n, force=False):
        self.done += n
        if self.cancel is not None and self.cancel.is_set():
            raise Cancelled()
        now = self.time.monotonic()
        if self.callback and (force or now - self._last > 0.25):
            self._last = now
            self.callback(min(self.done, self.total), self.total, self.label)


def _copy(src, dst, progress, move):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if move:
        try:
            os.replace(src, dst)
            progress.add(os.path.getsize(dst))
            return
        except OSError:
            pass                                             # autre disque : copie
    tmp = dst + ".part"
    try:
        with open(src, "rb") as fi, open(tmp, "wb") as fo:
            while chunk := fi.read(4 << 20):
                fo.write(chunk)
                progress.add(len(chunk))
        os.replace(tmp, dst)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    if move:
        os.unlink(src)


def execute(items, move=False, progress=None, keep_unknown=True):
    """Range les éléments prévus. Renvoie la liste des résultats (pour l'écran et la page web).
    keep_unknown=False : ce qui n'est pas reconnu n'est pas copié (clé USB : il y reste)."""
    progress = progress or Progress(1)
    results = []
    for it in items:
        if it.kind not in ("game", "bios", "to_sort") or it.status == "present" or \
                (it.kind == "to_sort" and not keep_unknown):
            if it.kind != "archive":
                results.append(it.public())
            continue
        progress.label = it.label
        try:
            if it.rel:                                       # jeu en plusieurs fichiers : un dossier
                for src in it.sources:
                    _copy(src, os.path.join(it.dest, it.rel[src]), progress, move)
            else:
                _copy(it.sources[0], it.dest, progress, move)
            for name, text in it.write.items():
                with open(os.path.join(it.dest, name), "w", encoding="utf-8") as f:
                    f.write(text)
            res = it.public()
            res["status"] = "added"
        except Cancelled:
            progress.cancelled = True                        # arrêt demandé : on garde ce qui est fait
            break
        except OSError as exc:
            log.warning("import de %s : %s", it.label, exc)
            res = it.public()
            res["status"] = "error"
            res["note"] = "plus de place sur la console" if exc.errno == 28 else str(exc.strerror or exc)
            results.append(res)
            if exc.errno == 28:
                break
            continue
        results.append(res)
    return results


# ---------------------------------------------------------------- archives
def _seven_zip():
    return next((b for b in ("7z", "7zz", "7za") if shutil.which(b)), None)


def extract(archive, dest):
    """Décompresse une archive .zip ou .7z dans dest. Lève OSError si impossible."""
    os.makedirs(dest, exist_ok=True)
    if archive.lower().endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            need = sum(i.file_size for i in z.infolist())
            if shutil.disk_usage(dest).free < need + (512 << 20):
                raise OSError(28, "plus de place pour décompresser")
            z.extractall(dest)                               # noms « ../ » neutralisés par zipfile
        return
    tool = _seven_zip()
    if not tool:
        raise OSError(2, "7-Zip absent : relance la mise à jour de la console")
    code = subprocess.run([tool, "x", "-y", "-bd", f"-o{dest}", "--", archive], stdout=subprocess.DEVNULL,
                          stderr=subprocess.PIPE, timeout=3600).returncode
    if code not in (0, 1):
        raise OSError(5, "archive illisible")
    for dirpath, dirnames, filenames in os.walk(dest):        # pas de liens symboliques venus d'une archive
        for name in dirnames + filenames:
            p = os.path.join(dirpath, name)
            if os.path.islink(p):
                os.unlink(p)


def archive_names(path):
    """Fichiers contenus dans une archive, sans la décompresser (None si illisible)."""
    if path.lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(path) as z:
                return [i.filename for i in z.infolist() if not i.is_dir()]
        except (OSError, zipfile.BadZipFile):
            return None
    tool = _seven_zip()
    if not tool:
        return None
    try:
        proc = subprocess.run([tool, "l", "-ba", "-slt", "--", path], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return [ln[7:] for ln in proc.stdout.splitlines() if ln.startswith("Path = ")]


def archive_present(path):
    """Tout ce que l'archive contient d'utile est déjà dans la bibliothèque (ou dans BIOS) ?"""
    names = archive_names(path)
    if names is None:
        return False
    import glob
    for n in names:
        base = os.path.basename(n.replace("\\", "/"))
        if not base or base.startswith(".") or os.path.splitext(base)[1].lower() in JUNK:
            continue
        pattern = glob.escape(base)
        if not (glob.glob(os.path.join(ROMS_DIR, "*", pattern)) or glob.glob(os.path.join(ROMS_DIR, "*", "*", pattern))
                or os.path.exists(os.path.join(BIOS_DIR, base))):
            return False
    return True


def import_tree(root, move=False, progress=None, depth=0):
    """Importe tout ce qui est reconnu dans root (archives comprises). Renvoie les résultats."""
    return import_items(plan(root), move=move, progress=progress, depth=depth)


def import_items(items, move=False, progress=None, depth=0, keep_unknown=True):
    """Range des éléments déjà analysés (plan), puis décompresse et range le contenu des archives."""
    results = execute(items, move=move, progress=progress, keep_unknown=keep_unknown)
    for it in items:
        if it.kind != "archive" or it.status == "present":
            continue
        if progress is not None and progress.cancelled:
            break
        tmp = os.path.join(WORK_DIR, "archive-" + uuid.uuid4().hex[:8])
        try:
            if progress:
                progress.label = it.label
            extract(it.sources[0], tmp)
            sub = import_items(plan(tmp), move=True, depth=depth + 1, keep_unknown=keep_unknown) if depth < 2 else []
            if progress:
                try:
                    progress.add(it.size, force=True)
                except Cancelled:
                    progress.cancelled = True
            results.append({"kind": "archive", "label": it.label, "status": "added" if sub else "empty",
                            "note": "", "system": None, "size": it.size})
            results += sub
            if move:
                os.unlink(it.sources[0])
        except Cancelled:
            raise
        except (OSError, zipfile.BadZipFile, subprocess.TimeoutExpired) as exc:
            results.append({"kind": "archive", "label": it.label, "status": "error", "system": None,
                            "size": it.size, "note": str(getattr(exc, "strerror", None) or exc)})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return results


# ---------------------------------------------------------------- état des BIOS
def _regions_of_games(system):
    from .covers import tag_info                             # régions écrites dans le nom des jeux
    pal = {"eu", "fr", "de", "es", "it", "uk", "nl", "se", "nordic", "au", "be", "ch", "pt", "pl", "gr", "dk", "ru"}
    count = {"eu": 0, "us": 0, "jp": 0}
    try:
        names = os.listdir(os.path.join(ROMS_DIR, system))
    except OSError:
        return count
    for n in names:
        if n.startswith(".") or n.startswith("_"):
            continue
        regions = tag_info(n)["regions"]
        if regions & pal or "world" in regions:
            count["eu"] += 1
        elif regions & {"us", "ca"}:
            count["us"] += 1
        elif "jp" in regions:
            count["jp"] += 1
    return count


def bios_status():
    """État des BIOS pour Réglages › Jeux."""
    found = {"psx": {}, "ps2": [], "nds": [], "gba": [], "unknown": []}
    try:
        names = sorted(os.listdir(BIOS_DIR))
    except OSError:
        names = []
    for n in names:
        path = os.path.join(BIOS_DIR, n)
        if n.startswith(".") or not os.path.isfile(path):
            continue
        info = bios_info(path)
        if not info:
            found["unknown"].append(n)
        elif info["system"] == "psx":
            region = PS1_BIOS_REGION.get(n)
            if region or n in ("PSXONPSP660.bin", "ps1_rom.bin"):
                found["psx"][region or "all"] = n
        elif info["system"] == "ps2" and "zone" in info:
            found["ps2"].append({"file": n, "zone": info["zone"], "version": info["version"], "date": info["date"]})
        elif info["system"] in ("nds", "gba"):
            found[info["system"]].append(n)
    games = _regions_of_games("psx")
    missing = [r for r in ("eu", "us", "jp") if games[r] and r not in found["psx"]]
    return {"psx": {"have": found["psx"], "games": games, "missing": missing},
            "ps2": {"have": found["ps2"], "games": len(_list_games("ps2"))},
            "nds": found["nds"], "gba": found["gba"], "unknown": found["unknown"]}


def _list_games(system):
    try:
        return [n for n in os.listdir(os.path.join(ROMS_DIR, system)) if not n.startswith((".", "_"))]
    except OSError:
        return []
