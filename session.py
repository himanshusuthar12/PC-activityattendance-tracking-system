import logging
from db import insert_start, insert_off

log = logging.getLogger("session")

class SessionTracker:
    def __init__(self, user_id: int):
        self.user_id = int(user_id)

    def start(self):
        try:
            insert_start(self.user_id)
            log.info("Session start recorded user_id=%s", self.user_id)
        except Exception as e:
            log.error("start insert failed: %s", e)

    def stop(self):
        try:
            insert_off(self.user_id)
            log.info("Session off recorded user_id=%s", self.user_id)
        except Exception as e:
            log.error("off insert failed: %s", e)
