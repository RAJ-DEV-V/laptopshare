r"""
LaptopShare Ethernet & Direct Cable Sharing Tab
Provides direct laptop-to-laptop Ethernet (Cat5e/Cat6) and USB-C sharing,
1-click virtual drive mounting (Drive E:\ or U:\) in Windows File Explorer,
in-app Remote File Explorer launch, and shared folder access control.
"""

import os
import time
import socket
import threading
import webbrowser
from pathlib import Path
from typing import Optional, List

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QMessageBox, QCheckBox, QComboBox, QLineEdit,
    QProgressBar, QScrollArea, QGroupBox
)
from PySide6.QtCore import Qt, Signal, QObject, Slot, QMetaObject, Q_ARG

from core.config import ConfigManager, DEFAULT_TRANSFER_PORT
from core.usb_detector import USBDetectionService, HardwareAuditReport, DirectLinkAdapter
from core.virtual_drive import (
    mount_usb_laptop_drive,
    mount_ethernet_laptop_drive,
    unmount_usb_laptop_drive,
    open_virtual_drive,
    is_drive_mounted,
    DEFAULT_DRIVE_LETTER,
    DEFAULT_DRIVE_LABEL,
    DEFAULT_ETHERNET_DRIVE_LETTER,
    DEFAULT_ETHERNET_DRIVE_LABEL,
    enable_windows_webclient_permissions,
    get_webclient_basic_auth_level
)
from core.web_explorer_server import DEFAULT_WEB_EXPLORER_PORT
from core.network_utils import get_ethernet_status, open_network_connections

class USBLinkBridge(QObject):
    cable_connected = Signal(object, str)
    cable_disconnected = Signal()
    status_updated = Signal(object)
    mount_result = Signal(bool, str, str, bool)

