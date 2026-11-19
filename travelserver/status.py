import collections
import datetime
import json
import threading
import time

STATE_LABELS = {
    "idle": "Idle - waiting for a device",
    "backup": "Backing up",
    "verify": "Verifying",
    "done": "Backup complete - source safe to erase",
    "error": "Error - backup incomplete",
}


class Status:
    def __init__(self):
        self._lock = threading.Lock()
        self.state = "idle"
        self.source = None
        self.source_kind = None
        self.files_total = 0
        self.files_done = 0
        self.files_copied = 0
        self.files_skipped = 0
        self.files_failed = 0
        self.files_unverified = 0
        self.current_file = None
        self.started_at = None
        self.finished_at = None
        self.last_error = None
        self.last_result = None
        self.disks = []
        self.led_pattern = "off"
        self.log = collections.deque(maxlen=200)

    def reset(self, source, source_kind, files_total):
        with self._lock:
            self.state = "backup"
            self.source = source
            self.source_kind = source_kind
            self.files_total = files_total
            self.files_done = 0
            self.files_copied = 0
            self.files_skipped = 0
            self.files_failed = 0
            self.files_unverified = 0
            self.current_file = None
            self.started_at = time.time()
            self.finished_at = None
            self.last_result = None

    def progress(self, current_file, copied=0, skipped=0, failed=0):
        with self._lock:
            self.files_done += 1
            self.current_file = current_file
            self.files_copied += copied
            self.files_skipped += skipped
            self.files_failed += failed

    def set_state(self, state, source=None, source_kind=None):
        with self._lock:
            self.state = state
            if source is not None:
                self.source = source
            if source_kind is not None:
                self.source_kind = source_kind
            if state in ("done", "error"):
                self.finished_at = time.time()
                self.current_file = None

    def set_verify(self):
        with self._lock:
            self.state = "verify"

    def set_unverified(self, count):
        with self._lock:
            self.files_unverified = count

    def set_result(self, result):
        with self._lock:
            self.last_result = result

    def set_error(self, message):
        with self._lock:
            self.last_error = message
            self.state = "error"
            self.finished_at = time.time()

    def set_disks(self, disks):
        with self._lock:
            self.disks = disks

    def set_led(self, pattern):
        with self._lock:
            self.led_pattern = pattern

    def add_log(self, message):
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        with self._lock:
            self.log.append("[%s] %s" % (stamp, message))

    def log_tail(self, count=50):
        with self._lock:
            return list(self.log)[-count:]

    def to_dict(self):
        with self._lock:
            elapsed = None
            if self.started_at:
                end = self.finished_at or time.time()
                elapsed = round(end - self.started_at, 1)
            return {
                "state": self.state,
                "state_label": STATE_LABELS.get(self.state, self.state),
                "source": self.source,
                "source_kind": self.source_kind,
                "files_total": self.files_total,
                "files_done": self.files_done,
                "files_copied": self.files_copied,
                "files_skipped": self.files_skipped,
                "files_failed": self.files_failed,
                "files_unverified": self.files_unverified,
                "current_file": self.current_file,
                "started_at": self.started_at,
                "elapsed_seconds": elapsed,
                "last_error": self.last_error,
                "last_result": self.last_result,
                "disks": list(self.disks),
                "led_pattern": self.led_pattern,
                "log_tail": list(self.log)[-30:],
            }

    def json(self):
        return json.dumps(self.to_dict(), indent=2)


STATUS = Status()
