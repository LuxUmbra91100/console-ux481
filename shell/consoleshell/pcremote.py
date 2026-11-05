"""PC distant (Moonlight / Sunshine) : santé, réparation, réveil par relais, alimentation.

- Santé de Sunshine : son port « appairé » (HTTPS, 47984) peut cesser de répondre alors que son
  port public (47989) répond encore. Moonlight dit alors le PC « injoignable » et envoie des
  Wake-on-LAN pour rien. On le détecte (état « half ») et, si l'identifiant Sunshine est enregistré,
  on relance Sunshine par son API, comme le bouton « Redémarrer » de sa page web. Une requête hors
  navigateur (sans en-tête Origin/Referer) n'est pas concernée par sa protection CSRF.
- Réveil par relais : un appareil toujours allumé sur le réseau du PC (un Raspberry…) envoie le
  Wake-on-LAN depuis l'intérieur, par SSH. Plus fiable qu'un paquet envoyé à travers Internet.
- Veille, redémarrage, arrêt du PC : par le serveur OpenSSH de Windows, avec la clé de la console.
"""
import base64
import http.client
import os
import re
import shlex
import socket
import ssl
import time
import urllib.error
import urllib.request

from .config import HOME, get_secret, set_secret
from .util import log, run

SSH_KEY = os.path.join(HOME, ".ssh", "id_ed25519")


