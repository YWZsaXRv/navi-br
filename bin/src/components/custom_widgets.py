from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QFontMetrics
from PyQt6.QtWidgets import QLabel


class ScaledLabel(QLabel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setMinimumSize(1, 1)
        self._movie = None

    def setMovie(self, movie):
        if self._movie:
            self._movie.frameChanged.disconnect(self.on_frame_changed)
        self._movie = movie
        if self._movie:
            self._movie.frameChanged.connect(self.on_frame_changed)

    def on_frame_changed(self):
        if self.size().width() > 0 and self.size().height() > 0 and self._movie:
            pixmap = self._movie.currentPixmap()
            scaled_pixmap = pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            super().setPixmap(scaled_pixmap)

    def resizeEvent(self, event):
        if self._movie:
            self.on_frame_changed()
        super().resizeEvent(event)


class ScaledFontLabel(QLabel):
    def __init__(self, *args, escala_por="altura", **kwargs):
        super().__init__(*args, **kwargs)
        self.escala_por = escala_por
        self.setMinimumSize(1, 1)
        self.setWordWrap(True)  # Enable word wrap
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)  # Center text

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Get text metrics to check if text fits
        font = self.font()
        text = self.text()

        if text:
            # largura: título de destaque; altura: rótulo comum
            if self.escala_por == "largura":
                base, fator = self.width(), 0.07
            else:
                base, fator = self.height(), 0.4
            new_size = max(8, min(72, int(base * fator)))
            font.setPointSize(new_size)

            # Check if text fits width-wise
            test_font = QFont(font)
            test_font.setPointSize(new_size)
            metrics = QFontMetrics(test_font)
            text_width = metrics.horizontalAdvance(text)

            # Reduce font size if text is too wide (with some padding)
            while text_width > self.width() * 0.9 and new_size > 8:
                new_size -= 1
                test_font.setPointSize(new_size)
                metrics = QFontMetrics(test_font)
                text_width = metrics.horizontalAdvance(text)

            font.setPointSize(new_size)

        self.setFont(font)
