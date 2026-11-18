"""
LaptopShare USB-C & Direct Cable Link Tab
Provides real-time USB hardware audit, direct cable link detection,
1-click virtual drive mounting (Drive U:) in Windows File Explorer,
and shared folder security controls.
"""

import os
import subprocess
import webbrowser
from pathlib import Path
from typing import Optional, List

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QMessageBox, QCheckBox, QComboBox, QLineEdit,
    QProgressBar, QScrollArea, QGroupBox
)
from PySide6.QtCore import Qt, Signal, QObject

from core.config import ConfigManager, DEFAULT_TRANSFER_PORT
from core.usb_detector import USBDetectionService, HardwareAuditReport, DirectLinkAdapter
from core.virtual_drive import (
    mount_usb_laptop_drive,
    unmount_usb_laptop_drive,
    open_virtual_drive,
    is_drive_mounted,
    DEFAULT_DRIVE_LETTER,
    DEFAULT_DRIVE_LABEL
)
from core.web_explorer_server import DEFAULT_WEB_EXPLORER_PORT

class USBLinkBridge(QObject):
    cable_connected = Signal(object, str)
    cable_disconnected = Signal()
    status_updated = Signal(object)

class USBLinkTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg = ConfigManager().get()

        self.service = USBDetectionService(check_interval_sec=2.5)
        self.bridge = USBLinkBridge()

        self.bridge.cable_connected.connect(self._on_cable_connected)
        self.bridge.cable_disconnected.connect(self._on_cable_disconnected)
        self.bridge.status_updated.connect(self._on_status_updated)

        self.service.on_cable_connected = lambda adapter, ip: self.bridge.cable_connected.emit(adapter, ip)
        self.service.on_cable_disconnected = lambda: self.bridge.cable_disconnected.emit()
        self.service.on_status_updated = lambda report: self.bridge.status_updated.emit(report)

        self.current_mounted_drive: Optional[str] = None
        self.last_connected_ip: Optional[str] = None

        self._init_ui()
        self.service.start()

    def _init_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        # Scroll Area for clean presentation
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll_content = QWidget()
        main_layout = QVBoxLayout(scroll_content)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(14)

        # 1. Header
        header_row = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("USB-C to USB-C Direct Laptop Sharing", self)
        title.setObjectName("titleLabel")
        subtitle = QLabel("Plug-and-play direct file sharing between two Windows laptops via USB-C or Direct Link", self)
        subtitle.setObjectName("subtitleLabel")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header_row.addLayout(title_box)
        header_row.addStretch()

        self.status_badge = QLabel("○ Awaiting Direct Cable Connection", self)
        self.status_badge.setObjectName("badge")
        self.status_badge.setStyleSheet("background-color: #334155; color: #cbd5e1; padding: 6px 14px; font-size: 12px; font-weight: 600;")
        header_row.addWidget(self.status_badge)
        main_layout.addLayout(header_row)

        # 2. Live Connection & Windows File Explorer Card
        self.conn_card = QFrame(self)
        self.conn_card.setObjectName("card")
        self.conn_card.setStyleSheet("QFrame#card { border: 2px solid #0284c7; background-color: #0f172a; }")
        conn_layout = QVBoxLayout(self.conn_card)
        conn_layout.setContentsMargins(18, 16, 18, 16)
        conn_layout.setSpacing(12)

        c_header = QHBoxLayout()
        c_title = QLabel("💻 Connected Laptop (Windows File Explorer)", self)
        c_title.setStyleSheet("font-size: 16px; font-weight: 700; color: #38bdf8;")
        self.speed_badge = QLabel("Speed: --", self)
        self.speed_badge.setStyleSheet("background-color: #0369a1; color: #e0f2fe; padding: 4px 10px; border-radius: 4px; font-size: 12px; font-weight: 600;")
        c_header.addWidget(c_title)
        c_header.addStretch()
        c_header.addWidget(self.speed_badge)
        conn_layout.addLayout(c_header)

        self.conn_desc = QLabel("Connect both laptops using a compatible USB-C, USB4, or direct transfer cable to mount the remote laptop as a virtual drive.", self)
        self.conn_desc.setObjectName("subtitleLabel")
        conn_layout.addWidget(self.conn_desc)

        # Connection details row
        info_grid = QHBoxLayout()
        info_grid.setSpacing(16)

        self.drive_status_label = QLabel("Mounted Location: Not Mounted", self)
        self.drive_status_label.setStyleSheet("font-weight: 600; color: #94a3b8;")
        info_grid.addWidget(self.drive_status_label)

        self.cable_type_label = QLabel("Connection Mode: Standby", self)
        self.cable_type_label.setStyleSheet("color: #94a3b8;")
        info_grid.addWidget(self.cable_type_label)
        info_grid.addStretch()
        conn_layout.addLayout(info_grid)

        # Action Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.open_explorer_btn = QPushButton("📂 Open in Windows File Explorer (Drive U:)", self)
        self.open_explorer_btn.setStyleSheet("""
            QPushButton {
                background-color: #0284c7;
                color: #ffffff;
                font-size: 13px;
                font-weight: 700;
                padding: 10px 18px;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover {
                background-color: #0369a1;
            }
        """)
        self.open_explorer_btn.clicked.connect(self._open_explorer_drive)
        btn_row.addWidget(self.open_explorer_btn)

        self.mount_btn = QPushButton("🔌 Mount Virtual Drive (U:)", self)
        self.mount_btn.setObjectName("secondaryButton")
        self.mount_btn.clicked.connect(self._manual_mount_drive)
        btn_row.addWidget(self.mount_btn)

        self.unmount_btn = QPushButton("⏏️ Unmount Drive", self)
        self.unmount_btn.setObjectName("dangerButton")
        self.unmount_btn.clicked.connect(self._unmount_drive)
        btn_row.addWidget(self.unmount_btn)

        self.web_btn = QPushButton("🌐 View in Browser", self)
        self.web_btn.setObjectName("secondaryButton")
        self.web_btn.clicked.connect(self._open_browser_portal)
        btn_row.addWidget(self.web_btn)

        btn_row.addStretch()
        conn_layout.addLayout(btn_row)
        main_layout.addWidget(self.conn_card)

        # 3. Hardware Capabilities & Diagnostic Matrix Card
        hw_card = QFrame(self)
        hw_card.setObjectName("card")
        hw_layout = QVBoxLayout(hw_card)
        hw_layout.setContentsMargins(18, 16, 18, 16)
        hw_layout.setSpacing(12)

        hw_header = QHBoxLayout()
        hw_title = QLabel("🔬 USB Hardware Capability Audit (This Laptop)", self)
        hw_title.setStyleSheet("font-size: 15px; font-weight: 700; color: #f1f5f9;")
        refresh_audit_btn = QPushButton("🔄 Refresh Audit", self)
        refresh_audit_btn.clicked.connect(self._refresh_hardware_audit)
        hw_header.addWidget(hw_title)
        hw_header.addStretch()
        hw_header.addWidget(refresh_audit_btn)
        hw_layout.addLayout(hw_header)

        self.model_label = QLabel("Detecting hardware model...", self)
        self.model_label.setStyleSheet("color: #38bdf8; font-weight: 600;")
        hw_layout.addWidget(self.model_label)

        self.diag_summary = QLabel("Auditing USB controllers...", self)
        self.diag_summary.setStyleSheet("background-color: #172033; padding: 10px 14px; border-radius: 6px; font-size: 12px; line-height: 1.5; color: #cbd5e1;")
        self.diag_summary.setWordWrap(True)
        hw_layout.addWidget(self.diag_summary)

        # Supported Cable Modes Box
        modes_box = QGroupBox("Supported Direct Connection Modes:", self)
        modes_layout = QVBoxLayout(modes_box)
        self.modes_label = QLabel("Loading supported modes...", self)
        self.modes_label.setStyleSheet("color: #94a3b8; font-size: 12px; line-height: 1.6;")
        modes_layout.addWidget(self.modes_label)
        hw_layout.addWidget(modes_box)

        main_layout.addWidget(hw_card)

        # 4. Shared Folders Security Settings (Security Requirement #6)
        sec_card = QFrame(self)
        sec_card.setObjectName("card")
        sec_layout = QVBoxLayout(sec_card)
        sec_layout.setContentsMargins(18, 16, 18, 16)
        sec_layout.setSpacing(10)

        sec_title = QLabel("🔒 Shared Folders & Access Control", self)
        sec_title.setStyleSheet("font-size: 15px; font-weight: 700; color: #4ade80;")
        sec_layout.addWidget(sec_title)

        sec_desc = QLabel("Control which folders on this laptop are visible over the direct cable. Entire filesystem is never exposed by default.", self)
        sec_desc.setObjectName("subtitleLabel")
        sec_layout.addWidget(sec_desc)

        folders_row = QHBoxLayout()
        self.chk_desktop = QCheckBox("Desktop", self)
        self.chk_desktop.setChecked(True)
        self.chk_documents = QCheckBox("Documents", self)
        self.chk_documents.setChecked(True)
        self.chk_pictures = QCheckBox("Pictures & Photos", self)
        self.chk_pictures.setChecked(True)
        self.chk_videos = QCheckBox("Videos", self)
        self.chk_videos.setChecked(True)
        self.chk_downloads = QCheckBox("Downloads", self)
        self.chk_downloads.setChecked(True)
        self.chk_drives = QCheckBox("Local Drives (C:, D:)", self)
        self.chk_drives.setChecked(True)

        folders_row.addWidget(self.chk_desktop)
        folders_row.addWidget(self.chk_documents)
        folders_row.addWidget(self.chk_pictures)
        folders_row.addWidget(self.chk_videos)
        folders_row.addWidget(self.chk_downloads)
        folders_row.addWidget(self.chk_drives)
        folders_row.addStretch()
        sec_layout.addLayout(folders_row)

        main_layout.addWidget(sec_card)

        # 5. Cable Guide & Technical Architecture
        guide_card = QFrame(self)
        guide_card.setObjectName("card")
        guide_layout = QVBoxLayout(guide_card)
        guide_layout.setContentsMargins(18, 16, 18, 16)
        guide_layout.setSpacing(10)

        guide_title = QLabel("📖 Direct USB-C Hardware & Cable Guide", self)
        guide_title.setStyleSheet("font-size: 14px; font-weight: 700; color: #cbd5e1;")
        guide_layout.addWidget(guide_title)

        guide_text = QLabel(
            "• <strong>Thunderbolt 4 / USB4 Cable:</strong> When connecting two Thunderbolt/USB4 laptops with a certified 40 Gbps cable, Windows automatically generates a direct 20-40 Gbps host-to-host virtual adapter.<br>"
            "• <strong>USB-C Host-to-Host Bridge Cable:</strong> Standard USB 3.x ports are host-only. A data transfer bridge cable (e.g. Belkin Easy Transfer, Plugable USB-C Transfer, Prolific PL27A1) contains bridging hardware to link two hosts directly.<br>"
            "• <strong>Ordinary USB-C Charging Cable:</strong> Standard phone/charging cables lack host-to-host bridging chips. If using standard cables, LaptopShare automatically activates ultra-high-speed Direct P2P Link so files transfer at full speed without external internet.<br>"
            "• <strong>Windows File Explorer Integration:</strong> Once connected, files appear under <em>This PC > USB-C Connected Laptop (U:)</em> for drag-and-drop and copy/paste.",
            self
        )
        guide_text.setStyleSheet("font-size: 12px; line-height: 1.6; color: #94a3b8;")
        guide_text.setTextFormat(Qt.RichText)
        guide_layout.addWidget(guide_text)

        main_layout.addWidget(guide_card)

        scroll.setWidget(scroll_content)
        root_layout.addWidget(scroll)

        # Initial hardware audit
        self._refresh_hardware_audit()

    def _refresh_hardware_audit(self):
        report = self.service.audit_hardware()
        self.model_label.setText(f"Laptop Model: {report.laptop_model}")
        self.diag_summary.setText(report.diagnostic_summary)
        self.modes_label.setText("\n".join(report.supported_cable_modes))

        if report.active_direct_cable:
            self._on_cable_connected(report.active_direct_cable, self.service.connected_peer_ip or "")
        else:
            self.status_badge.setText("○ Awaiting Direct Cable Connection")
            self.status_badge.setStyleSheet("background-color: #334155; color: #cbd5e1; padding: 6px 14px; font-size: 12px; font-weight: 600;")
            self.speed_badge.setText("Speed: Standby")
            self.cable_type_label.setText("Connection Mode: Standby")

    def _on_cable_connected(self, adapter: DirectLinkAdapter, peer_ip: str):
        self.last_connected_ip = peer_ip if peer_ip else "127.0.0.1"
        self.status_badge.setText(f"● Direct Cable Connected ({adapter.cable_type})")
        self.status_badge.setStyleSheet("background-color: #15803d; color: #dcfce7; padding: 6px 14px; font-size: 12px; font-weight: 700;")
        self.speed_badge.setText(f"Speed: {adapter.link_speed}")
        self.cable_type_label.setText(f"Connection Mode: {adapter.cable_type} ({adapter.name})")

        # Automatically mount virtual drive
        ok, drive, msg = mount_usb_laptop_drive(
            remote_ip=self.last_connected_ip,
            port=DEFAULT_WEB_EXPLORER_PORT,
            preferred_letter=DEFAULT_DRIVE_LETTER,
            drive_label=DEFAULT_DRIVE_LABEL,
            open_explorer=False
        )
        if ok:
            self.current_mounted_drive = drive
            self.drive_status_label.setText(f"Mounted Location: {drive}\\ ({DEFAULT_DRIVE_LABEL})")
            self.drive_status_label.setStyleSheet("font-weight: 700; color: #4ade80;")

    def _on_cable_disconnected(self):
        self.status_badge.setText("○ Direct Cable Disconnected")
        self.status_badge.setStyleSheet("background-color: #334155; color: #cbd5e1; padding: 6px 14px; font-size: 12px; font-weight: 600;")
        self.speed_badge.setText("Speed: Disconnected")
        self.cable_type_label.setText("Connection Mode: Standby")
        if self.current_mounted_drive:
            unmount_usb_laptop_drive(self.current_mounted_drive)
            self.current_mounted_drive = None
            self.drive_status_label.setText("Mounted Location: Not Mounted")
            self.drive_status_label.setStyleSheet("font-weight: 600; color: #94a3b8;")

    def _on_status_updated(self, report: HardwareAuditReport):
        if not report.active_direct_cable and not self.current_mounted_drive:
            self.status_badge.setText("○ Awaiting Direct Cable Connection")

    def _open_explorer_drive(self):
        drive = self.current_mounted_drive or DEFAULT_DRIVE_LETTER
        if is_drive_mounted(drive):
            open_virtual_drive(drive)
        else:
            # Mount and open
            self._manual_mount_drive(open_explorer=True)

    def _manual_mount_drive(self, open_explorer: bool = True):
        target_ip = self.last_connected_ip or "127.0.0.1"
        ok, drive, msg = mount_usb_laptop_drive(
            remote_ip=target_ip,
            port=DEFAULT_WEB_EXPLORER_PORT,
            preferred_letter=DEFAULT_DRIVE_LETTER,
            drive_label=DEFAULT_DRIVE_LABEL,
            open_explorer=open_explorer
        )
        if ok:
            self.current_mounted_drive = drive
            self.drive_status_label.setText(f"Mounted Location: {drive}\\ ({DEFAULT_DRIVE_LABEL})")
            self.drive_status_label.setStyleSheet("font-weight: 700; color: #4ade80;")
            QMessageBox.information(
                self,
                "Virtual Drive Mounted",
                f"Successfully mounted connected laptop as:\n\n{drive}\\ ({DEFAULT_DRIVE_LABEL})\n\n"
                f"You can now browse, drag, drop, and copy files directly in Windows File Explorer!"
            )
        else:
            QMessageBox.warning(self, "Mount Helper", f"Could not mount virtual drive: {msg}")

    def _unmount_drive(self):
        drive = self.current_mounted_drive or DEFAULT_DRIVE_LETTER
        if is_drive_mounted(drive):
            unmount_usb_laptop_drive(drive)
            self.current_mounted_drive = None
            self.drive_status_label.setText("Mounted Location: Not Mounted")
            self.drive_status_label.setStyleSheet("font-weight: 600; color: #94a3b8;")
            QMessageBox.information(self, "Drive Unmounted", f"Safely unmounted drive {drive}\\ from Windows File Explorer.")
        else:
            QMessageBox.information(self, "Drive Unmounted", f"Drive {drive}\\ is not currently mounted.")

    def _open_browser_portal(self):
        target_ip = self.last_connected_ip or "127.0.0.1"
        url = f"http://{target_ip}:{DEFAULT_WEB_EXPLORER_PORT}/"
        webbrowser.open(url)

    def closeEvent(self, event):
        self.service.stop()
        if self.current_mounted_drive:
            unmount_usb_laptop_drive(self.current_mounted_drive)
        super().closeEvent(event)
