import logging
from typing import Callable, Optional

from PyQt6.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PyQt6.QtGui import (
    QColor,
    QIcon,
    QLinearGradient,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.theme import claro, gradiente_titulo, sulco, texto_sobre
from utils.brand import DISPLAY_NAME
from utils.paths import Paths
from utils.settings import get_settings
from utils.version import app_version
from .assets import (
    BOOK_SVG,
    GEAR_SVG,
    SEARCH_SVG,
)

logger = logging.getLogger(__name__)

# 16px de botão + folga; a linha de 1px do topo entra na conta
ALTURA_BARRA = 24
TAMANHO_BOTAO = 16
GLIFO = 9

class ClickableLabel(QLabel):

    def __init__(
        self,
        text: str,
        parent: Optional[QWidget] = None,
        callback: Optional[Callable[[], None]] = None,
    ):
        super().__init__(text, parent)
        self.callback = callback
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        # aceito antes de abrir o modal, senão o clique vaza pro titlebar e o
        # startSystemMove começa sem ver o botão subir, a janela fica arrastando
        event.accept()
        if self.callback:
            self.callback()

class TituloElidido(QLabel):
    """corta o título com reticências quando falta espaço."""

    def __init__(self, text: str, parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self._texto = text

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        cortado = self.fontMetrics().elidedText(
            self._texto, Qt.TextElideMode.ElideRight, max(0, self.width())
        )
        if cortado != self.text():
            self.setText(cortado)

class BottomTitleBar(QFrame):
    """barra de título win95/98, no topo ou na base conforme a config."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.parent_window = parent
        self.setObjectName("barra_titulo")
        self.setFixedHeight(ALTURA_BARRA)
        self.no_previous_state = True

        self.icone_label: Optional[QLabel] = None
        self.title_label: Optional[TituloElidido] = None
        self.version_label: Optional[ClickableLabel] = None

        self.status_button: Optional[QPushButton] = None
        self.search_button: Optional[QPushButton] = None
        self.game_library_button: Optional[QPushButton] = None
        self.settings_button: Optional[QPushButton] = None
        self.minimize_button: Optional[QPushButton] = None
        self.maximize_button: Optional[QPushButton] = None
        self.close_button: Optional[QPushButton] = None

        self._inicio = QColor("#000080")
        self._fim = QColor("#A3A3C9")
        self._cor_texto = "#FFFFFF"
        self._cor_icone = "#FFFFFF"

        self._setup_ui()
        self._apply_style()
        parent.installEventFilter(self)
        logger.debug("BottomTitleBar initialized.")

    def _setup_ui(self) -> None:
        # a linha fica num widget próprio: borda em QFrame vaza pros rótulos
        # internos, já que QLabel herda de QFrame
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.top_line = QLabel()
        self.top_line.setFixedHeight(1)
        self.top_line.setObjectName("linha")
        outer.addWidget(self.top_line)

        layout = QHBoxLayout()
        layout.setContentsMargins(3, 2, 3, 2)
        layout.setSpacing(2)

        self.icone_label = QLabel()
        self.icone_label.setFixedSize(TAMANHO_BOTAO, TAMANHO_BOTAO)
        self.icone_label.setObjectName("icone")
        self._carrega_icone()
        layout.addWidget(self.icone_label)

        layout.addSpacing(3)

        self.title_label = TituloElidido(DISPLAY_NAME)
        self.title_label.setObjectName("titulo")
        layout.addWidget(self.title_label)

        layout.addSpacing(4)

        self.version_label = ClickableLabel(
            app_version,
            self.parent_window,
            getattr(self.parent_window, "open_credits_dialog", None),
        )
        self.version_label.setObjectName("versao")
        self.version_label.setToolTip("Ver créditos")
        layout.addWidget(self.version_label)

        layout.addSpacing(4)

        parent = self.parent_window

        self.status_button = self._create_colored_circle_button(
            getattr(parent, "open_status_dialog", None),
            "Status do download",
        )
        layout.addWidget(self.status_button)

        self.search_button = self._create_svg_button(
            SEARCH_SVG, getattr(parent, "open_fetch_dialog", None), "Baixar jogo"
        )
        layout.addWidget(self.search_button)

        self.game_library_button = self._create_svg_button(
            BOOK_SVG, getattr(parent, "open_game_library", None), "Biblioteca de jogos"
        )
        layout.addWidget(self.game_library_button)

        self.settings_button = self._create_svg_button(
            GEAR_SVG, getattr(parent, "open_settings", None), "Configurações"
        )
        layout.addWidget(self.settings_button)

        # o stretch isola os controles da janela na ponta direita, como no win95
        layout.addStretch(1)
        layout.addSpacing(4)

        self.minimize_button = self._create_control_button(
            "minimizar", self._minimize_window, "Minimizar"
        )
        layout.addWidget(self.minimize_button)

        self.maximize_button = self._create_control_button(
            "maximizar", self._maximize_window, "Maximizar"
        )
        layout.addWidget(self.maximize_button)

        self.close_button = self._create_control_button(
            "fechar", self._close_window, "Fechar"
        )
        layout.addWidget(self.close_button)

        outer.addLayout(layout, 1)

    def _carrega_icone(self) -> None:
        caminho = Paths.resource("logo/icon.ico")
        if not caminho.exists() or self.icone_label is None:
            return

        pixmap = QPixmap(str(caminho))
        if pixmap.isNull():
            return

        self.icone_label.setPixmap(
            pixmap.scaled(
                TAMANHO_BOTAO,
                TAMANHO_BOTAO,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _apply_style(self) -> None:
        settings = get_settings()
        bg_color = QColor(settings.value("background_color", "#000000"))
        accent_color = QColor(settings.value("accent_color", "#C06C84"))

        # sem estado inativo: sem foco (e no meio do arraste) some o azul
        self._inicio, self._fim = gradiente_titulo(accent_color)

        self._cor_texto = texto_sobre(self._inicio)
        self._cor_icone = self._cor_texto

        hover, press = (
            ("rgba(255,255,255,70)", "rgba(255,255,255,120)")
            if self._cor_texto == "#FFFFFF"
            else ("rgba(0,0,0,45)", "rgba(0,0,0,80)")
        )

        realce = QColor("#FFFFFF") if claro(bg_color) else accent_color.lighter(140)
        sombra = QColor("#808080") if claro(bg_color) else accent_color.darker(140)

        self.setStyleSheet(
            f"""
            QToolTip {{
                color: {accent_color.name()};
                background-color: {bg_color.name()};
                border: 1px solid {accent_color.name()};
                padding: 2px;
            }}
        """
        )

        if self.top_line:
            self.top_line.setStyleSheet(f"background-color: {sulco(bg_color)};")

        if self.title_label:
            self.title_label.setStyleSheet(
                f"color: {self._cor_texto}; font-size: 12px; font-weight: bold;"
                " background: transparent;"
            )

        if self.version_label:
            self.version_label.setCursor(Qt.CursorShape.PointingHandCursor)
            self.version_label.setStyleSheet(
                f"color: {self._cor_texto}; font-size: 11px; background: transparent;"
            )

        if self.icone_label:
            self.icone_label.setStyleSheet("background: transparent;")

        estilo_acao = f"""
            QPushButton {{
                background: transparent;
                border: none;
                padding: 0;
            }}
            QPushButton:hover {{
                background-color: {hover};
            }}
            QPushButton:pressed {{
                background-color: {press};
            }}
        """
        for botao in (
            self.search_button,
            self.game_library_button,
            self.settings_button,
        ):
            if botao:
                botao.setStyleSheet(estilo_acao)

        estilo_controle = f"""
            QPushButton {{
                background-color: {bg_color.name()};
                border-top: 2px solid {realce.name()};
                border-left: 2px solid {realce.name()};
                border-bottom: 2px solid {sombra.name()};
                border-right: 2px solid {sombra.name()};
                padding: 0;
            }}
            QPushButton:pressed {{
                background-color: {bg_color.name()};
                border-top: 2px solid {sombra.name()};
                border-left: 2px solid {sombra.name()};
                border-bottom: 2px solid {realce.name()};
                border-right: 2px solid {realce.name()};
            }}
        """
        for botao in (self.minimize_button, self.maximize_button, self.close_button):
            if botao:
                botao.setStyleSheet(estilo_controle)

        self._update_button_colors()
        self._atualiza_glifo_maximize()
        self.update()

    def update_style(self) -> None:
        self._apply_style()

    def _update_button_colors(self) -> None:
        # tingem com a cor do texto: com o acento eles somem no gradiente
        for button, svg_data in (
            (self.search_button, SEARCH_SVG),
            (self.game_library_button, BOOK_SVG),
            (self.settings_button, GEAR_SVG),
        ):
            if button:
                self._update_svg_button_color(button, svg_data, self._cor_icone)

        if self.no_previous_state and self.status_button:
            self._update_colored_circle_button(
                self.status_button,
                get_settings().value("accent_color", "#C06C84"),
            )

    def _update_colored_circle_button(self, button: QPushButton, color: str) -> None:
        try:
            circulo = QColor(color)
            # o acento é o próprio fundo do gradiente: sem anel o círculo some
            anel = (
                "rgba(255, 255, 255, 140)"
                if self._cor_texto == "#FFFFFF"
                else "rgba(0, 0, 0, 90)"
            )
            stylesheet = f"""
            QPushButton {{
                border-radius: 7px;
                background-color: {circulo.name()};
                border: 1px solid {anel};
                padding: 0;
            }}
            QPushButton:hover {{
                background-color: {circulo.lighter(125).name()};
            }}
            QPushButton:pressed {{
                background-color: {circulo.darker(120).name()};
            }}
            """
            button.setStyleSheet(stylesheet)
        except Exception as e:
            logger.error(f"Failed to update colored circle button: {e}", exc_info=True)

    def update_colored_circle_button(self, button: QPushButton, color: str) -> None:
        self._update_colored_circle_button(button, color)

    @staticmethod
    def _build_svg_pixmap(svg_data: str, color: QColor) -> QPixmap:
        renderer = QSvgRenderer(svg_data.encode("utf-8"))
        icon_size = QSize(TAMANHO_BOTAO, TAMANHO_BOTAO)

        pixmap = QPixmap(icon_size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)

        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), color)
        painter.end()

        return pixmap

    def _update_svg_button_color(
        self, button: QPushButton, svg_data: str, color: str
    ) -> None:
        try:
            pixmap = self._build_svg_pixmap(svg_data, QColor(color))
            button.setIcon(QIcon(pixmap))

        except Exception as e:
            logger.error(f"Failed to update SVG button color: {e}", exc_info=True)

    def _create_svg_button(
        self,
        svg_data: str,
        on_click: Optional[Callable[[], None]],
        tooltip: str,
    ) -> QPushButton:
        try:
            button = QPushButton()
            button.setToolTip(tooltip)
            button.setObjectName("acao")
            button.setFixedSize(TAMANHO_BOTAO, TAMANHO_BOTAO)

            pixmap = self._build_svg_pixmap(svg_data, QColor(self._cor_icone))
            button.setIcon(QIcon(pixmap))
            button.setIconSize(pixmap.size())

            if on_click:
                button.clicked.connect(on_click)
            return button

        except Exception as e:
            logger.error(f"Failed to create SVG button: {e}", exc_info=True)
            fallback_button = QPushButton("X")
            fallback_button.setFixedSize(TAMANHO_BOTAO, TAMANHO_BOTAO)
            if on_click:
                fallback_button.clicked.connect(on_click)
            return fallback_button

    @staticmethod
    def _glifo(tipo: str) -> QPixmap:
        """glifo na mão: a fonte do app muda, o desenho do win95 não."""
        pixmap = QPixmap(GLIFO, GLIFO)
        pixmap.fill(Qt.GlobalColor.transparent)
        pintor = QPainter(pixmap)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        preto = QColor("#000000")
        traco = QPen(preto, 1)
        pintor.setPen(traco)

        if tipo == "minimizar":
            pintor.fillRect(QRect(1, 6, 7, 2), preto)
        elif tipo == "maximizar":
            pintor.drawRect(QRect(1, 1, 6, 6))
            pintor.fillRect(QRect(2, 2, 5, 1), preto)
        elif tipo == "restaurar":
            # o recorte deixa a janela de trás aparecendo só nas bordas
            pintor.drawRect(QRect(0, 0, 6, 6))
            pintor.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_Clear
            )
            pintor.fillRect(QRect(1, 1, 8, 8), QColor(0, 0, 0, 0))
            pintor.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            pintor.setPen(traco)
            pintor.drawRect(QRect(1, 1, 7, 7))
            pintor.fillRect(QRect(2, 2, 6, 2), preto)
        elif tipo == "fechar":
            pintor.drawLine(QPoint(1, 1), QPoint(7, 7))
            pintor.drawLine(QPoint(7, 1), QPoint(1, 7))

        pintor.end()
        return pixmap

    def _create_control_button(
        self,
        glifo: str,
        on_click: Optional[Callable[[], None]],
        tooltip: str,
    ) -> QPushButton:
        button = QPushButton()
        button.setToolTip(tooltip)
        button.setFixedSize(TAMANHO_BOTAO, TAMANHO_BOTAO)
        button.setIcon(QIcon(self._glifo(glifo)))
        button.setIconSize(QSize(GLIFO, GLIFO))

        if on_click:
            button.clicked.connect(on_click)
        return button

    @staticmethod
    def _create_colored_circle_button(
        callback: Optional[Callable[[], None]],
        tooltip_text: str,
    ) -> QPushButton:
        button = QPushButton()
        button.setFixedSize(TAMANHO_BOTAO, TAMANHO_BOTAO)

        if tooltip_text:
            button.setToolTip(tooltip_text)

        if callback:
            button.clicked.connect(callback)

        return button

    def _atualiza_glifo_maximize(self) -> None:
        if not self.maximize_button:
            return
        tipo = "restaurar" if self.parent_window.isMaximized() else "maximizar"
        self.maximize_button.setIcon(QIcon(self._glifo(tipo)))

    def paintEvent(self, event: QPaintEvent) -> None:
        """gradiente win98 do accent, mesmo sem foco ou arrastando."""
        super().paintEvent(event)
        pintor = QPainter(self)
        gradiente = QLinearGradient(0, 0, max(1, self.width()), 0)
        gradiente.setColorAt(0.0, self._inicio)
        gradiente.setColorAt(1.0, self._fim)
        pintor.fillRect(self.rect(), gradiente)
        pintor.end()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.parent_window and event.type() == QEvent.Type.WindowStateChange:
            self._atualiza_glifo_maximize()
        return super().eventFilter(obj, event)

    def _minimize_window(self) -> None:
        self.parent_window.showMinimized()

    def _maximize_window(self) -> None:
        if self.parent_window.isMaximized():
            self.parent_window.showNormal()
        else:
            self.parent_window.showMaximized()

    def _close_window(self) -> None:
        self.parent_window.close()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            event.accept()
            return

        # perto da borda não arrasta: ali é a alça de resize da janela
        border_width = 6
        pos = event.pos()
        width = self.width()
        height = self.height()

        on_left_border = pos.x() <= border_width
        on_right_border = pos.x() >= width - border_width
        on_top_border = pos.y() <= border_width
        on_bottom_border = pos.y() >= height - border_width

        if on_left_border or on_right_border or on_top_border or on_bottom_border:
            event.accept()
            return

        window = self.window().windowHandle()
        if window is not None:
            window.startSystemMove()

        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._maximize_window()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

"""
The wired might actually be thought of as a highly advanced upper layer of
the real world. In other words, physical reality is nothing but an illusion,
a hologram of the information that flows to us through the wired.
This is because the body, physical motion, the activity of the human brain,
is merely a physical phenomenon, simply caused by synapses delivering
electrical impulses.
The physical body exists at a less evolved plane only to verify one's
existence in the universe.
"""
