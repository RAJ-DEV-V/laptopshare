"""
LaptopShare Remote File Explorer Tab
Provides native Windows-like remote file exploration, breadcrumb navigation,
search filtering, rich file type icons, batch file copying, and 1-click
native Windows File Explorer (explorer.exe) mounting.
"""

import os
import time
import webbrowser
from pathlib import Path
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QLineEdit, QProgressBar, QFrame, QMessageBox, QFileDialog,
    QSplitter, QCheckBox, QApplication
)
from PySide6.QtCore import Qt, Signal, QObject, Slot

from core.config import ConfigManager
from core.remote_browser_client import RemoteBrowserClient
from core.discovery import PeerDevice
from core.file_manager import format_file_size, format_transfer_speed, format_time_remaining
from core.web_explorer_server import (
    mount_remote_in_windows_explorer,
    DEFAULT_WEB_EXPLORER_PORT,
    open_in_windows_explorer
)
from core.virtual_drive import mount_ethernet_laptop_drive, open_virtual_drive, DEFAULT_ETHERNET_DRIVE_LETTER

class PullSignalBridge(QObject):
    progress = Signal(int, str, int, int, int, int, float, float)
    file_done = Signal(str, bool)
    finished = Signal(bool, str)

def get_file_icon_and_type(name: str, is_dir: bool) -> tuple[str, str]:
    if is_dir:
        return "📁", "File folder"
    ext = Path(name).suffix.lower()
    if ext in [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".raw", ".svg"]:
        return "🖼️", f"{ext[1:].upper()} Image"
    if ext in [".mp4", ".mkv", ".mov", ".avi", ".wmv", ".webm", ".flv", ".m4v"]:
        return "🎬", f"{ext[1:].upper()} Video"
    if ext in [".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".wma"]:
        return "🎵", f"{ext[1:].upper()} Audio"
    if ext in [".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".txt", ".rtf", ".md"]:
        return "📄", f"{ext[1:].upper()} Document"
    if ext in [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".iso"]:
        return "📦", f"{ext[1:].upper()} Archive"
    if ext in [".py", ".js", ".ts", ".html", ".css", ".json", ".cpp", ".cs", ".xml"]:
        return "💻", f"{ext[1:].upper()} Code"
    if ext in [".exe", ".msi"]:
        return "⚙️", f"{ext[1:].upper()} Application"
    return "📄", f"{ext[1:].upper()} File" if ext else "File"

class BrowseTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg = ConfigManager().get()
        self.client: Optional[RemoteBrowserClient] = None
        self.current_remote_path = ""
        self.current_items: List[Dict[str, Any]] = []

        # Navigation History Stack
        self.history: List[str] = []
        self.history_index: int = -1

        self.bridge = PullSignalBridge()
        self.bridge.progress.connect(self._on_pull_progress)
        self.bridge.file_done.connect(self._on_pull_file_done)
        self.bridge.finished.connect(self._on_pull_finished)

        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(12)

        # 1. Header
        header_row = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("📁 Remote File Explorer", self)
        title.setObjectName("titleLabel")
        subtitle = QLabel("Explore, browse, and copy files directly from connected laptops, or open in native Windows File Explorer", self)
        subtitle.setObjectName("subtitleLabel")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header_row.addLayout(title_box)
        header_row.addStretch()

        self.conn_status_badge = QLabel("○ Disconnected", self)
        self.conn_status_badge.setObjectName("badge")
        self.conn_status_badge.setStyleSheet("background-color: #3f424b; color: #e2e8f0; padding: 6px 14px; font-size: 12px; font-weight: 600; border-radius: 6px;")
        header_row.addWidget(self.conn_status_badge)
        main_layout.addLayout(header_row)

        # 2. Connection Card
        conn_card = QFrame(self)
        conn_card.setObjectName("card")
        conn_layout = QHBoxLayout(conn_card)
        conn_layout.setContentsMargins(14, 12, 14, 12)
        conn_layout.setSpacing(10)

        self.target_mode_combo = QComboBox(self)
        self.target_mode_combo.addItems(["Nearby Discovered Device", "Direct Ethernet / Manual IP"])
        self.target_mode_combo.currentIndexChanged.connect(self._on_target_mode_changed)
        self.target_mode_combo.setFixedWidth(220)
        conn_layout.addWidget(self.target_mode_combo)

        self.peer_combo = QComboBox(self)
        self.peer_combo.setPlaceholderText("Select remote laptop...")
        conn_layout.addWidget(self.peer_combo)

        self.manual_ip = QLineEdit(self)
        self.manual_ip.setPlaceholderText("Remote IP (e.g. 169.254.x.x or 192.168.x.x)")
        self.manual_ip.setVisible(False)
        conn_layout.addWidget(self.manual_ip)

        self.pin_input = QLineEdit(self)
        self.pin_input.setPlaceholderText("6-Digit PIN")
        self.pin_input.setText("123456")
        self.pin_input.setMaxLength(6)
        self.pin_input.setFixedWidth(95)
        conn_layout.addWidget(self.pin_input)

        self.connect_btn = QPushButton("🔑 Connect & Explore", self)
        self.connect_btn.setObjectName("primaryButton")
        self.connect_btn.clicked.connect(self._connect_and_request_access)
        conn_layout.addWidget(self.connect_btn)

        self.disconnect_btn = QPushButton("Disconnect", self)
        self.disconnect_btn.setObjectName("dangerButton")
        self.disconnect_btn.setVisible(False)
        self.disconnect_btn.clicked.connect(self._disconnect)
        conn_layout.addWidget(self.disconnect_btn)

        main_layout.addWidget(conn_card)

        # 3. Direct Windows Explorer & Web Quick Action Bar
        exp_bar = QFrame(self)
        exp_bar.setObjectName("card")
        exp_bar.setStyleSheet("QFrame#card { background-color: #111e33; border: 1px solid #1e3a5f; border-radius: 8px; }")
        exp_bar_layout = QHBoxLayout(exp_bar)
        exp_bar_layout.setContentsMargins(14, 10, 14, 10)
        exp_bar_layout.setSpacing(12)

        exp_icon = QLabel("💻", self)
        exp_icon.setStyleSheet("font-size: 20px;")
        exp_bar_layout.addWidget(exp_icon)

        exp_tip = QLabel("<b>Windows File Explorer Integration:</b> Mount this laptop as Drive E: under 'This PC' for native drag & drop:", self)
        exp_tip.setObjectName("subtitleLabel")
        exp_bar_layout.addWidget(exp_tip, stretch=1)

        self.mount_explorer_btn = QPushButton("📂 Open in Windows File Explorer (Drive E:)", self)
        self.mount_explorer_btn.setStyleSheet("""
            QPushButton {
                background-color: #0284c7;
                color: #ffffff;
                font-weight: 700;
                padding: 7px 14px;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover {
                background-color: #0369a1;
            }
        """)
        self.mount_explorer_btn.clicked.connect(self._mount_windows_explorer)
        exp_bar_layout.addWidget(self.mount_explorer_btn)

        self.browser_open_btn = QPushButton("🌐 Web Explorer", self)
        self.browser_open_btn.clicked.connect(self._open_target_web_browser)
        exp_bar_layout.addWidget(self.browser_open_btn)

        self.open_dest_btn = QPushButton("📁 Downloads Folder", self)
        self.open_dest_btn.clicked.connect(self._open_destination_folder)
        exp_bar_layout.addWidget(self.open_dest_btn)

        main_layout.addWidget(exp_bar)

        # 4. Remote File Explorer Viewport Card
        self.explorer_card = QFrame(self)
        self.explorer_card.setObjectName("card")
        exp_layout = QVBoxLayout(self.explorer_card)
        exp_layout.setContentsMargins(14, 14, 14, 14)
        exp_layout.setSpacing(10)

        # Toolbar Row (Navigation, Quick Locations, Path, Filter)
        toolbar_row = QHBoxLayout()
        toolbar_row.setSpacing(8)

        self.back_btn = QPushButton("◀", self)
        self.back_btn.setToolTip("Back")
        self.back_btn.setFixedWidth(34)
        self.back_btn.clicked.connect(self._navigate_back)
        toolbar_row.addWidget(self.back_btn)

        self.forward_btn = QPushButton("▶", self)
        self.forward_btn.setToolTip("Forward")
        self.forward_btn.setFixedWidth(34)
        self.forward_btn.clicked.connect(self._navigate_forward)
        toolbar_row.addWidget(self.forward_btn)

        self.up_btn = QPushButton("⬆ Up", self)
        self.up_btn.setToolTip("Up to parent folder")
        self.up_btn.setFixedWidth(55)
        self.up_btn.clicked.connect(self._navigate_up)
        toolbar_row.addWidget(self.up_btn)

        self.refresh_folder_btn = QPushButton("🔄", self)
        self.refresh_folder_btn.setToolTip("Refresh current directory")
        self.refresh_folder_btn.setFixedWidth(34)
        self.refresh_folder_btn.clicked.connect(self._refresh_current_folder)
        toolbar_row.addWidget(self.refresh_folder_btn)

        self.roots_combo = QComboBox(self)
        self.roots_combo.setToolTip("Quick access locations")
        self.roots_combo.setFixedWidth(200)
        self.roots_combo.currentIndexChanged.connect(self._on_root_selected)
        toolbar_row.addWidget(self.roots_combo)

        self.path_display = QLineEdit(self)
        self.path_display.setReadOnly(True)
        self.path_display.setPlaceholderText("Remote path...")
        toolbar_row.addWidget(self.path_display, stretch=1)

        self.search_filter_input = QLineEdit(self)
        self.search_filter_input.setPlaceholderText("🔍 Filter files...")
        self.search_filter_input.setFixedWidth(160)
        self.search_filter_input.textChanged.connect(self._apply_search_filter)
        toolbar_row.addWidget(self.search_filter_input)

        exp_layout.addLayout(toolbar_row)

        # File List Table
        self.file_table = QTableWidget(self)
        self.file_table.setColumnCount(5)
        self.file_table.setHorizontalHeaderLabels(["", "Name", "Type", "Size", "Date Modified"])
        self.file_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.file_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.file_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.file_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.file_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.file_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.file_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.file_table.setShowGrid(False)
        self.file_table.setStyleSheet("QTableWidget { gridline-color: #1e293b; font-size: 13px; } QTableWidget::item { padding: 6px; }")
        self.file_table.cellDoubleClicked.connect(self._on_table_double_clicked)
        self.file_table.itemChanged.connect(self._on_table_item_changed)
        exp_layout.addWidget(self.file_table)

        # Bottom Selection and Copy Bar
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(10)

        select_all_btn = QPushButton("Select All", self)
        select_all_btn.clicked.connect(self._select_all)
        deselect_all_btn = QPushButton("Deselect All", self)
        deselect_all_btn.clicked.connect(self._deselect_all)
        bottom_row.addWidget(select_all_btn)
        bottom_row.addWidget(deselect_all_btn)

        self.selection_label = QLabel("0 items selected (0 B)", self)
        self.selection_label.setObjectName("badge")
        self.selection_label.setStyleSheet("background-color: #1e293b; color: #38bdf8; padding: 4px 10px; border-radius: 4px; font-weight: 600;")
        bottom_row.addWidget(self.selection_label)

        bottom_row.addStretch()

        dest_lbl = QLabel("Save to:", self)
        self.local_dest_label = QLabel(self.cfg.download_dir, self)
        self.local_dest_label.setStyleSheet("color: #38bdf8; font-weight: 500;")
        browse_dest_btn = QPushButton("Browse...", self)
        browse_dest_btn.clicked.connect(self._browse_dest)
        bottom_row.addWidget(dest_lbl)
        bottom_row.addWidget(self.local_dest_label)
        bottom_row.addWidget(browse_dest_btn)

        self.copy_btn = QPushButton("📥 Copy Selected to This PC", self)
        self.copy_btn.setObjectName("successButton")
        self.copy_btn.setFixedHeight(38)
        self.copy_btn.setStyleSheet("""
            QPushButton {
                background-color: #059669;
                color: #ffffff;
                font-weight: 700;
                font-size: 13px;
                padding: 8px 18px;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover {
                background-color: #047857;
            }
        """)
        self.copy_btn.clicked.connect(self._copy_selected_files)
        bottom_row.addWidget(self.copy_btn)

        exp_layout.addLayout(bottom_row)
        main_layout.addWidget(self.explorer_card)

        # 5. Live High-Speed Download Progress Card
        self.progress_card = QFrame(self)
        self.progress_card.setObjectName("card")
        self.progress_card.setVisible(False)
        p_layout = QVBoxLayout(self.progress_card)
        p_layout.setContentsMargins(14, 14, 14, 14)
        p_layout.setSpacing(8)

        p_header = QHBoxLayout()
        self.p_title_label = QLabel("Transferring Files from Connected Laptop...", self)
        self.p_title_label.setObjectName("sectionHeader")
        self.speed_badge = QLabel("0.0 MB/s", self)
        self.speed_badge.setObjectName("badge")
        self.speed_badge.setStyleSheet("background-color: #0369a1; color: #e0f2fe; padding: 4px 10px; border-radius: 4px; font-weight: bold;")
        self.eta_label = QLabel("ETA: --:--", self)
        self.eta_label.setObjectName("subtitleLabel")
        p_header.addWidget(self.p_title_label)
        p_header.addStretch()
        p_header.addWidget(self.speed_badge)
        p_header.addWidget(self.eta_label)
        p_layout.addLayout(p_header)

        self.p_file_label = QLabel("Receiving stream...", self)
        self.p_file_label.setObjectName("subtitleLabel")
        p_layout.addWidget(self.p_file_label)

        self.file_progress_bar = QProgressBar(self)
        self.file_progress_bar.setValue(0)
        p_layout.addWidget(self.file_progress_bar)

        self.total_progress_bar = QProgressBar(self)
        self.total_progress_bar.setValue(0)
        p_layout.addWidget(self.total_progress_bar)

        cancel_row = QHBoxLayout()
        cancel_row.addStretch()
        cancel_btn = QPushButton("Cancel Download", self)
        cancel_btn.setObjectName("dangerButton")
        cancel_btn.clicked.connect(self._cancel_pull)
        cancel_row.addWidget(cancel_btn)
        p_layout.addLayout(cancel_row)

        main_layout.addWidget(self.progress_card)

        # Disable explorer card until connected
        self.explorer_card.setEnabled(False)

    def connect_to_ip(self, ip: str):
        """Allows other tabs (e.g. Ethernet Tab) to trigger exploration of a specific IP directly."""
        self.target_mode_combo.setCurrentIndex(1)
        self.manual_ip.setText(ip)
        self._connect_and_request_access()

    def _on_target_mode_changed(self, idx: int):
        is_manual = (idx == 1)
        self.peer_combo.setVisible(not is_manual)
        self.manual_ip.setVisible(is_manual)

    def update_peers(self, peers: List[PeerDevice]):
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

    def _get_target_ip_and_port(self) -> tuple[Optional[str], int]:
        if self.target_mode_combo.currentIndex() == 0:
            peer = self.peer_combo.currentData()
            if peer:
                return peer.ip, peer.port
            return None, 52140
        else:
            ip_str = self.manual_ip.text().strip()
            if not ip_str:
                return None, 52140
            if ":" in ip_str:
                parts = ip_str.split(":")
                return parts[0], int(parts[1])
            return ip_str, 52140

    def _connect_and_request_access(self):
        ip, port = self._get_target_ip_and_port()
        if not ip:
            QMessageBox.warning(self, "Select Laptop", "Please select a nearby laptop or enter an Ethernet/LAN IP.")
            return

        pin = self.pin_input.text().strip()
        self.conn_status_badge.setText("⏳ Requesting access on other laptop...")
        self.conn_status_badge.setStyleSheet("background-color: #0369a1; color: #e0f2fe; padding: 6px 14px; border-radius: 6px;")
        self.connect_btn.setEnabled(False)

        self.client = RemoteBrowserClient(target_ip=ip, target_port=port, pin=pin)
        import threading
        def connect_worker():
            success, msg = self.client.connect()
            from PySide6.QtCore import QMetaObject, Q_ARG
            QMetaObject.invokeMethod(self, "_on_connect_result", Qt.QueuedConnection, Q_ARG(bool, success), Q_ARG(str, msg))

        t = threading.Thread(target=connect_worker, daemon=True)
        t.start()

    @Slot(bool, str)
    def _on_connect_result(self, success: bool, msg: str):
        self.connect_btn.setEnabled(True)
        if success:
            self.conn_status_badge.setText(f"● Connected: {self.client.remote_device_name}")
            self.conn_status_badge.setStyleSheet("background-color: #15803d; color: #dcfce7; padding: 6px 14px; font-weight: 700; border-radius: 6px;")
            self.connect_btn.setVisible(False)
            self.disconnect_btn.setVisible(True)
            self.explorer_card.setEnabled(True)

            # Clear and reset history
            self.history = []
            self.history_index = -1

            # Populate roots
            self.roots_combo.clear()
            for r in self.client.roots:
                self.roots_combo.addItem(r["name"], userData=r["path"])

            if self.client.roots:
                self._load_remote_directory(self.client.roots[0]["path"])
        else:
            self.conn_status_badge.setText("○ Disconnected")
            self.conn_status_badge.setStyleSheet("background-color: #3f424b; color: #e2e8f0; padding: 6px 14px; border-radius: 6px;")
            QMessageBox.critical(self, "Connection / Access Failed", f"{msg}\n\nMake sure LaptopShare is running on the other laptop and approval is accepted.")

    def _disconnect(self):
        if self.client:
            self.client.disconnect()
            self.client = None
        self.conn_status_badge.setText("○ Disconnected")
        self.conn_status_badge.setStyleSheet("background-color: #3f424b; color: #e2e8f0; padding: 6px 14px; border-radius: 6px;")
        self.connect_btn.setVisible(True)
        self.disconnect_btn.setVisible(False)
        self.explorer_card.setEnabled(False)
        self.file_table.setRowCount(0)
        self.path_display.clear()
        self.history = []
        self.history_index = -1

    def _on_root_selected(self, idx: int):
        path = self.roots_combo.currentData()
        if path:
            self._navigate_to(path)

    def _navigate_to(self, path: str):
        # Truncate forward history if navigating to new path
        if self.history_index < len(self.history) - 1:
            self.history = self.history[:self.history_index + 1]
        self.history.append(path)
        self.history_index = len(self.history) - 1
        self._load_remote_directory(path)

    def _navigate_back(self):
        if self.history_index > 0:
            self.history_index -= 1
            self._load_remote_directory(self.history[self.history_index])

    def _navigate_forward(self):
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self._load_remote_directory(self.history[self.history_index])

    def _navigate_up(self):
        if not self.current_remote_path:
            return
        parent_p = str(Path(self.current_remote_path).parent)
        if parent_p != self.current_remote_path:
            self._navigate_to(parent_p)

    def _refresh_current_folder(self):
        if self.current_remote_path:
            self._load_remote_directory(self.current_remote_path)

    def _load_remote_directory(self, path: str):
        if not self.client or not self.client.is_connected:
            return

        self.current_remote_path = path
        self.path_display.setText(path)
        self.back_btn.setEnabled(self.history_index > 0)
        self.forward_btn.setEnabled(self.history_index < len(self.history) - 1)

        ok, items, err = self.client.list_directory(path)
        if not ok:
            QMessageBox.warning(self, "Folder Error", f"Cannot open folder: {err}")
            return

        self.current_items = items
        self._render_items(items)

    def _render_items(self, items: List[Dict[str, Any]]):
        self.file_table.blockSignals(True)
        self.file_table.setRowCount(len(items))

        for row, it in enumerate(items):
            is_dir = it["is_dir"]
            name = it["name"]
            icon, type_str = get_file_icon_and_type(name, is_dir)

            # Checkbox
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk_item.setCheckState(Qt.Unchecked)
            self.file_table.setItem(row, 0, chk_item)

            # Name with icon
            name_item = QTableWidgetItem(f"{icon}  {name}")
            name_item.setData(Qt.UserRole, it)
            self.file_table.setItem(row, 1, name_item)

            # Type
            type_item = QTableWidgetItem(type_str)
            type_item.setForeground(Qt.gray)
            self.file_table.setItem(row, 2, type_item)

            # Size
            size_str = "--" if is_dir else format_file_size(it["size"])
            size_item = QTableWidgetItem(size_str)
            self.file_table.setItem(row, 3, size_item)

            # Modified date
            mtime_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(it["mtime"]))
            mtime_item = QTableWidgetItem(mtime_str)
            mtime_item.setForeground(Qt.gray)
            self.file_table.setItem(row, 4, mtime_item)

        self.file_table.blockSignals(False)
        self._update_selection_summary()

    def _apply_search_filter(self, query: str):
        q = query.strip().lower()
        if not q:
            self._render_items(self.current_items)
            return

        filtered = [it for it in self.current_items if q in it["name"].lower()]
        self._render_items(filtered)

    def _on_table_double_clicked(self, row: int, col: int):
        name_item = self.file_table.item(row, 1)
        if not name_item:
            return
        item_data = name_item.data(Qt.UserRole)
        if item_data and item_data.get("is_dir"):
            self._navigate_to(item_data["path"])
        elif item_data:
            # Toggle checkbox on double click of file
            chk = self.file_table.item(row, 0)
            if chk:
                new_state = Qt.Unchecked if chk.checkState() == Qt.Checked else Qt.Checked
                chk.setCheckState(new_state)

    def _on_table_item_changed(self, item):
        if item.column() == 0:
            self._update_selection_summary()

    def _select_all(self):
        self.file_table.blockSignals(True)
        for r in range(self.file_table.rowCount()):
            chk = self.file_table.item(r, 0)
            if chk:
                chk.setCheckState(Qt.Checked)
        self.file_table.blockSignals(False)
        self._update_selection_summary()

    def _deselect_all(self):
        self.file_table.blockSignals(True)
        for r in range(self.file_table.rowCount()):
            chk = self.file_table.item(r, 0)
            if chk:
                chk.setCheckState(Qt.Unchecked)
        self.file_table.blockSignals(False)
        self._update_selection_summary()

    def _update_selection_summary(self):
        selected_count = 0
        total_size = 0
        for r in range(self.file_table.rowCount()):
            chk = self.file_table.item(r, 0)
            if chk and chk.checkState() == Qt.Checked:
                name_item = self.file_table.item(r, 1)
                if name_item:
                    it = name_item.data(Qt.UserRole)
                    if it:
                        selected_count += 1
                        if not it["is_dir"]:
                            total_size += it.get("size", 0)

        size_txt = format_file_size(total_size)
        self.selection_label.setText(f"✓ {selected_count} items selected ({size_txt})")

    def _browse_dest(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Download Folder", self.local_dest_label.text())
        if folder:
            self.local_dest_label.setText(folder)

    def _copy_selected_files(self):
        if not self.client or not self.client.is_connected:
            return

        selected_items = []
        for r in range(self.file_table.rowCount()):
            chk = self.file_table.item(r, 0)
            if chk and chk.checkState() == Qt.Checked:
                name_item = self.file_table.item(r, 1)
                if name_item:
                    it = name_item.data(Qt.UserRole)
                    if it:
                        selected_items.append(it)

        if not selected_items:
            QMessageBox.information(self, "No Files Selected", "Please select at least one file or folder to copy.")
            return

        dest_dir = self.local_dest_label.text().strip()
        if not dest_dir:
            dest_dir = self.cfg.download_dir

        self.progress_card.setVisible(True)
        self.file_progress_bar.setValue(0)
        self.total_progress_bar.setValue(0)
        self.p_title_label.setText(f"Copying {len(selected_items)} item(s) from remote laptop...")

        self.client.pull_files_thread(
            items=selected_items,
            dest_dir=dest_dir,
            on_progress=lambda f_id, rel_p, f_bytes, f_tot, b_tot, all_tot, spd, eta: self.bridge.progress.emit(
                f_id, rel_p, f_bytes, f_tot, b_tot, all_tot, spd, eta
            ),
            on_file_done=lambda name, ok: self.bridge.file_done.emit(name, ok),
            on_finished=lambda success, msg: self.bridge.finished.emit(success, msg)
        )

    def _on_pull_progress(self, f_id, rel_p, f_bytes, f_tot, b_tot, all_tot, spd, eta):
        file_pct = int((f_bytes / f_tot) * 100) if f_tot > 0 else 0
        tot_pct = int((b_tot / all_tot) * 100) if all_tot > 0 else 0
        self.file_progress_bar.setValue(min(100, file_pct))
        self.total_progress_bar.setValue(min(100, tot_pct))
        self.p_file_label.setText(f"Receiving: {rel_p} ({format_file_size(f_bytes)} / {format_file_size(f_tot)})")
        self.speed_badge.setText(format_transfer_speed(spd))
        self.eta_label.setText(f"ETA: {format_time_remaining(eta)}")

    def _on_pull_file_done(self, name: str, success: bool):
        pass

    def _on_pull_finished(self, success: bool, msg: str):
        self.progress_card.setVisible(False)
        if success:
            QMessageBox.information(self, "Transfer Complete", f"All files successfully transferred!\n\nSaved to: {self.local_dest_label.text()}")
        else:
            QMessageBox.warning(self, "Transfer Failed / Cancelled", f"Transfer stopped: {msg}")

    def _cancel_pull(self):
        if self.client:
            self.client.cancel()
            self.progress_card.setVisible(False)

    def _mount_windows_explorer(self):
        ip, port = self._get_target_ip_and_port()
        if not ip:
            QMessageBox.warning(self, "Target Missing", "Select or enter the remote laptop IP first.")
            return

        ok, drive, msg = mount_ethernet_laptop_drive(
            remote_ip=ip,
            port=DEFAULT_WEB_EXPLORER_PORT,
            preferred_letter=DEFAULT_ETHERNET_DRIVE_LETTER,
            drive_label="Ethernet Connected Laptop",
            open_explorer=True
        )
        if ok:
            QMessageBox.information(
                self,
                "Windows File Explorer Mounted",
                f"Successfully opened remote laptop in Windows File Explorer as:\n\n{drive}\\ (Ethernet Connected Laptop)\n\n"
                f"You can now browse and transfer files using native Windows File Explorer!"
            )
        else:
            QMessageBox.warning(self, "Explorer Mount Helper", f"Could not mount in Windows Explorer: {msg}\n\nMake sure LaptopShare is running on the other laptop.")

    def _open_target_web_browser(self):
        ip, port = self._get_target_ip_and_port()
        if not ip:
            QMessageBox.warning(self, "Target Missing", "Select or enter remote laptop IP first.")
            return
        url = f"http://{ip}:{DEFAULT_WEB_EXPLORER_PORT}/"
        webbrowser.open(url)

    def _open_destination_folder(self):
        dest_dir = self.local_dest_label.text().strip() or self.cfg.download_dir
        open_in_windows_explorer(dest_dir)
