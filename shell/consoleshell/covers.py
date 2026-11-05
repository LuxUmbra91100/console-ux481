"""Jaquettes automatiques depuis la base libre de libretro (thumbnails.libretro.com), sans compte.

Pour chaque jeu de ~/ROMs qui n'a pas encore d'image, on cherche dans la liste des images de son
système le titre le plus proche : même nom de fichier, sinon même titre une fois normalisé (accents,
ponctuation, articles, chiffres romains, mentions entre parenthèses ignorés), sinon un titre qui
contient tous ses mots. Entre plusieurs versions, on préfère la région du jeu, puis France, Europe,
Monde, USA, Japon, et jamais une démo ou un prototype si le jeu n'en est pas un.

Les images vont là où ES-DE et l'accueil les cherchent :
    ~/ES-DE/downloaded_media/<système>/covers/<chemin du jeu sans extension>.png       (jaquette)
    ~/ES-DE/downloaded_media/<système>/screenshots/<chemin du jeu sans extension>.png  (image du jeu)

Les listes de noms sont gardées 30 jours ; un jeu sans correspondance n'est recherché à nouveau
qu'avec une liste plus récente. Si le serveur de libretro ne répond pas, on passe par les dépôts
GitHub dont il est la copie (mêmes noms de fichiers).
"""
import difflib
import html
import json
import os
import posixpath
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from .config import ROMS_DIR, XDG_CACHE
from .library import MEDIA_DIR, SYSTEM_INDEX, dir_as_file
from .util import atomic_write, log, read_json, write_json

SERVER = "https://thumbnails.libretro.com"
GITHUB_RAW = "https://raw.githubusercontent.com/libretro-thumbnails"
GITHUB_API = "https://api.github.com/repos/libretro-thumbnails"
SYSTEM_NAMES = {
    "nes": "Nintendo - Nintendo Entertainment System",
    "snes": "Nintendo - Super Nintendo Entertainment System",
    "n64": "Nintendo - Nintendo 64",
    "gb": "Nintendo - Game Boy",
    "gbc": "Nintendo - Game Boy Color",
    "mastersystem": "Sega - Master System - Mark III",
    "megadrive": "Sega - Mega Drive - Genesis",
    "gamegear": "Sega - Game Gear",
    "gba": "Nintendo - Game Boy Advance",
    "nds": "Nintendo - Nintendo DS",
    "n3ds": "Nintendo - Nintendo 3DS",
    "gc": "Nintendo - GameCube",
    "wii": "Nintendo - Wii",
    "psx": "Sony - PlayStation",
    "ps2": "Sony - PlayStation 2",
}
KINDS = (("covers", "Named_Boxarts"), ("screenshots", "Named_Snaps"))   # dossier ES-DE, dossier libretro
IMAGE_EXTS = (".png", ".jpg", ".webp")
CACHE_DIR = os.path.join(XDG_CACHE, "console", "covers")
MISSES_PATH = os.path.join(CACHE_DIR, "misses.json")
LIST_TTL = 30 * 86400
USER_AGENT = "console-ux481/1 (jaquettes)"

# ------------------------------------------------------------------ titres
_TAGS = re.compile(r"[\(\[]([^\)\]]*)[\)\]]")
_STOP = {"the", "a", "an", "and", "of", "le", "la", "les", "l", "de", "des", "du", "et"}
_ROMAN = {r: str(i) for i, r in enumerate(
    "_ _ ii iii iv v vi vii viii ix x xi xii xiii xiv xv xvi xvii xviii xix xx".split()) if len(r) > 1}
# Mots qu'un titre libretro peut avoir en plus sans que ce soit un autre jeu (« Pokemon - Emerald Version »).
_EXTRA_OK = {"version", "edition"}
# Régions : préférences pour une console française (plus haut = mieux).
_PREF = {"fr": 6, "eu": 5, "world": 4, "us": 3, "uk": 5}
_REGION_WORDS = {
    "france": "fr", "europe": "eu", "world": "world", "usa": "us", "japan": "jp", "germany": "de",
    "spain": "es", "italy": "it", "uk": "uk", "united kingdom": "uk", "australia": "au", "korea": "kr",
    "canada": "ca", "netherlands": "nl", "sweden": "se", "scandinavia": "nordic", "brazil": "br",
    "china": "cn", "asia": "asia", "russia": "ru", "taiwan": "tw", "hong kong": "hk", "belgium": "be",
    "switzerland": "ch", "portugal": "pt", "poland": "pl", "greece": "gr", "denmark": "dk",
}
# Codes de région GoodTools : (E), (U), (F), (UE), (JUE)…
_GOODTOOLS = {"e": "eu", "u": "us", "j": "jp", "f": "fr", "g": "de", "s": "es", "i": "it", "w": "world",
              "k": "kr", "a": "au", "uk": "uk"}
