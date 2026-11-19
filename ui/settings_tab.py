"""
LaptopShare Settings & Diagnostics Tab
Configures device name, download path, theme, and provides comprehensive
network diagnostics and Windows Defender Firewall troubleshooting tools.
"""

from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QSpinBox, QComboBox, QFrame, QFileDialog,
    QMessageBox, QTextEdit, QScrollArea, QApplication, QCheckBox
)
from PySide6.QtCore import Qt, Signal

from core.config import ConfigManager
from core.network_utils import (
    get_local_ip_addresses,
    is_port_available,
    test_lan_connection,
    get_firewall_troubleshooting_info,
    get_wifi_diagnostics,
    open_mobile_hotspot_settings
)

class SettingsTab(QWidget):
    theme_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg_mgr = ConfigManager()
        self.cfg = self.cfg_mgr.get()
        self._init_ui()

    def _init_ui(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Header
        title = QLabel("Settings & Network Diagnostics", content)
        title.setObjectName("titleLabel")
        subtitle = QLabel("Configure application behavior and troubleshoot LAN connection issues", content)
        subtitle.setObjectName("subtitleLabel")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        # General Settings Card
        gen_card = QFrame(content)
        gen_card.setObjectName("card")
        gen_layout = QVBoxLayout(gen_card)
        gen_layout.setContentsMargins(16, 16, 16, 16)
        gen_layout.setSpacing(12)

        gen_title = QLabel("Device & Preferences", gen_card)
        gen_title.setObjectName("sectionHeader")
        gen_layout.addWidget(gen_title)

        # Device Name
        row1 = QHBoxLayout()
        name_lbl = QLabel("This Laptop's Name:", gen_card)
        name_lbl.setFixedWidth(160)
        self.name_input = QLineEdit(self.cfg.device_name, gen_card)
        row1.addWidget(name_lbl)
        row1.addWidget(self.name_input)
        gen_layout.addLayout(row1)

        # Download Directory
        row2 = QHBoxLayout()
        dl_lbl = QLabel("Default Download Path:", gen_card)
        dl_lbl.setFixedWidth(160)
        self.dl_input = QLineEdit(self.cfg.download_dir, gen_card)
        browse_btn = QPushButton("Browse...", gen_card)
        browse_btn.clicked.connect(self._browse_download_dir)
        row2.addWidget(dl_lbl)
        row2.addWidget(self.dl_input)
        row2.addWidget(browse_btn)
        gen_layout.addLayout(row2)

        # Port & Theme
        row3 = QHBoxLayout()
        port_lbl = QLabel("Transfer Port:", gen_card)
        port_lbl.setFixedWidth(160)
        self.port_spin = QSpinBox(gen_card)
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(self.cfg.transfer_port)
        row3.addWidget(port_lbl)
        row3.addWidget(self.port_spin)

        theme_lbl = QLabel("App Theme:", gen_card)
        theme_lbl.setFixedWidth(100)
        self.theme_combo = QComboBox(gen_card)
        self.theme_combo.addItems(["dark", "light"])
        self.theme_combo.setCurrentText(self.cfg.theme)
        self.theme_combo.currentTextChanged.connect(self._on_theme_changed)
        row3.addSpacing(20)
        row3.addWidget(theme_lbl)
        row3.addWidget(self.theme_combo)
        gen_layout.addLayout(row3)

        # Remote Browsing Toggle
        self.remote_browse_chk = QCheckBox("Allow other laptops to browse files on this computer (requires explicit approval)", gen_card)
        self.remote_browse_chk.setChecked(getattr(self.cfg, "allow_remote_browsing", True))
        gen_layout.addWidget(self.remote_browse_chk)

        save_btn = QPushButton("💾 Save Preferences", gen_card)
        save_btn.setObjectName("primaryButton")
        save_btn.clicked.connect(self._save_preferences)
        gen_layout.addWidget(save_btn, alignment=Qt.AlignRight)

        layout.addWidget(gen_card)

        # Turbo Wi-Fi & Wireless Speed Accelerator Card
        wifi_card = QFrame(content)
        wifi_card.setObjectName("card")
        wifi_card.setStyleSheet("QFrame#card { border: 1px solid #10b981; }")
        wifi_layout = QVBoxLayout(wifi_card)
        wifi_layout.setContentsMargins(16, 16, 16, 16)
        wifi_layout.setSpacing(10)

        wifi_title = QLabel("⚡ Turbo Wi-Fi 6 & Wireless Speed Accelerator", wifi_card)
        wifi_title.setObjectName("sectionHeader")
        wifi_sub = QLabel(
            "Maximizes wireless transfer speeds by auditing radio bands, link negotiation rates, and bypassing 2-hop router relays.",
            wifi_card
        )
        wifi_sub.setObjectName("subtitleLabel")
        wifi_layout.addWidget(wifi_title)
        wifi_layout.addWidget(wifi_sub)

        self.wifi_audit_label = QLabel(wifi_card)
        self.wifi_audit_label.setTextFormat(Qt.RichText)
        self.wifi_audit_label.setWordWrap(True)
        wifi_layout.addWidget(self.wifi_audit_label)

        wifi_btn_row = QHBoxLayout()
        refresh_wifi_btn = QPushButton("🔄 Re-Audit Wi-Fi", wifi_card)
        refresh_wifi_btn.clicked.connect(self._refresh_wifi_audit)

        hotspot_btn = QPushButton("🚀 Open Windows 5GHz Hotspot (Direct Link)", wifi_card)
        hotspot_btn.setStyleSheet("background-color: #059669; color: white; font-weight: bold; padding: 6px 14px;")
        hotspot_btn.clicked.connect(open_mobile_hotspot_settings)

        wifi_btn_row.addWidget(refresh_wifi_btn)
        wifi_btn_row.addWidget(hotspot_btn)
        wifi_btn_row.addStretch()
        wifi_layout.addLayout(wifi_btn_row)

        layout.addWidget(wifi_card)
        self._refresh_wifi_audit()

        # Network Diagnostics Card
        diag_card = QFrame(content)
        diag_card.setObjectName("card")
        diag_layout = QVBoxLayout(diag_card)
        diag_layout.setContentsMargins(16, 16, 16, 16)
        diag_layout.setSpacing(12)

        diag_title = QLabel("Network Connectivity Diagnostics", diag_card)
        diag_title.setObjectName("sectionHeader")
        diag_layout.addWidget(diag_title)

        # Detected Interfaces
        self.iface_label = QLabel(diag_card)
        self._refresh_detected_ips()
        diag_layout.addWidget(self.iface_label)

        # Test reachability tool
        test_row = QHBoxLayout()
        test_lbl = QLabel("Test Remote Laptop:", diag_card)
        test_lbl.setFixedWidth(150)
        self.target_ip_input = QLineEdit(diag_card)
        self.target_ip_input.setPlaceholderText("Remote laptop IP (e.g. 192.168.1.15)")
        test_btn = QPushButton("Ping Target", diag_card)
        test_btn.clicked.connect(self._test_remote_reachability)
        test_row.addWidget(test_lbl)
        test_row.addWidget(self.target_ip_input)
        test_row.addWidget(test_btn)
        diag_layout.addLayout(test_row)

        layout.addWidget(diag_card)

        # Windows Defender Firewall Troubleshooting Card
        fw_card = QFrame(content)
        fw_card.setObjectName("card")
        fw_layout = QVBoxLayout(fw_card)
        fw_layout.setContentsMargins(16, 16, 16, 16)
        fw_layout.setSpacing(10)

        fw_title = QLabel("Windows Firewall Troubleshooting", fw_card)
        fw_title.setObjectName("sectionHeader")
        fw_sub = QLabel(
            "If files cannot be transferred or laptops cannot see each other, Windows Firewall may be blocking incoming LAN packets.\n"
            "Do NOT disable your firewall! Instead, allow LaptopShare through Windows Firewall:",
            fw_card
        )
        fw_sub.setObjectName("subtitleLabel")
        fw_layout.addWidget(fw_title)
        fw_layout.addWidget(fw_sub)

        self.fw_text = QTextEdit(fw_card)
        self.fw_text.setReadOnly(True)
        self.fw_text.setMarkdown(get_firewall_troubleshooting_info())
        self.fw_text.setFixedHeight(180)
        fw_layout.addWidget(self.fw_text)

        copy_ps_btn = QPushButton("📋 Copy PowerShell Firewall Rule to Clipboard", fw_card)
        copy_ps_btn.clicked.connect(self._copy_firewall_cmd)
        fw_layout.addWidget(copy_ps_btn, alignment=Qt.AlignLeft)

        layout.addWidget(fw_card)

        scroll.setWidget(content)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def _refresh_wifi_audit(self):
        info = get_wifi_diagnostics()
        if info.get("connected"):
            band_color = "#10b981" if info.get("is_5ghz") else "#f59e0b"
            wifi6_badge = " [Wi-Fi 6 / 802.11ax]" if info.get("is_wifi6") else ""
            html = f"""
            <b>Current Wireless Connection:</b><br>
            • <b>Network (SSID):</b> {info.get('ssid', 'Unknown')} {wifi6_badge}<br>
            • <b>Band:</b> <span style="color: {band_color}; font-weight: bold;">{info.get('band', 'Unknown')}</span> | <b>Signal:</b> {info.get('signal', 'Unknown')}<br>
            • <b>Negotiated Link Rate:</b> <b>{info.get('link_speed_tx', '0')} Mbps</b> (TX) / <b>{info.get('link_speed_rx', '0')} Mbps</b> (RX)<br>
            • <b>Optimization Advice:</b> {info.get('advice', '')}
            """
        else:
            html = "<i>No active Wi-Fi adapter detected or not currently connected to a wireless network.</i>"
        self.wifi_audit_label.setText(html)

    def _refresh_detected_ips(self):
        ips = get_local_ip_addresses()
        lines = ["<b>Active Network Adapters Detected:</b>"]
        for item in ips:
            primary_tag = " (Recommended LAN)" if item.get("is_primary") else ""
            lines.append(f"• <b>{item['name']}</b>: <code>{item['ip']}</code>{primary_tag}")

        self.iface_label.setText("<br>".join(lines))

    def _browse_download_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose Download Directory", self.dl_input.text())
        if folder:
            self.dl_input.setText(folder)

    def _save_preferences(self):
        self.cfg.device_name = self.name_input.text().strip() or "Windows-Laptop"
        self.cfg.download_dir = self.dl_input.text().strip()
        self.cfg.transfer_port = self.port_spin.value()
        self.cfg.theme = self.theme_combo.currentText()
        self.cfg.allow_remote_browsing = self.remote_browse_chk.isChecked()
        self.cfg_mgr.save()
        QMessageBox.information(self, "Saved", "Preferences saved successfully!")

    def _on_theme_changed(self, new_theme: str):
        self.cfg.theme = new_theme
        self.cfg_mgr.save()
        self.theme_changed.emit(new_theme)

    def _test_remote_reachability(self):
        target = self.target_ip_input.text().strip()
        if not target:
            QMessageBox.warning(self, "IP Missing", "Enter target laptop IP.")
            return

        port = self.port_spin.value()
        success, msg = test_lan_connection(target, port)
        if success:
            QMessageBox.information(self, "Diagnostic Result", f"✅ Success: {msg}")
        else:
            QMessageBox.critical(self, "Diagnostic Result", f"❌ Failed: {msg}")

    def _copy_firewall_cmd(self):
        cmd = 'New-NetFirewallRule -DisplayName "LaptopShare File Transfer" -Direction Inbound -Program (Get-Process -Id $PID).Path -Action Allow -Profile Any'
        QApplication.clipboard().setText(cmd)
        QMessageBox.information(
            self,
            "Copied to Clipboard",
            "PowerShell firewall rule command copied!\n\nOpen PowerShell as Administrator and paste to immediately permit inbound transfers."
        )
