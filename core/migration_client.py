"""
LaptopShare Migration Client
Connects to an old PC, triggers category scans (Desktop, Documents, Photos, Browser Data),
and pulls the entire selected profile seamlessly into the new PC.
"""

import os
import time
import socket
import json
import uuid
import threading
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable, Tuple

from .config import ConfigManager, DEFAULT_TRANSFER_PORT
from .security import create_client_ssl_context
from .protocol import (
    MsgType,
    encode_json_message,
    read_message,
    decode_file_chunk_payload,
)
from .file_manager import sanitize_relative_path, calculate_sha256
from .history import HistoryManager, TransferRecord

class MigrationClient:
    def __init__(self, target_ip: str, target_port: int = DEFAULT_TRANSFER_PORT, pin: str = ""):
        self.target_ip = target_ip
        self.target_port = target_port
        self.pin = pin
        self.is_connected = False
        self.remote_device_name = target_ip
        self.categories: List[Dict[str, Any]] = []

        self._sock: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self.is_cancelled = False

    def connect_and_scan(self) -> Tuple[bool, str, List[Dict[str, Any]]]:
        """
        Connects to old laptop via TLS, requests migration authorization,
        and triggers a category scan.
        Returns (success, message, categories_list).
        """
        cfg = ConfigManager().get()
        raw_sock = None
        try:
            raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            raw_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
            raw_sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
            raw_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            raw_sock.settimeout(15.0)
            raw_sock.connect((self.target_ip, self.target_port))

            ssl_ctx = create_client_ssl_context()
            tls_sock = ssl_ctx.wrap_socket(raw_sock, server_hostname="LaptopShare-Peer")
            tls_sock.settimeout(95.0)  # User has up to 90s to click approve on old laptop
            self._sock = tls_sock

            # Send MIGRATE_SCAN_REQ
            tls_sock.sendall(encode_json_message(MsgType.MIGRATE_SCAN_REQ, {
                "device_name": cfg.device_name,
                "os": "Windows",
                "pin": self.pin,
            }))

            msg_type, payload = read_message(tls_sock)
            if msg_type != MsgType.MIGRATE_SCAN_RESP:
                self.disconnect()
                return False, "Unexpected response from old laptop.", []

            resp = json.loads(payload.decode("utf-8"))
            status = resp.get("status")

            if status == "BAD_PIN":
                self.disconnect()
                return False, "Incorrect connection PIN entered.", []
            elif status != "APPROVED":
                msg = resp.get("message", "Migration access declined on old laptop.")
                self.disconnect()
                return False, msg, []

            self.remote_device_name = resp.get("device_name", self.target_ip)
            self.categories = resp.get("categories", [])
            self.is_connected = True
            return True, f"Connected to {self.remote_device_name}!", self.categories

        except socket.timeout:
            self.disconnect()
            return False, "Connection timed out. Did you click approve on the old laptop?", []
        except ConnectionRefusedError:
            self.disconnect()
            return False, f"Could not reach {self.target_ip}:{self.target_port}. Is LaptopShare open on the old laptop?", []
        except Exception as e:
            self.disconnect()
            return False, f"Migration connection error: {e}", []

    def start_migration_thread(
        self,
        selected_category_ids: List[str],
        destination_dir: str,
        on_progress=None,
        on_file_completed=None,
        on_finished=None
    ) -> threading.Thread:
        """Runs migration transfer in a background worker thread."""
        t = threading.Thread(
            target=self._migration_worker,
            args=(selected_category_ids, destination_dir, on_progress, on_file_completed, on_finished),
            daemon=True,
            name=f"MigrationThread-{self.target_ip}"
        )
        t.start()
        return t

    def _migration_worker(
        self,
        selected_category_ids: List[str],
        destination_dir: str,
        on_progress=None,
        on_file_completed=None,
        on_finished=None
    ):
        with self._lock:
            if not self._sock or not self.is_connected:
                if on_finished:
                    on_finished(False, "Not connected to old laptop.")
                return

            self.is_cancelled = False
            start_time = time.time()
            transfer_id = str(uuid.uuid4())
            target_path = Path(destination_dir)
            target_path.mkdir(parents=True, exist_ok=True)
            active_file_handle = None
            total_files = 0
            total_bytes = 0

            try:
                # 1. Send MIGRATE_START_REQ
                self._sock.sendall(encode_json_message(MsgType.MIGRATE_START_REQ, {
                    "selected_category_ids": selected_category_ids
                }))

                msg_type, payload = read_message(self._sock)
                if msg_type != MsgType.MIGRATE_START_RESP:
                    raise ConnectionError("Invalid response from old laptop to migration start request.")

                resp = json.loads(payload.decode("utf-8"))
                if resp.get("status") != "APPROVED":
                    raise PermissionError(resp.get("message", "Migration start rejected."))

                files = resp.get("files", [])
                total_bytes = resp.get("total_bytes", 0)
                total_files = len(files)
                file_map = {f["file_id"]: f for f in files}

                # 2. Check existing files for RESUME offsets
                file_offsets = {}
                for item in files:
                    f_id = item["file_id"]
                    rel_p = sanitize_relative_path(item["rel_path"])
                    local_f = target_path / rel_p
                    existing_bytes = 0
                    if local_f.exists():
                        existing_bytes = local_f.stat().st_size
                        if existing_bytes >= item["size"]:
                            existing_bytes = item["size"]
                    file_offsets[f_id] = existing_bytes

                # Send MANIFEST_RESP with resume offsets
                self._sock.sendall(encode_json_message(MsgType.MANIFEST_RESP, {
                    "status": "APPROVED",
                    "offsets": file_offsets
                }))

                # Use generous timeout during large file streaming
                self._sock.settimeout(300.0)

                # 3. Receive migration stream
                bytes_received_total = sum(file_offsets.values())
                last_speed_check = time.time()
                bytes_since_check = 0
                current_speed = 0.0

                active_file_handle = None
                active_hasher = None
                current_file_meta = None
                current_file_received_bytes = 0

                while True:
                    if self.is_cancelled:
                        break

                    msg_type, payload = read_message(self._sock)

                    if msg_type == MsgType.FILE_START:
                        start_meta = json.loads(payload.decode("utf-8"))
                        f_id = start_meta["file_id"]
                        current_file_meta = file_map.get(f_id)
                        if not current_file_meta:
                            continue

                        rel_p = sanitize_relative_path(current_file_meta["rel_path"])
                        out_path = target_path / rel_p
                        out_path.parent.mkdir(parents=True, exist_ok=True)

                        start_offset = start_meta.get("offset", 0)
                        mode = "r+b" if (start_offset > 0 and out_path.exists()) else "wb"
                        active_file_handle = open(out_path, mode)
                        if start_offset > 0:
                            active_file_handle.seek(start_offset)
                        current_file_received_bytes = start_offset

                        active_hasher = hashlib.sha256()
                        if start_offset > 0 and out_path.exists():
                            try:
                                with open(out_path, "rb") as f_prev:
                                    p_read = 0
                                    while p_read < start_offset:
                                        to_r = min(1024 * 1024, start_offset - p_read)
                                        c = f_prev.read(to_r)
                                        if not c:
                                            break
                                        active_hasher.update(c)
                                        p_read += len(c)
                            except Exception as e:
                                print(f"[Migration] Prefix hash error: {e}")

                    elif msg_type == MsgType.FILE_CHUNK:
                        f_id, offset, chunk_data = decode_file_chunk_payload(payload)
                        chunk_len = len(chunk_data)

                        if active_file_handle:
                            active_file_handle.write(chunk_data)
                            if active_hasher is not None:
                                active_hasher.update(chunk_data)
                            current_file_received_bytes += chunk_len
                            bytes_received_total += chunk_len
                            bytes_since_check += chunk_len

                            now = time.time()
                            dt = now - last_speed_check
                            if dt >= 0.5:
                                current_speed = bytes_since_check / dt
                                bytes_since_check = 0
                                last_speed_check = now

                            eta = (total_bytes - bytes_received_total) / current_speed if current_speed > 0 else 0

                            if on_progress and current_file_meta:
                                on_progress(
                                    current_file_meta["file_id"],
                                    current_file_meta["rel_path"],
                                    current_file_received_bytes,
                                    current_file_meta["size"],
                                    bytes_received_total,
                                    total_bytes,
                                    current_speed,
                                    eta
                                )

                    elif msg_type == MsgType.FILE_END:
                        end_meta = json.loads(payload.decode("utf-8"))
                        f_id = end_meta["file_id"]
                        expected_sha256 = end_meta.get("sha256", "")

                        if active_file_handle:
                            active_file_handle.flush()
                            active_file_handle.close()
                            active_file_handle = None

                        meta = file_map.get(f_id)
                        checksum_ok = False
                        if meta:
                            if active_hasher is not None:
                                actual_sha256 = active_hasher.hexdigest()
                            else:
                                rel_p = sanitize_relative_path(meta["rel_path"])
                                final_p = str(target_path / rel_p)
                                actual_sha256 = calculate_sha256(final_p)

                            if actual_sha256.lower() == expected_sha256.lower():
                                checksum_ok = True
                                self._sock.sendall(encode_json_message(MsgType.FILE_ACK, {
                                    "file_id": f_id,
                                    "status": "OK"
                                }))
                            else:
                                self._sock.sendall(encode_json_message(MsgType.FILE_ACK, {
                                    "file_id": f_id,
                                    "status": "CHECKSUM_FAILED"
                                }))

                            if on_file_completed:
                                on_file_completed(meta["rel_path"], checksum_ok)

                    elif msg_type == MsgType.TRANSFER_COMPLETE:
                        duration = time.time() - start_time
                        HistoryManager().add_record(TransferRecord(
                            id=transfer_id,
                            direction="received (migrated)",
                            peer_name=self.remote_device_name,
                            peer_ip=self.target_ip,
                            files_count=total_files,
                            total_bytes=total_bytes,
                            status="Completed",
                            duration_sec=duration,
                            timestamp=time.time(),
                            destination_dir=str(target_path)
                        ))

                        if on_finished:
                            on_finished(True, f"PC Migration successfully completed ({total_files} files)!")
                        break

            except Exception as e:
                if active_file_handle:
                    try:
                        active_file_handle.close()
                    except Exception:
                        pass
                if on_finished:
                    on_finished(False, f"Migration transfer error: {e}")

    def cancel_migration(self):
        self.is_cancelled = True
        if self._sock:
            try:
                self._sock.sendall(encode_json_message(MsgType.CANCEL, {"reason": "Cancelled by user"}))
            except Exception:
                pass

    def disconnect(self):
        self.is_connected = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
