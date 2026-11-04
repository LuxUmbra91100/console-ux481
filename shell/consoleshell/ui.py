"""Fenêtres GTK + WebKit : écran d'accueil, superposition (menu/clavier) et notifications.

Pont JS ↔ Python :
  JS  → Python : window.webkit.messageHandlers.shell.postMessage(JSON {id, cmd, args})
  Python → JS : Shell._receive({id, ok, result|error}) et Shell._emit(event, data)
"""
import json
import os

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gdk, GLib, Gtk, WebKit2  # noqa: E402

try:
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GtkLayerShell  # noqa: E402
except (ValueError, ImportError):
    GtkLayerShell = None

try:
    import cairo  # noqa: E402
except ImportError:
    cairo = None

from .config import UI_DIR  # noqa: E402
from .util import log  # noqa: E402


def _js_value_to_str(value):
    if hasattr(value, "get_js_value"):          # WebKit2 4.1 : JavascriptResult
        value = value.get_js_value()
    return value.to_string()


class WebSurface:
    """Une WebView reliée au shell."""

    def __init__(self, name, page, handler, transparent=False):
        self.name = name
        self.handler = handler            # handler(surface, cmd, args) -> résultat
        self.ready = False
        self._queue = []
        manager = WebKit2.UserContentManager()
        manager.register_script_message_handler("shell")
        manager.connect("script-message-received::shell", self._on_message)
        kwargs = {"user_content_manager": manager}
        try:
            kwargs["website_policies"] = WebKit2.WebsitePolicies(autoplay=WebKit2.AutoplayPolicy.ALLOW)
        except (AttributeError, TypeError):
            pass
        self.view = WebKit2.WebView(**kwargs)
        s = self.view.get_settings()
        s.set_allow_file_access_from_file_urls(True)
        s.set_allow_universal_access_from_file_urls(True)
        s.set_enable_developer_extras(bool(os.environ.get("CONSOLE_DEBUG")))
        s.set_enable_write_console_messages_to_stdout(True)
        s.set_media_playback_requires_user_gesture(False)
        s.set_enable_back_forward_navigation_gestures(False)
        s.set_enable_smooth_scrolling(True)
        s.set_javascript_can_open_windows_automatically(False)
        if transparent:
            self.view.set_background_color(Gdk.RGBA(0, 0, 0, 0))
        else:
            self.view.set_background_color(Gdk.RGBA(0.02, 0.03, 0.05, 1))
        self.view.connect("load-changed", self._on_load)
        self.view.connect("context-menu", lambda *a: True)
        self.view.connect("web-process-terminated", self._on_crash)
        self.page = page
        self.view.load_uri("file://" + os.path.join(UI_DIR, page))

    def _on_load(self, _view, event):
        if event == WebKit2.LoadEvent.FINISHED:
            self.ready = True
            for script in self._queue:
                self.run_js(script)
            self._queue.clear()

    def _on_crash(self, *_args):
        log.error("processus web de %s arrêté : rechargement", self.name)
        self.ready = False
        GLib.timeout_add(500, lambda: (self.view.load_uri("file://" + os.path.join(UI_DIR, self.page)), False)[1])

    def run_js(self, script):
        if not self.ready:
            self._queue.append(script)
            return
        try:
            self.view.evaluate_javascript(script, -1, None, None, None, None, None)
        except (AttributeError, TypeError):
            self.view.run_javascript(script, None, None, None)

    def emit(self, event, data=None):
        self.run_js(f"window.Shell && Shell._emit({json.dumps(event)}, {json.dumps(data, ensure_ascii=False)})")

    def reply(self, msg_id, ok, payload):
        body = {"id": msg_id, "ok": ok, ("result" if ok else "error"): payload}
        self.run_js(f"window.Shell && Shell._receive({json.dumps(body, ensure_ascii=False)})")

    def _on_message(self, _manager, js_result):
        try:
            msg = json.loads(_js_value_to_str(js_result))
        except (ValueError, AttributeError) as exc:
            log.warning("message UI invalide : %s", exc)
            return
        msg_id, cmd, args = msg.get("id"), msg.get("cmd"), msg.get("args") or {}
        try:
            result = self.handler(self, cmd, args)
        except Exception as exc:  # noqa: BLE001
            log.exception("commande UI %s", cmd)
            if msg_id is not None:
                self.reply(msg_id, False, str(exc))
            return
        if msg_id is None:
            return
        if callable(result):          # réponse asynchrone : result(callback)
            result(lambda value, ok=True: self.reply(msg_id, ok, value))
        else:
            self.reply(msg_id, True, result)


