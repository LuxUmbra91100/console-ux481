"""Tuiles de l'écran d'accueil : ordre, sites épinglés (titre, icône, couleur)."""
import html.parser
import json
import os
import re
import urllib.parse
import urllib.request
import uuid

from .config import ICON_DIR, LAYOUT_PATH
from .util import log, on_main, read_json, thread, write_json

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/140.0.0.0 Safari/537.36")
CORE_TILES = ("moonlight", "games", "brave")
DEFAULT_LAYOUT = {
    "version": 1,
    "tiles": [
        {"id": "moonlight", "type": "moonlight"},
        {"id": "games", "type": "games"},
        {"id": "brave", "type": "brave"},
        {"id": "site-youtube", "type": "site", "title": "YouTube", "url": "https://www.youtube.com/",
         "color": "#ff0033", "control": "pointer", "tv": False, "icon": None},
    ],
}
PRESETS = [
    {"title": "YouTube", "url": "https://www.youtube.com/", "color": "#ff0033"},
    {"title": "YouTube TV", "url": "https://www.youtube.com/tv", "color": "#ff0033", "control": "tv", "tv": True,
     "note": "Interface télé, à la croix (expérimental)"},
    {"title": "Netflix", "url": "https://www.netflix.com/", "color": "#e50914"},
    {"title": "Twitch", "url": "https://www.twitch.tv/", "color": "#9146ff"},
    {"title": "Prime Video", "url": "https://www.primevideo.com/", "color": "#1a98ff"},
    {"title": "Disney+", "url": "https://www.disneyplus.com/", "color": "#113ccf"},
    {"title": "Spotify", "url": "https://open.spotify.com/", "color": "#1db954"},
    {"title": "france.tv", "url": "https://www.france.tv/", "color": "#2f3cdd"},
    {"title": "Arte", "url": "https://www.arte.tv/fr/", "color": "#fa481c"},
]
_OPENER = urllib.request.build_opener()
_OPENER.addheaders = [("User-Agent", UA), ("Accept-Language", "fr-FR,fr;q=0.9,en;q=0.6")]


def normalize_url(text):
    text = (text or "").strip()
    if not text:
        return None
    if not re.match(r"^[a-z][a-z0-9+.-]*://", text, re.I):
        if " " in text or "." not in text:
            return None
        text = "https://" + text
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return parsed.geturl()


def nice_title(url):
    host = urllib.parse.urlparse(url).netloc.removeprefix("www.")
    name = host.split(".")[0] if host else url
    return name[:1].upper() + name[1:]


class _HeadParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.title, self.in_title = "", False
        self.icons, self.meta, self.manifest = [], {}, None

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "title":
            self.in_title = True
        elif tag == "link":
            rel = a.get("rel", "").lower()
            if "icon" in rel:
                self.icons.append({"href": a.get("href", ""), "rel": rel, "sizes": a.get("sizes", ""),
                                   "type": a.get("type", "")})
            elif rel == "manifest":
                self.manifest = a.get("href")
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or "").lower()
            if key:
                self.meta[key] = a.get("content", "")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title and len(self.title) < 200:
            self.title += data


def _icon_score(icon):
    href = icon.get("href", "")
    if href.lower().split("?")[0].endswith(".svg") or "svg" in icon.get("type", ""):
        return 600
    best = 0
    for size in re.findall(r"(\d+)x(\d+)", icon.get("sizes", "")):
        best = max(best, int(size[0]))
    if not best:
        best = 180 if "apple-touch" in icon.get("rel", "") else 32
    return best if best <= 1024 else 300


def best_icon(icons, base):
    candidates = []
    for icon in icons or []:
        href = icon.get("href") or icon.get("src")
        if not href or href.startswith("data:"):
            continue
        url = urllib.parse.urljoin(base, href)
        candidates.append((_icon_score({**icon, "href": url}), url))
    candidates.sort(reverse=True)
    return [u for _, u in candidates]


def _get(url, limit=1_500_000, timeout=6):
    with _OPENER.open(url, timeout=timeout) as r:
        return r.read(limit), r.headers.get_content_type(), r.geturl()


