"""
LaptopShare Integration Tests
Tests TLS socket handshake, PIN verification, chunk streaming,
SHA-256 integrity, folder structure preservation, and resume capability.
"""

import os
import sys
import time
import shutil
import hashlib
import tempfile
import threading
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.transfer_server import TransferServer
from core.transfer_client import TransferClient
from core.file_manager import build_transfer_manifest, calculate_sha256
from core.config import ConfigManager

TEST_PORT = 52199
TEST_PIN = "654321"

def test_full_pipeline():
    print("=" * 60)
    print("STARTING LAPTOPSHARE PIPELINE INTEGRATION TESTS")
    print("=" * 60)

    # 1. Setup temporary sender and receiver directories
    base_tmp = Path(tempfile.mkdtemp(prefix="laptopshare_test_"))
    sender_dir = base_tmp / "sender"
    receiver_dir = base_tmp / "receiver"
    sender_dir.mkdir()
    receiver_dir.mkdir()

    print(f"[Test] Temp sender directory: {sender_dir}")
    print(f"[Test] Temp receiver directory: {receiver_dir}")

    # Create test files
    # File 1: Small text file
    f1 = sender_dir / "document.txt"
    f1.write_text("Hello from Old Laptop to Lenovo LOQ over LaptopShare!\n" * 100, encoding="utf-8")

    # File 2: Nested folder structure
    nested = sender_dir / "Photos" / "2024"
    nested.mkdir(parents=True)
    f2 = nested / "vacation.dat"
    f2.write_bytes(os.urandom(1024 * 512))  # 512 KB random binary

    # File 3: Larger file (5 MB) to test multiple chunks
    f3 = sender_dir / "large_archive.zip"
    f3.write_bytes(b"DATA_CHUNK_TEST_" * (1024 * 320))  # ~5.1 MB

    f1_hash = calculate_sha256(str(f1))
    f2_hash = calculate_sha256(str(f2))
    f3_hash = calculate_sha256(str(f3))

    print(f"[Test] Created test files with hashes:\n  f1: {f1_hash}\n  f2: {f2_hash}\n  f3: {f3_hash}")

    # Configure receiver
    cfg = ConfigManager().get()
    cfg.transfer_port = TEST_PORT
    cfg.current_pin = TEST_PIN
    cfg.download_dir = str(receiver_dir)

    server = TransferServer(port=TEST_PORT)

    # Auto-approve callback
    server_approvals = []
    def on_approval(req):
        print(f"[Server] Approving transfer request from {req.get('peer_name')}")
        server_approvals.append(req)
        server.approve_transfer(req["req_id"], accepted=True, save_dir=str(receiver_dir))

    server_completed_files = []
    def on_file_completed(rel_path, verified):
        print(f"[Server] File completed on receiver: {rel_path} (Verified={verified})")
        server_completed_files.append((rel_path, verified))

    server.on_approval_required = on_approval
    server.on_file_completed = on_file_completed

    server.start()
    time.sleep(1.0)

    try:
        # TEST 1: Bad PIN rejection
        print("\n--- Test 1: PIN Authentication Verification ---")
        client_bad_pin = TransferClient(target_ip="127.0.0.1", target_port=TEST_PORT, pin="000000")
        bad_pin_result = [None]
        bad_pin_event = threading.Event()

        def on_bad_pin_finished(success, msg):
            bad_pin_result[0] = (success, msg)
            bad_pin_event.set()

        client_bad_pin.on_finished = on_bad_pin_finished
        manifest, total_b = build_transfer_manifest([str(f1)])
        client_bad_pin.send_files_thread(manifest, total_b)
        bad_pin_event.wait(timeout=10.0)

        assert bad_pin_result[0] is not None, "Bad PIN test timed out"
        assert bad_pin_result[0][0] is False, "Transfer should have failed with bad PIN"
        print(f"[Test 1 PASSED] Rejection verified: {bad_pin_result[0][1]}")

        # TEST 2: Successful Multi-File Transfer with Nested Directories
        print("\n--- Test 2: Multi-File Chunked Transfer with Nested Folders ---")
        client = TransferClient(target_ip="127.0.0.1", target_port=TEST_PORT, pin=TEST_PIN)
        transfer_result = [None]
        transfer_event = threading.Event()

        def on_transfer_finished(success, msg):
            transfer_result[0] = (success, msg)
            transfer_event.set()

        client.on_finished = on_transfer_finished
        all_manifest, all_total = build_transfer_manifest([str(f1), str(nested.parent), str(f3)])
        print(f"[Test] Manifest contains {len(all_manifest)} files, {all_total} total bytes.")

        client.send_files_thread(all_manifest, all_total)
        transfer_event.wait(timeout=30.0)

        assert transfer_result[0] is not None, "Transfer timed out"
        assert transfer_result[0][0] is True, f"Transfer failed: {transfer_result[0][1]}"
        print(f"[Test 2 PASSED] Multi-file transfer completed successfully: {transfer_result[0][1]}")

        # Verify destination files and SHA-256 hashes
        rf1 = receiver_dir / "document.txt"
        rf2 = receiver_dir / "Photos" / "2024" / "vacation.dat"
        rf3 = receiver_dir / "large_archive.zip"

        assert rf1.exists(), "rf1 does not exist on receiver!"
        assert rf2.exists(), "rf2 (nested directory) does not exist on receiver!"
        assert rf3.exists(), "rf3 (large file) does not exist on receiver!"

        assert calculate_sha256(str(rf1)) == f1_hash, "rf1 SHA-256 hash mismatch!"
        assert calculate_sha256(str(rf2)) == f2_hash, "rf2 SHA-256 hash mismatch!"
        assert calculate_sha256(str(rf3)) == f3_hash, "rf3 SHA-256 hash mismatch!"
        print("[Test 2 Hash Check] All 3 files have identical SHA-256 hashes to sender originals!")

        # TEST 3: Resume Support Verification
        print("\n--- Test 3: Interruption & Resume Offset Support ---")
        # Create a new 8 MB file on sender
        f_resume = sender_dir / "resume_test.bin"
        resume_bytes = b"RESUME_PATTERN_XYZ_" * (1024 * 400)  # ~7.8 MB
        f_resume.write_bytes(resume_bytes)
        f_resume_hash = calculate_sha256(str(f_resume))

        # Simulate a partial file on the receiver (first 3 MB only)
        rf_partial = receiver_dir / "resume_test.bin"
        partial_len = 1024 * 1024 * 3
        rf_partial.write_bytes(resume_bytes[:partial_len])
        print(f"[Test] Pre-created partial receiver file with {partial_len} bytes.")

        # Now send the file using client. The receiver should detect 3MB and request resume from 3MB
        resume_client = TransferClient(target_ip="127.0.0.1", target_port=TEST_PORT, pin=TEST_PIN)
        resume_res = [None]
        resume_event = threading.Event()
        resume_client.on_finished = lambda s, m: (resume_res.__setitem__(0, (s, m)), resume_event.set())

        r_manifest, r_total = build_transfer_manifest([str(f_resume)])
        resume_client.send_files_thread(r_manifest, r_total)
        resume_event.wait(timeout=20.0)

        assert resume_res[0] is not None and resume_res[0][0] is True, f"Resume transfer failed: {resume_res[0]}"
        assert rf_partial.stat().st_size == len(resume_bytes), "Resumed file size incorrect!"
        assert calculate_sha256(str(rf_partial)) == f_resume_hash, "Resumed file SHA-256 hash mismatch!"
        print(f"[Test 3 PASSED] Resume successfully completed and verified: {resume_res[0][1]}")

        print("\n" + "=" * 60)
        print("ALL TESTS PASSED WITH 100% SUCCESS!")
        print("=" * 60)

    finally:
        server.stop()
        try:
            shutil.rmtree(base_tmp, ignore_errors=True)
        except Exception:
            pass

if __name__ == "__main__":
    test_full_pipeline()
