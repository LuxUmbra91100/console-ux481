"""Clé USB ou disque branché : les jeux et BIOS qu'il contient sont proposés à l'import.

Détection : la console surveille /dev/disk/by-id (udev y crée un lien par disque branché), puis
lsblk liste les partitions des disques USB. Le montage se fait en lecture seule par console-root
(jamais d'écriture sur la clé) ; l'analyse et la copie tournent dans des fils à part.
"""
import json
import os

from .config import PREFIX
from .util import log, on_main, run, thread

ROOT_HELPER = ["sudo", "-n", os.path.join(PREFIX, "bin", "console-root")]
FS_OK = {"vfat", "exfat", "ntfs", "ext4", "ext3", "ext2", "btrfs", "iso9660", "udf", "hfsplus"}


def _bool(v):
    return v is True or str(v).strip().lower() in ("1", "true")


def usb_partitions(lsblk_json=None):
    """{partition: {disk, label, size, fstype}} pour les disques USB (clés, disques, lecteurs de cartes)."""
    if lsblk_json is None:
        code, lsblk_json, _ = run(["lsblk", "-J", "-b", "-o",
                                   "NAME,FSTYPE,LABEL,SIZE,TRAN,HOTPLUG,TYPE,VENDOR,MODEL"], timeout=10)
        if code != 0:
            return {}
    try:
        devices = json.loads(lsblk_json).get("blockdevices", [])
    except ValueError:
        return {}
    out = {}
    for disk in devices:
        name = disk.get("name") or ""
        if disk.get("type") != "disk" or not name.startswith("sd"):
            continue
        if disk.get("tran") != "usb" and not _bool(disk.get("hotplug")):
            continue
        model = " ".join(x.strip() for x in (disk.get("vendor") or "", disk.get("model") or "") if x and x.strip())
        for part in disk.get("children") or [disk]:
            if (part.get("fstype") or "") in FS_OK:
                out[part["name"]] = {"disk": name, "label": (part.get("label") or model or "Clé USB").strip(),
                                     "size": int(part.get("size") or 0), "fstype": part["fstype"]}
    return out


def mount(part):
    """Monte la partition en lecture seule ; renvoie le dossier, ou None."""
    code, out, err = run(ROOT_HELPER + ["usb-mount", part], timeout=40)
    path = out.strip().splitlines()[-1] if out.strip() else ""
    if code != 0 or not path.startswith("/media/"):
        log.warning("clé USB %s : montage impossible (%s)", part, err.strip() or code)
        return None
    return path


def unmount(part):
    run(ROOT_HELPER + ["usb-unmount", part], timeout=40)


class UsbWatcher:
    """Appelle on_new(disque, {partition: infos}) quand une clé apparaît, on_gone(partition) quand elle part.
    Les clés déjà là au démarrage de la console ne sont pas proposées."""

    def __init__(self, on_new, on_gone):
        from gi.repository import Gio, GLib
        self.GLib = GLib
        self.on_new, self.on_gone = on_new, on_gone
        self.known = set(usb_partitions())
        self._timer = None
        self.monitor = None
        try:
            self.monitor = Gio.File.new_for_path("/dev/disk/by-id").monitor_directory(Gio.FileMonitorFlags.NONE, None)
            self.monitor.connect("changed", lambda *_: self._soon())
        except GLib.Error as exc:
            log.warning("surveillance des clés USB impossible (%s) : vérification toutes les 5 s", exc)
            GLib.timeout_add_seconds(5, lambda: (self._scan(), True)[1])

    def _soon(self):
        if self._timer:
            self.GLib.source_remove(self._timer)
        self._timer = self.GLib.timeout_add(1500, self._scan)       # udev crée plusieurs liens d'affilée

    def _scan(self):
        self._timer = None
        thread(lambda: on_main(self._diff, usb_partitions()), name="usb-scan")
        return False

    def _diff(self, parts):
        new = {k: v for k, v in parts.items() if k not in self.known}
        gone = [k for k in self.known if k not in parts]
        self.known = set(parts)
        for k in gone:
            self.on_gone(k)
        disks = {}
        for k, v in new.items():
            disks.setdefault(v["disk"], {})[k] = v
        for disk, ps in disks.items():
            self.on_new(disk, ps)
