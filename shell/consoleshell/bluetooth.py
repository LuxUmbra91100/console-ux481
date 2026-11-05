"""Manettes Bluetooth via BlueZ (D-Bus) : appairage automatique, batterie, déconnexion."""
import time

from gi.repository import Gio, GLib

from .util import later, log

BLUEZ = "org.bluez"
AGENT_PATH = "/org/console/btagent"
AGENT_XML = """<node><interface name="org.bluez.Agent1">
  <method name="Release"/>
  <method name="RequestPinCode"><arg type="o" direction="in"/><arg type="s" direction="out"/></method>
  <method name="DisplayPinCode"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
  <method name="RequestPasskey"><arg type="o" direction="in"/><arg type="u" direction="out"/></method>
  <method name="DisplayPasskey"><arg type="o" direction="in"/><arg type="u" direction="in"/><arg type="q" direction="in"/></method>
  <method name="RequestConfirmation"><arg type="o" direction="in"/><arg type="u" direction="in"/></method>
  <method name="RequestAuthorization"><arg type="o" direction="in"/></method>
  <method name="AuthorizeService"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
  <method name="Cancel"/>
</interface></node>"""
GAMEPAD_WORDS = ("controller", "gamepad", "xbox", "dualsense", "dualshock", "8bitdo", "pro controller", "joy-con")


def is_gamepad(dev):
    if dev.get("Icon") == "input-gaming":
        return True
    if dev.get("Appearance") in (0x03C3, 0x03C4):
        return True
    cls = dev.get("Class") or 0
    if ((cls >> 8) & 0x1F) == 0x05 and ((cls >> 2) & 0x0F) in (0x01, 0x02):
        return True
    name = (dev.get("Name") or dev.get("Alias") or "").lower()
    return any(w in name for w in GAMEPAD_WORDS)



