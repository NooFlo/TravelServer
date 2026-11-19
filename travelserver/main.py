import argparse
import os
import shutil
import subprocess
import sys
import time

import disks
import iphone as iphone_mod
import status
import webui
from backup import BackupError, MirrorBackup
from config import Config
from index import BackupIndex
from led import Led


def log(message):
    print("[travelserver] %s" % message, flush=True)
    status.STATUS.add_log(message)


def human_bytes(n):
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return "%.0f %s" % (value, unit)
            return "%.1f %s" % (value, unit)
        value /= 1024.0


def disk_entry(cfg, devices, label):
    """Snapshot of one labeled SSD for the status dashboard."""
    dev = None
    for d in devices:
        if d.get("label") == label or any(c.get("label") == label for c in d.get("children", [])):
            dev = d
            break
    entry = {"label": label, "present": dev is not None,
             "mountpoint": None, "size": None, "free": None}
    if dev:
        mountpoint = dev.get("mountpoint")
        if not mountpoint:
            for child in dev.get("children", []):
                mountpoint = mountpoint or child.get("mountpoint")
        entry["mountpoint"] = mountpoint
        entry["size"] = human_bytes(disks.dev_size_bytes(dev))
        if mountpoint:
            try:
                usage = shutil.disk_usage(mountpoint)
                entry["free"] = human_bytes(usage.free)
            except OSError:
                pass
    return entry


def disks_overview(cfg, devices):
    return [disk_entry(cfg, devices, label)
            for label in (cfg.ssd_label_1, cfg.ssd_label_2)]


def handle_card(cfg, led, dev):
    mountpoint = None
    try:
        mountpoint = disks.mount_readonly_partition(dev, cfg.mount_root)
        source_id = "%s-%s" % (dev.get("model") or "card", dev.get("serial") or dev["name"])
        backup = build_backup(cfg, led)
        marker = backup.read_marker(mountpoint)
        size_bytes = disks.dev_size_bytes(dev)
        if marker and marker.get("state") == "safe_to_erase" and marker.get("verified"):
            log("card %s re-inserted with verified safe-to-erase marker; formatting" % source_id)
            disks.unmount(mountpoint)
            mountpoint = None
            disks.format_exfat(dev["path"])
            led.set("done")
            status.STATUS.set_state("done", source=source_id, source_kind="card")
            log("card %s formatted to exFAT" % source_id)
            return
        led.set("backup")
        stats = backup.run_source(mountpoint, source_id, ("",), source_kind="card")
        info = backup.write_card_info(source_id, size_bytes, stats)
        if info["files_failed"] == 0 and info["files_unverified"] == 0:
            remount_rw_and_write_marker(cfg, dev, mountpoint, backup, info, source_id)
            led.set("done")
            status.STATUS.set_state("done")
            log("card %s: backup complete and verified - safe to erase" % source_id)
        else:
            led.set("error")
            status.STATUS.set_state("error")
            log("card %s: backup INCOMPLETE (%d failed, %d unverified); card NOT marked erasable"
                % (source_id, info["files_failed"], info["files_unverified"]))
    except Exception as exc:
        led.set("error")
        status.STATUS.set_error("card backup failed: %s" % exc)
        log("card backup failed: %s" % exc)
    finally:
        if mountpoint:
            disks.unmount(mountpoint)


def remount_rw_and_write_marker(cfg, dev, mountpoint, backup, info, source_id):
    disks.unmount(mountpoint)
    target = dev
    if not target.get("fstype"):
        children = dev.get("children", [])
        target = children[0] if children else dev
        if not target.get("fstype") and target.get("children"):
            target = target["children"][0]
    rw_mount, _ = disks.mount_partition_rw(target, cfg.mount_root)
    try:
        if backup.write_marker(rw_mount, info):
            log("safe-to-erase marker written to card %s" % source_id)
        else:
            log("marker already present on card %s" % source_id)
    except Exception as exc:
        log("could not write safe-to-erase marker (card write-protected?): %s" % exc)
    disks.unmount(rw_mount)


def handle_iphone(cfg, led):
    udid = iphone_mod.iphone_udid()
    if not udid:
        log("iPhone detected over USB but usbmuxd could not list it")
        led.set("error")
        return
    mountpoint = None
    try:
        name = iphone_mod.iphone_details(udid)
        mountpoint, err = iphone_mod.mount_iphone(udid, cfg.iphone_mountpoint)
        if not mountpoint:
            led.set("error")
            log("iPhone %s: %s" % (name, err))
            return
        led.set("backup")
        backup = build_backup(cfg, led)
        source_id = name.replace(" ", "-").lower()
        stats = backup.run_source(mountpoint, source_id, ("DCIM",), source_kind="phone")
        info = backup.write_card_info(source_id, 0, stats)
        if info["files_failed"] == 0 and info["files_unverified"] == 0:
            led.set("done")
            status.STATUS.set_state("done")
            log("iPhone %s: backup complete and verified" % name)
        else:
            led.set("error")
            status.STATUS.set_state("error")
            log("iPhone %s: backup INCOMPLETE (%d failed, %d unverified)"
                % (name, info["files_failed"], info["files_unverified"]))
    except Exception as exc:
        led.set("error")
        status.STATUS.set_error("iPhone backup failed: %s" % exc)
        log("iPhone backup failed: %s" % exc)
    finally:
        if mountpoint:
            subprocess.run(["umount", mountpoint], check=False)
            try:
                os.rmdir(mountpoint)
            except OSError:
                pass


