r"""
LaptopShare Virtual Drive & Windows File Explorer Manager
Mounts the connected laptop as a native virtual drive (e.g. U:\) under "This PC"
in Windows File Explorer with custom drive label 'USB-C Connected Laptop'.
"""

import os
import sys
import socket
import subprocess
import string
import ctypes
import winreg
from pathlib import Path
from typing import Tuple, Optional, List

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

DEFAULT_DRIVE_LETTER = "U:"
DEFAULT_DRIVE_LABEL = "USB-C Connected Laptop"
DEFAULT_ETHERNET_DRIVE_LETTER = "E:"
DEFAULT_ETHERNET_DRIVE_LABEL = "Ethernet Connected Laptop"

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

def is_webdav_service_reachable(remote_ip: str, port: int = 52145, timeout: float = 0.8) -> bool:
    """Fast pre-flight check to verify if remote WebDAV port is active before attempting net use."""
    try:
        with socket.create_connection((remote_ip, port), timeout=timeout):
            return True
    except Exception:
        return False

def get_webclient_basic_auth_level() -> int:
    """Reads BasicAuthLevel from HKLM\\SYSTEM\\CurrentControlSet\\Services\\WebClient\\Parameters."""
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services\WebClient\Parameters", 0, winreg.KEY_READ)
        val, _ = winreg.QueryValueEx(key, "BasicAuthLevel")
        return int(val)
    except Exception:
        return 1

def enable_windows_webclient_permissions() -> Tuple[bool, str]:
    """
    Elevates via UAC to set BasicAuthLevel = 2 and FileSizeLimitInBytes = 4GB,
    configures WebClient to start automatically, and restarts the service.
    This permanently eliminates Windows File Explorer 'Access is Denied' / 'No Permission' errors.
    """
    import base64
    ps_body = (
        "Set-ItemProperty -Path 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\WebClient\\Parameters' -Name 'BasicAuthLevel' -Value 2 -Type DWord\n"
        "Set-ItemProperty -Path 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\WebClient\\Parameters' -Name 'FileSizeLimitInBytes' -Value 4294967295 -Type DWord\n"
        "Set-Service -Name WebClient -StartupType Automatic\n"
        "Restart-Service -Name WebClient -Force\n"
    )
    enc = base64.b64encode(ps_body.encode("utf-16le")).decode("ascii")
    launch_script = f"Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -NonInteractive -EncodedCommand {enc}'"
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", launch_script],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=CREATE_NO_WINDOW
        )
        return True, "Windows permission update requested. Please click 'Yes' on the Windows UAC confirmation dialog."
    except Exception as e:
        return False, f"Could not launch permission update: {e}"

