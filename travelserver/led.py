import re
import subprocess
import threading

import status

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
        self._gpioset_major = None

    def _gpioset_command(self):
        """libgpiod v1 (libgpiod-utils, bookworm) and v2 (gpiod, trixie+)
        have different gpioset CLIs, but both hold the line while the
        process runs and release it on exit. Detect the version once."""
        if self._gpioset_major is None:
            self._gpioset_major = 1
            try:
                out = subprocess.run(["gpioset", "--version"],
                                     capture_output=True, text=True, timeout=5)
                first = (out.stdout.strip() or out.stderr.strip()).splitlines()
                m = re.search(r"gpioset\D*(\d+)", first[0]) if first else None
                if m:
                    self._gpioset_major = int(m.group(1))
            except (OSError, subprocess.SubprocessError):
                pass
        line = "%d=1" % self.cfg.led_gpio_line
        if self._gpioset_major >= 2:
            return ["gpioset", "--chip", self.cfg.led_gpio_chip, line]
        return ["gpioset", "--mode=signal", self.cfg.led_gpio_chip, line]

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
        status.STATUS.set_led(pattern)

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
                self._gpioset_command(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            print("[led] failed to run gpioset; is libgpiod-utils/gpiod installed?")
            self.enabled = False
