"""The running remote: phone server, pairing, screen view, address and HTTPS.

Shared by the terminal interface (cli.py) and the desktop app's control panel
(hostui.py), which can change the address and HTTPS while running.
"""

import json
import socket
import threading

from .blanker import Blanker
from .netinfo import BLUETOOTH, HOTSPOT, USB, phone_addresses
from .pairing import Pairing
from .screen import ScreenGrabber
from .server import RemoteServer
from .system import config_dir


class SetupError(Exception):
    """Startup failed in a way the user can fix; the message says how."""


class Settings:
    """Small JSON file of choices made in the control panel."""

    # The relay is off until the user turns it on: with it off, nothing leaves the local network.
    DEFAULTS = {"https": False, "screen": True, "relay": False, "relay_url": ""}

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
    NETWORK_CHECK_SECONDS = 3   # how often to notice the laptop joining another network

    def __init__(self, backend, store, approver, port=8765, ip=None, https=False,
                 cert=None, key=None, hostname=None, screen=True, relay_url=None, log=print):
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
        self.fixed_ip = bool(ip)      # --ip: always use that address
        self.picked_ip = False        # chosen in the panel: keep it while the laptop has it
        if ip:
            self.ip, self.kind = ip, dict(self.addresses).get(ip)
            self.unknown_ip = self.kind is None and ip not in dict(self.addresses)
        self._stopping = threading.Event()
        self.screen = ScreenGrabber(enabled=screen)
        self.blanker = Blanker()
        self.pairing = Pairing(store, approver, host=socket.gethostname(),
                               on_key_changed=self._key_changed)
        self.server = self._open_server(port)
        self.port = self.server.server_address[1]
        self.set_https(https)
        self._thread = None
        self.relay = None
        self.set_relay(relay_url)

    def _open_server(self, port):
        last_error = None
        for candidate in range(port, port + 20):
            try:
                return RemoteServer(("0.0.0.0", candidate), self.backend, self.pairing,
                                    screen=self.screen, log=self.log, blanker=self.blanker)
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
        return {BLUETOOTH: "connected over Bluetooth tethering", USB: "connected with a USB cable",
                HOTSPOT: "on the same hotspot"}.get(self.kind, "on the same Wi-Fi")

    # ----- internet relay -----

    def set_relay(self, url):
        """Connect to an internet relay at url (None or "" to stop using one)."""
        if self.relay is not None:
            self.relay.stop()
            self.relay = None
        if url:
            from .relay import RelayClient, load_room_secret

            self.relay = RelayClient(url, load_room_secret(config_dir() / "relay.json"),
                                     self.server.handle_api, log=self.log,
                                     on_change=lambda state: self._changed("relay"))
            if self._thread is not None or self._serving:
                self.relay.start()
        self._changed("relay")

    @property
    def relay_online(self):
        return self.relay is not None and self.relay.state == "online"

    @property
    def relay_pairing_url(self):
        """The link that works from any network, through the relay (None without one)."""
        if self.relay is None:
            return None
        return f"{self.relay.phone_url}#{self.pairing.pairing_fragment()}"

    def set_ip(self, ip):
        known = dict(self.addresses)
        if ip not in known:
            raise ValueError("not one of this laptop's addresses")
        self.ip, self.kind = ip, known[ip]
        self.picked_ip = True
        self._changed()

    def refresh_addresses(self):
        self.addresses = phone_addresses()

    def check_network(self):
        """Look again at this laptop's addresses, e.g. after it joined a phone's
        hotspot. Moves the pairing URL to the best address unless one was chosen
        (and the laptop still has it). Returns True when the URL's address changed."""
        addresses = phone_addresses()
        if addresses == self.addresses:
            return False
        self.addresses = addresses
        known = dict(addresses)
        if self.fixed_ip:
            self.kind = known.get(self.ip)
            return False
        if self.picked_ip and self.ip in known:
            self.kind = known[self.ip]
            return False
        self.picked_ip = False
        ip, kind = addresses[0]
        if ip == self.ip:
            self.kind = kind
            return False
        self.ip, self.kind = ip, kind
        if self.self_signed:
            self.set_https(True)   # a certificate that names the new address
        if not self.hostname:
            self.log(f"The laptop's network changed. Phones can now connect at {self.base_url}")
        self._changed("address")
        return True

    def _watch_network(self):
        while not self._stopping.wait(self.NETWORK_CHECK_SECONDS):
            try:
                self.check_network()
            except Exception:
                pass

    def _start_watching(self):
        threading.Thread(target=self._watch_network, daemon=True).start()

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

    _serving = False

    def start(self):
        """Serve phones on a background thread."""
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()
        self._start_watching()
        if self.relay:
            self.relay.start()

    def serve_forever(self):
        self._serving = True
        self._start_watching()
        if self.relay:
            self.relay.start()
        self.server.serve_forever()

    def close(self):
        self._stopping.set()
        self.blanker.close()   # never leave the projector dark
        if self.relay:
            self.relay.stop()
        if self._thread:
            self.server.shutdown()
        with self.server.input_lock:
            try:
                self.backend.mouse_up()
                self.backend.close()
            except Exception:
                pass
        self.server.server_close()
