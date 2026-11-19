"""
LaptopShare Receiver Server
Implements TLS TCP server, approval requests, chunk-based streaming,
resume support, and SHA-256 post-transfer integrity verification.
"""

import os
import time
import socket
import select
import threading
import uuid
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional, Callable, List

from .config import ConfigManager, DEFAULT_TRANSFER_PORT, get_system_shared_roots
from .security import create_server_ssl_context
from .protocol import (
    MsgType,
    encode_json_message,
    read_message,
    decode_file_chunk_payload,
    encode_file_chunk,
    DEFAULT_CHUNK_SIZE,
)
from .file_manager import sanitize_relative_path, calculate_sha256, build_transfer_manifest
from .history import HistoryManager, TransferRecord

class TransferServer:
    def __init__(self, port: int = DEFAULT_TRANSFER_PORT):
        self.port = port
        self.running = False
        self._server_sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None

        # Approval coordination: req_id -> threading.Event and result dict
        self._pending_approvals: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

        # Callbacks (can be connected to PySide6 Qt Signals)
        self.on_approval_required: Optional[Callable[[Dict[str, Any]], None]] = None
        self.on_browse_approval_required: Optional[Callable[[Dict[str, Any]], None]] = None
        self.on_migration_approval_required: Optional[Callable[[Dict[str, Any]], None]] = None
        self.on_transfer_started: Optional[Callable[[str, str, int, int], None]] = None
        self.on_progress: Optional[Callable[[int, str, int, int, int, int, float, float], None]] = None
        self.on_file_completed: Optional[Callable[[str, bool], None]] = None
        self.on_transfer_finished: Optional[Callable[[str, bool, str], None]] = None

    def start(self):
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._server_loop, daemon=True, name="TransferServerThread")
        self._thread.start()

    def stop(self):
        self.running = False
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass

    def approve_transfer(self, req_id: str, accepted: bool, save_dir: Optional[str] = None):
        """Called by UI to approve or decline an incoming transfer."""
        with self._lock:
            if req_id in self._pending_approvals:
                self._pending_approvals[req_id]["accepted"] = accepted
                if save_dir:
                    self._pending_approvals[req_id]["save_dir"] = save_dir
                self._pending_approvals[req_id]["event"].set()

    def approve_browse(self, req_id: str, accepted: bool):
        """Called by UI to approve or decline a remote file browsing request."""
        with self._lock:
            if req_id in self._pending_approvals:
                self._pending_approvals[req_id]["accepted"] = accepted
                self._pending_approvals[req_id]["event"].set()

    def approve_migration(self, req_id: str, accepted: bool):
        """Called by UI to approve or decline a full PC migration request."""
        with self._lock:
            if req_id in self._pending_approvals:
                self._pending_approvals[req_id]["accepted"] = accepted
                self._pending_approvals[req_id]["event"].set()

    def _server_loop(self):
        ssl_ctx = create_server_ssl_context()
        raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            raw_sock.bind(("0.0.0.0", self.port))
            raw_sock.listen(5)
            raw_sock.settimeout(1.0)
            self._server_sock = raw_sock
        except Exception as e:
            print(f"[Server] Failed to bind transfer server on port {self.port}: {e}")
            if self.on_transfer_finished:
                self.on_transfer_finished("", False, f"Failed to bind port {self.port}: {e}")
            return

        while self.running:
            try:
                client_sock, client_addr = raw_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            # Handle client in a separate thread so multiple transfers or queries are isolated
            handler = threading.Thread(
                target=self._handle_client,
                args=(client_sock, client_addr, ssl_ctx),
                daemon=True,
                name=f"ClientHandler-{client_addr[0]}"
            )
            handler.start()

        try:
            raw_sock.close()
        except Exception:
            pass

    def _handle_client(self, raw_sock: socket.socket, client_addr: tuple, ssl_ctx):
        tls_sock = None
        transfer_id = str(uuid.uuid4())
        start_time = time.time()
        peer_name = client_addr[0]
        total_files = 0
        total_bytes = 0
        dest_dir = ConfigManager().get().download_dir

        try:
            # Tune socket buffers for high-speed local network transfer (4MB window)
            try:
                raw_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
                raw_sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
                raw_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except Exception:
                pass

            # Wrap with TLS
            tls_sock = ssl_ctx.wrap_socket(raw_sock, server_side=True)
            tls_sock.settimeout(30.0)

            # 1. Read first message (HANDSHAKE_REQ or BROWSE_AUTH_REQ)
            msg_type, payload = read_message(tls_sock)

            if msg_type == MsgType.BROWSE_AUTH_REQ:
                self._handle_browse_session(tls_sock, client_addr, payload)
                return

            if msg_type == MsgType.MIGRATE_SCAN_REQ:
                self._handle_migration_session(tls_sock, client_addr, payload)
                return

            if msg_type != MsgType.HANDSHAKE_REQ:
                tls_sock.sendall(encode_json_message(MsgType.HANDSHAKE_RESP, {
                    "status": "REJECTED",
                    "message": "Expected HANDSHAKE_REQ, BROWSE_AUTH_REQ, or MIGRATE_SCAN_REQ"
                }))
                return

            import json
            handshake = json.loads(payload.decode("utf-8"))
            peer_name = handshake.get("device_name", client_addr[0])
            provided_pin = handshake.get("pin", "")

            cfg = ConfigManager().get()
            if cfg.require_pin and cfg.current_pin:
                if str(provided_pin).strip() != str(cfg.current_pin).strip():
                    tls_sock.sendall(encode_json_message(MsgType.HANDSHAKE_RESP, {
                        "status": "BAD_PIN",
                        "message": "Incorrect Connection PIN."
                    }))
                    return

            # Handshake preliminary OK
            tls_sock.sendall(encode_json_message(MsgType.HANDSHAKE_RESP, {
                "status": "APPROVED",
                "receiver_name": cfg.device_name
            }))

            # 2. Read MANIFEST_REQ
            msg_type, payload = read_message(tls_sock)
            if msg_type != MsgType.MANIFEST_REQ:
                return

            manifest_data = json.loads(payload.decode("utf-8"))
            files = manifest_data.get("files", [])
            total_bytes = manifest_data.get("total_bytes", 0)
            total_files = len(files)

            # 3. Request receiver user approval via GUI
            req_id = str(uuid.uuid4())
            approval_event = threading.Event()
            with self._lock:
                self._pending_approvals[req_id] = {
                    "event": approval_event,
                    "accepted": False,
                    "save_dir": cfg.download_dir,
                }

            if self.on_approval_required:
                self.on_approval_required({
                    "req_id": req_id,
                    "peer_name": peer_name,
                    "peer_ip": client_addr[0],
                    "total_files": total_files,
                    "total_bytes": total_bytes,
                    "files": files,
                })

            # Wait up to 60 seconds for user to click Accept or Decline
            approved = approval_event.wait(timeout=60.0)
            with self._lock:
                approval_info = self._pending_approvals.pop(req_id, None)

            if not approved or not approval_info or not approval_info.get("accepted"):
                tls_sock.sendall(encode_json_message(MsgType.MANIFEST_RESP, {
                    "status": "REJECTED",
                    "message": "Transfer declined by recipient or timed out."
                }))
                return

            dest_dir = approval_info.get("save_dir", cfg.download_dir)
            target_path = Path(dest_dir)
            target_path.mkdir(parents=True, exist_ok=True)

            # 4. Check for existing partial files to support RESUME
            file_offsets = {}
            for item in files:
                f_id = item["file_id"]
                rel_p = sanitize_relative_path(item["rel_path"])
                local_file_path = target_path / rel_p
                existing_bytes = 0
                if local_file_path.exists():
                    existing_bytes = local_file_path.stat().st_size
                    # If existing bytes exceed total size, truncate or restart
                    if existing_bytes >= item["size"]:
                        existing_bytes = item["size"]
                file_offsets[f_id] = existing_bytes

            # Send MANIFEST_RESP with resume offsets
            tls_sock.sendall(encode_json_message(MsgType.MANIFEST_RESP, {
                "status": "APPROVED",
                "offsets": file_offsets
            }))

            if self.on_transfer_started:
                self.on_transfer_started(transfer_id, peer_name, total_files, total_bytes)

            # Use generous 300s socket timeout during active streaming of large videos/photos
            tls_sock.settimeout(300.0)

            # 5. Receive files and chunks
            bytes_received_total = sum(file_offsets.values())
            last_speed_check = time.time()
            bytes_since_speed_check = 0
            current_speed = 0.0

            active_file_handle = None
            active_hasher = None
            current_file_meta = None
            current_file_received_bytes = 0

            # Map file_id to metadata
            file_map = {f["file_id"]: f for f in files}

            while True:
                msg_type, payload = read_message(tls_sock)

                if msg_type == MsgType.FILE_START:
                    start_meta = json.loads(payload.decode("utf-8"))
                    f_id = start_meta["file_id"]
                    current_file_meta = file_map.get(f_id)
                    if not current_file_meta:
                        continue

                    rel_p = sanitize_relative_path(current_file_meta["rel_path"])
                    file_out_path = target_path / rel_p
                    file_out_path.parent.mkdir(parents=True, exist_ok=True)

                    start_offset = start_meta.get("offset", 0)
                    mode = "r+b" if (start_offset > 0 and file_out_path.exists()) else "wb"
                    active_file_handle = open(file_out_path, mode, buffering=2 * 1024 * 1024)
                    if start_offset > 0:
                        active_file_handle.seek(start_offset)
                    current_file_received_bytes = start_offset

                    # Initialize in-flight incremental hasher
                    active_hasher = hashlib.sha256()
                    if start_offset > 0 and file_out_path.exists():
                        try:
                            with open(file_out_path, "rb") as f_prev:
                                pre_read = 0
                                while pre_read < start_offset:
                                    to_r = min(1024 * 1024, start_offset - pre_read)
                                    c = f_prev.read(to_r)
                                    if not c:
                                        break
                                    active_hasher.update(c)
                                    pre_read += len(c)
                        except Exception as e:
                            print(f"[Server] Prefix hash error: {e}")

                elif msg_type == MsgType.FILE_CHUNK:
                    f_id, offset, chunk_data = decode_file_chunk_payload(payload)
                    chunk_len = len(chunk_data)

                    if active_file_handle:
                        active_file_handle.write(chunk_data)
                        if active_hasher is not None:
                            active_hasher.update(chunk_data)
                        current_file_received_bytes += chunk_len
                        bytes_received_total += chunk_len
                        bytes_since_speed_check += chunk_len

                        # Calculate speed & ETA
                        now = time.time()
                        dt = now - last_speed_check
                        if dt >= 0.5:
                            current_speed = bytes_since_speed_check / dt
                            bytes_since_speed_check = 0
                            last_speed_check = now

                        eta = (total_bytes - bytes_received_total) / current_speed if current_speed > 0 else 0

                        if self.on_progress and current_file_meta:
                            self.on_progress(
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
                            final_file_path = str(target_path / rel_p)
                            actual_sha256 = calculate_sha256(final_file_path)

                        if actual_sha256.lower() == expected_sha256.lower():
                            checksum_ok = True
                            tls_sock.sendall(encode_json_message(MsgType.FILE_ACK, {
                                "file_id": f_id,
                                "status": "OK"
                            }))
                        else:
                            tls_sock.sendall(encode_json_message(MsgType.FILE_ACK, {
                                "file_id": f_id,
                                "status": "CHECKSUM_FAILED"
                            }))

                        if self.on_file_completed:
                            self.on_file_completed(meta["rel_path"], checksum_ok)

                elif msg_type == MsgType.TRANSFER_COMPLETE:
                    # All files transmitted
                    duration = time.time() - start_time
                    HistoryManager().add_record(TransferRecord(
                        id=transfer_id,
                        direction="received",
                        peer_name=peer_name,
                        peer_ip=client_addr[0],
                        files_count=total_files,
                        total_bytes=total_bytes,
                        status="Completed",
                        duration_sec=duration,
                        timestamp=time.time(),
                        destination_dir=str(target_path)
                    ))
                    if self.on_transfer_finished:
                        self.on_transfer_finished(transfer_id, True, "Transfer completed successfully.")
                    break

                elif msg_type == MsgType.CANCEL:
                    cancel_info = json.loads(payload.decode("utf-8"))
                    reason = cancel_info.get("reason", "Cancelled by sender")
                    if active_file_handle:
                        active_file_handle.close()
                        active_file_handle = None
                    if self.on_transfer_finished:
                        self.on_transfer_finished(transfer_id, False, f"Transfer cancelled: {reason}")
                    break

        except (ConnectionResetError, EOFError, socket.timeout) as e:
            if active_file_handle:
                try:
                    active_file_handle.close()
                except Exception:
                    pass
            duration = time.time() - start_time
            HistoryManager().add_record(TransferRecord(
                id=transfer_id,
                direction="received",
                peer_name=peer_name,
                peer_ip=client_addr[0],
                files_count=total_files,
                total_bytes=total_bytes,
                status="Interrupted",
                duration_sec=duration,
                timestamp=time.time(),
                destination_dir=str(dest_dir),
                error_message=str(e)
            ))
            if self.on_transfer_finished:
                self.on_transfer_finished(transfer_id, False, f"Connection lost: {e}")
        except Exception as e:
            if active_file_handle:
                try:
                    active_file_handle.close()
                except Exception:
                    pass
            if self.on_transfer_finished:
                self.on_transfer_finished(transfer_id, False, f"Transfer error: {e}")
        finally:
            if tls_sock:
                try:
                    tls_sock.close()
                except Exception:
                    pass
            try:
                raw_sock.close()
            except Exception:
                pass

    def _handle_browse_session(self, tls_sock, client_addr: tuple, payload: bytes):
        """Handles a remote file browsing and pulling session."""
        cfg = ConfigManager().get()
        import json

        try:
            data = json.loads(payload.decode("utf-8"))
            peer_name = data.get("device_name", client_addr[0])
            pin = data.get("pin", "")

            # 1. PIN verification
            if cfg.require_pin and cfg.current_pin:
                if str(pin).strip() != str(cfg.current_pin).strip():
                    tls_sock.sendall(encode_json_message(MsgType.BROWSE_AUTH_RESP, {
                        "status": "BAD_PIN",
                        "message": "Incorrect Connection PIN."
                    }))
                    return

            # 2. Check if host has allowed remote browsing
            if not getattr(cfg, "allow_remote_browsing", True):
                tls_sock.sendall(encode_json_message(MsgType.BROWSE_AUTH_RESP, {
                    "status": "REJECTED",
                    "message": "Remote file browsing is disabled on this laptop."
                }))
                return

            # 3. Request user permission on this laptop screen
            req_id = str(uuid.uuid4())
            approval_event = threading.Event()
            with self._lock:
                self._pending_approvals[req_id] = {
                    "event": approval_event,
                    "accepted": False
                }

            if self.on_browse_approval_required:
                self.on_browse_approval_required({
                    "req_id": req_id,
                    "peer_name": peer_name,
                    "peer_ip": client_addr[0]
                })

            # Wait up to 60 seconds for approval
            approved = approval_event.wait(timeout=60.0)
            with self._lock:
                appr_info = self._pending_approvals.pop(req_id, None)

            if not approved or not appr_info or not appr_info.get("accepted"):
                tls_sock.sendall(encode_json_message(MsgType.BROWSE_AUTH_RESP, {
                    "status": "REJECTED",
                    "message": "Remote access request was declined by the user."
                }))
                return

            # Send APPROVED response with roots
            roots = get_system_shared_roots()
            tls_sock.sendall(encode_json_message(MsgType.BROWSE_AUTH_RESP, {
                "status": "APPROVED",
                "device_name": cfg.device_name,
                "roots": roots
            }))

            # Command loop for browsing and pulling files
            tls_sock.settimeout(600.0)  # 10 minute inactivity timeout for browsing session

            while self.running:
                try:
                    cmd_type, cmd_payload = read_message(tls_sock)
                except (EOFError, ConnectionResetError, socket.timeout):
                    break

                if cmd_type == MsgType.BROWSE_LIST_REQ:
                    req_data = json.loads(cmd_payload.decode("utf-8"))
                    req_path = req_data.get("path", "")
                    items = []
                    status = "OK"
                    error_msg = ""
                    try:
                        p = Path(req_path)
                        if p.exists() and p.is_dir():
                            for entry in p.iterdir():
                                try:
                                    is_d = entry.is_dir()
                                    sz = 0 if is_d else entry.stat().st_size
                                    mtime = entry.stat().st_mtime
                                    items.append({
                                        "name": entry.name,
                                        "is_dir": is_d,
                                        "size": sz,
                                        "mtime": mtime,
                                        "path": str(entry.resolve())
                                    })
                                except (PermissionError, FileNotFoundError, OSError):
                                    continue
                            # Sort folders first, then case-insensitive alphabetically
                            items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
                        else:
                            status = "ERROR"
                            error_msg = f"Path does not exist or is not a directory: {req_path}"
                    except Exception as e:
                        status = "ERROR"
                        error_msg = str(e)

                    tls_sock.sendall(encode_json_message(MsgType.BROWSE_LIST_RESP, {
                        "status": status,
                        "path": req_path,
                        "items": items,
                        "error": error_msg
                    }))

                elif cmd_type == MsgType.PULL_REQ:
                    # Remote client requested files/folders to copy
                    req_data = json.loads(cmd_payload.decode("utf-8"))
                    requested_paths = req_data.get("paths", [])
                    manifest, total_bytes = build_transfer_manifest(requested_paths)

                    manifest_wire = [
                        {
                            "file_id": item["file_id"],
                            "rel_path": item["rel_path"],
                            "size": item["size"]
                        }
                        for item in manifest
                    ]

                    tls_sock.sendall(encode_json_message(MsgType.PULL_RESP, {
                        "status": "APPROVED",
                        "files": manifest_wire,
                        "total_bytes": total_bytes
                    }))

                    # Wait for client's MANIFEST_RESP (with resume offsets)
                    m_type, m_payload = read_message(tls_sock)
                    if m_type != MsgType.MANIFEST_RESP:
                        break

                    m_resp = json.loads(m_payload.decode("utf-8"))
                    resume_offsets = {int(k): v for k, v in m_resp.get("offsets", {}).items()}

                    # Stream files to remote client
                    for f_item in manifest:
                        f_id = f_item["file_id"]
                        abs_p = f_item["abs_path"]
                        rel_p = f_item["rel_path"]
                        f_size = f_item["size"]
                        start_offset = resume_offsets.get(f_id, 0)

                        tls_sock.sendall(encode_json_message(MsgType.FILE_START, {
                            "file_id": f_id,
                            "rel_path": rel_p,
                            "offset": start_offset
                        }))

                        hasher = hashlib.sha256()
                        if start_offset > 0 and Path(abs_p).exists():
                            try:
                                with open(abs_p, "rb") as f_pre:
                                    pre_read = 0
                                    while pre_read < start_offset:
                                        to_read = min(1024 * 1024, start_offset - pre_read)
                                        c = f_pre.read(to_read)
                                        if not c:
                                            break
                                        hasher.update(c)
                                        pre_read += len(c)
                            except Exception as e:
                                print(f"[Server] Browse prefix hash error: {e}")

                        if start_offset < f_size:
                            try:
                                with open(abs_p, "rb") as f_in:
                                    if start_offset > 0:
                                        f_in.seek(start_offset)
                                    sent_bytes = start_offset
                                    while sent_bytes < f_size:
                                        chunk = f_in.read(DEFAULT_CHUNK_SIZE)
                                        if not chunk:
                                            break
                                        hasher.update(chunk)
                                        tls_sock.sendall(encode_file_chunk(f_id, sent_bytes, chunk))
                                        sent_bytes += len(chunk)
                            except PermissionError:
                                print(f"[Server] File locked: {abs_p}")

                        sha256_hash = hasher.hexdigest()

                        # Send FILE_END
                        tls_sock.sendall(encode_json_message(MsgType.FILE_END, {
                            "file_id": f_id,
                            "sha256": sha256_hash
                        }))

                        # Wait for FILE_ACK
                        ack_type, ack_payload = read_message(tls_sock)

                    # Send TRANSFER_COMPLETE
                    tls_sock.sendall(encode_json_message(MsgType.TRANSFER_COMPLETE, {"status": "ALL_DONE"}))

                elif cmd_type == MsgType.CANCEL:
                    break

        except Exception as e:
            print(f"[Server] Remote browse session error with {client_addr}: {e}")
        finally:
            try:
                tls_sock.close()
            except Exception:
                pass

    def _handle_migration_session(self, tls_sock, client_addr: tuple, payload: bytes):
        """Handles a full PC Migration session from an old PC to a new PC."""
        cfg = ConfigManager().get()
        import json

        try:
            data = json.loads(payload.decode("utf-8"))
            peer_name = data.get("device_name", client_addr[0])
            pin = data.get("pin", "")

            # 1. PIN verification
            if cfg.require_pin and cfg.current_pin:
                if str(pin).strip() != str(cfg.current_pin).strip():
                    tls_sock.sendall(encode_json_message(MsgType.MIGRATE_SCAN_RESP, {
                        "status": "BAD_PIN",
                        "message": "Incorrect Connection PIN."
                    }))
                    return

            # 2. Check permission for PC migration on host screen
            req_id = str(uuid.uuid4())
            approval_event = threading.Event()
            with self._lock:
                self._pending_approvals[req_id] = {
                    "event": approval_event,
                    "accepted": False
                }

            if self.on_migration_approval_required:
                self.on_migration_approval_required({
                    "req_id": req_id,
                    "peer_name": peer_name,
                    "peer_ip": client_addr[0]
                })

            approved = approval_event.wait(timeout=90.0)
            with self._lock:
                appr_info = self._pending_approvals.pop(req_id, None)

            if not approved or not appr_info or not appr_info.get("accepted"):
                tls_sock.sendall(encode_json_message(MsgType.MIGRATE_SCAN_RESP, {
                    "status": "REJECTED",
                    "message": "PC Migration request was declined or timed out."
                }))
                return

            # 3. Scan migration categories on this host
            from .migration import scan_migration_categories
            categories = scan_migration_categories(fast=True)
            cat_dicts = [c.to_dict() for c in categories]

            tls_sock.sendall(encode_json_message(MsgType.MIGRATE_SCAN_RESP, {
                "status": "APPROVED",
                "device_name": cfg.device_name,
                "categories": cat_dicts
            }))

            # 4. Wait for MIGRATE_START_REQ
            tls_sock.settimeout(600.0)
            while self.running:
                try:
                    m_type, m_payload = read_message(tls_sock)
                except (EOFError, ConnectionResetError, socket.timeout):
                    break

                if m_type == MsgType.MIGRATE_START_REQ:
                    start_data = json.loads(m_payload.decode("utf-8"))
                    selected_ids = set(start_data.get("selected_category_ids", []))

                    cat_map = {c.id: c for c in categories if c.available and c.id in selected_ids}
                    all_manifest = []
                    file_id_counter = 1
                    total_bytes = 0

                    for cat_id, cat in cat_map.items():
                        src_p = Path(cat.source_path)
                        if not src_p.exists():
                            continue

                        if src_p.is_file():
                            sz = src_p.stat().st_size
                            rel = f"{cat.dest_subfolder}/{src_p.name}"
                            all_manifest.append({
                                "file_id": file_id_counter,
                                "abs_path": str(src_p),
                                "rel_path": rel,
                                "size": sz,
                            })
                            total_bytes += sz
                            file_id_counter += 1
                        elif src_p.is_dir():
                            for root, dirs, files in os.walk(src_p):
                                for fname in files:
                                    full_p = Path(root) / fname
                                    try:
                                        sz = full_p.stat().st_size
                                        rel_within_cat = full_p.relative_to(src_p).as_posix()
                                        rel = f"{cat.dest_subfolder}/{rel_within_cat}"
                                        all_manifest.append({
                                            "file_id": file_id_counter,
                                            "abs_path": str(full_p),
                                            "rel_path": rel,
                                            "size": sz,
                                        })
                                        total_bytes += sz
                                        file_id_counter += 1
                                    except (PermissionError, FileNotFoundError, OSError):
                                        continue

                    manifest_wire = [
                        {
                            "file_id": it["file_id"],
                            "rel_path": it["rel_path"],
                            "size": it["size"]
                        }
                        for it in all_manifest
                    ]

                    tls_sock.sendall(encode_json_message(MsgType.MIGRATE_START_RESP, {
                        "status": "APPROVED",
                        "files": manifest_wire,
                        "total_bytes": total_bytes
                    }))

                    # Wait for client's MANIFEST_RESP (with resume offsets)
                    ack_type, ack_payload = read_message(tls_sock)
                    if ack_type != MsgType.MANIFEST_RESP:
                        break

                    m_resp = json.loads(ack_payload.decode("utf-8"))
                    resume_offsets = {int(k): v for k, v in m_resp.get("offsets", {}).items()}

                    # Stream migration files
                    for item in all_manifest:
                        f_id = item["file_id"]
                        abs_p = item["abs_path"]
                        rel_p = item["rel_path"]
                        f_size = item["size"]
                        start_offset = resume_offsets.get(f_id, 0)

                        tls_sock.sendall(encode_json_message(MsgType.FILE_START, {
                            "file_id": f_id,
                            "rel_path": rel_p,
                            "offset": start_offset
                        }))

                        hasher = hashlib.sha256()
                        if start_offset > 0 and Path(abs_p).exists():
                            try:
                                with open(abs_p, "rb") as f_pre:
                                    pre_read = 0
                                    while pre_read < start_offset:
                                        to_read = min(1024 * 1024, start_offset - pre_read)
                                        c = f_pre.read(to_read)
                                        if not c:
                                            break
                                        hasher.update(c)
                                        pre_read += len(c)
                            except Exception as e:
                                print(f"[Server] Browse prefix hash error: {e}")

                        if start_offset < f_size:
                            try:
                                with open(abs_p, "rb") as f_in:
                                    if start_offset > 0:
                                        f_in.seek(start_offset)
                                    sent_bytes = start_offset
                                    while sent_bytes < f_size:
                                        chunk = f_in.read(DEFAULT_CHUNK_SIZE)
                                        if not chunk:
                                            break
                                        hasher.update(chunk)
                                        tls_sock.sendall(encode_file_chunk(f_id, sent_bytes, chunk))
                                        sent_bytes += len(chunk)
                            except PermissionError:
                                print(f"[Server] File locked: {abs_p}")

                        sha256_hash = hasher.hexdigest()

                        # Send FILE_END
                        tls_sock.sendall(encode_json_message(MsgType.FILE_END, {
                            "file_id": f_id,
                            "sha256": sha256_hash
                        }))

                        # Wait for FILE_ACK
                        f_ack_type, f_ack_payload = read_message(tls_sock)

                    # Send TRANSFER_COMPLETE
                    tls_sock.sendall(encode_json_message(MsgType.TRANSFER_COMPLETE, {"status": "ALL_DONE"}))
                    break

                elif m_type == MsgType.CANCEL:
                    break

        except Exception as e:
            print(f"[Server] Migration session error with {client_addr}: {e}")
        finally:
            try:
                tls_sock.close()
            except Exception:
                pass