def build_backup(cfg, led):
    primary_root = None
    mirror_root = None
    for label, slot in ((cfg.ssd_label_1, "primary_root"), (cfg.ssd_label_2, "mirror_root")):
        dev = disks.find_by_label(cfg, label)
        mountpoint = None
        if dev:
            mountpoint = dev.get("mountpoint")
            for child in dev.get("children", []):
                mountpoint = mountpoint or child.get("mountpoint")
            if not mountpoint:
                if dev.get("fstype"):
                    path, name = dev["path"], dev["name"]
                else:
                    child = dev.get("children", [None])[0]
                    path, name = child["path"], child["name"]
                mountpoint = disks.mount_filesystem_by_path(path, cfg.mount_root, name)
        if mountpoint:
            root = os.path.join(mountpoint, cfg.backup_dir)
            os.makedirs(root, exist_ok=True)
            if slot == "primary_root":
                primary_root = root
            else:
                mirror_root = root
        else:
            log("SSD with label %s not found" % label)
    if not primary_root:
        raise BackupError("primary SSD (label %s) not found" % cfg.ssd_label_1)
    if not mirror_root:
        log("WARNING: mirror SSD (label %s) not found; no mirroring" % cfg.ssd_label_2)
    index = BackupIndex(primary_root, mirror_root)
    return MirrorBackup(cfg, index, led, log)


def run_daemon(cfg, led, once=False):
    led.set("idle")
    if cfg.webui_enabled:
        try:
            webui.start(cfg)
            log("web UI listening on http://%s:%d" % (cfg.webui_bind, cfg.webui_port))
        except OSError as exc:
            log("could not start web UI on %s:%d: %s" % (cfg.webui_bind, cfg.webui_port, exc))
    known_cards = set()
    last_iphone = 0.0
    while True:
        try:
            devices = disks.flatten(disks.lsblk())
        except Exception as exc:
            log("lsblk failed: %s" % exc)
            devices = []
        try:
            status.STATUS.set_disks(disks_overview(cfg, devices))
        except Exception as exc:
            log("disk overview failed: %s" % exc)
        for dev in devices:
            if not disks.is_removable_card_reader_device(dev, cfg):
                continue
            card_key = dev.get("serial") or dev["name"]
            if dev.get("mountpoint") or any(c.get("mountpoint") for c in dev.get("children", [])):
                continue
            if card_key in known_cards:
                continue
            known_cards.add(card_key)
            log("card reader device appeared: %s (%s)" % (dev["path"], dev.get("model") or "unknown"))
            handle_card(cfg, led, dev)
            led.set("idle")
        now = time.time()
        if now - last_iphone > cfg.poll_interval:
            if iphone_present():
                log("iPhone detected")
                handle_iphone(cfg, led)
                led.set("idle")
                last_iphone = now
        known_cards = prune_known(known_cards)
        if once:
            return
        time.sleep(cfg.poll_interval)


def iphone_present():
    try:
        out = subprocess.run(
            ["lsusb"], capture_output=True, text=True, timeout=10
        ).stdout.lower()
        return "apple inc." in out or "apple, inc" in out or "05ac:" in out
    except (subprocess.SubprocessError, OSError):
        return False


def prune_known(known_cards):
    try:
        current = {d.get("serial") or d["name"] for d in disks.flatten(disks.lsblk())}
    except Exception:
        return known_cards
    return {k for k in known_cards if k in current}


def format_command(cfg, led, device_path):
    if not os.path.exists(device_path):
        print("device not found: %s" % device_path)
        return 1
    dev = None
    for d in disks.flatten(disks.lsblk()):
        if d["path"] == device_path:
            dev = d
            break
    if dev is None:
        print("device not found in lsblk: %s" % device_path)
        return 1
    if dev.get("fstype") or dev.get("label") in (cfg.ssd_label_1, cfg.ssd_label_2):
        print("refusing: %s looks like a backup SSD or mounted filesystem" % device_path)
        return 1
    if not disks.is_removable_card_reader_device(dev, cfg):
        print("refusing: %s is not a removable USB device" % device_path)
        return 1
    print("formatting %s to exFAT..." % device_path)
    disks.format_exfat(device_path)
    print("done")
    return 0


def main():
    parser = argparse.ArgumentParser(description="TravelServer photo backup daemon")
    parser.add_argument("--config", default=None)
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("run")
    sub.add_parser("once")
    fmt = sub.add_parser("format")
    fmt.add_argument("device")
    sub.add_parser("sd-check")
    args = parser.parse_args()

    cfg = Config(args.config)
    led = Led(cfg)
    led.start()

    if args.cmd == "format":
        sys.exit(format_command(cfg, led, args.device) or 0)

    if args.cmd == "sd-check":
        for dev in disks.flatten(disks.lsblk()):
            print("%s removable_card=%s label=%s model=%s" % (
                dev["path"], disks.is_removable_card_reader_device(dev, cfg),
                dev.get("label") or "-", dev.get("model") or "-"))
        return

    try:
        if args.cmd == "once":
            run_daemon(cfg, led, once=True)
        else:
            run_daemon(cfg, led)
    except KeyboardInterrupt:
        pass
    finally:
        led.stop()


if __name__ == "__main__":
    main()
