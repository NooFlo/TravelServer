import configparser
import os


DEFAULT_CONFIG_PATHS = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "travelserver.conf"),
    "/etc/travelserver/travelserver.conf",
]


class Config:
    def __init__(self, path):
        parser = configparser.ConfigParser()
        read = parser.read([path] if path else DEFAULT_CONFIG_PATHS)
        if not read:
            raise FileNotFoundError("no config file found at: %s" % (path or DEFAULT_CONFIG_PATHS))
        self.path = read[0]

        s = parser["storage"]
        self.ssd_label_1 = s.get("ssd_label_1", "TRAVEL1")
        self.ssd_label_2 = s.get("ssd_label_2", "TRAVEL2")
        self.backup_dir = s.get("backup_dir", "BACKUP")
        self.mount_root = s.get("mount_root", "/mnt/travelserver")

        m = parser["media"]
        self.extensions = {e.strip().lower().lstrip(".") for e in m.get("extensions").replace(",", " ").split() if e.strip()}

        l = parser["led"]
        self.led_enabled = l.getboolean("enabled", False)
        self.led_gpio_chip = l.get("gpio_chip", "gpiochip0")
        self.led_gpio_line = l.getint("gpio_line", 32)

        i = parser["iphone"]
        self.iphone_mountpoint = i.get("mountpoint", "/mnt/travelserver/iphone")

        if not parser.has_section("webui"):
            parser.add_section("webui")
        w = parser["webui"]
        self.webui_enabled = w.getboolean("enabled", True)
        self.webui_port = w.getint("port", 8000)
        self.webui_bind = w.get("bind", "0.0.0.0")

        b = parser["behavior"]
        self.poll_interval = b.getint("poll_interval", 2)
        self.max_sd_card_bytes = b.getint("max_sd_card_bytes", 1099511627776)
