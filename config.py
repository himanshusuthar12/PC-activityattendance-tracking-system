import os
import socket
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
    # load .env from app dir + current dir (installer uses exe dir)
    for p in [Path.cwd() / ".env", Path(__file__).parent / ".env"]:
        if p.exists():
            load_dotenv(dotenv_path=p, override=False)
    load_dotenv(override=False)
except ImportError:
    pass

def env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}

def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except (ValueError, AttributeError):
        return default

def _first_env(*names: str, default: str = "") -> str:
    for n in names:
        v = os.getenv(n)
        if v and v.strip():
            return v.strip()
    return default

def _load_secure_store() -> dict:
    """Try DPAPI secure store (%APPDATA%\\TimesheetManager\\config.enc)."""
    try:
        from secure_store import load_secure_config
        data = load_secure_config()
        if data:
            return data
    except Exception:
        pass
    return {}

_SECURE = _load_secure_store()

def _secure_or_env(secure_key: str, *env_names: str, default: str = "") -> str:
    # secure store takes precedence (installer saved it)
    if secure_key in _SECURE and str(_SECURE[secure_key]).strip():
        return str(_SECURE[secure_key]).strip()
    return _first_env(*env_names, default=default)

@dataclass(frozen=True)
class Settings:
    backend_base_url: str = field(default_factory=lambda: _secure_or_env("backend_url", "BACKEND_BASE_URL", default="http://127.0.0.1:5000").rstrip("/"))
    backend_user: str = field(default_factory=lambda: _secure_or_env("email", "USERID", "BACKEND_EMAIL", "BACKEND_USER", "USER_EMAIL", "EMAIL"))
    backend_password: str = field(default_factory=lambda: _secure_or_env("password", "PASSWORD", "BACKEND_PASSWORD", "USER_PASSWORD"))

    # MySQL (phpMyAdmin timesheet_db) - only DB used
    mysql_host: str = field(default_factory=lambda: _first_env("MYSQL_HOST", default="127.0.0.1"))
    mysql_port: int = field(default_factory=lambda: env_int("MYSQL_PORT", 3306))
    mysql_user: str = field(default_factory=lambda: _first_env("MYSQL_USER", default="root"))
    mysql_password: str = field(default_factory=lambda: _first_env("MYSQL_PASSWORD", default=""))
    mysql_database: str = field(default_factory=lambda: _first_env("MYSQL_DATABASE", default="timesheet_db"))

    # Tracking - only idle after 30 sec
    idle_poll_seconds: int = field(default_factory=lambda: env_int("IDLE_POLL_SECONDS", 5))
    idle_after_seconds: int = field(default_factory=lambda: env_int("IDLE_AFTER_SECONDS", 30))

    log_level: str = field(default_factory=lambda: _first_env("LOG_LEVEL", default="INFO"))
    port: int = field(default_factory=lambda: env_int("PORT", 8000))
    computer_name: str = field(default_factory=lambda: socket.gethostname())

    # Secure store meta
    secure_user_id: int = field(default_factory=lambda: int(_SECURE.get("user_id", 0) or 0) if str(_SECURE.get("user_id", "")).strip().isdigit() else 0)

    def is_secure_configured(self) -> bool:
        return bool(_SECURE.get("email") and _SECURE.get("password") and _SECURE.get("backend_url"))

    def validate(self) -> None:
        missing = []
        if not self.backend_user:
            missing.append("USERID")
        if not self.backend_password:
            missing.append("PASSWORD")
        if not self.backend_base_url:
            missing.append("BACKEND_BASE_URL")
        if missing:
            raise ValueError(f"Missing required values: {', '.join(missing)} (set via installer/onboarding or .env)")

    def reload_secure(self):
        """Re-read secure store (call after onboarding saves)."""
        global _SECURE
        _SECURE = _load_secure_store()
        # dataclass is frozen, so mutate via object.__setattr__
        object.__setattr__(self, "backend_base_url", _secure_or_env("backend_url", "BACKEND_BASE_URL", default="http://127.0.0.1:5000").rstrip("/"))
        object.__setattr__(self, "backend_user", _secure_or_env("email", "USERID", "BACKEND_EMAIL", "BACKEND_USER", "USER_EMAIL", "EMAIL"))
        object.__setattr__(self, "backend_password", _secure_or_env("password", "PASSWORD", "BACKEND_PASSWORD", "USER_PASSWORD"))
        try:
            object.__setattr__(self, "secure_user_id", int(_SECURE.get("user_id", 0) or 0))
        except Exception:
            object.__setattr__(self, "secure_user_id", 0)

settings = Settings()
