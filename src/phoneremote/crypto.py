"""Authenticated encryption shared with the phone.

Uses NaCl secretbox (XSalsa20-Poly1305). The phone runs tweetnacl-js
(web/crypto.js), which produces byte-identical messages: browsers disable
WebCrypto on plain-http pages, so we can't rely on it.

A sealed message is {"n": nonce, "c": ciphertext}, both unpadded base64url.
"""

import base64
import binascii
import hashlib
import json

import nacl.exceptions
import nacl.secret
import nacl.utils

KEY_SIZE = nacl.secret.SecretBox.KEY_SIZE
NONCE_SIZE = nacl.secret.SecretBox.NONCE_SIZE
MAX_ENCODED = 200_000


class CryptoError(Exception):
    pass


def b64e(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64d(text):
    if not isinstance(text, str) or len(text) > MAX_ENCODED:
        raise CryptoError("bad encoding")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, binascii.Error) as exc:
        raise CryptoError("bad encoding") from exc


def random_bytes(size):
    return nacl.utils.random(size)


def new_key():
    return nacl.utils.random(KEY_SIZE)


def seal(key, obj):
    nonce = nacl.utils.random(NONCE_SIZE)
    plain = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    ciphertext = nacl.secret.SecretBox(key).encrypt(plain, nonce).ciphertext
    return {"n": b64e(nonce), "c": b64e(ciphertext)}


def _parts(msg):
    if not isinstance(msg, dict):
        raise CryptoError("bad message")
    nonce, ciphertext = b64d(msg.get("n")), b64d(msg.get("c"))
    if len(nonce) != NONCE_SIZE:
        raise CryptoError("bad nonce")
    return nonce, ciphertext


def unseal(key, msg):
    nonce, ciphertext = _parts(msg)
    try:
        plain = nacl.secret.SecretBox(key).decrypt(ciphertext, nonce)
        obj = json.loads(plain)
    except (nacl.exceptions.CryptoError, ValueError) as exc:
        raise CryptoError("message failed verification") from exc
    if not isinstance(obj, dict):
        raise CryptoError("bad message")
    return obj


def pairing_code(msg):
    """6-digit code both screens show, so the user can match the request."""
    nonce, ciphertext = _parts(msg)
    digest = hashlib.sha512(nonce + ciphertext).digest()
    return f"{int.from_bytes(digest[:4], 'big') % 1_000_000:06d}"
