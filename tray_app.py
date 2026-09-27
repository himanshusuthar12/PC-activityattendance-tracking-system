"""
Tray / Status UI - optional small app for user/admin.

Features:
  - System tray icon (pystray) with menu: Status, Open Dashboard, Re-login, View Log, Exit
  - Status window (tkinter) showing: bound user, backend, DB, last activity, auto-start state
  - Starts agent as subprocess (pythonw) if not running, or shows its log tail
  - "Re-login" opens onboarding GUI

Run:
  python tray_app.py
  # or as exe built via PyInstaller with --hidden

Requires: pystray, Pillow (PIL)
  pip install pystray Pillow
Falls back to plain tkinter window if pystray not available.
"""
import subprocess
import sys
import time
import threading
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import scrolledtext, messagebox

from config import settings
from secure_store import load_secure_config, get_app_dir, get_log_path, has_secure_config

APP_TITLE = "TimesheetManager Agent"

def get_status_info():
    info = {}
    sc = load_secure_config()
    if sc:
        info["user"] = f"{sc.get('email')} (id={sc.get('user_id')})"
        info["backend_url"] = sc.get("backend_url")
        info["configured"] = True
    else:
        info["user"] = "Not configured"
        info["backend_url"] = settings.backend_base_url
        info["configured"] = False
    # backend check
    try:
        import requests
        url = info["backend_url"].rstrip("/") + "/api/auth/login"
        r = requests.post(url, json={"email": "healthcheck@test.com", "password": "x"}, timeout=4)
        info["backend_ok"] = r.status_code in (401, 400, 422)
        info["backend_detail"] = f"HTTP {r.status_code}"
    except Exception as e:
        info["backend_ok"] = False
        info["backend_detail"] = str(e)[:120]
    # db check
    try:
        from db import test_connection
        info["db_ok"] = test_connection()
    except Exception as e:
        info["db_ok"] = False
        info["db_error"] = str(e)[:200]
    # autostart check
    try:
        from startup import shortcut_path
        import winreg
        sc_exists = shortcut_path().exists()
        reg_exists = False
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
            winreg.QueryValueEx(k, "TimesheetManager Agent")
            reg_exists = True
            winreg.CloseKey(k)
        except Exception:
            pass
        info["autostart"] = sc_exists or reg_exists
        info["autostart_detail"] = f"shortcut={sc_exists} registry={reg_exists}"
    except Exception:
        info["autostart"] = False
        info["autostart_detail"] = "unknown"
    # log tail
    try:
        lp = get_log_path()
        if lp.exists():
            txt = lp.read_text(encoding="utf-8", errors="ignore")
            lines = txt.strip().splitlines()
            info["log_tail"] = "\n".join(lines[-40:])
            info["log_path"] = str(lp)
        else:
            info["log_tail"] = "(no log yet)"
            info["log_path"] = str(lp)
    except Exception as e:
        info["log_tail"] = str(e)
    return info


