"""
LaptopShare Windows 11 Fluent Theme Stylesheets
Provides modern dark and light mode stylesheets with rounded cards and accent colors.
"""

DARK_THEME = """
QWidget {
    background-color: #1a1b1e;
    color: #e4e4e7;
    font-family: 'Segoe UI Variable Display', 'Segoe UI', sans-serif;
    font-size: 13px;
}

QMainWindow, QDialog {
    background-color: #141416;
}

QFrame#card {
    background-color: #222328;
    border: 1px solid #2f3136;
    border-radius: 12px;
}

QFrame#dropZone {
    background-color: #222328;
    border: 2px dashed #3f424b;
    border-radius: 14px;
}
QFrame#dropZone:hover {
    border: 2px dashed #0ea5e9;
    background-color: #252830;
}

QLabel#titleLabel {
    font-size: 22px;
    font-weight: 700;
    color: #ffffff;
}

QLabel#subtitleLabel {
    font-size: 13px;
    color: #94a3b8;
}

QLabel#sectionHeader {
    font-size: 15px;
    font-weight: 600;
    color: #f1f5f9;
}

QLabel#badge {
    background-color: #0369a1;
    color: #e0f2fe;
    border-radius: 6px;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 600;
}

QLabel#pinDisplay {
    font-size: 32px;
    font-weight: 800;
    letter-spacing: 6px;
    color: #38bdf8;
    background-color: #1e293b;
    border: 1px solid #0284c7;
    border-radius: 10px;
    padding: 10px 20px;
}

QPushButton {
    background-color: #2d3038;
    color: #f8fafc;
    border: 1px solid #3f424b;
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #383c46;
    border: 1px solid #4b505c;
}
QPushButton:pressed {
    background-color: #252830;
}

QPushButton#primaryButton {
    background-color: #0284c7;
    color: #ffffff;
    border: 1px solid #0369a1;
    font-weight: 600;
    padding: 9px 20px;
}
QPushButton#primaryButton:hover {
    background-color: #0ea5e9;
    border: 1px solid #38bdf8;
}
QPushButton#primaryButton:pressed {
    background-color: #0369a1;
}

QPushButton#successButton {
    background-color: #16a34a;
    color: #ffffff;
    border: 1px solid #15803d;
    font-weight: 600;
}
QPushButton#successButton:hover {
    background-color: #22c55e;
}

QPushButton#dangerButton {
    background-color: #dc2626;
    color: #ffffff;
    border: 1px solid #b91c1c;
    font-weight: 600;
}
QPushButton#dangerButton:hover {
    background-color: #ef4444;
}

QLineEdit, QComboBox, QSpinBox {
    background-color: #272a31;
    color: #ffffff;
    border: 1px solid #3d414c;
    border-radius: 8px;
    padding: 7px 12px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
    border: 1px solid #0ea5e9;
    background-color: #2c3038;
}

QComboBox QAbstractItemView {
    background-color: #272a31;
    border: 1px solid #3d414c;
    selection-background-color: #0284c7;
    selection-color: #ffffff;
    border-radius: 6px;
    padding: 4px;
}

QListWidget, QTableWidget {
    background-color: #1f2025;
    border: 1px solid #2f323a;
    border-radius: 10px;
    padding: 6px;
    color: #e2e8f0;
}
QListWidget::item, QTableWidget::item {
    border-radius: 6px;
    padding: 8px 10px;
    margin-bottom: 2px;
}
QListWidget::item:selected, QTableWidget::item:selected {
    background-color: #0284c7;
    color: #ffffff;
}
QListWidget::item:hover, QTableWidget::item:hover {
    background-color: #2c2f37;
}

QProgressBar {
    background-color: #272a31;
    border: 1px solid #363942;
    border-radius: 6px;
    height: 12px;
    text-align: center;
    color: #ffffff;
    font-size: 11px;
}
QProgressBar::chunk {
    background-color: #0ea5e9;
    border-radius: 5px;
}

QScrollBar:vertical {
    border: none;
    background: #1a1b1e;
    width: 8px;
    margin: 0px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #475569;
    min-height: 20px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #64748b;
}

QHeaderView::section {
    background-color: #222328;
    color: #94a3b8;
    padding: 8px;
    border: none;
    border-bottom: 1px solid #2f3136;
    font-weight: 600;
}
"""

