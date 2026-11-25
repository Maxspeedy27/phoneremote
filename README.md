# Kumpas

*Kumpas* (Filipino): the hand gesture a conductor uses to lead the music.
(Formerly called Phone Remote.)

**[Website](https://maxspeedy27.github.io/phoneremote/)** · **[Download](https://github.com/Maxspeedy27/phoneremote/releases/latest)** (Windows, macOS, Linux) · [Privacy policy](https://maxspeedy27.github.io/phoneremote/privacy.html) · [Code signing policy](https://maxspeedy27.github.io/phoneremote/code-signing.html)

Use your phone's browser as a remote control for your laptop: next/back for
slides, a touchpad, scrolling, zoom and typing. Nothing to install on the
phone. The laptop runs a small local server; the phone scans a QR code.

Works with any presentation app (PowerPoint, Keynote, LibreOffice Impress,
Google Slides, PDF viewers), because it presses keys on the laptop rather
than plugging into one app. No account, no cloud: it works offline over Wi-Fi
or Bluetooth tethering.

- **Slides:** big Next/Back buttons and swipes, Start, Exit, black or white
  screen, First/Last, and go to a slide by number (PowerPoint, Keynote,
  Impress, Google Slides). A pointer strip moves the laptop's cursor so you can
  point at the projected slide without changing slides.
- **Private black/white screen:** on Linux (X11), Black and White blank the
  projector (or the laptop screen, when no projector is connected) without
  blanking the phone's screen view, so you can move to another slide or topic
  unseen and then reveal it. Tap the button again to show the screen. Elsewhere
  they press B/W in the slideshow app as before.
- **Talk timer:** counts up, or set a talk length and it counts down. The
  phone vibrates silently at 5 minutes left, 1 minute left and time up (on
  phones that support vibration, i.e. not iPhones), the clock turns amber then
  red, and overtime shows as `+MM:SS`. Survives page reloads.
- **Media:** play/pause, previous/next track, volume and mute for whatever is
  playing on the laptop, plus rewind/forward/space for video players.
- **Screen view:** a live, encrypted picture of the laptop screen at the top
  of the phone, with the laptop's mouse pointer drawn on it, so you can see the
  projected slide while facing the audience, or use the touchpad without
  looking up. Tap it to enlarge; switch monitors. Only sent while the phone is
  looking at it, and the laptop shows when it is. (Windows, macOS, Linux on
  X11; not yet on Wayland.)
- **Touchscreen:** the screen view's **Touch** button goes fullscreen (turn
  the phone sideways) and the picture becomes a touchscreen for the laptop:
  tap to click there, tap twice to double-click, hold to right-click, drag to
  drag, two fingers to scroll, pinch to zoom in on small targets. A keyboard
  button types into whatever you clicked. (Needs the pyautogui input method,
  the default everywhere except Wayland.)
- **Tilt to point:** over HTTPS, hold the pointer strip and move the phone like
  a laser pointer; let go and the cursor stays put.
- **Touchpad:** move, tap to click, two-finger tap to right-click, two-finger
  scroll, hold to drag, browser back, page up/down, fullscreen, zoom, typing.
  Double-tapping the pad double-clicks and opens the phone's keyboard, ready
  to type into the text box you clicked. The keyboard's Enter/Go key types the
  text and presses Enter (one step for search boxes); the Send button types
  without Enter.

Works on Windows, macOS and Linux (X11 and Wayland).

## Install

Download the installer for your laptop from the Releases page:

- **Windows:** `Kumpas-<version>-windows-setup.exe`. It also lets phones
  through the firewall on private networks, so there's no firewall prompt.
- **macOS:** `Kumpas-<version>-macos-arm64.dmg`; drag Kumpas to
  Applications. Until the app is signed, open it the first time with
  right-click → Open.
- **Linux (Debian, Ubuntu, Mint):** `sudo apt install ./kumpas_<version>_amd64.deb`.
  It also installs the permission rule that Wayland desktops need, so there
  are no setup commands.

Then start **Kumpas** from the Start menu, Launchpad or app menu. It
opens a control panel in your browser with the QR code, pairing requests
(Allow/Refuse), the paired phone, and switches for screen view and HTTPS.
Opening the app again while it runs just shows the panel; Quit is at the bottom.

## Run from source

Python 3.9+.

```bash
python -m venv .venv
.venv/bin/pip install -e .          # Windows: .venv\Scripts\pip install -e .
.venv/bin/kumpas               # terminal version (or: python -m kumpas)
.venv/bin/kumpas --app         # desktop app with the browser control panel
```

Options: `--port 8765`, `--backend auto|pyautogui|uinput`, `--ip ADDRESS`
(the laptop address to put in the QR code), `--https` (see below),
`--cert FILE --key FILE` and `--hostname NAME` (use your own certificate),
`--no-screen` (no screen view), `--light-qr`, `--forget` (unpair the
remembered phone), `--no-confirm` (skip the approval prompt; less secure).

## Pairing

1. Start Kumpas and scan the QR code with the phone's camera (see
   *Connecting* below for which code).
2. The phone shows a 6-digit code, and the laptop asks whether to allow it.
   Check that the codes match, then click Allow in the control panel (or type
   `y` in the terminal version).