_GOODTOOLS_MULTI = {"ue", "eu", "ju", "uj", "je", "ej", "jue", "jeu", "uje", "uej", "eju", "euj"}
# Versions à éviter quand le jeu lui-même n'en est pas une (on compare le début de la mention).
_BAD = ("beta", "proto", "demo", "sample", "kiosk", "debug", "alt", "bonus", "pirate", "unl", "hack",
        "preview", "promo", "competition", "taikenban", "trial")
_PAREN = re.compile(r"\(([^\)]*)\)")


def sanitize(stem):
    """Règle de nommage libretro : ces caractères deviennent « _ » dans les noms d'image."""
    return re.sub(r'[&*/:`<>?\\|"]', "_", stem)


def _ascii(text):
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def title_tokens(name):
    """« Legend of Zelda, The - The Minish Cap (Europe) » → ['legend', 'zelda', 'minish', 'cap']."""
    base = _TAGS.sub(" ", name)
    base = _ascii(base).lower().replace("'", "")
    return [_ROMAN.get(t, t) for t in re.findall(r"[a-z0-9]+", base) if t not in _STOP]


def title_key(name):
    return " ".join(title_tokens(name))


def tag_info(name):
    """Régions, langues, disque et mentions indésirables (démo, proto…) d'un nom de jeu.

    Seules les mentions entre parenthèses comptent : les crochets de GoodTools ([!], [b1]…) ne
    décrivent que le fichier, et les noms libretro n'en ont pas."""
    regions, langs, bad, disc, rev = set(), set(), set(), None, False
    for raw in _PAREN.findall(name):
        tag = raw.strip().lower()
        m = re.fullmatch(r"(?:disc|disk|cd)\s*(\d+)(?:\s+of\s+\d+)?", tag)
        if m:
            disc = int(m.group(1))
            continue
        if re.fullmatch(r"rev\s*[\w.]+|v\d+(\.\d+)*", tag):
            rev = True
            continue
        if tag in _GOODTOOLS or tag in _GOODTOOLS_MULTI:
            regions |= {_GOODTOOLS[c] for c in (tag if tag in _GOODTOOLS_MULTI else [tag])}
            continue
        parts = [p.strip() for p in re.split(r"[,+]", tag) if p.strip()]
        found = {_REGION_WORDS[p] for p in parts if p in _REGION_WORDS}
        if found:
            regions |= found                                     # (USA, Europe)
            continue
        if parts and all(re.fullmatch(r"[a-z]{2}(-[a-z]{2,4})?", p) for p in parts):
            langs.update(p[:2] for p in parts)                   # (En,Fr,De)
            continue
        hit = next((b for b in _BAD if tag.startswith(b)), None)
        if hit:
            bad.add(hit)
    return {"regions": regions, "langs": langs, "bad": bad, "disc": disc, "rev": rev}


def _score(rom, name):
    c = tag_info(name)
    s = 0
    if rom["regions"] and c["regions"] & rom["regions"]:
        s += 40
    s += max((_PREF.get(r, 1) for r in c["regions"]), default=2)
    if "fr" in c["langs"]:
        s += 2
    if rom["disc"]:
        s += 20 if c["disc"] == rom["disc"] else (-15 if c["disc"] else 0)
    else:
        s += 8 if c["disc"] is None else (4 if c["disc"] == 1 else -5)
    s -= 30 * len(c["bad"] - rom["bad"])
    if c["rev"] and not rom["rev"]:
        s -= 1
    return (s, -len(name), name)


_BARE_DISC = re.compile(r"(?:^|[\s\-_,])(?:disc|disk|cd)\s*(\d+)\b", re.I)


