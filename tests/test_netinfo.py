import sys
import unittest
from unittest import mock

from phoneremote import netinfo
from phoneremote.netinfo import BLUETOOTH, phone_addresses


class PhoneAddressesTest(unittest.TestCase):
    def addresses(self, interfaces, routes):
        """phone_addresses() on a fake Linux machine with these interfaces and route guesses."""
        with mock.patch.multiple(netinfo, _linux_interfaces=lambda: interfaces, _route_guesses=lambda: routes), \
                mock.patch.object(netinfo.sys, "platform", "linux"):
            return phone_addresses()

    def test_bluetooth_tethering_comes_first(self):
        result = self.addresses(
            [("lo", "127.0.0.1"), ("wlp2s0", "192.168.1.20"), ("bnep0", "192.168.44.7")],
            ["192.168.1.20", "127.0.1.1"])
        self.assertEqual(result, [("192.168.44.7", BLUETOOTH), ("192.168.1.20", "")])

    def test_route_guess_comes_before_other_interfaces(self):
        result = self.addresses([("eth0", "10.0.0.5"), ("wlp2s0", "192.168.1.20")], ["192.168.1.20"])
        self.assertEqual(result, [("192.168.1.20", ""), ("10.0.0.5", "")])

    def test_skips_virtual_interfaces(self):
        result = self.addresses(
            [("docker0", "172.17.0.1"), ("virbr0", "192.168.122.1"), ("wlp2s0", "192.168.1.20")],
            ["192.168.1.20"])
        self.assertEqual(result, [("192.168.1.20", "")])

    def test_falls_back_to_localhost(self):
        self.assertEqual(self.addresses([("lo", "127.0.0.1")], []), [("127.0.0.1", "")])

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux interface listing")
    def test_lists_real_linux_interfaces(self):
        self.assertIn(("lo", "127.0.0.1"), netinfo._linux_interfaces())


if __name__ == "__main__":
    unittest.main()
