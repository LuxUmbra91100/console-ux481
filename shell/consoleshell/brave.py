"""Pilotage de Brave par le protocole DevTools (CDP) sur 127.0.0.1:9222.

Sert à : détecter un champ texte qui prend le focus (→ clavier virtuel),
écrire le texte saisi dans la page, connaître l'onglet actif (épingler un site,
mode « TV »), ouvrir/activer des onglets, user-agent TV pour YouTube.
"""
import itertools
import json
import threading
import time
import urllib.request

from .util import log, on_main, thread

try:
    import websocket  # python3-websocket (websocket-client)
except ImportError:  # pragma: no cover
    websocket = None

PORT = 9222
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TV_UA = ("Mozilla/5.0 (SMART-TV; LINUX; Tizen 6.0) AppleWebKit/537.36 (KHTML, like Gecko) "
         "Version/6.0 TV Safari/537.36")

INJECT = r"""(() => {
  if (window.__consoleInjected) return; window.__consoleInjected = true;
  const send = (o) => { try { window.__consoleBridge(JSON.stringify(o)); } catch (e) {} };
  const TEXT = ['text','search','email','url','tel','password','number',''];
  const deep = (el) => { while (el && el.shadowRoot && el.shadowRoot.activeElement) el = el.shadowRoot.activeElement; return el; };
  const editable = (el) => {
    if (!el || el.disabled || el.readOnly) return false;
    if (el.isContentEditable) return true;
    if (el.tagName === 'TEXTAREA') return true;
    return el.tagName === 'INPUT' && TEXT.includes((el.getAttribute('type') || '').toLowerCase());
  };
  const label = (el) => {
    let t = el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.getAttribute('title') || '';
    if (!t && el.labels && el.labels.length) t = el.labels[0].innerText || '';
    return (t || el.name || '').trim().slice(0, 80);
  };
  const describe = (el) => ({
    kind: el.isContentEditable ? 'rich' : el.tagName.toLowerCase(),
    type: (el.getAttribute('type') || 'text').toLowerCase(),
    value: (el.isContentEditable ? el.innerText : el.value || '').slice(0, 4000),
    label: label(el), inputmode: el.getAttribute('inputmode') || '',
    multiline: el.tagName === 'TEXTAREA' || el.isContentEditable,
    maxlength: el.maxLength > 0 ? el.maxLength : 0,
    host: location.host,
  });
  document.addEventListener('focusin', (e) => {
    const el = deep(e.composedPath ? e.composedPath()[0] : e.target);
    if (editable(el)) { window.__consoleField = el; send({t: 'focus', field: describe(el)}); }
  }, true);
  document.addEventListener('focusout', (e) => {
    const el = deep(e.composedPath ? e.composedPath()[0] : e.target);
    if (editable(el)) send({t: 'blur'});
  }, true);
  const vis = () => send({t: 'visible', v: document.visibilityState === 'visible', url: location.href});
  if (window === window.top) { document.addEventListener('visibilitychange', vis); vis(); }
  window.__consoleFocused = () => {
    const el = deep(document.activeElement);
    return editable(el) ? (window.__consoleField = el, JSON.stringify(describe(el))) : '';
  };
  window.__consoleCommit = (text) => {
    const el = window.__consoleField;
    if (!el || !el.isConnected) return false;
    el.focus();
    if (el.isContentEditable) {
      const r = document.createRange(); r.selectNodeContents(el);
      const s = getSelection(); s.removeAllRanges(); s.addRange(r);
      document.execCommand('insertText', false, text);
    } else {
      const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, text);
      el.dispatchEvent(new Event('input', {bubbles: true}));
      el.dispatchEvent(new Event('change', {bubbles: true}));
      try { el.setSelectionRange(text.length, text.length); } catch (e) {}
    }
    return true;
  };
  window.__consoleSiteInfo = () => {
    const abs = (h) => { try { return new URL(h, location.href).href; } catch (e) { return ''; } };
    const icons = [...document.querySelectorAll('link[rel]')].filter(l => /icon/i.test(l.rel))
      .map(l => ({href: abs(l.getAttribute('href')), rel: l.rel.toLowerCase(), sizes: l.getAttribute('sizes') || ''}));
    const meta = (n) => (document.querySelector(`meta[name="${n}"],meta[property="${n}"]`) || {}).content || '';
    const man = document.querySelector('link[rel="manifest"]');
    return JSON.stringify({url: location.href, title: document.title, icons, theme: meta('theme-color'),
      siteName: meta('og:site_name') || meta('application-name'), manifest: man ? abs(man.getAttribute('href')) : ''});
  };
})();"""