LIGHT_THEME = """
QWidget {
    background-color: #f8fafc;
    color: #1e293b;
    font-family: 'Segoe UI Variable Display', 'Segoe UI', sans-serif;
    font-size: 13px;
}

QMainWindow, QDialog {
    background-color: #f1f5f9;
}

QFrame#card {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
}

QFrame#dropZone {
    background-color: #ffffff;
    border: 2px dashed #cbd5e1;
    border-radius: 14px;
}
QFrame#dropZone:hover {
    border: 2px dashed #0284c7;
    background-color: #f0f9ff;
}

QLabel#titleLabel {
    font-size: 22px;
    font-weight: 700;
    color: #0f172a;
}

QLabel#subtitleLabel {
    font-size: 13px;
    color: #64748b;
}

QLabel#sectionHeader {
    font-size: 15px;
    font-weight: 600;
    color: #1e293b;
}

QLabel#badge {
    background-color: #e0f2fe;
    color: #0369a1;
    border-radius: 6px;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 600;
}

QLabel#pinDisplay {
    font-size: 32px;
    font-weight: 800;
    letter-spacing: 6px;
    color: #0284c7;
    background-color: #f0f9ff;
    border: 1px solid #bae6fd;
    border-radius: 10px;
    padding: 10px 20px;
}

QPushButton {
    background-color: #ffffff;
    color: #334155;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #f8fafc;
    border: 1px solid #94a3b8;
}
QPushButton:pressed {
    background-color: #f1f5f9;
}

QPushButton#primaryButton {
    background-color: #0284c7;
    color: #ffffff;
    border: 1px solid #0369a1;
    font-weight: 600;
    padding: 9px 20px;
}
QPushButton#primaryButton:hover {
    background-color: #0369a1;
}

QPushButton#successButton {
    background-color: #16a34a;
    color: #ffffff;
    border: 1px solid #15803d;
    font-weight: 600;
}
QPushButton#successButton:hover {
    background-color: #15803d;
}

QPushButton#dangerButton {
    background-color: #dc2626;
    color: #ffffff;
    border: 1px solid #b91c1c;
    font-weight: 600;
}
QPushButton#dangerButton:hover {
    background-color: #b91c1c;
}

QLineEdit, QComboBox, QSpinBox {
    background-color: #ffffff;
    color: #0f172a;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 7px 12px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
    border: 1px solid #0284c7;
}

QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    selection-background-color: #0284c7;
    selection-color: #ffffff;
    border-radius: 6px;
    padding: 4px;
}

QListWidget, QTableWidget {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 6px;
    color: #1e293b;
}
QListWidget::item, QTableWidget::item {
    border-radius: 6px;
    padding: 8px 10px;
    margin-bottom: 2px;
}
QListWidget::item:selected, QTableWidget::item:selected {
    background-color: #0284c7;
    color: #ffffff;
}
QListWidget::item:hover, QTableWidget::item:hover {
    background-color: #f1f5f9;
}

QProgressBar {
    background-color: #e2e8f0;
    border: none;
    border-radius: 6px;
    height: 12px;
    text-align: center;
    color: #1e293b;
    font-size: 11px;
}
QProgressBar::chunk {
    background-color: #0284c7;
    border-radius: 5px;
}

QScrollBar:vertical {
    border: none;
    background: #f1f5f9;
    width: 8px;
    margin: 0px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #cbd5e1;
    min-height: 20px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #94a3b8;
}

QHeaderView::section {
    background-color: #f8fafc;
    color: #64748b;
    padding: 8px;
    border: none;
    border-bottom: 1px solid #e2e8f0;
    font-weight: 600;
}
"""
