"""
LaptopShare Remote Browse Tab
Enables connecting to another laptop with permission, browsing remote directories,
and choosing specific files/folders to copy to this laptop.
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
from PySide6.QtCore import Qt, Signal, QObject

from core.config import ConfigManager
from core.remote_browser_client import RemoteBrowserClient
from core.discovery import PeerDevice
from core.file_manager import format_file_size, format_transfer_speed, format_time_remaining
from core.web_explorer_server import (
    mount_remote_in_windows_explorer,
    DEFAULT_WEB_EXPLORER_PORT,
    open_in_windows_explorer
)

class PullSignalBridge(QObject):
    progress = Signal(int, str, int, int, int, int, float, float)
    file_done = Signal(str, bool)
    finished = Signal(bool, str)

class BrowseTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg = ConfigManager().get()
        self.client: Optional[RemoteBrowserClient] = None
        self.current_remote_path = ""
        self.current_items: List[Dict[str, Any]] = []

        self.bridge = PullSignalBridge()
        self.bridge.progress.connect(self._on_pull_progress)
        self.bridge.file_done.connect(self._on_pull_file_done)
        self.bridge.finished.connect(self._on_pull_finished)

        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(12)

        # Header
        header_row = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Browse & Copy from Another Laptop", self)
        title.setObjectName("titleLabel")
        subtitle = QLabel("Request permission to explore another laptop's files and choose what to copy here", self)
        subtitle.setObjectName("subtitleLabel")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header_row.addLayout(title_box)
        header_row.addStretch()

        self.conn_status_badge = QLabel("○ Disconnected", self)
        self.conn_status_badge.setObjectName("badge")
        self.conn_status_badge.setStyleSheet("background-color: #3f424b; color: #e2e8f0; padding: 5px 10px;")
        header_row.addWidget(self.conn_status_badge)
        main_layout.addLayout(header_row)

        # Connection Card
        conn_card = QFrame(self)
        conn_card.setObjectName("card")
        conn_layout = QHBoxLayout(conn_card)
        conn_layout.setContentsMargins(14, 12, 14, 12)
        conn_layout.setSpacing(10)

        self.target_mode_combo = QComboBox(self)
        self.target_mode_combo.addItems(["Nearby Discovered Device", "Manual IP & PIN"])
        self.target_mode_combo.currentIndexChanged.connect(self._on_target_mode_changed)
        self.target_mode_combo.setFixedWidth(210)
        conn_layout.addWidget(self.target_mode_combo)

        self.peer_combo = QComboBox(self)
        self.peer_combo.setPlaceholderText("Select remote laptop...")
        conn_layout.addWidget(self.peer_combo)

        self.manual_ip = QLineEdit(self)
        self.manual_ip.setPlaceholderText("Remote IP (e.g. 192.168.1.50)")
        self.manual_ip.setVisible(False)
        conn_layout.addWidget(self.manual_ip)

        self.pin_input = QLineEdit(self)
        self.pin_input.setPlaceholderText("6-Digit PIN")
        self.pin_input.setMaxLength(6)
        self.pin_input.setFixedWidth(100)
        conn_layout.addWidget(self.pin_input)

        self.connect_btn = QPushButton("🔑 Connect & Request Access", self)
        self.connect_btn.setObjectName("primaryButton")
        self.connect_btn.clicked.connect(self._connect_and_request_access)
        conn_layout.addWidget(self.connect_btn)

        self.disconnect_btn = QPushButton("Disconnect", self)
        self.disconnect_btn.setObjectName("dangerButton")
        self.disconnect_btn.setVisible(False)
        self.disconnect_btn.clicked.connect(self._disconnect)
        conn_layout.addWidget(self.disconnect_btn)

        main_layout.addWidget(conn_card)

        # Direct Windows Explorer & Browser Quick Actions Card
        exp_bar = QFrame(self)
        exp_bar.setObjectName("card")
        exp_bar.setStyleSheet("QFrame#card { background-color: #172033; border: 1px solid #1e293b; }")
        exp_bar_layout = QHBoxLayout(exp_bar)
        exp_bar_layout.setContentsMargins(14, 10, 14, 10)
        exp_bar_layout.setSpacing(12)

        exp_icon = QLabel("💡", self)
        exp_icon.setStyleSheet("font-size: 18px;")
        exp_bar_layout.addWidget(exp_icon)

        exp_tip = QLabel("Prefer native Windows Explorer? Mount the other laptop as a network drive or browse in browser:", self)
        exp_tip.setObjectName("subtitleLabel")
        exp_bar_layout.addWidget(exp_tip, stretch=1)

        self.mount_explorer_btn = QPushButton("📂 Mount in Windows Explorer (Drive Z:)", self)
        self.mount_explorer_btn.setStyleSheet("background-color: #0284c7; color: white; font-weight: 600; padding: 6px 12px; border-radius: 6px;")
        self.mount_explorer_btn.clicked.connect(self._mount_windows_explorer)
        exp_bar_layout.addWidget(self.mount_explorer_btn)

        self.browser_open_btn = QPushButton("🌐 Open in Web Browser", self)
        self.browser_open_btn.clicked.connect(self._open_target_web_browser)
        exp_bar_layout.addWidget(self.browser_open_btn)

        self.open_dest_btn = QPushButton("📁 Open Destination Folder", self)
        self.open_dest_btn.clicked.connect(self._open_destination_folder)
        exp_bar_layout.addWidget(self.open_dest_btn)

        main_layout.addWidget(exp_bar)

        # Remote File Explorer Card
        self.explorer_card = QFrame(self)
        self.explorer_card.setObjectName("card")
        exp_layout = QVBoxLayout(self.explorer_card)
        exp_layout.setContentsMargins(14, 14, 14, 14)
        exp_layout.setSpacing(10)

        # Explorer Toolbar (Roots selector, breadcrumbs, up button)
        toolbar_row = QHBoxLayout()

        roots_label = QLabel("Remote Locations:", self)
        roots_label.setObjectName("sectionHeader")
        toolbar_row.addWidget(roots_label)

        self.roots_combo = QComboBox(self)
        self.roots_combo.setFixedWidth(200)
        self.roots_combo.currentIndexChanged.connect(self._on_root_selected)
        toolbar_row.addWidget(self.roots_combo)

        self.up_btn = QPushButton("⬆️ Up", self)
        self.up_btn.setFixedWidth(70)
        self.up_btn.clicked.connect(self._navigate_up)
        toolbar_row.addWidget(self.up_btn)

        self.refresh_folder_btn = QPushButton("🔄", self)
        self.refresh_folder_btn.setFixedWidth(40)
        self.refresh_folder_btn.clicked.connect(self._refresh_current_folder)
        toolbar_row.addWidget(self.refresh_folder_btn)

        self.path_display = QLineEdit(self)
        self.path_display.setReadOnly(True)
        self.path_display.setPlaceholderText("Remote path...")
        toolbar_row.addWidget(self.path_display)

        exp_layout.addLayout(toolbar_row)

        # File Table
        self.file_table = QTableWidget(self)
        self.file_table.setColumnCount(4)
        self.file_table.setHorizontalHeaderLabels(["", "Name", "Size", "Date Modified"])
        self.file_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.file_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.file_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.file_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.file_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.file_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.file_table.cellDoubleClicked.connect(self._on_table_double_clicked)
        self.file_table.itemChanged.connect(self._on_table_item_changed)
        exp_layout.addWidget(self.file_table)

        # Bottom Selection and Copy Bar
        bottom_row = QHBoxLayout()
        select_all_btn = QPushButton("Select All", self)
        select_all_btn.clicked.connect(self._select_all)
        deselect_all_btn = QPushButton("Deselect All", self)
        deselect_all_btn.clicked.connect(self._deselect_all)
        bottom_row.addWidget(select_all_btn)
        bottom_row.addWidget(deselect_all_btn)

        self.selection_label = QLabel("0 items selected (0 B)", self)
        self.selection_label.setObjectName("badge")
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

        self.copy_btn = QPushButton("📥 Copy Selected to This Laptop", self)
        self.copy_btn.setObjectName("successButton")
        self.copy_btn.setFixedHeight(38)
        self.copy_btn.clicked.connect(self._copy_selected_files)
        bottom_row.addWidget(self.copy_btn)

        exp_layout.addLayout(bottom_row)
        main_layout.addWidget(self.explorer_card)

        # Live Download Progress Card
        self.progress_card = QFrame(self)
        self.progress_card.setObjectName("card")
        self.progress_card.setVisible(False)
        p_layout = QVBoxLayout(self.progress_card)
        p_layout.setContentsMargins(14, 14, 14, 14)
        p_layout.setSpacing(8)

        p_header = QHBoxLayout()
        self.p_title_label = QLabel("Downloading Files from Remote Laptop...", self)
        self.p_title_label.setObjectName("sectionHeader")
        self.speed_badge = QLabel("0.0 MB/s", self)
        self.speed_badge.setObjectName("badge")
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

        # Disable explorer until connected
        self.explorer_card.setEnabled(False)

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
            QMessageBox.warning(self, "Select Laptop", "Please select a nearby laptop or enter an IP.")
            return

        pin = self.pin_input.text().strip()
        self.conn_status_badge.setText("⏳ Waiting for permission on other laptop...")
        self.conn_status_badge.setStyleSheet("background-color: #0369a1; color: #e0f2fe; padding: 5px 10px;")
        self.connect_btn.setEnabled(False)

        # Attempt connection in background or direct
        self.client = RemoteBrowserClient(target_ip=ip, target_port=port, pin=pin)
        import threading
        def connect_worker():
            success, msg = self.client.connect()
            # Post back to Qt
            from PySide6.QtCore import QMetaObject, Q_ARG
            QMetaObject.invokeMethod(self, "_on_connect_result", Qt.QueuedConnection, Q_ARG(bool, success), Q_ARG(str, msg))

        t = threading.Thread(target=connect_worker, daemon=True)
        t.start()

    from PySide6.QtCore import Slot

    @Slot(bool, str)
    def _on_connect_result(self, success: bool, msg: str):
        self.connect_btn.setEnabled(True)
        if success:
            self.conn_status_badge.setText(f"● Connected to {self.client.remote_device_name}")
            self.conn_status_badge.setStyleSheet("background-color: #15803d; color: #dcfce7; padding: 5px 10px;")
            self.connect_btn.setVisible(False)
            self.disconnect_btn.setVisible(True)
            self.explorer_card.setEnabled(True)

            # Populate roots
            self.roots_combo.clear()
            for r in self.client.roots:
                self.roots_combo.addItem(r["name"], userData=r["path"])

            # Navigate to first root
            if self.client.roots:
                self._load_remote_directory(self.client.roots[0]["path"])
        else:
            self.conn_status_badge.setText("○ Disconnected")
            self.conn_status_badge.setStyleSheet("background-color: #3f424b; color: #e2e8f0; padding: 5px 10px;")
            QMessageBox.critical(self, "Permission Denied / Connection Failed", msg)

    def _disconnect(self):
        if self.client:
            self.client.disconnect()
            self.client = None
        self.conn_status_badge.setText("○ Disconnected")
        self.conn_status_badge.setStyleSheet("background-color: #3f424b; color: #e2e8f0; padding: 5px 10px;")
        self.connect_btn.setVisible(True)
        self.disconnect_btn.setVisible(False)
        self.explorer_card.setEnabled(False)
        self.file_table.setRowCount(0)
        self.path_display.clear()

    def _on_root_selected(self, idx: int):
        path = self.roots_combo.currentData()
        if path:
            self._load_remote_directory(path)

    def _load_remote_directory(self, path: str):
        if not self.client or not self.client.is_connected:
            return

        self.current_remote_path = path
        self.path_display.setText(path)

        ok, items, err = self.client.list_directory(path)
        if not ok:
            QMessageBox.warning(self, "Folder Error", f"Cannot open folder: {err}")
            return

        self.current_items = items
        self.file_table.blockSignals(True)
        self.file_table.setRowCount(len(items))

        for row, it in enumerate(items):
            # Checkbox
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk_item.setCheckState(Qt.Unchecked)
            self.file_table.setItem(row, 0, chk_item)

            # Name with icon
            icon = "📁 " if it["is_dir"] else "📄 "
            name_item = QTableWidgetItem(icon + it["name"])
            name_item.setData(Qt.UserRole, it)
            self.file_table.setItem(row, 1, name_item)

            # Size
            size_str = "--" if it["is_dir"] else format_file_size(it["size"])
            self.file_table.setItem(row, 2, QTableWidgetItem(size_str))

            # Modified date
            mtime_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(it["mtime"]))
            self.file_table.setItem(row, 3, QTableWidgetItem(mtime_str))

        self.file_table.blockSignals(False)
        self._update_selection_summary()

    def _on_table_double_clicked(self, row: int, col: int):
        name_item = self.file_table.item(row, 1)
        if not name_item:
            return
        item_data = name_item.data(Qt.UserRole)
        if item_data and item_data.get("is_dir"):
            self._load_remote_directory(item_data["path"])

    def _navigate_up(self):
        if not self.current_remote_path:
            return
        parent_p = str(Path(self.current_remote_path).parent)
        if parent_p != self.current_remote_path:
            self._load_remote_directory(parent_p)

    def _refresh_current_folder(self):
        if self.current_remote_path:
            self._load_remote_directory(self.current_remote_path)

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

    def _get_selected_items(self) -> List[Dict[str, Any]]:
        selected = []
        for r in range(self.file_table.rowCount()):
            chk = self.file_table.item(r, 0)
            if chk and chk.checkState() == Qt.Checked:
                name_item = self.file_table.item(r, 1)
                if name_item:
                    it = name_item.data(Qt.UserRole)
                    if it:
                        selected.append(it)
        return selected

    def _update_selection_summary(self):
        items = self._get_selected_items()
        count = len(items)
        bytes_sum = sum(it["size"] for it in items)
        self.selection_label.setText(f"{count} item{'s' if count != 1 else ''} selected ({format_file_size(bytes_sum)})")

    def _browse_dest(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Download Folder", self.cfg.download_dir)
        if folder:
            self.cfg.download_dir = folder
            ConfigManager().save()
            self.local_dest_label.setText(folder)

    def _copy_selected_files(self):
        items = self._get_selected_items()
        if not items:
            QMessageBox.warning(self, "No Files Selected", "Check the boxes next to files or folders you want to copy.")
            return

        if not self.client or not self.client.is_connected:
            QMessageBox.warning(self, "Not Connected", "You are not connected to the remote laptop.")
            return

        paths = [it["path"] for it in items]
        dest = self.cfg.download_dir

        self.progress_card.setVisible(True)
        self.copy_btn.setEnabled(False)
        self.file_progress_bar.setValue(0)
        self.total_progress_bar.setValue(0)
        self.p_title_label.setText(f"Copying {len(paths)} item(s) from {self.client.remote_device_name}...")

        # Start pull thread
        self.client.pull_files_thread(
            remote_paths=paths,
            destination_dir=dest,
            on_progress=self.bridge.progress.emit,
            on_file_completed=self.bridge.file_done.emit,
            on_finished=self.bridge.finished.emit
        )

    def _cancel_pull(self):
        if self.client:
            self.client.cancel_pull()
            self.p_title_label.setText("Cancelling download...")

    # Bridge slots
    def _on_pull_progress(self, file_id, rel, f_done, f_total, t_done, t_all, speed, eta):
        file_pct = int((f_done / f_total) * 100) if f_total > 0 else 0
        total_pct = int((t_done / t_all) * 100) if t_all > 0 else 0

        self.p_file_label.setText(f"File: {rel} ({format_file_size(f_done)} / {format_file_size(f_total)})")
        self.file_progress_bar.setValue(file_pct)
        self.total_progress_bar.setValue(total_pct)
        self.speed_badge.setText(format_transfer_speed(speed))
        self.eta_label.setText(f"ETA: {format_time_remaining(eta)}")

    def _on_pull_file_done(self, rel, verified):
        status = "✅ Verified SHA-256" if verified else "⚠️ Checksum mismatch"
        self.p_file_label.setText(f"{status}: {rel}")

    def _on_pull_finished(self, success, msg):
        self.copy_btn.setEnabled(True)
        if success:
            self.p_title_label.setText("🎉 All Selected Files Copied & Verified!")
            self.file_progress_bar.setValue(100)
            self.total_progress_bar.setValue(100)
            reply = QMessageBox.information(
                self,
                "Transfer Complete",
                f"Successfully copied files to:\n{self.cfg.download_dir}\n\nDo you want to open the destination folder?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes and Path(self.cfg.download_dir).exists():
                os.startfile(self.cfg.download_dir)
        else:
            self.p_title_label.setText(f"Transfer Ended: {msg}")
            QMessageBox.critical(self, "Download Failed", msg)

    def _mount_windows_explorer(self):
        ip, _ = self._get_target_ip_and_port()
        if not ip:
            QMessageBox.warning(self, "Select Laptop", "Please select a nearby laptop or enter an IP address first.")
            return

        ok, drive_or_unc, msg = mount_remote_in_windows_explorer(ip, DEFAULT_WEB_EXPLORER_PORT)
        if ok:
            QMessageBox.information(
                self,
                "Windows Explorer Mounted",
                f"Successfully opened {ip} in Windows File Explorer!\n\nLocation: {drive_or_unc}\n\nYou can now copy, drag and drop files directly between laptops using Windows Explorer."
            )
        else:
            QMessageBox.information(
                self,
                "Explorer Helper",
                f"{msg}\n\nTo open manually in Windows Explorer: Press Win + R and enter:\n\\\\{ip}@{DEFAULT_WEB_EXPLORER_PORT}\\DavWWWRoot"
            )

    def _open_target_web_browser(self):
        ip, _ = self._get_target_ip_and_port()
        if not ip:
            QMessageBox.warning(self, "Select Laptop", "Please select a nearby laptop or enter an IP address first.")
            return
        url = f"http://{ip}:{DEFAULT_WEB_EXPLORER_PORT}/"
        webbrowser.open(url)

    def _open_destination_folder(self):
        dest = self.cfg.download_dir
        open_in_windows_explorer(dest)
