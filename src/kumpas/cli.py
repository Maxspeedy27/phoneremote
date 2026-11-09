"""Entry points: `kumpas` (terminal) and `kumpas --app` (desktop app).

The terminal version prints the QR code and asks for approval on stdin. The
app version, used by the installers, opens a control panel in the browser.
"""

import argparse
import ipaddress
import sys
import webbrowser

from . import __version__
from .backends import CHOICES, create_backend
from .console import TerminalApprover, auto_approve, print_qr
from .pairing import DeviceStore
from .runtime import Runtime, Settings, SetupError
from .system import IS_MAC, IS_WAYLAND, IS_WIN, config_dir


def ipv4(text):
    try:
        return str(ipaddress.IPv4Address(text))
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an IPv4 address: {text}")


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="kumpas",
                                     description="Use your phone's browser as a remote for this laptop.")
    parser.add_argument("--app", action="store_true",
                        help="run as a desktop app: open a control panel in the browser instead of "
                             "using this terminal")
    parser.add_argument("--port", type=int, default=8765, help="port to listen on (default 8765)")
    parser.add_argument("--backend", choices=CHOICES, default="auto",
                        help="how to send input: pyautogui, or uinput (Linux virtual device that "
                             "also works on Wayland). auto picks uinput on Wayland.")
    parser.add_argument("--ip", type=ipv4,
                        help="laptop address to put in the QR code, e.g. its Bluetooth tethering "
                             "address (default: best guess)")
    parser.add_argument("--https", action="store_true",
                        help="serve the phone page over HTTPS with a self-signed certificate (the phone "
                             "shows a warning once); unlocks keep-screen-on and tilt pointing")
    parser.add_argument("--cert", help="HTTPS certificate file (PEM) to use instead of a self-signed one")
    parser.add_argument("--key", help="private key file (PEM) for --cert")
    parser.add_argument("--hostname",
                        help="name to put in the QR code instead of the IP address, e.g. the domain "
                             "name of --cert")
    parser.add_argument("--no-screen", action="store_true", help="don't let the phone view this screen")
    parser.add_argument("--relay", metavar="URL",
                        help="internet relay to connect through, so phones work from any network "
                             "(e.g. https://relay.example.com); see relay/README.md")
    parser.add_argument("--no-relay", action="store_true", help="local network only, no internet relay")
    parser.add_argument("--light-qr", action="store_true",
                        help="draw the QR code for a terminal with a light background")
    parser.add_argument("--forget", action="store_true", help="unpair the remembered phone before starting")
    parser.add_argument("--no-confirm", action="store_true",
                        help="pair any phone that scans the QR code without asking (less secure)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)
    if bool(args.cert) != bool(args.key):
        parser.error("--cert and --key go together")
    return args


def main(argv=None):
    args = parse_args(argv)
    try:  # show each line immediately even when output goes to a file or pipe
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass
    if args.app:
        return run_app(args)
    return run_terminal(args)


def relay_url(args, settings=None):
    """Which internet relay to use: --relay, else the panel's choice, else the built-in one."""
    from .relay import DEFAULT_RELAY_URL

    if args.no_relay or (settings is not None and not settings["relay"] and not args.relay):
        return None
    return args.relay or (settings["relay_url"] if settings is not None else "") or DEFAULT_RELAY_URL or None


# ---------------------------------------------------------------- terminal

def run_terminal(args):
    if not args.no_confirm and not sys.stdin.isatty():
        sys.exit("Pairing approval needs an interactive terminal. Run from a terminal, "
                 "pass --no-confirm, or use the desktop app (--app).")

    store = DeviceStore(config_dir() / "paired-phone.json")
    if args.forget:
        store.clear()
        print("Forgot the paired phone.")
    try:
        backend = create_backend(args.backend)
    except RuntimeError as exc:
        sys.exit(str(exc))

    approver = auto_approve if args.no_confirm else TerminalApprover()
    try:
        rt = Runtime(backend, store, approver, port=args.port, ip=args.ip,
                     https=bool(args.https or args.cert), cert=args.cert, key=args.key,
                     hostname=args.hostname, screen=not args.no_screen, relay_url=relay_url(args))
    except SetupError as exc:
        backend.close()
        sys.exit(str(exc))
    if rt.https_problem:
        print(f"Warning: {rt.https_problem} Using plain HTTP.")
    if rt.unknown_ip:
        print(f"Warning: {rt.ip} is not one of this laptop's addresses.")

    def show_pairing(with_qr=True):
        url = rt.relay_pairing_url if rt.relay_online else rt.pairing_url
        where = "any network with internet" if rt.relay_online else rt.network
        if with_qr:
            print(f"To pair a phone, scan this QR code with its camera ({where}), or open:\n")
            print(f"  {url}\n")
            print_qr(url, args.light_qr)
            if rt.relay_online:
                print(f"Without internet, on the same Wi-Fi: {rt.pairing_url}\n")
        else:
            print(f"    To pair a different phone later, open: {url}")

    def on_change(reason):
        if reason == "paired":
            print(f"    On this phone you can now simply open {rt.base_url}")
            show_pairing(with_qr=False)
        elif reason == "refused":
            print("    That QR code is no longer valid. New one:\n")
            show_pairing()

    rt.listeners.append(on_change)
    if rt.relay:   # give the relay a moment, so the QR code can work from any network
        rt.relay.start()
        import time
        for _ in range(40):
            if rt.relay.state != "connecting":
                break
            time.sleep(0.1)
        if not rt.relay_online:
            print(f"Internet relay unavailable ({rt.relay.error or 'not connected'}); local network only.")

    print(f"\nKumpas {__version__} is running.\n")
    if rt.pairing.device:
        home = rt.relay.phone_url if rt.relay_online else rt.base_url
        print(f"Paired phone: {rt.pairing.device.name}. On it, open {home}")
        print("(Pairing another phone replaces it.)\n")
    show_pairing()
    if rt.self_signed:
        print("HTTPS with a self-signed certificate: the phone warns that the connection isn't private")
        print("the first time. Tap Advanced, then Proceed. Certificate fingerprint (SHA-256):")
        print(f"  {rt.fingerprint}\n")
    others = [(a, k) for a, k in rt.addresses if a != rt.ip]
    if others and not args.hostname:
        listed = ", ".join(f"{a} ({k})" if k else a for a, k in others)
        print(f"If the phone can't open the link, try another address of this laptop: {listed}")
        print("  Restart with --ip <address> to put it in the QR code.\n")
    print(f"Input: {backend.name}")
    reason = rt.screen.unavailable_reason()
    print(f"Screen view: {'available' if not reason else reason}")
    if IS_MAC:
        print("macOS: allow this terminal under System Settings > Privacy & Security > Accessibility"
              " (and Screen Recording for screen view).")
    elif IS_WIN:
        print("Windows: if a firewall prompt appears, allow access on Private networks.")
    elif IS_WAYLAND and backend.name == "pyautogui":
        print("Warning: this is a Wayland session; pyautogui only works under X11. Try --backend uinput.")
    print("Press Ctrl+C to stop.\n")

    try:
        rt.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        rt.close()


# ---------------------------------------------------------------- desktop app

def run_app(args):
    from .hostui import Panel, PanelServer, existing_panel, remember_panel

    panel_file = config_dir() / "panel.json"
    url = existing_panel(panel_file)
    if url:   # already running: just show its panel again
        webbrowser.open(url)
        return

    settings = Settings(config_dir() / "settings.json")
    store = DeviceStore(config_dir() / "paired-phone.json")
    if args.forget:
        store.clear()

    rt, problem, backend = None, None, None
    panel = Panel(None, settings, __version__)
    try:
        backend = create_backend(args.backend)
        rt = Runtime(backend, store, panel.approve, port=args.port, ip=args.ip,
                     https=bool(args.https or args.cert or settings["https"]), cert=args.cert, key=args.key,
                     hostname=args.hostname, screen=settings["screen"] and not args.no_screen,
                     relay_url=relay_url(args, settings), log=panel.log)
    except (RuntimeError, SetupError) as exc:
        problem = f"Kumpas can't start yet.\n\n{exc}"
        if backend is not None:
            backend.close()
    panel.runtime, panel.problem = rt, problem
    from .relay import DEFAULT_RELAY_URL
    panel.relay_url = args.relay or settings["relay_url"] or None
    panel.default_relay = DEFAULT_RELAY_URL

    server = PanelServer(panel)
    remember_panel(panel_file, server)
    import threading
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if rt:
        rt.start()
        panel.log(f"Started. Phones can connect at {rt.base_url}")
    print(f"Kumpas {__version__}: control panel at {panel.url}")
    webbrowser.open(panel.url)
    try:
        panel.quit.wait()
    except KeyboardInterrupt:
        pass
    finally:
        if rt:
            rt.close()
        server.shutdown()
        server.server_close()
        try:
            panel_file.unlink()
        except OSError:
            pass


def app_main():
    """Entry point for the installed app.

    Started from a desktop icon (no terminal, no arguments) it runs as the app;
    started from a terminal it behaves like the `kumpas` command.
    """
    argv = [a for a in sys.argv[1:] if not a.startswith("-psn_")]  # old macOS Finder argument
    try:
        in_terminal = sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError, OSError):
        in_terminal = False
    if not argv and not in_terminal:
        argv = ["--app"]
    main(argv)


if __name__ == "__main__":
    main()
