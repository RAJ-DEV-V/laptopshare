"""
LaptopShare Remote Browse & Pull Integration Test
Tests remote authorization, directory listing, and pulling files/folders with SHA-256 verification.
"""

import os
import sys
import time
import shutil
import tempfile
import threading
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.transfer_server import TransferServer
from core.remote_browser_client import RemoteBrowserClient
from core.config import ConfigManager
from core.file_manager import calculate_sha256

TEST_PORT = 52188
TEST_PIN = "777888"

def test_remote_browse_pipeline():
    print("=" * 60)
    print("TESTING REMOTE BROWSE & CHOOSE-TO-COPY FUNCTIONALITY")
    print("=" * 60)

    base_tmp = Path(tempfile.mkdtemp(prefix="laptopshare_browse_"))
    host_laptop_dir = base_tmp / "old_laptop_files"
    dest_laptop_dir = base_tmp / "lenovo_loq_downloads"
    host_laptop_dir.mkdir()
    dest_laptop_dir.mkdir()

    # Create dummy remote files on the host laptop (old laptop)
    f1 = host_laptop_dir / "project_report.docx"
    f1.write_text("Confidential Project Report for Lenovo LOQ\n" * 50, encoding="utf-8")

    subfolder = host_laptop_dir / "Photos_2024"
    subfolder.mkdir()
    f2 = subfolder / "trip_photo.raw"
    f2.write_bytes(os.urandom(1024 * 300))  # 300 KB binary

    f1_hash = calculate_sha256(str(f1))
    f2_hash = calculate_sha256(str(f2))

    # Configure server (Old Laptop)
    cfg = ConfigManager().get()
    cfg.transfer_port = TEST_PORT
    cfg.current_pin = TEST_PIN
    cfg.allow_remote_browsing = True

    server = TransferServer(port=TEST_PORT)

    # Remote browsing approval callback (Simulates clicking "Grant Access" on the old laptop)
    def on_browse_approval(req):
        print(f"[Old Laptop Host] Received permission request from {req.get('peer_name')}. Granting access...")
        server.approve_browse(req["req_id"], accepted=True)

    server.on_browse_approval_required = on_browse_approval
    server.start()
    time.sleep(0.5)

    try:
        # Step 1: Connect from Lenovo LOQ and request permission
        print("\n--- Step 1: Connecting and Requesting Browsing Permission ---")
        client = RemoteBrowserClient(target_ip="127.0.0.1", target_port=TEST_PORT, pin=TEST_PIN)
        success, msg = client.connect()
        assert success is True, f"Failed to connect: {msg}"
        print(f"[Success] {msg}")
        print(f"[Success] Remote Roots available: {len(client.roots)} roots")

        # Step 2: List directory on Old Laptop
        print("\n--- Step 2: Browsing Remote Directory ---")
        ok, items, err = client.list_directory(str(host_laptop_dir))
        assert ok is True, f"Failed to list directory: {err}"
        print(f"[Success] Found {len(items)} items in {host_laptop_dir}:")
        for it in items:
            t = "DIR" if it["is_dir"] else "FILE"
            print(f"  [{t}] {it['name']} ({it['size']} bytes)")

        # Step 3: Choose files/folders to copy to Lenovo LOQ
        print("\n--- Step 3: Pulling/Copying Selected Items to Local Laptop ---")
        done_event = threading.Event()
        result_flag = [False]

        def on_finished(success, msg):
            print(f"[Client Pull] Finished: success={success}, msg={msg}")
            result_flag[0] = success
            done_event.set()

        # We select f1 and the subfolder
        selected_paths = [str(f1), str(subfolder)]
        client.pull_files_thread(
            remote_paths=selected_paths,
            destination_dir=str(dest_laptop_dir),
            on_finished=on_finished
        )
        done_event.wait(timeout=30.0)

        assert result_flag[0] is True, "Pull transfer failed!"

        # Step 4: Verify copied files on destination laptop
        print("\n--- Step 4: Integrity Verification of Copied Files ---")
        copied_f1 = dest_laptop_dir / "project_report.docx"
        copied_f2 = dest_laptop_dir / "Photos_2024" / "trip_photo.raw"

        assert copied_f1.exists(), "Copied file 1 missing!"
        assert copied_f2.exists(), "Copied folder file missing!"

        assert calculate_sha256(str(copied_f1)) == f1_hash, "SHA-256 mismatch on file 1!"
        assert calculate_sha256(str(copied_f2)) == f2_hash, "SHA-256 mismatch on file 2!"
        print(f"[Success] SHA-256 hashes verified 100% byte-for-byte!")

        client.disconnect()
        print("\n>>> REMOTE BROWSE & CHOOSE-TO-COPY TEST PASSED 100%! <<<")

    finally:
        server.stop()
        try:
            shutil.rmtree(base_tmp, ignore_errors=True)
        except Exception:
            pass

if __name__ == "__main__":
    test_remote_browse_pipeline()
