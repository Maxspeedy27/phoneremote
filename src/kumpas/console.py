"""Terminal user interface: QR codes and pairing approval prompts."""

import queue
import sys
import threading


def print_qr(url, light_terminal=False):
    try:
        import qrcode
    except ImportError:
        print("  (pip install qrcode to get a scannable QR code here)\n")
        return
    qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_L)
    qr.add_data(url)
    qr.make(fit=True)
    try:
        qr.print_ascii(invert=not light_terminal)
    except (UnicodeEncodeError, OSError):
        print("  (this terminal can't display the QR code; type the URL instead)")
    print()


def format_code(code):
    return f"{code[:3]} {code[3:]}"


class TerminalApprover:
    """Asks on the terminal whether a phone may pair."""

    def __init__(self):
        self._lines = queue.Queue()
        threading.Thread(target=self._read_stdin, daemon=True).start()

    def _read_stdin(self):
        for line in sys.stdin:
            self._lines.put(line.strip().lower())

    def __call__(self, name, code, timeout):
        while not self._lines.empty():  # ignore anything typed before the prompt
            self._lines.get_nowait()
        print(f"\n>>> {name} wants to control this laptop.")
        print(f"    Allow only if the phone shows the code {format_code(code)}.")
        print(f"    Allow? Type y and press Enter (or n to refuse; {timeout} s): ", end="", flush=True)
        try:
            answer = self._lines.get(timeout=timeout)
        except queue.Empty:
            print("\n    No answer - pairing cancelled.")
            return False
        approved = answer in ("y", "yes")
        print(f"    {'Paired.' if approved else 'Refused.'}")
        return approved


def auto_approve(name, code, timeout):
    print(f"\n>>> Paired with {name} (code {format_code(code)}) without asking (--no-confirm).")
    return True
