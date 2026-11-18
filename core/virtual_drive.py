r"""
LaptopShare Virtual Drive & Windows File Explorer Manager
Mounts the connected laptop as a native virtual drive (e.g. U:\) under "This PC"
in Windows File Explorer with custom drive label 'USB-C Connected Laptop'.
"""

import os
import sys
import subprocess
import string
import ctypes
import winreg
from pathlib import Path
from typing import Tuple, Optional, List

DEFAULT_DRIVE_LETTER = "U:"
DEFAULT_DRIVE_LABEL = "USB-C Connected Laptop"

def get_available_drive_letters(preferred: str = "U:") -> List[str]:
    """Returns available Windows drive letters, with preferred letters first."""
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    all_letters = list(string.ascii_uppercase)
    used = set()
    for i in range(26):
        if bitmask & (1 << i):
            used.add(f"{all_letters[i]}:")

    # Preference order: U:, L:, Z:, Y:, X:, W:, V:...
    priority = [preferred.upper().rstrip(":"), "U", "L", "Z", "Y", "X", "W", "V", "T", "S", "R", "Q", "P"]
    ordered = []
    for l in priority:
        d = f"{l}:"
        if d not in used and d not in ordered:
            ordered.append(d)

    for l in reversed(all_letters):
        d = f"{l}:"
        if d not in used and d not in ordered:
            ordered.append(d)

    return ordered

def set_windows_explorer_drive_label(target_unc_or_url: str, drive_letter: str, label: str):
    """
    Registers a custom desktop label in the Windows Registry so Windows File Explorer
    renders the drive as e.g. "USB-C Connected Laptop (U:)" under This PC.
    """
    try:
        # Registry key for Explorer MountPoints2
        # Normalizes format: \\192.168.1.50@52145\DavWWWRoot -> ##192.168.1.50#52145#DavWWWRoot
        norm = target_unc_or_url.replace("\\\\", "##").replace("\\", "#").replace("@", "#")
        norm = norm.replace("http://", "##").replace(":", "#").strip("#")

        base_key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\MountPoints2"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base_key_path) as base_k:
            # Set for the specific UNC / WebDAV target
            try:
                with winreg.CreateKey(base_k, norm) as sub_k:
                    winreg.SetValueEx(sub_k, "_LabelFromDesktop", 0, winreg.REG_SZ, label)
            except Exception:
                pass

            # Also set for the drive letter (e.g. U:)
            try:
                letter_key = drive_letter.upper().rstrip(":")
                with winreg.CreateKey(base_k, letter_key) as sub_k:
                    winreg.SetValueEx(sub_k, "_LabelFromDesktop", 0, winreg.REG_SZ, label)
            except Exception:
                pass
    except Exception as e:
        print(f"[VirtualDrive] Could not set Explorer label in registry: {e}")

def mount_usb_laptop_drive(
    remote_ip: str,
    port: int = 52145,
    preferred_letter: str = DEFAULT_DRIVE_LETTER,
    drive_label: str = DEFAULT_DRIVE_LABEL,
    open_explorer: bool = True
) -> Tuple[bool, str, str]:
    """
    Mounts the remote laptop as a virtual drive in Windows File Explorer.
    Returns: (success: bool, drive_letter: str, message: str)
    """
    available = get_available_drive_letters(preferred_letter)
    if not available:
        return False, "", "No free drive letters available on this PC."

    target_letter = available[0]

    # Ensure Windows WebClient service is active
    try:
        subprocess.run(["sc", "start", "webclient"], capture_output=True, timeout=2)
    except Exception:
        pass

    # Ensure target drive letter is unmapped
    unmount_usb_laptop_drive(target_letter)

    # 1. Attempt WebDAV HTTP mount: net use <letter> http://<ip>:<port>/
    url_target = f"http://{remote_ip}:{port}/"
    unc_target = f"\\\\{remote_ip}@{port}\\DavWWWRoot"

    cmd1 = ["net", "use", target_letter, url_target, "/user:guest", '""', "/persistent:no"]
    try:
        res1 = subprocess.run(cmd1, capture_output=True, text=True, timeout=8)
        if res1.returncode == 0:
            set_windows_explorer_drive_label(url_target, target_letter, drive_label)
            if open_explorer:
                open_virtual_drive(target_letter)
            return True, target_letter, f"Successfully mounted remote laptop as {target_letter}\\ ({drive_label})!"
    except Exception as e:
        print(f"[VirtualDrive] Method 1 failed: {e}")

    # 2. Attempt UNC mount: net use <letter> \\ip@port\DavWWWRoot
    cmd2 = ["net", "use", target_letter, unc_target, "/user:guest", '""', "/persistent:no"]
    try:
        res2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=8)
        if res2.returncode == 0:
            set_windows_explorer_drive_label(unc_target, target_letter, drive_label)
            if open_explorer:
                open_virtual_drive(target_letter)
            return True, target_letter, f"Successfully mounted remote laptop as {target_letter}\\ ({drive_label})!"
    except Exception as e:
        print(f"[VirtualDrive] Method 2 failed: {e}")

    # 3. Fallback: Launch Windows Explorer directly pointing to UNC
    try:
        subprocess.Popen(["explorer.exe", unc_target])
        return True, unc_target, f"Opened {unc_target} directly in Windows Explorer."
    except Exception as e:
        return False, "", f"Failed to mount or open in Windows Explorer: {e}"

def unmount_usb_laptop_drive(drive_letter: str) -> bool:
    """Safely unmounts a mapped virtual drive."""
    clean_letter = drive_letter.strip().rstrip("\\")
    if not clean_letter.endswith(":"):
        clean_letter += ":"
    try:
        res = subprocess.run(["net", "use", clean_letter, "/delete", "/y"], capture_output=True, text=True, timeout=4)
        return res.returncode == 0
    except Exception:
        return False

def open_virtual_drive(drive_letter: str):
    """Opens native Windows File Explorer focused on the virtual drive."""
    target = f"{drive_letter.rstrip('\\')}\\"
    try:
        subprocess.Popen(["explorer.exe", target])
    except Exception as e:
        print(f"[VirtualDrive] Could not open explorer: {e}")

def is_drive_mounted(drive_letter: str) -> bool:
    """Checks whether the specified drive letter is currently mounted."""
    clean = drive_letter.upper().rstrip(":") + ":"
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    all_letters = list(string.ascii_uppercase)
    for i in range(26):
        if bitmask & (1 << i):
            if f"{all_letters[i]}:" == clean:
                return True
    return False