class StatusWindow:
    def __init__(self, root=None):
        self.root = root or tk.Tk()
        self.root.title(APP_TITLE + " — Status")
        self.root.geometry("560x620")
        self.root.configure(bg="#0f172a")
        try:
            self.root.eval('tk::PlaceWindow . center')
        except Exception:
            pass
        self.build()
        self.refresh()

    def build(self):
        outer = tk.Frame(self.root, bg="#0f172a", padx=16, pady=14)
        outer.pack(fill="both", expand=True)

        tk.Label(outer, text="TimesheetManager — Agent Status", font=("Segoe UI", 13, "bold"), bg="#0f172a", fg="#f8fafc").pack(anchor="w")
        tk.Label(outer, text="PC activity tracking agent", font=("Segoe UI", 8), bg="#0f172a", fg="#94a3b8").pack(anchor="w", pady=(2, 12))

        self.info_frame = tk.Frame(outer, bg="#1e293b", highlightbackground="#334155", highlightthickness=1, padx=12, pady=10)
        self.info_frame.pack(fill="x")

        self.labels = {}
        for key, label in [("user", "Bound User"), ("backend_url", "Backend URL"), ("backend_ok", "Backend"), ("db_ok", "MySQL DB"), ("autostart", "Auto-start"), ("log_path", "Log file")]:
            row = tk.Frame(self.info_frame, bg="#1e293b")
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label, font=("Segoe UI", 8, "bold"), bg="#1e293b", fg="#94a3b8", width=14, anchor="w").pack(side="left")
            v = tk.Label(row, text="—", font=("Segoe UI", 8), bg="#1e293b", fg="#e2e8f0", wraplength=380, justify="left", anchor="w")
            v.pack(side="left", fill="x", expand=True)
            self.labels[key] = v

        btns = tk.Frame(outer, bg="#0f172a")
        btns.pack(fill="x", pady=(10, 0))

        def btn(txt, cmd, primary=False):
            bg = "#38bdf8" if primary else "#1e293b"
            fg = "#0f172a" if primary else "#e2e8f0"
            b = tk.Button(btns, text=txt, command=cmd, bg=bg, fg=fg, activebackground="#0ea5e9" if primary else "#334155", font=("Segoe UI", 8, "bold" if primary else "normal"), relief="flat", padx=10, pady=6, cursor="hand2", highlightthickness=1, highlightbackground="#334155")
            b.pack(side="left", padx=(0, 6))
            return b

        btn("Refresh", self.refresh)
        btn("Re-login", self.relogin, primary=True)
        btn("Start Agent", self.start_agent)
        btn("View Dashboard", self.open_dashboard)
        btn("Open Log", self.open_log)

        tk.Label(outer, text="Recent log (tail 40 lines):", font=("Segoe UI", 8, "bold"), bg="#0f172a", fg="#94a3b8").pack(anchor="w", pady=(12, 4))
        self.log_text = scrolledtext.ScrolledText(outer, height=18, font=("Consolas", 8), bg="#020617", fg="#cbd5e1", insertbackground="#e2e8f0", relief="flat", highlightthickness=1, highlightbackground="#334155")
        self.log_text.pack(fill="both", expand=True)

        footer = tk.Frame(outer, bg="#0f172a")
        footer.pack(fill="x", pady=(8, 0))
        tk.Label(footer, text=f"Config: {get_app_dir()}  •  Viewer: http://127.0.0.1:{settings.port}", font=("Segoe UI", 7), bg="#0f172a", fg="#64748b").pack(anchor="w")
        # autostart toggle
        self.autostart_var = tk.BooleanVar()
        tk.Checkbutton(footer, text="Auto-start on Windows logon", variable=self.autostart_var, command=self.toggle_autostart, bg="#0f172a", fg="#cbd5e1", selectcolor="#1e293b", activebackground="#0f172a", font=("Segoe UI", 8)).pack(anchor="w", pady=(4, 0))

    def refresh(self):
        info = get_status_info()
        self.labels["user"].configure(text=info.get("user", "—"))
        self.labels["backend_url"].configure(text=info.get("backend_url", "—"))
        bg_ok = info.get("backend_ok")
        self.labels["backend_ok"].configure(text=("Connected ✓" if bg_ok else "Not reachable ✗") + f"  {info.get('backend_detail','')}", fg="#4ade80" if bg_ok else "#f87171")
        db_ok = info.get("db_ok")
        self.labels["db_ok"].configure(text="Connected ✓" if db_ok else "Error ✗ " + info.get("db_error",""), fg="#4ade80" if db_ok else "#f87171")
        auto = info.get("autostart")
        self.labels["autostart"].configure(text=("Enabled ✓" if auto else "Disabled") + f"  {info.get('autostart_detail','')}", fg="#4ade80" if auto else "#fbbf24")
        self.autostart_var.set(bool(auto))
        self.labels["log_path"].configure(text=info.get("log_path","—"))
        self.log_text.delete("1.0", tk.END)
        self.log_text.insert(tk.END, info.get("log_tail",""))
        self.log_text.see(tk.END)

    def relogin(self):
        # run onboarding gui as subprocess so it blocks but not freeze
        try:
            import subprocess, sys
            from pathlib import Path
            # if frozen exe, onboarding is next to exe
            if getattr(sys, "frozen", False):
                exe = Path(sys.executable)
                # try TimesheetAgent.exe --onboarding vs onboarding.exe
                subprocess.Popen([str(exe), "--onboarding"])
            else:
                subprocess.Popen([sys.executable, str(Path(__file__).parent / "onboarding.py")])
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def start_agent(self):
        try:
            from pathlib import Path
            if getattr(sys, "frozen", False):
                exe = Path(sys.executable)
                subprocess.Popen([str(exe), "--hidden"], creationflags=subprocess.DETACHED_PROCESS if sys.platform == "win32" else 0)
            else:
                py = Path(sys.executable)
                pyw = py.with_name("pythonw.exe")
                target = str(pyw) if pyw.exists() else sys.executable
                main_py = str(Path(__file__).parent / "main.py")
                subprocess.Popen([target, main_py, "--hidden"], creationflags=subprocess.DETACHED_PROCESS if sys.platform == "win32" else 0)
            messagebox.showinfo("Agent", "Agent start requested (hidden). Check log tail after a few seconds.")
            self.root.after(2000, self.refresh)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def open_dashboard(self):
        try:
            webbrowser.open(f"http://127.0.0.1:{settings.port}/dashboard")
            # also try start server if not running
            try:
                import requests
                requests.get(f"http://127.0.0.1:{settings.port}/health", timeout=1.5)
            except Exception:
                # start viewer in background
                if not getattr(sys, "frozen", False):
                    subprocess.Popen([sys.executable, str(Path(__file__).parent / "server.py")], creationflags=subprocess.DETACHED_PROCESS if sys.platform == "win32" else 0)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def open_log(self):
        try:
            lp = get_log_path()
            if sys.platform == "win32":
                import os
                os.startfile(str(lp))  # type: ignore
            else:
                webbrowser.open(str(lp))
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def toggle_autostart(self):
        try:
            from startup import install, uninstall
            if self.autostart_var.get():
                install()
            else:
                uninstall()
            self.refresh()
        except Exception as e:
            messagebox.showerror("Auto-start", str(e))

    def run(self):
        self.root.mainloop()


