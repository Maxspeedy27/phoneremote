import socket
import struct
import sys

BLUETOOTH = "Bluetooth"
SIOCGIFADDR = 0x8915  # Linux ioctl: an interface's IPv4 address
# Interfaces a phone can't reach: loopback, containers, VMs.
VIRTUAL_PREFIXES = ("lo", "docker", "br-", "veth", "virbr", "vmnet", "vboxnet")


def _route_guesses():
    """Addresses of the interfaces this machine would send outside traffic from."""
    found = []
    for probe in ("8.8.8.8", "10.255.255.255"):
        # connect() on a UDP socket sends nothing; it just picks the outgoing interface.
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((probe, 80))
            found.append(s.getsockname()[0])
        except OSError:
            pass
        finally:
            s.close()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    return found


def _linux_interfaces():
    """(name, IPv4 address) for each Linux network interface that has one."""
    import fcntl
    found = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for _, name in socket.if_nameindex():
            try:
                ifreq = fcntl.ioctl(s.fileno(), SIOCGIFADDR, struct.pack("256s", name.encode()[:15]))
            except OSError:
                continue  # down, or no IPv4 address
            found.append((name, socket.inet_ntoa(ifreq[20:24])))
    finally:
        s.close()
    return found


def phone_addresses():
    """Addresses a phone might reach this laptop on, best guess first, as
    (ip, kind) pairs. kind is BLUETOOTH for Bluetooth tethering, else "".

    A Bluetooth tethering address comes first: the phone providing it can
    always reach it, even when the laptop is also on a Wi-Fi the phone isn't.
    Bluetooth interfaces are only recognised on Linux (BlueZ's bnep*).
    """
    bluetooth, others = [], []
    if sys.platform.startswith("linux"):
        try:
            interfaces = _linux_interfaces()
        except (ImportError, OSError):
            interfaces = []
        for name, ip in interfaces:
            if name.startswith("bnep"):
                bluetooth.append(ip)
            elif not name.startswith(VIRTUAL_PREFIXES):
                others.append(ip)
    result = []
    for ip in bluetooth + _route_guesses() + others:
        if ip not in [r[0] for r in result] and not ip.startswith(("127.", "0.")):
            result.append((ip, BLUETOOTH if ip in bluetooth else ""))
    return result or [("127.0.0.1", "")]
