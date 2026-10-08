import logging
import math
import os
import platform
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QIntValidator, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# --- Import Handling with Fallbacks ---
try:
    from core import morrenus_api
except ImportError:
    morrenus_api = None

try:
    from core.steam_helpers import slssteam_api_send
except ImportError:

    def slssteam_api_send(_cmd):
        return None


try:
    from utils.helpers import get_base_path
except ImportError:

    def get_base_path():
        return Path(".")


try:
    from managers.image_fetcher import ImageFetcher
except ImportError:
    try:
        from utils.image_fetcher import ImageFetcher
    except ImportError:
        ImageFetcher = None

try:
    from managers.db_manager import DatabaseManager
except ImportError:
    DatabaseManager = None

try:
    from utils.yaml_config_manager import (
        add_fake_app_id,
        get_fake_app_ids,
        get_fake_appid,
        get_user_config_path,
        is_slssteam_config_management_enabled,
        is_slssteam_mode_enabled,
        remove_fake_app_id,
    )
except ImportError:
    # Dummy fallbacks to prevent crash if module is missing
    def add_fake_app_id(*_args, **_kwargs):
        return False

    def get_fake_app_ids(*_args, **_kwargs):
        return []

    def get_fake_appid(*_args, **_kwargs):
        return None

    def get_user_config_path():
        return Path("config.yaml")

    def is_slssteam_config_management_enabled():
        return False

    def is_slssteam_mode_enabled():
        return False

    def remove_fake_app_id(*_args, **_kwargs):
        return False


from ui.dialogs.dialog_helpers import FiltroVimListas, aplicar_barra_titulo, pergunta_sim_nao
from ui.theme import claro, cor_secundaria, cores_status, sulco
from ui.window_defaults import aplicar
from utils.brand import DISPLAY_NAME

logger = logging.getLogger(__name__)


def format_game_display_name(game_data: dict) -> str:
    """nome de exibicao do jogo, incluindo o marcador do navi-br."""
    name = game_data.get("game_name", "Desconhecido")
    if game_data.get("is_accela_install"):
        return f"{name} [{DISPLAY_NAME}]"
    return name


