import socket


def lan_ips():
    """Best guess for this machine's Wi-Fi/LAN IPv4 address first, then others."""
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
    ips = []
    for ip in found:
        if ip not in ips and not ip.startswith(("127.", "0.")):
            ips.append(ip)
    return ips or ["127.0.0.1"]
