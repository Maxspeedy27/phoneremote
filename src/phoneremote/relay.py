"""Reaching the laptop over the internet through a relay.

Without a relay the phone must reach the laptop directly, which fails when the
phone is on mobile data, on a different Wi-Fi, or on a venue Wi-Fi that keeps
devices apart. With a relay, the phone opens the remote from the relay's
website and both sides connect *out* to it, which works on any network that
has internet, with a real HTTPS certificate.

The relay only passes messages along. Everything stays end-to-end encrypted
with the keys from pairing, and the pairing key in the QR code's #fragment is
never sent to it, so the relay can't read or forge commands.

Each laptop has its own room: a random secret kept in the config folder. The
room id is derived from it (SHA-256), so the relay can check that whoever
claims to be the laptop knows the secret without storing anything.

Protocol (text messages over one WebSocket, see relay/src/worker.js):
  laptop -> relay   {"t": "auth", "secret": ...}           first message
  relay  -> laptop  {"t": "ready"}
  relay  -> laptop  '<phone id> {"i": request id, "p": "/api/cmd", "b": body}'
  laptop -> relay   '<phone id> {"i": request id, "s": status, "b": body}'
  "ping" / "pong"   keep-alive, answered by the relay without waking it
The relay only reads the phone id prefix, never the encrypted messages.
"""

import base64
import hashlib
import json
import os
import queue
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor

# The relay this build connects to unless told otherwise (--relay, or the
# control panel). Empty until you deploy one: see relay/README.md.
DEFAULT_RELAY_URL = ""

KEEPALIVE = 25            # seconds between pings
MAX_MESSAGE = 4 * 1024 * 1024
BACKOFF = (1, 2, 5, 10, 20, 30)


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def room_id(secret):
    """The public room id for a room secret: what goes into the phone's link."""
    return _b64(hashlib.sha256(secret.encode("ascii")).digest()[:16])


def load_room_secret(path):
    """This laptop's room secret, created on first use and kept owner-only."""
    try:
        secret = json.loads(path.read_text(encoding="utf-8"))["secret"]
        if isinstance(secret, str) and len(secret) >= 32:
            return secret
    except (OSError, ValueError, KeyError, TypeError):
        pass
    secret = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"secret": secret}, f)
    return secret


def phone_url(relay_url, room):
    return f"{relay_url.rstrip('/')}/r/{room}/"


def host_socket_url(relay_url, room):
    base = relay_url.rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[len("https://"):]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://"):]
    return f"{base}/ws/host/{room}"


class RelayClient:
    """Keeps the laptop connected to its room on the relay, in the background.

    handle(path, body, client) -> (status, body) answers one phone request;
    it is RemoteServer.handle_api, so relayed requests behave exactly like
    ones over the local network.
    """

    def __init__(self, relay_url, secret, handle, log=print, on_change=None):
        self.relay_url = relay_url.rstrip("/")
        self.secret = secret
        self.room = room_id(secret)
        self.handle = handle
        self.log = log
        self.on_change = on_change
        self.state = "connecting"      # connecting | online | offline
        self.error = None
        self._stop = threading.Event()
        self._ws = None
        self._send_lock = threading.Lock()
        self._thread = None
        # Commands must run in the order sent, so they share one worker;
        # pairing (which waits for approval), frames and cursor polls don't.
        self._commands = queue.Queue()
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="relay")

    @property
    def phone_url(self):
        return phone_url(self.relay_url, self.room)

    def start(self):
        if self._thread is not None:   # already running
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="relay")
        self._thread.start()
        threading.Thread(target=self._command_worker, daemon=True, name="relay-commands").start()
        threading.Thread(target=self._keepalive, daemon=True, name="relay-keepalive").start()

    def stop(self):
        self._stop.set()
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        self._commands.put(None)
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _set_state(self, state, error=None):
        changed = state != self.state
        self.state, self.error = state, error
        if changed and self.on_change:
            try:
                self.on_change(state)
            except Exception:
                pass

    # ----- connection -----

    def _run(self):
        from websockets.sync.client import connect

        failures = 0
        while not self._stop.is_set():
            try:
                with connect(host_socket_url(self.relay_url, self.room), open_timeout=10,
                             close_timeout=2, max_size=MAX_MESSAGE, ping_interval=None,
                             user_agent_header="PhoneRemote") as ws:
                    ws.send(json.dumps({"t": "auth", "secret": self.secret}))
                    reply = json.loads(ws.recv(timeout=10))
                    if reply.get("t") != "ready":
                        raise ConnectionError(reply.get("error") or "the relay refused this laptop")
                    self._ws = ws
                    failures = 0
                    self._set_state("online")
                    self.log("Connected to the internet relay.")
                    for message in ws:
                        self._dispatch(message)
                    # A clean close ends the loop without an error; it's still a drop.
                    raise ConnectionError("the relay closed the connection")
            except Exception as exc:
                if self._stop.is_set():
                    break
                was_online = self.state == "online"
                self._set_state("offline", f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__)
                if was_online:
                    self.log("Lost the connection to the internet relay; retrying.")
            finally:
                self._ws = None
            delay = BACKOFF[min(failures, len(BACKOFF) - 1)]
            failures += 1
            self._stop.wait(delay)
        self._set_state("offline")

    def _keepalive(self):
        while not self._stop.wait(KEEPALIVE):
            self._send_text("ping")

    def _send_text(self, text):
        ws = self._ws
        if ws is None:
            return
        try:
            with self._send_lock:
                ws.send(text)
        except Exception:
            pass   # the receive loop notices the broken connection

    # ----- requests from phones -----

    def _dispatch(self, message):
        if not isinstance(message, str) or message == "pong":
            return
        phone, _, raw = message.partition(" ")
        try:
            request = json.loads(raw)
            req_id, path, body = request["i"], request["p"], request["b"]
        except (ValueError, KeyError, TypeError):
            return
        if not phone.isalnum() or not isinstance(path, str):
            return
        job = (phone, req_id, path, body)
        if path == "/api/cmd":
            self._commands.put(job)
        else:
            try:
                self._pool.submit(self._answer, *job)
            except RuntimeError:
                pass   # shutting down

    def _command_worker(self):
        while True:
            job = self._commands.get()
            if job is None or self._stop.is_set():
                return
            self._answer(*job)

    def _answer(self, phone, req_id, path, body):
        status, reply = self.handle(path, body, "the internet relay")
        self._send_text(phone + " " + json.dumps({"i": req_id, "s": status, "b": reply},
                                                 separators=(",", ":")))
