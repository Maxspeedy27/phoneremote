import ipaddress
import os
import socket
import struct
import sys

BLUETOOTH = "Bluetooth"
USB = "USB cable"
HOTSPOT = "iPhone hotspot"
# Linux drivers for a phone sharing its connection over a USB cable:
# Android's USB tethering (RNDIS / CDC Ethernet / NCM) and iPhone's (ipheth).
USB_TETHER_DRIVERS = {"rndis_host", "cdc_ether", "cdc_ncm", "cdc_eem", "ipheth"}
# An iPhone's Personal Hotspot always hands out addresses in this range,
# whether the laptop joined it over Wi-Fi, Bluetooth or a cable.
IPHONE_HOTSPOT = ipaddress.ip_network("172.20.10.0/28")
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


def _linux_driver(name):
    """The kernel driver behind a Linux network interface, e.g. "rndis_host"."""
    try:
        return os.path.basename(os.readlink(f"/sys/class/net/{name}/device/driver"))
    except OSError:
        return ""


def phone_addresses():
    """Addresses a phone might reach this laptop on, best guess first, as
    (ip, kind) pairs. kind is BLUETOOTH, USB or HOTSPOT when the laptop is
    linked to a phone that way, else "".

    Links to a phone come first: that phone can always reach them, even when
    the laptop is also on a Wi-Fi the phone isn't (or that keeps devices apart).
    Bluetooth and USB links are recognised on Linux by interface; an iPhone
    hotspot is recognised everywhere by its address range.
    """
    tethered, others = {}, []
    if sys.platform.startswith("linux"):
        try:
            interfaces = _linux_interfaces()
        except (ImportError, OSError):
            interfaces = []
        for name, ip in interfaces:
            if name.startswith("bnep"):
                tethered[ip] = BLUETOOTH
            elif name.startswith("usb") or _linux_driver(name) in USB_TETHER_DRIVERS:
                tethered[ip] = USB
            elif not name.startswith(VIRTUAL_PREFIXES):
                others.append(ip)
    result = []
    for ip in list(tethered) + _route_guesses() + others:
        if ip in [r[0] for r in result] or ip.startswith(("127.", "0.")):
            continue
        kind = tethered.get(ip, "")
        if not kind:
            try:
                kind = HOTSPOT if ipaddress.ip_address(ip) in IPHONE_HOTSPOT else ""
            except ValueError:
                pass
        result.append((ip, kind))
    # Phone links first, keeping the order found otherwise.
    result.sort(key=lambda r: 0 if r[1] else 1)
    return result or [("127.0.0.1", "")]
