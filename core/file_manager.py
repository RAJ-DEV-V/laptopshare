"""
LaptopShare File Manager
Handles file scanning, folder recursion, relative path sanitization,
checksum computation, and safe destination writing.
"""

import os
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

def sanitize_relative_path(rel_path: str) -> Path:
    """
    Sanitizes an incoming relative path to prevent directory traversal.
    Ensures no leading slashes, drive letters, or '..' elements exist.
    """
    # Replace backslashes with forward slashes for uniform splitting
    normalized = rel_path.replace("\\", "/").strip("/ ")
    parts = [p for p in normalized.split("/") if p and p != "." and p != ".."]
    if not parts:
        return Path("received_file")
    return Path(*parts)

def build_transfer_manifest(paths: List[str]) -> Tuple[List[Dict[str, Any]], int]:
    """
    Given a list of file or folder paths, builds a transfer manifest.
    Returns (manifest_list, total_bytes).
    Each manifest item has:
      - file_id: int
      - abs_path: str (local absolute path for reading)
      - rel_path: str (relative path preserving folder structure)
      - size: int
    """
    manifest = []
    total_bytes = 0
    file_id_counter = 1

    for p_str in paths:
        p = Path(p_str)
        if not p.exists():
            continue

        if p.is_file():
            size = p.stat().st_size
            manifest.append({
                "file_id": file_id_counter,
                "abs_path": str(p),
                "rel_path": p.name,
                "size": size,
            })
            total_bytes += size
            file_id_counter += 1
        elif p.is_dir():
            base_parent = p.parent
            for root, dirs, files in os.walk(p):
                for fname in files:
                    full_p = Path(root) / fname
                    try:
                        size = full_p.stat().st_size
                        # Relative path relative to parent folder so base folder name is kept
                        rel = full_p.relative_to(base_parent).as_posix()
                        manifest.append({
                            "file_id": file_id_counter,
                            "abs_path": str(full_p),
                            "rel_path": rel,
                            "size": size,
                        })
                        total_bytes += size
                        file_id_counter += 1
                    except (PermissionError, FileNotFoundError):
                        continue

    return manifest, total_bytes

def calculate_sha256(file_path: str, max_bytes: Optional[int] = None, progress_callback=None) -> str:
    """
    Computes SHA-256 hash of a file incrementally up to max_bytes (or whole file).
    Progress callback can be provided for large files.
    """
    hasher = hashlib.sha256()
    bytes_read = 0
    chunk_size = 1024 * 1024  # 1 MB read buffer

    with open(file_path, "rb") as f:
        while True:
            to_read = chunk_size
            if max_bytes is not None:
                remaining = max_bytes - bytes_read
                if remaining <= 0:
                    break
                to_read = min(chunk_size, remaining)

            data = f.read(to_read)
            if not data:
                break
            hasher.update(data)
            bytes_read += len(data)
            if progress_callback:
                progress_callback(bytes_read)

    return hasher.hexdigest()

def format_file_size(size_bytes: int) -> str:
    """Formats bytes into human readable format (B, KB, MB, GB, TB)."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    elif size_bytes < 1024 * 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024 * 1024):.2f} TB"

def format_transfer_speed(bytes_per_sec: float) -> str:
    """Formats transfer speed into MB/s or KB/s."""
    if bytes_per_sec < 1024 * 1024:
        return f"{bytes_per_sec / 1024:.1f} KB/s"
    else:
        return f"{bytes_per_sec / (1024 * 1024):.1f} MB/s"

def format_time_remaining(seconds: float) -> str:
    """Formats estimated remaining seconds into clean mm:ss or hh:mm:ss."""
    if seconds < 0 or seconds > 86400 * 7:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
