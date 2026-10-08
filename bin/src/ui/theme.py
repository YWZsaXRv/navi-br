"""
Theme Manager.

Handles application theming, palette application, and font loading.
"""

import logging
from pathlib import Path
from typing import Dict, Optional, Tuple, Union

from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PyQt6.QtWidgets import QApplication

from utils.paths import Paths

logger = logging.getLogger(__name__)


def cabecalho_secao(accent: str) -> str:
    """Estilo dos cabeçalhos de seção da janela principal (Logs, Fila)."""
    return f"color: {accent}; font-size: 12px; font-weight: bold;"


def claro(background: Union[str, QColor]) -> bool:
    """True quando o fundo é claro (win95: aí o texto/borda precisa ser escuro)."""
    bg = background if isinstance(background, QColor) else QColor(background)
    return bg.lightness() > 128


def cor_secundaria(background: Union[str, QColor]) -> str:
    """Cinza de apoio legível sobre o fundo indicado."""
    return "#4A4A4A" if claro(background) else "#888888"


def cores_status(background: Union[str, QColor]) -> Dict[str, str]:
    """Cores de status legíveis sobre o fundo indicado (ok, andamento, erro)."""
    if claro(background):
        return {"ok": "#005900", "andamento": "#7F3500", "erro": "#990000"}
    return {"ok": "#00FF00", "andamento": "#FFA500", "erro": "#FF0000"}


def sulco(background: Union[str, QColor]) -> str:
    """Trilha da barra de progresso: escura o bastante para o texto branco."""
    bg = background if isinstance(background, QColor) else QColor(background)
    return bg.darker(200).name() if claro(bg) else "#222222"


def _mistura(base: QColor, alvo: QColor, fator: float) -> QColor:
    return QColor(
        int(base.red() + (alvo.red() - base.red()) * fator),
        int(base.green() + (alvo.green() - base.green()) * fator),
        int(base.blue() + (alvo.blue() - base.blue()) * fator),
    )


def gradiente_titulo(accent: Union[str, QColor]) -> Tuple[QColor, QColor]:
    """par início/fim do gradiente da barra de título, como no win98."""
    cor = accent if isinstance(accent, QColor) else QColor(accent)
    branco = QColor("#FFFFFF")
    if claro(cor):
        # acento claro: escurece o início senão texto branco não assenta
        return cor.darker(140), _mistura(cor, branco, 0.45)
    return cor, _mistura(cor, branco, 0.58)


def texto_sobre(cor: Union[str, QColor]) -> str:
    """preto ou branco conforme a luminância da cor de trás."""
    return "#202020" if claro(cor) else "#FFFFFF"


def normal_palette_colors(
    background_color: QColor, accent_color: QColor
) -> Dict[QPalette.ColorRole, QColor]:
    """Define colors for the normal palette state."""
    return {
        QPalette.ColorRole.Window: background_color,
        QPalette.ColorRole.WindowText: accent_color,
        QPalette.ColorRole.Base: background_color.darker(120),
        QPalette.ColorRole.AlternateBase: background_color,
        QPalette.ColorRole.ToolTipBase: accent_color,
        QPalette.ColorRole.ToolTipText: background_color,
        QPalette.ColorRole.Text: accent_color,
        QPalette.ColorRole.Button: background_color,
        QPalette.ColorRole.ButtonText: accent_color,
        QPalette.ColorRole.BrightText: accent_color.lighter(120),
        QPalette.ColorRole.Link: accent_color.lighter(120),
        QPalette.ColorRole.Highlight: accent_color,
        QPalette.ColorRole.HighlightedText: background_color,
        QPalette.ColorRole.PlaceholderText: accent_color.darker(120),
    }


def disabled_palette_colors(
    disabled_bg: QColor, disabled_text: QColor, background_color: QColor
) -> Dict[QPalette.ColorRole, QColor]:
    """Define colors for the disabled palette state."""
    return {
        QPalette.ColorRole.Button: disabled_bg,
        QPalette.ColorRole.ButtonText: disabled_text,
        QPalette.ColorRole.Text: disabled_text,
        QPalette.ColorRole.WindowText: disabled_text,
        QPalette.ColorRole.Base: background_color.darker(140),
    }


