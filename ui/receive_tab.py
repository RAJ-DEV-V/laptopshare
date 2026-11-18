"""
LaptopShare Receive Tab
Displays local IP addresses, 6-digit PIN, QR code, destination folder selector,
and handles receiver approval requests and incoming transfer progress.
"""

import os
import subprocess
import webbrowser
from pathlib import Path
from typing import Dict, Any, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QFrame, QFileDialog, QMessageBox, QListWidget,
    QListWidgetItem, QComboBox, QApplication
)
from PySide6.QtCore import Qt, Signal, QObject

from core.config import ConfigManager
from core.security import generate_pin
from core.network_utils import get_local_ip_addresses, get_primary_ip
from core.file_manager import format_file_size, format_transfer_speed, format_time_remaining
from core.transfer_server import TransferServer
from core.web_explorer_server import DEFAULT_WEB_EXPLORER_PORT, open_in_windows_explorer
from ui.qr_widget import QRCodeWidget

class ServerSignalBridge(QObject):
    approval_required = Signal(dict)
    browse_approval_required = Signal(dict)
    migration_approval_required = Signal(dict)
    transfer_started = Signal(str, str, int, int)
    progress = Signal(int, str, int, int, int, int, float, float)
    file_completed = Signal(str, bool)
    transfer_finished = Signal(str, bool, str)

