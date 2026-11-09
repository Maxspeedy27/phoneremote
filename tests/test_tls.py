import ipaddress
import os
import ssl
import sys
import tempfile
import unittest
from pathlib import Path

from cryptography import x509

from kumpas import tls


class SelfSignedTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name) / "conf"

    def sans(self, cert_path):
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        return cert, {str(i) for i in san.get_values_for_type(x509.IPAddress)}, set(san.get_values_for_type(x509.DNSName))

    def test_certificate_covers_addresses_and_loads(self):
        cert_path, key_path = tls.self_signed(self.folder, ["192.168.1.20", "192.168.44.7"], "mylaptop")
        cert, ips, names = self.sans(cert_path)
        self.assertEqual(ips, {"192.168.1.20", "192.168.44.7", "127.0.0.1"})
        self.assertIn("mylaptop.local", names)
        days = (cert.not_valid_after_utc - cert.not_valid_before_utc).days
        self.assertLessEqual(days, 825)   # Apple's limit for TLS certificates
        tls.server_context(cert_path, key_path)   # loads without error
        if sys.platform != "win32":
            self.assertEqual(os.stat(key_path).st_mode & 0o777, 0o600)
        self.assertRegex(tls.fingerprint(cert_path), r"^([0-9A-F]{2}:){31}[0-9A-F]{2}$")

    def test_reused_until_an_address_is_missing(self):
        first, _ = tls.self_signed(self.folder, ["10.0.0.5"], "box")
        pem = first.read_bytes()
        tls.self_signed(self.folder, ["10.0.0.5"], "box")
        self.assertEqual(first.read_bytes(), pem)
        tls.self_signed(self.folder, ["10.0.0.9"], "box")   # moved to another network
        self.assertNotEqual(first.read_bytes(), pem)
        self.assertIn("10.0.0.9", self.sans(first)[1])

    def test_odd_hostnames_are_left_out(self):
        cert_path, _ = tls.self_signed(self.folder, ["10.0.0.5"], "my laptop's")
        names = self.sans(cert_path)[2]
        self.assertEqual(names, {"localhost"})


if __name__ == "__main__":
    unittest.main()