class USBLinkTab(QWidget):
    open_file_explorer_requested = Signal(str)  # emitted when user wants to browse peer in app explorer

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg = ConfigManager().get()

        self.service = USBDetectionService(check_interval_sec=2.0)
        self.bridge = USBLinkBridge()

        self.bridge.cable_connected.connect(self._on_cable_connected)
        self.bridge.cable_disconnected.connect(self._on_cable_disconnected)
        self.bridge.status_updated.connect(self._on_status_updated)
        self.bridge.mount_result.connect(self._on_mount_result)

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
        title = QLabel("🌐 Direct Ethernet & Cable Sharing", self)
        title.setObjectName("titleLabel")
        subtitle = QLabel("Ultra-fast plug-and-play laptop-to-laptop file sharing via direct Ethernet cable or USB-C link", self)
        subtitle.setObjectName("subtitleLabel")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header_row.addLayout(title_box)
        header_row.addStretch()

        self.status_badge = QLabel("○ Awaiting Direct Cable Connection", self)
        self.status_badge.setObjectName("badge")
        self.status_badge.setStyleSheet("background-color: #334155; color: #cbd5e1; padding: 6px 14px; font-size: 12px; font-weight: 600; border-radius: 6px;")
        header_row.addWidget(self.status_badge)
        main_layout.addLayout(header_row)

        # 2. Hero Direct Cable Connection & Windows Explorer Card
        self.conn_card = QFrame(self)
        self.conn_card.setObjectName("card")
        self.conn_card.setStyleSheet("QFrame#card { border: 2px solid #0284c7; background-color: #0f172a; border-radius: 10px; }")
        conn_layout = QVBoxLayout(self.conn_card)
        conn_layout.setContentsMargins(18, 16, 18, 16)
        conn_layout.setSpacing(12)

        c_header = QHBoxLayout()
        self.conn_card_title = QLabel("💻 Connected Laptop (Windows File Explorer)", self)
        self.conn_card_title.setStyleSheet("font-size: 16px; font-weight: 700; color: #38bdf8;")
        self.speed_badge = QLabel("Standby", self)
        self.speed_badge.setStyleSheet("background-color: #0369a1; color: #e0f2fe; padding: 4px 10px; border-radius: 4px; font-size: 12px; font-weight: 600;")
        c_header.addWidget(self.conn_card_title)
        c_header.addStretch()
        c_header.addWidget(self.speed_badge)
        conn_layout.addLayout(c_header)

        self.conn_desc = QLabel("Plug an Ethernet cable (Cat5e/Cat6) directly between both laptops to share files and mount remote folders in File Explorer.", self)
        self.conn_desc.setObjectName("subtitleLabel")
        conn_layout.addWidget(self.conn_desc)

        # Direct Link Connection Details
        info_grid = QHBoxLayout()
        info_grid.setSpacing(16)

        self.cable_type_label = QLabel("Connection Mode: Standby", self)
        self.cable_type_label.setStyleSheet("color: #cbd5e1; font-weight: 500;")
        info_grid.addWidget(self.cable_type_label)

        self.drive_status_label = QLabel("Mounted Location: Not Mounted", self)
        self.drive_status_label.setStyleSheet("font-weight: 600; color: #94a3b8;")
        info_grid.addWidget(self.drive_status_label)
        info_grid.addStretch()
        conn_layout.addLayout(info_grid)

        # Remote Laptop IP row (Auto-detected + Manual Override)
        ip_row = QHBoxLayout()
        ip_lbl = QLabel("Remote Laptop IP:", self)
        ip_lbl.setStyleSheet("color: #94a3b8; font-weight: 600;")
        ip_row.addWidget(ip_lbl)

        self.remote_ip_input = QLineEdit(self)
        self.remote_ip_input.setPlaceholderText("Auto-detecting... or enter peer IP (e.g. 169.254.x.x)")
        self.remote_ip_input.setFixedWidth(260)
        ip_row.addWidget(self.remote_ip_input)

        connect_peer_btn = QPushButton("Connect to IP", self)
        connect_peer_btn.clicked.connect(self._on_manual_ip_connect)
        ip_row.addWidget(connect_peer_btn)
        ip_row.addStretch()
        conn_layout.addLayout(ip_row)

        # Primary Action Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.open_explorer_btn = QPushButton("📂 Open in Windows File Explorer (Drive E:)", self)
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

        self.open_in_app_explorer_btn = QPushButton("📁 Open in Remote File Explorer", self)
        self.open_in_app_explorer_btn.setStyleSheet("""
            QPushButton {
                background-color: #059669;
                color: #ffffff;
                font-size: 13px;
                font-weight: 700;
                padding: 10px 16px;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover {
                background-color: #047857;
            }
        """)
        self.open_in_app_explorer_btn.clicked.connect(self._open_in_app_explorer)
        btn_row.addWidget(self.open_in_app_explorer_btn)

        self.mount_btn = QPushButton("🔌 Mount Drive (E:)", self)
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

        self.fix_perms_btn = QPushButton("🔓 Fix Windows Permissions", self)
        self.fix_perms_btn.setObjectName("secondaryButton")
        self.fix_perms_btn.setToolTip("Configure Windows WebClient registry permissions (BasicAuthLevel=2) so Windows File Explorer can mount remote laptops without access denied errors.")
        self.fix_perms_btn.clicked.connect(self._on_fix_permissions_clicked)
        btn_row.addWidget(self.fix_perms_btn)

        btn_row.addStretch()
        conn_layout.addLayout(btn_row)
        main_layout.addWidget(self.conn_card)

        # 3. Direct Ethernet Information & Setup Guide
        eth_card = QFrame(self)
        eth_card.setObjectName("card")
        eth_card.setStyleSheet("QFrame#card { background-color: #131d2e; border: 1px solid #1e293b; border-radius: 8px; }")
        eth_layout = QVBoxLayout(eth_card)
        eth_layout.setContentsMargins(16, 14, 16, 14)
        eth_layout.setSpacing(10)

        eth_header = QHBoxLayout()
        eth_title = QLabel("⚡ Direct Ethernet Speed & Plug-and-Play Guide", eth_card)
        eth_title.setStyleSheet("font-size: 14px; font-weight: 700; color: #38bdf8;")
        eth_header.addWidget(eth_title)
        eth_header.addStretch()

        ncpa_btn = QPushButton("🛠️ Windows Network Connections", eth_card)
        ncpa_btn.clicked.connect(open_network_connections)
        eth_header.addWidget(ncpa_btn)
        eth_layout.addLayout(eth_header)

        self.eth_live_info_label = QLabel(eth_card)
        self.eth_live_info_label.setTextFormat(Qt.RichText)
        self.eth_live_info_label.setWordWrap(True)
        eth_layout.addWidget(self.eth_live_info_label)

        guide_html = """
        <div style="color: #94a3b8; font-size: 12px; line-height: 1.6;">
        • <b>How Direct Ethernet Sharing Works:</b> Connect a standard Cat5e or Cat6 Ethernet cable directly between both laptops (no router or switch needed).<br>
        • <b>Auto-MDIX Crossover:</b> Modern Ethernet network cards (Gigabit & 2.5 GbE) automatically cross over internally. Any regular Ethernet cable works.<br>
        • <b>Automatic IP Configuration:</b> Windows automatically assigns link-local IP addresses (<code>169.254.x.x</code>) within seconds.<br>
        • <b>Wire Speed:</b> Transfers move at full wire speed (<b>~115 MB/s Gigabit</b> sustained). 100 GB transfers in ~14 minutes; 1 TB in ~2.2 hours.
        </div>
        """
        guide_label = QLabel(guide_html, eth_card)
        guide_label.setTextFormat(Qt.RichText)
        guide_label.setWordWrap(True)
        eth_layout.addWidget(guide_label)

        main_layout.addWidget(eth_card)

        # 4. Hardware Capability Audit Matrix
        hw_card = QFrame(self)
        hw_card.setObjectName("card")
        hw_layout = QVBoxLayout(hw_card)
        hw_layout.setContentsMargins(18, 16, 18, 16)
        hw_layout.setSpacing(10)

        hw_header = QHBoxLayout()
        hw_title = QLabel("🔬 Network & USB Hardware Audit (This Laptop)", self)
        hw_title.setStyleSheet("font-size: 14px; font-weight: 700; color: #f1f5f9;")
        refresh_audit_btn = QPushButton("🔄 Refresh Audit", self)
        refresh_audit_btn.clicked.connect(self._refresh_hardware_audit)
        hw_header.addWidget(hw_title)
        hw_header.addStretch()
        hw_header.addWidget(refresh_audit_btn)
        hw_layout.addLayout(hw_header)

        self.model_label = QLabel("Detecting hardware model...", self)
        self.model_label.setStyleSheet("color: #38bdf8; font-weight: 600;")
        hw_layout.addWidget(self.model_label)

        self.diag_summary = QLabel("Auditing network & USB controllers...", self)
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

        # 5. Shared Folders Security Settings
        sec_card = QFrame(self)
        sec_card.setObjectName("card")
        sec_layout = QVBoxLayout(sec_card)
        sec_layout.setContentsMargins(18, 16, 18, 16)
        sec_layout.setSpacing(10)

        sec_title = QLabel("🔒 Shared Folders & Access Control", self)
        sec_title.setStyleSheet("font-size: 14px; font-weight: 700; color: #4ade80;")
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

        scroll.setWidget(scroll_content)
        root_layout.addWidget(scroll)

        # Initial hardware & Ethernet audit
        self._refresh_hardware_audit()

    def _refresh_hardware_audit(self):
        report = self.service.audit_hardware()
        eth = get_ethernet_status()

        self.model_label.setText(f"Laptop Model: {report.laptop_model}")
        self.diag_summary.setText(report.diagnostic_summary)
        self.modes_label.setText("\n".join(report.supported_cable_modes))

        # Update Ethernet Live Info Card
        if eth["is_connected"]:
            eth_html = f"""
            <b>Active Adapter:</b> {eth['adapter_name']} &nbsp;|&nbsp;
            <b>Link Speed:</b> <span style="color: #4ade80; font-weight: bold;">{eth['speed_text']}</span> &nbsp;|&nbsp;
            <b>Assigned IP:</b> <code>{eth.get('ipv4', 'Acquiring...')}</code>
            """
            self.eth_live_info_label.setText(eth_html)
        else:
            self.eth_live_info_label.setText(
                "<i>Ethernet cable is currently unplugged. Plug a standard Cat5e/Cat6 cable into the RJ-45 port to activate.</i>"
            )

        if report.active_direct_cable:
            self._on_cable_connected(report.active_direct_cable, self.service.connected_peer_ip or "")
        elif eth["is_connected"]:
            # Ethernet is up, show active badge
            self.status_badge.setText(f"● Direct Ethernet Active ({eth['speed_text']})")
            self.status_badge.setStyleSheet("background-color: #059669; color: #ecfdf5; padding: 6px 14px; font-size: 12px; font-weight: 700; border-radius: 6px;")
            self.speed_badge.setText(f"Speed: {eth['speed_text']}")
            self.cable_type_label.setText(f"Connection Mode: Direct Ethernet Cable ({eth['adapter_name']})")
            if eth.get("ipv4"):
                self.conn_desc.setText(f"Ethernet connection active at local address {eth['ipv4']}. Ready to share and browse remote files.")
        else:
            self.status_badge.setText("○ Awaiting Direct Cable Connection")
            self.status_badge.setStyleSheet("background-color: #334155; color: #cbd5e1; padding: 6px 14px; font-size: 12px; font-weight: 600; border-radius: 6px;")
            self.speed_badge.setText("Standby")
            self.cable_type_label.setText("Connection Mode: Standby")

    def _on_cable_connected(self, adapter: DirectLinkAdapter, peer_ip: str):
        self.last_connected_ip = peer_ip if peer_ip else self.remote_ip_input.text().strip()
        if self.last_connected_ip:
            self.remote_ip_input.setText(self.last_connected_ip)

        self.status_badge.setText(f"● Direct Cable Connected ({adapter.cable_type})")
        self.status_badge.setStyleSheet("background-color: #059669; color: #ecfdf5; padding: 6px 14px; font-size: 12px; font-weight: 700; border-radius: 6px;")
        self.speed_badge.setText(f"Speed: {adapter.link_speed}")
        self.cable_type_label.setText(f"Connection Mode: {adapter.cable_type} ({adapter.name})")

        # Automatically mount virtual drive asynchronously (never blocking Qt GUI)
        target_ip = self.last_connected_ip or "127.0.0.1"
        is_eth = "ethernet" in adapter.name.lower() or "ethernet" in adapter.cable_type.lower()
        pref_letter = DEFAULT_ETHERNET_DRIVE_LETTER if is_eth else DEFAULT_DRIVE_LETTER
        pref_label = DEFAULT_ETHERNET_DRIVE_LABEL if is_eth else DEFAULT_DRIVE_LABEL

        def bg_auto_mount():
            ok, drive, msg = mount_usb_laptop_drive(
                remote_ip=target_ip,
                port=DEFAULT_WEB_EXPLORER_PORT,
                preferred_letter=pref_letter,
                drive_label=pref_label,
                open_explorer=False
            )
            self.bridge.mount_result.emit(ok, drive, msg, False)

        threading.Thread(target=bg_auto_mount, daemon=True).start()

    def _on_cable_disconnected(self):
        eth = get_ethernet_status()
        if not eth["is_connected"]:
            self.status_badge.setText("○ Direct Cable Disconnected")
            self.status_badge.setStyleSheet("background-color: #334155; color: #cbd5e1; padding: 6px 14px; font-size: 12px; font-weight: 600; border-radius: 6px;")
            self.speed_badge.setText("Disconnected")
            self.cable_type_label.setText("Connection Mode: Standby")
            if self.current_mounted_drive:
                unmount_usb_laptop_drive(self.current_mounted_drive)
                self.current_mounted_drive = None
                self.drive_status_label.setText("Mounted Location: Not Mounted")
                self.drive_status_label.setStyleSheet("font-weight: 600; color: #94a3b8;")

    def _on_status_updated(self, report: HardwareAuditReport):
        eth = get_ethernet_status()
        if eth["is_connected"] and not report.active_direct_cable:
            self.status_badge.setText(f"● Direct Ethernet Active ({eth['speed_text']})")
            self.status_badge.setStyleSheet("background-color: #059669; color: #ecfdf5; padding: 6px 14px; font-size: 12px; font-weight: 700; border-radius: 6px;")
            self.speed_badge.setText(f"Speed: {eth['speed_text']}")
            self.cable_type_label.setText(f"Connection Mode: Direct Ethernet Cable ({eth['adapter_name']})")
        elif not report.active_direct_cable and not self.current_mounted_drive and not eth["is_connected"]:
            self.status_badge.setText("○ Awaiting Direct Cable Connection")

    def _on_manual_ip_connect(self):
        target = self.remote_ip_input.text().strip()
        if not target:
            QMessageBox.warning(self, "IP Missing", "Please enter the IP address of the connected laptop.")
            return
        self.last_connected_ip = target
        self._manual_mount_drive(open_explorer=True)

    def _open_explorer_drive(self):
        drive = self.current_mounted_drive or DEFAULT_ETHERNET_DRIVE_LETTER
        if is_drive_mounted(drive):
            open_virtual_drive(drive)
        else:
            self._manual_mount_drive(open_explorer=True)

    def _open_in_app_explorer(self):
        target_ip = self.remote_ip_input.text().strip() or self.last_connected_ip or "127.0.0.1"
        self.open_file_explorer_requested.emit(target_ip)

    def _manual_mount_drive(self, open_explorer: bool = True):
        target_ip = self.remote_ip_input.text().strip() or self.last_connected_ip or "127.0.0.1"
        pref_letter = DEFAULT_ETHERNET_DRIVE_LETTER
        pref_label = DEFAULT_ETHERNET_DRIVE_LABEL

        # Set UI to async loading state (never freeze Qt)
        self.open_explorer_btn.setEnabled(False)
        self.mount_btn.setEnabled(False)
        self.open_explorer_btn.setText("⏳ Mounting Drive E:... (No Lag)")

        def bg_worker():
            ok, drive, msg = mount_ethernet_laptop_drive(
                remote_ip=target_ip,
                port=DEFAULT_WEB_EXPLORER_PORT,
                preferred_letter=pref_letter,
                drive_label=pref_label,
                open_explorer=open_explorer
            )
            self.bridge.mount_result.emit(ok, drive, msg, open_explorer)

        threading.Thread(target=bg_worker, daemon=True).start()

    @Slot(bool, str, str, bool)
    def _on_mount_result(self, ok: bool, drive: str, msg: str, open_explorer: bool):
        # Restore button states
        self.open_explorer_btn.setEnabled(True)
        self.mount_btn.setEnabled(True)
        self.open_explorer_btn.setText("📂 Open in Windows File Explorer (Drive E:)")

        if ok:
            self.current_mounted_drive = drive
            self.drive_status_label.setText(f"Mounted Location: {drive}\\ ({DEFAULT_ETHERNET_DRIVE_LABEL})")
            self.drive_status_label.setStyleSheet("font-weight: 700; color: #4ade80;")
            if not open_explorer:
                QMessageBox.information(
                    self,
                    "Virtual Drive Mounted",
                    f"Successfully mounted connected laptop as:\n\n{drive}\\ ({DEFAULT_ETHERNET_DRIVE_LABEL})\n\n"
                    f"You can now browse, drag, drop, and copy files directly in Windows File Explorer!"
                )
        else:
            auth_level = get_webclient_basic_auth_level()
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("Windows Explorer Mount Helper")

            if "WINDOWS_PERMISSION_REQUIRED" in msg or auth_level < 2:
                box.setText(
                    "<b>Windows File Explorer Permission Restriction Detected</b><br><br>"
                    "Windows blocks unencrypted network drive mapping by default (<code>BasicAuthLevel = 1</code>). "
                    "This causes Windows to report <i>'Access is denied'</i> or freeze.<br><br>"
                    "Choose an option below:"
                )
                fix_btn = box.addButton("🔓 1-Click Fix Windows Permissions", QMessageBox.ActionRole)
                app_btn = box.addButton("📁 Open Built-in Remote Explorer (Zero Setup)", QMessageBox.ActionRole)
                box.addButton(QMessageBox.Cancel)

                box.exec_()
                clicked = box.clickedButton()
                if clicked == fix_btn:
                    self._on_fix_permissions_clicked()
                elif clicked == app_btn:
                    self._open_in_app_explorer()
            else:
                box.setText(
                    f"<b>Could not mount Windows virtual drive:</b><br>{msg}<br><br>"
                    "You can browse and transfer files at full speed using LaptopShare's built-in Remote File Explorer:"
                )
                app_btn = box.addButton("📁 Open Built-in Remote Explorer", QMessageBox.ActionRole)
                web_btn = box.addButton("🌐 Open Web Explorer", QMessageBox.ActionRole)
                box.addButton(QMessageBox.Cancel)

                box.exec_()
                clicked = box.clickedButton()
                if clicked == app_btn:
                    self._open_in_app_explorer()
                elif clicked == web_btn:
                    self._open_browser_portal()

    def _on_fix_permissions_clicked(self):
        ok, msg = enable_windows_webclient_permissions()
        if ok:
            QMessageBox.information(
                self,
                "Windows Permissions Update",
                "A Windows User Account Control (UAC) prompt has been requested.<br><br>"
                "1. Click <b>'Yes'</b> on the Windows UAC dialog.<br>"
                "2. Windows will set <code>BasicAuthLevel = 2</code>, unlock 4GB file transfers, and restart WebClient.<br><br>"
                "Once confirmed, click <b>'Open in Windows File Explorer'</b> again to mount Drive E:!"
            )
        else:
            QMessageBox.warning(self, "Permission Update Failed", msg)

    def _unmount_drive(self):
        drive = self.current_mounted_drive or DEFAULT_ETHERNET_DRIVE_LETTER
        if is_drive_mounted(drive):
            unmount_usb_laptop_drive(drive)
            self.current_mounted_drive = None
            self.drive_status_label.setText("Mounted Location: Not Mounted")
            self.drive_status_label.setStyleSheet("font-weight: 600; color: #94a3b8;")
            QMessageBox.information(self, "Drive Unmounted", f"Safely unmounted drive {drive}\\ from Windows File Explorer.")
        else:
            QMessageBox.information(self, "Drive Unmounted", f"Drive {drive}\\ is not currently mounted.")

    def _open_browser_portal(self):
        target_ip = self.remote_ip_input.text().strip() or self.last_connected_ip or "127.0.0.1"
        url = f"http://{target_ip}:{DEFAULT_WEB_EXPLORER_PORT}/"
        webbrowser.open(url)

    def closeEvent(self, event):
        self.service.stop()
        if self.current_mounted_drive:
            unmount_usb_laptop_drive(self.current_mounted_drive)
        super().closeEvent(event)
