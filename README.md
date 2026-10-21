# Phone Remote

Use your phone's browser as a remote control for your laptop: next/back for
slides, a touchpad, scrolling, zoom and typing. Nothing to install on the
phone. The laptop runs a small local server; the phone scans a QR code.

- **Slides:** big Next/Back buttons and swipes, Start, Exit, Blank, First/Last, talk timer.
- **Touchpad:** move, tap to click, two-finger tap to right-click, two-finger
  scroll, hold to drag, browser back, page up/down, fullscreen, zoom, typing.
  Double-tapping the pad double-clicks and opens the phone's keyboard, ready
  to type into the text box you clicked. The keyboard's Enter/Go key types the
  text and presses Enter (one step for search boxes); the Send button types
  without Enter.

Works on Windows, macOS and Linux (X11 and Wayland).

## Install (development)

Python 3.9+.

```bash
python -m venv .venv
.venv/bin/pip install -e .          # Windows: .venv\Scripts\pip install -e .
```

## Run

```bash
.venv/bin/phoneremote               # or: python -m phoneremote
```

Options: `--port 8765`, `--backend auto|pyautogui|uinput`, `--ip ADDRESS`
(the laptop address to put in the QR code), `--light-qr`,
`--forget` (unpair the remembered phone), `--no-confirm` (skip the approval
prompt; less secure).

## Pairing

1. Start Phone Remote and scan the QR code with the phone's camera. The phone
   must be on the same Wi-Fi as the laptop, or connected to it by Bluetooth
   tethering (see below).
2. The phone shows a 6-digit code, and the laptop asks whether to allow it.
   Check that the codes match, then type `y`.
3. The phone is now paired and remembered. Next time, simply reopen the page
   (bookmark it, or add it to the home screen). Pairing another phone
   replaces the first one.

## No shared Wi-Fi? Use Bluetooth tethering

Phone Remote also works where there's no Wi-Fi, or where the Wi-Fi blocks
devices from seeing each other (common in hotels and conference venues). Let
the laptop join the phone's network over Bluetooth:

1. Pair the phone and laptop in the laptop's Bluetooth settings, if you haven't before.
2. On the phone, turn on Bluetooth tethering: on Android, Settings → Network
   & internet → Hotspot & tethering → Bluetooth tethering; on iPhone, Settings
   → Personal Hotspot → Allow Others to Join.
3. Connect the laptop to it. On Linux, open Bluetooth settings, choose the
   phone and turn on its network (access point) option. On macOS, choose the
   phone in the Bluetooth menu and connect to its network. On Windows, open
   Bluetooth devices → Join a Personal Area Network, then the phone →
   Connect using → Access point.
4. Start Phone Remote and scan the QR code as usual.

On Linux, Phone Remote recognises the Bluetooth connection and puts its address
in the QR code ("connected over Bluetooth tethering"). On macOS and Windows, or
if the phone can't open the link, use one of the other addresses listed under
the QR code: `phoneremote --ip 192.168.44.7`.

Things to know:

- The phone saves its pairing per address, so a phone paired over Wi-Fi needs
  to pair once more when it opens the Bluetooth address (and the other way round).
- The laptop may send its internet traffic through the phone while tethered,
  which uses mobile data. Some carriers block tethering on certain plans.
- The touchpad may feel slightly less responsive than over Wi-Fi.

## Security model

Designed so that other people on the same Wi-Fi, or someone who photographs
the QR code on a projected screen, can't control the laptop or read typed text.

- The QR code's pairing key sits in the URL fragment (`#k=...`), which
  browsers never send over the network. It is single-use: it is replaced after
  every pairing attempt, accepted or not.
- Pairing must be approved on the laptop, with a matching code on both screens.
- Every command is encrypted and authenticated (NaCl secretbox:
  XSalsa20-Poly1305; tweetnacl on the phone, PyNaCl on the laptop). Sessions
  are chosen by the laptop and requests are numbered, so recorded traffic can't
  be replayed.
- The phone may only trigger a fixed list of named actions, not arbitrary keys.
- The paired phone's key is stored owner-only in the user config folder
  (`~/.config/phoneremote/` on Linux, `~/Library/Application Support/PhoneRemote/`
  on macOS, `%APPDATA%\PhoneRemote\` on Windows).

**Known limitation:** the page is served over plain HTTP, so an attacker who can
actively tamper with LAN traffic (ARP spoofing) could serve modified JavaScript
to the phone. Fixing that needs HTTPS, planned together with the relay.

## Platform notes

**Windows:** on first run, allow Python through the firewall on *Private*
networks, and make sure your Wi-Fi's profile is *Private*. To add the rule
manually (Administrator terminal):

    netsh advfirewall firewall add rule name="Phone Remote" dir=in action=allow protocol=TCP localport=8765 profile=private

**macOS:** allow the app you run it from (Terminal, iTerm, …) under System
Settings → Privacy & Security → Accessibility, then restart Phone Remote.
"Start" sends Cmd+Shift+Return (PowerPoint for Mac); for Keynote change
`start` in `src/phoneremote/shortcuts.py` to `("option", "command", "p")`.

**Linux, X11:** uses pyautogui. Non-ASCII typing needs `xclip`.

**Linux, Wayland:** Wayland ignores pyautogui, so Phone Remote creates a virtual
keyboard and mouse through `/dev/uinput`. Allow the logged-in user to do that
once:

    echo 'KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess", OPTIONS+="static_node=uinput"' | sudo tee /etc/udev/rules.d/60-phone-remote-uinput.rules
    sudo udevadm control --reload-rules
    sudo udevadm trigger --name-match=uinput

Typing assumes a US keyboard layout; non-ASCII text needs `wl-clipboard`.

## Development

```bash
cd tests && ../.venv/bin/python -m unittest -v
```

The crypto tests also check the phone's `crypto.js` against the Python side
when Node.js is installed.

Layout:

    src/phoneremote/
      cli.py          command line, startup output
      server.py       HTTP server and routes
      pairing.py      pairing, device storage, sessions, replay protection
      crypto.py       secretbox helpers shared with web/crypto.js
      commands.py     validating and applying phone operations
      shortcuts.py    named actions -> per-OS key combinations
      backends/       pyautogui and uinput input backends
      web/            phone page (HTML, CSS, JS) and vendored tweetnacl
    tests/

Third-party code: `web/vendor/nacl-fast.min.js` is tweetnacl-js 1.0.3
(public domain, see `LICENSE-tweetnacl.txt`).
