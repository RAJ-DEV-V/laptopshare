"""
LaptopShare QR Code Widget
Generates high-resolution QR codes to easily connect using IP and PIN.
"""

from io import BytesIO
import qrcode
from PIL import Image

from PySide6.QtWidgets import QLabel
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtCore import Qt

class QRCodeWidget(QLabel):
    def __init__(self, size: int = 180, parent=None):
        super().__init__(parent)
        self.qr_size = size
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("border-radius: 8px; background-color: #ffffff; padding: 4px;")

    def set_data(self, data: str):
        if not data:
            self.clear()
            return

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=6,
            border=2,
        )
        qr.add_data(data)
        qr.make(fit=True)

        img: Image.Image = qr.make_image(fill_color="black", back_color="white")
        # Convert PIL to QPixmap
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        qimage = QImage.fromData(buffer.getvalue())
        pixmap = QPixmap.fromImage(qimage)

        scaled = pixmap.scaled(
            self.qr_size,
            self.qr_size,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.setPixmap(scaled)
