"""
Windows startup helper - supports Startup shortcut, Registry Run, and Task Scheduler.

Usage:
    python startup.py install          # auto-detect best method (shortcut + registry)
    python startup.py install --task   # also create Scheduled Task (logon trigger, hidden)
    python startup.py install --exe "C:\\Program Files\\TimesheetManager\\TimesheetAgent.exe"
    python startup.py uninstall
    python startup.py status

When app is installed via Inno Setup (exe), prefer --exe path so startup
survives venv deletion. When running from source, defaults to pythonw + main.py --hidden.
"""
import argparse
import os
import sys
import subprocess
from pathlib import Path

try:
    from win32com.client import Dispatch
    HAS_PYWIN32 = True
except ImportError:
    Dispatch = None
    HAS_PYWIN32 = False

APP_NAME = "TimesheetManager Agent"
TASK_NAME = "TimesheetManagerAgent"

def startup_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA not set - not a Windows user profile?")
    return Path(appdata) / "Microsoft/Windows/Start Menu/Programs/Startup"

def shortcut_path() -> Path:
    return startup_dir() / f"{APP_NAME}.lnk"

def _resolve_target(exe_override: str = None):
    """Return (target, args, workdir)."""
    if exe_override:
        p = Path(exe_override)
        return str(p), "--hidden", str(p.parent)
    # default: source mode -> pythonw + main.py --hidden
    main_py = Path(__file__).resolve().parent / "main.py"
    python_exe = sys.executable
    # prefer pythonw
    try:
        pythonw = Path(python_exe).with_name("pythonw.exe")
        if pythonw.exists():
            python_exe = str(pythonw)
    except Exception:
        pass
    return python_exe, f'"{main_py}" --hidden', str(main_py.parent)

def install_shortcut(exe_override=None) -> bool:
    if not HAS_PYWIN32:
        return False
    try:
        startup_dir().mkdir(parents=True, exist_ok=True)
        shell = Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(str(shortcut_path()))
        target, args, wdir = _resolve_target(exe_override)
        shortcut.Targetpath = target
        shortcut.Arguments = args
        shortcut.WorkingDirectory = wdir
        shortcut.Description = APP_NAME
        shortcut.IconLocation = target
        shortcut.Save()
        print(f"Installed (shortcut): {shortcut_path()}")
        print(f"  Target: {target} {args}")
        return True
    except Exception as e:
        print(f"Shortcut install failed: {e}")
        return False

def install_registry(exe_override=None) -> bool:
    try:
        import winreg
        target, args, _ = _resolve_target(exe_override)
        # quote properly
        cmd = f'"{target}" {args}'
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
        winreg.CloseKey(key)
        print(f"Installed (registry): HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\\{APP_NAME}")
        print(f"  Command: {cmd}")
        return True
    except Exception as e:
        print(f"Registry install failed: {e}")
        return False

def install_task(exe_override=None) -> bool:
    """Create Scheduled Task: logon trigger, hidden, run even if on battery."""
    try:
        target, args, _ = _resolve_target(exe_override)
        # schtasks expects TR quoted
        tr = f"'{target}' {args}" if " " in target else f"{target} {args}"
        # use schtasks /Create /SC ONLOGON /TN ... /TR ... /RL HIGHEST may need admin, so try LIMITED first
        cmd = [
            "schtasks", "/Create", "/SC", "ONLOGON", "/TN", TASK_NAME,
            "/TR", f'"{target}" {args}',
            "/F"
        ]
        print("Creating scheduled task:", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True)
        print(result.stdout)
        if result.stderr:
            print(result.stderr)
        if result.returncode == 0:
            print(f"Installed (task): {TASK_NAME} (ONLOGON)")
            return True
        # fallback with /RL LIMITED hint
        cmd2 = ["schtasks", "/Create", "/SC", "ONLOGON", "/TN", TASK_NAME, "/TR", f'"{target}" {args}', "/RL", "LIMITED", "/F"]
        result2 = subprocess.run(cmd2, capture_output=True, text=True)
        print(result2.stdout)
        if result2.stderr:
            print(result2.stderr)
        return result2.returncode == 0
    except Exception as e:
        print(f"Task install failed: {e}")
        return False

def uninstall():
    removed = False
    path = shortcut_path()
    if path.exists():
        try:
            path.unlink()
            print(f"Removed: {path}")
            removed = True
        except Exception as e:
            print(f"Failed to remove shortcut: {e}")
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
        try:
            winreg.DeleteValue(key, APP_NAME)
            print(f"Removed registry: {APP_NAME}")
            removed = True
        except FileNotFoundError:
            pass
        winreg.CloseKey(key)
    except Exception:
        pass
    # task
    try:
        result = subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"Removed task: {TASK_NAME}")
            removed = True
        else:
            # not exists is fine
            if "cannot find" not in result.stdout.lower() and "cannot find" not in result.stderr.lower():
                if result.stdout.strip():
                    print(result.stdout.strip())
    except Exception:
        pass
    if not removed:
        print("Startup entry not installed.")

def status():
    sc = shortcut_path().exists()
    reg_exists = False
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
        try:
            v, _ = winreg.QueryValueEx(key, APP_NAME)
            reg_exists = True
            print(f"Registry: {v}")
        except FileNotFoundError:
            pass
        winreg.CloseKey(key)
    except Exception as e:
        print(f"Registry check skipped: {e}")
    task_exists = False
    try:
        result = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME], capture_output=True, text=True)
        task_exists = result.returncode == 0
        if task_exists:
            print(result.stdout[:800])
    except Exception:
        pass
    print(f"Shortcut: {'installed' if sc else 'not installed'} ({shortcut_path()})")
    print(f"Registry: {'installed' if reg_exists else 'not installed'}")
    print(f"Task: {'installed' if task_exists else 'not installed'} ({TASK_NAME})")
    if sc or reg_exists or task_exists:
        print("Overall: Installed (will auto-start on logon)")
    else:
        print("Overall: Not installed")

def install(exe_override=None, with_task=False):
    if os.name != "nt":
        raise RuntimeError("Windows only")
    print(f"Installing auto-start for: {APP_NAME}")
    ok1 = install_shortcut(exe_override)
    ok2 = install_registry(exe_override)
    ok3 = False
    if with_task:
        ok3 = install_task(exe_override)
    if not (ok1 or ok2 or ok3):
        raise RuntimeError("All install methods failed. Try: pip install pywin32 and run as normal user.")
    print("Done. Agent will start on next logon. To start now: python main.py --hidden  (or run the exe)")
    # Also ensure onboarding has been done
    try:
        from secure_store import has_secure_config
        if not has_secure_config():
            print("NOTE: No credentials saved yet. Run: python onboarding.py  or  python main.py")
    except Exception:
        pass

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Timesheet startup helper")
    parser.add_argument("action", choices=["install", "uninstall", "status"], help="action")
    parser.add_argument("--exe", dest="exe", default=None, help="path to installed exe (e.g. C:\\Program Files\\TimesheetManager\\TimesheetAgent.exe)")
    parser.add_argument("--task", action="store_true", help="also create Scheduled Task (with install)")
    args = parser.parse_args()
    if args.action == "install":
        install(exe_override=args.exe, with_task=args.task)
    elif args.action == "uninstall":
        uninstall()
    elif args.action == "status":
        status()
