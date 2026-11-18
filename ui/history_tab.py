"""
LaptopShare Transfer History Tab
Displays past transfer records, duration, status, and destination paths.
"""

import os
import time
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox
)
from PySide6.QtCore import Qt

from core.history import HistoryManager
from core.file_manager import format_file_size

class HistoryTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(14)

        # Header
        header_row = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Transfer History", self)
        title.setObjectName("titleLabel")
        subtitle = QLabel("Log of past sent and received file transfers", self)
        subtitle.setObjectName("subtitleLabel")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header_row.addLayout(title_box)
        header_row.addStretch()

        clear_btn = QPushButton("🗑️ Clear History", self)
        clear_btn.clicked.connect(self._clear_history)
        header_row.addWidget(clear_btn)

        refresh_btn = QPushButton("🔄 Refresh", self)
        refresh_btn.clicked.connect(self.refresh_records)
        header_row.addWidget(refresh_btn)

        main_layout.addLayout(header_row)

        # Table
        self.table = QTableWidget(self)
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Time", "Direction", "Device", "Files", "Size", "Duration", "Status"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

        main_layout.addWidget(self.table)

        # Action row
        action_row = QHBoxLayout()
        action_row.addStretch()
        open_folder_btn = QPushButton("📂 Open Transfer Folder", self)
        open_folder_btn.clicked.connect(self._open_selected_folder)
        action_row.addWidget(open_folder_btn)
        main_layout.addLayout(action_row)

        self.refresh_records()

    def refresh_records(self):
        records = HistoryManager().get_all()
        self.table.setRowCount(len(records))

        for row, r in enumerate(records):
            # Time
            time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r.timestamp))
            self.table.setItem(row, 0, QTableWidgetItem(time_str))

            # Direction
            dir_text = "⬆️ Sent" if r.direction == "sent" else "⬇️ Received"
            dir_item = QTableWidgetItem(dir_text)
            self.table.setItem(row, 1, dir_item)

            # Device
            peer_text = f"{r.peer_name} ({r.peer_ip})"
            self.table.setItem(row, 2, QTableWidgetItem(peer_text))

            # Files
            self.table.setItem(row, 3, QTableWidgetItem(str(r.files_count)))

            # Size
            size_str = format_file_size(r.total_bytes)
            self.table.setItem(row, 4, QTableWidgetItem(size_str))

            # Duration
            dur_str = f"{r.duration_sec:.1f}s" if r.duration_sec < 60 else f"{r.duration_sec/60:.1f}m"
            self.table.setItem(row, 5, QTableWidgetItem(dur_str))

            # Status
            status_item = QTableWidgetItem(r.status)
            if r.status == "Completed":
                status_item.setForeground(Qt.green)
            else:
                status_item.setForeground(Qt.red)
            self.table.setItem(row, 6, status_item)

    def _clear_history(self):
        reply = QMessageBox.question(
            self, "Clear History", "Are you sure you want to clear transfer history?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            HistoryManager().clear()
            self.refresh_records()

    def _open_selected_folder(self):
        row = self.table.currentRow()
        records = HistoryManager().get_all()
        if 0 <= row < len(records):
            record = records[row]
            dest = record.destination_dir
            if dest and Path(dest).exists():
                os.startfile(dest)
                return
        # Default fallback
        from core.config import ConfigManager
        dl = ConfigManager().get().download_dir
        if Path(dl).exists():
            os.startfile(dl)
