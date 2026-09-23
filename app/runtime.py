"""Small single-process operational health surface; never a distributed heartbeat."""

import time
import threading

workers = {}
lock = threading.Lock()


def mark(name, phase="idle"):
    with lock:
        workers[name] = dict(at=time.monotonic(), phase=phase)


def snapshot():
    with lock:
        return {
            name: dict(
                age_seconds=round(time.monotonic() - v["at"], 1), phase=v["phase"]
            )
            for name, v in workers.items()
        }
