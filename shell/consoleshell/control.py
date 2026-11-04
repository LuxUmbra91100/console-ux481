"""Socket de contrôle local (console-ctl, sway, swayidle → shell)."""
import json
import os
import socket
import threading

from .util import log, on_main


class ControlServer(threading.Thread):
    def __init__(self, path, handler):
        super().__init__(name="control", daemon=True)
        self.path = path
        self.handler = handler

    def run(self):
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(self.path)
        os.chmod(self.path, 0o600)
        srv.listen(8)
        while True:
            try:
                conn, _ = srv.accept()
            except OSError as exc:
                log.error("socket de contrôle : %s", exc)
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        with conn:
            conn.settimeout(3)
            data = b""
            try:
                while not data.endswith(b"\n") and len(data) < 65536:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                msg = json.loads(data.decode("utf-8") or "{}")
            except (OSError, ValueError):
                return
            box, done = {}, threading.Event()

            def call():
                try:
                    box["r"] = self.handler(msg.get("cmd", ""), msg.get("args") or [])
                except Exception as exc:  # noqa: BLE001
                    log.exception("commande %s", msg.get("cmd"))
                    box["r"] = {"error": str(exc)}
                finally:
                    done.set()
            on_main(call)
            done.wait(5)
            try:
                conn.sendall((json.dumps(box.get("r"), default=str, ensure_ascii=False) + "\n").encode("utf-8"))
            except OSError:
                pass
