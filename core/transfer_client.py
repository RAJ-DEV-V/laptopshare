"""
LaptopShare Sender Client
Connects via TLS socket to receiver, performs PIN authentication,
streams chunks, computes SHA-256, handles resume offsets, and emits progress.
"""

import os
import time
import socket
import json
import uuid
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable

from .config import ConfigManager, DEFAULT_TRANSFER_PORT
from .security import create_client_ssl_context
from .protocol import (
    MsgType,
    encode_json_message,
    encode_file_chunk,
    read_message,
    DEFAULT_CHUNK_SIZE,
)
from .file_manager import calculate_sha256
from .history import HistoryManager, TransferRecord

class TransferClient:
    def __init__(self, target_ip: str, target_port: int = DEFAULT_TRANSFER_PORT, pin: str = ""):
        self.target_ip = target_ip
        self.target_port = target_port
        self.pin = pin
        self.is_cancelled = False
        self._sock: Optional[socket.socket] = None

        # Callbacks (connected to Qt signals)
        self.on_connecting: Optional[Callable[[], None]] = None
        self.on_connected: Optional[Callable[[str], None]] = None
        self.on_waiting_approval: Optional[Callable[[], None]] = None
        self.on_transfer_started: Optional[Callable[[int, int], None]] = None
        self.on_progress: Optional[Callable[[int, str, int, int, int, int, float, float], None]] = None
        self.on_file_completed: Optional[Callable[[str, bool], None]] = None
        self.on_finished: Optional[Callable[[bool, str], None]] = None

    def cancel(self):
        """Cancels the current transfer."""
        self.is_cancelled = True
        if self._sock:
            try:
                self._sock.sendall(encode_json_message(MsgType.CANCEL, {"reason": "Cancelled by sender"}))
            except Exception:
                pass
            try:
                self._sock.close()
            except Exception:
                pass

    def send_files_thread(self, manifest: List[Dict[str, Any]], total_bytes: int):
        """Runs the file sending routine in a dedicated background worker thread."""
        thread = threading.Thread(
            target=self._send_files_worker,
            args=(manifest, total_bytes),
            daemon=True,
            name=f"SenderThread-{self.target_ip}"
        )
        thread.start()
        return thread

    def _send_files_worker(self, manifest: List[Dict[str, Any]], total_bytes: int):
        transfer_id = str(uuid.uuid4())
        start_time = time.time()
        receiver_name = self.target_ip
        total_files = len(manifest)
        bytes_transferred_total = 0
        cfg = ConfigManager().get()

        if self.on_connecting:
            self.on_connecting()

        raw_sock = None
        tls_sock = None

        try:
            # Create TCP connection with optimized high-performance LAN buffers (4MB window)
            raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            raw_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
            raw_sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
            raw_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            raw_sock.settimeout(15.0)
            raw_sock.connect((self.target_ip, self.target_port))

            # Establish TLS
            ssl_ctx = create_client_ssl_context()
            tls_sock = ssl_ctx.wrap_socket(raw_sock, server_hostname="LaptopShare-Peer")
            self._sock = tls_sock
            tls_sock.settimeout(30.0)

            # 1. Send HANDSHAKE_REQ
            tls_sock.sendall(encode_json_message(MsgType.HANDSHAKE_REQ, {
                "device_name": cfg.device_name,
                "os": "Windows",
                "pin": self.pin,
            }))

            # Read HANDSHAKE_RESP
            msg_type, payload = read_message(tls_sock)
            if msg_type != MsgType.HANDSHAKE_RESP:
                raise ConnectionError("Unexpected handshake response from receiver")

            resp_data = json.loads(payload.decode("utf-8"))
            status = resp_data.get("status")
            if status == "BAD_PIN":
                raise PermissionError("Connection rejected: Incorrect PIN code. Check receiver's PIN.")
            elif status != "APPROVED":
                raise ConnectionError(f"Connection rejected by receiver: {resp_data.get('message', 'Unknown error')}")

            receiver_name = resp_data.get("receiver_name", self.target_ip)
            if self.on_connected:
                self.on_connected(receiver_name)

            # 2. Send MANIFEST_REQ
            manifest_wire = [
                {
                    "file_id": item["file_id"],
                    "rel_path": item["rel_path"],
                    "size": item["size"],
                }
                for item in manifest
            ]

            if self.on_waiting_approval:
                self.on_waiting_approval()

            tls_sock.sendall(encode_json_message(MsgType.MANIFEST_REQ, {
                "files": manifest_wire,
                "total_bytes": total_bytes,
            }))

            # Wait for receiver approval (timeout 70 seconds)
            tls_sock.settimeout(75.0)
            msg_type, payload = read_message(tls_sock)
            tls_sock.settimeout(30.0)

            if msg_type != MsgType.MANIFEST_RESP:
                raise ConnectionError("Invalid response to manifest request")

            m_resp = json.loads(payload.decode("utf-8"))
            if m_resp.get("status") != "APPROVED":
                raise PermissionError(m_resp.get("message", "Transfer declined by receiver."))

            resume_offsets: Dict[int, int] = {
                int(k): v for k, v in m_resp.get("offsets", {}).items()
            }

            if self.on_transfer_started:
                self.on_transfer_started(total_files, total_bytes)

            # Use generous 300s socket timeout during active streaming of large videos/photos
            tls_sock.settimeout(300.0)

            # 3. Stream files
            import hashlib
            last_speed_check = time.time()
            bytes_since_speed_check = 0
            current_speed = 0.0

            # Pre-add existing offsets to bytes_transferred_total
            for f_item in manifest:
                offset = resume_offsets.get(f_item["file_id"], 0)
                bytes_transferred_total += offset

            for f_item in manifest:
                if self.is_cancelled:
                    break

                f_id = f_item["file_id"]
                abs_path = f_item["abs_path"]
                rel_path = f_item["rel_path"]
                file_size = f_item["size"]
                start_offset = resume_offsets.get(f_id, 0)

                # Send FILE_START immediately without blocking disk read
                tls_sock.sendall(encode_json_message(MsgType.FILE_START, {
                    "file_id": f_id,
                    "rel_path": rel_path,
                    "offset": start_offset,
                }))

                file_bytes_sent = start_offset
                hasher = hashlib.sha256()

                # If resuming, hash existing prefix
                if start_offset > 0 and Path(abs_path).exists():
                    try:
                        with open(abs_path, "rb") as f_pre:
                            pre_read = 0
                            while pre_read < start_offset:
                                to_read = min(1024 * 1024, start_offset - pre_read)
                                c = f_pre.read(to_read)
                                if not c:
                                    break
                                hasher.update(c)
                                pre_read += len(c)
                    except Exception as e:
                        print(f"[Client] Prefix hash error: {e}")

                if start_offset < file_size:
                    try:
                        with open(abs_path, "rb", buffering=2 * 1024 * 1024) as f:
                            if start_offset > 0:
                                f.seek(start_offset)

                            while file_bytes_sent < file_size:
                                if self.is_cancelled:
                                    break

                                chunk = f.read(DEFAULT_CHUNK_SIZE)
                                if not chunk:
                                    break

                                hasher.update(chunk)  # In-flight incremental hash!
                                chunk_bytes = encode_file_chunk(f_id, file_bytes_sent, chunk)
                                tls_sock.sendall(chunk_bytes)

                                chunk_len = len(chunk)
                                file_bytes_sent += chunk_len
                                bytes_transferred_total += chunk_len
                                bytes_since_speed_check += chunk_len

                                # Update speed and ETA
                                now = time.time()
                                dt = now - last_speed_check
                                if dt >= 0.5:
                                    current_speed = bytes_since_speed_check / dt
                                    bytes_since_speed_check = 0
                                    last_speed_check = now

                                eta = (total_bytes - bytes_transferred_total) / current_speed if current_speed > 0 else 0

                                if self.on_progress:
                                    self.on_progress(
                                        f_id,
                                        rel_path,
                                        file_bytes_sent,
                                        file_size,
                                        bytes_transferred_total,
                                        total_bytes,
                                        current_speed,
                                        eta
                                    )
                    except PermissionError:
                        print(f"[Client] File is locked or in use: {abs_path}")
                        continue

                if self.is_cancelled:
                    break

                sha256_hash = hasher.hexdigest()

                # Send FILE_END with in-flight computed SHA-256
                tls_sock.sendall(encode_json_message(MsgType.FILE_END, {
                    "file_id": f_id,
                    "sha256": sha256_hash,
                }))

                # Wait for FILE_ACK
                ack_type, ack_payload = read_message(tls_sock)
                if ack_type == MsgType.FILE_ACK:
                    ack_data = json.loads(ack_payload.decode("utf-8"))
                    verified = (ack_data.get("status") == "OK")
                    if self.on_file_completed:
                        self.on_file_completed(rel_path, verified)
                else:
                    if self.on_file_completed:
                        self.on_file_completed(rel_path, False)

            if not self.is_cancelled:
                # Send TRANSFER_COMPLETE
                tls_sock.sendall(encode_json_message(MsgType.TRANSFER_COMPLETE, {"status": "ALL_DONE"}))

                duration = time.time() - start_time
                HistoryManager().add_record(TransferRecord(
                    id=transfer_id,
                    direction="sent",
                    peer_name=receiver_name,
                    peer_ip=self.target_ip,
                    files_count=total_files,
                    total_bytes=total_bytes,
                    status="Completed",
                    duration_sec=duration,
                    timestamp=time.time(),
                ))

                if self.on_finished:
                    self.on_finished(True, "All files transferred successfully!")

        except PermissionError as pe:
            if self.on_finished:
                self.on_finished(False, str(pe))
        except (ConnectionRefusedError, socket.timeout) as ce:
            err_msg = (
                f"Could not connect to {self.target_ip}:{self.target_port}. "
                "Ensure LaptopShare is open on the other laptop and Windows Firewall is allowing incoming traffic."
            )
            if self.on_finished:
                self.on_finished(False, err_msg)
        except Exception as e:
            if not self.is_cancelled:
                if self.on_finished:
                    self.on_finished(False, f"Transfer failed: {e}")
        finally:
            if tls_sock:
                try:
                    tls_sock.close()
                except Exception:
                    pass
            elif raw_sock:
                try:
                    raw_sock.close()
                except Exception:
                    pass
            self._sock = None
