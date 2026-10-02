import asyncio
import os
import time
from clients.bots.handlers.base import BaseHandler
from clients.bots.qq.settings import (
    BOTS_DIR,
    MASTER_QQ_ID,
    SESSION_IDLE_SECONDS,
    TEMP_IMAGES_MAX_FILES,
    TEMP_IMAGES_TTL_SECONDS,
)

class LifecycleHandler(BaseHandler):
    """
    Handles lifecycle events, cleanup tasks, and session management.
    """

    def get_temp_images_dir(self) -> str:
        return os.path.join(BOTS_DIR, "temp_images")

    def cleanup_temp_images(self):
        try:
            temp_dir = self.get_temp_images_dir()
            if not os.path.isdir(temp_dir):
                return

            now = time.time()
            ttl = max(60, int(TEMP_IMAGES_TTL_SECONDS))
            max_files = max(50, int(TEMP_IMAGES_MAX_FILES))

            files = []
            for name in os.listdir(temp_dir):
                p = os.path.join(temp_dir, name)
                if not os.path.isfile(p):
                    continue
                try:
                    st = os.stat(p)
                    files.append((p, float(st.st_mtime)))
                except Exception:
                    continue

            expired = [p for (p, mtime) in files if (now - mtime) > ttl]
            for p in expired:
                try:
                    os.remove(p)
                except Exception:
                    pass

            files = [(p, mtime) for (p, mtime) in files if os.path.exists(p)]
            if len(files) <= max_files:
                return
            files.sort(key=lambda it: it[1])
            for p, _ in files[: max(0, len(files) - max_files)]:
                try:
                    os.remove(p)
                except Exception:
                    pass
        except Exception:
            return

    async def cleanup_loop(self):
        while self.adapter.running:
            self.cleanup_temp_images()
            self.cleanup_idle_sessions()
            await asyncio.sleep(10 * 60)

    def cleanup_idle_sessions(self):
        try:
            now = time.time()
            idle_s = max(60, int(SESSION_IDLE_SECONDS))
            to_stop = []

            mid = str(MASTER_QQ_ID or "").strip()
            master_sid = "default_user" if mid else ""

            for sid, sess in list(self.adapter.sessions.items()):
                try:
                    if master_sid and sid == master_sid:
                        continue
                    if not getattr(sess, "running", False):
                        to_stop.append(sess)
                        continue
                    last = float(getattr(sess, "last_activity", 0.0) or 0.0)
                    if last > 0 and (now - last) > idle_s:
                        to_stop.append(sess)
                except Exception:
                    continue

            for sess in to_stop:
                try:
                    asyncio.create_task(sess.stop())
                except Exception:
                    pass
        except Exception:
            return
