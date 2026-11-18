# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:/Users/mishr/.gemini/antigravity/scratch/LaptopShare/main.py'],
    pathex=[],
    binaries=[],
    datas=[('C:/Users/mishr/.gemini/antigravity/scratch/LaptopShare/assets', 'assets')],
    hiddenimports=['PySide6', 'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets', 'cryptography', 'qrcode', 'PIL', 'psutil', 'core.config', 'core.security', 'core.protocol', 'core.network_utils', 'core.file_manager', 'core.history', 'core.discovery', 'core.transfer_server', 'core.transfer_client', 'core.remote_browser_client', 'core.migration', 'core.migration_client', 'core.web_explorer_server', 'ui.styles', 'ui.qr_widget', 'ui.send_tab', 'ui.receive_tab', 'ui.browse_tab', 'ui.migration_tab', 'ui.devices_tab', 'ui.history_tab', 'ui.settings_tab', 'ui.main_window'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='LaptopShare',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['C:/Users/mishr/.gemini/antigravity/scratch/LaptopShare/assets/icon.ico'],
)