3. The phone is now paired and remembered. Next time, simply reopen the page
   (bookmark it, or add it to the home screen). Pairing another phone
   replaces the first one.

## Connecting

- **Any network (internet relay):** with a relay set up (see
  [relay/README.md](relay/README.md)), the control panel's **Any network**
  code works wherever both devices have internet: the phone on mobile data,
  a different Wi-Fi, or venue Wi-Fi that keeps devices apart. The page comes
  from the relay over real HTTPS, and everything stays end-to-end encrypted.
  If the laptop goes offline, the phone says so and reconnects by itself.
  It is off until you turn on **Connect over the internet** in the panel's
  settings (or pass `--relay` in the terminal); until then nothing leaves the
  local network.
- **Same Wi-Fi:** the **Same Wi-Fi / no internet** code connects directly,
  with no internet needed.
- **No internet at all:** link the phone and laptop directly, then use the
  **Same Wi-Fi / no internet** code. Kumpas recognises these links and
  puts the right address in the code:
  - *Phone hotspot* (easiest): turn on the phone's hotspot and join it from
    the laptop. (An iPhone's hotspot needs a mobile plan that allows it.)
  - *USB cable*: plug the phone in, then Android: Settings → Hotspot &
    tethering → USB tethering; iPhone: Settings → Personal Hotspot → Allow
    Others to Join (Windows also needs Apple's Apple Devices app). USB links
    are recognised by interface on Linux and by the iPhone's hotspot
    addresses everywhere; elsewhere pick the address in the panel.
  - *Bluetooth tethering*: see below.

The phone keeps a separate pairing for the relay page and the local page, as
browsers treat them as different sites; pairing one replaces the other on
the laptop (one paired phone at a time).

### Bluetooth tethering

Kumpas also works where there's no Wi-Fi, or where the Wi-Fi blocks
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
4. Start Kumpas and scan the QR code as usual.

On Linux, Kumpas recognises the Bluetooth connection and puts its address
in the QR code ("connected over Bluetooth tethering"). On macOS and Windows, or
if the phone can't open the link, use one of the other addresses listed under
the QR code: `kumpas --ip 192.168.44.7`.

Things to know:

- The phone saves its pairing per address, so a phone paired over Wi-Fi needs
  to pair once more when it opens the Bluetooth address (and the other way round).
- The laptop may send its internet traffic through the phone while tethered,
  which uses mobile data. Some carriers block tethering on certain plans.
- The touchpad may feel slightly less responsive than over Wi-Fi.

## Security model

The internet relay passes along encrypted messages it can't read: the pairing
key in the QR code's `#fragment` never reaches it, and a laptop must prove it
owns its room with a secret kept in the config folder (`relay.json`).


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
- Screen view pictures are encrypted the same way, taken only while the paired
  phone is looking, can be switched off in the panel (or `--no-screen`), and
  the panel shows "The phone is viewing your screen" while it happens.
- The control panel only listens on 127.0.0.1, checks the Host header (against
  DNS rebinding) and needs a secret token per launch, so neither other devices
  nor other websites open in the same browser can approve a pairing.
- The paired phone's key is stored owner-only in the user config folder
  (`~/.config/kumpas/` on Linux, `~/Library/Application Support/Kumpas/`
  on macOS, `%APPDATA%\Kumpas\` on Windows).

## HTTPS

By default the phone page is plain HTTP, which works with no warnings. Because
of that, an attacker who can actively tamper with LAN traffic (ARP spoofing)
could serve modified JavaScript to the phone, and browsers hide some features
from HTTP pages. Turning on **Secure connection (HTTPS)** in the panel (or
`--https`) serves the page over HTTPS with a self-signed certificate made for
this laptop, which unlocks:

- keeping the phone's screen on while the talk timer runs (Wake Lock);
- tilt-to-point (motion sensors);
- installing the page as an app.

The phone shows a "connection not private" warning the first time (tap
Advanced, then Proceed) and pairs once more, because `https://` is a different
site to the browser. The panel shows the certificate's SHA-256 fingerprint to
compare with the browser's certificate viewer. Plain `http://` links to the
same port are redirected to `https://`. A self-signed certificate can't stop
an attacker who is already intercepting before that first visit; a certificate
the phone trusts can: `--cert FILE --key FILE --hostname NAME` uses your own,
for example for a domain name that points at the laptop's address.

## Platform notes

**Windows:** on first run, allow Python through the firewall on *Private*
networks, and make sure your Wi-Fi's profile is *Private*. To add the rule
manually (Administrator terminal):

    netsh advfirewall firewall add rule name="Kumpas" dir=in action=allow protocol=TCP localport=8765 profile=private

**macOS:** allow the app you run it from (Terminal, iTerm, …) under System
Settings → Privacy & Security → Accessibility, then restart Kumpas.
"Start" sends Cmd+Shift+Return (PowerPoint for Mac); for Keynote change
`start` in `src/kumpas/shortcuts.py` to `("option", "command", "p")`.

**macOS screen view:** allow Kumpas under System Settings → Privacy &
Security → Screen Recording (macOS asks the first time the phone opens the
screen view), then restart it.

**Linux, X11:** uses pyautogui. Non-ASCII typing needs `xclip`.

**Linux, Wayland:** Wayland ignores pyautogui, so Kumpas creates a virtual
keyboard and mouse through `/dev/uinput`. Allow the logged-in user to do that
once:

    echo 'KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess", OPTIONS+="static_node=uinput"' | sudo tee /etc/udev/rules.d/60-kumpas-uinput.rules
    sudo udevadm control --reload-rules
    sudo udevadm trigger --name-match=uinput

Typing assumes a US keyboard layout; non-ASCII text needs `wl-clipboard`.
Screen view isn't available on Wayland yet: Wayland only offers screen capture
through a portal that is far too slow for a live view (it would need the
PipeWire screencast portal). Log in to an X11 session to use it.

## Development

```bash
cd tests && ../.venv/bin/python -m unittest -v
```

The crypto tests also check the phone's `crypto.js` against the Python side
when Node.js is installed.

Layout:

    src/kumpas/
      cli.py          entry points: terminal version and desktop app (--app)
      runtime.py      the running remote: server, pairing, address, HTTPS switch
      hostui.py       desktop app control panel (served on 127.0.0.1)
      server.py       phone HTTP(S) server and routes
      screen.py       screen view snapshots (mss + Pillow)
      tls.py          self-signed or user-supplied HTTPS certificates
      relay.py        keeping the laptop connected to the internet relay
      pairing.py      pairing, device storage, sessions, replay protection
      crypto.py       secretbox helpers shared with web/crypto.js
      commands.py     validating and applying phone operations
      shortcuts.py    named actions -> per-OS key combinations
      backends/       pyautogui and uinput input backends
      web/            phone page (HTML, CSS, JS), icons, vendored tweetnacl
      web/panel/      control panel page
    relay/            internet relay: Cloudflare Worker + Durable Object (see relay/README.md)
    packaging/        PyInstaller spec, build script, Linux/Windows installer files, icons
    tests/

## Building the installers

```bash
.venv/bin/pip install pyinstaller
.venv/bin/python packaging/build.py     # builds for the OS it runs on, into dist/
```

Linux builds a `.deb`, macOS a `.dmg`, Windows an installer `.exe` (needs
[Inno Setup 6](https://jrsoftware.org/isinfo.php)). PyInstaller can't
cross-compile, so `.github/workflows/build.yml` builds all three on GitHub's
machines on every push, and publishes them as a release when you push a tag
like `v0.3.0`. Build the Linux package on the oldest distro you support
(the workflow uses Ubuntu 22.04): it runs on that glibc or newer.
`packaging/make_icons.py` redraws the icons.

**Signing (before a public launch):** the packages are unsigned.

- **Windows:** SmartScreen warns about unsigned downloads ("Windows protected
  your PC" → More info → Run anyway) until the app has a code-signing
  certificate and some download reputation.
- **macOS:** Gatekeeper blocks unsigned apps on double-click (right-click → Open
  works). Signing with a Developer ID and notarizing (Apple Developer Program,
  US$99/year) removes that; `build.py` signs with `MACOS_SIGN_IDENTITY` when
  set. Signing also keeps macOS's Accessibility and Screen Recording
  permissions across updates.
- **Linux:** `.deb` files are installed directly; signing matters once you run
  an apt repository.

Third-party code: `web/vendor/nacl-fast.min.js` is tweetnacl-js 1.0.3
(public domain, see `LICENSE-tweetnacl.txt`).

## Privacy

Kumpas has no accounts, analytics, telemetry or update checks. This program
will not transfer any information to other networked systems unless
specifically requested by the user or the person installing or operating it.

- **Local connections** (same Wi-Fi, hotspot, USB, Bluetooth) go straight
  from the phone to the laptop and never touch the internet.
- **The internet relay** is used only after you turn it on. It passes along
  end-to-end encrypted messages it can't read and stores nothing, but like
  any server it sees the laptop's and the phone's IP addresses, when they
  connect and how much they send. The relay runs on Cloudflare, which keeps
  its own request logs under [Cloudflare's privacy
  policy](https://www.cloudflare.com/privacypolicy/). A relay you deploy
  yourself (`--relay URL`) is under your control instead.
- **Screen pictures** are taken only while the paired phone has the screen
  view open, and go only to that phone, encrypted.

The same policy is on the website (`website/privacy.html`).

## Code signing policy

Installers are built only by GitHub Actions from this repository's source, for
a tagged release; nothing built on a personal computer is published. They are
not code-signed yet: Windows and macOS warn on first launch (see
[Building the installers](#building-the-installers)). The full policy, the
team and what each installer changes on the system are on the
[code signing policy page](https://maxspeedy27.github.io/phoneremote/code-signing.html).

## License

Copyright © 2026 Macley Domingo.

Kumpas is free software: you can redistribute it and/or modify it under the
terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version. It is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; see [`LICENSE`](LICENSE) for the full terms.

The license covers the code. The name "Kumpas" and the K logo are not
licensed for use by modified versions: a fork that you distribute needs its
own name and icon.