def _tls():
    """Sunshine utilise un certificat auto-signé : pas de vérification (réseau privé / Tailscale)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                      urllib.request.HTTPSHandler(context=_tls()))


# ------------------------------------------------------------------ santé de Sunshine --
def https_alive(addr, port, timeout=3.0):
    """Le port HTTPS des appareils appairés répond-il ? Un refus TLS compte comme une réponse
    (Sunshine exige le certificat d'un appareil appairé) ; un silence ou une connexion refusée, non."""
    try:
        sock = socket.create_connection((addr.strip("[]"), int(port)), timeout=timeout)
    except OSError:
        return False
    try:
        sock.settimeout(timeout)
        tls = _tls().wrap_socket(sock, do_handshake_on_connect=False)
        try:
            tls.do_handshake()
            return True
        except ssl.SSLError:
            return True
        except (socket.timeout, TimeoutError):
            return False
        except OSError:
            return True              # connexion coupée net : quelqu'un a répondu
        finally:
            tls.close()
    finally:
        sock.close()


def check(host):
    """État complet d'un PC : celui de moonlight.server_status, plus "sunshine" = ok | half."""
    from . import moonlight
    st = moonlight.server_status(host)
    if st.get("online") and st.get("address"):
        st["sunshine"] = "ok" if https_alive(st["address"], st.get("https_port") or st["port"] - 5) else "half"
    return st


# --------------------------------------------------------------- API de Sunshine --
def credentials(uuid):
    c = get_secret(f"sunshine:{uuid}") if uuid else None
    return c if isinstance(c, dict) and c.get("user") and c.get("password") else None


def save_credentials(uuid, user, password):
    set_secret(f"sunshine:{uuid}", {"user": user, "password": password} if user and password else None)


def api(st, creds, method, path, timeout=8.0):
    """Requête authentifiée vers l'API de la page web de Sunshine (port HTTP + 1).
    → (code HTTP, détail) ; code 0 = connexion coupée par Sunshine, None = injoignable."""
    addr = st["address"]
    host = f"[{addr}]" if ":" in addr else addr
    url = f"https://{host}:{(st.get('port') or 47989) + 1}{path}"
    req = urllib.request.Request(url, method=method, data=b"" if method == "POST" else None)
    token = base64.b64encode(f"{creds['user']}:{creds['password']}".encode()).decode()
    req.add_header("Authorization", "Basic " + token)
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            return r.status, r.read(4096).decode(errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except (http.client.RemoteDisconnected, http.client.IncompleteRead, ConnectionResetError):
        return 0, "connexion coupée"
    except (OSError, http.client.HTTPException, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        return None, str(reason)


def verify_credentials(st, creds):
    """ok | auth (refusé) | unreachable"""
    code, _ = api(st, creds, "GET", "/api/config", timeout=6)
    if code == 401:
        return "auth"
    return "unreachable" if code is None else "ok"


def restart_sunshine(st, creds, wait=50.0):
    """Relance Sunshine et attend que son port appairé réponde de nouveau.
    → ok | auth | unreachable | stuck"""
    code, detail = api(st, creds, "POST", "/api/restart", timeout=10)
    if code == 401:
        return "auth"
    if code is None and "timed out" not in detail.lower():
        return "unreachable"
    # 200, connexion coupée (il redémarre aussitôt) ou délai dépassé (il était trop bloqué pour
    # répondre, mais a souvent reçu l'ordre) : on regarde s'il revient.
    https_port = st.get("https_port") or st["port"] - 5
    deadline = time.monotonic() + wait
    time.sleep(4)                    # le temps qu'il s'arrête vraiment
    while time.monotonic() < deadline:
        if https_alive(st["address"], https_port, timeout=2):
            return "ok"
        time.sleep(2)
    return "stuck"


# ---------------------------------------------------------------------------- SSH --
def resolve(target):
    """« utilisateur@nom » : si « nom » n'est pas résolu (MagicDNS de Tailscale désactivé sur la
    console), on demande son adresse à Tailscale."""
    user, _, host = (target or "").rpartition("@")
    if not host:
        return target
    try:
        socket.getaddrinfo(host, 22)
        return target
    except OSError:
        pass
    code, out, _ = run(["tailscale", "ip", "-4", host], timeout=5)
    ip = out.strip().splitlines()[0].strip() if code == 0 and out.strip() else ""
    return f"{user}@{ip}" if user and ip else (ip or target)


def ssh_cmd(target, remote, connect_timeout=6):
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={connect_timeout}",
           "-o", "StrictHostKeyChecking=accept-new", "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=2"]
    if os.path.exists(SSH_KEY):
        cmd += ["-i", SSH_KEY]
    return cmd + [target, remote]


# Envoyé au relais : Python est présent sur Raspberry Pi OS ; sinon on essaie « wakeonlan ».
_WOL_PY = ("import socket\n"
           "p=b'\\xff'*6+bytes.fromhex('{mac}')*16\n"
           "s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)\n"
           "s.setsockopt(socket.SOL_SOCKET,socket.SO_BROADCAST,1)\n"
           "for port in (9,7):\n"
           "    s.sendto(p,('255.255.255.255',port))\n")


def relay_wake_command(mac):
    hexmac = re.sub(r"[^0-9a-fA-F]", "", mac or "").lower()
    if len(hexmac) != 12:
        raise ValueError("adresse MAC inconnue")
    colons = ":".join(hexmac[i:i + 2] for i in range(0, 12, 2))
    return f"python3 -c {shlex.quote(_WOL_PY.format(mac=hexmac))} || wakeonlan {colons}"


def relay_wake(relay, mac):
    """Demande au relais (utilisateur@hôte) d'envoyer le Wake-on-LAN sur son réseau. → (ok, détail)"""
    try:
        remote = relay_wake_command(mac)
    except ValueError as exc:
        return False, str(exc)
    code, out, err = run(ssh_cmd(resolve(relay), remote), timeout=20)
    if code != 0:
        log.warning("réveil par %s impossible : %s", relay, (err or out).strip()[-300:])
    return code == 0, (err or out).strip()[-200:]


# Windows (OpenSSH, interpréteur cmd.exe par défaut).
PC_COMMANDS = {
    "sleep": "powershell -NoProfile -Command \"Add-Type -AssemblyName System.Windows.Forms; "
             "[System.Windows.Forms.Application]::SetSuspendState('Suspend', $false, $false)\"",
    "reboot": "shutdown /r /t 3",
    "shutdown": "shutdown /s /t 3",
}


def pc_power(target, action):
    """Veille / redémarrage / arrêt du PC par SSH. → (ok, détail)"""
    remote = PC_COMMANDS[action]
    code, out, err = run(ssh_cmd(resolve(target), remote), timeout=12)
    if code == 0:
        return True, ""
    text = (err or out).strip()
    # La mise en veille coupe la session SSH avant toute réponse : ce n'est pas un échec.
    if action == "sleep" and (code in (124, 255) or "closed" in text.lower()):    # 124 : délai dépassé
        return True, ""
    log.warning("PC %s par SSH impossible : %s", action, text[-300:])
    return False, text[-200:] or f"code {code}"
