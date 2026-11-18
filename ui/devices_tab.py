"""
LaptopShare Nearby Devices Tab
Displays nearby laptops discovered on local Wi-Fi, provides quick connect buttons,
and manual IP discovery probe.
"""

from typing import List, Callable, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QFrame, QLineEdit, QMessageBox
)
from PySide6.QtCore import Qt, Signal

from core.discovery import DiscoveryService, PeerDevice
from core.web_explorer_server import mount_remote_in_windows_explorer, DEFAULT_WEB_EXPLORER_PORT

class DeviceCardWidget(QFrame):
    def __init__(
        self,
        peer: PeerDevice,
        on_send_clicked: Callable[[PeerDevice], None],
        on_browse_clicked: Callable[[PeerDevice], None],
        on_migrate_clicked: Callable[[PeerDevice], None],
        parent=None
    ):
        super().__init__(parent)
        self.peer = peer
        self.setObjectName("card")
        self.setFixedHeight(75)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        icon_label = QLabel("💻", self)
        icon_label.setStyleSheet("font-size: 26px;")
        layout.addWidget(icon_label)

        info_box = QVBoxLayout()
        info_box.setSpacing(2)
        name_label = QLabel(peer.device_name, self)
        name_label.setObjectName("sectionHeader")
        ip_label = QLabel(f"IP: {peer.ip}:{peer.port}  •  OS: {peer.os_name}  •  Status: Online", self)
        ip_label.setObjectName("subtitleLabel")
        info_box.addWidget(name_label)
        info_box.addWidget(ip_label)
        layout.addLayout(info_box)

        layout.addStretch()

        migrate_btn = QPushButton("🔄 Migrate PC", self)
        migrate_btn.setToolTip("Seamlessly migrate Desktop, Documents, Photos & Browser data from this laptop")
        migrate_btn.clicked.connect(lambda: on_migrate_clicked(self.peer))
        layout.addWidget(migrate_btn)

        browse_btn = QPushButton("📂 Browse", self)
        browse_btn.clicked.connect(lambda: on_browse_clicked(self.peer))
        layout.addWidget(browse_btn)

        explorer_btn = QPushButton("🗂️ Explorer", self)
        explorer_btn.setToolTip("Mount and open in native Windows File Explorer (Drive Z:)")
        explorer_btn.clicked.connect(self._open_in_windows_explorer)
        layout.addWidget(explorer_btn)

        send_btn = QPushButton("📤 Send Files", self)
        send_btn.setObjectName("primaryButton")
        send_btn.clicked.connect(lambda: on_send_clicked(self.peer))
        layout.addWidget(send_btn)

    def _open_in_windows_explorer(self):
        ok, drive_or_unc, msg = mount_remote_in_windows_explorer(self.peer.ip, DEFAULT_WEB_EXPLORER_PORT)
        if ok:
            QMessageBox.information(
                self,
                "Windows Explorer Mounted",
                f"Successfully opened {self.peer.device_name} ({self.peer.ip}) in Windows File Explorer!\n\nLocation: {drive_or_unc}\n\nYou can now copy, drag and drop files directly between laptops."
            )
        else:
            QMessageBox.information(
                self,
                "Windows Explorer Info",
                f"{msg}\n\nTo open manually in Windows Explorer: Press Win + R and enter:\n\\\\{self.peer.ip}@{DEFAULT_WEB_EXPLORER_PORT}\\DavWWWRoot"
            )

class DevicesTab(QWidget):
    peer_selected_for_send = Signal(object)
    peer_selected_for_browse = Signal(object)
    peer_selected_for_migrate = Signal(object)

    def __init__(self, discovery_service: DiscoveryService, parent=None):
        super().__init__(parent)
        self.discovery = discovery_service
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(14)

        # Header
        header_row = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Nearby Devices", self)
        title.setObjectName("titleLabel")
        subtitle = QLabel("Laptops running LaptopShare on the same Wi-Fi / LAN", self)
        subtitle.setObjectName("subtitleLabel")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header_row.addLayout(title_box)
        header_row.addStretch()

        refresh_btn = QPushButton("🔄 Refresh Scan", self)
        refresh_btn.clicked.connect(self._refresh_scan)
        header_row.addWidget(refresh_btn)
        main_layout.addLayout(header_row)

        # Device List Container
        self.list_container = QVBoxLayout()
        self.list_container.setSpacing(10)

        self.empty_label = QLabel("Scanning local network for LaptopShare devices...\nMake sure LaptopShare is running on the other laptop.", self)
        self.empty_label.setObjectName("subtitleLabel")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet("padding: 40px; font-size: 14px;")
        self.list_container.addWidget(self.empty_label)

        main_layout.addLayout(self.list_container)

        # Manual Direct Probe Card
        probe_card = QFrame(self)
        probe_card.setObjectName("card")
        p_layout = QVBoxLayout(probe_card)
        p_layout.setContentsMargins(14, 14, 14, 14)
        p_layout.setSpacing(8)

        p_title = QLabel("Can't find your laptop automatically?", self)
        p_title.setObjectName("sectionHeader")
        p_sub = QLabel("Some Wi-Fi routers block UDP multicast/broadcast. Enter your other laptop's IP directly to probe:", self)
        p_sub.setObjectName("subtitleLabel")
        p_layout.addWidget(p_title)
        p_layout.addWidget(p_sub)

        probe_row = QHBoxLayout()
        self.probe_ip_input = QLineEdit(self)
        self.probe_ip_input.setPlaceholderText("Enter target IP (e.g. 192.168.1.100)")
        probe_btn = QPushButton("📡 Direct Discovery Probe", self)
        probe_btn.clicked.connect(self._send_direct_probe)

        probe_row.addWidget(self.probe_ip_input)
        probe_row.addWidget(probe_btn)
        p_layout.addLayout(probe_row)

        main_layout.addWidget(probe_card)
        main_layout.addStretch()

    def update_peers(self, peers: List[PeerDevice]):
        # Clear existing cards
        while self.list_container.count():
            item = self.list_container.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        if not peers:
            self.empty_label = QLabel("No nearby LaptopShare devices found yet.\nCheck that Wi-Fi network profile is set to Private and both laptops are on the same Wi-Fi.", self)
            self.empty_label.setObjectName("subtitleLabel")
            self.empty_label.setAlignment(Qt.AlignCenter)
            self.empty_label.setStyleSheet("padding: 40px; font-size: 14px;")
            self.list_container.addWidget(self.empty_label)
            return

        for p in peers:
            card = DeviceCardWidget(
                p,
                on_send_clicked=self._on_send_clicked,
                on_browse_clicked=self._on_browse_clicked,
                on_migrate_clicked=self._on_migrate_clicked,
                parent=self
            )
            self.list_container.addWidget(card)

    def _on_send_clicked(self, peer: PeerDevice):
        self.peer_selected_for_send.emit(peer)

    def _on_browse_clicked(self, peer: PeerDevice):
        self.peer_selected_for_browse.emit(peer)

    def _on_migrate_clicked(self, peer: PeerDevice):
        self.peer_selected_for_migrate.emit(peer)

    def _refresh_scan(self):
        peers = self.discovery.get_peers()
        self.update_peers(peers)

    def _send_direct_probe(self):
        target_ip = self.probe_ip_input.text().strip()
        if not target_ip:
            QMessageBox.warning(self, "IP Required", "Please enter an IP address to probe.")
            return

        self.discovery.direct_probe(target_ip)
        QMessageBox.information(
            self,
            "Probe Sent",
            f"Sent discovery probe to {target_ip}.\nIf LaptopShare is running there, it will appear in the list momentarily."
        )
