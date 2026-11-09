import sys
import unittest
from unittest import mock

from kumpas import netinfo
from kumpas.netinfo import BLUETOOTH, HOTSPOT, USB, phone_addresses


class PhoneAddressesTest(unittest.TestCase):
    def addresses(self, interfaces, routes, drivers=None):
        """phone_addresses() on a fake Linux machine with these interfaces and route guesses."""
        drivers = drivers or {}
        with mock.patch.multiple(netinfo, _linux_interfaces=lambda: interfaces, _route_guesses=lambda: routes,
                                 _linux_driver=lambda name: drivers.get(name, "")), \
                mock.patch.object(netinfo.sys, "platform", "linux"):
            return phone_addresses()

    def test_usb_cable_to_a_phone_comes_first(self):
        result = self.addresses(
            [("wlp2s0", "192.168.1.20"), ("enx0a1b2c3d4e5f", "10.42.17.30"), ("usb0", "192.168.42.10")],
            ["192.168.1.20"], drivers={"enx0a1b2c3d4e5f": "rndis_host", "wlp2s0": "iwlwifi"})
        self.assertEqual(result, [("10.42.17.30", USB), ("192.168.42.10", USB), ("192.168.1.20", "")])

    def test_iphone_hotspot_is_recognised_by_its_addresses(self):
        result = self.addresses([("eth0", "10.0.0.5"), ("wlp2s0", "172.20.10.3")], ["10.0.0.5", "172.20.10.3"])
        self.assertEqual(result, [("172.20.10.3", HOTSPOT), ("10.0.0.5", "")])
        # The same on macOS and Windows, where only the route guesses are known.
        with mock.patch.object(netinfo, "_route_guesses", lambda: ["192.168.0.8", "172.20.10.2"]), \
                mock.patch.object(netinfo.sys, "platform", "win32"):
            self.assertEqual(phone_addresses(), [("172.20.10.2", HOTSPOT), ("192.168.0.8", "")])

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
