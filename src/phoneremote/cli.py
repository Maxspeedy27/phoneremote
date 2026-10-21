"""Command-line entry point: `phoneremote` or `python -m phoneremote`."""

import argparse
import ipaddress
import socket
import sys

from . import __version__
from .backends import CHOICES, create_backend
from .console import TerminalApprover, auto_approve, print_qr
from .netinfo import BLUETOOTH, phone_addresses
from .pairing import DeviceStore, Pairing
from .server import RemoteServer
from .system import IS_MAC, IS_WAYLAND, IS_WIN, config_dir


def make_server(port, backend, pairing):
    last_error = None
    for candidate in range(port, port + 20):
        try:
            return RemoteServer(("0.0.0.0", candidate), backend, pairing)
        except OSError as exc:
            last_error = exc
    sys.exit(f"Could not open a port between {port} and {port + 19}: {last_error}")


def ipv4(text):
    try:
        return str(ipaddress.IPv4Address(text))
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an IPv4 address: {text}")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="phoneremote",
                                     description="Use your phone's browser as a remote for this laptop.")
    parser.add_argument("--port", type=int, default=8765, help="port to listen on (default 8765)")
    parser.add_argument("--backend", choices=CHOICES, default="auto",
                        help="how to send input: pyautogui, or uinput (Linux virtual device that "
                             "also works on Wayland). auto picks uinput on Wayland.")
    parser.add_argument("--ip", type=ipv4,
                        help="laptop address to put in the QR code, e.g. its Bluetooth tethering "
                             "address (default: best guess)")
    parser.add_argument("--light-qr", action="store_true",
                        help="draw the QR code for a terminal with a light background")
    parser.add_argument("--forget", action="store_true", help="unpair the remembered phone before starting")
    parser.add_argument("--no-confirm", action="store_true",
                        help="pair any phone that scans the QR code without asking (less secure)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)
    try:  # show each line immediately even when output goes to a file or pipe
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass

    if not args.no_confirm and not sys.stdin.isatty():
        sys.exit("Pairing approval needs an interactive terminal. Run from a terminal, or pass --no-confirm.")

    store = DeviceStore(config_dir() / "paired-phone.json")
    if args.forget:
        store.clear()
        print("Forgot the paired phone.")

    try:
        backend = create_backend(args.backend)
    except RuntimeError as exc:
        sys.exit(str(exc))

    approver = auto_approve if args.no_confirm else TerminalApprover()
    pairing = Pairing(store, approver, host=socket.gethostname())
    server = make_server(args.port, backend, pairing)
    addresses = phone_addresses()
    ip, kind = addresses[0]
    if args.ip:
        ip, kind = args.ip, dict(addresses).get(args.ip)
        if kind is None:
            print(f"Warning: {ip} is not one of this laptop's addresses.")
    base_url = f"http://{ip}:{server.server_address[1]}/"
    network = "connected over Bluetooth tethering" if kind == BLUETOOTH else "on the same Wi-Fi"

    def show_pairing(with_qr=True):
        url = f"{base_url}#{pairing.pairing_fragment()}"
        if with_qr:
            print(f"To pair a phone, scan this QR code with its camera ({network}), or open:\n")
            print(f"  {url}\n")
            print_qr(url, args.light_qr)
        else:
            print(f"    To pair a different phone later, open: {url}")

    def on_key_changed(reason):
        if reason == "paired":
            print(f"    On this phone you can now simply open {base_url}")
            show_pairing(with_qr=False)
        else:
            print("    That QR code is no longer valid. New one:\n")
            show_pairing()

    pairing.on_key_changed = on_key_changed

    print(f"\nPhone Remote {__version__} is running.\n")
    if pairing.device:
        print(f"Paired phone: {pairing.device.name}. On it, open {base_url}")
        print("(Pairing another phone replaces it.)\n")
    show_pairing()
    others = [(a, k) for a, k in addresses if a != ip]
    if others:
        listed = ", ".join(f"{a} ({k})" if k else a for a, k in others)
        print(f"If the phone can't open the link, try another address of this laptop: {listed}")
        print("  Restart with --ip <address> to put it in the QR code.\n")
    print(f"Input: {backend.name}")
    if IS_MAC:
        print("macOS: allow this terminal under System Settings > Privacy & Security > Accessibility.")
    elif IS_WIN:
        print("Windows: if a firewall prompt appears, allow access on Private networks.")
    elif IS_WAYLAND and backend.name == "pyautogui":
        print("Warning: this is a Wayland session; pyautogui only works under X11. Try --backend uinput.")
    print("Press Ctrl+C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        with server.input_lock:
            try:
                backend.mouse_up()
                backend.close()
            except Exception:
                pass
        server.server_close()


if __name__ == "__main__":
    main()
