"""
LaptopShare Configuration Manager
Handles user preferences, persistent settings, and application constants.
"""

import os
import json
import socket
import string
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import List, Dict

DEFAULT_TRANSFER_PORT = 52140
DEFAULT_DISCOVERY_PORT = 52141
PROTOCOL_VERSION = "1.0"
APP_NAME = "LaptopShare"

def get_default_download_dir() -> str:
    user_home = Path.home()
    dl_dir = user_home / "Downloads" / "LaptopShare"
    dl_dir.mkdir(parents=True, exist_ok=True)
    return str(dl_dir)

def get_app_data_dir() -> Path:
    app_data = os.getenv("APPDATA")
    if app_data:
        p = Path(app_data) / "LaptopShare"
    else:
        p = Path.home() / ".laptopshare"
    p.mkdir(parents=True, exist_ok=True)
    return p

def get_system_shared_roots() -> List[Dict[str, str]]:
    """
    Returns list of standard system roots and drives available on Windows.
    Each item has 'name' and 'path'.
    """
    roots = []
    user_home = Path.home()

    # Common user folders
    common_folders = [
        ("User Home", user_home),
        ("Desktop", user_home / "Desktop"),
        ("Documents", user_home / "Documents"),
        ("Downloads", user_home / "Downloads"),
        ("Pictures", user_home / "Pictures"),
        ("Videos", user_home / "Videos"),
        ("Music", user_home / "Music"),
    ]

    for name, p in common_folders:
        if p.exists():
            roots.append({"name": f"📁 {name}", "path": str(p.resolve())})

    # Available system drives (C:\, D:\, etc.)
    for letter in string.ascii_uppercase:
        drive_path = Path(f"{letter}:\\")
        if drive_path.exists():
            roots.append({"name": f"💾 Local Disk ({letter}:)", "path": str(drive_path)})

    return roots

@dataclass
class AppConfig:
    device_name: str = ""
    download_dir: str = ""
    transfer_port: int = DEFAULT_TRANSFER_PORT
    discovery_port: int = DEFAULT_DISCOVERY_PORT
    theme: str = "dark"  # "dark" or "light"
    auto_discovery: bool = True
    require_pin: bool = True
    current_pin: str = "123456"
    allow_remote_browsing: bool = True

    def __post_init__(self):
        if not self.device_name:
            try:
                self.device_name = socket.gethostname()
            except Exception:
                self.device_name = "Windows-Laptop"
        if not self.download_dir:
            self.download_dir = get_default_download_dir()

class ConfigManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance._load()
        return cls._instance

    def _get_config_path(self) -> Path:
        return get_app_data_dir() / "settings.json"

    def _load(self):
        self.config = AppConfig()
        config_path = self._get_config_path()
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for k, v in data.items():
                        if hasattr(self.config, k):
                            setattr(self.config, k, v)
            except Exception as e:
                print(f"[Config] Error loading configuration: {e}")

    def save(self):
        config_path = self._get_config_path()
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(asdict(self.config), f, indent=2)
        except Exception as e:
            print(f"[Config] Error saving configuration: {e}")

    def get(self) -> AppConfig:
        return self.config
