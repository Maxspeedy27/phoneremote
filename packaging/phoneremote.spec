# PyInstaller spec for Phone Remote. Build with:  python packaging/build.py
# (or: pyinstaller --noconfirm --distpath dist --workpath build packaging/phoneremote.spec)
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
WEB = ROOT / "src" / "phoneremote" / "web"
ICONS = ROOT / "packaging" / "icons"
sys.path.insert(0, str(ROOT / "src"))
from phoneremote import __version__  # noqa: E402

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform.startswith("win")

hidden = ["phoneremote.backends.pyautogui_backend", "phoneremote.relay", "websockets.sync.client",
          *collect_submodules("mss")]
if IS_WIN:
    hidden += ["pyautogui._pyautogui_win"]
elif IS_MAC:
    hidden += ["pyautogui._pyautogui_osx", "Quartz", "AppKit"]
else:
    hidden += ["pyautogui._pyautogui_x11", "phoneremote.backends.uinput", "Xlib.ext.xtest"]

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "src")],
    datas=[(str(WEB), "phoneremote/web")],
    hiddenimports=hidden,
    # tkinter is only used by pyautogui's optional message boxes and mouse-info
    # helper, which Phone Remote never calls.
    excludes=["tkinter", "mouseinfo", "pymsgbox", "unittest", "pydoc"],
    noarchive=False,
)
pyz = PYZ(a.pure)

name = "PhoneRemote" if (IS_WIN or IS_MAC) else "phoneremote"
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=name,
    console=not (IS_WIN or IS_MAC),   # Linux keeps a console so `phoneremote` works in a terminal
    icon=str(ICONS / ("phoneremote.ico" if IS_WIN else "phoneremote.icns")) if (IS_WIN or IS_MAC) else None,
    version=str(ROOT / "build" / "win-version.txt") if IS_WIN else None,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name=name, upx=False)

if IS_MAC:
    app = BUNDLE(
        coll,
        name="Phone Remote.app",
        icon=str(ICONS / "phoneremote.icns"),
        bundle_identifier="app.phoneremote.desktop",
        version=__version__,
        info_plist={
            "CFBundleName": "Phone Remote",
            "CFBundleDisplayName": "Phone Remote",
            "CFBundleShortVersionString": __version__,
            "NSHighResolutionCapable": True,
            # No windows of its own (the control panel opens in the browser),
            # so stay out of the Dock; open the app again to show the panel.
            "LSUIElement": True,
            "NSHumanReadableCopyright": "Phone Remote",
        },
    )
