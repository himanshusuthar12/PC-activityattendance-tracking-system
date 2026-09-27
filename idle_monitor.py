import ctypes
import logging
import threading
import time
from datetime import datetime, timezone

from config import settings
from db import insert_idle

log = logging.getLogger("idle")

class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

def get_idle_seconds() -> float:
    if not hasattr(ctypes, "windll"):
        return 0.0
    try:
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        try:
            tick = ctypes.windll.kernel32.GetTickCount64()
            millis = (tick - info.dwTime) & 0xFFFFFFFF
            if millis > 86400000 * 2:
                raise ValueError("overflow")
        except Exception:
            millis = ctypes.windll.kernel32.GetTickCount() - info.dwTime
            if millis < 0:
                millis += 2**32
        return millis / 1000.0
    except Exception:
        return 0.0

class IdleMonitor:
    def __init__(self, user_id: int):
        self.user_id = int(user_id)
        self.running = False
        self.thread = None
        self.idle_start: datetime | None = None

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, name="idle-monitor", daemon=True)
        self.thread.start()
        log.info("Idle monitor started (threshold=%ss)", settings.idle_after_seconds)

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=3)

    def _run(self):
        while self.running:
            try:
                idle_sec = get_idle_seconds()
                is_idle = idle_sec >= settings.idle_after_seconds

                if is_idle and self.idle_start is None:
                    # Just went idle - record start time (now - idle_sec)
                    self.idle_start = datetime.now(timezone.utc)
                    # adjust to actual idle begin time
                    log.info("Idle started at %s (idle %.1fs)", self.idle_start.isoformat(), idle_sec)

                elif not is_idle and self.idle_start is not None:
                    # Just became active - compute duration and store
                    now = datetime.now(timezone.utc)
                    duration = (now - self.idle_start).total_seconds()
                    # duration approx equals idle_sec before movement, use measured
                    idle_at = self.idle_start
                    secs = int(round(duration))
                    if secs >= settings.idle_after_seconds:
                        try:
                            insert_idle(self.user_id, idle_at, secs)
                            log.info("Idle recorded user_id=%s at=%s duration=%s (%s)", self.user_id, idle_at.strftime("%d-%m-%Y %H:%M"), secs, f"{secs//60}:{secs%60:02d}")
                        except Exception as e:
                            log.error("idle insert failed: %s", e)
                    self.idle_start = None

            except Exception as e:
                log.exception("idle monitor error: %s", e)

            for _ in range(int(settings.idle_poll_seconds * 10)):
                if not self.running:
                    break
                time.sleep(0.1)
