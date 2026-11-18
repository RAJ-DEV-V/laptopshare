"""
LaptopShare PC Migration Engine
Handles discovery of user profile categories (Desktop, Documents, Downloads, Pictures,
Videos, Music, Browser Data, VS Code & Dev configs) for seamless laptop-to-laptop switching.
"""

import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict

from .file_manager import format_file_size

@dataclass
class MigrationCategory:
    id: str
    name: str
    icon: str
    description: str
    source_path: str
    dest_subfolder: str
    file_count: int = 0
    total_bytes: int = 0
    available: bool = False
    selected: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

def get_detectable_migration_categories(user_home: Optional[Path] = None) -> List[MigrationCategory]:
    """
    Returns list of standard Windows user migration categories with their default paths.
    """
    home = user_home or Path.home()
    local_app_data = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
    roaming_app_data = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))

    categories = [
        MigrationCategory(
            id="desktop",
            name="Desktop",
            icon="🖥️",
            description="All desktop shortcuts, folders, and files",
            source_path=str(home / "Desktop"),
            dest_subfolder="Desktop",
            selected=True
        ),
        MigrationCategory(
            id="documents",
            name="Documents",
            icon="📄",
            description="Personal documents, spreadsheets, PDFs, and work files",
            source_path=str(home / "Documents"),
            dest_subfolder="Documents",
            selected=True
        ),
        MigrationCategory(
            id="pictures",
            name="Pictures & Photos",
            icon="🖼️",
            description="Photos, camera rolls, wallpapers, and image albums",
            source_path=str(home / "Pictures"),
            dest_subfolder="Pictures",
            selected=True
        ),
        MigrationCategory(
            id="downloads",
            name="Downloads",
            icon="📥",
            description="Recent downloads, installers, and saved web files",
            source_path=str(home / "Downloads"),
            dest_subfolder="Downloads",
            selected=False  # Optional by default to save bandwidth
        ),
        MigrationCategory(
            id="videos",
            name="Videos & Movies",
            icon="🎬",
            description="Personal video recordings, screen captures, and movies",
            source_path=str(home / "Videos"),
            dest_subfolder="Videos",
            selected=True
        ),
        MigrationCategory(
            id="music",
            name="Music & Audio",
            icon="🎵",
            description="Music library, albums, podcasts, and sound files",
            source_path=str(home / "Music"),
            dest_subfolder="Music",
            selected=True
        ),
        MigrationCategory(
            id="chrome",
            name="Google Chrome Bookmarks",
            icon="🌐",
            description="Bookmarks, reading list, and browser settings",
            source_path=str(local_app_data / "Google" / "Chrome" / "User Data" / "Default" / "Bookmarks"),
            dest_subfolder="Browsers/Chrome",
            selected=True
        ),
        MigrationCategory(
            id="edge",
            name="Microsoft Edge Bookmarks",
            icon="🌊",
            description="Edge bookmarks, favorites, and configuration",
            source_path=str(local_app_data / "Microsoft" / "Edge" / "User Data" / "Default" / "Bookmarks"),
            dest_subfolder="Browsers/Edge",
            selected=True
        ),
        MigrationCategory(
            id="vscode",
            name="VS Code Configuration",
            icon="💻",
            description="Visual Studio Code user settings, keybindings, and snippets",
            source_path=str(roaming_app_data / "Code" / "User"),
            dest_subfolder="DevConfigs/VSCode_User",
            selected=True
        ),
        MigrationCategory(
            id="git_ssh",
            name="Git & SSH Credentials",
            icon="🔑",
            description="SSH public/private keys and global .gitconfig",
            source_path=str(home / ".ssh"),
            dest_subfolder="DevConfigs/SSH",
            selected=False  # Optional for security
        ),
    ]

    return categories

def scan_migration_categories(user_home: Optional[Path] = None, fast: bool = False) -> List[MigrationCategory]:
    """
    Scans the local filesystem to calculate file counts and total byte sizes for each category.
    """
    categories = get_detectable_migration_categories(user_home)

    for cat in categories:
        src = Path(cat.source_path)
        if not src.exists():
            cat.available = False
            continue

        cat.available = True
        if src.is_file():
            try:
                cat.file_count = 1
                cat.total_bytes = src.stat().st_size
            except Exception:
                pass
        elif src.is_dir():
            count = 0
            size = 0
            # Fast scan (shallow) or full scan
            try:
                if fast:
                    # Scan top 2 levels
                    for root, dirs, files in os.walk(src):
                        count += len(files)
                        for f in files:
                            try:
                                size += (Path(root) / f).stat().st_size
                            except Exception:
                                pass
                        if count > 500:
                            break
                else:
                    for root, dirs, files in os.walk(src):
                        count += len(files)
                        for f in files:
                            try:
                                size += (Path(root) / f).stat().st_size
                            except Exception:
                                pass
            except Exception:
                pass

            cat.file_count = count
            cat.total_bytes = size

    return categories
