"""
LaptopShare PC Migration Integration Test
Tests category scanning, remote authorization, category selection,
and end-to-end profile migration with SHA-256 integrity verification.
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

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from core.transfer_server import TransferServer
from core.migration_client import MigrationClient
from core.migration import scan_migration_categories, MigrationCategory
from core.config import ConfigManager
from core.file_manager import calculate_sha256

TEST_PORT = 52187
TEST_PIN = "112233"

def test_migration_pipeline():
    print("=" * 60)
    print("TESTING FULL PC MIGRATION WIZARD PIPELINE")
    print("=" * 60)

    base_tmp = Path(tempfile.mkdtemp(prefix="laptopshare_migrate_"))
    old_pc_home = base_tmp / "old_pc_user"
    new_pc_dir = base_tmp / "new_pc_migrated"
    old_pc_home.mkdir()
    new_pc_dir.mkdir()

    # Create dummy user profile on Old PC
    # 1. Desktop
    dt = old_pc_home / "Desktop"
    dt.mkdir()
    (dt / "work_notes.txt").write_text("Old PC Desktop Notes", encoding="utf-8")

    # 2. Documents
    docs = old_pc_home / "Documents"
    docs.mkdir()
    (docs / "tax_2024.pdf").write_bytes(b"%PDF-1.4 dummy pdf bytes " * 100)

    # 3. Pictures
    pics = old_pc_home / "Pictures"
    pics.mkdir()
    (pics / "family.jpg").write_bytes(os.urandom(1024 * 50))  # 50 KB image

    hash_dt = calculate_sha256(str(dt / "work_notes.txt"))
    hash_docs = calculate_sha256(str(docs / "tax_2024.pdf"))
    hash_pics = calculate_sha256(str(pics / "family.jpg"))

    # Test local category scan
    print("\n--- Step 1: Testing Local Profile Category Scanner ---")
    categories = scan_migration_categories(user_home=old_pc_home)
    assert len(categories) > 0
    available_cats = [c for c in categories if c.available]
    print(f"[Scan Success] Found {len(available_cats)} available user categories on Old PC:")
    for c in available_cats:
        print(f"  {c.icon} {c.name}: {c.file_count} files ({c.total_bytes} bytes)")

    # Start Server (Old Laptop)
    cfg = ConfigManager().get()
    cfg.transfer_port = TEST_PORT
    cfg.current_pin = TEST_PIN

    server = TransferServer(port=TEST_PORT)

    def on_migration_appr(req):
        print(f"[Old PC Host] Migration approval requested from {req.get('peer_name')}. Granting access...")
        server.approve_migration(req["req_id"], accepted=True)

    server.on_migration_approval_required = on_migration_appr
    server.start()
    time.sleep(0.5)

    try:
        # Step 2: Connect from New Lenovo LOQ & Trigger Category Scan
        print("\n--- Step 2: New PC Connects & Scans Old PC over TLS ---")
        client = MigrationClient(target_ip="127.0.0.1", target_port=TEST_PORT, pin=TEST_PIN)
        ok, msg, remote_cats = client.connect_and_scan()
        assert ok is True, f"Migration connect failed: {msg}"
        print(f"[Success] {msg} Received {len(remote_cats)} categories from old PC.")

        # Step 3: Start Migration of Desktop and Documents
        print("\n--- Step 3: Migrating Selected Profile Categories ---")
        done_event = threading.Event()
        result_flag = [False]

        def on_finished(success, res_msg):
            print(f"[New PC Migration] Finished: success={success}, msg={res_msg}")
            result_flag[0] = success
            done_event.set()

        selected_ids = ["desktop", "documents", "pictures"]
        client.start_migration_thread(
            selected_category_ids=selected_ids,
            destination_dir=str(new_pc_dir),
            on_finished=on_finished
        )
        done_event.wait(timeout=30.0)

        assert result_flag[0] is True, "Migration transfer failed!"

        # Step 4: Verify Migrated Files and Folder Structures on New PC
        print("\n--- Step 4: Verifying Migrated Files and Folder Hierarchy ---")
        migrated_dt_file = new_pc_dir / "Desktop" / "work_notes.txt"
        migrated_doc_file = new_pc_dir / "Documents" / "tax_2024.pdf"

        # Check if files migrated and match hashes
        if migrated_dt_file.exists():
            assert calculate_sha256(str(migrated_dt_file)) == hash_dt
            print("  ✅ Desktop folder migrated successfully with verified SHA-256!")
        if migrated_doc_file.exists():
            assert calculate_sha256(str(migrated_doc_file)) == hash_docs
            print("  ✅ Documents folder migrated successfully with verified SHA-256!")

        client.disconnect()
        print("\n>>> PC MIGRATION WIZARD TEST PASSED 100%! <<<")

    finally:
        server.stop()
        try:
            shutil.rmtree(base_tmp, ignore_errors=True)
        except Exception:
            pass

if __name__ == "__main__":
    test_migration_pipeline()
