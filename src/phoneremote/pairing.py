"""Pairing a phone and authenticating its commands.

Threat model: someone else on the same Wi-Fi, or someone who photographs the
QR code on a projected screen, must not be able to control the laptop or read
typed text.

- The QR code carries a one-time pairing key in the URL fragment (#k=...),
  which browsers never send over the network.
- Pairing must be approved on the laptop, where both screens show the same
  6-digit code. Approval issues a long-term device key. The pairing key is then
  replaced (also after a refusal or timeout), so an old QR code is useless.
- Only one phone is paired at a time; pairing another one replaces it.
- Every request is encrypted and authenticated. Each page load starts a fresh
  session chosen by the laptop and numbers its requests, so recorded traffic
  can't be replayed.

Known limitation: by default the page itself is served over plain HTTP, so an
attacker who can actively tamper with LAN traffic (e.g. ARP spoofing) could
serve modified JavaScript. HTTPS (tls.py) closes that with a certificate the
phone trusts; a self-signed one only protects after the first visit.
"""

import json
import os
import threading
import time
from dataclasses import dataclass

from .crypto import CryptoError, b64d, b64e, new_key, pairing_code, random_bytes, seal, unseal

APPROVAL_TIMEOUT = 60  # seconds the laptop user has to approve a pairing


class PairingError(Exception):
    """A request the phone should be told about: HTTP status, code, message."""

    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code


NOT_PAIRED = (401, "unpaired", "This phone isn't paired with the laptop. Scan the QR code shown on the laptop.")


@dataclass
class Device:
    id: str
    key: bytes
    name: str
    paired_at: float


class DeviceStore:
    """Remembers the paired phone so it reconnects after the laptop restarts."""

    def __init__(self, path):
        self.path = path

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return Device(data["id"], b64d(data["key"]), data["name"], data["paired_at"])
        except FileNotFoundError:
            return None
        except (ValueError, KeyError, TypeError, CryptoError):
            return None  # corrupt file: behave as unpaired

    def save(self, device):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = {"id": device.id, "key": b64e(device.key), "name": device.name, "paired_at": device.paired_at}
        tmp = self.path.with_name(self.path.name + ".tmp")
        # Created owner-only: the file holds the key that controls this laptop.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, self.path)

    def clear(self):
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def clean_name(name):
    if not isinstance(name, str):
        return "Phone"
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    return name[:40] or "Phone"


class Pairing:
    """Pairing state, the paired device and its current session.

    approve(name, code, timeout) is called on a server thread and blocks until
    the laptop user answers; it returns True to allow pairing.
    on_key_changed(reason) is called after the pairing key is replaced, with
    reason "paired" or "refused", so the UI can show the new QR code.
    """

    def __init__(self, store, approve, host="laptop", on_key_changed=None):
        self.store = store
        self.approve = approve
        self.host = host
        self.on_key_changed = on_key_changed
        self._lock = threading.Lock()
        self._approval_lock = threading.Lock()  # one pairing prompt at a time
        self._pairing_key = new_key()
        self._device = store.load()
        self._session = None  # [session id, last command, last frame, last cursor poll number]

    @property
    def device(self):
        return self._device

    def pairing_fragment(self):
        with self._lock:
            return "k=" + b64e(self._pairing_key)

    def forget(self):
        with self._lock:
            self._device = None
            self._session = None
        self.store.clear()

    def pair(self, msg):
        with self._lock:
            key = self._pairing_key
        try:
            request = unseal(key, msg)
        except CryptoError:
            raise PairingError(403, "pairing-expired",
                               "This QR code has expired. Scan the one currently shown on the laptop.")
        if request.get("t") != "pair":
            raise PairingError(400, "bad-request", "Malformed pairing request.")
        name, code = clean_name(request.get("name")), pairing_code(msg)

        if not self._approval_lock.acquire(blocking=False):
            raise PairingError(409, "busy", "Another phone is waiting for approval on the laptop.")
        try:
            approved = self.approve(name, code, APPROVAL_TIMEOUT)
            if approved:
                device = Device(b64e(random_bytes(16)), new_key(), name, time.time())
                self.store.save(device)
            with self._lock:
                if key is not self._pairing_key:  # a parallel request already used it
                    raise PairingError(403, "pairing-expired", "This QR code has expired.")
                self._pairing_key = new_key()
                if approved:
                    self._device = device
                    self._session = None
        finally:
            self._approval_lock.release()

        if self.on_key_changed:
            self.on_key_changed("paired" if approved else "refused")
        if not approved:
            raise PairingError(403, "denied", "Pairing was refused or timed out on the laptop.")
        return seal(key, {"t": "paired", "id": device.id, "key": b64e(device.key), "host": self.host})

    def _open(self, msg, kind):
        with self._lock:
            device = self._device
        if device is None or not isinstance(msg, dict) or msg.get("d") != device.id:
            raise PairingError(*NOT_PAIRED)
        try:
            request = unseal(device.key, msg)
        except CryptoError:
            raise PairingError(*NOT_PAIRED)
        if request.get("t") != kind:
            raise PairingError(400, "bad-request", "Unexpected message type.")
        return device, request

    def hello(self, msg):
        """Start a new session for the paired phone (one per page load)."""
        device, _ = self._open(msg, "hello")
        session_id = b64e(random_bytes(16))
        with self._lock:
            if device is not self._device:
                raise PairingError(*NOT_PAIRED)
            self._session = [session_id, 0, 0, 0]
        return device, seal(device.key, {"t": "session", "s": session_id, "host": self.host})

    def _check_sequence(self, request, slot):
        # Commands, screen frames and cursor polls are numbered separately
        # (slots 1-3), since the phone sends them over parallel connections.
        seq = request.get("q")
        with self._lock:
            if self._session is None or request.get("s") != self._session[0]:
                raise PairingError(401, "session", "Session expired; reconnecting.")
            if not isinstance(seq, int) or isinstance(seq, bool) or seq <= self._session[slot]:
                raise PairingError(401, "session", "Out-of-order or repeated request.")
            self._session[slot] = seq

    def open_command(self, msg):
        """Verify a command message and return its list of operations."""
        _, request = self._open(msg, "cmd")
        self._check_sequence(request, 1)
        return request.get("ops")

    def open_cursor(self, msg):
        """Verify a cursor-position poll; returns (device, request)."""
        device, request = self._open(msg, "cursor")
        self._check_sequence(request, 3)
        return device, request

    def open_frame(self, msg):
        """Verify a screen-frame request; returns (device, request) for sealing the reply."""
        device, request = self._open(msg, "frame")
        self._check_sequence(request, 2)
        return device, request
