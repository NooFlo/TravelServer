import datetime
import hashlib
import json
import os
import shutil

import status


MARKER_NAME = ".travelserver.json"
CARD_INFO_DIR = "cards"


class BackupError(Exception):
    pass


def sha256_file(path, chunk_size=1024 * 1024):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def scan_media(mountpoint, extensions, subdirs=("",)):
    for subdir in subdirs:
        base = os.path.join(mountpoint, subdir) if subdir else mountpoint
        if not os.path.isdir(base):
            continue
        for root, dirs, files in os.walk(base):
            for name in files:
                if name.startswith("."):
                    continue
                if name.lower().rsplit(".", 1)[-1] in extensions:
                    yield os.path.join(root, name)


def same_hash(a, b):
    return sha256_file(a) == sha256_file(b)


class MirrorBackup:
    def __init__(self, cfg, index, led, log):
        self.cfg = cfg
        self.index = index
        self.led = led
        self.log = log
        self.targets = self._resolve_targets()
        self.backup_date = datetime.date.today().isoformat()

    def _resolve_targets(self):
        import disks
        targets = []
        for label, tag in ((self.cfg.ssd_label_1, 1), (self.cfg.ssd_label_2, 2)):
            dev = disks.find_by_label(self.cfg, label)
            mountpoint = None
            pre_mounted = None
            if dev:
                pre_mounted = dev.get("mountpoint")
                for child in dev.get("children", []):
                    pre_mounted = pre_mounted or child.get("mountpoint")
            if pre_mounted:
                mountpoint = pre_mounted
            elif dev:
                if dev.get("fstype"):
                    path, name = dev["path"], dev["name"]
                else:
                    child = dev.get("children", [None])[0]
                    path, name = child["path"], child["name"]
                try:
                    mountpoint = disks.mount_filesystem_by_path(path, self.cfg.mount_root, name)
                except Exception as exc:
                    self.log("failed to mount SSD %s: %s" % (label, exc))
            if mountpoint:
                root = os.path.join(mountpoint, self.cfg.backup_dir)
                os.makedirs(root, exist_ok=True)
                os.makedirs(os.path.join(root, CARD_INFO_DIR), exist_ok=True)
                targets.append(root)
                if len(targets) == 1:
                    self.primary = root
            else:
                self.log("SSD with label %s not found" % label)
        if not targets:
            raise BackupError("no backup SSD found (labels %s/%s)" % (self.cfg.ssd_label_1, self.cfg.ssd_label_2))
        if len(targets) == 1:
            self.log("WARNING: only one SSD found; running without mirror")
        return targets

    def dedupe_check(self, path):
        name = os.path.basename(path)
        size = os.path.getsize(path)
        rows = self.index.find(name, size)
        for sha256, source, backup_date in rows:
            existing = [os.path.join(t, backup_date, name) for t in [getattr(self, "primary", self.targets[0])]]
            existing = [p for p in existing if os.path.exists(p)]
            if existing and same_hash(path, existing[0]):
                return sha256
        sha = sha256_file(path)
        if self.index.find_hash(sha):
            return sha
        return None

    def backup_file(self, path, source):
        sha = self.dedupe_check(path)
        if sha:
            self.log("skip (already backed up): %s" % os.path.basename(path))
            return sha, False
        sha = sha256_file(path)
        day_dir = os.path.join(self.backup_date)
        for target in self.targets:
            dest_dir = os.path.join(target, day_dir)
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, os.path.basename(path))
            tmp = dest + ".part"
            shutil.copy2(path, tmp)
            os.replace(tmp, dest)
        stat = os.stat(path)
        self.index.add(os.path.basename(path), stat.st_size, stat.st_mtime, sha, source, self.backup_date)
        return sha, True

    def verify_file(self, path):
        name = os.path.basename(path)
        source_hash = sha256_file(path)
        for target in self.targets:
            dest = os.path.join(target, self.backup_date, name)
            if not os.path.exists(dest):
                return False
            if sha256_file(dest) != source_hash:
                return False
        return True

    def run_source(self, mountpoint, source, subdirs, source_kind="card"):
        copied = 0
        skipped = 0
        failed = 0
        files = list(scan_media(mountpoint, self.cfg.extensions, subdirs))
        total = len(files)
        status.STATUS.reset(source, source_kind, total)
        self.log("backing up %d media files from %s" % (total, source))
        for i, path in enumerate(files, 1):
            name = os.path.basename(path)
            try:
                sha, was_new = self.backup_file(path, source)
                if was_new:
                    copied += 1
                    status.STATUS.progress(name, copied=1)
                else:
                    skipped += 1
                    status.STATUS.progress(name, skipped=1)
            except Exception as exc:
                self.log("FAILED %s: %s" % (path, exc))
                failed += 1
                status.STATUS.progress(name, failed=1)
            if i % 10 == 0 or i == total:
                self.log("progress: %d/%d" % (i, total))
        self.led.set("verify")
        status.STATUS.set_verify()
        self.log("verifying %d copied files" % copied)
        unverified = 0
        for path in files:
            name = os.path.basename(path)
            if any(os.path.exists(os.path.join(t, self.backup_date, name)) for t in self.targets):
                if not self.verify_file(path):
                    unverified += 1
                    self.log("VERIFY FAILED: %s" % name)
        status.STATUS.set_unverified(unverified)
        return total, copied, skipped, failed, unverified

    def write_card_info(self, source, size_bytes, stats):
        info = {
            "source": source,
            "card_size_bytes": size_bytes,
            "date": self.backup_date,
            "files_total": stats[0],
            "files_copied": stats[1],
            "files_skipped": stats[2],
            "files_failed": stats[3],
            "files_unverified": stats[4],
        }
        fname = "%s-%s.json" % (source.replace("/", "_").strip("_"), self.backup_date)
        for target in self.targets:
            os.makedirs(os.path.join(target, CARD_INFO_DIR), exist_ok=True)
            path = os.path.join(target, CARD_INFO_DIR, fname)
            with open(path + ".part", "w") as f:
                json.dump(info, f, indent=2)
            os.replace(path + ".part", path)
        return info

    def write_marker(self, mountpoint, info):
        marker = {
            "state": "safe_to_erase",
            "backup_date": self.backup_date,
            "verified": info["files_unverified"] == 0 and info["files_failed"] == 0,
            "card_size_bytes": info["card_size_bytes"],
            "files_total": info["files_total"],
        }
        existing = os.path.join(mountpoint, MARKER_NAME)
        if os.path.exists(existing):
            return False
        with open(existing + ".part", "w") as f:
            json.dump(marker, f, indent=2)
        os.replace(existing + ".part", existing)
        return True

    def read_marker(self, mountpoint):
        marker_path = os.path.join(mountpoint, MARKER_NAME)
        if not os.path.exists(marker_path):
            return None
        try:
            with open(marker_path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None
