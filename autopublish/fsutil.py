import logging
import time

log = logging.getLogger(__name__)


def safe_rglob(path, pattern, retries=5, delay=0.2):
    """path.rglob(pattern) that survives EINTR on synced/watched containers.

    The iA Writer container directory is iCloud-synced, and scandir() on it
    occasionally raises InterruptedError: [Errno 4] mid-walk when a signal
    interrupts the syscall. rglob() is a generator — once it raises, that
    generator is dead, so a caught exception can't just resume iteration; the
    whole walk has to restart. Returns a materialized list so a retry always
    starts a fresh walk rather than replaying a partially-consumed generator.
    """
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            return list(path.rglob(pattern))
        except InterruptedError as e:
            last_error = e
            log.warning("Interrupted scanning %s (attempt %d/%d): %s", path, attempt, retries, e)
            time.sleep(delay)
    raise last_error
