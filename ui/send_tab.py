"""
LaptopShare Send Tab
Enables drag-and-drop file/folder addition, recipient selection (nearby or manual IP/PIN),
and live transfer tracking with speed, ETA, and SHA-256 verification.
"""

from pathlib import Path
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QFileDialog, QLineEdit,
    QComboBox, QProgressBar, QFrame, QMessageBox, QSplitter
)
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QDragEnterEvent, QDropEvent

from core.file_manager import build_transfer_manifest, format_file_size, format_transfer_speed, format_time_remaining
from core.transfer_client import TransferClient
from core.discovery import PeerDevice
from core.network_utils import test_lan_connection

class DropZone(QFrame):
    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setFixedHeight(120)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        icon_label = QLabel("📂", self)
        icon_label.setStyleSheet("font-size: 32px;")
        icon_label.setAlignment(Qt.AlignCenter)

        text_label = QLabel("Drag & Drop Files or Folders Here", self)
        text_label.setObjectName("sectionHeader")
        text_label.setAlignment(Qt.AlignCenter)

        sub_label = QLabel("or use the buttons below to browse", self)
        sub_label.setObjectName("subtitleLabel")
        sub_label.setAlignment(Qt.AlignCenter)

        layout.addWidget(icon_label)
        layout.addWidget(text_label)
        layout.addWidget(sub_label)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        paths = [u.toLocalFile() for u in urls if u.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)
        event.acceptProposedAction()

class TransferSignalBridge(QObject):
    connecting = Signal()
    connected = Signal(str)
    waiting_approval = Signal()
    started = Signal(int, int)
    progress = Signal(int, str, int, int, int, int, float, float)
    file_done = Signal(str, bool)
    finished = Signal(bool, str)

class SendTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_paths: List[str] = []
        self.active_client: Optional[TransferClient] = None
        self.discovered_peers: List[PeerDevice] = []

        self.bridge = TransferSignalBridge()
        self.bridge.connecting.connect(self._on_client_connecting)
        self.bridge.connected.connect(self._on_client_connected)
        self.bridge.waiting_approval.connect(self._on_client_waiting_approval)
        self.bridge.started.connect(self._on_client_started)
        self.bridge.progress.connect(self._on_client_progress)
        self.bridge.file_done.connect(self._on_client_file_done)
        self.bridge.finished.connect(self._on_client_finished)

        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(14)

        # Title
        header_row = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Send Files & Folders", self)
        title.setObjectName("titleLabel")
        subtitle = QLabel("Direct encrypted transfer to another Windows laptop over LAN", self)
        subtitle.setObjectName("subtitleLabel")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header_row.addLayout(title_box)
        header_row.addStretch()
        main_layout.addLayout(header_row)

        # Drop Zone
        self.drop_zone = DropZone(self)
        self.drop_zone.files_dropped.connect(self.add_paths)
        main_layout.addWidget(self.drop_zone)

        # Buttons row
        btn_row = QHBoxLayout()
        add_file_btn = QPushButton("📄 Add Files", self)
        add_file_btn.clicked.connect(self._browse_files)
        add_folder_btn = QPushButton("📁 Add Folder", self)
        add_folder_btn.clicked.connect(self._browse_folder)
        clear_btn = QPushButton("🗑️ Clear List", self)
        clear_btn.clicked.connect(self.clear_paths)

        btn_row.addWidget(add_file_btn)
        btn_row.addWidget(add_folder_btn)
        btn_row.addStretch()
        btn_row.addWidget(clear_btn)
        main_layout.addLayout(btn_row)

        # File List View Card
        list_card = QFrame(self)
        list_card.setObjectName("card")
        list_layout = QVBoxLayout(list_card)
        list_layout.setContentsMargins(12, 12, 12, 12)

        list_header_row = QHBoxLayout()
        list_title = QLabel("Selected Items for Transfer", self)
        list_title.setObjectName("sectionHeader")
        self.summary_badge = QLabel("0 items (0 B)", self)
        self.summary_badge.setObjectName("badge")
        list_header_row.addWidget(list_title)
        list_header_row.addStretch()
        list_header_row.addWidget(self.summary_badge)
        list_layout.addLayout(list_header_row)

        self.file_list = QListWidget(self)
        self.file_list.setFixedHeight(140)
        list_layout.addWidget(self.file_list)
        main_layout.addWidget(list_card)

        # Recipient Selection Card
        recipient_card = QFrame(self)
        recipient_card.setObjectName("card")
        rec_layout = QVBoxLayout(recipient_card)
        rec_layout.setContentsMargins(14, 14, 14, 14)
        rec_layout.setSpacing(10)

        rec_header = QLabel("Recipient Laptop", self)
        rec_header.setObjectName("sectionHeader")
        rec_layout.addWidget(rec_header)

        # Selector Row
        target_row = QHBoxLayout()
        self.mode_combo = QComboBox(self)
        self.mode_combo.addItems(["Nearby Discovered Device", "Manual IP & PIN"])
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.mode_combo.setFixedWidth(210)
        target_row.addWidget(self.mode_combo)

        # Nearby peer dropdown
        self.peer_combo = QComboBox(self)
        self.peer_combo.setPlaceholderText("Select a discovered laptop on Wi-Fi...")
        target_row.addWidget(self.peer_combo)

        # Manual input fields (hidden initially or shown based on mode)
        self.manual_ip_input = QLineEdit(self)
        self.manual_ip_input.setPlaceholderText("Receiver IP (e.g. 192.168.1.55)")
        self.manual_ip_input.setVisible(False)
        target_row.addWidget(self.manual_ip_input)

        self.pin_input = QLineEdit(self)
        self.pin_input.setPlaceholderText("6-Digit PIN")
        self.pin_input.setMaxLength(6)
        self.pin_input.setFixedWidth(100)
        target_row.addWidget(self.pin_input)

        self.check_btn = QPushButton("Test Ping", self)
        self.check_btn.setToolTip("Check if target laptop and port are reachable")
        self.check_btn.clicked.connect(self._test_connection)
        target_row.addWidget(self.check_btn)

        rec_layout.addLayout(target_row)
        main_layout.addWidget(recipient_card)

        # Progress & Status Card
        self.status_card = QFrame(self)
        self.status_card.setObjectName("card")
        self.status_card.setVisible(False)
        status_layout = QVBoxLayout(self.status_card)
        status_layout.setContentsMargins(14, 14, 14, 14)
        status_layout.setSpacing(8)

        status_header_row = QHBoxLayout()
        self.transfer_state_label = QLabel("Transfer Status", self)
        self.transfer_state_label.setObjectName("sectionHeader")
        self.speed_label = QLabel("0.0 MB/s", self)
        self.speed_label.setObjectName("badge")
        self.eta_label = QLabel("ETA: --:--", self)
        self.eta_label.setObjectName("subtitleLabel")
        status_header_row.addWidget(self.transfer_state_label)
        status_header_row.addStretch()
        status_header_row.addWidget(self.speed_label)
        status_header_row.addWidget(self.eta_label)
        status_layout.addLayout(status_header_row)

        self.current_file_label = QLabel("Preparing...", self)
        self.current_file_label.setObjectName("subtitleLabel")
        status_layout.addWidget(self.current_file_label)

        # File Progress Bar
        self.file_progress_bar = QProgressBar(self)
        self.file_progress_bar.setValue(0)
        status_layout.addWidget(self.file_progress_bar)

        # Total Progress Bar
        self.total_progress_bar = QProgressBar(self)
        self.total_progress_bar.setValue(0)
        status_layout.addWidget(self.total_progress_bar)

        # Cancel button
        cancel_row = QHBoxLayout()
        cancel_row.addStretch()
        self.cancel_btn = QPushButton("Cancel Transfer", self)
        self.cancel_btn.setObjectName("dangerButton")
        self.cancel_btn.clicked.connect(self._cancel_transfer)
        cancel_row.addWidget(self.cancel_btn)
        status_layout.addLayout(cancel_row)

        main_layout.addWidget(self.status_card)

        # Send Action Button
        send_row = QHBoxLayout()
        send_row.addStretch()
        self.send_btn = QPushButton("🚀 Send Files Now", self)
        self.send_btn.setObjectName("primaryButton")
        self.send_btn.setFixedHeight(42)
        self.send_btn.setFixedWidth(200)
        self.send_btn.clicked.connect(self.start_send)
        send_row.addWidget(self.send_btn)
        main_layout.addLayout(send_row)

    def _browse_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select Files to Send")
        if files:
            self.add_paths(files)

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Send")
        if folder:
            self.add_paths([folder])

    def add_paths(self, paths: List[str]):
        for p in paths:
            if p not in self.selected_paths:
                self.selected_paths.append(p)

        self._refresh_file_list()

    def clear_paths(self):
        self.selected_paths.clear()
        self._refresh_file_list()

    def _refresh_file_list(self):
        self.file_list.clear()
        manifest, total_bytes = build_transfer_manifest(self.selected_paths)

        for item in manifest:
            rel = item["rel_path"]
            size_str = format_file_size(item["size"])
            icon = "📁" if "/" in rel or "\\" in rel else "📄"
            list_item = QListWidgetItem(f"{icon} {rel} ({size_str})")
            self.file_list.addItem(list_item)

        count = len(manifest)
        total_str = format_file_size(total_bytes)
        self.summary_badge.setText(f"{count} file{'s' if count != 1 else ''} ({total_str})")

    def _on_mode_changed(self, index: int):
        is_manual = (index == 1)
        self.peer_combo.setVisible(not is_manual)
        self.manual_ip_input.setVisible(is_manual)

    def update_peers(self, peers: List[PeerDevice]):
        self.discovered_peers = peers
        current_data = self.peer_combo.currentData()
        self.peer_combo.clear()

        for p in peers:
            display = f"{p.device_name} ({p.ip}:{p.port}) - {p.os_name}"
            self.peer_combo.addItem(display, userData=p)

        if current_data:
            for i in range(self.peer_combo.count()):
                p = self.peer_combo.itemData(i)
                if p and p.device_id == current_data.device_id:
                    self.peer_combo.setCurrentIndex(i)
                    break

    def set_target_peer(self, peer: PeerDevice):
        """Allows other tabs (like Nearby Devices) to pre-select a peer and switch to Send."""
        self.mode_combo.setCurrentIndex(0)
        for i in range(self.peer_combo.count()):
            p = self.peer_combo.itemData(i)
            if p and p.ip == peer.ip:
                self.peer_combo.setCurrentIndex(i)
                return

    def _test_connection(self):
        ip, port = self._get_target_ip_and_port()
        if not ip:
            QMessageBox.warning(self, "Invalid IP", "Please specify a recipient IP address.")
            return

        success, msg = test_lan_connection(ip, port)
        if success:
            QMessageBox.information(self, "Connection Test", f"✅ {msg}")
        else:
            QMessageBox.critical(self, "Connection Failed", f"❌ {msg}")

    def _get_target_ip_and_port(self) -> tuple[Optional[str], int]:
        if self.mode_combo.currentIndex() == 0:
            peer = self.peer_combo.currentData()
            if peer:
                return peer.ip, peer.port
            return None, 52140
        else:
            ip_str = self.manual_ip_input.text().strip()
            if not ip_str:
                return None, 52140
            if ":" in ip_str:
                parts = ip_str.split(":")
                return parts[0], int(parts[1])
            return ip_str, 52140

    def start_send(self):
        if not self.selected_paths:
            QMessageBox.warning(self, "No Files Selected", "Please select or drop files/folders to send.")
            return

        ip, port = self._get_target_ip_and_port()
        if not ip:
            QMessageBox.warning(self, "No Recipient", "Please select a recipient laptop or enter an IP.")
            return

        pin = self.pin_input.text().strip()
        manifest, total_bytes = build_transfer_manifest(self.selected_paths)
        if not manifest:
            QMessageBox.warning(self, "Empty Files", "No valid files found in selected paths.")
            return

        # Prepare client
        self.active_client = TransferClient(target_ip=ip, target_port=port, pin=pin)

        # Wire up bridge callbacks
        self.active_client.on_connecting = self.bridge.connecting.emit
        self.active_client.on_connected = self.bridge.connected.emit
        self.active_client.on_waiting_approval = self.bridge.waiting_approval.emit
        self.active_client.on_transfer_started = self.bridge.started.emit
        self.active_client.on_progress = self.bridge.progress.emit
        self.active_client.on_file_completed = self.bridge.file_done.emit
        self.active_client.on_finished = self.bridge.finished.emit

        # Show status card and disable send button
        self.status_card.setVisible(True)
        self.send_btn.setEnabled(False)
        self.transfer_state_label.setText(f"Connecting to {ip}:{port}...")
        self.file_progress_bar.setValue(0)
        self.total_progress_bar.setValue(0)

        # Start sending worker thread
        self.active_client.send_files_thread(manifest, total_bytes)

    def _cancel_transfer(self):
        if self.active_client:
            self.active_client.cancel()
            self.transfer_state_label.setText("Cancelling transfer...")

    # Bridge slots
    def _on_client_connecting(self):
        self.transfer_state_label.setText("Connecting via secure TLS...")

    def _on_client_connected(self, receiver_name: str):
        self.transfer_state_label.setText(f"Connected to {receiver_name}. Authenticating...")

    def _on_client_waiting_approval(self):
        self.transfer_state_label.setText("Waiting for recipient to approve transfer on their screen...")

    def _on_client_started(self, total_files: int, total_bytes: int):
        self.transfer_state_label.setText(f"Transferring {total_files} file(s)...")

    def _on_client_progress(self, file_id: int, rel_path: str, file_done: int, file_total: int, total_done: int, total_all: int, speed: float, eta: float):
        file_pct = int((file_done / file_total) * 100) if file_total > 0 else 0
        total_pct = int((total_done / total_all) * 100) if total_all > 0 else 0

        self.current_file_label.setText(f"File: {rel_path} ({format_file_size(file_done)} / {format_file_size(file_total)})")
        self.file_progress_bar.setValue(file_pct)
        self.total_progress_bar.setValue(total_pct)
        self.speed_label.setText(format_transfer_speed(speed))
        self.eta_label.setText(f"ETA: {format_time_remaining(eta)}")

    def _on_client_file_done(self, rel_path: str, verified: bool):
        if verified:
            self.current_file_label.setText(f"✅ Verified SHA-256 for: {rel_path}")
        else:
            self.current_file_label.setText(f"⚠️ Checksum issue for: {rel_path}")

    def _on_client_finished(self, success: bool, msg: str):
        self.send_btn.setEnabled(True)
        if success:
            self.transfer_state_label.setText("🎉 Transfer Completed Successfully!")
            self.total_progress_bar.setValue(100)
            self.file_progress_bar.setValue(100)
            QMessageBox.information(self, "Success", "All files transferred and verified successfully!")
        else:
            self.transfer_state_label.setText(f"Transfer stopped: {msg}")
            QMessageBox.critical(self, "Transfer Failed", msg)
