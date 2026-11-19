# TravelServer

A headless photo backup appliance for the [Radxa ROCK 5A](https://radxa.com/products/rock5/rock5a). Insert an SD card, and it automatically backs up all photos and videos to two SSDs (mirrored), verifies them, and marks the card safe to erase. Plug in an iPhone over USB and its camera roll is backed up the same way. A GPIO status LED shows what the box is doing. Each file is backed up exactly once: files are compared by date, name, size, and SHA-256 hash before anything is copied. A small web dashboard shows live progress.

## First boot on a fresh ROCK 5A

The ROCK 5A **has no native Ethernet jack** — you need a **USB→GbE adapter**
(any ASIX/Realtek-based one works) in one of the USB 3 ports. The box is
otherwise headless: no monitor or keyboard needed.

1. On your computer: download the **Armbian server** image for the ROCK 5A
   from [armbian.com](https://www.armbian.com/download/?device=radxa_rock_5a)
   and flash it to the microSD card (the one labeled "untitled") with
   [balenaEtcher](https://etcher.balena.io/) or the Armbian imaging utility.
2. Plug the USB→GbE adapter into the ROCK 5A, connect Ethernet to your
   router, insert the SD, power on.
3. On first boot, Armbian resizes its partition and reboots once more; give
   it ~5 minutes. Find the board's IP address in your router's DHCP list.
4. SSH in — Armbian defaults are `root` / `1234`, and you're asked to set a
   new password immediately:
   ```bash
   ssh root@<rock5a-ip>
   ```
5. Install TravelServer:
   ```bash
   git clone -b vibe/travel-server-rock5a https://github.com/NooFlo/TravelServer.git
   cd TravelServer
   sudo ./install.sh           # add --with-docker for the optional webapps layer
   sudo systemctl start travelserver
   ```
   (Once PR #1 merges, drop the `-b vibe/travel-server-rock5a`.)
6. Open the status dashboard in a browser: **http://\<rock5a-ip\>:8000**
   — insert an SD card and watch it work.

With no backup SSDs attached yet, the daemon runs fine: it idles, logs
`SSD with label TRAVEL1 not found`, and shows an error pattern if you insert
a card. The dashboard's *Storage* section tells you when both SSDs are seen.

## How it works

1. **Insert an SD card** into any USB card reader connected to the ROCK 5A.
   The daemon mounts it read-only, records the card's capacity, creates a folder
   named with today's date (`YYYY-MM-DD/`) on both SSDs, and copies each media
   file there. Files already present (matching name, size, mtime, and SHA-256)
   are skipped.
2. **Verify.** Every copied file is re-read from both SSDs and hash-compared
   against the card.
3. **Safe-to-erase (two-step format).** After a fully verified backup the card
   gets a small `.travelserver.json` marker with its original size and the
   backup date, plus a `cards/<source>-<date>.json` info file on each SSD.
   **The card is NOT formatted automatically.** The next time that marked card
   is inserted, the daemon formats it to exFAT — that second insertion is your
   confirmation. You can also format explicitly:
   ```bash
   python3 /opt/travelserver/travelserver/main.py format /dev/sdX
   ```
4. **iPhone.** Connect via USB and tap *Trust*. The daemon pairs via
   libimobiledevice, mounts the phone's `DCIM` with ifuse, and runs the same
   dedupe/verify pipeline. No formatting of phones, obviously.
5. **LED status** (configurable GPIO line):

   | Pattern | Meaning |
   |---|---|
   | slow blink | idle, waiting for a device |
   | fast blink (4 Hz) | copying files |
   | very fast blink (~12 Hz) | verifying files |
   | solid | backup complete and verified (card is safe to erase) |
   | double flash, pause | error — incomplete backup; card was NOT marked |

## Hardware

- **ROCK 5A** (RK3588S) running Armbian or an official Radxa Debian/Ubuntu image, booted from the on-board microSD.
- **Two SSDs** on the USB 3.0 ports (or one via a USB 3.0 hub). Label the filesystems exactly `TRAVEL1` and `TRAVEL2`:
  ```bash
  sudo mkfs.ext4 -L TRAVEL1 /dev/sda1
  sudo mkfs.ext4 -L TRAVEL2 /dev/sdb1
  ```
- **USB SD card reader(s)** — any reader works; multi-slot readers also work (each card is handled as its own device).
- **Status LED** — a single LED (plus resistor, ~330 Ω) wired between a GPIO pin and ground on the 40-pin header. Set the libgpiod line in the config. Use `gpioinfo` to find a free line corresponding to your chosen pin. Set `led.enabled = false` to run without an LED (states are also logged).
- Recommended: a powered USB hub if your SSDs are bus-powered — the ROCK 5A's ports can't comfortably feed two SSDs plus readers on power alone.

## Layout on the SSDs

```
BACKUP/
  index.db              # dedupe index (SQLite), mirrored on both SSDs
  2025-11-19/          # folder per backup day; all photos from that day
    IMG_0001.JPG
    DSC_0123.RW2
  cards/                # per-card/per-phone info: size, date, file counts
    Generic-Ultra-64GB-2025-11-19.json
    johns-iphone-2025-11-19.json
```

## Web GUI

The daemon serves a small dark-theme dashboard on port **8000** (config:
`[webui]` → `enabled`, `bind`, `port`): live progress bar and per-file stats
(copied / skipped dedupe / failed / unverified), the drive presence and free
space of TRAVEL1/TRAVEL2, the current LED pattern, and a rolling last-200
log lines. It polls `/api/status.json` every 3 s and is plain stdlib —
no framework, no database, nothing to configure beyond the port.
It's plain HTTP: treat it as LAN-only.

Other webapps (Immich, a minimal gallery) can run alongside via the optional
Docker layer — see [webapps/README.md](webapps/README.md) and
`sudo ./install.sh --with-docker`. They are strictly separate from the
backup pipeline and only ever see `BACKUP/` read-only.

## Installation

On the ROCK 5A (Armbian/Debian/Ubuntu):

```bash
git clone -b vibe/travel-server-rock5a https://github.com/NooFlo/TravelServer.git
cd TravelServer
sudo ./install.sh
sudo systemctl start travelserver
journalctl -u travelserver -f    # watch it work
```

The installer copies the code to `/opt/travelserver`, the config to
`/etc/travelserver/travelserver.conf`, and installs `python3`,
`libimobiledevice-utils`, `usbmuxd`, `ifuse`, `exfatprogs`, and `libgpiod-utils`.
Use `sudo ./install.sh --with-docker` to additionally install Docker + Compose
for the [optional webapps](webapps/README.md).

Edit `/etc/travelserver/travelserver.conf` to change:
- SSD labels, backup folder name
- media file extensions
- LED GPIO chip/line, or disable the LED
- poll interval, max card size guard for the formatter
- web UI port / bind address, or disable it entirely

## Safety guards around formatting

- Only whole disks that report as **removable USB devices** under the max card
  size are ever considered SD cards; the label-matched SSDs are excluded.
- Formatting only happens for a card whose on-card marker says
  `state: safe_to_erase, verified: true` — i.e. two-step, after a fully
  verified backup.
- If any file fails to copy or verify, the card is never marked and never
  formatted; the LED shows the error pattern.
- The explicit `format` subcommand refuses non-removable or labeled devices.

## Verification & dedupe details

- Quick check: filename + size + mtime against the index; then SHA-256 of the
  source compared with the stored copy.
- Full check: after a run, every source file that has a copy in the day folder
  is hash-compared on **both** SSDs. A backup counts as complete only if zero
  failures and zero mismatches.
- The index lives on the primary SSD and is mirrored to the second, so either
  SSD alone can decide what has been backed up before.

## Tests

```bash
python3 tests/test_backup.py
python3 tests/test_webui.py
```

## Acknowledgements / prior art

- [Little Backup Box](https://github.com/outdoorbits/little-backup-box) — inspiration for the insert-and-backup UX; this project is purpose-built instead (added mirrored SSDs, hash dedupe, two-step auto-format, iPhone via modern libimobiledevice).
- [libimobiledevice](https://github.com/libimobiledevice/libimobiledevice), [ifuse](https://github.com/libimobiledevice/ifuse), [usbmuxd](https://github.com/libimobiledevice/usbmuxd) — all iPhone communication.
