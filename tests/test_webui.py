import json
import os
import sys
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "travelserver"))

import status
import webui


class WebUiConfig:
    led_enabled = False
    webui_enabled = True
    webui_bind = "127.0.0.1"
    webui_port = 0  # ephemeral


def get(url):
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.status, resp.read().decode(), dict(resp.headers)


def get_json(url):
    code, body, headers = get(url)
    return code, json.loads(body)


class WebUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = webui.start(WebUiConfig())
        cls.port = cls.server.server_address[1]
        cls.base = "http://127.0.0.1:%d" % cls.port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        s = status.STATUS
        with s._lock:
            s.state = "idle"
            s.source = None
            s.source_kind = None
            s.files_total = 0
            s.files_done = 0
            s.files_copied = 0
            s.files_skipped = 0
            s.files_failed = 0
            s.files_unverified = 0
            s.current_file = None
            s.started_at = None
            s.finished_at = None
            s.last_error = None
            s.last_result = None
            s.disks = []
            s.led_pattern = "off"
            s.log.clear()

    def test_index_served(self):
        code, body, headers = get(self.base + "/")
        self.assertEqual(code, 200)
        self.assertIn("TravelServer", body)
        self.assertTrue(headers.get("Content-Type", "").startswith("text/html"))

    def test_css_percent_escaping(self):
        # regression: PAGE used to contain a literal '%%' (python %-format
        # escape inside a plain string), which breaks the progress bar CSS.
        self.assertNotIn("%%", webui.PAGE)
        self.assertIn("width: 0%", webui.PAGE)

    def test_status_json_shape(self):
        status.STATUS.reset("/mnt/card", "card", 3)
        code, data = get_json(self.base + "/api/status.json")
        self.assertEqual(code, 200)
        for key in ("state", "state_label", "source", "source_kind", "files_total",
                    "files_done", "files_copied", "files_skipped", "files_failed",
                    "files_unverified", "current_file", "elapsed_seconds",
                    "last_error", "last_result", "disks", "led_pattern", "log_tail"):
            self.assertIn(key, data)
        self.assertEqual(data["state"], "backup")
        self.assertEqual(data["source"], "/mnt/card")
        self.assertEqual(data["source_kind"], "card")
        self.assertEqual(data["files_total"], 3)

    def test_status_transitions_through_pipeline(self):
        # backup
        status.STATUS.reset("/mnt/card", "card", 2)
        status.STATUS.progress("a.jpg", copied=1)
        status.STATUS.progress("b.jpg", skipped=1)
        _, data = get_json(self.base + "/api/status.json")
        self.assertEqual(data["state"], "backup")
        self.assertEqual(data["files_done"], 2)
        self.assertEqual(data["files_copied"], 1)
        self.assertEqual(data["files_skipped"], 1)
        self.assertEqual(data["current_file"], "b.jpg")

        # verify
        status.STATUS.set_verify()
        status.STATUS.set_unverified(1)
        _, data = get_json(self.base + "/api/status.json")
        self.assertEqual(data["state"], "verify")
        self.assertEqual(data["files_unverified"], 1)

        # done
        status.STATUS.set_state("done")
        _, data = get_json(self.base + "/api/status.json")
        self.assertEqual(data["state"], "done")
        self.assertIn("safe to erase", data["state_label"])
        self.assertIsNone(data["current_file"])

        # error
        status.STATUS.set_error("SSD with label TRAVEL1 not found")
        _, data = get_json(self.base + "/api/status.json")
        self.assertEqual(data["state"], "error")
        self.assertEqual(data["last_error"], "SSD with label TRAVEL1 not found")

    def test_disks_reflected(self):
        status.STATUS.set_disks([{"label": "TRAVEL1", "present": True,
                                  "mountpoint": "/mnt/travelserver/sda1",
                                  "size": "931.5 GB", "free": "512.0 GB"},
                                 {"label": "TRAVEL2", "present": False,
                                  "mountpoint": None, "size": None, "free": None}])
        _, data = get_json(self.base + "/api/status.json")
        self.assertEqual(len(data["disks"]), 2)
        self.assertTrue(data["disks"][0]["present"])
        self.assertFalse(data["disks"][1]["present"])

    def test_log_ring_and_led(self):
        status.STATUS.add_log("hello dashboard")
        status.STATUS.set_led("backup")
        _, data = get_json(self.base + "/api/status.json")
        self.assertTrue(any("hello dashboard" in line for line in data["log_tail"]))
        self.assertEqual(data["led_pattern"], "backup")

    def test_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            get(self.base + "/nope")
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