def apply_palette(app: QApplication, accent: str, background: str) -> None:
    """Apply the Fusion style and custom color palette to the application."""
    app.setStyle("Fusion")
    dark_palette = QPalette()

    background_color = QColor(background)
    accent_color = QColor(accent)

    # desabilitado perde o negrito e o traco cinza, mas mantem a face normal:
    # face escura com texto escuro deixava a letra invisivel
    if claro(background_color):
        disabled_bg = background_color
        disabled_text = QColor("#4A4A4A")
    else:
        disabled_bg = background_color.darker(200)
        disabled_text = QColor(100, 100, 100)

    # Apply normal colors
    for role, color in normal_palette_colors(background_color, accent_color).items():
        dark_palette.setColor(role, color)

    # Apply disabled colors
    for role, color in disabled_palette_colors(
        disabled_bg, disabled_text, background_color
    ).items():
        dark_palette.setColor(QPalette.ColorGroup.Disabled, role, color)

    app.setPalette(dark_palette)
    _apply_stylesheet(app, background_color, accent_color, disabled_bg, disabled_text)


def _apply_stylesheet(
    app: QApplication,
    bg_color: QColor,
    accent_color: QColor,
    disabled_bg: QColor,
    disabled_text: QColor,
) -> None:
    """Generate and apply the CSS stylesheet."""
    bg_effect = bg_color
    if bg_effect == QColor("#000000"):
        bg_effect = QColor("#282828")

    fundo_hover = bg_color.darker(108) if claro(bg_color) else bg_effect
    fundo_press = bg_color.darker(120) if claro(bg_color) else bg_effect.darker(115)
    texto_hover = (
        accent_color.name()
        if claro(bg_color)
        else accent_color.lighter(150).name()
    )

    # item da lista: hover sobe um degrau; selecao usa o acento como fundo
    item_hover = bg_color.darker(108) if claro(bg_color) else bg_effect.lighter(120)
    selecao_bg = accent_color if claro(bg_color) else bg_effect.lighter(150)
    selecao_fg = bg_color if claro(bg_color) else accent_color

    # relevo win95: branco em cima/esquerda, cinza embaixo/direita. no fundo
    # escuro o acento assume, sem o brilho branco que grita no prata
    realce = QColor("#FFFFFF") if claro(bg_color) else accent_color.lighter(140)
    sombra = QColor("#808080") if claro(bg_color) else accent_color.darker(140)

    borda_relevo = (
        f"border-top: 2px solid {realce.name()};\n"
        f"border-left: 2px solid {realce.name()};\n"
        f"border-bottom: 2px solid {sombra.name()};\n"
        f"border-right: 2px solid {sombra.name()};"
    )

    borda_afundada = (
        f"border-top: 2px solid {sombra.name()};\n"
        f"border-left: 2px solid {sombra.name()};\n"
        f"border-bottom: 2px solid {realce.name()};\n"
        f"border-right: 2px solid {realce.name()};"
    )

    style_sheet = f"""
        QLineEdit {{
            background-color: {bg_color.name()};
            color: {accent_color.name()};
            border: 1px solid {accent_color.name()};
            padding: 8px;
        }}

        QLineEdit:hover {{
            background-color: {fundo_hover.name()};
            color: {accent_color.name()};
        }}

        QCheckBox {{
            background-color: {bg_color.name()};
            color: {accent_color.name()};
            padding: 8px;
            spacing: 8px;
        }}

        QCheckBox::indicator {{
            width: 12px;
            height: 12px;
            background: {bg_color.name()};
            {borda_relevo}
        }}

        QCheckBox::indicator:checked {{
            background: {accent_color.name()};
        }}

        QDialog {{
            background-color: {bg_color.name()};
            color: {accent_color.name()};
        }}

        QListWidget {{
            background-color: {bg_color.darker(120).name()};
            color: {accent_color.name()};
            border-radius: 4px;
            outline: 0;
            border: none;
        }}

        QListWidget::item {{
            background-color: {bg_color.darker(120).name()};
            color: {accent_color.name()};
            border-radius: 4px;
            padding: 6px;
        }}

        QListWidget::item:hover {{
            background-color: {item_hover.name()};
            color: {accent_color.name()};
        }}

        QListWidget::item:selected {{
            background-color: {selecao_bg.name()};
            color: {selecao_fg.name()};
        }}

        QListWidget::item:checked {{
            background-color: {bg_effect.lighter(200).name()};
            color: {accent_color.name()};
            font-weight: bold;
        }}

        QListWidget::item:checked:selected {{
            background-color: {bg_effect.lighter(250).name()};
            color: {accent_color.name()};
        }}

        QListWidget::indicator {{
            {borda_relevo}
            border-radius: 4px;
        }}

        QListWidget::indicator:unchecked {{
            background-color: {bg_color.name()};
        }}

        QListWidget::indicator:checked {{
            background-color: {accent_color.name()};
        }}

        QPushButton {{
            background-color: {bg_color.name()};
            color: {accent_color.name()};
            padding: 6px 6px;
            {borda_relevo}
            font-weight: bold;
        }}

        QPushButton:hover {{
            background-color: {fundo_hover.name()};
            color: {texto_hover};
        }}

        QPushButton:pressed {{
            background-color: {fundo_press.name()};
            color: {accent_color.name()};
            {borda_afundada}
        }}

        QPushButton:disabled {{
            background-color: {disabled_bg.name()};
            color: {disabled_text.name()};
            border: 1px solid {disabled_text.name()};
            font-weight: normal;
        }}

        QPushButton:disabled:hover {{
            background-color: {disabled_bg.name()};
            color: {disabled_text.name()};
        }}

        QLabel {{
            color: {accent_color.name()};
        }}

        QToolTip {{
            background-color: {bg_color.name()};
            color: {accent_color.name()};
            padding: 6px;
        }}
    """
    app.setStyleSheet(style_sheet)


