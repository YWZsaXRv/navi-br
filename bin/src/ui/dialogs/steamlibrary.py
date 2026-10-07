import logging
from typing import List, Optional

from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import (
    QDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from ui.dialogs.dialog_helpers import FiltroVimListas, aplicar_barra_titulo, create_accept_button
from ui.window_defaults import aplicar

logger = logging.getLogger(__name__)


class SteamLibraryDialog(QDialog):
    """Dialog for selecting a Steam library folder."""

    def __init__(self, library_paths: List[str], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Selecionar biblioteca Steam")
        aplicar(self, parent)

        self.selected_path: Optional[str] = None
        self.list_widget: Optional[QListWidget] = None

        logger.debug(f"Opening SteamLibraryDialog with {len(library_paths)} libraries.")
        self._setup_ui(library_paths)
        aplicar_barra_titulo(self)

    def _setup_ui(self, library_paths: List[str]) -> None:
        """Initialize the layout and widgets."""
        layout = QVBoxLayout(self)

        self.list_widget = QListWidget()
        self.list_widget.installEventFilter(FiltroVimListas(self.list_widget))

        # Fix for overlapping items
        self.list_widget.setUniformItemSizes(True)
        self.list_widget.setSpacing(2)

        # Populate list with sorted paths
        for path in sorted(library_paths):
            item = QListWidgetItem(path)
            # Explicitly set size hint to prevent overlap
            item.setSizeHint(QSize(0, 24))
            self.list_widget.addItem(item)

        layout.addWidget(self.list_widget)

        # Select first item by default if available
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

        buttons = create_accept_button(self.accept)
        layout.addWidget(buttons)

    def accept(self) -> None:
        """Handle the OK button click."""
        if not self.list_widget:
            super().accept()
            return

        current_item = self.list_widget.currentItem()

        if not current_item:
            QMessageBox.warning(self, "Nenhuma seleção", "Selecione uma pasta de biblioteca.")
            return

        self.selected_path = current_item.text()
        logger.info(f"User selected Steam library: {self.selected_path}")
        super().accept()

    def get_selected_path(self) -> Optional[str]:
        """Return the selected library path."""
        return self.selected_path

    def keyPressEvent(self, event):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QListWidget

        k = event.key()
        if k in (Qt.Key.Key_J, Qt.Key.Key_Down):
            if hasattr(self, 'list_widget') and isinstance(self.list_widget, QListWidget):
                lst = self.list_widget
                cnt = lst.count()
                if cnt:
                    cur = lst.currentRow()
                    lst.setCurrentRow(min(cnt-1, cur+1))
                    lst.setFocus()
                return
        if k in (Qt.Key.Key_K, Qt.Key.Key_Up):
            if hasattr(self, 'list_widget') and isinstance(self.list_widget, QListWidget):
                lst = self.list_widget
                cnt = lst.count()
                if cnt:
                    cur = lst.currentRow()
                    lst.setCurrentRow(max(0, cur-1))
                    lst.setFocus()
                return
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.accept()
            return
        if k == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)