class GameItemWidget(QWidget):
    """
    Custom widget for displaying a game item in the library list.
    Layout: [ Image ] [ Name/Size/Status ]
    """

    def __init__(
        self, game_data: dict, size_str: str, accent_color: str, background_color: str
    ):
        super().__init__()
        self.game_data = game_data
        self.accent_color = accent_color
        self.background_color = background_color
        self._init_ui(size_str)

    def _init_ui(self, size_str: str) -> None:
        """Initialize the UI components."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)

        # --- Image Section ---
        self.image_label = QLabel()
        self.image_label.setFixedSize(230, 108)  # Standard Steam Header Ratio
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        name = self.game_data.get("game_name", "Desconhecido")
        display_name = format_game_display_name(self.game_data)
        self.image_label.setText(name[:2].upper())

        self.image_label.setStyleSheet(
            f"background-color: {self.background_color}; "
            f"color: {self.accent_color}; "
            f"border-radius: 4px; "
        )
        layout.addWidget(self.image_label)

        # --- Info Section (Vertical) ---
        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(0, 5, 0, 5)
        info_layout.setSpacing(2)

        # Game name
        name_label = QLabel(display_name)
        name_label.setStyleSheet(
            f"font-weight: bold; font-size: 14px; color: {self.accent_color};"
        )
        name_label.setWordWrap(True)
        info_layout.addWidget(name_label)

        # Size
        size_label = QLabel(f"Tamanho: {size_str}")
        size_label.setStyleSheet(f"color: {self.accent_color};")
        info_layout.addWidget(size_label)

        # Update status
        self.status_label = QLabel()
        self.apply_status(self.game_data.get("update_status", "cannot_determine"))
        info_layout.addWidget(self.status_label)

        info_layout.addStretch()
        layout.addLayout(info_layout)

    def apply_status(self, update_status: str) -> None:
        """Sets the status label text and color."""
        status = cores_status(self.background_color)
        status_map = {
            "update_available": ("Nova versão disponível", self.accent_color),
            "up_to_date": ("Atualizado", status["ok"]),
            "checking": ("Verificando atualizações...", status["andamento"]),
        }
        text, color = status_map.get(
            update_status,
            (
                "Não foi possível verificar atualizações",
                cor_secundaria(self.background_color),
            ),
        )
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {color}; font-style: italic;")

    def set_image(self, pixmap: QPixmap) -> None:
        """Sets the image on the label, scaling it nicely."""
        if not pixmap or pixmap.isNull():
            return

        scaled = pixmap.scaled(
            self.image_label.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)

    def sizeHint(self) -> QSize:
        """Return size hint that matches the desired row height."""
        return QSize(400, 118)


class _DetalhesDialog(QDialog):
    """detalhes do jogo com navegação vim-like (j/k, h/l nas abas)."""

    def keyPressEvent(self, event):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import (
            QCheckBox,
            QLineEdit,
            QRadioButton,
            QPushButton,
            QTabWidget,
            QTextEdit,
        )

        k = event.key()
        foco = self.focusWidget()

        if k == Qt.Key.Key_Escape and isinstance(foco, (QLineEdit, QTextEdit)):
            # dentro do input esc solta o foco em vez de fechar o diálogo
            self._sai_do_input(foco)
            return

        if k in (Qt.Key.Key_H, Qt.Key.Key_Left, Qt.Key.Key_L, Qt.Key.Key_Right):
            tabs = getattr(self, 'tabs', None)
            if isinstance(tabs, QTabWidget):
                idx = tabs.currentIndex()
                if k in (Qt.Key.Key_H, Qt.Key.Key_Left):
                    tabs.setCurrentIndex(max(0, idx - 1))
                else:
                    tabs.setCurrentIndex(min(tabs.count() - 1, idx + 1))
                return

        if k in (Qt.Key.Key_J, Qt.Key.Key_Down):
            self.focusNextChild()
            return
        if k in (Qt.Key.Key_K, Qt.Key.Key_Up):
            self.focusPreviousChild()
            return

        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if isinstance(foco, (QCheckBox, QRadioButton)):
                foco.setChecked(not foco.isChecked())
                return
            if isinstance(foco, QPushButton):
                foco.click()
                return
            # foco comum (aba, label): enter não faz nada
            return
        super().keyPressEvent(event)

    def _sai_do_input(self, input_focado):
        """foca o próximo widget utilizável fora do campo de texto."""
        w = input_focado.nextInFocusChain()
        while w is not input_focado:
            if (
                w.isVisible()
                and w.isEnabled()
                and not isinstance(w, (QLineEdit, QTextEdit))
                and w is not self
            ):
                w.setFocus()
                return
            w = w.nextInFocusChain()


class GameLibraryDialog(QDialog):
    """Dialog to display and manage the game library."""

    _mtime_cache: dict[str, float] = {}
    manifest_download_complete = pyqtSignal(str, str, dict)  # fpath, error, game_data
    uninstall_complete = pyqtSignal(bool, str)  # success, error_message

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.game_manager = getattr(main_window, "game_manager", None)
        self.settings = getattr(main_window, "settings", None)
        self.executor = ThreadPoolExecutor(max_workers=4)

        # Load theme colors
        self.accent_color = "#000080"
        self.background_color = "#c0c0c0"

        if self.settings:
            self.accent_color = self.settings.value("accent_color", "#000080")
            self.background_color = self.settings.value("background_color", "#c0c0c0")

        # State tracking
        self._active_fetchers = {}
        self._image_cache = {}
        self._appid_to_item = {}
        self._pending_update_checks = 0
        self._dialog_open = False
        self._refreshing = False
        self._closing = False
        self._scanning = False
        self._checking_updates = False
        self._download_progress_dialog = None
        self._uninstall_progress_dialog = None
        self._details_dialog = None
        self._loading_games = False
        self._initial_refresh_started = False
        self._list_refresh_token = 0
        self._list_load_batch_size = 12
        self._pending_games = []
        self._pending_total_size = 0
        self._pending_accela_count = 0
        self._loaded_games_count = 0

        # Search
        self._search_text = ""
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._refresh_game_list)

        self._setup_window()
        self._setup_ui()
        self._connect_signals()
        aplicar_barra_titulo(self)

    def _setup_window(self) -> None:
        """Configure main window properties and styles."""
        self.setWindowTitle("Biblioteca de jogos")
        aplicar(self, self.main_window)

        # a folha foi escrita para o tema escuro: no fundo claro os cinzos
        # fixos viram sujeira, então tudo deriva do par fundo/accent
        fundo = QColor(self.background_color)
        fundo_claro = claro(fundo)
        linha_lista = fundo.darker(135).name() if fundo_claro else "#333333"
        selecao = self.accent_color if fundo_claro else "#1A1A1A"
        selecao_txt = self.background_color if fundo_claro else self.accent_color
        trilha = sulco(self.background_color)

        self.setStyleSheet(
            f"""
            QDialog {{ background-color: {self.background_color}; color: {self.accent_color}; }}
            
            QListWidget {{ 
                background-color: {self.background_color}; 
                border: none; 
                border-radius: 4px; 
            }}
            QListWidget::item {{ 
                border-bottom: 1px solid {linha_lista}; 
                color: {self.accent_color};
            }}
            QListWidget::item:selected {{ 
                background-color: {selecao}; 
                color: {selecao_txt};
            }}
            
            QLabel {{ color: {self.accent_color}; }}
            
            QComboBox {{ 
                background-color: {self.background_color}; 
                color: {self.accent_color}; 
                padding: 4px; 
                border: none; 
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background-color: {self.background_color};
                color: {self.accent_color};
                selection-background-color: {selecao};
                selection-color: {selecao_txt};
                border: none;
            }}
            QProgressBar {{
                background-color: {trilha};
                border: 1px solid {self.accent_color};
                border-radius: 4px;
                color: #FFFFFF;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background-color: {self.accent_color};
                border-radius: 3px;
            }}
            QCheckBox:focus, QRadioButton:focus, QPushButton:focus {{
                outline: 2px solid {self.accent_color};
                outline-offset: 1px;
            }}
        """
        )

    def _setup_ui(self) -> None:
        """Create and arrange UI elements."""
        layout = QVBoxLayout(self)

        # --- Top Bar ---
        top_layout = QHBoxLayout()

        self.scan_button = QPushButton("Escanear bibliotecas")
        self.scan_button.clicked.connect(self._scan_for_games)
        self.scan_button.setMinimumHeight(34)
        top_layout.addWidget(self.scan_button)

        # Search bar
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Buscar jogos...")
        self.search_edit.textChanged.connect(self._on_search_text_changed)
        self.search_edit.setMinimumHeight(34)
        self.search_edit.setStyleSheet("QLineEdit { padding: 6px 10px; }")
        top_layout.addWidget(self.search_edit, 1)

        layout.addLayout(top_layout)

        # --- Sort --- linha própria senão a de cima aperta
        sort_layout = QHBoxLayout()

        sort_label = QLabel("Ordenar por:")
        sort_layout.addWidget(sort_label)

        self.sort_combo = QComboBox()
        self.sort_combo.addItem("Instalados recentemente", "recently_installed")
        self.sort_combo.addItem("Nome (A-Z)", "name_asc")
        self.sort_combo.addItem("Nome (Z-A)", "name_desc")
        self.sort_combo.addItem("Tamanho (menor)", "size_asc")
        self.sort_combo.addItem("Tamanho (maior)", "size_desc")
        self.sort_combo.addItem("AppID", "appid")

        if self.settings:
            saved_sort = self.settings.value("library_sort_option", "name_asc")
            index = self.sort_combo.findData(saved_sort)
            if index >= 0:
                self.sort_combo.setCurrentIndex(index)

        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        sort_layout.addWidget(self.sort_combo)
        sort_layout.addStretch()

        layout.addLayout(sort_layout)

        # --- Loading State ---
        self.loading_widget = QWidget()
        loading_layout = QVBoxLayout(self.loading_widget)
        loading_layout.setContentsMargins(0, 0, 0, 6)
        loading_layout.setSpacing(6)

        self.loading_label = QLabel("Carregando biblioteca de jogos...")
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading_layout.addWidget(self.loading_label)

        self.loading_bar = QProgressBar()
        self.loading_bar.setMinimum(0)
        self.loading_bar.setTextVisible(True)
        loading_layout.addWidget(self.loading_bar)

        layout.addWidget(self.loading_widget)

        # --- Games List ---
        self.games_list = QListWidget()
        self.games_list.setSpacing(2)
        self.games_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.games_list.installEventFilter(
            FiltroVimListas(self.games_list, ao_topo=self._volta_busca)
        )
        layout.addWidget(self.games_list)

        # --- Footer ---
        footer_layout = QHBoxLayout()
        self.info_label = QLabel("Encontrados 0 jogos Steam instalados")
        self.info_label.setWordWrap(True)
        footer_layout.addWidget(self.info_label, 1)

        layout.addLayout(footer_layout)

    def _connect_signals(self) -> None:
        """Connect GameManager and local signals."""
        if not self.game_manager:
            return

        self.game_manager.scan_complete.connect(
            self._on_scan_complete, Qt.ConnectionType.UniqueConnection
        )
        self.game_manager.library_updated.connect(
            self._refresh_game_list, Qt.ConnectionType.UniqueConnection
        )
        self.game_manager.game_update_status_changed.connect(
            self._on_game_update_status_changed, Qt.ConnectionType.UniqueConnection
        )

        self.games_list.itemClicked.connect(self._on_item_selected)
        self.manifest_download_complete.connect(self._on_manifest_download_complete)
        self.uninstall_complete.connect(self._on_uninstall_complete)

    def _ensure_executor(self) -> None:
        """Recreate the background executor when reusing the dialog."""
        if self.executor is None:
            self.executor = ThreadPoolExecutor(max_workers=4)

    def showEvent(self, event) -> None:
        """Defer the first list build until the dialog is visible."""
        super().showEvent(event)
        self._closing = False
        self._ensure_executor()

        if not self._initial_refresh_started:
            self._initial_refresh_started = True
            QTimer.singleShot(0, self._refresh_game_list)

    # --- Scanning & Updates ---

    def _scan_for_games(self) -> None:
        if self._scanning or not self.game_manager:
            return

        self._scanning = True
        self.scan_button.setEnabled(False)
        self.scan_button.setText("Escaneando...")
        self.info_label.setText("Escaneando bibliotecas Steam...")
        self._refreshing = True
        self.games_list.clear()

        self.game_manager.scan_steam_libraries_async()

    def _on_scan_complete(self, count: int) -> None:
        self.scan_button.setEnabled(True)
        self.scan_button.setText("Escanear bibliotecas")

        if count > 0:
            self._checking_updates = True
            QTimer.singleShot(100, self._check_if_updates_complete)
            return

        self.info_label.setText(
            f"Escaneamento completo: {count} jogo(s) Steam instalado(s) encontrado(s)."
        )
        self._scanning = False
        # Force refresh to clear "Scanning..." state if 0 found
        self._refresh_game_list()

    def _check_if_updates_complete(self) -> None:
        if not self._checking_updates:
            return

        # Check if any items are still in "checking" state
        checking = False
        for i in range(self.games_list.count()):
            item = self.games_list.item(i)
            game_data = item.data(Qt.ItemDataRole.UserRole)
            if game_data and game_data.get("update_status") == "checking":
                checking = True
                break

        if checking:
            QTimer.singleShot(500, self._check_if_updates_complete)
            return

        self._checking_updates = False
        self._scanning = False
        self._refresh_game_list()

    def _on_game_update_status_changed(self, appid: str, update_status: str) -> None:
        if self._closing or not self.isVisible():
            return

        # Find matching item
        item = None
        for i in range(self.games_list.count()):
            it = self.games_list.item(i)
            game_data = it.data(Qt.ItemDataRole.UserRole)
            if game_data and game_data.get("appid") == appid:
                item = it
                break

        if not item:
            return

        self._update_item_status(item, appid, update_status)

    def _update_item_status(
        self, item: QListWidgetItem, appid: str, update_status: str
    ) -> None:
        """Update specific item status logic extracted to flatten logic."""
        game_data = item.data(Qt.ItemDataRole.UserRole)
        game_data["update_status"] = update_status
        item.setData(Qt.ItemDataRole.UserRole, game_data)

        widget = self.games_list.itemWidget(item)
        if not isinstance(widget, GameItemWidget):
            return

        # Update label in-place, no widget rebuild needed
        widget.apply_status(update_status)

        # Re-apply cached image if available
        if appid in self._image_cache:
            pixmap = QPixmap()
            pixmap.loadFromData(self._image_cache[appid])
            widget.set_image(pixmap)

    # --- List Management ---

    def _on_search_text_changed(self, text: str) -> None:
        self._search_text = text.strip().lower()
        self._search_timer.start(300)

    def _on_sort_changed(self) -> None:
        if self.settings:
            self.settings.setValue("library_sort_option", self.sort_combo.currentData())
        self._refresh_game_list()

    @staticmethod
    def _get_sort_key(game, sort_option):
        """Helper for sorting keys."""
        if sort_option in ("name_asc", "name_desc"):
            return game.get("game_name", "").lower()
        if sort_option in ("size_asc", "size_desc"):
            return game.get("size_on_disk", 0)
        if sort_option == "appid":
            try:
                return int(game.get("appid", 0))
            except (ValueError, TypeError):
                return 0
        if sort_option == "recently_installed":
            path = (
                game.get("accela_marker_path")
                or game.get("depot_downloader_path")
                or game.get("appmanifest_path")
                or game.get("install_path", "")
            )
            if path and path not in GameLibraryDialog._mtime_cache:
                GameLibraryDialog._mtime_cache[path] = (
                    os.path.getmtime(path) if os.path.exists(path) else 0
                )
            return GameLibraryDialog._mtime_cache.get(path, 0)
        return game.get("game_name", "").lower()

    def _sort_games(self, games: list) -> list:
        sort_option = self.sort_combo.currentData()
        reverse = sort_option in ("name_desc", "size_desc", "recently_installed")
        return sorted(
            games,
            key=lambda g: GameLibraryDialog._get_sort_key(g, sort_option),
            reverse=reverse,
        )

    def _filter_search(self, name: str, search: str) -> bool:
        """Case‑insensitive substring match."""
        return search in name.lower()

    def _refresh_game_list(self) -> None:
        if self._closing:
            return

        self._ensure_executor()
        self._refreshing = True
        self.games_list.clear()
        self._appid_to_item.clear()  # Clear index on refresh

        if not self.game_manager:
            self._hide_loading_state()
            self._refreshing = False
            return

        games = self.game_manager.get_all_games()
        if self._search_text:
            games = [
                g
                for g in games
                if self._filter_search(g.get("game_name", ""), self._search_text)
            ]

        # Batch-resolve all unknown AppIDs in a single DB query
        unknown_names = [
            g.get("game_name")
            for g in games
            if str(g.get("appid", "0")) in ("0", "N/A", "unknown")
        ]
        if unknown_names:
            resolved_map = self._batch_resolve_appids(unknown_names)
            for g in games:
                if str(g.get("appid", "0")) in ("0", "N/A", "unknown"):
                    name = g.get("game_name")
                    if name in resolved_map:
                        g["appid"] = resolved_map[name]

        games = self._sort_games(games)
        self._start_game_list_loading(games)

    @staticmethod
    def _batch_resolve_appids(names: list[str]) -> dict[str, str]:
        """Resolve multiple game names to AppIDs in a single DB query."""
        if not names or not DatabaseManager:
            return {}
        try:
            db = DatabaseManager()
            if not db.conn:
                return {}
            placeholders = ",".join("?" * len(names))
            cur = db.conn.cursor()
            cur.execute(
                f"SELECT name, appid FROM apps WHERE name IN ({placeholders}) COLLATE NOCASE",
                names,
            )
            return {row[0]: str(row[1]) for row in cur.fetchall()}
        except Exception as e:
            logger.debug(f"Batch DB lookup failed: {e}")
        return {}

    def _start_game_list_loading(self, games: list[dict]) -> None:
        """Populate the list in batches so the dialog can paint first."""
        self._list_refresh_token += 1
        self._loading_games = True
        self._pending_games = games
        self._pending_total_size = 0
        self._pending_accela_count = 0
        self._loaded_games_count = 0

        self.loading_label.setText("Carregando biblioteca de jogos...")
        self.loading_bar.setRange(0, max(len(games), 1))
        self.loading_bar.setValue(0)
        self.loading_widget.show()

        if not games:
            self._finish_game_list_loading(self._list_refresh_token)
            return

        refresh_token = self._list_refresh_token
        QTimer.singleShot(0, lambda: self._load_game_batch(refresh_token))

    def _load_game_batch(self, refresh_token: int) -> None:
        """Add a small batch of game widgets per event-loop tick."""
        if refresh_token != self._list_refresh_token or self._closing:
            return

        end_index = min(
            self._loaded_games_count + self._list_load_batch_size,
            len(self._pending_games),
        )

        while self._loaded_games_count < end_index:
            game = self._pending_games[self._loaded_games_count]
            if game.get("is_accela_install"):
                self._pending_accela_count += 1
            self._pending_total_size += self._add_game_to_list(game)
            self._loaded_games_count += 1

        self.loading_bar.setValue(self._loaded_games_count)

        if self._loaded_games_count < len(self._pending_games):
            QTimer.singleShot(0, lambda: self._load_game_batch(refresh_token))
            return

        self._finish_game_list_loading(refresh_token)

    def _finish_game_list_loading(self, refresh_token: int) -> None:
        """Finalize loading state once all list items have been created."""
        if refresh_token != self._list_refresh_token:
            return

        self.info_label.setText(
            f"Encontrados {len(self._pending_games)} jogo(s) Steam "
            f"({self._pending_accela_count} gerenciados pelo {DISPLAY_NAME}) - "
            f"tamanho total: {GameLibraryDialog._format_size(self._pending_total_size)}"
        )
        if self._search_text:
            self.info_label.setText(
                self.info_label.text() + f" (filtrado por '{self._search_text}')"
            )
        self._hide_loading_state()
        self._loading_games = False
        self._refreshing = False

    def _hide_loading_state(self) -> None:
        """Hide the loading widget and reset its progress display."""
        self.loading_widget.hide()
        self.loading_bar.reset()

    def _add_game_to_list(self, game: dict) -> int:
        """Creates and adds a single game widget to the list. Returns size."""
        size = game.get("size_on_disk", 0)
        widget = GameItemWidget(
            game,
            GameLibraryDialog._format_size(size),
            self.accent_color,
            self.background_color,
        )
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, game)
        item.setSizeHint(widget.sizeHint())
        self.games_list.addItem(item)
        self.games_list.setItemWidget(item, widget)

        app_id = str(game.get("appid", "0"))
        if app_id not in ("0", "N/A", "unknown"):
            self._appid_to_item[app_id] = item  # Register in index
            self._fetch_item_image(item, app_id)
        # No else branch needed, batch resolve already ran before this point

        return size

    @staticmethod
    def _resolve_appid_by_name(name: str) -> str | None:
        """Search the local database for an AppID by name."""
        if not name or not DatabaseManager:
            return None
        try:
            db = DatabaseManager()
            if not db.conn:
                return None

            cur = db.conn.cursor()
            cur.execute("SELECT appid FROM apps WHERE name = ? COLLATE NOCASE", (name,))
            row = cur.fetchone()
            if row:
                return str(row[0])
        except Exception as e:
            logger.debug(f"DB lookup failed for '{name}': {e}")
        return None

    def _on_item_selected(self, item: QListWidgetItem) -> None:
        """Handle click on list item."""
        if self._dialog_open or self._refreshing:
            return

        if not item:
            return

        game_data = item.data(Qt.ItemDataRole.UserRole)
        if not game_data:
            return

        # Debounce
        self._dialog_open = True
        QTimer.singleShot(500, lambda: setattr(self, "_dialog_open", False))

        self._show_game_details_dialog(game_data)

    # --- Image Handling ---

    def _fetch_item_image(self, _item: QListWidgetItem, app_id: str) -> None:
        self._ensure_executor()
        if not ImageFetcher:
            return
        if app_id in self._active_fetchers:
            return

        url = ImageFetcher.get_header_image_url(app_id)
        if not url:
            return

        fetcher = ImageFetcher(url)
        fetcher.setProperty("app_id", app_id)
        self._active_fetchers[app_id] = fetcher

        fetcher.finished.connect(self._on_item_image_fetched)
        fetcher.finished.connect(lambda _, aid=app_id: self._cleanup_fetcher(aid))
        fetcher.start()

    def _cleanup_fetcher(self, app_id: str) -> None:
        if app_id in self._active_fetchers:
            del self._active_fetchers[app_id]

    def _on_item_image_fetched(self, image_data: bytes) -> None:
        if self._closing:
            return

        sender = self.sender()
        app_id = sender.property("app_id")
        if not app_id:
            return

        if not image_data:
            # If image fetch failed, trigger a background refresh of the URL
            if self.isVisible():
                QTimer.singleShot(0, lambda: self._trigger_header_refresh(app_id))
            return

        self._image_cache[app_id] = image_data

        if not self.isVisible():
            return

        # Find item and widget
        item = self._appid_to_item.get(app_id)
        if item:
            self._update_item_image_if_match(item, app_id, image_data)

    def _check_appid_match(self, data: dict, app_id: str) -> bool:
        """Helper to check if a game's AppID matches the target AppID."""
        game_appid = str(data.get("appid", "0"))
        if game_appid == app_id:
            return True
        if game_appid in ("0", "N/A", "unknown"):
            resolved = self._resolve_appid_by_name(data.get("game_name"))
            return resolved == app_id
        return False

    def _update_item_image_if_match(self, item, app_id, image_data):
        """Helper to check if list item matches app_id and update image."""
        data = item.data(Qt.ItemDataRole.UserRole)
        if self._check_appid_match(data, app_id):
            widget = self.games_list.itemWidget(item)
            if isinstance(widget, GameItemWidget):
                pixmap = QPixmap()
                pixmap.loadFromData(image_data)
                widget.set_image(pixmap)

    def _trigger_header_refresh(self, app_id: str) -> None:
        """Trigger background refresh of header URL from API."""
        self._ensure_executor()

        def fetch_and_update():
            try:
                from utils.image_fetcher import ImageFetcher

                return ImageFetcher.fetch_header_from_web_api(app_id)
            except Exception as e:
                logger.warning(f"Header refresh failed for {app_id}: {e}")
            return None

        def on_complete(future_result):
            try:
                url = future_result.result()
                if url and not self._closing:
                    QTimer.singleShot(
                        0, lambda: self._apply_header_refresh(app_id, url)
                    )
            except RuntimeError:
                pass

        future = self.executor.submit(fetch_and_update)
        future.add_done_callback(on_complete)

    def _apply_header_refresh(self, app_id: str, api_url: str) -> None:
        """Update DB and retry fetch with new URL."""
        if self._closing or not self.isVisible():
            return

        try:
            from managers.db_manager import DatabaseManager

            db = DatabaseManager()
            db.upsert_app_info(app_id, {"header_url": api_url})

            # Retry fetch
            if app_id not in self._active_fetchers:
                fetcher = ImageFetcher(api_url)
                fetcher.setProperty("app_id", app_id)
                self._active_fetchers[app_id] = fetcher
                fetcher.finished.connect(self._on_item_image_fetched)
                fetcher.finished.connect(
                    lambda _, aid=app_id: self._cleanup_fetcher(aid)
                )
                fetcher.start()
        except RuntimeError as e:
            logger.warning(f"Failed to apply header refresh: {e}")

    # --- Game Details Dialog ---

    def _show_game_details_dialog(self, game_data: dict) -> None:
        """Show detailed game info in a tabbed dialog."""
        self._details_dialog = _DetalhesDialog(self)
        self._details_dialog.setWindowTitle("Detalhes do jogo")
        self._details_dialog.setMinimumWidth(500)
        self._details_dialog.setModal(True)

        # Consistent styling using background_color
        self._details_dialog.setStyleSheet(
            self.styleSheet()
            + f"""
            QTabWidget::pane {{ border: none; background-color: {self.background_color}; }}
            QTabBar::tab {{ 
                background: {self.background_color}; 
                color: {cor_secundaria(self.background_color)}; 
                padding: 8px 16px; 
            }}
            QTabBar::tab:selected {{ 
                color: {self.accent_color}; 
                border-bottom: 2px solid {self.accent_color}; 
            }}
            QCheckBox:focus, QRadioButton:focus, QPushButton:focus, QTabBar::tab:focus {{
                outline: 2px solid {self.accent_color};
                outline-offset: 1px;
            }}
            QWidget {{ background-color: {self.background_color}; }}
        """
        )

        main_layout = QVBoxLayout(self._details_dialog)
        tab_widget = QTabWidget()
        self._details_dialog.tabs = tab_widget

        self._create_overview_tab(tab_widget, game_data, self._details_dialog)
        self._create_uninstall_tab(tab_widget, game_data, self._details_dialog)
        self._create_tools_tab(tab_widget, game_data, self._details_dialog)

        main_layout.addWidget(tab_widget)
        self._details_dialog.exec()
        self._details_dialog = None

    def _create_overview_tab(self, tab_widget, game_data, dialog) -> None:
        """Helper to create the Overview tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(15)

        # Header Info
        name_lbl = QLabel(format_game_display_name(game_data))
        name_lbl.setStyleSheet(
            f"font-size: 20px; font-weight: bold; color: {self.accent_color};"
        )
        layout.addWidget(name_lbl)

        status_text = {
            "update_available": "Nova versão disponível",
            "up_to_date": "Atualizado",
            "checking": "Verificando atualizações...",
        }.get(game_data.get("update_status"), "Desconhecido")

        status_lbl = QLabel(status_text)
        status_lbl.setStyleSheet(f"color: {self.accent_color}; font-style: italic;")
        layout.addWidget(status_lbl)

        # Info Grid
        form = QFormLayout()

        def _lbl(text):
            label = QLabel(text)
            label.setStyleSheet(f"color: {self.accent_color};")
            return label

        form.addRow(_lbl("App ID:"), _lbl(str(game_data.get("appid"))))
        form.addRow(_lbl("Origem:"), _lbl(str(game_data.get("source", "Steam"))))
        size = GameLibraryDialog._format_size(game_data.get("size_on_disk", 0))
        form.addRow(_lbl("Tamanho:"), _lbl(size))
        form.addRow(_lbl("Caminho:"), _lbl(str(game_data.get("install_path"))))
        layout.addLayout(form)

        # Linux FakeAppID
        if platform.system() == "Linux":
            self._add_fake_appid_controls(layout, game_data)

        # Validate/Update Button
        validate_btn = QPushButton()
        is_update = game_data.get("update_status") == "update_available"
        validate_btn.setText("Baixar atualização" if is_update else "Verificar arquivos")
        validate_btn.clicked.connect(
            lambda: self._fetch_game_manifest(game_data, dialog)
        )
        layout.addWidget(validate_btn)

        # Footer Actions
        btn_layout = QHBoxLayout()
        open_btn = QPushButton("Abrir pasta")
        open_btn.clicked.connect(
            lambda: GameLibraryDialog._open_folder(game_data.get("install_path"))
        )
        btn_layout.addWidget(open_btn)

        close_btn = QPushButton("Fechar")
        close_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(close_btn)

        layout.addStretch()
        layout.addLayout(btn_layout)
        tab_widget.addTab(tab, "Visão geral")

    def _add_fake_appid_controls(self, layout, game_data) -> None:
        """Helper to add Linux FakeAppID UI controls."""
        if not is_slssteam_config_management_enabled():
            return

        hbox = QHBoxLayout()
        checkbox = QCheckBox("Adicionar ao SLSonline como:")
        checkbox.setStyleSheet(f"color: {self.accent_color};")
        checkbox.setToolTip("Adicionar a FakeAppIds no config.yaml do SLSsteam")
        hbox.addWidget(checkbox)

        hbox.addStretch()

        inp = QLineEdit()
        inp.setPlaceholderText("Spacewar (480)")
        inp.setFixedWidth(150)
        inp.setValidator(QIntValidator())
        hbox.addWidget(inp)

        save_btn = QPushButton("Salvar")
        save_btn.setFixedWidth(70)
        hbox.addWidget(save_btn)

        layout.addLayout(hbox)

        appid = str(game_data.get("appid", "0"))
        if appid in ("0", "N/A", "unknown", "480"):
            checkbox.setEnabled(False)
            inp.setEnabled(False)
            save_btn.setEnabled(False)
            return

        # Check initial state
        config = get_user_config_path()
        if config.exists():
            existing_fake_id = get_fake_appid(config, appid)
            if existing_fake_id:
                checkbox.setChecked(True)
                inp.setText(existing_fake_id)
            else:
                checkbox.setChecked(False)

        # Connect logic
        def _toggle(state):
            fake_id = inp.text().strip() or "480"
            name = game_data.get("game_name", "Desconhecido")
            if state == Qt.CheckState.Checked.value:
                # Ensure clean slate
                current_in_config = get_fake_appid(config, appid)
                if current_in_config:
                    remove_fake_app_id(config, appid, current_in_config)

                if not add_fake_app_id(config, appid, name, fake_id):
                    checkbox.setChecked(False)
            else:
                current_in_config = get_fake_appid(config, appid)
                if current_in_config:
                    if not remove_fake_app_id(config, appid, current_in_config):
                        checkbox.setChecked(True)

        def _update_fake_id():
            if checkbox.isChecked():
                fake_id = inp.text().strip() or "480"
                name = game_data.get("game_name", "Desconhecido")

                current_fake_id = get_fake_appid(config, appid)
                if current_fake_id:
                    remove_fake_app_id(config, appid, current_fake_id)

                add_fake_app_id(config, appid, name, fake_id)
                QMessageBox.information(self, "Sucesso", "AppID atualizado com sucesso.")

        checkbox.stateChanged.connect(_toggle)
        save_btn.clicked.connect(_update_fake_id)

    def _create_uninstall_tab(self, tab_widget, game_data, dialog) -> None:
        """Helper to create the Uninstall tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        lbl = QLabel("Remover este jogo e seus arquivos?")
        lbl.setStyleSheet(f"color: {self.accent_color};")
        layout.addWidget(lbl)

        opts = {}
        if platform.system() == "Linux":
            opts["compat"] = QCheckBox("Remover dados do Proton/Wine")
            opts["saves"] = QCheckBox("Remover saves da nuvem")
            opts["compat"].setStyleSheet(f"color: {self.accent_color};")
            opts["saves"].setStyleSheet(f"color: {self.accent_color};")
            layout.addWidget(opts["compat"])
            layout.addWidget(opts["saves"])

        btn = QPushButton("Desinstalar jogo")
        btn.clicked.connect(lambda: self._uninstall_game(game_data, dialog, opts))
        layout.addWidget(btn)
        layout.addStretch()

        tab_widget.addTab(tab, "Desinstalar")

    def _create_tools_tab(self, tab_widget, game_data, dialog) -> None:
        """Helper to create the Tools tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        path = game_data.get("install_path")
        name = game_data.get("game_name")

        # Steamless
        sl_btn = QPushButton("Remover DRM (Steamless)")
        sl_btn.clicked.connect(
            lambda: self.main_window.task_manager.run_steamless_for_game(path, name)
        )
        layout.addWidget(sl_btn)

        # ACF Fix
        fix_btn = QPushButton("Corrigir instalação (remover .acf)")
        fix_btn.clicked.connect(lambda: self._fix_game_install(game_data))
        layout.addWidget(fix_btn)

    # --- Actions ---

    def _fetch_game_manifest(self, game_data: dict, dialog: QDialog) -> None:
        app_id = str(game_data.get("appid", "0"))

        if app_id in ("0", "N/A", "unknown"):
            QMessageBox.warning(self, "Erro", "App ID inválido.")
            return

        name = game_data.get("game_name", "Desconhecido")
        status = game_data.get("update_status")

        # Determine if we can use local cache
        local_path = None
        if status != "update_available":
            fpath = (
                get_base_path() / "morrenus_manifests" / f"accela_fetch_{app_id}.zip"
            )
            if fpath.exists():
                local_path = str(fpath)

        if not local_path:
            self._handle_download_manifest(app_id, name, game_data, dialog)
        else:
            self._submit_job(local_path, game_data, dialog)

    def _handle_download_manifest(self, app_id, name, game_data, dialog):
        """Logic separated to flatten nesting in fetch_game_manifest."""
        if not self._confirm_action(
            "Confirmar download",
            f"Baixar o manifest de '{name}'?\nIsso usará sua cota da API.",
        ):
            return

        if not morrenus_api:
            QMessageBox.critical(self, "Erro", "Módulo da API não encontrado.")
            return

        self._download_progress_dialog = QProgressDialog(
            f"Baixando {name}...", "Cancelar", 0, 0, self
        )
        self._download_progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._download_progress_dialog.show()

        # Start async download
        self.executor.submit(self._download_manifest_async, app_id, game_data)

    def _download_manifest_async(self, app_id: str, game_data: dict) -> None:
        """Background task to download manifest."""
        try:
            fpath, error = morrenus_api.download_manifest(app_id)
            self.manifest_download_complete.emit(
                str(fpath) if fpath else "", str(error) if error else "", game_data
            )
        except Exception as e:
            self.manifest_download_complete.emit("", str(e), game_data)

    def _on_manifest_download_complete(
        self, fpath: str, error: str, game_data: dict
    ) -> None:
        """Slot to handle manifest download completion."""
        if self._download_progress_dialog:
            self._download_progress_dialog.close()
            self._download_progress_dialog = None

        if fpath:
            # If we have a valid path, submit the job
            # We need to access the dialog passed to _fetch_game_manifest, but it's not stored.
            # However, we stored _details_dialog in _show_game_details_dialog.
            if self._details_dialog:
                self._submit_job(fpath, game_data, self._details_dialog)
        else:
            QMessageBox.critical(self, "Erro", f"Falhou: {error}")

    def _submit_job(self, filepath: str, game_data: dict, dialog: QDialog) -> None:
        """Submit the job to the main window queue."""
        metadata = {
            "appid": game_data.get("appid"),
            "library_path": game_data.get("library_path"),
            "install_path": game_data.get("install_path"),
        }
        self.main_window.job_queue.add_job(filepath, metadata)
        dialog.accept()
        self.accept()

    @staticmethod
    def _open_folder(path: str) -> None:
        if not path or not os.path.exists(path):
            return
        try:
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.call(["open", path])
            else:
                subprocess.call(["xdg-open", path])
        except OSError:
            pass

    def _confirm_action(self, title: str, message: str) -> bool:
        return pergunta_sim_nao(self, title, message)

    def _uninstall_game(self, game_data: dict, dialog: QDialog, opts: dict) -> None:
        if not self.game_manager:
            return

        msg = self.game_manager.get_uninstall_confirmation_message(game_data)
        if not self._confirm_action("Confirmar desinstalação", msg):
            return

        # Extract boolean states from checkboxes
        c_data = opts.get("compat").isChecked() if "compat" in opts else False
        c_saves = opts.get("saves").isChecked() if "saves" in opts else False

        self._uninstall_progress_dialog = QProgressDialog(
            "Desinstalando o jogo...", None, 0, 0, self
        )
        self._uninstall_progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._uninstall_progress_dialog.show()

        # Start async uninstall
        self.executor.submit(self._uninstall_game_async, game_data, c_data, c_saves)

    def _uninstall_game_async(
        self, game_data: dict, c_data: bool, c_saves: bool
    ) -> None:
        """Background task to uninstall game."""
        try:
            success, err = self.game_manager.uninstall_game(
                game_data, remove_compatdata=c_data, remove_saves=c_saves
            )
            self.uninstall_complete.emit(success, str(err) if err else "")
        except Exception as e:
            self.uninstall_complete.emit(False, str(e))

    def _on_uninstall_complete(self, success: bool, error: str) -> None:
        """Slot to handle uninstall completion."""
        if self._uninstall_progress_dialog:
            self._uninstall_progress_dialog.close()
            self._uninstall_progress_dialog = None

        if success:
            QMessageBox.information(self, "Sucesso", "Jogo desinstalado.")
            if self._details_dialog:
                self._details_dialog.accept()
        else:
            QMessageBox.critical(self, "Erro", f"Falhou: {error}")

    def _fix_game_install(self, game_data: dict) -> None:
        path = game_data.get("library_path")
        appid = str(game_data.get("appid", ""))

        if not path or not appid or appid == "0":
            return

        acf = os.path.join(path, "steamapps", f"appmanifest_{appid}.acf")
        if not os.path.exists(acf):
            QMessageBox.warning(self, "Erro", "Arquivo de manifest não encontrado.")
            return

        if not self._confirm_action(
            "Confirmar", "Remover o arquivo de manifest? O Steam vai reverificar os arquivos."
        ):
            return

        os.remove(acf)
        QMessageBox.information(self, "Concluído", "Manifest removido.")
        if sys.platform == "linux":
            slssteam_api_send(f"install|{appid}|0")

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        if size_bytes == 0:
            return "0 B"
        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_names[i]}"

    def closeEvent(self, event) -> None:
        """Cleanup resources on close."""
        self._closing = True
        for fetcher in self._active_fetchers.values():
            fetcher.stop()
        self._active_fetchers.clear()
        if self.executor is not None:
            self.executor.shutdown(wait=False)
            self.executor = None
        super().closeEvent(event)
        self._closing = False

    def _volta_busca(self):
        """k no topo da lista volta pro campo de busca."""
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def keyPressEvent(self, event):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import (
            QCheckBox,
            QComboBox,
            QLineEdit,
            QPushButton,
            QRadioButton,
            QTextEdit,
        )

        k = event.key()
        foco = self.focusWidget()

        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if isinstance(foco, (QCheckBox, QRadioButton)):
                foco.setChecked(not foco.isChecked())
                return
            if isinstance(foco, QPushButton):
                foco.click()
                return
            lst = getattr(self, 'games_list', None)
            if lst is not None and lst.currentItem() is not None:
                lst.itemClicked.emit(lst.currentItem())
                return

        if foco and isinstance(foco, (QLineEdit, QTextEdit)):
            super().keyPressEvent(event)
            return
        if isinstance(foco, QComboBox) and foco.isEditable():
            super().keyPressEvent(event)
            return

        if k in (Qt.Key.Key_J, Qt.Key.Key_Down):
            lst = getattr(self, 'games_list', None)
            if lst is not None:
                cnt = lst.count()
                if cnt:
                    lst.setCurrentRow(min(cnt - 1, max(-1, lst.currentRow()) + 1))
                    lst.setFocus()
                return
        if k in (Qt.Key.Key_K, Qt.Key.Key_Up):
            lst = getattr(self, 'games_list', None)
            if lst is not None:
                cnt = lst.count()
                if cnt:
                    if lst.currentRow() <= 0:
                        if hasattr(self, 'search_edit'):
                            self.search_edit.setFocus()
                            self.search_edit.selectAll()
                        return
                    lst.setCurrentRow(lst.currentRow() - 1)
                    lst.setFocus()
                return
        if k == Qt.Key.Key_Slash:
            if hasattr(self, 'search_edit'):
                self.search_edit.setFocus()
                self.search_edit.selectAll()
                return
        if k == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)
