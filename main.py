"""
Timesheet Agent - entry point for installed app and dev.

Flow:
  1) Load secure config (%APPDATA%/TimesheetManager/config.enc via DPAPI)
     fallback to .env. If neither -> launch onboarding GUI.
  2) Validate credentials against BACKEND_BASE_URL/api/auth/login (backend_auth)
  3) Test MySQL, ensure_schema, start SessionTracker + IdleMonitor
  4) Handle OS signals + Windows shutdown/logoff/sleep to record 'off' reliably
  5) Run silently (pythonw / --hidden) or tray mode

CLI:
  python main.py                 # normal run
  python main.py --onboarding    # force credential prompt
  python main.py --hidden        # no console popup hint (for Startup)
  python main.py --service       # service mode (no onboarding prompt, just exit if not configured)
"""
import argparse
import atexit
import logging
import signal
import sys
import time
from pathlib import Path

# --- logging to file + console (file always, console if not hidden) ---
from secure_store import get_log_path, get_app_dir

LOG_PATH = get_log_path()
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

def setup_logging(hidden: bool, level: str):
    lvl = getattr(logging, level.upper(), logging.INFO)
    handlers = [logging.FileHandler(str(LOG_PATH), encoding="utf-8")]
    if not hidden:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=lvl, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s", handlers=handlers, force=True)

# parse early for hidden flag
_early_parser = argparse.ArgumentParser(add_help=False)
_early_parser.add_argument("--hidden", action="store_true")
_early_parser.add_argument("--service", action="store_true")
_early_args, _ = _early_parser.parse_known_args()

from config import settings
setup_logging(hidden=_early_args.hidden, level=settings.log_level)
log = logging.getLogger("agent")

from backend_auth import validate_backend_credentials
from session import SessionTracker
from idle_monitor import IdleMonitor
from db import ensure_schema, test_connection

# --- Windows shutdown/logoff hook ---
_windows_shutdown_registered = False

def _register_windows_shutdown_handler(agent_ref):
    """Register for Windows shutdown/logoff/close events.

    Uses:
      - SetConsoleCtrlHandler for CTRL_SHUTDOWN_EVENT / CTRL_LOGOFF_EVENT
      - Hidden window for WM_QUERYENDSESSION / WM_ENDSESSION (best with pythonw)
      - atexit for normal exit
    """
    global _windows_shutdown_registered
    if _windows_shutdown_registered:
        return
    _windows_shutdown_registered = True

    # atexit always
    def _atexit_handler():
        try:
            if agent_ref and agent_ref.get("agent"):
                ag = agent_ref["agent"]
                if ag and ag.running:
                    log.info("atexit: recording session off")
                    ag._do_stop_once()
        except Exception:
            pass

    atexit.register(_atexit_handler)

    if sys.platform != "win32":
        return

    # Console control handler (works for console + service)
    try:
        import win32api
        import win32con

        def _ctrl_handler(ctrl_type):
            # win32con.CTRL_SHUTDOWN_EVENT = 6, CTRL_LOGOFF_EVENT = 5
            log.info("ConsoleCtrlHandler ctrl_type=%s - shutting down", ctrl_type)
            try:
                ag = agent_ref.get("agent")
                if ag:
                    ag.stop()
                    # give time to flush DB
                    time.sleep(1.5)
                    ag._do_stop_once()
            except Exception as e:
                log.error("ctrl_handler error: %s", e)
            return True  # handled

        win32api.SetConsoleCtrlHandler(_ctrl_handler, True)
        log.info("Windows console ctrl handler registered")
    except Exception as e:
        log.debug("SetConsoleCtrlHandler not available: %s", e)

    # Hidden window for WM_QUERYENDSESSION / WM_ENDSESSION / WM_POWERBROADCAST
    # This catches shutdown even when running as pythonw (no console)
    try:
        import threading
        import win32gui
        import win32con  # type: ignore

        def _wnd_thread():
            try:
                wc = win32gui.WNDCLASS()
                wc.lpfnWndProc = _wnd_proc
                wc.lpszClassName = "TimesheetAgentShutdownHook"
                wc.hInstance = win32gui.GetModuleHandle(None)
                try:
                    win32gui.RegisterClass(wc)
                except Exception:
                    pass  # already registered
                hwnd = win32gui.CreateWindow(wc.lpszClassName, "TimesheetAgentHook", 0, 0, 0, 0, 0, 0, 0, wc.hInstance, None)
                log.info("Shutdown hook window hwnd=%s", hwnd)
                win32gui.PumpMessages()
            except Exception as e:
                log.debug("hidden window hook failed: %s", e)

        def _wnd_proc(hwnd, msg, wparam, lparam):
            try:
                if msg == win32con.WM_QUERYENDSESSION:
                    log.info("WM_QUERYENDSESSION received - stopping session")
                    ag = agent_ref.get("agent")
                    if ag:
                        ag.stop()
                        ag._do_stop_once()
                    return 1  # allow shutdown
                elif msg == win32con.WM_ENDSESSION:
                    if wparam:
                        log.info("WM_ENDSESSION wParam=True - session already stopped")
                    return 0
                elif msg == win32con.WM_POWERBROADCAST:
                    # PBT_APMSUSPEND = 0x4
                    if wparam == 0x4:
                        log.info("WM_POWERBROADCAST PBT_APMSUSPEND - system suspending")
                elif msg == win32con.WM_CLOSE:
                    log.info("WM_CLOSE - stopping")
                    ag = agent_ref.get("agent")
                    if ag:
                        ag.stop()
            except Exception as e:
                log.error("wnd_proc error: %s", e)
            return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

        t = threading.Thread(target=_wnd_thread, name="shutdown-hook-wnd", daemon=True)
        t.start()
    except Exception as e:
        log.debug("hidden window not registered: %s", e)


