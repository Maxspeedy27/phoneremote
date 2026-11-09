"""Build the installable app for the OS this runs on.

    python packaging/build.py            # from the repository root

Linux:   dist/kumpas_<version>_<arch>.deb
macOS:   dist/Kumpas-<version>-macos-<arch>.dmg
Windows: dist/Kumpas-<version>-windows-setup.exe  (needs Inno Setup 6)

Each OS must build its own package; PyInstaller can't cross-compile. The GitHub
Actions workflow in .github/workflows/build.yml runs this on all three.
Nothing here signs the packages; see README "Distributing" for what that means.
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"
DIST, BUILD = ROOT / "dist", ROOT / "build"
sys.path.insert(0, str(ROOT / "src"))
from kumpas import __version__ as VERSION  # noqa: E402


def run(*cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def pyinstaller():
    BUILD.mkdir(exist_ok=True)
    if sys.platform.startswith("win"):
        write_windows_version_file(BUILD / "win-version.txt")
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", DIST, "--workpath", BUILD / "pyinstaller", PACKAGING / "kumpas.spec")


# ---------------------------------------------------------------- Linux

def deb_arch():
    try:
        return subprocess.run(["dpkg", "--print-architecture"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine(), platform.machine())


def build_deb():
    arch = deb_arch()
    stage = BUILD / "deb"
    shutil.rmtree(stage, ignore_errors=True)
    app_dir = stage / "opt" / "kumpas"
    shutil.copytree(DIST / "kumpas", app_dir, symlinks=True)
    (stage / "usr" / "bin").mkdir(parents=True)
    os.symlink("/opt/kumpas/kumpas", stage / "usr" / "bin" / "kumpas")
    for src, dest in [
        (PACKAGING / "linux" / "kumpas.desktop", "usr/share/applications/kumpas.desktop"),
        (PACKAGING / "icons" / "kumpas.png", "usr/share/icons/hicolor/512x512/apps/kumpas.png"),
        (PACKAGING / "linux" / "60-kumpas-uinput.rules", "usr/lib/udev/rules.d/60-kumpas-uinput.rules"),
    ]:
        target = stage / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, target)
        target.chmod(0o644)

    debian = stage / "DEBIAN"
    debian.mkdir()
    size_kb = sum(f.stat().st_size for f in stage.rglob("*") if f.is_file() and not f.is_symlink()) // 1024
    (debian / "control").write_text(f"""\
Package: kumpas
Version: {VERSION}
Architecture: {arch}
Maintainer: Kumpas <noreply@kumpas.invalid>
Installed-Size: {size_kb}
Depends: libc6, libx11-6, libxtst6, libxrandr2
Recommends: wl-clipboard, xclip
Section: utils
Priority: optional
Homepage: https://github.com/Maxspeedy27/phoneremote
Description: Control your laptop from your phone's browser
 Slides, touchpad, keyboard, media keys, a talk timer and a live view of the
 screen, from any phone browser: nothing to install on the phone. Pairing is
 approved on the laptop and every command is encrypted.
""", encoding="utf-8")
    for script in ("postinst", "postrm"):
        shutil.copy(PACKAGING / "linux" / script, debian / script)
        (debian / script).chmod(0o755)
    # Packages must be owned by root and not group-writable.
    for path in [stage, *stage.rglob("*")]:
        if not path.is_symlink():
            mode = path.stat().st_mode & 0o7777
            path.chmod(mode & ~0o022)
    out = DIST / f"kumpas_{VERSION}_{arch}.deb"
    run("dpkg-deb", "--root-owner-group", "--build", stage, out)
    return out


# ---------------------------------------------------------------- macOS

def build_dmg():
    app = DIST / "Kumpas.app"
    # Ad-hoc signature: required to run on Apple Silicon. A Developer ID
    # signature plus notarization (paid Apple account) removes the Gatekeeper
    # warning; set MACOS_SIGN_IDENTITY to use one.
    identity = os.environ.get("MACOS_SIGN_IDENTITY", "-")
    run("codesign", "--force", "--deep", "--options", "runtime", "--sign", identity, app)
    stage = BUILD / "dmg"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    shutil.copytree(app, stage / app.name, symlinks=True)
    os.symlink("/Applications", stage / "Applications")
    out = DIST / f"Kumpas-{VERSION}-macos-{platform.machine()}.dmg"
    out.unlink(missing_ok=True)
    run("hdiutil", "create", "-volname", "Kumpas", "-srcfolder", stage, "-ov", "-format", "UDZO", out)
    return out


# ---------------------------------------------------------------- Windows

def write_windows_version_file(path):
    nums = [int(p) for p in VERSION.split(".")[:3]] + [0]
    path.write_text(f"""\
VSVersionInfo(
  ffi=FixedFileInfo(filevers={tuple(nums)}, prodvers={tuple(nums)}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('FileDescription', 'Kumpas'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('ProductName', 'Kumpas'),
      StringStruct('ProductVersion', '{VERSION}'),
      StringStruct('OriginalFilename', 'Kumpas.exe')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""", encoding="utf-8")


def find_iscc():
    found = shutil.which("iscc") or shutil.which("ISCC")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base and (Path(base) / "Inno Setup 6" / "ISCC.exe").exists():
            return str(Path(base) / "Inno Setup 6" / "ISCC.exe")
    return None


def build_windows_installer():
    iscc = find_iscc()
    if not iscc:
        sys.exit("Inno Setup 6 not found (https://jrsoftware.org/isinfo.php). "
                 "The app itself is in dist/Kumpas.")
    run(iscc, f"/DAppVersion={VERSION}", f"/DSourceDir={DIST / 'Kumpas'}",
        PACKAGING / "windows" / "kumpas.iss")
    return DIST / f"Kumpas-{VERSION}-windows-setup.exe"


def main():
    pyinstaller()
    if sys.platform.startswith("linux"):
        out = build_deb()
    elif sys.platform == "darwin":
        out = build_dmg()
    elif sys.platform.startswith("win"):
        out = build_windows_installer()
    else:
        sys.exit(f"no package format for {sys.platform}")
    print(f"\nBuilt {out}")


if __name__ == "__main__":
    main()