def _variants(stem):
    """Titres à essayer pour un nom de fichier : tel quel, puis sans numéro de sortie (« 1986 - … »),
    sans « _ » ni mention de disque hors parenthèses (« Final Fantasy 7 - Disc 1 »)."""
    out = [stem]
    alt = re.sub(r"^\s*#?\d{3,4}\s+-\s+", "", stem.replace("_", " "))
    alt = _BARE_DISC.sub(" ", alt).strip(" -")
    if alt and alt != stem:
        out.append(alt)
    return out


def _disc(stem):
    """Numéro de disque d'un nom de jeu : « (Disc 2) », ou « - Disc 2 » / « CD2 » hors parenthèses."""
    disc = tag_info(stem)["disc"]
    if disc is None:
        m = _BARE_DISC.search(_TAGS.sub(" ", stem))
        disc = int(m.group(1)) if m else None
    return disc


def _numbers(key):
    return {t for t in key.split() if t.isdigit()}


def _in_order(small, big):
    """Les mots de « small » apparaissent dans « big », dans le même ordre."""
    it = iter(big)
    return all(w in it for w in small)


def _main_title(stem):
    """« Advance Wars 2 - Black Hole Rising (Europe) » → « advance wars 2 »."""
    head = _TAGS.sub(" ", stem).split(" - ", 1)[0]
    return title_key(head)


class Index:
    """Liste des images d'un système, interrogeable par nom de jeu."""

    def __init__(self, names):
        self.names = set(names)
        self.by_key, self.by_joined, self.by_token, self.by_main = {}, {}, {}, {}
        for n in names:
            stem = os.path.splitext(n)[0]
            k = title_key(stem)
            if not k:
                continue
            self.by_key.setdefault(k, []).append(n)
            self.by_joined.setdefault(k.replace(" ", ""), set()).add(k)
            self.by_main.setdefault(_main_title(stem), set()).add(k)
            for t in set(k.split()):
                self.by_token.setdefault(t, set()).add(k)
        self.keys = list(self.by_key)

    def _contained(self, k):
        toks = set(k.split())
        if len(toks) < 2:
            return []
        sets = [self.by_token.get(t) for t in toks]
        if not all(sets):
            return []
        # Mêmes mots dans le même ordre, et pas de numéro en plus (« Top Spin » n'est pas « Top Spin 2 »).
        words = k.split()
        cands = {c for c in set.intersection(*sets)
                 if _in_order(words, c.split()) and not _numbers(" ".join(set(c.split()) - toks))}
        harmless = sorted((len(set(c.split()) - toks), c) for c in cands if set(c.split()) - toks <= _EXTRA_OK)
        if harmless and (len(harmless) == 1 or harmless[0][0] < harmless[1][0]):
            return [harmless[0][1]]
        # Le titre libretro a quelques mots de plus (« Zelda Minish Cap » → « Legend of Zelda, The - The
        # Minish Cap ») : accepté seulement si c'est le seul titre qui contient tous les mots.
        if len(cands) == 1:
            c = next(iter(cands))
            if len(set(c.split()) - toks) <= 3:
                return [c]
        return []

    def _close(self, k):
        """Faute de frappe : même nombre de mots, chacun presque identique, et les mots courts ou les
        numéros exactement pareils (« Fire Pro Wrestling Z » n'est pas « … A », « 2 » n'est pas « 3 »)."""
        a = k.split()
        for c in difflib.get_close_matches(k, self.keys, n=3, cutoff=0.9):
            b = c.split()
            if len(a) == len(b) and all(x == y or (len(x) > 3 and difflib.SequenceMatcher(None, x, y).ratio() >= 0.8)
                                        for x, y in zip(a, b)):
                return [c]
        return []

    def match(self, rom_file):
        """Nom de l'image libretro la plus proche de ce fichier de jeu, ou None."""
        stem = os.path.splitext(os.path.basename(rom_file))[0]
        exact = sanitize(stem)
        for ext in (".png", ".jpg", ".JPG"):
            if exact + ext in self.names:
                return exact + ext
        info = tag_info(stem)
        info["disc"] = _disc(stem)
        for title in _variants(stem):
            k = title_key(title)
            if not k:
                continue
            keys = [k] if k in self.by_key else sorted(self.by_joined.get(k.replace(" ", ""), ()))
            if not keys and len(self.by_main.get(k, ())) == 1:
                keys = list(self.by_main[k])                    # « Advance Wars 2 » → « … 2 - Black Hole Rising »
            if not keys:
                keys = self._contained(k)
            if not keys:
                keys = self._close(k)
            if keys:
                return max((n for kk in keys for n in self.by_key[kk]), key=lambda n: _score(info, n))
        return None

    def match_path(self, rom_file, folder=None):
        """Comme match(), puis d'après le dossier du jeu s'il en a un (« Final Fantasy VII (France)/FF7 - Disc 1.cue »)."""
        name = self.match(rom_file)
        if name is None and folder:
            disc = _disc(os.path.splitext(os.path.basename(rom_file))[0])
            name = self.match(folder + (f" (Disc {disc})" if disc else "") + ".dossier")
        return name


