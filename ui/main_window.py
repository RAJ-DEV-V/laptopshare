"""
LaptopShare Main Window
Provides a Windows 11 Fluent layout with a modern sidebar and 5 main views.
"""

from typing import List

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
    QStackedWidget, QLabel, QFrame, QButtonGroup
)
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QIcon, QFont

from core.config import ConfigManager, APP_NAME, PROTOCOL_VERSION
from core.transfer_server import TransferServer
from core.discovery import DiscoveryService, PeerDevice
from core.web_explorer_server import WebExplorerServer
from ui.styles import DARK_THEME, LIGHT_THEME
from ui.send_tab import SendTab
from ui.receive_tab import ReceiveTab
from ui.browse_tab import BrowseTab
from ui.migration_tab import MigrationTab
from ui.devices_tab import DevicesTab
from ui.history_tab import HistoryTab
from ui.settings_tab import SettingsTab

class PeerUpdateBridge(QObject):
    peers_updated = Signal(list)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg_mgr = ConfigManager()
        self.cfg = self.cfg_mgr.get()

        self.setWindowTitle(f"{APP_NAME} — Fast LAN File Sharing")
        self.resize(1000, 680)
        self.setMinimumSize(850, 580)

        # Core services
        self.server = TransferServer(port=self.cfg.transfer_port)
        self.discovery = DiscoveryService(port=self.cfg.discovery_port)
        self.web_explorer = WebExplorerServer()

        # Peer update bridge for Qt thread safety
        self.peer_bridge = PeerUpdateBridge()
        self.peer_bridge.peers_updated.connect(self._on_peers_updated_main_thread)
        self.discovery.on_peers_updated = lambda peers: self.peer_bridge.peers_updated.emit(peers)

        # Build UI
        self._init_ui()

        # Apply theme
        self.apply_theme(self.cfg.theme)

        # Start background services
        self.server.start()
        self.discovery.start()
        self.web_explorer.start()

    def _init_ui(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        root_layout = QHBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Sidebar Frame
        sidebar = QFrame(self)
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        sidebar.setStyleSheet("""
            QFrame#sidebar {
                background-color: #17181c;
                border-right: 1px solid #27282f;
            }
        """)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(14, 20, 14, 20)
        sb_layout.setSpacing(8)

        # App Brand Header
        brand_box = QHBoxLayout()
        logo_icon = QLabel("⚡", sidebar)
        logo_icon.setStyleSheet("font-size: 24px;")
        brand_box.addWidget(logo_icon)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        app_title = QLabel(APP_NAME, sidebar)
        app_title.setStyleSheet("font-size: 16px; font-weight: 700; color: #ffffff;")
        version_label = QLabel(f"v{PROTOCOL_VERSION} LAN Peer", sidebar)
        version_label.setStyleSheet("font-size: 11px; color: #64748b;")
        title_box.addWidget(app_title)
        title_box.addWidget(version_label)
        brand_box.addLayout(title_box)
        brand_box.addStretch()

        sb_layout.addLayout(brand_box)
        sb_layout.addSpacing(20)

        # Nav Buttons
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        self.btn_send = self._create_nav_button("📤  Send Files", 0)
        self.btn_receive = self._create_nav_button("📥  Receive Files", 1)
        self.btn_browse = self._create_nav_button("📂  Browse & Copy", 2)
        self.btn_migrate = self._create_nav_button("🔄  PC Migration", 3)
        self.btn_devices = self._create_nav_button("📡  Nearby Devices", 4)
        self.btn_history = self._create_nav_button("📜  Transfer History", 5)
        self.btn_settings = self._create_nav_button("⚙️  Settings", 6)

        sb_layout.addWidget(self.btn_send)
        sb_layout.addWidget(self.btn_receive)
        sb_layout.addWidget(self.btn_browse)
        sb_layout.addWidget(self.btn_migrate)
        sb_layout.addWidget(self.btn_devices)
        sb_layout.addWidget(self.btn_history)
        sb_layout.addWidget(self.btn_settings)

        sb_layout.addStretch()

        # Theme toggle button
        self.theme_btn = QPushButton("🌙 Dark Mode", sidebar)
        self.theme_btn.clicked.connect(self._toggle_theme)
        sb_layout.addWidget(self.theme_btn)

        root_layout.addWidget(sidebar)

        # Stacked view container
        self.stack = QStackedWidget(self)

        self.send_tab = SendTab(self)
        self.receive_tab = ReceiveTab(self.server, self)
        self.browse_tab = BrowseTab(self)
        self.migration_tab = MigrationTab(self)
        self.devices_tab = DevicesTab(self.discovery, self)
        self.history_tab = HistoryTab(self)
        self.settings_tab = SettingsTab(self)

        # Wire cross-tab interactions
        self.devices_tab.peer_selected_for_send.connect(self._switch_to_send_with_peer)
        self.devices_tab.peer_selected_for_browse.connect(self._switch_to_browse_with_peer)
        self.devices_tab.peer_selected_for_migrate.connect(self._switch_to_migrate_with_peer)
        self.settings_tab.theme_changed.connect(self.apply_theme)

        self.stack.addWidget(self.send_tab)
        self.stack.addWidget(self.receive_tab)
        self.stack.addWidget(self.browse_tab)
        self.stack.addWidget(self.migration_tab)
        self.stack.addWidget(self.devices_tab)
        self.stack.addWidget(self.history_tab)
        self.stack.addWidget(self.settings_tab)

        root_layout.addWidget(self.stack)

        # Select Send tab by default
        self.btn_send.setChecked(True)

    def _create_nav_button(self, text: str, index: int) -> QPushButton:
        btn = QPushButton(text, self)
        btn.setCheckable(True)
        btn.setFixedHeight(40)
        btn.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding-left: 14px;
                font-size: 13px;
                font-weight: 500;
                border: none;
                border-radius: 8px;
                color: #94a3b8;
                background-color: transparent;
            }
            QPushButton:hover {
                background-color: #22232a;
                color: #f1f5f9;
            }
            QPushButton:checked {
                background-color: #0284c7;
                color: #ffffff;
                font-weight: 600;
            }
        """)
        btn.clicked.connect(lambda: self._on_nav_clicked(index))
        self.nav_group.addButton(btn, index)
        return btn

    def _on_nav_clicked(self, index: int):
        self.stack.setCurrentIndex(index)
        if index == 5:
            self.history_tab.refresh_records()

    def _switch_to_send_with_peer(self, peer: PeerDevice):
        self.send_tab.set_target_peer(peer)
        self.btn_send.setChecked(True)
        self.stack.setCurrentIndex(0)

    def _switch_to_browse_with_peer(self, peer: PeerDevice):
        self.browse_tab.target_mode_combo.setCurrentIndex(0)
        for i in range(self.browse_tab.peer_combo.count()):
            p = self.browse_tab.peer_combo.itemData(i)
            if p and p.ip == peer.ip:
                self.browse_tab.peer_combo.setCurrentIndex(i)
                break
        self.btn_browse.setChecked(True)
        self.stack.setCurrentIndex(2)

    def _switch_to_migrate_with_peer(self, peer: PeerDevice):
        self.migration_tab.target_mode_combo.setCurrentIndex(0)
        for i in range(self.migration_tab.peer_combo.count()):
            p = self.migration_tab.peer_combo.itemData(i)
            if p and p.ip == peer.ip:
                self.migration_tab.peer_combo.setCurrentIndex(i)
                break
        self.btn_migrate.setChecked(True)
        self.stack.setCurrentIndex(3)

    def _on_peers_updated_main_thread(self, peers: List[PeerDevice]):
        self.send_tab.update_peers(peers)
        self.browse_tab.update_peers(peers)
        self.migration_tab.update_peers(peers)
        self.devices_tab.update_peers(peers)

    def _toggle_theme(self):
        new_theme = "light" if self.cfg.theme == "dark" else "dark"
        self.cfg.theme = new_theme
        self.cfg_mgr.save()
        self.apply_theme(new_theme)
        self.settings_tab.theme_combo.setCurrentText(new_theme)

    def apply_theme(self, theme: str):
        if theme == "light":
            self.setStyleSheet(LIGHT_THEME)
            self.theme_btn.setText("☀️ Light Mode")
        else:
            self.setStyleSheet(DARK_THEME)
            self.theme_btn.setText("🌙 Dark Mode")

    def closeEvent(self, event):
        """Safely shut down background networking threads on window close."""
        self.discovery.stop()
        self.server.stop()
        self.web_explorer.stop()
        super().closeEvent(event)
