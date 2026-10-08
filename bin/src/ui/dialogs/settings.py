import logging
import os
import shutil
import subprocess
import sys
import webbrowser

from datetime import datetime
from typing import Any, Optional, Tuple

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QColor, QFont, QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFontDialog,
    QGroupBox,
    QHBoxLayout,
    QLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core import morrenus_api
from ui.dialogs.dialog_helpers import (
    FiltroVimListas,
    aplicar_barra_titulo,
    create_accept_button,
    tira_icones_padrao,
    traduz_rotulos,
)
from ui.theme import cor_secundaria, cores_status, sulco
from ui.window_defaults import LARGURA, aplicar
from utils.brand import DISPLAY_NAME
from utils.helpers import (
    create_checkbox_setting,
    create_font_setting,
    get_base_path,
    get_slscheevo_path,
    get_slscheevo_save_path,
    get_venv_python,
)
from utils.paths import Paths
from utils.settings import get_settings

logger = logging.getLogger(__name__)

# o qt entrega o seletor de cor e o de fonte em inglês: aqui vira pt-br
_ROTULOS_COR = {
    "&Basic colors": "Cores &básicas",
    "&Custom colors": "Cores &personalizadas",
    "Hu&e:": "&Matiz:",
    "&Sat:": "S&aturação:",
    "&Val:": "Valo&r:",
    "&Red:": "&Vermelho:",
    "&Green:": "Ver&de:",
    "Bl&ue:": "Azu&l:",
    "A&lpha channel:": "Canal alfa:",
    "&HTML:": "&HTML:",
    "&Pick Screen Color": "&Selecionar cor da tela",
    "&Add to Custom Colors": "Adicionar &cor personalizada",
}

_ROTULOS_FONTE = {
    "&Font": "&Fonte",
    "Font st&yle": "Estil&o",
    "&Size": "&Tamanho",
    "Effects": "Efeitos",
    "Sample": "Amostra",
}