def try_tray():
    """Try pystray tray, fallback to window."""
    try:
        import pystray  # type: ignore
        from PIL import Image, ImageDraw  # type: ignore

        # create simple icon (blue circle with clock)
        def create_image():
            img = Image.new("RGBA", (64, 64), (15, 23, 42, 0))
            d = ImageDraw.Draw(img)
            d.ellipse([4, 4, 60, 60], fill="#38bdf8", outline="#0ea5e9", width=2)
            d.ellipse([22, 18, 42, 38], outline="white", width=2)
            d.line([32, 28, 32, 38], fill="white", width=2)
            d.line([32, 32, 38, 32], fill="white", width=2)
            return img

        status_win = None

        def show_status(icon, item):
            def _show():
                nonlocal status_win
                # need to run on main thread
                win = tk.Tk()
                StatusWindow(win).run()
            threading.Thread(target=_show, daemon=True).start()

        def do_relogin(icon, item):
            try:
                if getattr(sys, "frozen", False):
                    subprocess.Popen([sys.executable, "--onboarding"])
                else:
                    subprocess.Popen([sys.executable, str(Path(__file__).parent / "onboarding.py")])
            except Exception:
                pass

        def do_quit(icon, item):
            icon.stop()
            # don't kill agent, just tray
            sys.exit(0)

        def do_open_dashboard(icon, item):
            webbrowser.open(f"http://127.0.0.1:{settings.port}/dashboard")

        menu = pystray.Menu(
            pystray.MenuItem("Status…", show_status, default=True),
            pystray.MenuItem("Open Dashboard", do_open_dashboard),
            pystray.MenuItem("Re-login…", do_relogin),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit Tray (agent keeps running)", do_quit),
        )
        icon = pystray.Icon("TimesheetAgent", create_image(), APP_TITLE, menu)
        # run in background thread, also show window on first run if not configured
        if not has_secure_config():
            threading.Thread(target=lambda: StatusWindow().run(), daemon=True).start()
        icon.run()
        return True
    except Exception as e:
        print(f"Tray not available ({e}), falling back to window")
        return False

def main():
    if "--tray" in sys.argv or "--hidden" not in sys.argv:
        # try tray first, if fails show window
        if not try_tray():
            StatusWindow().run()
    else:
        StatusWindow().run()

if __name__ == "__main__":
    main()
