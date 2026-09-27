"""Read-only viewer for single table activity_states (MySQL timesheet_db)."""
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from config import settings
from db import get_mysql_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("server")

app = FastAPI(title="Timesheet Viewer - activity_states", version="3.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

class LoginIn(BaseModel):
    email: str
    password: str

@app.post("/api/auth/login")
def proxy_login(body: LoginIn):
    url = settings.backend_base_url.rstrip("/") + "/api/auth/login"
    try:
        resp = requests.post(url, json={"email": body.email.strip(), "password": body.password}, timeout=10)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Backend not reachable: {e}")
    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not resp.ok:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    data = resp.json()
    token = data.get("token") or data.get("Token") or ""
    user = data.get("user") or data.get("User") or {}
    user_id = user.get("id") or user.get("Id") or data.get("user_id")
    if not user_id:
        raise HTTPException(status_code=500, detail=f"missing user.id: {data}")
    return {"status": "success", "token": token, "user": user, "user_id": int(user_id)}

@app.get("/health")
def health():
    db_ok = False
    err = None
    try:
        conn = get_mysql_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM activity_states")
        cur.fetchone()
        conn.close()
        db_ok = True
    except Exception as e:
        err = str(e)[:300]
    try:
        resp = requests.post(settings.backend_base_url.rstrip("/")+"/api/auth/login", json={"email":"healthcheck@test.com","password":"x"}, timeout=4)
        backend_ok = resp.status_code in (401,400,422)
    except Exception:
        backend_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": "connected timesheet_db.activity_states" if db_ok else f"error: {err}", "backend_ok": backend_ok, "backend_url": settings.backend_base_url, "timestamp": datetime.now(timezone.utc).isoformat()}

@app.get("/api/activity")
def list_activity(limit: int = Query(50, ge=1, le=500), user_id: Optional[int] = None, status: Optional[str] = None):
    try:
        conn = get_mysql_connection()
        cur = conn.cursor()
        sql = "SELECT id, user_id, status, start_time, end_time, idle_at, idle_duration_seconds, idle_duration_display, created_at FROM activity_states"
        params = []
        where = []
        if user_id is not None:
            where.append("user_id=%s")
            params.append(user_id)
        if status in ("start","off","idle"):
            where.append("status=%s")
            params.append(status)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT %s"
        params.append(limit)
        cur.execute(sql, params)
        rows = cur.fetchall()
        conn.close()
        out = []
        for r in rows:
            out.append({
                "id": r[0], "user_id": r[1], "status": r[2],
                "start_time": str(r[3]) if r[3] else None,
                "end_time": str(r[4]) if r[4] else None,
                "idle_at": str(r[5]) if r[5] else None,
                "idle_at_display": r[5].strftime("%d-%m-%Y %H:%M") if r[5] else None,
                "idle_duration_seconds": r[6],
                "idle_duration_display": r[7],
                "created_at": str(r[8]),
            })
        return {"mode": "mysql", "data": out}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# keep legacy path for compatibility
@app.get("/api/v1/events")
def legacy_events(limit: int = Query(50, ge=1, le=500), user_id: Optional[int] = None):
    return list_activity(limit, user_id)

LOGIN_HTML = STATIC_DIR / "login.html"
DASHBOARD_HTML = STATIC_DIR / "dashboard.html"
@app.get("/", response_class=HTMLResponse)
def root():
    return FileResponse(str(LOGIN_HTML)) if LOGIN_HTML.exists() else HTMLResponse("<a href='/docs'>docs</a> <a href='/health'>health</a>")
@app.get("/login", response_class=HTMLResponse)
def login_page():
    return FileResponse(str(LOGIN_HTML)) if LOGIN_HTML.exists() else HTMLResponse("login missing")
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return FileResponse(str(DASHBOARD_HTML)) if DASHBOARD_HTML.exists() else HTMLResponse("dashboard missing")
@app.get("/api")
def api_root():
    return {"service": "activity_states viewer", "table": "activity_states", "endpoints": ["/api/activity?user_id=&status=idle|start|off", "/health"]}

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=settings.port, reload=True)
