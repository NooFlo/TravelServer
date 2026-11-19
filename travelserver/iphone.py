import subprocess


def iphone_udid():
    try:
        out = subprocess.run(
            ["idevice_id", "-l"], check=True, capture_output=True, text=True, timeout=10
        ).stdout.strip().splitlines()
    except (subprocess.SubprocessError, OSError):
        return None
    return out[0] if out else None


def iphone_details(udid):
    try:
        name = subprocess.run(
            ["idevicename", "-u", udid], check=True, capture_output=True, text=True, timeout=10
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        name = "iphone"
    return name or "iphone"


def validate_pairing(udid):
    result = subprocess.run(
        ["idevicepair", "-u", udid, "validate"], capture_output=True, text=True, timeout=10
    )
    return result.returncode == 0, result.stdout.strip() + result.stderr.strip()


def mount_iphone(udid, mountpoint_cfg):
    if not udid:
        return None, "no iPhone detected"
    paired, message = validate_pairing(udid)
    if not paired:
        if "No device found" not in message and "not paired" not in message.lower():
            try:
                subprocess.run(["idevicepair", "-u", udid, "pair"], capture_output=True, text=True, timeout=10)
                paired, message = validate_pairing(udid)
            except subprocess.SubprocessError:
                pass
        if not paired:
            return None, "iPhone not paired/trusted: %s" % message
    import os
    os.makedirs(mountpoint_cfg, exist_ok=True)
    result = subprocess.run(
        ["ifuse", "-u", udid, mountpoint_cfg], capture_output=True, text=True, timeout=15
    )
    if result.returncode != 0:
        return None, "ifuse failed: %s" % (result.stderr.strip() or result.stdout.strip())
    return mountpoint_cfg, None
