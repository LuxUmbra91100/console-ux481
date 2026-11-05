"""Envoi de jeux et de BIOS depuis un téléphone ou un PC : petit serveur web de la console.

Il ne tourne que pendant que l'écran « Ajouter des jeux » est ouvert sur la TV (un envoi commencé
va quand même jusqu'au bout). L'adresse du QR code contient un jeton secret ; tapée à la main, la
page demande le code à 6 chiffres affiché sur la TV. Les fichiers arrivent dans
~/.cache/console/import/envoi-<n°>/, puis importer.py les range (simple déplacement, même disque).
"""
import json
import os
import re
import secrets
import shutil
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import importer
from .config import UI_DIR
from .util import log, run

PORT = 8765
PAGE = os.path.join(UI_DIR, "upload.html")
BATCH = re.compile(r"^[A-Za-z0-9_-]{6,40}$")
MARGIN = 1 << 30                                   # garder 1 Go libre sur la console


def safe_rel(path):
    """Chemin relatif sûr (pas de « .. », pas de chemin absolu, 8 niveaux au plus), ou None."""
    parts = [re.sub(r"[\x00-\x1f]", "", p)[:200] for p in re.split(r"[\\/]+", path or "")]
    parts = [p for p in parts if p not in ("", ".", "..")]
    if not parts or len(parts) > 8 or any(p.startswith(".") for p in parts):
        return None
    return os.path.join(*parts)


def qr_svg(text):
    """QR code en SVG (qrencode), ou None s'il n'est pas installé."""
    code, out, _ = run(["qrencode", "-t", "SVG", "-m", "1", "-l", "M", "-o", "-", text], timeout=5)
    if code != 0 or "<svg" not in out:
        return None
    return out[out.index("<svg"):]


class Uploader:
    def __init__(self, on_event, name=lambda: "Console"):
        self.on_event = on_event                   # appelé depuis les fils du serveur
        self.name = name
        self.httpd = None
        self.port = None
        self.token = self.code = None
        self.failures = 0
        self.active = 0
        self.closing = False
        self.lock = threading.Lock()

    @property
    def running(self):
        return self.httpd is not None

    def start(self, port=PORT):
        if self.httpd:
            self.closing = False                   # écran rouvert : même adresse, même code
            return self.port
        self.token = secrets.token_urlsafe(18)
        self.code = f"{secrets.randbelow(10 ** 6):06d}"
        self.failures, self.closing = 0, False
        handler = type("UploadHandler", (Handler,), {"up": self})
        for p in (port, 0):
            try:
                self.httpd = ThreadingHTTPServer(("", p), handler)
                break
            except OSError:
                continue
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, name="upload-http", daemon=True).start()
        log.info("envoi de jeux : serveur ouvert sur le port %s", self.port)
        return self.port

    def stop(self):
        """Ferme dès qu'aucun envoi n'est en cours."""
        if not self.httpd:
            return
        self.closing = True

        def wait():
            while True:
                with self.lock:
                    if not self.closing:           # rouvert entre-temps
                        return
                    if self.active == 0:
                        httpd, self.httpd = self.httpd, None
                        break
                time.sleep(0.5)
            if httpd:
                httpd.shutdown()
                httpd.server_close()
                log.info("envoi de jeux : serveur fermé")
        threading.Thread(target=wait, name="upload-stop", daemon=True).start()

    def staging(self, batch):
        return os.path.join(importer.WORK_DIR, "envoi-" + batch)


