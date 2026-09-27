"""MySQL only - single table activity_states for timesheet_db (127.0.0.1:3306)."""
import logging
from datetime import datetime, timezone
from typing import Optional

from config import settings

log = logging.getLogger("db")

def get_mysql_connection():
    import pymysql
    conn = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_database,
        autocommit=False,
        connect_timeout=5,
    )
    log.info("MySQL connected at %s:%s/%s", settings.mysql_host, settings.mysql_port, settings.mysql_database)
    return conn

def ensure_schema():
    """Create single table activity_states if not exists."""
    conn = get_mysql_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS activity_states (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                status ENUM('start','off','idle') NOT NULL,
                start_time DATETIME NULL,
                end_time DATETIME NULL,
                idle_at DATETIME NULL,
                idle_duration_seconds INT NULL,
                idle_duration_display VARCHAR(20) NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_user (user_id),
                INDEX idx_status (status),
                INDEX idx_idle_at (idle_at)
            )
        """)
        conn.commit()
        log.info("Schema ensured: activity_states (single table)")

        # Drop unwanted tables if they exist from previous version
        for tbl in ["Computers","Sessions","Events","ForegroundApps","Heartbeats","ActivityStates"]:
            try:
                cur.execute(f"DROP TABLE IF EXISTS {tbl}")
            except Exception as e:
                log.debug("drop %s skipped: %s", tbl, e)
        # Also drop lower variations
        for tbl in ["activitystates","activitystates_old"]:
            try:
                cur.execute(f"DROP TABLE IF EXISTS {tbl}")
            except Exception:
                pass
        conn.commit()
    finally:
        conn.close()

def _format_duration(seconds: int) -> str:
    m = seconds // 60
    s = seconds % 60
    return f"{m}:{s:02d}"

def insert_start(user_id: int) -> Optional[int]:
    conn = get_mysql_connection()
    try:
        cur = conn.cursor()
        now = datetime.now(timezone.utc).astimezone().replace(tzinfo=None)
        cur.execute(
            "INSERT INTO activity_states (user_id, status, start_time) VALUES (%s,'start',%s)",
            (int(user_id), now),
        )
        conn.commit()
        eid = cur.lastrowid
        log.info("Inserted start user_id=%s id=%s", user_id, eid)
        return eid
    finally:
        conn.close()

def insert_off(user_id: int) -> Optional[int]:
    conn = get_mysql_connection()
    try:
        cur = conn.cursor()
        now = datetime.now(timezone.utc).astimezone().replace(tzinfo=None)
        cur.execute(
            "INSERT INTO activity_states (user_id, status, end_time) VALUES (%s,'off',%s)",
            (int(user_id), now),
        )
        conn.commit()
        eid = cur.lastrowid
        log.info("Inserted off user_id=%s id=%s", user_id, eid)
        return eid
    finally:
        conn.close()

def insert_idle(user_id: int, idle_at: datetime, idle_duration_seconds: int) -> Optional[int]:
    conn = get_mysql_connection()
    try:
        cur = conn.cursor()
        disp = _format_duration(int(idle_duration_seconds))
        # idle_at is aware datetime; store naive local
        at_naive = idle_at.astimezone().replace(tzinfo=None) if idle_at.tzinfo else idle_at
        cur.execute(
            "INSERT INTO activity_states (user_id, status, idle_at, idle_duration_seconds, idle_duration_display) VALUES (%s,'idle',%s,%s,%s)",
            (int(user_id), at_naive, int(idle_duration_seconds), disp),
        )
        conn.commit()
        eid = cur.lastrowid
        log.info("Inserted idle user_id=%s at=%s duration=%s (%s) id=%s", user_id, at_naive, idle_duration_seconds, disp, eid)
        return eid
    finally:
        conn.close()

def test_connection() -> bool:
    try:
        conn = get_mysql_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        conn.close()
        return True
    except Exception as e:
        log.error("MySQL test failed: %s", e)
        return False

# Compatibility wrappers for server
def fetch_activity_states(limit=50, user_id=None, status=None):
    conn = get_mysql_connection()
    try:
        cur = conn.cursor()
        sql = "SELECT id, user_id, status, start_time, end_time, idle_at, idle_duration_seconds, idle_duration_display, created_at FROM activity_states"
        params = []
        where = []
        if user_id is not None:
            where.append("user_id=%s")
            params.append(user_id)
        if status:
            where.append("status=%s")
            params.append(status)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT %s"
        params.append(limit)
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        conn.close()