class Bluetooth:
    def __init__(self, on_event):
        self.on_event = on_event          # on_event(kind, data)
        self.objects = {}
        self.pairing_until = 0.0
        self.busy_paths = set()
        self.agent_id = None
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
        except GLib.Error as exc:
            log.error("D-Bus système indisponible : %s", exc.message)
            self.bus = None
            return
        for member in ("InterfacesAdded", "InterfacesRemoved"):
            self.bus.signal_subscribe(BLUEZ, "org.freedesktop.DBus.ObjectManager", member, None, None,
                                      Gio.DBusSignalFlags.NONE, self._on_objects)
        self.bus.signal_subscribe(BLUEZ, "org.freedesktop.DBus.Properties", "PropertiesChanged", None,
                                  None, Gio.DBusSignalFlags.NONE, self._on_props)
        Gio.bus_watch_name_on_connection(self.bus, BLUEZ, Gio.BusNameWatcherFlags.NONE,
                                         self._on_bluez_up, self._on_bluez_down)

    # ------------------------------------------------------------- D-Bus ---
    def _call(self, path, iface, method, params=None, reply=None, timeout=10000, callback=None):
        if self.bus is None:
            return None
        if callback is None:
            try:
                res = self.bus.call_sync(BLUEZ, path, iface, method, params,
                                         GLib.VariantType(reply) if reply else None,
                                         Gio.DBusCallFlags.NONE, timeout, None)
                return res.unpack() if res is not None else None
            except GLib.Error as exc:
                log.debug("BlueZ %s.%s : %s", iface, method, exc.message)
                return None

        def done(bus, result):
            try:
                bus.call_finish(result)
                callback(True, None)
            except GLib.Error as exc:
                callback(False, exc.message)
        self.bus.call(BLUEZ, path, iface, method, params, None, Gio.DBusCallFlags.NONE, timeout, None, done)
        return None

    def _set(self, path, iface, prop, value):
        return self._call(path, "org.freedesktop.DBus.Properties", "Set",
                          GLib.Variant("(ssv)", (iface, prop, value)))

    def _on_bluez_up(self, *_):
        log.info("BlueZ disponible")
        self._register_agent()
        self.refresh()
        adapter = self.adapter()
        if adapter:
            self._set(adapter, "org.bluez.Adapter1", "Powered", GLib.Variant("b", True))
        for path, dev in self.devices():
            if dev.get("Paired") and is_gamepad(dev):
                self._set(path, "org.bluez.Device1", "Trusted", GLib.Variant("b", True))
                self._set(path, "org.bluez.Device1", "WakeAllowed", GLib.Variant("b", True))

    def _on_bluez_down(self, *_):
        self.objects.clear()
        self.agent_id = None
        self.on_event("changed", None)

    def _register_agent(self):
        if self.agent_id is None:
            node = Gio.DBusNodeInfo.new_for_xml(AGENT_XML)
            try:
                self.agent_id = self.bus.register_object(AGENT_PATH, node.interfaces[0], self._agent_call, None, None)
            except GLib.Error as exc:
                log.error("agent Bluetooth : %s", exc.message)
                return
        self._call("/org/bluez", "org.bluez.AgentManager1", "RegisterAgent",
                   GLib.Variant("(os)", (AGENT_PATH, "NoInputNoOutput")))
        self._call("/org/bluez", "org.bluez.AgentManager1", "RequestDefaultAgent",
                   GLib.Variant("(o)", (AGENT_PATH,)))

    def _agent_call(self, _conn, _sender, _path, _iface, method, _params, invocation):
        # Appairage « sans code » : on accepte tout (seulement pendant le mode appairage
        # ou pour des appareils déjà connus).
        if method == "RequestPinCode":
            invocation.return_value(GLib.Variant("(s)", ("0000",)))
        elif method == "RequestPasskey":
            invocation.return_value(GLib.Variant("(u)", (0,)))
        else:
            invocation.return_value(None)

    def refresh(self):
        res = self._call("/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects",
                         reply="(a{oa{sa{sv}}})")
        self.objects = dict(res[0]) if res else {}
        self.on_event("changed", None)

    def _on_objects(self, _conn, _sender, _path, _iface, signal, params, *_):
        if signal == "InterfacesAdded":
            path, ifaces = params.unpack()
            self.objects.setdefault(path, {}).update(ifaces)
            self._consider(path)
        else:
            path, ifaces = params.unpack()
            obj = self.objects.get(path, {})
            for i in ifaces:
                obj.pop(i, None)
            if not obj:
                self.objects.pop(path, None)
        self.on_event("changed", None)

    def _on_props(self, _conn, _sender, path, _iface, _signal, params, *_):
        iface, changed, _invalid = params.unpack()
        if not iface.startswith("org.bluez."):
            return
        self.objects.setdefault(path, {}).setdefault(iface, {}).update(changed)
        if iface == "org.bluez.Device1" and ("RSSI" in changed or "Name" in changed):
            self._consider(path)
        if iface in ("org.bluez.Device1", "org.bluez.Battery1"):
            self.on_event("changed", None)

    # ------------------------------------------------------------- données --
    def adapter(self):
        for path, ifaces in self.objects.items():
            if "org.bluez.Adapter1" in ifaces:
                return path
        return None

    def devices(self):
        for path, ifaces in self.objects.items():
            dev = ifaces.get("org.bluez.Device1")
            if dev is not None:
                yield path, dev

    def gamepads(self):
        out = []
        for path, dev in self.devices():
            if not (dev.get("Paired") and is_gamepad(dev)):
                continue
            battery = (self.objects.get(path, {}).get("org.bluez.Battery1") or {}).get("Percentage")
            out.append({"path": path, "address": dev.get("Address"), "name": dev.get("Alias") or dev.get("Name") or "Manette",
                        "connected": bool(dev.get("Connected")), "battery": battery})
        return sorted(out, key=lambda d: (not d["connected"], d["name"]))

    def available(self):
        return self.adapter() is not None

    # ----------------------------------------------------------- appairage --
    @property
    def pairing(self):
        return time.monotonic() < self.pairing_until

    def start_pairing(self, seconds=120):
        adapter = self.adapter()
        if not adapter:
            return False
        self._set(adapter, "org.bluez.Adapter1", "Powered", GLib.Variant("b", True))
        self._set(adapter, "org.bluez.Adapter1", "Pairable", GLib.Variant("b", True))
        self._call(adapter, "org.bluez.Adapter1", "SetDiscoveryFilter",
                   GLib.Variant("(a{sv})", ({"Transport": GLib.Variant("s", "auto")},)))
        self._call(adapter, "org.bluez.Adapter1", "StartDiscovery")
        self.pairing_until = time.monotonic() + seconds
        later(seconds * 1000 + 200, self._pairing_timeout)
        self.on_event("pairing", {"state": "searching"})
        for path, _ in list(self.devices()):
            self._consider(path)
        return True

    def stop_pairing(self):
        self.pairing_until = 0.0
        adapter = self.adapter()
        if adapter:
            self._call(adapter, "org.bluez.Adapter1", "StopDiscovery")
        self.on_event("pairing", {"state": "stopped"})

    def _pairing_timeout(self):
        if self.pairing_until and not self.pairing:
            self.stop_pairing()

    def _consider(self, path):
        if not self.pairing or path in self.busy_paths:
            return
        dev = (self.objects.get(path) or {}).get("org.bluez.Device1") or {}
        if dev.get("Paired") or "RSSI" not in dev or not is_gamepad(dev):
            return
        name = dev.get("Alias") or dev.get("Name") or "Manette"
        log.info("appairage de %s (%s)", name, dev.get("Address"))
        self.busy_paths.add(path)
        self.on_event("pairing", {"state": "pairing", "name": name})

        def after_pair(ok, err, attempt=1):
            if not ok and attempt == 1 and "AlreadyExists" not in (err or ""):
                log.info("nouvel essai d'appairage (%s)", err)
                later(1500, lambda: self._call(path, "org.bluez.Device1", "Pair", timeout=45000,
                                               callback=lambda o, e: after_pair(o, e, 2)))
                return
            if not ok and "AlreadyExists" not in (err or ""):
                self.busy_paths.discard(path)
                self.on_event("pairing", {"state": "failed", "name": name, "error": err})
                return
            self._set(path, "org.bluez.Device1", "Trusted", GLib.Variant("b", True))
            self._set(path, "org.bluez.Device1", "WakeAllowed", GLib.Variant("b", True))

            def after_connect(ok2, err2):
                self.busy_paths.discard(path)
                if ok2:
                    self.stop_pairing()
                    self.on_event("pairing", {"state": "paired", "name": name})
                else:
                    self.on_event("pairing", {"state": "failed", "name": name, "error": err2})
            self._call(path, "org.bluez.Device1", "Connect", timeout=30000, callback=after_connect)

        self._call(path, "org.bluez.Device1", "Pair", timeout=45000, callback=after_pair)

    # ------------------------------------------------------------- actions --
    def disconnect_gamepads(self):
        """Éteint les manettes (comme une console qu'on met en veille)."""
        for pad in self.gamepads():
            if pad["connected"]:
                self._call(pad["path"], "org.bluez.Device1", "Disconnect", callback=lambda ok, err: None)

    def forget(self, path):
        adapter = self.adapter()
        if adapter:
            self._call(adapter, "org.bluez.Adapter1", "RemoveDevice", GLib.Variant("(o)", (path,)))
            self.refresh()
