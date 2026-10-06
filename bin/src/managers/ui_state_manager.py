import logging
from typing import cast
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QHBoxLayout,
    QApplication,
    QFrame,
)

from ui.theme import cabecalho_secao, cor_secundaria

logger = logging.getLogger(__name__)


class UIStateManager:
    def __init__(self, main_window):
        self.main_window = main_window
        self.settings = main_window.settings

        # UI state
        self.fetch_dialog = None
        self.depot_dialog = None

        # Queue UI elements
        self.queue_widget = None
        self.queue_label = None
        self.fila_vazia_label = None
        self.queue_list_widget = None
        self.queue_move_up_button = None
        self.queue_move_down_button = None
        self.queue_remove_button = None
        self.pause_button = None
        self.cancel_button = None

    def setup_queue_panel(self):
        """Setup the download queue panel"""
        self.queue_widget = QWidget()
        queue_layout = QVBoxLayout(self.queue_widget)
        # sem recuo: o recuo lateral e o gap de baixo já vêm da seção de baixo
        queue_layout.setContentsMargins(0, 0, 0, 0)
        queue_layout.setSpacing(6)

        # mesmo formato do cabeçalho de log: título e linha embaixo
        self.queue_label = QLabel("Fila de download")
        self.queue_label.setStyleSheet(cabecalho_secao(self.main_window.accent_color))
        queue_layout.addWidget(self.queue_label)

        queue_line = QFrame()
        queue_line.setFixedHeight(1)
        queue_line.setStyleSheet(
            f"background-color: {self.main_window.accent_color}; border: none;"
        )
        queue_layout.addWidget(queue_line)

        # mesmo respiro do log entre a linha e o conteúdo
        queue_layout.addSpacing(8)

        # lista e botões no mesmo recuo dos títulos e do log
        conteudo = QWidget()
        conteudo_layout = QVBoxLayout(conteudo)
        conteudo_layout.setContentsMargins(0, 0, 0, 0)
        conteudo_layout.setSpacing(6)

        self.fila_vazia_label = QLabel("Nenhum download na fila")
        self.fila_vazia_label.setStyleSheet(
            f"color: {cor_secundaria(self.settings.value('background_color', '#000000'))};"
        )
        conteudo_layout.addWidget(self.fila_vazia_label)

        # Queue list
        self.queue_list_widget = QListWidget()
        self.queue_list_widget.setToolTip(
            "Fila de download atual. Selecione um item para movê-lo."
        )
        # a lista absorve o espaço que sobra, os botões ficam no fim
        conteudo_layout.addWidget(self.queue_list_widget, 1)

        # Queue buttons
        self._setup_queue_buttons(conteudo_layout)

        queue_layout.addWidget(conteudo, 1)

        modelo = self.queue_list_widget.model()
        modelo.rowsInserted.connect(self._atualiza_fila_vazia)
        modelo.rowsRemoved.connect(self._atualiza_fila_vazia)
        # o clear() da lista vira reset, não remove linha por linha
        modelo.modelReset.connect(self._atualiza_fila_vazia)
        self._atualiza_fila_vazia()

    def _atualiza_fila_vazia(self, *args):
        """Aviso de fila vazia e botões seguem a quantidade de itens."""
        vazio = self.queue_list_widget.count() == 0
        self.fila_vazia_label.setVisible(vazio)
        for botao in (
            self.queue_move_up_button,
            self.queue_move_down_button,
            self.queue_remove_button,
        ):
            botao.setEnabled(not vazio)

    def _setup_queue_buttons(self, parent_layout):
        """Setup queue control buttons"""
        queue_button_layout = QHBoxLayout()
        # folga entre os botões; na janela mínima com 5 visíveis ainda cabe
        queue_button_layout.setSpacing(10)

        self.queue_move_up_button = QPushButton("Mover para cima")
        self.queue_move_up_button.clicked.connect(
            self.main_window.job_queue.move_item_up
        )
        queue_button_layout.addWidget(self.queue_move_up_button)

        self.queue_move_down_button = QPushButton("Mover para baixo")
        self.queue_move_down_button.clicked.connect(
            self.main_window.job_queue.move_item_down
        )
        queue_button_layout.addWidget(self.queue_move_down_button)

        self.queue_remove_button = QPushButton("Remover")
        self.queue_remove_button.clicked.connect(self.main_window.job_queue.remove_item)
        queue_button_layout.addWidget(self.queue_remove_button)

        self.pause_button = QPushButton("Pausar")
        self.pause_button.clicked.connect(self.main_window.task_manager.toggle_pause)
        self.pause_button.setVisible(False)
        queue_button_layout.addWidget(self.pause_button)

        self.cancel_button = QPushButton("Cancelar")
        self.cancel_button.clicked.connect(
            self.main_window.task_manager.cancel_current_job
        )
        self.cancel_button.setVisible(False)
        queue_button_layout.addWidget(self.cancel_button)

        parent_layout.addLayout(queue_button_layout)

    def apply_style_settings(self):
        """Apply current style settings to UI"""
        self.main_window.background_color = self.settings.value(
            "background_color", "#000000"
        )
        self.main_window.accent_color = self.settings.value("accent_color", "#C06C84")

        # Load font family
        font_family = self.settings.value("font", "W95FA")

        font_size = self.settings.value("font-size", 10, type=int)

        # Create font
        font = QFont(font_family)
        font.setPointSize(font_size)

        # Set font style
        font_style = self.settings.value("font-style", "Normal")
        if font_style == "Italic":
            font.setItalic(True)
        elif font_style == "Bold":
            font.setBold(True)
        elif font_style == "Bold Italic":
            font.setBold(True)
            font.setItalic(True)
        # "Normal" is the default, so no changes needed

        self.main_window.font = font

        # Update application appearance
        from main import update_appearance

        font_file = None
        font_ok, font_info = update_appearance(
            cast(QApplication, QApplication.instance()),
            self.main_window.accent_color,
            self.main_window.background_color,
            self.main_window.font,
            font_file=font_file,
        )

        # Apply styles to various UI elements
        self._apply_background_color()
        self._apply_accent_color()

    def _apply_background_color(self):
        """Apply background color to main content"""
        main_frame = self.main_window.central_widget.findChild(QFrame)
        if main_frame:
            main_frame.setStyleSheet(
                f"background-color: {self.main_window.background_color};"
            )

    def _apply_accent_color(self):
        """Apply accent color to UI elements"""
        accent_style = f"color: {self.main_window.accent_color};"

        # Drop text label
        self.main_window._atualiza_zona_drop()

        # Cabeçalho da fila (mesmo estilo do cabeçalho de log)
        if getattr(self, "queue_label", None):
            self.queue_label.setStyleSheet(
                cabecalho_secao(self.main_window.accent_color)
            )

        # Progress bar
        self.main_window.update_progress_bar_style()

        # Log output
        self.main_window.log_output.setStyleSheet(accent_style)

        # Bottom titlebar
        if hasattr(self.main_window, "bottom_titlebar"):
            self.main_window.bottom_titlebar.update_style()

    def update_queue_visibility(self, is_processing, has_jobs):
        """Update queue visibility based on current state"""
        if not is_processing and not has_jobs:
            if self.queue_widget:
                self.queue_widget.setVisible(False)
            self.main_window.drop_text_label.setText("Arraste o ZIP aqui")
        else:
            if self.queue_widget:
                self.queue_widget.setVisible(True)
            if not is_processing:
                self.main_window.drop_text_label.setText(
                    "Fila ociosa. Pronto para o próximo."
                )
        # a fila muda a reserva de espaço, o log se reencaixa
        if hasattr(self.main_window, "_agenda_ajuste_log"):
            self.main_window._agenda_ajuste_log()