# --------------------------------------------------------------- réseau
def _get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_index(text):
    """Noms d'images d'une page d'index (« Index of … ») du serveur libretro."""
    names = []
    for href in re.findall(r'href="([^"?#]+)"', text):
        name = urllib.parse.unquote(html.unescape(href)).rsplit("/", 1)[-1]
        if name.lower().endswith((".png", ".jpg")):
            names.append(name)
    return names


def _repo(system):
    return SYSTEM_NAMES[system].replace(" ", "_")


def _list_server(system, folder):
    url = f"{SERVER}/{urllib.parse.quote(SYSTEM_NAMES[system])}/{folder}/"
    return parse_index(_get(url, timeout=60).decode("utf-8", "replace"))


def _list_github(system, folder):
    root = json.loads(_get(f"{GITHUB_API}/{_repo(system)}/git/trees/master"))
    sha = next(e["sha"] for e in root["tree"] if e["path"] == folder)
    sub = json.loads(_get(f"{GITHUB_API}/{_repo(system)}/git/trees/{sha}", timeout=60))
    return [e["path"] for e in sub["tree"] if e.get("type") == "blob"]


def listing(system, folder, max_age=LIST_TTL):
    """{"ts", "source", "names"} depuis le cache, sinon depuis le réseau ; None si injoignable."""
    path = os.path.join(CACHE_DIR, f"{system}-{folder}.json")
    cached = read_json(path, None)
    if cached and time.time() - cached.get("ts", 0) < max_age and cached.get("names"):
        return cached
    for source, fn in (("libretro", _list_server), ("github", _list_github)):
        try:
            names = fn(system, folder)
        except (OSError, ValueError, KeyError, StopIteration) as exc:
            log.info("jaquettes : liste %s/%s indisponible chez %s (%s)", system, folder, source, exc)
            continue
        if names:
            data = {"ts": time.time(), "source": source, "names": names}
            write_json(path, data)
            return data
    return cached if cached and cached.get("names") else None       # vieille liste plutôt que rien


