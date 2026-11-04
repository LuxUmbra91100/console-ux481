"""Petits utilitaires partagés (journal, fichiers, sous-processus, boucle GLib)."""
import json
import logging
import os
import subprocess
import tempfile
import threading

log = logging.getLogger("console")


def setup_logging():
    level = logging.DEBUG if os.environ.get("CONSOLE_DEBUG") else logging.INFO
    logging.basicConfig(level=level, format="%(levelname).1s %(name)s: %(message)s")


def on_main(fn, *args, **kwargs):
    """Exécute fn dans la boucle GLib principale (depuis n'importe quel thread)."""
    from gi.repository import GLib

    def _call():
        try:
            fn(*args, **kwargs)
        except Exception:  # noqa: BLE001 - on ne veut jamais tuer la boucle
            log.exception("erreur dans %s", getattr(fn, "__name__", fn))
        return False

    GLib.idle_add(_call)


def later(ms, fn, *args):
    """Appelle fn(*args) une fois après ms millisecondes (boucle principale)."""
    from gi.repository import GLib

    def _call():
        try:
            fn(*args)
        except Exception:  # noqa: BLE001
            log.exception("erreur différée dans %s", getattr(fn, "__name__", fn))
        return False

    return GLib.timeout_add(ms, _call)


def every(ms, fn):
    """Appelle fn() toutes les ms millisecondes tant qu'elle ne renvoie pas False."""
    from gi.repository import GLib

    def _call():
        try:
            return fn() is not False
        except Exception:  # noqa: BLE001
            log.exception("erreur périodique dans %s", getattr(fn, "__name__", fn))
            return True

    return GLib.timeout_add(ms, _call)


def thread(fn, *args, name=None):
    t = threading.Thread(target=fn, args=args, name=name or getattr(fn, "__name__", "worker"), daemon=True)
    t.start()
    return t


def run(cmd, timeout=15, input_text=None, env=None):
    """Lance une commande et renvoie (code, stdout, stderr) sans jamais lever d'exception."""
    try:
        p = subprocess.run(cmd, input=input_text, capture_output=True, text=True,
                           timeout=timeout, env=env)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"{cmd[0]}: introuvable"
    except subprocess.TimeoutExpired:
        return 124, "", "délai dépassé"
    except Exception as exc:  # noqa: BLE001
        return 1, "", str(exc)


def run_async(cmd, callback=None, timeout=30, env=None):
    """Lance une commande dans un thread ; callback(code, out, err) dans la boucle principale."""
    def worker():
        res = run(cmd, timeout=timeout, env=env)
        if callback:
            on_main(callback, *res)
    return thread(worker, name=f"run:{cmd[0]}")


def atomic_write(path, data, mode=0o644):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data.encode("utf-8") if isinstance(data, str) else data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, obj):
    atomic_write(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def parent_pid(pid):
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as f:
            data = f.read()
        # le nom du processus peut contenir des espaces/parenthèses : on coupe après le dernier ')'
        return int(data[data.rindex(")") + 2:].split()[1])
    except (OSError, ValueError, IndexError):
        return 0


def is_descendant(pid, ancestor, max_depth=40):
    for _ in range(max_depth):
        if not pid or pid <= 1:
            return False
        if pid == ancestor:
            return True
        pid = parent_pid(pid)
    return False


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v