def http_json(path, timeout=1.5):
    with _OPENER.open(f"http://127.0.0.1:{PORT}{path}", timeout=timeout) as r:
        return json.load(r)


class BraveCDP:
    def __init__(self, shell):
        self.shell = shell
        self.ws = None
        self.ids = itertools.count(1)
        self.pending = {}
        self.lock = threading.Lock()
        self.sessions = {}      # sessionId -> {"target": id, "type": page|iframe}
        self.targets = {}       # targetId -> {"url", "title", "session"}
        self.active = None      # targetId de l'onglet visible
        self.field = None       # {"session", "field", "at"}
        self.tv_targets = set()
        self.generation = 0

    # ---------------------------------------------------------- connexion --
    @property
    def connected(self):
        return self.ws is not None

    def start(self):
        if websocket is None:
            log.error("python3-websocket absent : clavier virtuel du navigateur limité")
            return
        self.generation += 1
        thread(self._run, self.generation, name="brave-cdp")

    def stop(self):
        self.generation += 1
        ws, self.ws = self.ws, None
        if ws:
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass
        self.sessions.clear()
        self.targets.clear()
        self.active = None
        self.field = None

    def _run(self, gen):
        deadline = time.time() + 45
        while gen == self.generation and time.time() < deadline:
            try:
                info = http_json("/json/version")
                url = info["webSocketDebuggerUrl"].replace("localhost", "127.0.0.1")
                ws = websocket.create_connection(url, timeout=10, suppress_origin=True,
                                                 enable_multithread=True)
                ws.settimeout(None)
            except Exception:  # noqa: BLE001
                time.sleep(0.5)
                continue
            self.ws = ws
            log.info("Brave : connexion DevTools établie")
            self.send("Target.setDiscoverTargets", {"discover": True})
            self.send("Target.getTargets", {}, cb=self._on_targets)
            try:
                while gen == self.generation:
                    raw = ws.recv()
                    if not raw:
                        break
                    self._dispatch(json.loads(raw))
            except Exception as exc:  # noqa: BLE001
                log.info("Brave : connexion DevTools fermée (%s)", exc)
            if gen == self.generation:
                self.ws = None
            return

    def send(self, method, params=None, session=None, cb=None):
        ws = self.ws
        if ws is None:
            if cb:
                on_main(cb, None, {"message": "non connecté"})
            return
        with self.lock:
            msg_id = next(self.ids)
            if cb:
                self.pending[msg_id] = cb
        msg = {"id": msg_id, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        try:
            ws.send(json.dumps(msg))
        except Exception as exc:  # noqa: BLE001
            log.debug("CDP %s : %s", method, exc)
            with self.lock:
                cb = self.pending.pop(msg_id, None)
            if cb:
                on_main(cb, None, {"message": str(exc)})

    def _dispatch(self, msg):
        if "id" in msg:
            with self.lock:
                cb = self.pending.pop(msg["id"], None)
            if cb:
                on_main(cb, msg.get("result"), msg.get("error"))
            return
        method = msg.get("method")
        if method in ("Target.targetCreated", "Target.targetInfoChanged", "Target.targetDestroyed",
                      "Target.attachedToTarget", "Target.detachedFromTarget", "Runtime.bindingCalled"):
            on_main(self._on_event, method, msg.get("params") or {}, msg.get("sessionId"))

    # -------------------------------------------------------------- cibles --
    def _on_targets(self, result, error):
        for info in (result or {}).get("targetInfos", []):
            self._track(info)

    def _track(self, info):
        if info.get("type") != "page":
            return
        tid = info["targetId"]
        known = self.targets.get(tid)
        if known is None:
            self.targets[tid] = {"url": info.get("url", ""), "title": info.get("title", ""), "session": None}
            self.send("Target.attachToTarget", {"targetId": tid, "flatten": True},
                      cb=lambda res, err, tid=tid: self._attached(tid, res))
        else:
            old = known["url"]
            known.update(url=info.get("url", ""), title=info.get("title", ""))
            if tid == self.active and old != known["url"]:
                self.shell.on_brave_active(known["url"])

    def _attached(self, tid, res):
        if not res or tid not in self.targets:
            return
        session = res["sessionId"]
        self.targets[tid]["session"] = session
        self.sessions[session] = {"target": tid, "type": "page"}
        self._setup(session)
        if self.shell.is_tv_url(self.targets[tid]["url"]):
            self.set_tv(tid, True, reload=True)

    def _setup(self, session):
        self.send("Runtime.enable", {}, session)
        self.send("Runtime.addBinding", {"name": "__consoleBridge"}, session)
        self.send("Page.addScriptToEvaluateOnNewDocument", {"source": INJECT}, session)
        self.send("Runtime.evaluate", {"expression": INJECT}, session)
        self.send("Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": False, "flatten": True},
                  session)

    def _on_event(self, method, p, session):
        if method in ("Target.targetCreated", "Target.targetInfoChanged"):
            self._track(p.get("targetInfo") or {})
        elif method == "Target.targetDestroyed":
            tid = p.get("targetId")
            info = self.targets.pop(tid, None)
            if info and info.get("session"):
                self.sessions.pop(info["session"], None)
            self.tv_targets.discard(tid)
            if self.active == tid:
                self.active = None
        elif method == "Target.attachedToTarget":
            info = p.get("targetInfo") or {}
            if info.get("type") == "iframe":
                child = p["sessionId"]
                parent = self.sessions.get(session, {})
                self.sessions[child] = {"target": parent.get("target"), "type": "iframe", "frame": info.get("targetId")}
                self._setup(child)
        elif method == "Target.detachedFromTarget":
            self.sessions.pop(p.get("sessionId"), None)
        elif method == "Runtime.bindingCalled" and p.get("name") == "__consoleBridge":
            try:
                data = json.loads(p.get("payload") or "{}")
            except ValueError:
                return
            self._on_page_message(session, data)

    def _on_page_message(self, session, data):
        info = self.sessions.get(session)
        if not info:
            return
        kind = data.get("t")
        if kind == "visible" and info["type"] == "page" and data.get("v"):
            if self.active != info["target"]:
                self.active = info["target"]
                self.shell.on_brave_active(data.get("url", ""))
        elif kind == "focus":
            self.field = {"session": session, "field": data.get("field") or {}, "at": time.monotonic()}
            self.shell.on_brave_field_focus(self.field["field"])
        elif kind == "blur":
            if self.field and self.field["session"] == session:
                self.field["blurred"] = time.monotonic()

    # -------------------------------------------------------------- actions --
    def top_session(self, target=None):
        t = self.targets.get(target or self.active or "")
        return t.get("session") if t else None

    def active_info(self):
        t = self.targets.get(self.active or "")
        return dict(t, id=self.active) if t else None

    def focused_field(self, callback):
        """Interroge l'onglet actif : un champ texte a-t-il le focus ? callback(field|None)."""
        session = self.top_session()
        if not session:
            callback(None)
            return

        def done(res, err):
            value = ((res or {}).get("result") or {}).get("value") or ""
            if value:
                self.field = {"session": session, "field": json.loads(value), "at": time.monotonic()}
                callback(self.field["field"])
            else:
                callback(None)
        self.send("Runtime.evaluate", {"expression": "window.__consoleFocused ? window.__consoleFocused() : ''",
                                       "returnByValue": True}, session, cb=done)

    def commit_text(self, text, submit, callback):
        """Écrit le texte dans le dernier champ focalisé ; callback(ok)."""
        field = self.field
        if not field:
            callback(False)
            return
        session = field["session"]
        top = self.top_session(self.sessions.get(session, {}).get("target"))

        def after(res, err):
            ok = bool(((res or {}).get("result") or {}).get("value"))
            if ok and submit:
                self.key("Enter", 13, top or session, text="\r")
            callback(ok)
        self.send("Runtime.evaluate", {"expression": f"window.__consoleCommit({json.dumps(text)})",
                                       "returnByValue": True, "userGesture": True}, session, cb=after)

    def key(self, key, code, session=None, text=None):
        session = session or self.top_session()
        if not session:
            return
        down = {"type": "keyDown", "key": key, "code": key, "windowsVirtualKeyCode": code,
                "nativeVirtualKeyCode": code}
        if text:
            down.update(text=text, unmodifiedText=text)
        self.send("Input.dispatchKeyEvent", down, session)
        self.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": key, "code": key,
                                             "windowsVirtualKeyCode": code, "nativeVirtualKeyCode": code}, session)

    def site_info(self, callback):
        session = self.top_session()
        if not session:
            callback(None)
            return

        def done(res, err):
            value = ((res or {}).get("result") or {}).get("value")
            try:
                callback(json.loads(value) if value else None)
            except ValueError:
                callback(None)
        self.send("Runtime.evaluate", {"expression": "window.__consoleSiteInfo ? window.__consoleSiteInfo() : ''",
                                       "returnByValue": True}, session, cb=done)

    def navigate(self, url):
        session = self.top_session()
        if session:
            self.send("Page.navigate", {"url": url}, session)
        else:
            self.open(url)

    def open(self, url, tv=False):
        """Active un onglet déjà ouvert sur ce site, sinon en ouvre un nouveau."""
        def same_site(a, b):
            from urllib.parse import urlparse
            pa, pb = urlparse(a), urlparse(b)
            return pa.netloc.removeprefix("www.") == pb.netloc.removeprefix("www.") and \
                (pa.path.rstrip("/") == pb.path.rstrip("/") or pb.path in ("", "/"))
        for tid, info in self.targets.items():
            if same_site(info["url"], url):
                self.send("Target.activateTarget", {"targetId": tid})
                return
        if tv:
            def created(res, err):
                if not res:
                    return
                tid = res["targetId"]
                self.tv_targets.add(tid)

                def attached(res2, err2):
                    if res2:
                        s = res2["sessionId"]
                        self.send("Emulation.setUserAgentOverride", {"userAgent": TV_UA}, s)
                        self.send("Page.navigate", {"url": url}, s)
                self.send("Target.attachToTarget", {"targetId": tid, "flatten": True}, cb=attached)
            self.send("Target.createTarget", {"url": "about:blank"}, cb=created)
        else:
            self.send("Target.createTarget", {"url": url})

    def set_tv(self, tid, on, reload=False):
        session = self.top_session(tid)
        if not session:
            return
        if on:
            self.tv_targets.add(tid)
            self.send("Emulation.setUserAgentOverride", {"userAgent": TV_UA}, session)
            if reload:
                self.send("Page.reload", {"ignoreCache": False}, session)

    def fullscreen(self, on):
        tid = self.active
        if not tid:
            return

        def got(res, err):
            if res:
                self.send("Browser.setWindowBounds", {"windowId": res["windowId"],
                                                      "bounds": {"windowState": "fullscreen" if on else "normal"}})
        self.send("Browser.getWindowForTarget", {"targetId": tid}, cb=got)

    def new_tab(self, url="about:newtab"):
        self.send("Target.createTarget", {"url": url})

    def close_tab(self):
        if self.active:
            self.send("Target.closeTarget", {"targetId": self.active})

    def reload(self):
        session = self.top_session()
        if session:
            self.send("Page.reload", {}, session)

    def tabs(self):
        return [{"id": tid, "title": t["title"] or t["url"], "url": t["url"], "active": tid == self.active}
                for tid, t in self.targets.items() if not t["url"].startswith("devtools://")]

    def activate(self, tid):
        self.send("Target.activateTarget", {"targetId": tid})
