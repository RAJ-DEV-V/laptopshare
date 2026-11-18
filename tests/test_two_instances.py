"""
LaptopShare Two-Instance Concurrency & Large File Test
Tests two distinct local instances exchanging a large file over TLS sockets.
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
from core.transfer_client import TransferClient
from core.file_manager import build_transfer_manifest, calculate_sha256

PORT_A = 52170
PORT_B = 52171
PIN_B = "987654"

def test_two_instances_large_file():
    print("=" * 60)
    print("TESTING TWO LAPTOPSHARE INSTANCES & LARGE FILE STREAM (50 MB)")
    print("=" * 60)

    base_tmp = Path(tempfile.mkdtemp(prefix="laptopshare_dual_"))
    dir_a = base_tmp / "laptop_a_old"
    dir_b = base_tmp / "laptop_b_lenovo_loq"
    dir_a.mkdir()
    dir_b.mkdir()

    # Create 50 MB test file on Laptop A
    large_file = dir_a / "video_clip_50mb.mkv"
    print("[Instance A] Generating 50 MB test binary file...")
    chunk_pattern = os.urandom(1024 * 1024)  # 1 MB pattern
    with open(large_file, "wb") as f:
        for _ in range(50):
            f.write(chunk_pattern)

    original_hash = calculate_sha256(str(large_file))
    print(f"[Instance A] 50 MB file generated. SHA-256: {original_hash}")

    # Start Instance B (Receiver)
    server_b = TransferServer(port=PORT_B)

    def on_approval_b(req):
        print(f"[Instance B - Lenovo LOQ] Approving transfer from {req.get('peer_name')}")
        server_b.approve_transfer(req["req_id"], accepted=True, save_dir=str(dir_b))

    server_b.on_approval_required = on_approval_b
    server_b.start()
    time.sleep(0.5)

    try:
        # Start Instance A (Sender) sending to Instance B
        client_a = TransferClient(target_ip="127.0.0.1", target_port=PORT_B, pin=PIN_B)
        # Note: We need server_b's ConfigManager PIN to match PIN_B
        from core.config import ConfigManager
        ConfigManager().get().current_pin = PIN_B

        done_event = threading.Event()
        result_flag = [False]

        def on_progress(f_id, rel, done, total, t_done, t_all, speed, eta):
            pct = int((t_done / t_all) * 100)
            mb_done = done / (1024 * 1024)
            mb_total = total / (1024 * 1024)
            speed_mb = speed / (1024 * 1024)
            print(f"\r[Transfer A -> B] {pct}% | {mb_done:.1f}/{mb_total:.1f} MB @ {speed_mb:.1f} MB/s | ETA: {eta:.1f}s", end="", flush=True)

        def on_finished(success, msg):
            print(f"\n[Instance A] Finished: {msg}")
            result_flag[0] = success
            done_event.set()

        client_a.on_progress = on_progress
        client_a.on_finished = on_finished

        manifest, total_b = build_transfer_manifest([str(large_file)])
        client_a.send_files_thread(manifest, total_b)
        done_event.wait(timeout=60.0)

        assert result_flag[0] is True, "50 MB transfer failed!"
        received_file = dir_b / "video_clip_50mb.mkv"
        assert received_file.exists(), "Received file not found on Instance B!"
        assert received_file.stat().st_size == 50 * 1024 * 1024, "Received file size mismatch!"

        received_hash = calculate_sha256(str(received_file))
        assert received_hash == original_hash, "Checksum mismatch on 50 MB transfer!"
        print(f"[Verification] SHA-256 match verified: {received_hash}")
        print("\n>>> TWO-INSTANCE LARGE FILE TEST PASSED 100%! <<<")

    finally:
        server_b.stop()
        try:
            shutil.rmtree(base_tmp, ignore_errors=True)
        except Exception:
            pass

if __name__ == "__main__":
    test_two_instances_large_file()
