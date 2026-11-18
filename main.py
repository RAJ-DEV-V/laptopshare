"""
LaptopShare Main Entrypoint
Supports graphical desktop interface (PySide6) as well as headless / CLI mode.
"""

import sys
import os
import argparse
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Ensure Windows console supports UTF-8 characters cleanly
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from core.config import ConfigManager, APP_NAME, PROTOCOL_VERSION
from core.transfer_server import TransferServer
from core.transfer_client import TransferClient
from core.file_manager import build_transfer_manifest

def run_headless_receiver(port: int, pin: str, download_dir: str):
    import time
    print(f"[{APP_NAME}] Starting Headless Receiver on port {port}...")
    print(f"[{APP_NAME}] PIN required: {pin}")
    print(f"[{APP_NAME}] Destination folder: {download_dir}")

    cfg = ConfigManager().get()
    cfg.transfer_port = port
    cfg.current_pin = pin
    cfg.download_dir = download_dir

    server = TransferServer(port=port)

    # Auto-approve in headless test mode
    def on_approval(req):
        print(f"[{APP_NAME}] Received transfer request from {req.get('peer_name')} ({req.get('peer_ip')}). Auto-approving...")
        server.approve_transfer(req["req_id"], accepted=True, save_dir=download_dir)

    def on_progress(f_id, rel, done, total, t_done, t_all, speed, eta):
        pct = int((t_done / t_all) * 100) if t_all > 0 else 100
        print(f"\r[{APP_NAME}] Progress: {pct}% - {rel} ({done}/{total})", end="", flush=True)

    def on_finished(tid, success, msg):
        print(f"\n[{APP_NAME}] Transfer finished: success={success}, msg={msg}")

    server.on_approval_required = on_approval
    server.on_progress = on_progress
    server.on_transfer_finished = on_finished

    server.start()
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nStopping receiver...")
        server.stop()

def run_cli_sender(target_ip: str, port: int, pin: str, file_paths: list):
    import threading
    print(f"[{APP_NAME}] Sending to {target_ip}:{port} with PIN {pin}...")
    manifest, total_bytes = build_transfer_manifest(file_paths)
    if not manifest:
        print(f"[{APP_NAME}] No valid files to send!")
        sys.exit(1)

    print(f"[{APP_NAME}] Manifest ready: {len(manifest)} files ({total_bytes} bytes)")
    client = TransferClient(target_ip=target_ip, target_port=port, pin=pin)

    done_event = threading.Event()
    success_flag = [False]

    def on_progress(f_id, rel, done, total, t_done, t_all, speed, eta):
        pct = int((t_done / t_all) * 100) if t_all > 0 else 100
        print(f"\r[{APP_NAME}] Sending: {pct}% - {rel} ({done}/{total})", end="", flush=True)

    def on_finished(success, msg):
        print(f"\n[{APP_NAME}] Finished: {msg}")
        success_flag[0] = success
        done_event.set()

    client.on_progress = on_progress
    client.on_finished = on_finished

    client.send_files_thread(manifest, total_bytes)
    done_event.wait()
    sys.exit(0 if success_flag[0] else 1)

def main():
    parser = argparse.ArgumentParser(description=f"{APP_NAME} v{PROTOCOL_VERSION}")
    parser.add_argument("--port", type=int, help="Override transfer port")
    parser.add_argument("--discovery-port", type=int, help="Override discovery port")
    parser.add_argument("--pin", type=str, help="Override connection PIN")
    parser.add_argument("--name", type=str, help="Override device name")
    parser.add_argument("--dir", type=str, help="Override download folder")
    parser.add_argument("--headless-receiver", action="store_true", help="Run as headless receiver")
    parser.add_argument("--send-cli", action="store_true", help="Send files via command line")
    parser.add_argument("--target", type=str, help="Target IP for CLI sender")
    parser.add_argument("files", nargs="*", help="Files or folders to send in CLI mode")

    args = parser.parse_args()

    # Load configuration
    cfg_mgr = ConfigManager()
    cfg = cfg_mgr.get()

    if args.port:
        cfg.transfer_port = args.port
    if args.discovery_port:
        cfg.discovery_port = args.discovery_port
    if args.pin:
        cfg.current_pin = args.pin
    if args.name:
        cfg.device_name = args.name
    if args.dir:
        cfg.download_dir = args.dir

    if args.headless_receiver:
        run_headless_receiver(
            port=cfg.transfer_port,
            pin=cfg.current_pin,
            download_dir=cfg.download_dir
        )
        return

    if args.send_cli:
        if not args.target:
            print("Error: --target IP is required for --send-cli")
            sys.exit(1)
        run_cli_sender(
            target_ip=args.target,
            port=cfg.transfer_port,
            pin=cfg.current_pin,
            file_paths=args.files
        )
        return

    # Windows AppUserModelID setup for taskbar grouping and icon
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("LaptopShare.App.1.0")
    except Exception:
        pass

    # Launch PySide6 GUI
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon
    from PySide6.QtCore import Qt
    from ui.main_window import MainWindow

    # High DPI support
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(PROTOCOL_VERSION)

    icon_path = Path(__file__).resolve().parent / "assets" / "icon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow()
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