def fetch_metadata(url):
    """Titre, couleur et liste d'icônes candidates d'une page (sans navigateur)."""
    info = {"title": None, "color": None, "icons": [], "url": url}
    try:
        body, ctype, final = _get(url)
    except Exception as exc:  # noqa: BLE001
        log.info("métadonnées de %s indisponibles : %s", url, exc)
        return info
    p = _HeadParser()
    try:
        p.feed(body.decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        pass
    info["title"] = (p.meta.get("og:site_name") or p.meta.get("application-name") or p.title or "").strip()[:60] or None
    info["color"] = p.meta.get("theme-color") or None
    icons = list(p.icons)
    if p.manifest:
        try:
            mbody, _, mfinal = _get(urllib.parse.urljoin(final, p.manifest), limit=300_000)
            manifest = json.loads(mbody.decode("utf-8", errors="replace"))
            info["title"] = info["title"] or manifest.get("short_name") or manifest.get("name")
            info["color"] = info["color"] or manifest.get("theme_color")
            for ic in manifest.get("icons", []):
                icons.append({"href": urllib.parse.urljoin(mfinal, ic.get("src", "")), "sizes": ic.get("sizes", ""),
                              "type": ic.get("type", ""), "rel": "manifest"})
        except Exception:  # noqa: BLE001
            pass
    info["icons"] = best_icon(icons, final) + [urllib.parse.urljoin(final, "/favicon.ico")]
    return info


def download_icon(candidates, tile_id):
    os.makedirs(ICON_DIR, exist_ok=True)
    for url in candidates[:6]:
        try:
            body, ctype, _ = _get(url, limit=2_000_000)
        except Exception:  # noqa: BLE001
            continue
        if not body or not (ctype.startswith("image/") or url.lower().endswith((".ico", ".png", ".svg"))):
            continue
        ext = {"image/svg+xml": ".svg", "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
               "image/x-icon": ".ico", "image/vnd.microsoft.icon": ".ico"}.get(ctype, ".png")
        path = os.path.join(ICON_DIR, f"{tile_id}{ext}")
        for old in os.listdir(ICON_DIR):
            if old.startswith(tile_id + "."):
                os.unlink(os.path.join(ICON_DIR, old))
        with open(path, "wb") as f:
            f.write(body)
        return path
    return None


class Sites:
    def __init__(self, on_change):
        self.on_change = on_change
        data = read_json(LAYOUT_PATH, None)
        if not data or not isinstance(data.get("tiles"), list):
            data = json.loads(json.dumps(DEFAULT_LAYOUT))
        ids = [t.get("id") for t in data["tiles"]]
        for core in CORE_TILES:          # les tuiles principales ne disparaissent jamais
            if core not in ids:
                data["tiles"].insert(CORE_TILES.index(core), {"id": core, "type": core})
        self.data = data
        self.save()
        for tile in self.sites():
            if not tile.get("icon") or not os.path.exists(tile["icon"]):
                self._refresh_meta(tile["id"], keep_title=True)

    def save(self):
        write_json(LAYOUT_PATH, self.data)

    def tiles(self):
        return self.data["tiles"]

    def sites(self):
        return [t for t in self.data["tiles"] if t.get("type") == "site"]

    def get(self, tile_id):
        return next((t for t in self.data["tiles"] if t.get("id") == tile_id), None)

    def add(self, url, title=None, color=None, control="pointer", tv=False, icons=None):
        url = normalize_url(url)
        if not url:
            raise ValueError("Adresse invalide")
        tile = {"id": "site-" + uuid.uuid4().hex[:8], "type": "site", "title": title or nice_title(url),
                "url": url, "color": color, "control": control, "tv": bool(tv), "icon": None}
        self.data["tiles"].append(tile)
        self.save()
        self.on_change()
        self._refresh_meta(tile["id"], keep_title=bool(title), icons=icons)
        return tile

    def _refresh_meta(self, tile_id, keep_title=False, icons=None):
        tile = self.get(tile_id)
        if not tile:
            return
        url = tile["url"]

        def work():
            meta = fetch_metadata(url) if not icons else {"title": None, "color": None, "icons": icons}
            if icons:
                meta["icons"] = list(icons) + fetch_metadata(url)["icons"]
            path = download_icon(meta["icons"], tile_id)
            on_main(apply, meta, path)

        def apply(meta, path):
            t = self.get(tile_id)
            if not t:
                return
            if path:
                t["icon"] = path
            if meta.get("title") and not keep_title:
                t["title"] = meta["title"]
            if meta.get("color") and not t.get("color"):
                t["color"] = meta["color"]
            self.save()
            self.on_change()
        thread(work, name="site-meta")

    def remove(self, tile_id):
        tile = self.get(tile_id)
        if not tile or tile.get("type") != "site":
            return False
        self.data["tiles"].remove(tile)
        if tile.get("icon") and os.path.exists(tile["icon"]):
            try:
                os.unlink(tile["icon"])
            except OSError:
                pass
        self.save()
        self.on_change()
        return True

    def move(self, tile_id, delta):
        tiles = self.data["tiles"]
        tile = self.get(tile_id)
        if not tile:
            return
        i = tiles.index(tile)
        j = max(0, min(len(tiles) - 1, i + delta))
        tiles.insert(j, tiles.pop(i))
        self.save()
        self.on_change()

    def update(self, tile_id, **fields):
        tile = self.get(tile_id)
        if not tile:
            return None
        for k in ("title", "control", "tv", "color"):
            if k in fields and fields[k] is not None:
                tile[k] = fields[k]
        self.save()
        self.on_change()
        return tile