class ReceiveTab(QWidget):
    def __init__(self, server: TransferServer, parent=None):
        super().__init__(parent)
        self.server = server
        self.cfg = ConfigManager().get()

        self.bridge = ServerSignalBridge()
        self.bridge.approval_required.connect(self._on_approval_required)
        self.bridge.browse_approval_required.connect(self._on_browse_approval_required)
        self.bridge.migration_approval_required.connect(self._on_migration_approval_required)
        self.bridge.transfer_started.connect(self._on_transfer_started)
        self.bridge.progress.connect(self._on_progress)
        self.bridge.file_completed.connect(self._on_file_completed)
        self.bridge.transfer_finished.connect(self._on_transfer_finished)

        # Wire server callbacks to bridge
        self.server.on_approval_required = self.bridge.approval_required.emit
        self.server.on_browse_approval_required = self.bridge.browse_approval_required.emit
        self.server.on_migration_approval_required = self.bridge.migration_approval_required.emit
        self.server.on_transfer_started = self.bridge.transfer_started.emit
        self.server.on_progress = self.bridge.progress.emit
        self.server.on_file_completed = self.bridge.file_completed.emit
        self.server.on_transfer_finished = self.bridge.transfer_finished.emit

        self.pending_req_id: Optional[str] = None
        self.pending_browse_req_id: Optional[str] = None
        self.pending_migration_req_id: Optional[str] = None

        self._init_ui()
        self._refresh_network_info()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(14)

        # Header
        header_row = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Receive Files", self)
        title.setObjectName("titleLabel")
        subtitle = QLabel("Ready to receive files over local Wi-Fi / Ethernet", self)
        subtitle.setObjectName("subtitleLabel")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header_row.addLayout(title_box)
        header_row.addStretch()

        self.status_badge = QLabel("● Active & Listening", self)
        self.status_badge.setObjectName("badge")
        self.status_badge.setStyleSheet("background-color: #15803d; color: #dcfce7; padding: 6px 12px; font-size: 12px;")
        header_row.addWidget(self.status_badge)
        main_layout.addLayout(header_row)

        # Connection Details Card (IP, PIN, QR Code)
        conn_card = QFrame(self)
        conn_card.setObjectName("card")
        conn_layout = QHBoxLayout(conn_card)
        conn_layout.setContentsMargins(18, 18, 18, 18)
        conn_layout.setSpacing(20)

        # Left Info Column
        left_info = QVBoxLayout()
        left_info.setSpacing(12)

        ip_section_title = QLabel("Your Local IP Address:", self)
        ip_section_title.setObjectName("sectionHeader")
        left_info.addWidget(ip_section_title)

        self.ip_combo = QComboBox(self)
        self.ip_combo.currentIndexChanged.connect(self._on_ip_selection_changed)
        left_info.addWidget(self.ip_combo)

        pin_section_title = QLabel("Temporary Connection PIN:", self)
        pin_section_title.setObjectName("sectionHeader")
        left_info.addWidget(pin_section_title)

        pin_row = QHBoxLayout()
        self.pin_label = QLabel(self.cfg.current_pin, self)
        self.pin_label.setObjectName("pinDisplay")
        pin_row.addWidget(self.pin_label)

        self.new_pin_btn = QPushButton("🔄 New PIN", self)
        self.new_pin_btn.clicked.connect(self._generate_new_pin)
        pin_row.addWidget(self.new_pin_btn)
        pin_row.addStretch()
        left_info.addLayout(pin_row)

        dest_title = QLabel("Save Destination Folder:", self)
        dest_title.setObjectName("sectionHeader")
        left_info.addWidget(dest_title)

        dest_row = QHBoxLayout()
        self.dest_path_label = QLabel(self.cfg.download_dir, self)
        self.dest_path_label.setStyleSheet("font-weight: 500; color: #38bdf8;")
        dest_row.addWidget(self.dest_path_label)

        change_dest_btn = QPushButton("Browse...", self)
        change_dest_btn.clicked.connect(self._browse_destination)
        open_dest_btn = QPushButton("Open Folder", self)
        open_dest_btn.clicked.connect(self._open_destination)

        dest_row.addWidget(change_dest_btn)
        dest_row.addWidget(open_dest_btn)
        left_info.addLayout(dest_row)

        conn_layout.addLayout(left_info, stretch=2)

        # Right QR Code Column
        qr_box = QVBoxLayout()
        qr_box.setAlignment(Qt.AlignCenter)
        qr_title = QLabel("Quick Connect QR", self)
        qr_title.setObjectName("subtitleLabel")
        qr_title.setAlignment(Qt.AlignCenter)
        self.qr_widget = QRCodeWidget(size=150, parent=self)
        qr_box.addWidget(qr_title)
        qr_box.addWidget(self.qr_widget)
        conn_layout.addLayout(qr_box, stretch=1)

        main_layout.addWidget(conn_card)

        # Windows Explorer & Web Browser File Sharing Card
        we_card = QFrame(self)
        we_card.setObjectName("card")
        we_card.setStyleSheet("QFrame#card { border: 1px solid #0369a1; background-color: #172033; }")
        we_layout = QVBoxLayout(we_card)
        we_layout.setContentsMargins(16, 14, 16, 14)
        we_layout.setSpacing(10)

        we_header_row = QHBoxLayout()
        we_title = QLabel("📂 Windows File Explorer & Web Browser Access", self)
        we_title.setStyleSheet("font-size: 14px; font-weight: 700; color: #38bdf8;")
        we_badge = QLabel("● WebDAV Active", self)
        we_badge.setStyleSheet("background-color: #0369a1; color: #e0f2fe; padding: 4px 8px; border-radius: 4px; font-size: 11px;")
        we_header_row.addWidget(we_title)
        we_header_row.addStretch()
        we_header_row.addWidget(we_badge)
        we_layout.addLayout(we_header_row)

        we_desc = QLabel("On another laptop, you can explore and copy files from this PC directly via Windows Explorer (no Windows passwords needed):", self)
        we_desc.setObjectName("subtitleLabel")
        we_layout.addWidget(we_desc)

        we_info_row = QHBoxLayout()
        we_info_row.setSpacing(10)
        self.we_path_label = QLabel(f"\\\\{get_primary_ip()}@{DEFAULT_WEB_EXPLORER_PORT}\\DavWWWRoot", self)
        self.we_path_label.setStyleSheet("font-family: monospace; font-size: 12px; background: #0f172a; padding: 6px 10px; border-radius: 6px; color: #4ade80;")
        we_info_row.addWidget(self.we_path_label, stretch=1)

        copy_unc_btn = QPushButton("📋 Copy Explorer Address", self)
        copy_unc_btn.clicked.connect(self._copy_explorer_unc)
        we_info_row.addWidget(copy_unc_btn)

        open_web_btn = QPushButton("🌐 View in Browser", self)
        open_web_btn.clicked.connect(self._open_web_portal)
        we_info_row.addWidget(open_web_btn)

        we_layout.addLayout(we_info_row)
        main_layout.addWidget(we_card)

        # Incoming Transfer Approval Card (Hidden by default)
        self.approval_card = QFrame(self)
        self.approval_card.setObjectName("card")
        self.approval_card.setStyleSheet("QFrame#card { border: 2px solid #0284c7; background-color: #1e293b; }")
        self.approval_card.setVisible(False)
        appr_layout = QVBoxLayout(self.approval_card)
        appr_layout.setContentsMargins(16, 16, 16, 16)
        appr_layout.setSpacing(10)

        appr_title_row = QHBoxLayout()
        self.appr_header = QLabel("Incoming Transfer Request!", self)
        self.appr_header.setObjectName("titleLabel")
        self.appr_header.setStyleSheet("color: #38bdf8; font-size: 18px;")
        appr_title_row.addWidget(self.appr_header)
        appr_title_row.addStretch()
        self.appr_summary_badge = QLabel("0 files (0 MB)", self)
        self.appr_summary_badge.setObjectName("badge")
        appr_title_row.addWidget(self.appr_summary_badge)
        appr_layout.addLayout(appr_title_row)

        self.appr_sender_info = QLabel("Sender: Unknown", self)
        self.appr_sender_info.setObjectName("subtitleLabel")
        appr_layout.addWidget(self.appr_sender_info)

        self.appr_file_list = QListWidget(self)
        self.appr_file_list.setFixedHeight(100)
        appr_layout.addWidget(self.appr_file_list)

        appr_btn_row = QHBoxLayout()
        appr_btn_row.addStretch()
        self.decline_btn = QPushButton("❌ Decline", self)
        self.decline_btn.setObjectName("dangerButton")
        self.decline_btn.clicked.connect(self._decline_transfer)
        self.accept_btn = QPushButton("✅ Accept Transfer", self)
        self.accept_btn.setObjectName("successButton")
        self.accept_btn.clicked.connect(self._accept_transfer)
        appr_btn_row.addWidget(self.decline_btn)
        appr_btn_row.addWidget(self.accept_btn)
        appr_layout.addLayout(appr_btn_row)

        main_layout.addWidget(self.approval_card)

        # Remote File Browsing Permission Card
        self.browse_card = QFrame(self)
        self.browse_card.setObjectName("card")
        self.browse_card.setStyleSheet("QFrame#card { border: 2px solid #16a34a; background-color: #1e293b; }")
        self.browse_card.setVisible(False)
        b_layout = QVBoxLayout(self.browse_card)
        b_layout.setContentsMargins(16, 16, 16, 16)
        b_layout.setSpacing(10)

        b_title_row = QHBoxLayout()
        self.b_header = QLabel("🔐 Remote Laptop File Access Request", self)
        self.b_header.setObjectName("titleLabel")
        self.b_header.setStyleSheet("color: #4ade80; font-size: 18px;")
        b_title_row.addWidget(self.b_header)
        b_layout.addLayout(b_title_row)

        self.b_sender_info = QLabel("Another laptop is requesting permission to browse files and copy them.", self)
        self.b_sender_info.setObjectName("subtitleLabel")
        b_layout.addWidget(self.b_sender_info)

        b_btn_row = QHBoxLayout()
        b_btn_row.addStretch()
        self.b_deny_btn = QPushButton("❌ Deny Access", self)
        self.b_deny_btn.setObjectName("dangerButton")
        self.b_deny_btn.clicked.connect(self._deny_browse)
        self.b_grant_btn = QPushButton("✅ Grant Browsing Permission", self)
        self.b_grant_btn.setObjectName("successButton")
        self.b_grant_btn.clicked.connect(self._grant_browse)
        b_btn_row.addWidget(self.b_deny_btn)
        b_btn_row.addWidget(self.b_grant_btn)
        b_layout.addLayout(b_btn_row)

        main_layout.addWidget(self.browse_card)

        # Full PC Migration Permission Card
        self.migration_card = QFrame(self)
        self.migration_card.setObjectName("card")
        self.migration_card.setStyleSheet("QFrame#card { border: 2px solid #8b5cf6; background-color: #1e1b4b; }")
        self.migration_card.setVisible(False)
        m_layout = QVBoxLayout(self.migration_card)
        m_layout.setContentsMargins(16, 16, 16, 16)
        m_layout.setSpacing(10)

        m_title_row = QHBoxLayout()
        self.m_header = QLabel("🔄 Full PC Migration Request", self)
        self.m_header.setObjectName("titleLabel")
        self.m_header.setStyleSheet("color: #a78bfa; font-size: 18px;")
        m_title_row.addWidget(self.m_header)
        m_layout.addLayout(m_title_row)

        self.m_sender_info = QLabel("Another laptop wants to scan and migrate user files and profiles from this PC.", self)
        self.m_sender_info.setObjectName("subtitleLabel")
        m_layout.addWidget(self.m_sender_info)

        m_btn_row = QHBoxLayout()
        m_btn_row.addStretch()
        self.m_deny_btn = QPushButton("❌ Deny Migration", self)
        self.m_deny_btn.setObjectName("dangerButton")
        self.m_deny_btn.clicked.connect(self._deny_migration)
        self.m_grant_btn = QPushButton("✅ Approve PC Migration", self)
        self.m_grant_btn.setObjectName("successButton")
        self.m_grant_btn.clicked.connect(self._grant_migration)
        m_btn_row.addWidget(self.m_deny_btn)
        m_btn_row.addWidget(self.m_grant_btn)
        m_layout.addLayout(m_btn_row)

        main_layout.addWidget(self.migration_card)

        # Active Transfer Progress Card
        self.transfer_card = QFrame(self)
        self.transfer_card.setObjectName("card")
        self.transfer_card.setVisible(False)
        trans_layout = QVBoxLayout(self.transfer_card)
        trans_layout.setContentsMargins(14, 14, 14, 14)
        trans_layout.setSpacing(8)

        t_header_row = QHBoxLayout()
        self.trans_status_label = QLabel("Receiving Files...", self)
        self.trans_status_label.setObjectName("sectionHeader")
        self.speed_label = QLabel("0.0 MB/s", self)
        self.speed_label.setObjectName("badge")
        self.eta_label = QLabel("ETA: --:--", self)
        self.eta_label.setObjectName("subtitleLabel")
        t_header_row.addWidget(self.trans_status_label)
        t_header_row.addStretch()
        t_header_row.addWidget(self.speed_label)
        t_header_row.addWidget(self.eta_label)
        trans_layout.addLayout(t_header_row)

        self.file_label = QLabel("Waiting for data stream...", self)
        self.file_label.setObjectName("subtitleLabel")
        trans_layout.addWidget(self.file_label)

        self.file_bar = QProgressBar(self)
        self.file_bar.setValue(0)
        trans_layout.addWidget(self.file_bar)

        self.total_bar = QProgressBar(self)
        self.total_bar.setValue(0)
        trans_layout.addWidget(self.total_bar)

        main_layout.addWidget(self.transfer_card)
        main_layout.addStretch()

    def _refresh_network_info(self):
        self.ip_combo.clear()
        ips = get_local_ip_addresses()
        for iface in ips:
            label = f"{iface['name']} — {iface['ip']}"
            self.ip_combo.addItem(label, userData=iface["ip"])

        self._update_qr()

    def _on_ip_selection_changed(self):
        self._update_qr()
        ip = self.ip_combo.currentData() or get_primary_ip()
        self.we_path_label.setText(f"\\\\{ip}@{DEFAULT_WEB_EXPLORER_PORT}\\DavWWWRoot")

    def _copy_explorer_unc(self):
        unc = self.we_path_label.text()
        QApplication.clipboard().setText(unc)
        QMessageBox.information(
            self,
            "Address Copied",
            f"Windows File Explorer address copied to clipboard:\n\n{unc}\n\n"
            f"On another laptop, press Win + R or paste this into Windows File Explorer address bar to explore and copy files!"
        )

    def _open_web_portal(self):
        ip = self.ip_combo.currentData() or "127.0.0.1"
        url = f"http://{ip}:{DEFAULT_WEB_EXPLORER_PORT}/"
        webbrowser.open(url)

    def _update_qr(self):
        ip = self.ip_combo.currentData() or get_primary_ip()
        pin = self.cfg.current_pin
        port = self.cfg.transfer_port
        # Encode connection URI
        uri = f"laptopshare://{ip}:{port}?pin={pin}"
        self.qr_widget.set_data(uri)

    def _generate_new_pin(self):
        new_pin = generate_pin()
        self.cfg.current_pin = new_pin
        ConfigManager().save()
        self.pin_label.setText(new_pin)
        self._update_qr()

    def _browse_destination(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Download Destination Folder", self.cfg.download_dir)
        if folder:
            self.cfg.download_dir = folder
            ConfigManager().save()
            self.dest_path_label.setText(folder)

    def _open_destination(self):
        folder = self.cfg.download_dir
        if Path(folder).exists():
            os.startfile(folder)
        else:
            QMessageBox.warning(self, "Folder Not Found", f"Directory does not exist: {folder}")

    # Server bridge slots
    def _on_approval_required(self, data: dict):
        self.pending_req_id = data["req_id"]
        sender = data.get("peer_name", "Unknown")
        ip = data.get("peer_ip", "")
        count = data.get("total_files", 0)
        total_b = data.get("total_bytes", 0)

        self.appr_sender_info.setText(f"From: {sender} ({ip})")
        self.appr_summary_badge.setText(f"{count} files ({format_file_size(total_b)})")

        self.appr_file_list.clear()
        for f in data.get("files", []):
            item = QListWidgetItem(f"📄 {f.get('rel_path')} ({format_file_size(f.get('size', 0))})")
            self.appr_file_list.addItem(item)

        self.approval_card.setVisible(True)

    def _accept_transfer(self):
        if self.pending_req_id:
            self.server.approve_transfer(self.pending_req_id, accepted=True, save_dir=self.cfg.download_dir)
            self.approval_card.setVisible(False)
            self.transfer_card.setVisible(True)
            self.pending_req_id = None

    def _decline_transfer(self):
        if self.pending_req_id:
            self.server.approve_transfer(self.pending_req_id, accepted=False)
            self.approval_card.setVisible(False)
            self.pending_req_id = None

    def _on_browse_approval_required(self, data: dict):
        self.pending_browse_req_id = data["req_id"]
        sender = data.get("peer_name", "Unknown")
        ip = data.get("peer_ip", "")
        self.b_sender_info.setText(
            f"Laptop <b>'{sender}'</b> ({ip}) is requesting permission to browse files and copy them to their laptop."
        )
        self.browse_card.setVisible(True)

    def _grant_browse(self):
        if self.pending_browse_req_id:
            self.server.approve_browse(self.pending_browse_req_id, accepted=True)
            self.browse_card.setVisible(False)
            self.pending_browse_req_id = None

    def _deny_browse(self):
        if self.pending_browse_req_id:
            self.server.approve_browse(self.pending_browse_req_id, accepted=False)
            self.browse_card.setVisible(False)
            self.pending_browse_req_id = None

    def _on_migration_approval_required(self, data: dict):
        self.pending_migration_req_id = data["req_id"]
        sender = data.get("peer_name", "Unknown")
        ip = data.get("peer_ip", "")
        self.m_sender_info.setText(
            f"Laptop <b>'{sender}'</b> ({ip}) is requesting permission to scan and migrate user files and profiles to their new laptop."
        )
        self.migration_card.setVisible(True)

    def _grant_migration(self):
        if hasattr(self, "pending_migration_req_id") and self.pending_migration_req_id:
            self.server.approve_migration(self.pending_migration_req_id, accepted=True)
            self.migration_card.setVisible(False)
            self.pending_migration_req_id = None

    def _deny_migration(self):
        if hasattr(self, "pending_migration_req_id") and self.pending_migration_req_id:
            self.server.approve_migration(self.pending_migration_req_id, accepted=False)
            self.migration_card.setVisible(False)
            self.pending_migration_req_id = None

    def _on_transfer_started(self, transfer_id: str, peer_name: str, total_files: int, total_bytes: int):
        self.trans_status_label.setText(f"Receiving from {peer_name}...")
        self.transfer_card.setVisible(True)
        self.file_bar.setValue(0)
        self.total_bar.setValue(0)

    def _on_progress(self, file_id: int, rel_path: str, file_done: int, file_total: int, total_done: int, total_all: int, speed: float, eta: float):
        file_pct = int((file_done / file_total) * 100) if file_total > 0 else 0
        total_pct = int((total_done / total_all) * 100) if total_all > 0 else 0

        self.file_label.setText(f"Saving: {rel_path} ({format_file_size(file_done)} / {format_file_size(file_total)})")
        self.file_bar.setValue(file_pct)
        self.total_bar.setValue(total_pct)
        self.speed_label.setText(format_transfer_speed(speed))
        self.eta_label.setText(f"ETA: {format_time_remaining(eta)}")

    def _on_file_completed(self, rel_path: str, verified: bool):
        if verified:
            self.file_label.setText(f"✅ Verified SHA-256: {rel_path}")
        else:
            self.file_label.setText(f"⚠️ Checksum Mismatch: {rel_path}")

    def _on_transfer_finished(self, transfer_id: str, success: bool, msg: str):
        if success:
            self.trans_status_label.setText("🎉 Transfer Completed & Verified!")
            self.total_bar.setValue(100)
            self.file_bar.setValue(100)
            QMessageBox.information(self, "Received", f"Files received and saved to:\n{self.cfg.download_dir}")
        else:
            self.trans_status_label.setText(f"Transfer Ended: {msg}")
