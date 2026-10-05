from PyQt6.QtWidgets import QDialogButtonBox, QPushButton
from PyQt6.QtCore import Qt


def create_standard_buttons(on_accept, on_reject):
    buttons = QDialogButtonBox()
    ok_btn = buttons.addButton(QDialogButtonBox.StandardButton.Ok)
    cancel_btn = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
    ok_btn.setText("OK")
    cancel_btn.setText("Cancelar")
    buttons.accepted.connect(on_accept)
    buttons.rejected.connect(on_reject)
    return buttons