class MorrenusStatsWidget(QWidget):
    """Widget displaying Morrenus API user statistics."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.settings = get_settings()
        self.username_label = None
        self.daily_usage_bar = None
        self.expiration_label = None
        self.total_calls_label = None
        self.status_label = None
        self.refresh_button = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Initialize the UI components."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 5, 0, 5)

        # Row 1: Username
        row1 = QHBoxLayout()
        row1.setSpacing(10)
        self.username_label = QLabel("Usuário: --")
        self.username_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row1.addWidget(self.username_label)
        main_layout.addLayout(row1)

        # Progress Bar
        self.daily_usage_bar = QProgressBar()
        self.daily_usage_bar.setRange(0, 100)
        self.daily_usage_bar.setValue(0)
        self.daily_usage_bar.setFormat("Diário: --")
        self.daily_usage_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)

        accent_color = self.settings.value("accent_color", "#000080")
        fundo = self.settings.value("background_color", "#c0c0c0")
        self.daily_usage_bar.setStyleSheet(
            f"""
            QProgressBar {{
                border: 1px solid {accent_color};
                border-radius: 0px;
                text-align: center;
                color: #FFFFFF;
                background-color: {sulco(fundo)};
                height: 20px;
            }}
            QProgressBar::chunk {{
                background-color: {accent_color};
            }}
        """
        )
        main_layout.addWidget(self.daily_usage_bar)

        # Row 2: Stats
        row2 = QHBoxLayout()
        row2.setSpacing(10)

        self.expiration_label = QLabel("Expira em: --")
        self.expiration_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row2.addWidget(self.expiration_label)

        self.total_calls_label = QLabel("Total: --")
        self.total_calls_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row2.addWidget(self.total_calls_label)

        self.status_label = QLabel("Status: --")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row2.addWidget(self.status_label)

        main_layout.addLayout(row2)

        # Refresh button
        self.refresh_button = QPushButton("Atualizar")
        self.refresh_button.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.refresh_button.clicked.connect(self.refresh_stats)
        main_layout.addWidget(self.refresh_button)

    def refresh_stats(self) -> None:
        """Fetch and display latest stats from the API."""
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText("Carregando...")

        stats = morrenus_api.get_user_stats()

        self.refresh_button.setEnabled(True)
        self.refresh_button.setText("Atualizar")

        if stats.get("error"):
            self._display_error_state()
        else:
            self._display_stats(stats)

    def _display_error_state(self) -> None:
        """Update UI to show error state."""
        self.username_label.setText("Usuário: erro")
        self.total_calls_label.setText("Total: --")
        self.daily_usage_bar.setFormat("Diário: erro")
        self.daily_usage_bar.setValue(0)
        self.expiration_label.setText("Expira em: --")
        self.status_label.setText("Status: erro")

    def _display_stats(self, stats: dict) -> None:
        """Update UI with fetched statistics."""
        self.username_label.setText(f"Usuário: {stats.get('username', 'desconhecido')}")
        self.total_calls_label.setText(f"Total: {stats.get('api_key_usage_count', 0)}")

        daily_usage = MorrenusStatsWidget._parse_int(stats.get("daily_usage", 0))
        daily_limit = MorrenusStatsWidget._parse_int(stats.get("daily_limit", 100))
        if daily_limit == 0:
            daily_limit = 100

        self.daily_usage_bar.setRange(0, daily_limit)
        self.daily_usage_bar.setValue(daily_usage)
        self.daily_usage_bar.setFormat(f"Diário: {daily_usage}/{daily_limit}")

        self._update_expiration_label(stats.get("api_key_expires_at", ""))

        status = "Ativo" if stats.get("can_make_requests", False) else "Bloqueado"
        self.status_label.setText(f"Status: {status}")

    @staticmethod
    def _parse_int(value: Any, default: int = 0) -> int:
        """Safely parse an integer value."""
        try:
            return int(value or default)
        except (TypeError, ValueError):
            return default

    def _update_expiration_label(self, expires_at: str) -> None:
        """Format and update the expiration label."""
        if not expires_at:
            self.expiration_label.setText("Expira em: nunca")
            return

        try:
            dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            self.expiration_label.setText(f"Expira em: {dt.strftime('%d/%m/%Y')}")
        except ValueError:
            self.expiration_label.setText(f"Expira em: {expires_at[:10]}")


class SettingsDialog(QDialog):
    """Dialog for configuring application settings."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Configurações")
        aplicar(self, parent)
        self.settings = get_settings()
        self.main_window = parent
        self.accent_color = self.settings.value("accent_color", "#000080")
        self.main_layout = None
        self.tab_widget = None
        self.library_mode_checkbox = None
        self.auto_skip_single_choice_checkbox = None
        self.steamless_checkbox = None
        self.achievements_checkbox = None
        self.sls_mode_checkbox = None
        self.sls_config_management_checkbox = None
        self.prompt_steam_restart_checkbox = None
        self.block_steam_updates_checkbox = None
        self.download_slssteam_button = None
        self.slssteam_status_label = None
        self.slssteam_hash_warning_label = None
        self.accent_color_button = None
        self.accent_reset_button = None
        self.bg_color_button = None
        self.bg_reset_button = None
        self.ignore_color_warnings_checkbox = None
        self.current_font = QFont()
        self.morrenus_stats_widget = None
        self.morrenus_tab_initialized = False

        # Save original API keys for restore on cancel
        self._original_morrenus_key = self.settings.value(
            "morrenus_api_key", "", type=str
        )

        self._user_accent_color = self.settings.value(
            "user_accent_color",
            self.settings.value("accent_color", "#000080"),
            type=str,
        )
        self._user_background_color = self.settings.value(
            "user_background_color",
            self.settings.value("background_color", "#c0c0c0"),
            type=str,
        )

        logger.debug("Opening SettingsDialog.")
        self._setup_ui()
        aplicar_barra_titulo(self)

    def _setup_ui(self) -> None:
        """Initialize the UI layout."""
        self.main_layout = QVBoxLayout(self)

        self._create_tab_widget()
        self._setup_tabs()
        self.main_layout.addWidget(self.tab_widget)

        self._create_dialog_buttons()

    def _create_tab_widget(self) -> None:
        """Create and style the tab widget."""
        self.tab_widget = QTabWidget()
        bg_color = self.settings.value("background_color", "#1E1E1E")
        self.tab_widget.setStyleSheet(
            f"""
            QTabWidget::pane {{
                border: none;
            }}
            QTabBar::tab {{
                background: {bg_color};
                color: {cor_secundaria(bg_color)};
                padding: 8px 16px;
                border: none;
            }}
            QTabBar::tab:selected {{
                color: {self.accent_color};
                border-bottom: 2px solid {self.accent_color};
            }}
            QTabBar::tab:!selected {{
                color: {cor_secundaria(bg_color)};
            }}
            QCheckBox:focus, QRadioButton:focus, QPushButton:focus, QTabBar::tab:focus {{
                outline: 2px solid {self.accent_color};
                outline-offset: 1px;
            }}
        """
        )

    def _setup_tabs(self) -> None:
        """Initialize and add all settings tabs."""
        self._create_downloads_tab()
        self._create_morrenus_tab()
        self._create_steam_tab()
        self._create_tools_tab()
        self._create_style_tab()

    def _create_dialog_buttons(self) -> None:
        """Create standard Ok/Cancel buttons."""
        buttons = create_accept_button(self.accept)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.button_box = buttons
        self.main_layout.addWidget(buttons)

    def _create_api_key_setting(
        self,
        label: str,
        placeholder: str,
        setting_key: str,
        help_url: Optional[str] = None,
        help_text: Optional[str] = None,
    ) -> Tuple[QVBoxLayout, QLineEdit]:
        """Create an API key input field with password toggle and help link."""
        layout = QVBoxLayout()
        layout.setSpacing(5)

        layout.addWidget(QLabel(label))

        input_layout = QHBoxLayout()
        input_layout.setSpacing(5)

        api_key_input = QLineEdit()
        api_key_input.setPlaceholderText(placeholder)
        api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        current_key = self.settings.value(setting_key, "", type=str)
        api_key_input.setText(current_key)

        toggle_btn = QPushButton("Mostrar")
        toggle_btn.clicked.connect(
            lambda: SettingsDialog._toggle_api_key_visibility(api_key_input, toggle_btn)
        )

        input_layout.addWidget(api_key_input)
        input_layout.addWidget(toggle_btn)
        layout.addLayout(input_layout)

        accent_color = self.settings.value("accent_color", "#000080")
        if help_url:
            help_label = QLabel(
                f'<a href="{help_url}" style="color: {accent_color};">Obter chave API</a>'
            )
            help_label.setOpenExternalLinks(True)
            layout.addWidget(help_label)
        elif help_text:
            help_label = QLabel(help_text)
            help_label.setStyleSheet(
                f"color: {cor_secundaria(self.settings.value('background_color', '#c0c0c0'))};"
                " font-size: 11px;"
            )
            layout.addWidget(help_label)

        return layout, api_key_input

    @staticmethod
    def _toggle_api_key_visibility(
        input_field: QLineEdit, toggle_btn: QPushButton
    ) -> None:
        """Toggle API key visibility."""
        if input_field.echoMode() == QLineEdit.EchoMode.Password:
            input_field.setEchoMode(QLineEdit.EchoMode.Normal)
            toggle_btn.setText("Ocultar")
        else:
            input_field.setEchoMode(QLineEdit.EchoMode.Password)
            toggle_btn.setText("Mostrar")

    def _create_downloads_tab(self) -> None:
        """Create the Downloads settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)

        # Download Settings Group
        dl_group = QGroupBox("Configurações de download")
        dl_layout = QVBoxLayout()

        library_tooltip = "Detectar bibliotecas Steam para escolher onde instalar cada jogo."

        self.library_mode_checkbox = create_checkbox_setting(
            "Limitar downloads às bibliotecas Steam",
            "library_mode",
            True,
            self,
            library_tooltip,
        )
        dl_layout.addWidget(self.library_mode_checkbox)

        self.auto_skip_single_choice_checkbox = create_checkbox_setting(
            "Pular seleção única",
            "auto_skip_single_choice",
            True,
            self,
            "Pular automaticamente quando só existe uma opção.",
        )
        dl_layout.addWidget(self.auto_skip_single_choice_checkbox)

        dl_group.setLayout(dl_layout)
        layout.addWidget(dl_group)

        # Post-Processing Group
        pp_group = QGroupBox("Pós-Processamento")
        pp_layout = QVBoxLayout()

        self.achievements_checkbox = create_checkbox_setting(
            "Gerar conquistas Steam",
            "generate_achievements",
            True,
            self,
            "Gerar arquivos de conquista para seus jogos após os downloads.",
        )
        pp_layout.addWidget(self.achievements_checkbox)

        self.steamless_checkbox = create_checkbox_setting(
            "Remover DRM Steam com Steamless",
            "use_steamless",
            True,
            self,
            "Remover DRM dos executáveis dos jogos após baixar.",
        )
        pp_layout.addWidget(self.steamless_checkbox)

        pp_group.setLayout(pp_layout)
        layout.addWidget(pp_group)

        layout.addStretch()
        self.tab_widget.addTab(tab, "Downloads")

    def _create_morrenus_tab(self) -> None:
        """Create the Morrenus API settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)

        # API Keys Group
        key_group = QGroupBox("Chaves de API")
        key_layout = QVBoxLayout()
        key_layout.setSpacing(10)

        morrenus_layout, self.api_key_input = self._create_api_key_setting(
            "Chave API Morrenus:",
            "Cole sua chave API Morrenus",
            "morrenus_api_key",
            help_url="https://discord.com/invite/hubcapsmanifest",
        )
        key_layout.addLayout(morrenus_layout)

        key_group.setLayout(key_layout)
        layout.addWidget(key_group)

        # Stats Group
        stats_group = QGroupBox("Estatísticas Morrenus")
        stats_layout = QVBoxLayout()
        stats_layout.setContentsMargins(5, 10, 5, 10)

        self.morrenus_stats_widget = MorrenusStatsWidget()
        stats_layout.addWidget(self.morrenus_stats_widget)

        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)

        layout.addStretch()

        # Connect tab change for lazy loading stats
        self.morrenus_tab_initialized = False
        self.tab_widget.currentChanged.connect(self._on_tab_changed)

        self.tab_widget.addTab(tab, "Integrações")

    def _on_tab_changed(self, index: int) -> None:
        """Handle tab change events."""
        if (
            self.tab_widget.tabText(index) == "Integrações"
            and not self.morrenus_tab_initialized
        ):
            self.morrenus_tab_initialized = True
            QTimer.singleShot(100, self.morrenus_stats_widget.refresh_stats)

    def _create_steam_tab(self) -> None:
        """Create the Steam settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)

        # Integration Group
        int_group = QGroupBox("Integração Steam")
        int_layout = QVBoxLayout()

        if sys.platform == "linux":
            wrapper_name = "SLSsteam"
            self.sls_mode_checkbox = None
            linux_hint = QLabel(
                "SLSsteam é habilitado automaticamente para instalações em bibliotecas Steam."
            )
            linux_hint.setWordWrap(True)
            int_layout.addWidget(linux_hint)
        else:
            wrapper_name = "GreenLuma"
            wrapper_full = "Modo Wrapper GreenLuma"
            tooltip = (
                "Integrar jogos com Steam usando GreenLuma.\n"
                "Jogos aparecem na sua biblioteca Steam automaticamente."
            )
            self.sls_mode_checkbox = create_checkbox_setting(
                wrapper_full, "slssteam_mode", False, self, tooltip
            )
            int_layout.addWidget(self.sls_mode_checkbox)

        self.sls_config_management_checkbox = create_checkbox_setting(
            f"Gerenciar configurações do {wrapper_name}",
            "sls_config_management",
            True,
            self,
            f"Permitir {DISPLAY_NAME} gerenciar arquivos de configuração do {wrapper_name}.",
        )
        int_layout.addWidget(self.sls_config_management_checkbox)

        int_group.setLayout(int_layout)
        layout.addWidget(int_group)

        # Settings Group
        settings_group = QGroupBox("Configurações Steam")
        settings_layout = QVBoxLayout()

        self.prompt_steam_restart_checkbox = create_checkbox_setting(
            "Perguntar para reiniciar o Steam",
            "prompt_steam_restart",
            True,
            self,
            "Mostrar prompt para reiniciar Steam após downloads integrados ao Steam.",
        )
        settings_layout.addWidget(self.prompt_steam_restart_checkbox)

        self.block_steam_updates_checkbox = create_checkbox_setting(
            "Bloquear atualizações do Steam",
            "block_steam_updates",
            SettingsDialog._is_steam_updates_blocked(),
            self,
            "Impedir que o Steam atualize automaticamente.",
        )
        settings_layout.addWidget(self.block_steam_updates_checkbox)

        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)

        layout.addStretch()
        self.tab_widget.addTab(tab, "Steam")

    def _create_tools_tab(self) -> None:
        """Create the Tools settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)

        # Tools Group
        tools_group = QGroupBox("Ferramentas")
        tools_layout = QVBoxLayout()

        SettingsDialog._add_tool_button(
            tools_layout,
            "Configurar conquistas",
            "Iniciar SLScheevo para configurar credenciais de conquista.",
            self.run_slscheevo,
        )

        SettingsDialog._add_tool_button(
            tools_layout,
            "Remover DRM",
            "Executar Steamless manualmente em um .exe do jogo.",
            self.run_steamless_manually,
        )

        self.download_slssteam_button = QPushButton("Ir ao repositório do h3adcr-b no GitHub")
        self.download_slssteam_button.setToolTip(
            "Instalador auxiliar do SLSsteam (h3adcr-b)."
        )
        self.download_slssteam_button.clicked.connect(self.download_slssteam)

        if sys.platform == "linux":
            tools_layout.addWidget(self.download_slssteam_button)
            SettingsDialog._add_tool_explanation(
                tools_layout, self.download_slssteam_button.toolTip()
            )
            self.slssteam_status_label = QLabel()
            self.slssteam_status_label.setStyleSheet(
                f"color: {self.accent_color}; font-size: 12px;"
            )
            tools_layout.addWidget(self.slssteam_status_label)

            self.slssteam_hash_warning_label = QLabel()
            self.slssteam_hash_warning_label.setStyleSheet(
                f"color: {cores_status(self.settings.value('background_color', '#c0c0c0'))['erro']};"
                " font-size: 11px;"
            )
            self.slssteam_hash_warning_label.setWordWrap(True)
            self.slssteam_hash_warning_label.setMaximumWidth(300)
            tools_layout.addWidget(self.slssteam_hash_warning_label)

            # Update status after labels are created
            self._update_slssteam_status()

        tools_group.setLayout(tools_layout)
        layout.addWidget(tools_group)

        layout.addStretch()
        self.tab_widget.addTab(tab, "Ferramentas")

    @staticmethod
    def _add_tool_button(layout: QVBoxLayout, text: str, tooltip: str, slot) -> None:
        """Helper to add a tool button with explanation text."""
        btn = QPushButton(text)
        btn.setToolTip(tooltip)
        btn.clicked.connect(slot)
        layout.addWidget(btn)
        SettingsDialog._add_tool_explanation(layout, tooltip)

    @staticmethod
    def _add_tool_explanation(layout: QVBoxLayout, text: str) -> None:
        """Helper to add explanation label."""
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {cor_secundaria(get_settings().value('background_color', '#c0c0c0'))};"
            " font-size: 11px;"
        )
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

    def _create_style_tab(self) -> None:
        """Create the Style settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)

        # Color Group
        color_group = QGroupBox("Configurações de cor")
        color_layout = QVBoxLayout()

        # Accent
        acc_layout = QHBoxLayout()
        self.accent_color_button = QPushButton()
        self.accent_color_button.setStyleSheet(
            f"background-color: {self._user_accent_color};"
        )
        self.accent_reset_button = QPushButton("Redefinir")
        acc_layout.addWidget(QLabel("Cor de destaque:"))
        acc_layout.addWidget(self.accent_color_button)
        acc_layout.addWidget(self.accent_reset_button)
        acc_layout.addStretch()
        self.accent_color_button.clicked.connect(self.choose_accent_color)
        self.accent_reset_button.clicked.connect(self.reset_accent_color)
        color_layout.addLayout(acc_layout)

        # Background
        bg_layout = QHBoxLayout()
        self.bg_color_button = QPushButton()
        self.bg_color_button.setStyleSheet(
            f"background-color: {self._user_background_color};"
        )
        self.bg_reset_button = QPushButton("Redefinir")
        bg_layout.addWidget(QLabel("Cor de fundo:"))
        bg_layout.addWidget(self.bg_color_button)
        bg_layout.addWidget(self.bg_reset_button)
        bg_layout.addStretch()
        self.bg_color_button.clicked.connect(self.choose_bg_color)
        self.bg_reset_button.clicked.connect(self.reset_bg_color)
        color_layout.addLayout(bg_layout)

        self.ignore_color_warnings_checkbox = create_checkbox_setting(
            "Ignorar avisos de cor",
            "ignore_color_warnings",
            True,
            self,
            "Permitir qualquer combinação de cores.",
        )
        color_layout.addWidget(self.ignore_color_warnings_checkbox)

        color_group.setLayout(color_layout)
        layout.addWidget(color_group)

        # Font Group
        font_group = QGroupBox("Configurações de fonte")
        font_layout = QVBoxLayout()
        font_children, self.font_button, self.font_reset_button = create_font_setting(
            self
        )
        self.font_button.clicked.connect(self.choose_font)
        self.font_reset_button.clicked.connect(self.reset_font)
        font_layout.addLayout(font_children)
        font_group.setLayout(font_layout)
        layout.addWidget(font_group)

        layout.addStretch()
        self.tab_widget.addTab(tab, "Estilo")

    # Color Handlers
    def _abre_seletor_cor(self):
        """seletor de cor com barra win95, sem cancelar e sem ícone no ok."""
        caixa = QColorDialog(self)
        traduz_rotulos(caixa, _ROTULOS_COR, "Selecionar cor")
        tira_icones_padrao(caixa)
        box = caixa.findChild(QDialogButtonBox)
        if box is not None:
            cancelar = box.button(QDialogButtonBox.StandardButton.Cancel)
            if cancelar is not None:
                box.removeButton(cancelar)
                cancelar.deleteLater()
        aplicar_barra_titulo(caixa)
        # o grid do qt tem mínimo de 579 de largura; libera o trava-geometria
        # p/ caber na largura padrão (altura fica a natural: o 660 do padrão
        # abre um vão feio no meio do seletor)
        if caixa.layout() is not None:
            caixa.layout().setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        caixa.setFixedSize(LARGURA, caixa.sizeHint().height())
        quadro = caixa.frameGeometry()
        quadro.moveCenter(self.frameGeometry().center())
        caixa.move(quadro.topLeft())
        if caixa.exec():
            return caixa.currentColor()
        return QColor()

    def choose_accent_color(self) -> None:
        color = self._abre_seletor_cor()
        if not color.isValid():
            return
        if (
            not self.ignore_color_warnings_checkbox.isChecked()
            and SettingsDialog._is_too_dark(color)
        ):
            SettingsDialog._show_color_warning()
            return
        hex_c = color.name()
        self.accent_color_button.setStyleSheet(f"background-color: {hex_c};")

    def reset_accent_color(self) -> None:
        default = "#000080"
        self.settings.setValue("accent_color", default)
        self.accent_color_button.setStyleSheet(f"background-color: {default};")

    def choose_bg_color(self) -> None:
        color = self._abre_seletor_cor()
        if not color.isValid():
            return
        hex_c = color.name()
        self.bg_color_button.setStyleSheet(f"background-color: {hex_c};")

    def reset_bg_color(self) -> None:
        default = "#c0c0c0"
        self.settings.setValue("background_color", default)
        self.bg_color_button.setStyleSheet(f"background-color: {default};")

    @staticmethod
    def _is_too_dark(color: QColor) -> bool:
        brightness = color.red() * 0.299 + color.green() * 0.587 + color.blue() * 0.114
        return brightness < 15

    @staticmethod
    def _is_too_close(accent: QColor, bg: QColor, threshold: int = 100) -> bool:
        r_diff = bg.red() - accent.red()
        g_diff = bg.green() - accent.green()
        b_diff = bg.blue() - accent.blue()
        return (r_diff**2 + g_diff**2 + b_diff**2) ** 0.5 < threshold

    @staticmethod
    def _show_color_warning() -> None:
        QMessageBox.warning(
            None,
            "Cor inválida",
            "Esta cor é muito escura e deixará a interface inutilizável.",
        )

    # Font Handlers
    def choose_font(self) -> None:
        dialogo = QFontDialog(self.current_font, self)
        # j/k linha a linha; h/l e setas entre as seções (font/style/size)
        filtro_fonte = FiltroVimListas(dialogo, secoes=True)
        for vista in dialogo.findChildren(QAbstractItemView):
            vista.installEventFilter(filtro_fonte)
        # suporte é só pt-br: sem efeitos e sem escolha de writing system
        for grupo in dialogo.findChildren(QGroupBox):
            if grupo.findChildren(QCheckBox):
                grupo.hide()
            elif grupo.findChild(QLineEdit) is not None:
                # sem os efeitos o sample despenca no grid e perde toda a
                # altura (fica 42px e o padding do qss mata o texto)
                grupo.setMinimumHeight(150)
        for sistema in dialogo.findChildren(QComboBox):
            sistema.hide()
            for rotulo in dialogo.findChildren(QLabel):
                if rotulo.buddy() is sistema:
                    rotulo.hide()
        traduz_rotulos(dialogo, _ROTULOS_FONTE, "Selecionar fonte")
        tira_icones_padrao(dialogo)
        box = dialogo.findChild(QDialogButtonBox)
        if box is not None:
            cancelar = box.button(QDialogButtonBox.StandardButton.Cancel)
            if cancelar is not None:
                box.removeButton(cancelar)
                cancelar.deleteLater()
        aplicar_barra_titulo(dialogo)
        aplicar(dialogo, self)
        if dialogo.exec():
            self.current_font = dialogo.currentFont()
            self.update_font_button_text()

    def reset_font(self) -> None:
        default = QFont("W95FA", 10)
        default.setBold(False)
        default.setItalic(False)
        self.current_font = default
        self.update_font_button_text()

    def update_font_button_text(self) -> None:
        if hasattr(self, "font_button") and hasattr(self, "current_font"):
            fam = self.current_font.family()
            size = self.current_font.pointSize()
            text = f"{fam} {size}pt"
            if self.current_font.bold():
                text += " negrito"
            if self.current_font.italic():
                text += " itálico"
            self.font_button.setText(text)
            self.font_button.setFont(self.current_font)

    def accept(self) -> None:
        """Save all settings and close."""
        self._save_general_settings()
        self._save_download_settings()
        if not self._save_style_settings():
            return  # Style validation failed
        logger.info("All settings saved.")
        super().accept()

    def _save_general_settings(self) -> None:
        api_key = self.api_key_input.text().strip()
        self.settings.setValue("morrenus_api_key", api_key)

    def _save_download_settings(self) -> None:
        if self.sls_mode_checkbox is not None:
            self.settings.setValue("slssteam_mode", self.sls_mode_checkbox.isChecked())
        self.settings.setValue(
            "sls_config_management",
            self.sls_config_management_checkbox.isChecked(),
        )
        self.settings.setValue("library_mode", self.library_mode_checkbox.isChecked())
        self.settings.setValue(
            "auto_skip_single_choice",
            self.auto_skip_single_choice_checkbox.isChecked(),
        )
        self.settings.setValue(
            "prompt_steam_restart",
            self.prompt_steam_restart_checkbox.isChecked(),
        )
        self.settings.setValue(
            "generate_achievements", self.achievements_checkbox.isChecked()
        )
        self.settings.setValue("use_steamless", self.steamless_checkbox.isChecked())

        block_updates = self.block_steam_updates_checkbox.isChecked()
        self.settings.setValue("block_steam_updates", block_updates)
        SettingsDialog._apply_steam_updates_block(block_updates)

    def _save_style_settings(self) -> bool:
        acc_s = self.accent_color_button.styleSheet()
        bg_s = self.bg_color_button.styleSheet()
        u_accent = acc_s.split("background-color: ")[1].split(";")[0]
        u_bg = bg_s.split("background-color: ")[1].split(";")[0]

        self.settings.setValue("user_accent_color", u_accent)
        self.settings.setValue("user_background_color", u_bg)

        applied_accent = u_accent
        applied_bg = u_bg
        self.settings.setValue("font-file", "")

        ignore = self.ignore_color_warnings_checkbox.isChecked()
        self.settings.setValue("ignore_color_warnings", ignore)

        if not ignore:
            if SettingsDialog._is_too_close(QColor(u_accent), QColor(u_bg)):
                QMessageBox.warning(
                    self,
                    "Cor inválida",
                    "O fundo é muito parecido com a cor de destaque.",
                )
                return False

        self.settings.setValue("accent_color", applied_accent)
        self.settings.setValue("background_color", applied_bg)

        self.settings.setValue("font", self.current_font.family())
        self.settings.setValue("font-size", self.current_font.pointSize())

        style = "Normal"
        if self.current_font.bold():
            style = "Bold"
        if self.current_font.italic():
            style = "Italic"
        if self.current_font.bold() and self.current_font.italic():
            style = "Bold Italic"
        self.settings.setValue("font-style", style)

        if self.main_window and hasattr(self.main_window, "ui_state"):
            # noinspection PyUnresolvedReferences
            self.main_window.ui_state.apply_style_settings()

        return True

    def reject(self) -> None:
        """Revert settings on cancel."""
        self.settings.setValue("morrenus_api_key", self._original_morrenus_key)

        super().reject()

    @staticmethod
    def _is_steam_updates_blocked() -> bool:
        """Check if steam.cfg exists."""
        try:
            from core.steam_helpers import find_steam_install

            path = find_steam_install()
            if not path:
                return False
            return os.path.exists(os.path.join(path, "steam.cfg"))
        except ImportError:
            return False

    @staticmethod
    def _apply_steam_updates_block(enabled: bool) -> None:
        """Manage steam.cfg file."""
        try:
            from core.steam_helpers import find_steam_install

            path = find_steam_install()
            if not path:
                logger.warning("Steam not found, skipping steam.cfg")
                return

            dest = os.path.join(path, "steam.cfg")
            src = Paths.deps("steam.cfg")

            if enabled:
                if not src.exists():
                    logger.error(f"Source steam.cfg missing: {src}")
                    return
                shutil.copy2(str(src), dest)
                logger.info(f"Copied steam.cfg to {dest}")
            elif os.path.exists(dest):
                os.remove(dest)
                logger.info(f"Removed steam.cfg from {dest}")

        except (ImportError, IOError) as e:
            logger.error(f"Failed to apply steam.cfg: {e}", exc_info=True)

    def _update_slssteam_status(self) -> None:
        """Check status update in background."""
        from core.tasks.download_slssteam_task import DownloadSLSsteamTask

        vf = get_base_path() / "SLSsteam" / "VERSION"
        if not vf.exists():
            self._set_label_viz("slssteam_status_label", False)
            self._set_label_viz("slssteam_hash_warning_label", False)
            return

        self._set_label_viz("slssteam_status_label", True)
        self._set_label_viz("slssteam_hash_warning_label", True)

        import threading

        def check() -> None:
            st = DownloadSLSsteamTask.check_update_available()
            if hasattr(self, "slssteam_status_label"):
                self.slssteam_status_label.setText(
                    SettingsDialog._format_status_text(st)
                )
            if hasattr(self, "slssteam_hash_warning_label"):
                self._update_slssteam_hash_warning(st)

        threading.Thread(target=check, daemon=True).start()

    def _set_label_viz(self, name: str, viz: bool) -> None:
        if hasattr(self, name):
            getattr(self, name).setVisible(viz)

    def _update_slssteam_hash_warning(self, status: dict) -> None:
        """Update hash warning text."""
        if not hasattr(self, "slssteam_hash_warning_label"):
            return

        lbl = self.slssteam_hash_warning_label
        mis = status.get("steamclient_mismatch")
        fnd = status.get("steamclient_found")
        err = status.get("steamclient_error")
        cores = cores_status(self.settings.value("background_color", "#c0c0c0"))
        pink = f"color: {cores['erro']}; font-size: 11px;"
        green = f"color: {cores['ok']}; font-size: 11px;"

        if mis:
            lbl.setText("Seu cliente Steam não é compatível.")
            lbl.setStyleSheet(pink)
        elif err and fnd:
            lbl.setText("Não foi possível verificar a compatibilidade.")
            lbl.setStyleSheet(pink)
        elif not fnd:
            lbl.setText("Cliente Steam não encontrado.")
            lbl.setStyleSheet(pink)
        elif mis is False:
            lbl.setText("Seu cliente Steam é compatível.")
            lbl.setStyleSheet(green)
        lbl.setVisible(True)

    @staticmethod
    def _format_status_text(status: dict) -> str:
        if status.get("error"):
            return "Status desconhecido (erro na verificação)"
        ver = status.get("latest_version", "Unknown")
        if not status.get("installed", False):
            return f"Não instalado • Mais recente: {ver}"
        if status.get("update_available", False):
            return f"Atualização disponível • Mais recente: {ver}"
        return f"Atualizado • Versão: {status.get('installed_version', '?')}"

    def download_slssteam(self):
        """Open external recommended SLSsteam installer page instead of installing."""
        url = "https://github.com/Deadboy666/h3adcr-b?tab=readme-ov-file#headcrab"
        opened = False

        if sys.platform == "linux" and shutil.which("xdg-open"):
            try:
                result = subprocess.run(
                    ["xdg-open", url],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                opened = result.returncode == 0
            except Exception as e:
                logger.error(f"xdg-open failed: {e}")

        if not opened:
            try:
                browser = webbrowser.get()
                opened = browser.open_new_tab(url)
                logger.info("webbrowser.open_new_tab returned: %s", opened)
            except Exception as e:
                logger.warning(f"Webbrowser fallback failed: {e}")

        if not opened:
            try:
                opened = QDesktopServices.openUrl(QUrl(url))
                logger.info("QDesktopServices.openUrl returned: %s", opened)
            except Exception as e:
                logger.warning(f"QDesktopServices failed: {e}")

        if opened:
            try:
                self.accept()
            except Exception:
                pass
        else:
            QMessageBox.critical(
                self,
                "Erro",
                f"Não foi possível abrir a página do instalador externo. Visite:\n{url}",
            )

    def run_slscheevo(self) -> None:
        """Launch SLScheevo."""
        path = get_slscheevo_path()
        if not os.path.exists(path):
            QMessageBox.critical(self, "Erro", f"SLScheevo não encontrado: {path}")
            return

        save = get_slscheevo_save_path()
        cmd = []
        if str(path).endswith(".py"):
            py = get_venv_python()
            cmd.append(
                py if py else ("python" if sys.platform == "win32" else "python3")
            )
        cmd.extend(
            [str(path), "--save-dir", str(save), "--noclear", "--max-tries", "101"]
        )

        SettingsDialog._launch_terminal_command(cmd, os.path.dirname(path))

    @staticmethod
    def _launch_terminal_command(
        cmd: list[str], cwd: str, needs_env: bool = False
    ) -> None:
        """Try to launch a command in a visible terminal."""
        cmd: list[str] = [str(part) for part in cmd]
        cwd = str(cwd)
        if sys.platform == "win32":
            q_cmd = " ".join([f'"{c}"' if " " in str(c) else str(c) for c in cmd])
            try:
                subprocess.Popen(
                    f'start cmd /k "cd /d {cwd} && {q_cmd}"',
                    shell=True,
                )
                return
            except OSError:
                pass
        else:
            terms = [
                ["wezterm", "start", "--always-new-process", "--"] + cmd,
                ["konsole", "-e"] + cmd,
                ["gnome-terminal", "--"] + cmd,
                ["ptyxis", "--"] + cmd,
                ["alacritty", "-e"] + cmd,
                ["tilix", "-e"] + cmd,
                ["xfce4-terminal", "-e"] + cmd,
                ["terminator", "-x"] + cmd,
                ["mate-terminal", "-e"] + cmd,
                ["lxterminal", "-e"] + cmd,
                ["xterm", "-e"] + cmd,
                ["kitty", "-e"] + cmd,
            ]
            for t in terms:
                try:
                    t_cmd: list[str] = [str(part) for part in t]
                    subprocess.Popen(t_cmd, cwd=cwd)
                    return
                except FileNotFoundError:
                    continue

        # Fallback dialog
        msg_box = QMessageBox()
        msg_box.setWindowTitle("Terminal não encontrado")
        msg_box.setText(
            "Não foi possível abrir um terminal automaticamente.\n"
            "Abra um terminal e execute:\n"
        )
        msg_box.setInformativeText(" ".join(cmd))
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg_box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        tira_icones_padrao(msg_box)
        msg_box.exec()

    def run_steamless_manually(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Selecionar executável", os.path.expanduser("~"), "*.exe"
        )
        if path and self.main_window:
            # noinspection PyUnresolvedReferences
            self.main_window.task_manager.run_steamless_manually(path)



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
        mod = event.modifiers()

        if (mod & Qt.KeyboardModifier.ShiftModifier) and k in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        ):
            ok = self._botao_ok()
            if ok:
                ok.click()
            return

        foco = self.focusWidget()
        if foco and isinstance(foco, (QLineEdit, QTextEdit)):
            super().keyPressEvent(event)
            return
        if isinstance(foco, QComboBox) and foco.isEditable():
            super().keyPressEvent(event)
            return

        if k in (Qt.Key.Key_J, Qt.Key.Key_Down):
            self._navega_lista(1)
            return
        if k in (Qt.Key.Key_K, Qt.Key.Key_Up):
            self._navega_lista(-1)
            return
        if k in (Qt.Key.Key_H, Qt.Key.Key_Left):
            if hasattr(self, "tab_widget"):
                idx = self.tab_widget.currentIndex()
                self.tab_widget.setCurrentIndex(max(0, idx - 1))
            return
        if k in (Qt.Key.Key_L, Qt.Key.Key_Right):
            if hasattr(self, "tab_widget"):
                idx = self.tab_widget.currentIndex()
                cnt = self.tab_widget.count()
                self.tab_widget.setCurrentIndex(min(cnt - 1, idx + 1))
            return
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if isinstance(foco, (QCheckBox, QRadioButton)):
                foco.setChecked(not foco.isChecked())
                return
            if isinstance(foco, QPushButton):
                foco.click()
                return
            # foco na aba ou widget comum: enter não faz nada (não aperta o OK)
            return
        super().keyPressEvent(event)

    def _botao_ok(self):
        box = getattr(self, "button_box", None)
        if box is None:
            return None
        return box.button(box.StandardButton.Ok)

    def _nav_widgets(self):
        """widgets focáveis (checkbox/radio/botão) da aba atual, em ordem."""
        from PyQt6.QtWidgets import QCheckBox, QPushButton, QRadioButton

        tab = self.tab_widget.currentWidget() if hasattr(self, "tab_widget") else self
        widgets = []
        node = tab.nextInFocusChain()
        guard = 0
        while node is not tab and guard < 4000:
            guard += 1
            if (
                isinstance(node, (QCheckBox, QRadioButton, QPushButton))
                and node.isVisible()
                and node.isEnabled()
                and self._e_desc(node, tab)
            ):
                widgets.append(node)
            node = node.nextInFocusChain()
        return widgets

    @staticmethod
    def _e_desc(widget, raiz):
        pai = widget.parentWidget()
        while pai is not None:
            if pai is raiz:
                return True
            pai = pai.parentWidget()
        return False

    def _navega_lista(self, passo):
        """j/k: anda um por um; para no fim e no início (sem pular pro OK)."""
        nav = self._nav_widgets()
        if not nav:
            return
        foco = self.focusWidget()
        if any(foco is w for w in nav):
            idx = next(i for i, w in enumerate(nav) if w is foco) + passo
            if idx >= len(nav) or idx < 0:
                return
            alvo = nav[idx]
        else:
            alvo = nav[0] if passo > 0 else nav[-1]
        alvo.setFocus()
