import json
import os
import subprocess

def lsblk():
    out = subprocess.run(
        ["lsblk", "-J", "-o", "NAME,PATH,SIZE,TYPE,FSTYPE,LABEL,MOUNTPOINT,MODEL,SERIAL,TRAN,RM,HOTPLUG"],
        check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(out)["blockdevices"]

def walk_devices(devices):
    stack = list(devices)
    while stack:
        dev = stack.pop(0)
        yield dev
        stack.extend(dev.get("children", []))

def flatten(devices):
    return list(walk_devices(devices))

def find_by_label(cfg, label):
    for dev in flatten(lsblk()):
        if dev.get("label") == label or any(c.get("label") == label for c in dev.get("children", [])):
            return dev
    return None

def dev_size_bytes(dev):
    size = dev.get("size", "0")
    units = {"B": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4, "P": 1024**5}
    num = ""
    unit = "B"
    for ch in size.strip():
        if ch.isdigit() or ch == ".":
            num += ch
        else:
            unit = ch.upper()
            break
    return int(float(num or 0) * units.get(unit, 1))

def is_removable_card_reader_device(dev, cfg):
    """True if this whole disk looks like it belongs to a USB card reader."""
    if dev.get("type") != "disk":
        return False
    if str(dev.get("rm", "0")) != "1" and str(dev.get("hotplug", "0")) != "1":
        return False
    if dev.get("tran") != "usb":
        return False
    if dev.get("label") in (cfg.ssd_label_1, cfg.ssd_label_2):
        return False
    if dev_size_bytes(dev) > cfg.max_sd_card_bytes:
        return False
    return True

def mount_readonly_partition(dev, mount_root):
    """Mount the first mountable filesystem of a disk, read-only. Returns mountpoint."""
    target = None
    if dev.get("fstype"):
        target = dev
    else:
        for child in dev.get("children", []):
            if child.get("fstype"):
                target = child
                break
            for grandchild in child.get("children", []):
                if grandchild.get("fstype"):
                    target = grandchild
                    break
    if target is None:
        raise RuntimeError("no filesystem found on %s" % dev["path"])
    if target.get("mountpoint"):
        return target["mountpoint"]
    mp = os.path.join(mount_root, target["name"])
    os.makedirs(mp, exist_ok=True)
    subprocess.run(["mount", "-o", "ro", target["path"], mp], check=True)
    return mp

def mount_partition_rw(dev, mount_root):
    if dev.get("mountpoint"):
        return dev["mountpoint"], True
    mp = os.path.join(mount_root, dev["name"])
    os.makedirs(mp, exist_ok=True)
    subprocess.run(["mount", dev["path"], mp], check=True)
    return mp, True

def unmount(mountpoint):
    if not mountpoint:
        return
    subprocess.run(["umount", mountpoint], check=False)
    try:
        os.rmdir(mountpoint)
    except OSError:
        pass

def mount_filesystem_by_path(path, mount_root, name):
    mp = os.path.join(mount_root, name)
    os.makedirs(mp, exist_ok=True)
    subprocess.run(["mount", path, mp], check=True)
    return mp

def format_exfat(device_path):
    subprocess.run(["wipefs", "-a", device_path], check=True)
    subprocess.run(["mkfs.exfat", device_path], check=True)
