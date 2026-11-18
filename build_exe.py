"""
LaptopShare PyInstaller Build Script
Packages LaptopShare into a single standalone portable Windows executable (LaptopShare.exe).
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

def build():
    project_dir = Path(__file__).resolve().parent
    icon_path = project_dir / "assets" / "icon.ico"
    main_py = project_dir / "main.py"
    dist_dir = project_dir / "dist"
    build_dir = project_dir / "build"

    print("=" * 60)
    print("Building LaptopShare.exe with PyInstaller")
    print(f"Project Directory: {project_dir}")
    print(f"Icon Path: {icon_path}")
    print("=" * 60)

    # Use the python executable that installed PyInstaller
    py_exe = sys.executable

    cmd = [
        py_exe, "-m", "PyInstaller",
        "--name=LaptopShare",
        "--onefile",
        "--windowed",
        f"--icon={icon_path}",
        f"--add-data={project_dir / 'assets'};assets",
        "--hidden-import=PySide6",
        "--hidden-import=PySide6.QtCore",
        "--hidden-import=PySide6.QtGui",
        "--hidden-import=PySide6.QtWidgets",
        "--hidden-import=cryptography",
        "--hidden-import=qrcode",
        "--hidden-import=PIL",
        "--hidden-import=psutil",
        "--hidden-import=core.config",
        "--hidden-import=core.security",
        "--hidden-import=core.protocol",
        "--hidden-import=core.network_utils",
        "--hidden-import=core.file_manager",
        "--hidden-import=core.history",
        "--hidden-import=core.discovery",
        "--hidden-import=core.transfer_server",
        "--hidden-import=core.transfer_client",
        "--hidden-import=core.remote_browser_client",
        "--hidden-import=core.migration",
        "--hidden-import=core.migration_client",
        "--hidden-import=core.web_explorer_server",
        "--hidden-import=ui.styles",
        "--hidden-import=ui.qr_widget",
        "--hidden-import=ui.send_tab",
        "--hidden-import=ui.receive_tab",
        "--hidden-import=ui.browse_tab",
        "--hidden-import=ui.migration_tab",
        "--hidden-import=ui.devices_tab",
        "--hidden-import=ui.history_tab",
        "--hidden-import=ui.settings_tab",
        "--hidden-import=ui.main_window",
        "--clean",
        "--noconfirm",
        str(main_py)
    ]

    print("Executing command:")
    print(" ".join(cmd))
    result = subprocess.run(cmd, cwd=str(project_dir))

    if result.returncode == 0:
        exe_path = dist_dir / "LaptopShare.exe"
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            print("=" * 60)
            print(f"BUILD SUCCEEDED!")
            print(f"Executable: {exe_path}")
            print(f"Size: {size_mb:.2f} MB")
            print("=" * 60)
            return True
    print("BUILD FAILED!")
    return False

if __name__ == "__main__":
    success = build()
    sys.exit(0 if success else 1)