def _resolve_font_path(font_resource: Union[str, Path]) -> Path:
    """Resolve the provided font resource to a concrete Path object."""
    try:
        if isinstance(font_resource, str):
            candidate = Path(font_resource)
            if candidate.is_absolute() and candidate.exists():
                return candidate
            return Paths.resource(font_resource)

        if isinstance(font_resource, Path):
            return font_resource

        return Paths.resource(str(font_resource))
    except TypeError:
        # Fallback for unexpected types
        return Paths.resource(str(font_resource))


def _load_and_set_font(
    app: QApplication, font_path: Path, current_font: Optional[QFont]
) -> Tuple[bool, str]:
    """Load a font file from disk and set it to the application."""
    logger.debug(f"Attempting to load font from: {font_path}")

    if not font_path.exists():
        logger.warning(f"Font file not found at: {font_path}")
        return False, str(font_path)

    font_id = QFontDatabase.addApplicationFont(str(font_path))
    if font_id == -1:
        logger.warning(f"QFontDatabase failed to load font: {font_path}")
        return False, str(font_path)

    families = QFontDatabase.applicationFontFamilies(font_id)
    if not families:
        logger.warning(f"No font families returned for: {font_path}")
        return False, str(font_path)

    font_name = families[0]

    if current_font:
        # Update existing font object with new family
        current_font.setFamily(font_name)
        new_font = current_font
    else:
        # Create new default font
        new_font = QFont(font_name, 10)

    app.setFont(new_font)
    return True, font_name


def apply_font(
    app: QApplication,
    font: Optional[QFont],
    font_file: Optional[Union[str, Path]],
) -> Tuple[bool, Union[str, Path]]:
    """
    Applies the font to the application.

    If font_file is provided, loads that font file and applies it.
    If font is provided (with a family name), checks if it's a system font.
    Otherwise, falls back to a font bundled in res/.
    """
    default_font_file = "W95F.otf"
    embutidas = {"W95FA": "W95F.otf"}

    # Case 1: Specific font file provided
    if font_file:
        path = _resolve_font_path(font_file)
        return _load_and_set_font(app, path, font)

    # Case 2: System font provided
    if font and font.family():
        font_family = font.family()
        if font_family in QFontDatabase.families():
            logger.debug(f"Using system font: {font_family}")
            app.setFont(font)
            return True, font_family

        # System font not found, log and fall through to default
        logger.debug(f"Font family '{font_family}' not found in system, using default")

    # Case 3: família pedida que só existe no res/, carrega ela
    if font and font.family() in embutidas:
        path = _resolve_font_path(embutidas[font.family()])
        return _load_and_set_font(app, path, font)

    # Case 3: Fallback to default font
    path = _resolve_font_path(default_font_file)
    return _load_and_set_font(app, path, font)


def update_appearance(
    app: QApplication,
    accent: str = "#000080",
    background: str = "#c0c0c0",
    font: Optional[QFont] = None,
    font_file: Optional[Union[str, Path]] = None,
) -> Tuple[bool, Union[str, Path]]:
    """
    Apply a dynamic palette and custom font to the application.

    Args:
        app: The QApplication instance.
        accent: Hex string for accent color.
        background: Hex string for background color.
        font: Optional QFont object for settings.
        font_file: Relative resource path to load custom font.
    """
    apply_palette(app, accent, background)
    return apply_font(app, font, font_file)