def _valid_image(data):
    return 1000 < len(data) < 12_000_000 and (data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff"))


def _url(source, system, path):
    if source == "libretro":
        return f"{SERVER}/{urllib.parse.quote(SYSTEM_NAMES[system])}/{urllib.parse.quote(path)}"
    return f"{GITHUB_RAW}/{_repo(system)}/master/{urllib.parse.quote(path)}"


def _link_target(data, path):
    """Les dépôts libretro partagent une même image entre versions par des liens symboliques : GitHub
    renvoie alors juste le nom de la cible (« Final Fantasy VII (Europe).png »)."""
    if len(data) > 400:
        return None
    try:
        target = data.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None
    if "\n" in target or not target.lower().endswith((".png", ".jpg")):
        return None
    return posixpath.normpath(posixpath.join(posixpath.dirname(path), target))


def download(system, folder, name, prefer="libretro"):
    """Octets de l'image, ou None. Essaie le serveur libretro puis GitHub (ou l'inverse)."""
    order = [prefer] + [s for s in ("libretro", "github") if s != prefer]
    for source in order:
        path = f"{folder}/{name}"
        for _hop in range(4):                                    # liens symboliques suivis
            try:
                data = _get(_url(source, system, path))
            except (OSError, ValueError) as exc:
                log.debug("jaquettes : %s indisponible chez %s (%s)", path, source, exc)
                break
            if _valid_image(data):
                return data
            path = _link_target(data, path)
            if not path or path.startswith(".."):
                break
    return None


def _read(path):
    if not path:
        return None
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


# --------------------------------------------------------------- bibliothèque
def games(system):
    """Jeux d'un système (comme ES-DE : dossier du système et un niveau de sous-dossiers)."""
    root = os.path.join(ROMS_DIR, system)
    exts = set(SYSTEM_INDEX[system][4].split())
    out = []
    try:
        entries = sorted(os.scandir(root), key=lambda e: e.name)
    except OSError:
        return out
    for e in entries:
        if e.name.startswith((".", "_")):
            continue
        if e.is_file() and os.path.splitext(e.name)[1].lower() in exts:
            out.append(e.path)
        elif e.is_dir() and dir_as_file(e.path, exts):
            out.append(e.path)                               # « Jeu.m3u/ » : un seul jeu
        elif e.is_dir():
            try:
                for f in sorted(os.listdir(e.path)):
                    sub = os.path.join(e.path, f)
                    if not f.startswith(".") and os.path.splitext(f)[1].lower() in exts and \
                            (os.path.isfile(sub) or dir_as_file(sub, exts)):
                        out.append(sub)
            except OSError:
                pass
    return out


def media_path(system, rom, kind, ext=".png"):
    rel = os.path.relpath(rom, os.path.join(ROMS_DIR, system))
    if not os.path.isdir(rom):                               # dossier vu comme un fichier : nom gardé entier
        rel = os.path.splitext(rel)[0]
    return os.path.join(MEDIA_DIR, system, kind, rel + ext)


def has_media(system, rom, kind):
    return any(os.path.exists(media_path(system, rom, kind, ext)) for ext in IMAGE_EXTS)


def pending(systems=None):
    """[(système, jeu, [types d'image manquants])] pour les jeux sans jaquette ou sans image du jeu."""
    out = []
    for system in systems or SYSTEM_NAMES:
        for rom in games(system):
            if re.search(r"\(track \d+\)", os.path.basename(rom), re.I):
                continue                                         # piste audio d'un .cue
            kinds = [k for k, _ in KINDS if not has_media(system, rom, k)]
            if kinds:
                out.append((system, rom, kinds))
    return out


def run(should_wait=lambda: False, should_stop=lambda: False, limit=400):
    """Cherche et télécharge les images manquantes. Renvoie {"added", "missing", "failed", "games"}."""
    stats = {"added": 0, "missing": 0, "failed": 0, "games": 0, "offline": False}
    misses = read_json(MISSES_PATH, {}) or {}
    todo = pending()
    stats["games"] = len({rom for _, rom, _ in todo})
    downloads = 0
    by_system = {}
    for system, rom, kinds in todo:
        by_system.setdefault(system, []).append((rom, kinds))
    for system, items in by_system.items():
        for kind, folder in KINDS:
            wanted = [rom for rom, kinds in items if kind in kinds]
            if not wanted:
                continue
            lst = listing(system, folder)
            if lst is None:
                stats["offline"] = True
                stats["failed"] += len(wanted)
                continue
            index, fetched = Index(lst["names"]), {}           # nom libretro → image déjà écrite
            for rom in wanted:
                miss_key = f"{kind}:{rom}"
                if misses.get(miss_key, 0) >= lst["ts"]:
                    stats["missing"] += kind == "covers"
                    continue
                rel_dir = os.path.dirname(os.path.relpath(rom, os.path.join(ROMS_DIR, system)))
                name = index.match_path(rom, os.path.basename(rel_dir) if rel_dir else None)
                if name is None:
                    misses[miss_key] = lst["ts"]
                    stats["missing"] += kind == "covers"
                    continue
                if downloads >= limit:
                    break
                while should_wait():
                    if should_stop():
                        write_json(MISSES_PATH, misses)
                        return stats
                    time.sleep(15)
                if should_stop():
                    write_json(MISSES_PATH, misses)
                    return stats
                data = _read(fetched.get(name))                  # même image pour .cue et .bin, disques…
                if data is None:
                    data = download(system, folder, name, prefer=lst.get("source", "libretro"))
                    downloads += 1
                if data is None:
                    stats["failed"] += 1
                    continue
                ext = ".jpg" if data.startswith(b"\xff\xd8") else ".png"
                dest = media_path(system, rom, kind, ext)
                atomic_write(dest, data)
                fetched[name] = dest
                misses.pop(miss_key, None)
                stats["added"] += kind == "covers"
                log.info("jaquettes : %s → %s/%s", os.path.basename(rom), folder, name)
                time.sleep(0.15)                                 # sans brusquer le serveur
    write_json(MISSES_PATH, misses)
    return stats
