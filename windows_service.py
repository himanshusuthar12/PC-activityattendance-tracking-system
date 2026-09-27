"""
Windows Service wrapper for Timesheet Agent.

Allows the agent to run as a Windows Service (auto-start before logon,
runs as LocalSystem or specified user, survives user logoff).

Requires pywin32.

Install:
  python windows_service.py install
  # then set service to auto-start:
  sc config TimesheetAgent start= auto
  net start TimesheetAgent

Or via pywin32:
  python windows_service.py --startup auto install
  python windows_service.py start
  python windows_service.py stop
  python windows_service.py remove

Note: Service runs as LocalSystem by default which has its own %APPDATA%.
For per-user DPAPI config, prefer Startup/Task mode. Service mode is
best when you store credentials machine-wide or use a service account.

Alternative: use --user mode where service reads from C:\\ProgramData\\TimesheetManager
"""
import sys
import time
import logging
from pathlib import Path

try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager
    HAS_SERVICE = True
except ImportError:
    HAS_SERVICE = False

from secure_store import get_log_path

LOG_PATH = get_log_path()
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s", handlers=[logging.FileHandler(str(LOG_PATH), encoding="utf-8")])
log = logging.getLogger("service")

if HAS_SERVICE:
    class TimesheetAgentService(win32serviceutil.ServiceFramework):
        _svc_name_ = "TimesheetAgent"
        _svc_display_name_ = "TimesheetManager PC Activity Agent"
        _svc_description_ = "Tracks PC session start/stop and idle time to MySQL timesheet_db. Validates user via C# HRMS backend."

        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
            self.agent = None
            self._running = False
            # need to set current dir to app dir for config/.env
            try:
                app_dir = Path(__file__).parent
                import os
                os.chdir(str(app_dir))
            except Exception:
                pass

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            log.info("Service stop requested")
            try:
                if self.agent:
                    self.agent.stop()
                    self.agent._do_stop_once()
            except Exception as e:
                log.error("SvcStop error: %s", e)
            win32event.SetEvent(self.hWaitStop)
            self._running = False

        def SvcDoRun(self):
            servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE, servicemanager.PYS_SERVICE_STARTED, (self._svc_name_, ""))
            log.info("Service starting")
            self._running = True
            try:
                # import here so service control is responsive
                from config import settings
                from backend_auth import validate_backend_credentials
                from main import Agent

                # validate credentials (service mode = no GUI)
                try:
                    settings.validate()
                except Exception as e:
                    log.error("No credentials configured for service: %s", e)
                    log.error("Run onboarding once as the service user or set .env, then restart service")
                    return

                try:
                    auth = validate_backend_credentials()
                except Exception as e:
                    log.error("Backend validation failed in service: %s", e)
                    return

                log.info("Service backend OK user_id=%s", auth["user_id"])
                self.agent = Agent(auth["user_id"])

                # run agent in background thread so we can watch for stop event
                import threading

                def _run_agent():
                    try:
                        self.agent.run()
                    except Exception as e:
                        log.exception("Agent run failed: %s", e)

                t = threading.Thread(target=_run_agent, name="service-agent", daemon=True)
                t.start()

                # wait for stop signal, keep service alive
                while self._running:
                    rc = win32event.WaitForSingleObject(self.hWaitStop, 2000)
                    if rc == win32event.WAIT_OBJECT_0:
                        break
                    # keep alive check - if agent thread died, restart? For now just log
                    if not t.is_alive() and self._running:
                        log.warning("Agent thread died, restarting in 10s")
                        time.sleep(10)
                        if self._running:
                            t = threading.Thread(target=_run_agent, name="service-agent-restart", daemon=True)
                            t.start()

            except Exception as e:
                log.exception("Service run error: %s", e)
            finally:
                log.info("Service stopped")

if __name__ == "__main__":
    if not HAS_SERVICE:
        print("pywin32 not installed. Install with: pip install pywin32")
        print("Service mode requires Windows + pywin32. For non-service auto-start, use: python startup.py install")
        sys.exit(1)
    win32serviceutil.HandleCommandLine(TimesheetAgentService)
