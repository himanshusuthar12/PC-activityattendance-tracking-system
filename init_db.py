"""Initialize timesheet_db - single table activity_states (MySQL 127.0.0.1:3306)."""
import logging
from config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("init_db")

from db import ensure_schema, test_connection, get_mysql_connection

if __name__ == "__main__":
    print(f"Testing MySQL {settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}...")
    if not test_connection():
        print("FAILED: Cannot connect to MySQL. Check:")
        print("  - XAMPP/MySQL is running")
        print("  - phpMyAdmin http://localhost/phpmyadmin/index.php?route=/sql&db=timesheet_db")
        print(f"  - DB {settings.mysql_database} exists (create manually if needed)")
        print(f"  - User {settings.mysql_user} @{settings.mysql_host}")
        raise SystemExit(1)
    print("MySQL Connected OK.")

    print("Ensuring single table activity_states...")
    ensure_schema()
    print("Done. Checking table...")

    conn = get_mysql_connection()
    cur = conn.cursor()
    cur.execute("SHOW TABLES LIKE 'activity_states'")
    print("  activity_states exists:", bool(cur.fetchone()))
    cur.execute("DESCRIBE activity_states")
    for row in cur.fetchall():
        print("   ", row)
    # List dropped tables check
    cur.execute("SHOW TABLES")
    print("  All tables in DB:", [r[0] for r in cur.fetchall()])
    conn.close()
    print("Ready. http://localhost/phpmyadmin/index.php?route=/sql&db=timesheet_db&table=activity_states")
