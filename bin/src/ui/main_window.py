import atexit
import logging
import sys
import webbrowser
from typing import Optional

from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QIcon,
    QKeySequence,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QLabel,
    QMainWindow,
    QProgressBar,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
)

from components.custom_widgets import ScaledFontLabel
from managers.game_manager import GameManager
from managers.job_queue_manager import JobQueueManager
from managers.task_manager import TaskManager
from managers.ui_state_manager import UIStateManager
from ui.assets import DROP_SVG, DROP_SVG_HOVER, svg_para_pixmap
from ui.bottom_titlebar import BottomTitleBar, ClickableLabel
from ui.dialogs.credits import CreditsDialog
from ui.dialogs.fetchmanifest import FetchManifestDialog
from ui.dialogs.gamelibrary import GameLibraryDialog
from ui.dialogs.settings import SettingsDialog
from ui.dialogs.status import StatusDialog
from ui.frameless import Alcas
from ui.theme import cabecalho_secao, cor_secundaria, sulco, texto_sobre
from ui.window_defaults import ALTURA, GAP, LARGURA, RECUO_LATERAL
from utils.brand import DISPLAY_NAME
from utils.logger import open_log_directory, qt_log_handler
from utils.paths import Paths
from utils.settings import get_settings
from utils.version import app_version, release_url

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.alcas: Optional[Alcas] = None
        self.settings = None
        self.accent_color = None
        self.background_color = None
        self.task_manager = None
        self.ui_state = None
        self.job_queue = None
        self.game_manager = None
        self.exit_shortcut = None
        self.central_widget = None
        self.layout = None
        self.titlebar_position = None
        self.bottom_titlebar = None
        self.main_container = None
        self.main_layout = None
        self.drop_zone_container = None
        self.drop_zone_layout = None
        self.drop_text_label = None
        self.drop_icon = None
        self.drop_hint = None
        self.lado_icone_drop = 0
        self.drop_destacado = False
        self.texto_drop_antes = None
        self.progress_container = None
        self.progress_layout = None
        self.progress_bar = None
        self.speed_label = None
        self.bottom_widget = None
        self.bottom_layout = None
        self.log_output = None
        self.status_widget = None
        self.status_texto = None
        self.status_versao = None

        self._setup_window_properties()
        self._initialize_managers()
        self._setup_ui()
        self.alcas = Alcas(self)
        if self.ui_state:
            self.ui_state.apply_style_settings()
        self._setup_exit_shortcut()

    def _setup_window_properties(self) -> None:
        """Configure basic window properties."""
        self.setWindowTitle(DISPLAY_NAME)
        flags = Qt.WindowType.FramelessWindowHint
        if sys.platform == "linux":
            # no i3 só janela de diálogo flutua, senão ela abre tiled e come
            # a workspace inteira
            flags |= Qt.WindowType.Dialog
        self.setWindowFlags(flags)
        self.setMinimumSize(LARGURA, ALTURA)
        self.setGeometry(100, 100, LARGURA, ALTURA)

        icon_path = Paths.resource("logo/icon.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        else:
            logger.warning(f"Could not find window icon at: {icon_path}")

        if sys.platform == "win32":
            MainWindow._setup_windows_taskbar()

    def _setup_exit_shortcut(self) -> None:
        """Setup Ctrl+Q shortcut to exit the application."""
        self.exit_shortcut = QShortcut(QKeySequence("Ctrl+Q"), self)
        self.exit_shortcut.activated.connect(self.close)
        # atalhos internos
        self.sc_lupa = QShortcut(QKeySequence("/"), self)
        self.sc_lupa.activated.connect(self.open_fetch_dialog)
        self.sc_biblioteca = QShortcut(QKeySequence("b"), self)
        self.sc_biblioteca.activated.connect(self.open_game_library)
        self.sc_config = QShortcut(QKeySequence("c"), self)
        self.sc_config.activated.connect(self.open_settings)
        self.sc_status = QShortcut(QKeySequence("s"), self)
        self.sc_status.activated.connect(self.open_status_dialog)
        self.sc_drop_z = QShortcut(QKeySequence("z"), self)
        self.sc_drop_z.activated.connect(self._duplo_clique_drop)
        logger.info("Atalhos registrados")

    @staticmethod
    def _setup_windows_taskbar() -> None:
        """Windows-specific taskbar configuration."""
        try:
            import ctypes

            app_id = "god.is.in.the.wired.accela"
            # noinspection PyUnresolvedReferences
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        except (ImportError, AttributeError) as e:
            logger.warning(f"Could not set AppUserModelID: {e}")

    def _initialize_managers(self) -> None:
        """Initialize all manager classes."""
        self.settings = get_settings()

        self.accent_color = self.settings.value("accent_color", "#000080")
        self.background_color = self.settings.value("background_color", "#c0c0c0")

        self.task_manager = TaskManager(self)
        self.ui_state = UIStateManager(self)
        self.job_queue = JobQueueManager(self)
        self.game_manager = GameManager(self)

        logger.info("Starting initial game library scan...")
        self.game_manager.scan_steam_libraries_async()

    def _setup_ui(self) -> None:
        """Setup the main UI components."""
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        self.titlebar_position = self.settings.value(
            "titlebar_position", "bottom", type=str
        )

        if self.titlebar_position == "top":
            self.bottom_titlebar = BottomTitleBar(self, marca_central=True)
            self.layout.addWidget(self.bottom_titlebar)

        self._create_main_content()
        self._create_bottom_section()

        if self.titlebar_position != "top":
            self.bottom_titlebar = BottomTitleBar(self, marca_central=True)
            self.layout.addWidget(self.bottom_titlebar)

        # sempre a última: a versão fica colada no chão da janela
        self._cria_barra_status()
        self.setAcceptDrops(True)

    def resizeEvent(self, event) -> None:
        """Update resize handle positions when window is resized."""
        super().resizeEvent(event)
        if self.alcas:
            self.alcas.atualizar()
        self._ajusta_icone_drop()
        if getattr(self, "log_output", None):
            # o layout da seção de baixo ainda não rodou, refaz no próximo turno
            self._agenda_ajuste_log()

    def _agenda_ajuste_log(self) -> None:
        """Reencaixa o log depois que o layout terminar de calcular os tamanhos."""
        QTimer.singleShot(0, self._ajusta_altura_log)

    def _create_main_content(self) -> None:
        """Create the main content area with drop zone."""
        self.main_container = QWidget()
        self.main_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.layout.addWidget(self.main_container, 3)

        self.main_layout = QVBoxLayout(self.main_container)
        # o recuo lateral deixa a moldura do campo caber dentro da janela
        # e o topo respira o mesmo que a borda de baixo da janela
        self.main_layout.setContentsMargins(
            RECUO_LATERAL, GAP, RECUO_LATERAL, 0
        )
        self.main_layout.setSpacing(0)

        self._create_drop_zone()
        self._create_progress_section()

    def _create_drop_zone(self) -> None:
        """campo win95 onde o zip entra arrastando ou no duplo clique."""
        self.drop_zone_container = QWidget()
        self.drop_zone_container.setObjectName("zona_drop")
        self.drop_zone_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.drop_zone_container.setCursor(Qt.CursorShape.PointingHandCursor)
        self.drop_zone_container.installEventFilter(self)
        self.drop_zone_layout = QVBoxLayout(self.drop_zone_container)
        self.drop_zone_layout.setContentsMargins(16, 16, 16, 16)
        self.drop_zone_layout.setSpacing(0)

        # o respiro de cima e de baixo centraliza o bloco sozinho
        self.drop_zone_layout.addStretch(1)

        self.drop_text_label = ScaledFontLabel(
            "Arraste o ZIP aqui", escala_por="largura"
        )
        self.drop_text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_text_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.drop_text_label.setMinimumHeight(32)
        self.drop_zone_layout.addWidget(self.drop_text_label)
        self.drop_zone_layout.addSpacing(12)

        self.drop_icon = QLabel()
        self.drop_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_zone_layout.addWidget(
            self.drop_icon, 0, Qt.AlignmentFlag.AlignCenter
        )
        self.drop_zone_layout.addSpacing(6)

        # QLabel comum: o ScaledFontLabel mexe no tamanho da fonte sozinho
        self.drop_hint = QLabel("ou dê 2 cliques para escolher o zip")
        self.drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_hint.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.drop_zone_layout.addWidget(
            self.drop_hint, 0, Qt.AlignmentFlag.AlignCenter
        )

        self.drop_zone_layout.addStretch(1)
        self._ajusta_icone_drop()
        self._atualiza_zona_drop()
        self.main_layout.addWidget(self.drop_zone_container, 10)

    def _ajusta_icone_drop(self) -> None:
        """ícone cresce com a janela: 32 no piso, 96 no teto."""
        if self.drop_icon is None:
            return
        lado = max(32, min(96, self.width() // 8))
        if lado == self.lado_icone_drop:
            return
        self.lado_icone_drop = lado
        self.drop_icon.setFixedSize(lado, lado)
        self._pinta_icone_drop()

    def _pinta_icone_drop(self) -> None:
        """branco no arraste (o campo vira seleção), acento no repouso."""
        if self.drop_icon is None or not self.lado_icone_drop:
            return
        svg = DROP_SVG_HOVER if self.drop_destacado else DROP_SVG
        cor = (
            texto_sobre(self.accent_color)
            if self.drop_destacado
            else self.accent_color
        )
        self.drop_icon.setPixmap(
            svg_para_pixmap(svg, QColor(cor), self.lado_icone_drop)
        )

    def _destaque_drop(self, ativo: bool) -> None:
        """destaque enquanto o zip está arrastando por cima."""
        if self.drop_text_label is None:
            return
        if ativo:
            if self.drop_destacado:
                return
            self.drop_destacado = True
            self.texto_drop_antes = self.drop_text_label.text()
            self.drop_text_label.setText("Solte agora")
        else:
            if not self.drop_destacado:
                return
            self.drop_destacado = False
            if self.texto_drop_antes:
                self.drop_text_label.setText(self.texto_drop_antes)
            self.texto_drop_antes = None
        self._atualiza_zona_drop()

    def _estilo_zona_drop(self) -> None:
        """moldura rebaixada do win95; no arraste o campo vira seleção."""
        fundo = QColor(self.background_color or "#c0c0c0")
        # com seletor: declaração solta escorre pros filhos e vira caixa em volta deles
        if self.drop_destacado:
            sel = QColor(self.accent_color).name()
            self.drop_zone_container.setStyleSheet(
                f"QWidget#zona_drop {{"
                f"background-color: {sel};"
                f"border-top: 2px solid {sel};"
                f"border-left: 2px solid {sel};"
                f"border-bottom: 2px solid {sel};"
                f"border-right: 2px solid {sel};"
                f"}}"
            )
            return
        escuro = sulco(fundo)
        self.drop_zone_container.setStyleSheet(
            f"QWidget#zona_drop {{"
            f"background-color: {fundo.name()};"
            f"border-top: 2px solid {escuro};"
            f"border-left: 2px solid {escuro};"
            f"border-bottom: 2px solid #FFFFFF;"
            f"border-right: 2px solid #FFFFFF;"
            f"}}"
        )

    def _pinta_textos_drop(self) -> None:
        """texto e apoio acompanham o estado do campo."""
        if self.drop_text_label is None:
            return
        if self.drop_destacado:
            cor_texto = texto_sobre(self.accent_color)
            cor_apoio = cor_texto
        else:
            cor_texto = self.accent_color
            cor_apoio = cor_secundaria(self.background_color or "#c0c0c0")
        self.drop_text_label.setStyleSheet(f"color: {cor_texto};")
        if self.drop_hint is not None:
            self.drop_hint.setStyleSheet(
                f"color: {cor_apoio}; font-size: 11px; background: transparent;"
            )

    def _atualiza_zona_drop(self) -> None:
        """campo, textos e ícone juntos: cor nova ou estado de arraste."""
        if self.drop_zone_container is None:
            return
        self._estilo_zona_drop()
        self._pinta_textos_drop()
        self._pinta_icone_drop()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.drop_zone_container and event.type() == QEvent.Type.MouseButtonDblClick:
            if event.button() == Qt.MouseButton.LeftButton:
                self._escolhe_zips()
                return True
        if obj is getattr(self, "_logs_header", None) and event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton:
                open_log_directory()
                return True
        return super().eventFilter(obj, event)

    def _escolhe_zips(self) -> None:
        """2 cliques no campo: quem prefere mouse escolhe os zips na mão."""
        caminhos, _ = QFileDialog.getOpenFileNames(
            self, "Escolher ZIP", "", "Arquivos ZIP (*.zip)"
        )
        if not caminhos:
            return
        logger.info(f"Added {len(caminhos)} file(s) to the queue via file dialog.")
        for caminho in caminhos:
            self.job_queue.add_job(caminho)

    def _create_progress_section(self) -> None:
        """Create the progress bar and speed label."""
        self.progress_container = QWidget()
        self.progress_layout = QVBoxLayout(self.progress_container)
        self.progress_layout.setContentsMargins(0, 5, 0, 5)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self._update_progress_bar_style()
        self.progress_layout.addWidget(self.progress_bar)

        self.speed_label = QLabel("")
        self.speed_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.speed_label.setVisible(False)
        self.progress_layout.addWidget(self.speed_label)

        self.main_layout.addWidget(self.progress_container, 1)

    def _create_bottom_section(self) -> None:
        """Create the bottom section with queue and logs."""
        self.bottom_widget = QWidget()
        # vertical: o espaço que sobra fica em cima, log e fila descem juntos
        self.bottom_layout = QVBoxLayout(self.bottom_widget)
        self.bottom_layout.setContentsMargins(
            RECUO_LATERAL, GAP, RECUO_LATERAL, GAP
        )
        self.bottom_layout.setSpacing(6)
        self.bottom_layout.addStretch(1)

        # cabeçalho do log: título e linha, o texto começa com respiro embaixo
        logs_header = QLabel("Logs")
        logs_header.setStyleSheet(cabecalho_secao(self.accent_color))
        logs_header.setToolTip("Ver logs")
        logs_header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._logs_header = logs_header
        logs_header.installEventFilter(self)
        self.bottom_layout.addWidget(logs_header)

        logs_line = QFrame()
        logs_line.setFixedHeight(1)
        logs_line.setStyleSheet(
            f"background-color: {self.accent_color}; border: none;"
        )
        self.bottom_layout.addWidget(logs_line)

        # respiro maior entre a linha e a primeira linha do log
        self.bottom_layout.addSpacing(8)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        # sem margem interna: o texto começa no mesmo recuo dos títulos
        self.log_output.document().setDocumentMargin(0)
        # altura colada no texto, senão sobra buraco entre o log e a fila
        self.log_output.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.log_output.textChanged.connect(self._ajusta_altura_log)
        # o leitor saindo do fim desliga o acompanhamento automático
        self._log_seguindo = False
        self.log_output.verticalScrollBar().valueChanged.connect(
            self._log_leitor_saiu_do_fim
        )
        qt_log_handler.new_record.connect(self.log_output.append)
        self.bottom_layout.addWidget(self.log_output)

        self.ui_state.setup_queue_panel()
        # a fila absorve o resto (leva 2 porque o cabeçalho dela pesa mais)
        self.bottom_layout.addWidget(self.ui_state.queue_widget, 2)

        self.layout.addWidget(self.bottom_widget, 1)
        self.ui_state.queue_widget.setVisible(False)
        self._ajusta_altura_log()

    def _ajusta_altura_log(self) -> None:
        """A altura do log segue o texto, o espaço que sobra fica em cima dele."""
        doc = self.log_output.document()
        altura = doc.lineCount() * self.log_output.fontMetrics().lineSpacing()
        altura += 2 * doc.documentMargin() + 2

        disponivel = self.bottom_widget.height()
        if disponivel > 0:
            # teto duplo: não passa de um terço da janela (senão a seção de
            # baixo empurra a área principal) e não come o espaço da fila
            reserva = 55
            fila = getattr(self.ui_state, "queue_widget", None)
            if fila is not None and fila.isVisible():
                reserva += 165
            teto = int(self.height() * 0.30)
            altura = min(altura, max(48, min(teto, disponivel - reserva)))

        altura = int(altura)
        if self.log_output.height() != altura:
            self.log_output.setFixedHeight(altura)

        # acompanha o fim: durante um job é sempre, senão segue quem já seguia
        barra = self.log_output.verticalScrollBar()
        processando = getattr(self.task_manager, "is_processing", False)
        no_fim = barra.maximum() - barra.value() < 6
        if processando or self._log_seguindo or no_fim:
            self._log_seguindo = True
            barra.setValue(barra.maximum())
        else:
            self._log_seguindo = False

    def _log_leitor_saiu_do_fim(self, valor: int) -> None:
        """rolar para longe do fim desliga o acompanhamento automático."""
        barra = self.log_output.verticalScrollBar()
        if self._log_seguindo and barra.maximum() - valor >= 6:
            self._log_seguindo = False

    def _cria_barra_status(self) -> None:
        """painel rebaixado no chão da janela: estado à esquerda, versão à direita."""
        self.status_widget = QWidget()
        self.status_widget.setObjectName("barra_status")
        barra = QHBoxLayout(self.status_widget)
        barra.setContentsMargins(6, 2, 6, 2)
        barra.setSpacing(8)

        # sem texto: só ação entra aqui (o campo dá a instrução de repouso)
        self.status_texto = QLabel("")
        barra.addWidget(self.status_texto)
        barra.addStretch(1)

        self.status_versao = ClickableLabel(app_version, self, self._abre_release)
        self.status_versao.setToolTip("Ver release no GitHub")
        barra.addWidget(self.status_versao)

        self.status_widget.setFixedHeight(20)
        self.layout.addWidget(self.status_widget)
        self.update_barra_status_style()

    def update_barra_status_style(self) -> None:
        fundo = QColor(self.background_color or "#c0c0c0")
        self.status_widget.setStyleSheet(
            f"QWidget#barra_status {{"
            f" background-color: {fundo.name()};"
            f" border-top: 1px solid {sulco(fundo)};"
            f"}}"
            f"QWidget#barra_status QLabel {{"
            f" color: {cor_secundaria(fundo)};"
            f" background: transparent;"
            f" font-size: 11px;"
            f"}}"
        )

    def _mostra_estado(self, texto: str) -> None:
        """ação em andamento: mesma frase no campo e na barra de status."""
        self.drop_text_label.setText(texto)
        if self.status_texto is not None:
            self.status_texto.setText(texto)

    def limpa_estado(self) -> None:
        """repouso: o campo instrui e a barra de status fica quieta."""
        if self.status_texto is not None:
            self.status_texto.setText("")

    def update_progress_bar_style(self) -> None:
        self._update_progress_bar_style()

    def _update_progress_bar_style(self) -> None:
        """Update progress bar styling."""
        self.progress_bar.setStyleSheet(
            f"""
            QProgressBar {{
                max-height: 10px;
                border: 1px solid {self.accent_color};
                border-radius: 5px;
                text-align: center;
                color: #FFFFFF;
                background-color: {sulco(self.background_color or "#c0c0c0")};
            }}
            QProgressBar::chunk {{
                background-color: {self.accent_color};
                border-radius: 5px;
            }}
        """
        )

    def open_settings(self) -> None:
        dialog = SettingsDialog(self)
        dialog.exec()

    def open_fetch_dialog(self) -> None:
        self.ui_state.fetch_dialog = FetchManifestDialog(self)
        self.ui_state.fetch_dialog.exec()
        self.ui_state.fetch_dialog = None

    def open_game_library(self) -> None:
        dialog = GameLibraryDialog(self)
        dialog.exec()

    def open_status_dialog(self) -> None:
        dialog = StatusDialog(self)
        dialog.exec()

    def open_credits_dialog(self) -> None:
        dialog = CreditsDialog(self)
        dialog.exec()

    def _abre_release(self) -> None:
        webbrowser.open(release_url)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if not event.mimeData().hasUrls():
            return

        urls = event.mimeData().urls()
        has_zip = any(
            url.isLocalFile() and url.toLocalFile().lower().endswith(".zip")
            for url in urls
        )

        if has_zip:
            self._destaque_drop(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._destaque_drop(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._destaque_drop(False)
        urls = event.mimeData().urls()
        new_jobs = [
            url.toLocalFile()
            for url in urls
            if url.isLocalFile() and url.toLocalFile().lower().endswith(".zip")
        ]

        if not new_jobs:
            return

        logger.info(f"Added {len(new_jobs)} file(s) to the queue via drag-drop.")
        for job_path in new_jobs:
            self.job_queue.add_job(job_path)

    def closeEvent(self, event) -> None:
        """Handle application shutdown."""
        try:
            MainWindow._cleanup_logging()
            self.task_manager.cleanup()
            self.job_queue.clear()
            self.game_manager.cleanup()
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

        super().closeEvent(event)

    def reposition_titlebar(self, position: str) -> None:
        """Dynamically reposition the titlebar without restart."""
        if not hasattr(self, "bottom_titlebar") or not self.bottom_titlebar:
            return

        self.layout.removeWidget(self.bottom_titlebar)
        self.bottom_titlebar.setParent(None)

        if position == "top":
            self.layout.insertWidget(0, self.bottom_titlebar)
        else:
            self.layout.addWidget(self.bottom_titlebar)

        self.titlebar_position = position
        logger.info(f"Titlebar repositioned to: {position}")

    @staticmethod
    def _cleanup_logging() -> None:
        """Clean up logging system."""
        try:
            atexit.unregister(logging.shutdown)
            logging.getLogger().removeHandler(qt_log_handler)
            qt_log_handler.close()
            logger.info("QtLogHandler removed and atexit hook unregistered.")
            logging.shutdown()
        except Exception as e:
            print(f"Error during custom logger shutdown: {e}")

    def _duplo_clique_drop(self) -> None:
        """Simula duplo clique na zona de drop para abrir seleção de zips."""
        self._escolhe_zips()
