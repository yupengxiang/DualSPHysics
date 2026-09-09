"""Two process-wide slots for bounded CPU postprocessing."""

from contextlib import contextmanager
import fcntl, time
from scripts.l1r_continuation_evidence import OUT, begin_activity_window


@contextmanager
def cpu_slot():
    begin_activity_window()
    handles = [(OUT / f"cpu-{i}.lock").open("a") for i in range(2)]
    chosen = None
    try:
        while chosen is None:
            for h in handles:
                try:
                    fcntl.flock(h, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    chosen = h
                    break
                except BlockingIOError:
                    pass
            if chosen is None:
                time.sleep(1)
        yield
    finally:
        if chosen:
            fcntl.flock(chosen, fcntl.LOCK_UN)
        for h in handles:
            h.close()