class Agent:
    def __init__(self, user_id: int):
        self.running = True
        self._stopped_once = False
        self.session = SessionTracker(user_id)
        self.idle = IdleMonitor(user_id)

    def stop(self, *_):
        if not self.running:
            return
        log.info("Stopping...")
        self.running = False

    def _do_stop_once(self):
        if self._stopped_once:
            return
        self._stopped_once = True
        try:
            self.idle.stop()
        except Exception:
            pass
        try:
            self.session.stop()
        except Exception:
            pass
        log.info("Tracker off (user_id=%s)", self.session.user_id)

    def run(self):
        try:
            signal.signal(signal.SIGINT, self.stop)
            if hasattr(signal, "SIGTERM"):
                signal.signal(signal.SIGTERM, self.stop)
            if hasattr(signal, "SIGBREAK"):
                signal.signal(signal.SIGBREAK, self.stop)
        except (ValueError, AttributeError):
            pass

        log.info("Agent start user_id=%s idle_after=%ss log=%s", self.session.user_id, settings.idle_after_seconds, LOG_PATH)
        if not test_connection():
            log.error("MySQL not reachable at %s:%s/%s", settings.mysql_host, settings.mysql_port, settings.mysql_database)
            log.error("Check XAMPP MySQL and phpMyAdmin http://localhost/phpmyadmin/index.php?route=/sql&db=timesheet_db")
            sys.exit(1)
        ensure_schema()
        log.info("DB ready: activity_states")

        # register shutdown hooks after DB is known good (so 'off' will succeed)
        _register_windows_shutdown_handler({"agent": self})

        self.session.start()
        self.idle.start()
        log.info("Tracker running - idle counted after %ss (hidden=%s)", settings.idle_after_seconds, _early_args.hidden)
        try:
            while self.running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            self.running = False
        finally:
            self._do_stop_once()


def ensure_credentials_or_onboard(force_onboarding: bool = False, service_mode: bool = False) -> bool:
    """Ensure we have valid credentials. If not, launch onboarding.

    Returns True if credentials are ready, False if user cancelled / service mode.
    """
    # Check if settings already have creds (secure store or .env)
    try:
        settings.validate()
        has_creds = True
    except Exception:
        has_creds = False

    if has_creds and not force_onboarding:
        return True

    if service_mode:
        # service should not pop GUI - just log and exit
        log.error("No credentials configured (run onboarding once as user). Service exiting.")
        return False

    log.info("No valid credentials - launching onboarding UI")
    # Try GUI onboarding, fallback to CLI if headless
    try:
        from onboarding import run_gui, run_cli
        try:
            code = run_gui()
        except Exception as e:
            log.warning("GUI onboarding failed (%s), trying CLI", e)
            code = run_cli()
        if code != 0:
            log.error("Onboarding cancelled/failed (code=%s)", code)
            return False
        # reload and re-validate
        settings.reload_secure()
        settings.validate()
        log.info("Onboarding complete, credentials saved to %s", get_app_dir())
        return True
    except SystemExit:
        raise
    except Exception as e:
        log.error("Onboarding error: %s", e)
        return False


def main():
    parser = argparse.ArgumentParser(description="Timesheet Agent")
    parser.add_argument("--onboarding", action="store_true", help="force credential prompt")
    parser.add_argument("--hidden", action="store_true", help="run without console UI hints")
    parser.add_argument("--service", action="store_true", help="service mode (no GUI prompt)")
    args = parser.parse_args()

    # re-setup logging if hidden flag differs from early parse
    setup_logging(hidden=args.hidden, level=settings.log_level)

    if not ensure_credentials_or_onboard(force_onboarding=args.onboarding, service_mode=args.service):
        if args.service:
            sys.exit(1)
        # if user cancelled onboarding, exit gracefully
        log.error("No credentials - run with --onboarding or set .env and retry")
        # offer to retry onboarding once more if not hidden
        if not args.hidden and sys.stdin.isatty():
            try:
                input("Press Enter to retry onboarding or Ctrl+C to exit...")
                if ensure_credentials_or_onboard(force_onboarding=True):
                    pass
                else:
                    sys.exit(1)
            except KeyboardInterrupt:
                sys.exit(1)
        else:
            sys.exit(1)

    # validate against backend (single API)
    try:
        auth = validate_backend_credentials()
    except Exception as e:
        log.error("Backend validation failed: %s", e)
        log.error("Check BACKEND_BASE_URL=%s USERID/PASSWORD", settings.backend_base_url)
        # if secure config is bad, offer re-onboarding
        if not args.service and not args.hidden:
            log.info("Credentials rejected - launching onboarding to re-enter")
            try:
                from secure_store import delete_secure_config
                # don't delete immediately, just re-prompt
                if ensure_credentials_or_onboard(force_onboarding=True):
                    auth = validate_backend_credentials()
                else:
                    sys.exit(1)
            except Exception as e2:
                log.error("Re-validation failed: %s", e2)
                sys.exit(1)
        else:
            sys.exit(1)

    log.info("Backend OK user_id=%s email=%s", auth["user_id"], auth.get("email", ""))
    # if secure store had no user_id, update it
    try:
        from secure_store import load_secure_config, save_credentials
        sc = load_secure_config()
        if sc and int(sc.get("user_id", 0) or 0) != int(auth["user_id"]):
            save_credentials(email=auth["email"], password=settings.backend_password, backend_url=settings.backend_base_url, user_id=auth["user_id"], token=auth.get("token", ""), extra={"user": auth.get("user", {})})
    except Exception:
        pass

    Agent(auth["user_id"]).run()


if __name__ == "__main__":
    main()