class HomeWindow:
    def __init__(self, handler):
        self.surface = WebSurface("home", "home.html", handler)
        self.window = Gtk.Window(title="Console")
        self.window.set_default_size(1920, 1080)
        self.window.add(self.surface.view)
        self.window.connect("delete-event", lambda *a: True)   # ne jamais fermer l'accueil
        self.window.show_all()


class LayerWindow:
    """Surface wlr-layer-shell au-dessus de tout (y compris des jeux plein écran)."""

    def __init__(self, name, page, handler, anchors=("top", "bottom", "left", "right"),
                 size=None, margins=None):
        self.name = name
        self.surface = WebSurface(name, page, handler, transparent=True)
        self.window = Gtk.Window()
        self.window.set_app_paintable(True)
        screen = self.window.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None:
            self.window.set_visual(visual)
        css = Gtk.CssProvider()
        css.load_from_data(b"window, .background { background-color: transparent; }")
        self.window.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        if size:
            self.window.set_default_size(*size)
            self.window.set_size_request(*size)
        self.window.add(self.surface.view)
        self.visible = False
        self.keyboard = False
        if GtkLayerShell is not None and GtkLayerShell.is_supported():
            GtkLayerShell.init_for_window(self.window)
            GtkLayerShell.set_namespace(self.window, f"console-{name}")
            GtkLayerShell.set_layer(self.window, GtkLayerShell.Layer.OVERLAY)
            GtkLayerShell.set_exclusive_zone(self.window, -1)
            edges = {"top": GtkLayerShell.Edge.TOP, "bottom": GtkLayerShell.Edge.BOTTOM,
                     "left": GtkLayerShell.Edge.LEFT, "right": GtkLayerShell.Edge.RIGHT}
            for edge_name, edge in edges.items():
                GtkLayerShell.set_anchor(self.window, edge, edge_name in anchors)
            for edge_name, value in (margins or {}).items():
                GtkLayerShell.set_margin(self.window, edges[edge_name], value)
            self._set_keyboard(False)
        else:
            log.error("gtk-layer-shell indisponible : la superposition « %s » sera une fenêtre normale", name)
        self.surface.view.show()
        self.window.realize()

    def _set_keyboard(self, exclusive):
        self.keyboard = exclusive
        if GtkLayerShell is None:
            return
        if hasattr(GtkLayerShell, "set_keyboard_mode"):
            mode = GtkLayerShell.KeyboardMode.EXCLUSIVE if exclusive else GtkLayerShell.KeyboardMode.NONE
            GtkLayerShell.set_keyboard_mode(self.window, mode)
        else:
            GtkLayerShell.set_keyboard_interactivity(self.window, exclusive)

    def _set_input(self, interactive):
        if cairo is None:
            return
        gdk_window = self.window.get_window()
        if interactive:
            self.window.input_shape_combine_region(None)
        else:
            self.window.input_shape_combine_region(cairo.Region())
        if gdk_window is not None:
            gdk_window.set_pass_through(not interactive)

    def show(self, interactive):
        """interactive=True : prend le clavier (le jeu dessous perd le focus et se met en pause)."""
        self._set_keyboard(interactive)
        if not self.visible:
            self.window.show_all()
            self.visible = True
        self._set_input(interactive)

    def hide(self):
        if self.visible:
            self._set_keyboard(False)
            self.window.hide()
            self.visible = False
