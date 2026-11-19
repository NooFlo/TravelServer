import datetime
import hashlib
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "travelserver"))

import backup
from index import BackupIndex
from led import Led


class FakeCfg:
    ssd_label_1 = "TRAVEL1"
    ssd_label_2 = "TRAVEL2"
    backup_dir = "BACKUP"
    mount_root = "/tmp/does-not-matter"
    extensions = {"jpg", "mp4"}
    led_enabled = False
    led_gpio_chip = "gpiochip0"
    led_gpio_line = 32
    iphone_mountpoint = "/tmp/does-not-matter"
    poll_interval = 2
    max_sd_card_bytes = 1024 ** 4


class LogCollector:
    def __call__(self, msg):
        self.last = msg


class NullLed:
    def __init__(self):
        self.patterns = []

    def set(self, pattern):
        self.patterns.append(pattern)

    def start(self):
        pass

    def stop(self):
        pass


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


class MirrorBackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.media = os.path.join(self.tmp, "card")
        self.ssd1 = os.path.join(self.tmp, "ssd1", "BACKUP")
        self.ssd2 = os.path.join(self.tmp, "ssd2", "BACKUP")
        os.makedirs(self.media)
        os.makedirs(self.ssd1)
        os.makedirs(self.ssd2)
        self.index = BackupIndex(self.ssd1, self.ssd2)
        self.led = NullLed()
        self.log = LogCollector()
        self.cfg = FakeCfg()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_backup(self):
        b = backup.MirrorBackup.__new__(backup.MirrorBackup)
        b.cfg = self.cfg
        b.index = self.index
        b.led = self.led
        b.log = self.log
        b.targets = [self.ssd1, self.ssd2]
        b.primary = self.ssd1
        b.backup_date = datetime.date.today().isoformat()
        return b

    def test_backup_and_dedupe(self):
        b = self.make_backup()
        src = os.path.join(self.media, "photo1.jpg")
        write_file(src, b"jpegdata1")
        sha, was_new = b.backup_file(src, "test-card")
        self.assertTrue(was_new)
        for target in (self.ssd1, self.ssd2,):
            self.assertTrue(os.path.exists(os.path.join(target, b.backup_date, "photo1.jpg")))
        sha2, was_new2 = b.backup_file(src, "test-card")
        self.assertFalse(was_new2)
        self.assertEqual(sha, sha2)

    def test_different_card_same_file_not_copied_twice(self):
        b = self.make_backup()
        src1 = os.path.join(self.media, "photo2.jpg")
        write_file(src1, b"jpegdata2")
        _, new1 = b.backup_file(src1, "card-A")
        _, new2 = b.backup_file(src1, "card-B")
        self.assertTrue(new1)
        self.assertFalse(new2)

    def test_different_content_with_same_name_is_copied(self):
        b = self.make_backup()
        src = os.path.join(self.media, "photo3.jpg")
        write_file(src, b"original")
        _, new1 = b.backup_file(src, "card-A")
        write_file(src, b"replaced")
        os.utime(src, (0, 0))
        _, new2 = b.backup_file(src, "card-B")
        self.assertTrue(new1)
        self.assertTrue(new2)

    def test_verify_detects_corruption(self):
        b = self.make_backup()
        src = os.path.join(self.media, "photo4.jpg")
        write_file(src, b"jpegdata4")
        b.backup_file(src, "test-card")
        self.assertTrue(b.verify_file(src))
        with open(os.path.join(self.ssd1, b.backup_date, "photo4.jpg"), "wb") as f:
            f.write(b"corrupted")
        self.assertFalse(b.verify_file(src))

    def test_marker_roundtrip(self):
        b = self.make_backup()
        info = {"source": "card-A", "card_size_bytes": 32003203000, "date": b.backup_date,
                "files_total": 10, "files_copied": 8, "files_skipped": 2,
                "files_failed": 0, "files_unverified": 0}
        self.assertTrue(b.write_marker(self.media, info))
        marker = b.read_marker(self.media)
        self.assertEqual(marker["state"], "safe_to_erase")
        self.assertTrue(marker["verified"])
        self.assertFalse(b.write_marker(self.media, info))

    def test_card_info_written_to_both_targets(self):
        b = self.make_backup()
        info = b.write_card_info("card-A", 32003203000, (10, 8, 2, 0, 0))
        for target in (self.ssd1, self.ssd2):
            self.assertTrue(any(os.listdir(os.path.join(target, backup.CARD_INFO_DIR))))




class DevSizeTest(unittest.TestCase):
    def test_sizes(self):
        import disks
        self.assertEqual(disks.dev_size_bytes({"size": "29.7G"}), 31890132172)
        self.assertEqual(disks.dev_size_bytes({"size": "64M"}), 67108864)
        self.assertEqual(disks.dev_size_bytes({"size": "512B"}), 512)
        self.assertEqual(disks.dev_size_bytes({"size": "1.5T"}), 1649267441664)
        self.assertEqual(disks.dev_size_bytes({"size": "1000"}), 1000)


if __name__ == "__main__":
    unittest.main()
