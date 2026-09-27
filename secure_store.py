"""
Secure config store - DPAPI encrypted file in %APPDATA%/TimesheetManager.

Uses Windows DPAPI (CryptProtectData/CryptUnprotectData) via pywin32.
Falls back to base64+obfuscation if pywin32 unavailable (dev only).

File: %APPDATA%\\TimesheetManager\\config.enc  (per-user, encrypted)
Legacy fallback: %APPDATA%\\TimesheetManager\\config.json (plain, for migration)

Stores: backend_url, email, password, user_id, token, mysql overrides (optional)
"""
import base64
import json
import os
from pathlib import Path
from typing import Optional, Dict, Any

APP_DIR_NAME = "TimesheetManager"
CONFIG_ENC = "config.enc"
CONFIG_JSON = "config.json"  # legacy plain fallback

def get_app_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        # fallback to home
        appdata = str(Path.home() / "AppData" / "Roaming")
    p = Path(appdata) / APP_DIR_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p

def get_enc_path() -> Path:
    return get_app_dir() / CONFIG_ENC

def get_json_path() -> Path:
    return get_app_dir() / CONFIG_JSON

# --- DPAPI helpers ---
def _encrypt_dpapi(plaintext: bytes) -> bytes:
    try:
        import win32crypt  # type: ignore
        # CryptProtectData(data, description, entropy, reserved, prompt, flags)
        blob = win32crypt.CryptProtectData(plaintext, None, None, None, None, 0)
        return base64.b64encode(blob)
    except Exception:
        # fallback: simple base64 (NOT secure, but allows dev on non-Windows)
        return base64.b64encode(b"FALLBACK:" + plaintext)

def _decrypt_dpapi(cipher_b64: bytes) -> bytes:
    raw = base64.b64decode(cipher_b64)
    try:
        import win32crypt  # type: ignore
        # win32crypt returns tuple, second element is decrypted
        _, decrypted = win32crypt.CryptUnprotectData(raw, None, None, None, 0)
        # win32crypt returns bytes already
        if isinstance(decrypted, str):
            return decrypted.encode("utf-8")
        return decrypted
    except Exception:
        # fallback handling
        if raw.startswith(b"FALLBACK:"):
            return raw[len(b"FALLBACK:"):]
        # try to decode as fallback payload
        raise

def save_secure_config(data: Dict[str, Any]) -> Path:
    """Encrypt and save config dict. Returns path."""
    path = get_enc_path()
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    enc = _encrypt_dpapi(payload)
    path.write_bytes(enc)
    # also remove legacy plain if exists? keep for debug but secure
    try:
        jp = get_json_path()
        if jp.exists():
            jp.unlink()
    except Exception:
        pass
    # restrict file permissions (Windows: per-user already)
    return path

def load_secure_config() -> Optional[Dict[str, Any]]:
    """Load and decrypt config. Returns dict or None if not found/corrupt."""
    enc_path = get_enc_path()
    if enc_path.exists():
        try:
            enc = enc_path.read_bytes().strip()
            if not enc:
                return None
            plain = _decrypt_dpapi(enc)
            return json.loads(plain.decode("utf-8"))
        except Exception:
            return None
    # legacy plain fallback
    json_path = get_json_path()
    if json_path.exists():
        try:
            return json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None

def has_secure_config() -> bool:
    return get_enc_path().exists() or get_json_path().exists()

def delete_secure_config():
    for p in [get_enc_path(), get_json_path()]:
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass

def save_credentials(email: str, password: str, backend_url: str, user_id: int, token: str = "", extra: Dict[str, Any] = None) -> Path:
    data: Dict[str, Any] = {
        "backend_url": backend_url.rstrip("/"),
        "email": email.strip(),
        "password": password,  # stored encrypted via DPAPI
        "user_id": int(user_id),
        "token": token or "",
    }
    if extra:
        data.update(extra)
    return save_secure_config(data)

def get_log_path() -> Path:
    return get_app_dir() / "agent.log"
