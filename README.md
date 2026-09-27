# PC Activity / Attendance Tracking — TimesheetManager

Lightweight Windows agent that validates a user against a C# HRMS backend (**single auth API**) and then tracks PC **session start / stop** and **idle time** directly into **MySQL `timesheet_db.activity_states`** (`127.0.0.1:3306`). No activity data is ever sent to the backend.

> **New — installable app:** This repo now builds a real **Windows Setup.exe** (Inno Setup + PyInstaller). On install it asks for **Username + Password**, validates against the C# backend, saves it **encrypted (DPAPI)**, and runs **silently on boot** — recording `off` even on shutdown/logoff without manual start. See [Is it possible? — End-to-end flow](#is-it-possible--end-to-end-flow).

---

## Table of Contents
- [Is it possible? — End-to-end flow](#is-it-possible--end-to-end-flow)
- [How it works (installed app)](#how-it-works-installed-app)
- [Project structure](#project-structure)
- [Configuration](#configuration)
- [Database schema](#database-schema)
- [Dev setup & run](#dev-setup--run)
- [Build the Setup.exe](#build-the-setupexe)
- [Installer behavior & auto-start options](#installer-behavior--auto-start-options)
- [Shutdown / logoff handling](#shutdown--logoff-handling)
- [Status UI](#status-ui)
- [Viewer API](#viewer-api)
- [Logging & verification](#logging--verification)
- [Troubleshooting](#troubleshooting)

---

## Is it possible? — End-to-end flow

**Yes — 100% possible on Windows without admin (per-user) or with admin (service).**

Complete path from code to installed app on another machine:

```
1) Code + DB ready
   python init_db.py  -> creates timesheet_db.activity_states (MySQL via XAMPP)
   C# HRMS backend running at BACKEND_BASE_URL (POST /api/auth/login)

2) Build exe (dev machine)
   pip install pyinstaller
   python build.py                -> dist/TimesheetAgent/TimesheetAgent.exe  (windowed, no console)
   # optional: python build.py --with-tray --with-onboarding

3) Create installer
   Install Inno Setup 6 (https://jrsoftware.org/isinfo.php)
   iscc installer\installer.iss   -> installer\Output\TimesheetManager-Setup-2.0.0.exe

4) Distribute Setup.exe to target Windows machine

5) User runs Setup.exe
   -> Copies to C:\Program Files\TimesheetManager\  (or per-user %LocalAppData%)
   -> [Run] TimesheetAgent.exe --onboarding   (GUI: Username + Password + Backend URL)
        -> POST {BACKEND_BASE_URL}/api/auth/login  (backend_auth.py:17)
        -> on 200 {user:{id}} saves encrypted to %APPDATA%\TimesheetManager\config.enc (DPAPI)
        -> via secure_store.py:7  (win32crypt.CryptProtectData, per-user, not readable on other machines/users)
   -> Creates auto-start (Startup .lnk + HKCU Run [+ optional Scheduled Task])
        -> via startup.py:38  / installer.iss [Registry]

6) From now on — no manual start needed
   - On every Windows logon:  TimesheetAgent.exe --hidden  starts silently (pythonw, no window)
   - On power on / reboot: same — Task/Startup fires automatically
   - Agent: validates cached creds, test_connection() -> ensure_schema() -> SessionTracker.start() (insert 'start')
            -> IdleMonitor (GetLastInputInfo + GetTickCount64) -> periodic 'idle' inserts
   - On shutdown / logoff / sleep / Ctrl+C:  WM_QUERYENDSESSION + SetConsoleCtrlHandler + atexit -> SessionTracker.stop() (insert 'off')
            -> handled in main.py:_register_windows_shutdown_handler  (hidden window + console handler)
   - Logs to %APPDATA%\TimesheetManager\agent.log

7) Optional status
   Start Menu -> TimesheetManager Status  -> TimesheetAgent.exe --tray  (tray_app.py)
   -> shows bound user, backend/DB health, autostart state, log tail, Re-login, Open Dashboard
   Viewer: http://127.0.0.1:8000/dashboard  (server.py) reads from MySQL

8) Uninstall
   Add/Remove Programs -> TimesheetManager -> removes files + autostart (+ keeps DB rows)
   Or: python startup.py uninstall  /  delete %APPDATA%\TimesheetManager\config.enc to re-onboard
```

**What you send to users:** single `TimesheetManager-Setup-2.0.0.exe` (~15–30 MB one-dir, ~12 MB one-file). No Python needed on target machine (PyInstaller bundles it).

---

## How it works (installed app)

```
Secure store: %APPDATA%\TimesheetManager\config.enc  (DPAPI per-user)
                    ▲  save/load via secure_store.py
                    │
Onboarding GUI  onboarding.py ──POST /api/auth/login──► C# HRMS Backend :5000
 (Tkinter)  ──────────┴─ success {user_id, token} ──► encrypted JSON
                                                  │
Installed exe  main.py --hidden (pythonw) ◄───────┘
   ├─ config.py  (secure store takes precedence over .env)
   ├─ backend_auth.py:validate_backend_credentials()
   ├─ main.py:Agent  ──► SessionTracker  -> activity_states (start/off)
   │                 └─► IdleMonitor    -> activity_states (idle)
   ├─ db.py (pymysql) ──► MySQL timesheet_db
   └─ shutdown hooks: hidden window (WM_QUERYENDSESSION) + SetConsoleCtrlHandler + atexit
           └──► inserts 'off' even on power off without manual close

Autostart (any one is enough):
  • Startup folder: %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\TimesheetManager Agent.lnk -> exe --hidden  (no admin)
  • Registry: HKCU\Software\Microsoft\Windows\CurrentVersion\Run  (no admin)
  • Scheduled Task: TimesheetManagerAgent  ONLOGON  (optional, via startup.py --task)
  • Windows Service: TimesheetAgent  (admin, windows_service.py, runs before logon)

Viewer (optional): server.py :8000  +  static/login.html, static/dashboard.html
Tray status: tray_app.py  (pystray + tkinter)  --tray
```

**Privacy:** only `start`/`off` timestamps + idle periods (`idle_at`, `idle_duration_seconds`, `m:ss`). No keystrokes/URLs/screenshots.

---

## Project structure

```
config.py            # Settings dataclass, _load_secure_store() -> DPAPI config.enc takes precedence over .env
secure_store.py      # DPAPI encrypt/decrypt (%APPDATA%\TimesheetManager\config.enc), save_credentials(), load_secure_config()
backend_auth.py      # validate_backend_credentials() — single POST /api/auth/login
db.py                # pymysql MySQL helper — get_mysql_connection(), ensure_schema(), insert_start/off/idle()
session.py           # SessionTracker(user_id) — start()/stop()
idle_monitor.py      # get_idle_seconds() via GetLastInputInfo + GetTickCount64, IdleMonitor thread
main.py              # Agent entry — secure load -> onboarding fallback -> validate -> shutdown hooks -> run
onboarding.py        # Tkinter credential prompt (install/first-run/Re-login), validates + DPAPI save
startup.py           # Auto-start helper — shortcut + registry + scheduled task (install/uninstall/status, --exe, --task)
windows_service.py   # Optional Windows Service wrapper (pywin32 ServiceFramework, admin)
tray_app.py          # Optional system tray + status window (pystray + Pillow, --tray)
server.py            # FastAPI viewer — POST /api/auth/login proxy, /health, /api/activity, static
init_db.py / .sql    # MySQL schema ensure for activity_states
build.py             # PyInstaller build script (one-dir default, --onefile, --with-tray)
build.ps1            # PowerShell helper: venv + pip + pyinstaller + optional iscc
installer/
  installer.iss      # Inno Setup 6 script -> Output\TimesheetManager-Setup-2.0.0.exe
requirements.txt     # pinned deps + pyinstaller/pystray/Pillow (Windows)
.env                 # dev fallback (USERID/PASSWORD/BACKEND_BASE_URL/MYSQL_*)
static/login.html, dashboard.html
```

History: `MSSQL/pyodbc/Computers/Sessions/Events` removed — current is **single table `activity_states`**.

---

## Configuration

Priority: **secure store (`config.enc` DPAPI) > .env > defaults**. `config.py:23` `_secure_or_env()`.

```ini
# .env — dev fallback only. Installed app uses DPAPI config.enc instead.
BACKEND_BASE_URL=http://127.0.0.1:5000
USERID=admin@udaaann.com
PASSWORD=UDaaann@2026

MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=
MYSQL_DATABASE=timesheet_db

IDLE_POLL_SECONDS=5
IDLE_AFTER_SECONDS=30
LOG_LEVEL=INFO
PORT=8000
```

| Variable | Default | Notes |
|----------|---------|-------|
| `BACKEND_BASE_URL` | `http://127.0.0.1:5000` | C# backend, only `POST /api/auth/login` |
| `USERID` / `PASSWORD` | — | `email`/`password` sent to login; aliases supported (`BACKEND_EMAIL` etc.) |
| `MYSQL_*` | `127.0.0.1:3306/root/timesheet_db` | XAMPP MySQL |
| `IDLE_AFTER_SECONDS` | `30` | idle threshold |
| `LOG_LEVEL` / `PORT` | `INFO` / `8000` | viewer port |

Installed location: `%APPDATA%\TimesheetManager\config.enc` (DPAPI, per-user, per-machine) — `secure_store.py:12` `get_app_dir()`. Plain `%APPDATA%\TimesheetManager\config.json` is legacy fallback. Delete `config.enc` to force re-onboarding.

---

## Database schema

Single table `timesheet_db.activity_states` (`db.py:29`, `init_db.sql:2`):

```sql
CREATE TABLE IF NOT EXISTS activity_states (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    status ENUM('start','off','idle') NOT NULL,
    start_time DATETIME NULL,
    end_time DATETIME NULL,
    idle_at DATETIME NULL,
    idle_duration_seconds INT NULL,
    idle_duration_display VARCHAR(20) NULL, -- m:ss e.g. "2:05"
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user (user_id),
    INDEX idx_status (status),
    INDEX idx_idle_at (idle_at)
);
```

`status='start'` via `db.py:69` `insert_start()`, `off` via `insert_off()`, `idle` via `insert_idle()` (`m:ss`).

---

## Dev setup & run

```powershell
py -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

notepad .env   # set C# backend URL and MySQL

# ensure MySQL running (XAMPP -> MySQL Start), create DB if needed
python init_db.py
# -> MySQL Connected OK. activity_states exists: True

# First run: will pop onboarding GUI if no .env/secure config (or use --onboarding)
python onboarding.py          # or: python onboarding.py --cli
python main.py                # validates -> tracks; Ctrl+C inserts 'off'
python main.py --hidden       # silent (for testing Startup feel)
python main.py --onboarding   # force re-prompt

# optional viewer + status UI
python server.py              # http://127.0.0.1:8000  /health  /docs  /dashboard
python tray_app.py            # tray + status window (needs Pillow/pystray)
python tray_app.py            # if tray fails, falls back to window
```

Logs: `%APPDATA%\TimesheetManager\agent.log` (always) + console (unless `--hidden`/`--windowed`).

---

## Build the Setup.exe

### Quick (PowerShell)

```powershell
.\build.ps1                   # one-dir windowed build
.\build.ps1 -OneFile           # single exe
.\build.ps1 -WithTray -WithOnboarding
.\build.ps1 -WithInstaller     # also runs iscc if Inno Setup installed
```

### Manual

```powershell
pip install pyinstaller
python build.py               # -> dist/TimesheetAgent/TimesheetAgent.exe
python build.py --onefile     # -> dist/TimesheetAgent.exe (single file, slower cold start)
python build.py --with-tray   # -> dist/TimesheetAgentTray.exe
python build.py --with-onboarding

# Inno Setup 6 (https://jrsoftware.org/isinfo.php) -> iscc
iscc installer\installer.iss
# -> installer\Output\TimesheetManager-Setup-2.0.0.exe
```

**Output sizes:** one-dir ~25 MB folder (fast start), one-file ~12–18 MB (slower). Both bundle Python — target machine needs no Python.

**Test the built exe without installer:**

```powershell
.\dist\TimesheetAgent\TimesheetAgent.exe --onboarding
.\dist\TimesheetAgent\TimesheetAgent.exe --hidden
# check: %APPDATA%\TimesheetManager\config.enc exists, agent.log tail, phpMyAdmin rows
```

---

## Installer behavior & auto-start options

`installer/installer.iss:1` — per-user install (`PrivilegesRequired=lowest` — no admin). Change to `admin` for machine-wide + service.

| Method | Privilege | When it starts | How it runs | File/registry |
|--------|-----------|----------------|-------------|---------------|
| **Startup shortcut** (default) | none | user logon | `TimesheetAgent.exe --hidden` via `.lnk` | `%APPDATA%\...\Startup\TimesheetManager Agent.lnk` |
| **Registry Run** | none | user logon | `HKCU\...\Run\TimesheetManager Agent = "…\TimesheetAgent.exe" --hidden` | `startup.py:install_registry()` |
| **Scheduled Task** | none (or admin for HIGHEST) | `ONLOGON` | `schtasks /Create /SC ONLOGON /TN TimesheetManagerAgent` | `startup.py --task` |
| **Windows Service** | admin | boot (before logon) | `windows_service.py` via `win32serviceutil` | `sc create TimesheetAgent` |

Default installer enables **shortcut + registry** (`Tasks: autostart`). Service is opt-in.

**Manage autostart:**

```powershell
python startup.py status
python startup.py install                        # shortcut + registry (source mode: pythonw main.py --hidden)
python startup.py install --exe "C:\Program Files\TimesheetManager\TimesheetAgent.exe"
python startup.py install --task --exe "C:\...\TimesheetAgent.exe"
python startup.py uninstall

# service (admin PowerShell)
python windows_service.py install
python windows_service.py --startup auto install
sc config TimesheetAgent start= auto
net start TimesheetAgent
net stop TimesheetAgent
python windows_service.py remove
```

Uninstall via `Add/Remove Programs` removes files + autostart.

---

## Shutdown / logoff handling

Records `off` even if user just clicks **Shut down** / **Sign out** without closing the app:

- Hidden window `TimesheetAgentShutdownHook` listens `WM_QUERYENDSESSION` / `WM_ENDSESSION` (`main.py:_register_windows_shutdown_handler`, `win32gui.PumpMessages`) — works with `pythonw --windowed`.
- `SetConsoleCtrlHandler` catches `CTRL_SHUTDOWN_EVENT` / `CTRL_LOGOFF_EVENT` (`main.py:win32api.SetConsoleCtrlHandler`).
- `atexit` + `SIGTERM`/`SIGBREAK` as fallback.

All paths call `Agent._do_stop_once()` which does `idle.stop()` + `session.stop()` (`insert_off`). Tested to flush within ~1.5s before Windows kills the process (returns `1` to `WM_QUERYENDSESSION` to allow shutdown).

---

## Status UI

**Tray** (`tray_app.py`, needs `pystray` + `Pillow`):

```powershell
python tray_app.py
# or built: dist\TimesheetAgent\TimesheetAgent.exe --tray
# Start Menu shortcut: TimesheetManager Status
```

Shows bound user, backend/DB health, autostart state, log tail (40 lines), buttons: Refresh / Re-login / Start Agent / View Dashboard / Open Log, plus auto-start checkbox.

If tray unavailable, falls back to plain `StatusWindow` (tkinter).

---

## Viewer API

`server.py:38`

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/auth/login` | Proxy to `POST {BACKEND_BASE_URL}/api/auth/login` |
| `GET` | `/health` | DB + backend liveness |
| `GET` | `/api/activity?limit=50&user_id=&status=idle\|start\|off` | List `activity_states` |
| `GET` | `/api/v1/events` | Alias for `/api/activity` |
| `GET` | `/`, `/login`, `/dashboard` | `static/login.html`, `dashboard.html` |

```powershell
curl http://127.0.0.1:8000/health
curl "http://127.0.0.1:8000/api/activity?user_id=1&status=idle&limit=20"
```

> Note: `dashboard.html` may fetch `/api/auth/me`, `/api/v1/computers` etc. not yet implemented — use `/api/activity`/`/health`.

---

## Logging & verification

```powershell
python -m py_compile config.py secure_store.py onboarding.py main.py startup.py tray_app.py
python -c "from config import settings; settings.validate(); print('env OK', settings.backend_base_url, settings.mysql_database)"
type $env:APPDATA\TimesheetManager\agent.log
Get-Content $env:APPDATA\TimesheetManager\config.enc -ErrorAction SilentlyContinue | Measure-Object  # encrypted blob exists
curl http://127.0.0.1:8000/health
# phpMyAdmin: http://localhost/phpmyadmin/index.php?route=/sql&db=timesheet_db&table=activity_states
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Onboarding 401 Invalid credentials | `USERID`/`PASSWORD` mismatch with `users` table; check `BACKEND_BASE_URL` |
| Backend not reachable / 404 | C# backend not running or route ≠ `POST /api/auth/login`; check port/firewall |
| MySQL not reachable | XAMPP MySQL not started, wrong `MYSQL_PASSWORD`, DB `timesheet_db` not created (`python init_db.py`) |
| No config.enc after onboarding | `pywin32` missing (`pip install pywin32`) → fallback to plain `config.json`; check `%APPDATA%\TimesheetManager` |
| Agent doesn't auto-start | `python startup.py status`; re-run `install --exe "<path>"`; check Defender/AV quarantine |
| No `off` on shutdown | Ensure `pywin32` installed; built exe must be `--windowed` (has message loop); check `agent.log` for `WM_QUERYENDSESSION` |
| Service has no credentials | Service runs as `LocalSystem` with its own `%APPDATA%`; run onboarding as service user or switch to Startup/Task mode for per-user config |
| Viewer 404 on `/api/v1/computers` | Expected — not implemented; use `/api/activity` |

---

## Roadmap

- Per-machine encrypted store (`C:\ProgramData\TimesheetManager`) for service mode
- Auto-update (check GitHub releases + silent MSI)
- Attendance daily aggregation + export

---

## License

Internal demo — no license specified.
