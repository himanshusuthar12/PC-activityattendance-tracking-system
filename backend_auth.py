"""
Single API: POST {BACKEND_BASE_URL}/api/auth/login with {email, password}
Used only to validate .env USERID/PASSWORD and fetch users.id.
No tracking data is ever sent to backend.
"""
import logging
from typing import Dict, Any

import requests
from config import settings

log = logging.getLogger("backend_auth")

TIMEOUT = 10


def validate_backend_credentials(email: str = None, password: str = None, backend_url: str = None) -> Dict[str, Any]:
    """
    Validate credentials against C# backend.
    Returns {user_id, token, user} on success.
    Raises ValueError / requests.RequestException on failure.
    """
    email = (email or settings.backend_user or "").strip()
    password = password or settings.backend_password or ""
    backend_url = (backend_url or settings.backend_base_url or "").rstrip("/")

    if not email or not password:
        raise ValueError("USERID/PASSWORD not set in .env")
    if not backend_url:
        raise ValueError("BACKEND_BASE_URL not set in .env")

    url = f"{backend_url}/api/auth/login"
    log.info("Validating credentials at %s for %s", url, email)
    try:
        resp = requests.post(url, json={"email": email, "password": password}, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise ConnectionError(f"Backend not reachable at {backend_url}: {e}") from e

    if resp.status_code == 401:
        raise ValueError("Invalid credentials (backend returned 401)")
    if resp.status_code == 404:
        raise ValueError(f"Auth endpoint not found at {url} (404)")
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        detail = resp.text[:500]
        raise ValueError(f"Backend login failed ({resp.status_code}): {detail}") from e

    data = resp.json()
    token = data.get("token") or data.get("Token") or ""
    user = data.get("user") or data.get("User") or {}
    user_id = user.get("id") or user.get("Id") or data.get("user_id") or data.get("userId")
    if not user_id:
        raise ValueError(f"Login response missing user.id: {data}")
    log.info("Backend validation OK: user_id=%s email=%s", user_id, email)
    return {"user_id": int(user_id), "token": token, "user": user, "email": email}
