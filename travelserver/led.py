import subprocess
import threading

PATTERNS = {
    "off": [],
    "idle": [(1.0, 2.0), (0.0, 2.0)],
    "backup": [(1.0, 0.25), (0.0, 0.25)],
    "verify": [(1.0, 0.08), (0.0, 0.08)],
    "done": [(1.0, 0.0)],
    "error": [(1.0, 0.1), (0.0, 0.1), (1.0, 0.1), (0.0, 1.2)],
}


class Led(threading.Thread):
    def __init__(self, cfg):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.enabled = cfg.led_enabled
        self._pattern = "off"
        self._stop = threading.Event()
        self._state_lock = threading.Lock()
        self._gpioset_proc = None

    def run(self):
        while not self._stop.is_set():
            with self._state_lock:
                pattern = PATTERNS[self._pattern]
            for value, duration in pattern:
                self._write_value(value)
                self._stop.wait(duration)
        self._write_value(0)

    def set(self, pattern):
        if pattern not in PATTERNS:
            raise ValueError("unknown LED pattern: %s" % pattern)
        with self._state_lock:
            self._pattern = pattern

    def stop(self):
        self._stop.set()
        self.join(timeout=3)
        self._write_value(0)

    def _write_value(self, value):
        if not self.enabled:
            print("[led] %s" % ("on" if value else "off"))
            return
        proc = getattr(self, "_gpioset_proc", None)
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
            self._gpioset_proc = None
        if not value:
            return
        try:
            self._gpioset_proc = subprocess.Popen(
                ["gpioset", "--mode=signal", self.cfg.led_gpio_chip, "%d=1" % self.cfg.led_gpio_line],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            print("[led] failed to run gpioset; is libgpiod-utils installed?")
            self.enabled = False