class Handler(BaseHTTPRequestHandler):
    up = None
    server_version = "Console"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        log.debug("envoi : " + fmt, *args)

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if code >= 400 and self.command == "PUT":
            self.close_connection = True               # corps de la requête non lu : on ne réutilise pas
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def _query(self):
        url = urllib.parse.urlsplit(self.path)
        return url.path, {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}

    def _authorized(self, q):
        tok = self.headers.get("X-Token") or q.get("k") or ""
        return bool(tok) and secrets.compare_digest(tok.encode(), (self.up.token or "").encode())

    def _batch(self, q):
        b = q.get("batch") or ""
        return b if BATCH.match(b) else None

    # ---------------------------------------------------------------- GET
    def do_GET(self):
        path, q = self._query()
        if path in ("/", "/index.html"):
            try:
                with open(PAGE, encoding="utf-8") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            except OSError:
                return self._send(500, "Page introuvable", "text/plain; charset=utf-8")
        if path == "/api/auth":
            if self.up.failures >= 10:
                return self._send(429, {"error": "Trop d'essais : ferme et rouvre « Ajouter des jeux » sur la TV."})
            if secrets.compare_digest((q.get("code") or "").strip().encode(), (self.up.code or "").encode()):
                return self._send(200, {"token": self.up.token})
            self.up.failures += 1
            time.sleep(1)
            return self._send(403, {"error": "Code incorrect"})
        if path == "/api/info":
            if not self._authorized(q):
                return self._send(403, {"error": "Lien expiré : scanne de nouveau le QR code de la TV."})
            return self._send(200, {"name": self.up.name(), "free": shutil.disk_usage(os.path.expanduser("~")).free})
        if path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")
        return self._send(404, {"error": "introuvable"})

    # ---------------------------------------------------------------- PUT /api/upload
    def do_PUT(self):
        path, q = self._query()
        if path != "/api/upload":
            return self._send(404, {"error": "introuvable"})
        if not self._authorized(q):
            return self._send(403, {"error": "Lien expiré : scanne de nouveau le QR code de la TV."})
        if self.up.closing:
            return self._send(503, {"error": "L'écran « Ajouter des jeux » a été fermé sur la TV."})
        batch, rel = self._batch(q), safe_rel(q.get("path"))
        length = int(self.headers.get("Content-Length") or -1)
        if not batch or not rel or length < 0:
            return self._send(400, {"error": "requête invalide"})
        os.makedirs(importer.WORK_DIR, exist_ok=True)
        if shutil.disk_usage(importer.WORK_DIR).free < length + MARGIN:
            return self._send(507, {"error": "Plus assez de place sur la console pour ce fichier."})
        dest = os.path.join(self.up.staging(batch), rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with self.up.lock:
            self.up.active += 1
        done, last = 0, 0.0
        try:
            with open(dest, "wb") as f:
                while done < length:
                    chunk = self.rfile.read(min(1 << 20, length - done))
                    if not chunk:
                        raise ConnectionError("envoi interrompu")
                    f.write(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if now - last > 0.3:
                        last = now
                        self.up.on_event({"type": "progress", "batch": batch, "name": rel, "done": done,
                                          "total": length})
        except (OSError, ConnectionError) as exc:
            log.info("envoi de %s interrompu : %s", rel, exc)
            try:
                os.unlink(dest)
            except OSError:
                pass
            self.close_connection = True
            return None
        finally:
            with self.up.lock:
                self.up.active -= 1
        self.up.on_event({"type": "progress", "batch": batch, "name": rel, "done": length, "total": length})
        return self._send(200, {"ok": True})

    # ---------------------------------------------------------------- POST /api/done
    def do_POST(self):
        path, q = self._query()
        if path != "/api/done":
            return self._send(404, {"error": "introuvable"})
        if not self._authorized(q):
            return self._send(403, {"error": "Lien expiré : scanne de nouveau le QR code de la TV."})
        batch = self._batch(q)
        folder = self.up.staging(batch) if batch else None
        if not folder or not os.path.isdir(folder):
            return self._send(404, {"error": "rien à ranger"})
        with self.up.lock:
            self.up.active += 1
        try:
            self.up.on_event({"type": "sorting", "batch": batch})
            results = importer.import_tree(folder, move=True)
        except Exception as exc:  # noqa: BLE001 — la page doit toujours avoir une réponse
            log.exception("rangement de l'envoi %s", batch)
            results = [{"kind": "error", "label": "Rangement", "status": "error", "note": str(exc), "system": None,
                        "size": 0}]
        finally:
            shutil.rmtree(folder, ignore_errors=True)
            with self.up.lock:
                self.up.active -= 1
        self.up.on_event({"type": "done", "batch": batch, "results": results})
        return self._send(200, {"results": results})
