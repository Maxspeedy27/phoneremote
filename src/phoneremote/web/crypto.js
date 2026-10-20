// Phone side of phoneremote/crypto.py: NaCl secretbox via tweetnacl.
// Runs in the browser (exports window.RemoteCrypto) and in Node for tests.
(function (root) {
  'use strict';
  const nacl = root.nacl || require('./vendor/nacl-fast.min.js');
  const encoder = new TextEncoder(), decoder = new TextDecoder();

  function b64e(bytes) {
    let s = '';
    for (const b of bytes) s += String.fromCharCode(b);
    return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  function b64d(text) {
    let s = String(text).replace(/-/g, '+').replace(/_/g, '/');
    while (s.length % 4) s += '=';
    const raw = atob(s);
    const out = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }

  function seal(key, obj) {
    const nonce = nacl.randomBytes(nacl.secretbox.nonceLength);
    const box = nacl.secretbox(encoder.encode(JSON.stringify(obj)), nonce, key);
    return { n: b64e(nonce), c: b64e(box) };
  }

  function unseal(key, msg) {
    const plain = nacl.secretbox.open(b64d(msg.c), b64d(msg.n), key);
    if (!plain) throw new Error('Reply from the laptop failed verification');
    return JSON.parse(decoder.decode(plain));
  }

  // Same 6-digit code as crypto.pairing_code() on the laptop.
  function pairingCode(msg) {
    const nonce = b64d(msg.n), box = b64d(msg.c);
    const both = new Uint8Array(nonce.length + box.length);
    both.set(nonce);
    both.set(box, nonce.length);
    const h = nacl.hash(both);
    const value = (h[0] * 16777216 + h[1] * 65536 + h[2] * 256 + h[3]) % 1000000;
    return String(value).padStart(6, '0');
  }

  const api = { b64e, b64d, seal, unseal, pairingCode, keyLength: nacl.secretbox.keyLength };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.RemoteCrypto = api;
})(typeof self !== 'undefined' ? self : globalThis);