def mount_usb_laptop_drive(
    remote_ip: str,
    port: int = 52145,
    preferred_letter: str = DEFAULT_DRIVE_LETTER,
    drive_label: str = DEFAULT_DRIVE_LABEL,
    open_explorer: bool = True
) -> Tuple[bool, str, str]:
    """
    Mounts the remote laptop as a virtual drive in Windows File Explorer without freezing or lagging.
    Returns: (success: bool, drive_letter: str, message: str)
    """
    # 1. Fast pre-flight check: ensure remote port is reachable within 0.8s
    if not is_webdav_service_reachable(remote_ip, port, timeout=0.8):
        return False, "", f"Cannot reach remote laptop at {remote_ip}:{port}. Ensure LaptopShare is running on the other laptop."

    available = get_available_drive_letters(preferred_letter)
    if not available:
        return False, "", "No free drive letters available on this PC."

    target_letter = available[0]

    # Ensure Windows WebClient service is active
    try:
        subprocess.run(["sc", "start", "webclient"], capture_output=True, timeout=2, creationflags=CREATE_NO_WINDOW)
    except Exception:
        pass

    # Ensure target drive letter is unmapped
    unmount_usb_laptop_drive(target_letter)

    url_target = f"http://{remote_ip}:{port}/"
    unc_target = f"\\\\{remote_ip}@{port}\\DavWWWRoot"

    # Attempt 1: WebDAV HTTP mount: net use <letter> http://<ip>:<port>/ /persistent:no
    cmd1 = ["net", "use", target_letter, url_target, "/persistent:no"]
    try:
        res1 = subprocess.run(cmd1, capture_output=True, text=True, timeout=4, creationflags=CREATE_NO_WINDOW)
        if res1.returncode == 0:
            set_windows_explorer_drive_label(url_target, target_letter, drive_label)
            if open_explorer:
                open_virtual_drive(target_letter)
            return True, target_letter, f"Successfully mounted remote laptop as {target_letter}\\ ({drive_label})!"
    except Exception as e:
        print(f"[VirtualDrive] Method 1 failed: {e}")

    # Attempt 2: UNC mount: net use <letter> \\ip@port\DavWWWRoot /persistent:no
    cmd2 = ["net", "use", target_letter, unc_target, "/persistent:no"]
    try:
        res2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=4, creationflags=CREATE_NO_WINDOW)
        if res2.returncode == 0:
            set_windows_explorer_drive_label(unc_target, target_letter, drive_label)
            if open_explorer:
                open_virtual_drive(target_letter)
            return True, target_letter, f"Successfully mounted remote laptop as {target_letter}\\ ({drive_label})!"
    except Exception as e:
        print(f"[VirtualDrive] Method 2 failed: {e}")

    # NOTE: We intentionally DO NOT launch raw UNC in explorer.exe on failure!
    # Raw UNC lookup on unmounted WebDAV causes explorer.exe to hang, freeze, and fail with "Access is Denied".
    auth_level = get_webclient_basic_auth_level()
    if auth_level < 2:
        return False, "", (
            "WINDOWS_PERMISSION_REQUIRED: Windows WebClient policy (BasicAuthLevel=1) blocks plain HTTP network drive mapping.\n\n"
            "Click '🔓 1-Click Fix Permissions' to unlock Windows File Explorer access, or use the built-in Remote File Explorer."
        )

    return False, "", "Windows WebClient could not map the network drive. Please use the built-in Remote File Explorer or Web Explorer."

def mount_ethernet_laptop_drive(
    remote_ip: str,
    port: int = 52145,
    preferred_letter: str = DEFAULT_ETHERNET_DRIVE_LETTER,
    drive_label: str = DEFAULT_ETHERNET_DRIVE_LABEL,
    open_explorer: bool = True
) -> Tuple[bool, str, str]:
    """Mounts remote laptop connected via Ethernet cable as Drive E: (or next available letter)."""
    return mount_usb_laptop_drive(
        remote_ip=remote_ip,
        port=port,
        preferred_letter=preferred_letter,
        drive_label=drive_label,
        open_explorer=open_explorer
    )

def cleanup_stale_laptopshare_drives():
    """
    Scans for and cleanly removes any leftover WebDAV drive mappings from previous sessions.
    This prevents Windows File Explorer from hanging, lagging, or throwing network errors.
    """
    try:
        res = subprocess.run(["net", "use"], capture_output=True, text=True, timeout=2, creationflags=CREATE_NO_WINDOW)
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                if "DavWWWRoot" in line or "@52145" in line:
                    parts = line.split()
                    for p in parts:
                        if len(p) == 2 and p[1] == ":" and p[0].isalpha():
                            subprocess.run(["net", "use", p, "/delete", "/y"], capture_output=True, timeout=2, creationflags=CREATE_NO_WINDOW)
    except Exception:
        pass

def unmount_usb_laptop_drive(drive_letter: str) -> bool:
    """Safely unmounts a mapped virtual drive."""
    clean_letter = drive_letter.strip().rstrip("\\")
    if not clean_letter.endswith(":"):
        clean_letter += ":"
    try:
        res = subprocess.run(["net", "use", clean_letter, "/delete", "/y"], capture_output=True, text=True, timeout=4, creationflags=CREATE_NO_WINDOW)
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
