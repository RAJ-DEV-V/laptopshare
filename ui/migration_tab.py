"""
LaptopShare PC Migration Wizard Tab
Allows seamless switching between an old laptop and a new PC by scanning
and migrating user categories (Desktop, Documents, Photos, Downloads, Browser data, Dev settings).
"""

import os
from pathlib import Path
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QFrame, QMessageBox, QFileDialog, QScrollArea,
    QCheckBox, QRadioButton, QButtonGroup, QGridLayout, QComboBox, QLineEdit
)
from PySide6.QtCore import Qt, Signal, QObject, Slot

from core.config import ConfigManager
from core.migration_client import MigrationClient
from core.discovery import PeerDevice
from core.file_manager import format_file_size, format_transfer_speed, format_time_remaining

class MigrationSignalBridge(QObject):
    progress = Signal(int, str, int, int, int, int, float, float)
    file_done = Signal(str, bool)
    finished = Signal(bool, str)

class CategoryCard(QFrame):
    toggled = Signal()

    def __init__(self, cat_data: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.cat_data = cat_data
        self.setObjectName("card")
        self.setFixedHeight(85)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        self.checkbox = QCheckBox(self)
        self.checkbox.setChecked(cat_data.get("selected", True))
        self.checkbox.toggled.connect(self._on_toggled)
        layout.addWidget(self.checkbox)

        icon_label = QLabel(cat_data.get("icon", "📁"), self)
        icon_label.setStyleSheet("font-size: 26px;")
        layout.addWidget(icon_label)

        info_box = QVBoxLayout()
        info_box.setSpacing(2)
        name_label = QLabel(cat_data.get("name", ""), self)
        name_label.setObjectName("sectionHeader")
        desc_label = QLabel(cat_data.get("description", ""), self)
        desc_label.setObjectName("subtitleLabel")
        info_box.addWidget(name_label)
        info_box.addWidget(desc_label)
        layout.addLayout(info_box)

        layout.addStretch()

        size_b = cat_data.get("total_bytes", 0)
        count = cat_data.get("file_count", 0)
        size_str = format_file_size(size_b)
        count_str = f"{count} files" if count > 0 else "Ready"
        self.badge = QLabel(f"{count_str} • {size_str}", self)
        self.badge.setObjectName("badge")
        layout.addWidget(self.badge)

    def _on_toggled(self, checked: bool):
        self.cat_data["selected"] = checked
        self.toggled.emit()

    def is_selected(self) -> bool:
        return self.checkbox.isChecked()

    def set_selected(self, val: bool):
        self.checkbox.setChecked(val)

class MigrationTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg = ConfigManager().get()
        self.client: Optional[MigrationClient] = None
        self.category_cards: List[CategoryCard] = []

        self.bridge = MigrationSignalBridge()
        self.bridge.progress.connect(self._on_migration_progress)
        self.bridge.file_done.connect(self._on_migration_file_done)
        self.bridge.finished.connect(self._on_migration_finished)

        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Header
        header_row = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Seamless PC Migration Wizard 🔄", content)
        title.setObjectName("titleLabel")
        subtitle = QLabel("Switch to your new PC easily: scan your old laptop and migrate your desktop, documents, photos, and browser data in 1 click", content)
        subtitle.setObjectName("subtitleLabel")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header_row.addLayout(title_box)
        header_row.addStretch()

        self.status_pill = QLabel("○ Not Connected", content)
        self.status_pill.setObjectName("badge")
        self.status_pill.setStyleSheet("background-color: #3f424b; color: #e2e8f0; padding: 5px 12px;")
        header_row.addWidget(self.status_pill)
        layout.addLayout(header_row)

        # Connection Card
        conn_card = QFrame(content)
        conn_card.setObjectName("card")
        conn_layout = QHBoxLayout(conn_card)
        conn_layout.setContentsMargins(14, 12, 14, 12)
        conn_layout.setSpacing(10)

        self.target_mode_combo = QComboBox(content)
        self.target_mode_combo.addItems(["Nearby Discovered Device", "Manual IP & PIN"])
        self.target_mode_combo.currentIndexChanged.connect(self._on_target_mode_changed)
        self.target_mode_combo.setFixedWidth(200)
        conn_layout.addWidget(self.target_mode_combo)

        self.peer_combo = QComboBox(content)
        self.peer_combo.setPlaceholderText("Select your old laptop on Wi-Fi...")
        conn_layout.addWidget(self.peer_combo)

        self.manual_ip = QLineEdit(content)
        self.manual_ip.setPlaceholderText("Old Laptop IP (e.g. 192.168.1.55)")
        self.manual_ip.setVisible(False)
        conn_layout.addWidget(self.manual_ip)

        self.pin_input = QLineEdit(content)
        self.pin_input.setPlaceholderText("6-Digit PIN")
        self.pin_input.setMaxLength(6)
        self.pin_input.setFixedWidth(100)
        conn_layout.addWidget(self.pin_input)

        self.scan_btn = QPushButton("🔍 Connect & Scan Old PC", content)
        self.scan_btn.setObjectName("primaryButton")
        self.scan_btn.clicked.connect(self._start_scan)
        conn_layout.addWidget(self.scan_btn)

        layout.addWidget(conn_card)

        # Category Checklist Section
        self.cat_frame = QFrame(content)
        self.cat_frame.setObjectName("card")
        self.cat_layout = QVBoxLayout(self.cat_frame)
        self.cat_layout.setContentsMargins(16, 16, 16, 16)
        self.cat_layout.setSpacing(10)

        cat_header_row = QHBoxLayout()
        cat_title = QLabel("What Would You Like to Migrate?", self.cat_frame)
        cat_title.setObjectName("sectionHeader")
        cat_header_row.addWidget(cat_title)
        cat_header_row.addStretch()

        sel_all_btn = QPushButton("Select All", self.cat_frame)
        sel_all_btn.clicked.connect(self._select_all_cats)
        sel_rec_btn = QPushButton("Recommended Only", self.cat_frame)
        sel_rec_btn.clicked.connect(self._select_recommended_cats)
        cat_header_row.addWidget(sel_all_btn)
        cat_header_row.addWidget(sel_rec_btn)

        self.total_summary_badge = QLabel("Total: 0 B (0 files)", self.cat_frame)
        self.total_summary_badge.setObjectName("badge")
        cat_header_row.addWidget(self.total_summary_badge)
        self.cat_layout.addLayout(cat_header_row)

        # Card container
        self.cards_container = QVBoxLayout()
        self.cards_container.setSpacing(8)
        self.cat_layout.addLayout(self.cards_container)

        self.empty_scan_label = QLabel("Connect to your old laptop above to scan and choose categories for migration.", self.cat_frame)
        self.empty_scan_label.setObjectName("subtitleLabel")
        self.empty_scan_label.setAlignment(Qt.AlignCenter)
        self.empty_scan_label.setStyleSheet("padding: 30px;")
        self.cards_container.addWidget(self.empty_scan_label)

        layout.addWidget(self.cat_frame)

        # Placement Options Card
        self.dest_card = QFrame(content)
        self.dest_card.setObjectName("card")
        d_layout = QVBoxLayout(self.dest_card)
        d_layout.setContentsMargins(16, 14, 16, 14)
        d_layout.setSpacing(8)

        d_title = QLabel("Destination Placement on This New PC", self.dest_card)
        d_title.setObjectName("sectionHeader")
        d_layout.addWidget(d_title)

        self.radio_organized = QRadioButton("Organized Migration Folder (Recommended: Downloads\\LaptopShare\\Migrated_Old_PC)", self.dest_card)
        self.radio_organized.setChecked(True)
        self.radio_profile = QRadioButton("Direct User Profile (Merge directly into Desktop, Documents, Pictures)", self.dest_card)

        d_layout.addWidget(self.radio_organized)
        d_layout.addWidget(self.radio_profile)

        dest_browse_row = QHBoxLayout()
        dest_lbl = QLabel("Base Folder:", self.dest_card)
        default_mig_dir = str(Path(self.cfg.download_dir) / "Migrated_Old_PC")
        self.dest_path_input = QLineEdit(default_mig_dir, self.dest_card)
        browse_dest_btn = QPushButton("Browse...", self.dest_card)
        browse_dest_btn.clicked.connect(self._browse_dest)
        dest_browse_row.addWidget(dest_lbl)
        dest_browse_row.addWidget(self.dest_path_input)
        dest_browse_row.addWidget(browse_dest_btn)
        d_layout.addLayout(dest_browse_row)

        layout.addWidget(self.dest_card)

        # Start Migration Action Bar
        action_row = QHBoxLayout()
        action_row.addStretch()
        self.start_migrate_btn = QPushButton("🚀 Start Seamless PC Migration", content)
        self.start_migrate_btn.setObjectName("primaryButton")
        self.start_migrate_btn.setFixedHeight(45)
        self.start_migrate_btn.setFixedWidth(260)
        self.start_migrate_btn.setEnabled(False)
        self.start_migrate_btn.clicked.connect(self._start_migration)
        action_row.addWidget(self.start_migrate_btn)
        layout.addLayout(action_row)

        # Live Progress Card
        self.prog_card = QFrame(content)
        self.prog_card.setObjectName("card")
        self.prog_card.setVisible(False)
        p_layout = QVBoxLayout(self.prog_card)
        p_layout.setContentsMargins(16, 14, 16, 14)
        p_layout.setSpacing(8)

        p_top = QHBoxLayout()
        self.m_status_title = QLabel("Migrating Profile from Old Laptop...", self.prog_card)
        self.m_status_title.setObjectName("sectionHeader")
        self.speed_badge = QLabel("0.0 MB/s", self.prog_card)
        self.speed_badge.setObjectName("badge")
        self.eta_label = QLabel("ETA: --:--", self.prog_card)
        self.eta_label.setObjectName("subtitleLabel")
        p_top.addWidget(self.m_status_title)
        p_top.addStretch()
        p_top.addWidget(self.speed_badge)
        p_top.addWidget(self.eta_label)
        p_layout.addLayout(p_top)

        self.m_file_label = QLabel("Initializing migration stream...", self.prog_card)
        self.m_file_label.setObjectName("subtitleLabel")
        p_layout.addWidget(self.m_file_label)

        self.file_bar = QProgressBar(self.prog_card)
        self.file_bar.setValue(0)
        p_layout.addWidget(self.file_bar)

        self.total_bar = QProgressBar(self.prog_card)
        self.total_bar.setValue(0)
        p_layout.addWidget(self.total_bar)

        cancel_row = QHBoxLayout()
        cancel_row.addStretch()
        cancel_btn = QPushButton("Cancel Migration", self.prog_card)
        cancel_btn.setObjectName("dangerButton")
        cancel_btn.clicked.connect(self._cancel_migration)
        cancel_row.addWidget(cancel_btn)
        p_layout.addLayout(cancel_row)

        layout.addWidget(self.prog_card)

        scroll.setWidget(content)
        main_layout.addWidget(scroll)

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

    def _browse_dest(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Migration Folder", self.dest_path_input.text())
        if folder:
            self.dest_path_input.setText(folder)

    def _start_scan(self):
        ip, port = self._get_target_ip_and_port()
        if not ip:
            QMessageBox.warning(self, "Old Laptop Required", "Please select your old laptop from nearby devices or enter its IP.")
            return

        pin = self.pin_input.text().strip()
        self.status_pill.setText("⏳ Waiting for approval on old laptop...")
        self.status_pill.setStyleSheet("background-color: #0369a1; color: #e0f2fe; padding: 5px 12px;")
        self.scan_btn.setEnabled(False)

        self.client = MigrationClient(target_ip=ip, target_port=port, pin=pin)

        import threading
        def worker():
            ok, msg, cats = self.client.connect_and_scan()
            from PySide6.QtCore import QMetaObject, Q_ARG
            QMetaObject.invokeMethod(
                self,
                "_on_scan_result",
                Qt.QueuedConnection,
                Q_ARG(bool, ok),
                Q_ARG(str, msg),
                Q_ARG(list, cats)
            )

        threading.Thread(target=worker, daemon=True).start()

    @Slot(bool, str, list)
    def _on_scan_result(self, ok: bool, msg: str, cats: list):
        self.scan_btn.setEnabled(True)
        if not ok:
            self.status_pill.setText("○ Not Connected")
            self.status_pill.setStyleSheet("background-color: #3f424b; color: #e2e8f0; padding: 5px 12px;")
            QMessageBox.critical(self, "Migration Scan Failed", msg)
            return

        self.status_pill.setText(f"● Connected to {self.client.remote_device_name}")
        self.status_pill.setStyleSheet("background-color: #15803d; color: #dcfce7; padding: 5px 12px;")

        # Populate category cards
        while self.cards_container.count():
            item = self.cards_container.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        self.category_cards.clear()

        for c_data in cats:
            if c_data.get("available", False):
                card = CategoryCard(c_data, parent=self.cat_frame)
                card.toggled.connect(self._update_total_summary)
                self.category_cards.append(card)
                self.cards_container.addWidget(card)

        if not self.category_cards:
            lbl = QLabel("No standard user folders found on old laptop.", self.cat_frame)
            lbl.setObjectName("subtitleLabel")
            self.cards_container.addWidget(lbl)
            self.start_migrate_btn.setEnabled(False)
        else:
            self.start_migrate_btn.setEnabled(True)
            self._update_total_summary()

    def _update_total_summary(self):
        total_b = 0
        total_files = 0
        for card in self.category_cards:
            if card.is_selected():
                total_b += card.cat_data.get("total_bytes", 0)
                total_files += card.cat_data.get("file_count", 0)

        self.total_summary_badge.setText(f"Total to Migrate: {format_file_size(total_b)} ({total_files} files)")

    def _select_all_cats(self):
        for card in self.category_cards:
            card.set_selected(True)
        self._update_total_summary()

    def _select_recommended_cats(self):
        recommended_ids = {"desktop", "documents", "pictures", "chrome", "edge", "vscode"}
        for card in self.category_cards:
            cid = card.cat_data.get("id")
            card.set_selected(cid in recommended_ids)
        self._update_total_summary()

    def _start_migration(self):
        selected_ids = [card.cat_data["id"] for card in self.category_cards if card.is_selected()]
        if not selected_ids:
            QMessageBox.warning(self, "No Categories", "Please select at least one category to migrate.")
            return

        if not self.client or not self.client.is_connected:
            QMessageBox.warning(self, "Not Connected", "You are not connected to the old laptop.")
            return

        # Determine target folder
        if self.radio_profile.isChecked():
            dest_dir = str(Path.home())
        else:
            dest_dir = self.dest_path_input.text().strip() or str(Path(self.cfg.download_dir) / "Migrated_Old_PC")

        self.prog_card.setVisible(True)
        self.start_migrate_btn.setEnabled(False)
        self.file_bar.setValue(0)
        self.total_bar.setValue(0)
        self.m_status_title.setText(f"Migrating {len(selected_ids)} categories from {self.client.remote_device_name}...")

        self.client.start_migration_thread(
            selected_category_ids=selected_ids,
            destination_dir=dest_dir,
            on_progress=self.bridge.progress.emit,
            on_file_completed=self.bridge.file_done.emit,
            on_finished=self.bridge.finished.emit
        )

    def _cancel_migration(self):
        if self.client:
            self.client.cancel_migration()
            self.m_status_title.setText("Cancelling migration...")

    # Bridge slots
    def _on_migration_progress(self, file_id, rel, f_done, f_total, t_done, t_all, speed, eta):
        file_pct = int((f_done / f_total) * 100) if f_total > 0 else 0
        total_pct = int((t_done / t_all) * 100) if t_all > 0 else 0

        self.m_file_label.setText(f"Migrating: {rel} ({format_file_size(f_done)} / {format_file_size(f_total)})")
        self.file_bar.setValue(file_pct)
        self.total_bar.setValue(total_pct)
        self.speed_badge.setText(format_transfer_speed(speed))
        self.eta_label.setText(f"ETA: {format_time_remaining(eta)}")

    def _on_migration_file_done(self, rel, verified):
        status = "✅ Verified SHA-256" if verified else "⚠️ Checksum mismatch"
        self.m_file_label.setText(f"{status}: {rel}")

    def _on_migration_finished(self, success, msg):
        self.start_migrate_btn.setEnabled(True)
        if success:
            self.m_status_title.setText("🎉 PC Migration Complete!")
            self.file_bar.setValue(100)
            self.total_bar.setValue(100)

            dest_dir = str(Path.home()) if self.radio_profile.isChecked() else self.dest_path_input.text()
            reply = QMessageBox.information(
                self,
                "Migration Success",
                f"Your old laptop files have been migrated successfully to:\n{dest_dir}\n\nWould you like to open the migrated folder?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes and Path(dest_dir).exists():
                os.startfile(dest_dir)
        else:
            self.m_status_title.setText(f"Migration Stopped: {msg}")
            QMessageBox.critical(self, "Migration Interrupted", msg)
