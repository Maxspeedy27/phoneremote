import json
import shutil
import subprocess
import unittest
from importlib.resources import files

from phoneremote.crypto import CryptoError, b64d, b64e, new_key, pairing_code, seal, unseal

CRYPTO_JS = files("phoneremote") / "web" / "crypto.js"


class CryptoTest(unittest.TestCase):
    def test_roundtrip(self):
        key = new_key()
        self.assertEqual(unseal(key, seal(key, {"a": 1, "s": "héllo"})), {"a": 1, "s": "héllo"})

    def test_wrong_key_rejected(self):
        with self.assertRaises(CryptoError):
            unseal(new_key(), seal(new_key(), {"a": 1}))

    def test_tampering_rejected(self):
        key = new_key()
        msg = seal(key, {"a": 1})
        raw = bytearray(b64d(msg["c"]))
        raw[-1] ^= 1
        with self.assertRaises(CryptoError):
            unseal(key, {"n": msg["n"], "c": b64e(bytes(raw))})

    def test_malformed_messages_rejected(self):
        key = new_key()
        for bad in (None, [], {}, {"n": "x", "c": "y"}, {"n": 5, "c": "AA"}, {"n": "é", "c": "AA"}):
            with self.assertRaises(CryptoError):
                unseal(key, bad)

    def test_nonces_are_fresh(self):
        key = new_key()
        self.assertNotEqual(seal(key, {})["n"], seal(key, {})["n"])

    def test_pairing_code_is_six_digits_and_stable(self):
        msg = seal(new_key(), {"t": "pair"})
        code = pairing_code(msg)
        self.assertRegex(code, r"^\d{6}$")
        self.assertEqual(code, pairing_code(dict(msg)))


@unittest.skipUnless(shutil.which("node"), "node not installed")
class JavaScriptInteropTest(unittest.TestCase):
    """The phone's crypto.js and the laptop's crypto.py must agree byte for byte."""

    def run_js(self, script, payload):
        result = subprocess.run(
            ["node", "-e", f"const rc = require({json.dumps(str(CRYPTO_JS))});"
                           f"const input = JSON.parse(process.argv[1]); {script}",
             json.dumps(payload)],
            capture_output=True, text=True, timeout=30, check=True)
        return json.loads(result.stdout)

    def test_js_seals_python_opens(self):
        key = new_key()
        out = self.run_js(
            "const key = rc.b64d(input.key);"
            "const msg = rc.seal(key, {t: 'pair', name: 'Pixel (Chrome) é'});"
            "console.log(JSON.stringify({msg, code: rc.pairingCode(msg)}));",
            {"key": b64e(key)})
        self.assertEqual(unseal(key, out["msg"]), {"t": "pair", "name": "Pixel (Chrome) é"})
        self.assertEqual(out["code"], pairing_code(out["msg"]))

    def test_python_seals_js_opens(self):
        key = new_key()
        msg = seal(key, {"t": "session", "s": "abc", "host": "läptop"})
        out = self.run_js(
            "console.log(JSON.stringify(rc.unseal(rc.b64d(input.key), input.msg)));",
            {"key": b64e(key), "msg": msg})
        self.assertEqual(out, {"t": "session", "s": "abc", "host": "läptop"})

    def test_js_rejects_wrong_key(self):
        msg = seal(new_key(), {"a": 1})
        out = self.run_js(
            "try { rc.unseal(rc.b64d(input.key), input.msg); console.log('false'); }"
            "catch (e) { console.log('true'); }",
            {"key": b64e(new_key()), "msg": msg})
        self.assertTrue(out)


if __name__ == "__main__":
    unittest.main()
