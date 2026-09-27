"""
Onboarding UI - asks Username + Password at install / first run.

- Validates against C# backend via backend_auth.validate_backend_credentials
- Saves encrypted config via secure_store (DPAPI)
- Can run as: python onboarding.py  OR  TimesheetAgent.exe --onboarding
- Returns exit 0 on success, 2 on cancel/fail

Used by:
  - Installer post-install step (Inno Setup [Run] -> onboarding.exe)
  - main.py first-run fallback (if no secure config and no .env)
  - tray_app "Re-login" button
"""
import sys
import tkinter as tk
from tkinter import messagebox

from config import settings
from secure_store import load_secure_config, save_credentials, get_app_dir

APP_TITLE = "TimesheetManager — Sign in"

def validate_and_save(email: str, password: str, backend_url: str):
    from backend_auth import validate_backend_credentials
    auth = validate_backend_credentials(email=email, password=password, backend_url=backend_url)
    # save encrypted
    save_credentials(
        email=auth["email"],
        password=password,  # keep original password encrypted
        backend_url=backend_url,
        user_id=auth["user_id"],
        token=auth.get("token", ""),
        extra={"user": auth.get("user", {})},
    )
    # reload settings so main.py picks it up without restart
    try:
        settings.reload_secure()
    except Exception:
        pass
    return auth


def run_cli() -> int:
    """Fallback CLI if tkinter unavailable."""
    print("=== TimesheetManager Setup ===")
    print(f"Backend: {settings.backend_base_url}")
    backend_url = input(f"Backend URL [{settings.backend_base_url}]: ").strip() or settings.backend_base_url
    email = input("Email / Username: ").strip()
    import getpass
    password = getpass.getpass("Password: ")
    if not email or not password:
        print("Email and password required.")
        return 2
    try:
        auth = validate_and_save(email, password, backend_url)
        print(f"✓ Validated user_id={auth['user_id']} ({auth['email']})")
        print(f"✓ Saved encrypted config to {get_app_dir()}")
        return 0
    except Exception as e:
        print(f"✗ Failed: {e}")
        return 2


def run_gui() -> int:
    existing = load_secure_config() or {}
    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry("440x380")
    root.resizable(False, False)
    root.configure(bg="#0f172a")

    # center
    try:
        root.eval('tk::PlaceWindow . center')
    except Exception:
        pass

    result = {"code": 2}

    outer = tk.Frame(root, bg="#0f172a", padx=20, pady=18)
    outer.pack(fill="both", expand=True)

    tk.Label(outer, text="Sign in to TimesheetManager", font=("Segoe UI", 14, "bold"), bg="#0f172a", fg="#f8fafc").pack(anchor="w")
    tk.Label(outer, text="Enter your C# HRMS credentials. They will be validated\nagainst the backend and saved securely (DPAPI).", font=("Segoe UI", 8), bg="#0f172a", fg="#94a3b8", justify="left").pack(anchor="w", pady=(4, 14))

    card = tk.Frame(outer, bg="#1e293b", highlightbackground="#334155", highlightthickness=1, padx=16, pady=16)
    card.pack(fill="x")

    def add_row(label, var, show=None):
        tk.Label(card, text=label, font=("Segoe UI", 8), bg="#1e293b", fg="#cbd5e1").pack(anchor="w", pady=(8 if label != "Backend URL" else 0, 2))
        ent = tk.Entry(card, textvariable=var, font=("Segoe UI", 10), bg="#0f172a", fg="#f1f5f9", insertbackground="#f1f5f9", relief="flat", highlightthickness=1, highlightbackground="#334155", highlightcolor="#38bdf8", show=show)
        ent.pack(fill="x", ipady=6, padx=1)
        return ent

    backend_var = tk.StringVar(value=existing.get("backend_url") or settings.backend_base_url)
    email_var = tk.StringVar(value=existing.get("email") or settings.backend_user)
    pass_var = tk.StringVar(value="")  # never prefill password

    e_backend = add_row("Backend URL", backend_var)
    e_email = add_row("Email / Username", email_var)
    e_pass = add_row("Password", pass_var, show="•")

    if email_var.get():
        e_pass.focus()
    else:
        e_email.focus()

    status_var = tk.StringVar(value="")
    status_lbl = tk.Label(outer, textvariable=status_var, font=("Segoe UI", 8), bg="#0f172a", fg="#f87171", wraplength=400, justify="left")
    status_lbl.pack(anchor="w", pady=(10, 0))

    def set_status(msg, ok=False):
        status_var.set(msg)
        status_lbl.configure(fg="#4ade80" if ok else "#f87171")

    btn_frame = tk.Frame(outer, bg="#0f172a")
    btn_frame.pack(fill="x", pady=(14, 0))

    def on_cancel():
        result["code"] = 2
        root.destroy()

    def on_signin():
        email = email_var.get().strip()
        password = pass_var.get()
        backend_url = backend_var.get().strip().rstrip("/") or settings.backend_base_url
        if not email or not password:
            set_status("Email and password are required.")
            return
        if not backend_url.startswith("http"):
            set_status("Backend URL must start with http:// or https://")
            return
        btn_signin.configure(state="disabled", text="Validating…")
        status_var.set("")
        root.update_idletasks()

        def do_validate():
            try:
                auth = validate_and_save(email, password, backend_url)
                set_status(f"✓ Logged in as {auth['email']} (user_id={auth['user_id']}) — saved securely.", ok=True)
                root.update()
                messagebox.showinfo("Success", f"Validated {auth['email']} (user_id={auth['user_id']})\n\nTracking will start automatically on boot.\nYou can close this window.")
                result["code"] = 0
                root.after(600, root.destroy)
            except Exception as e:
                set_status(f"✗ {e}")
                btn_signin.configure(state="normal", text="Sign in & Save")
            else:
                btn_signin.configure(state="normal", text="Sign in & Save")

        root.after(50, do_validate)

    btn_signin = tk.Button(btn_frame, text="Sign in & Save", command=on_signin, bg="#38bdf8", fg="#0f172a", activebackground="#0ea5e9", font=("Segoe UI", 9, "bold"), relief="flat", padx=16, pady=8, cursor="hand2")
    btn_signin.pack(side="right")

    btn_cancel = tk.Button(btn_frame, text="Cancel", command=on_cancel, bg="#1e293b", fg="#cbd5e1", activebackground="#334155", font=("Segoe UI", 9), relief="flat", padx=12, pady=8, cursor="hand2", highlightthickness=1, highlightbackground="#334155")
    btn_cancel.pack(side="right", padx=(0, 8))

    # Enter handling
    def on_enter(e):
        on_signin()
    e_pass.bind("<Return>", on_enter)
    e_email.bind("<Return>", lambda e: e_pass.focus())
    e_backend.bind("<Return>", lambda e: e_email.focus())

    # footer
    tk.Label(outer, text=f"Config: {get_app_dir()}\\config.enc  (DPAPI encrypted, per-user)", font=("Segoe UI", 7), bg="#0f172a", fg="#64748b").pack(anchor="w", pady=(12, 0))

    root.protocol("WM_DELETE_WINDOW", on_cancel)
    root.mainloop()
    return result["code"]


def main() -> int:
    # if --help
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Usage: python onboarding.py [--cli]")
        print("  --cli   force CLI mode (no GUI)")
        return 0
    force_cli = "--cli" in sys.argv
    if force_cli:
        return run_cli()
    try:
        # try GUI
        return run_gui()
    except Exception as e:
        print(f"GUI failed ({e}), falling back to CLI")
        return run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
