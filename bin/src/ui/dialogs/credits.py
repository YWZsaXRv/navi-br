import logging

from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QGroupBox,
    QLabel,
    QWidget,
)

from ui.dialogs.dialog_helpers import aplicar_barra_titulo
from ui.theme import cor_secundaria
from ui.window_defaults import aplicar
from utils.settings import get_settings

logger = logging.getLogger(__name__)


class CreditsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Créditos")
        aplicar(self, parent)
        self.settings = get_settings()
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(24, 24, 24, 24)
        self.main_layout.setSpacing(16)
        self.accent_color = self.settings.value("accent_color", "#C06C84")
        self.background_color = self.settings.value("background_color", "#000000")

        logger.debug("Opening CreditsDialog.")

        # Apply styling (match settings dialog)
        self.setStyleSheet(
            f"""
            QGroupBox {{
                color: {self.accent_color};
            }}
        """
        )

        self.main_layout.addStretch()

        # Create credits content
        self._create_credits_content()

        self.main_layout.addStretch()

        # rodapé com o fechar alinhado na direita
        footer = QHBoxLayout()
        footer.addStretch()
        close_button = QPushButton("Fechar")
        close_button.setFixedWidth(110)
        close_button.clicked.connect(self.reject)
        footer.addWidget(close_button)
        self.main_layout.addLayout(footer)
        aplicar_barra_titulo(self)

    def _create_credits_content(self):
        """Create the credits content"""
        credits_widget = QWidget()
        credits_layout = QVBoxLayout(credits_widget)
        credits_layout.setContentsMargins(15, 15, 15, 15)

        # --- Credits Information ---
        credits_group = QGroupBox()
        credits_info_layout = QVBoxLayout()

        # Developer information
        dev_label = QLabel("Desenvolvido por: Lain Iwakura")
        dev_label.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {self.accent_color};"
        )
        credits_info_layout.addWidget(dev_label)

        # Address information (folga igual à das outras linhas, sem margem extra)
        address_label = QLabel("Endereço: Takei Nakama, Tokyo")
        address_label.setStyleSheet("font-size: 12px;")
        credits_info_layout.addWidget(address_label)

        # Phone information
        phone_label = QLabel("Telefone: 4002-8922")
        phone_label.setStyleSheet("font-size: 12px;")
        credits_info_layout.addWidget(phone_label)

        credits_group.setLayout(credits_info_layout)
        credits_layout.addWidget(credits_group)

        # --- Special Thanks ---
        special_thanks_group = QGroupBox()
        special_thanks_layout = QVBoxLayout()

        # deixa claro que a lista é de projetos usados, não de autores
        tools_title = QLabel("Projetos incríveis que a ferramenta consome:")
        tools_title.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {self.accent_color};"
        )
        special_thanks_layout.addWidget(tools_title)

        tools_label = QLabel(
            "• SLSsteam\n"
            "• h3adcr-b\n"
            "• Steamless\n"
            "• DepotDownloaderMod\n"
            "• SLScheevo\n"
            "• steam[client] (solsticegamestudios)\n"
            "• Morrenus API"
        )
        tools_label.setStyleSheet(
            f"font-size: 11px; color: {cor_secundaria(self.background_color)};"
            " margin-left: 15px;"
        )
        special_thanks_layout.addWidget(tools_label)

        special_thanks_group.setLayout(special_thanks_layout)
        credits_layout.addWidget(special_thanks_group)

        # coluna centralizada, senão o grupo fica largo com texto curto sobrando
        row = QHBoxLayout()
        row.addStretch()
        credits_widget.setFixedWidth(400)
        row.addWidget(credits_widget)
        row.addStretch()
        self.main_layout.addLayout(row)
