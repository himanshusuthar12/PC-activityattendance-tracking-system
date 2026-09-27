"""
Build script - PyInstaller one-file / one-dir exe generation.

Usage:
  pip install pyinstaller
  python build.py              # one-dir build (recommended, faster start)
  python build.py --onefile    # single exe (slower cold start)
  python build.py --no-window  # console build (for debugging)

Outputs:
  dist/TimesheetAgent/          (one-dir)  OR  dist/TimesheetAgent.exe (onefile)
  dist/TimesheetAgentTray.exe   (optional tray)
  dist/Onboarding.exe           (optional standalone onboarding)

Then use installer/installer.iss with Inno Setup to create Setup.exe
"""
import argparse
import shutil
import subprocess
import sys
import os
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"

COMMON_HIDDEN = [
    "pymysql", "requests", "dotenv", "psutil", "win32api", "win32con",
    "win32gui", "win32event", "win32service", "win32serviceutil", "win32crypt",
    "win32com.client"
]

def run(cmd, **kw):
    print(">", " ".join(cmd))
    subprocess.check_call(cmd, **kw)

def build_agent(onefile=False, windowed=True):
    name = "TimesheetAgent"
    args = [
        sys.executable, "-m", "PyInstaller",
        "--name", name,
        "--clean", "--noconfirm",
        "--onedir" if not onefile else "--onefile",
        "--windowed" if windowed else "--console",
        "--icon", "NONE",
        "--add-data", f"static{os.pathsep}static",
        "--hidden-import", "win32timezone",
    ]
    for h in COMMON_HIDDEN:
        args += ["--hidden-import", h]
    # main entry
    args.append(str(ROOT / "main.py"))
    run(args)
    print(f"Built {name} -> {DIST}")

def build_onboarding():
    args = [
        sys.executable, "-m", "PyInstaller",
        "--name", "Onboarding",
        "--clean", "--noconfirm",
        "--onefile", "--windowed",
        "--hidden-import", "win32crypt",
        str(ROOT / "onboarding.py"),
    ]
    run(args)

def build_tray():
    args = [
        sys.executable, "-m", "PyInstaller",
        "--name", "TimesheetAgentTray",
        "--clean", "--noconfirm",
        "--onefile", "--windowed",
        "--hidden-import", "pystray",
        "--hidden-import", "PIL",
        "--hidden-import", "win32crypt",
        str(ROOT / "tray_app.py"),
    ]
    run(args)

def main():
    parser = argparse.ArgumentParser(description="Build TimesheetAgent exe")
    parser.add_argument("--onefile", action="store_true", help="single file exe")
    parser.add_argument("--no-window", action="store_true", help="console mode (debug)")
    parser.add_argument("--with-tray", action="store_true", help="also build tray")
    parser.add_argument("--with-onboarding", action="store_true", help="also build onboarding")
    args = parser.parse_args()

    if DIST.exists():
        print(f"Cleaning {DIST} (keep manually if needed)")
    build_agent(onefile=args.onefile, windowed=not args.no_window)
    if args.with_onboarding:
        build_onboarding()
    if args.with_tray:
        build_tray()
    print("\nBuild done.")
    print("Next: compile installer/installer.iss with Inno Setup (https://jrsoftware.org/isinfo.php)")
    print("  iscc installer\\installer.iss")
    if not args.onefile:
        print(f"  Source: {DIST / 'TimesheetAgent' / 'TimesheetAgent.exe'}")

if __name__ == "__main__":
    main()
