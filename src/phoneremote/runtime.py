"""The running remote: phone server, pairing, screen view, address and HTTPS.

Shared by the terminal interface (cli.py) and the desktop app's control panel
(hostui.py), which can change the address and HTTPS while running.
"""

import json
import socket
import threading

from .netinfo import BLUETOOTH, phone_addresses
from .pairing import Pairing
from .screen import ScreenGrabber
from .server import RemoteServer
from .system import config_dir


class SetupError(Exception):
    """Startup failed in a way the user can fix; the message says how."""


class Settings:
    """Small JSON file of choices made in the control panel."""

    DEFAULTS = {"https": False, "screen": True}

    def __init__(self, path):
        self.path = path
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        self.values = {k: data.get(k, v) if isinstance(data.get(k), type(v)) else v
                       for k, v in self.DEFAULTS.items()}

    def __getitem__(self, key):
        return self.values[key]

    def __setitem__(self, key, value):
        self.values[key] = value
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.path.write_text(json.dumps(self.values), encoding="utf-8")
        except OSError:
            pass


class Runtime:
    def __init__(self, backend, store, approver, port=8765, ip=None, https=False,
                 cert=None, key=None, hostname=None, screen=True, log=print):
        self.backend = backend
        self.log = log
        self.hostname = hostname
        self.custom_cert = (cert, key) if cert else None
        self.fingerprint = None
        self.https_problem = None
        self.listeners = []           # called with no arguments when the pairing URL changes
        self.addresses = phone_addresses()
        self.ip, self.kind = self.addresses[0]
        self.unknown_ip = False
        if ip:
            self.ip, self.kind = ip, dict(self.addresses).get(ip)
            self.unknown_ip = self.kind is None and ip not in dict(self.addresses)
        self.screen = ScreenGrabber(enabled=screen)
        self.pairing = Pairing(store, approver, host=socket.gethostname(),
                               on_key_changed=self._key_changed)
        self.server = self._open_server(port)
        self.port = self.server.server_address[1]
        self.set_https(https)
        self._thread = None

    def _open_server(self, port):
        last_error = None
        for candidate in range(port, port + 20):
            try:
                return RemoteServer(("0.0.0.0", candidate), self.backend, self.pairing,
                                    screen=self.screen, log=self.log)
            except OSError as exc:
                last_error = exc
        raise SetupError(f"Could not open a port between {port} and {port + 19}: {last_error}")

    # ----- addresses and URLs -----

    @property
    def https(self):
        return self.server.ssl_context is not None

    @property
    def base_url(self):
        host = self.hostname or self.ip
        return f"{self.server.scheme}://{host}:{self.port}/"

    @property
    def pairing_url(self):
        return f"{self.base_url}#{self.pairing.pairing_fragment()}"

    @property
    def network(self):
        return "connected over Bluetooth tethering" if self.kind == BLUETOOTH else "on the same Wi-Fi"

    def set_ip(self, ip):
        known = dict(self.addresses)
        if ip not in known:
            raise ValueError("not one of this laptop's addresses")
        self.ip, self.kind = ip, known[ip]
        self._changed()

    def refresh_addresses(self):
        self.addresses = phone_addresses()

    # ----- HTTPS -----

    def set_https(self, on):
        """Turn HTTPS on or off. Takes effect for new connections at once."""
        self.https_problem = None
        if not on:
            self.server.ssl_context = None
            self.fingerprint = None
            self._changed()
            return True
        from . import tls

        try:
            if self.custom_cert:
                cert, key = self.custom_cert
            else:
                ips = [a for a, _ in self.addresses]
                if self.ip not in ips:
                    ips.append(self.ip)
                cert, key = tls.self_signed(config_dir(), ips, socket.gethostname())
            context = tls.server_context(cert, key)
            self.fingerprint = tls.fingerprint(cert) if not self.custom_cert else None
        except ImportError:
            self.https_problem = "HTTPS needs the cryptography package (pip install cryptography)."
        except (OSError, ValueError) as exc:
            self.https_problem = f"Couldn't set up HTTPS: {exc}"
        if self.https_problem:
            self.server.ssl_context = None
            self._changed()
            return False
        self.server.ssl_context = context
        self._changed()
        return True

    @property
    def self_signed(self):
        return self.https and not self.custom_cert

    # ----- running -----

    def _key_changed(self, reason):
        self._changed(reason)

    def _changed(self, reason=None):
        for listener in list(self.listeners):
            try:
                listener(reason)
            except Exception:
                pass

    def start(self):
        """Serve phones on a background thread."""
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

    def serve_forever(self):
        self.server.serve_forever()

    def close(self):
        if self._thread:
            self.server.shutdown()
        with self.server.input_lock:
            try:
                self.backend.mouse_up()
                self.backend.close()
            except Exception:
                pass
        self.server.server_close()
