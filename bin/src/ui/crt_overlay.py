"""
OGL or QP CRT effect overlay. Falls back to the original QPainter path when OpenGL or PyOpenGL is absent.

Usage:
    overlay = CRTOverlay(parent, accent_color="#c06c84")
    overlay.set_accent_color("#ff0000")
    overlay.set_enabled(False)

To restart:
    from ui.crt_overlay import restart_crt_overlay
    self.crt_overlay = restart_crt_overlay(
        parent,
        old_overlay,
        settings,
    )
"""
from __future__ import annotations

import ctypes
import logging
import struct
import time as _time
from typing import Optional

from PyQt6.QtCore import QTimer, Qt, QSettings
from PyQt6.QtGui import QColor, QPainter, QSurfaceFormat
from PyQt6.QtWidgets import QWidget

from utils.paths import Paths

logger = logging.getLogger(__name__)

# Optional OpenGL imports
_GL_AVAILABLE = False
try:
    from PyQt6.QtOpenGLWidgets import QOpenGLWidget
    from PyQt6.QtOpenGL import QOpenGLShader, QOpenGLShaderProgram
    import OpenGL.GL as gl
    _GL_AVAILABLE = True
except ImportError:
    pass  # falls through to software renderer


# Shader loading
def _load_shader_source(filename: str) -> str:
    """Load shader source from deps/shaders/filename. Raises FileNotFoundError if missing."""
    shader_path = Paths.deps("shaders") / filename
    if not shader_path.exists():
        raise FileNotFoundError(f"Shader file not found: {shader_path}")
    with open(shader_path, "r", encoding="utf-8") as f:
        source = f.read()
    logger.debug(f"Loaded shader from {shader_path}")
    return source


# Load shaders at module level, will raise FileNotFoundError if missing.
# This happens when the module is imported; the error will be caught and logged and the GL overlay will be marked unavailable.
try:
    _VERT_SRC = _load_shader_source("crt_vert.glsl")
    _FRAG_SRC = _load_shader_source("crt_frag.glsl")
    _SHADERS_LOADED = True
except FileNotFoundError as e:
    logger.error(f"CRT overlay shaders missing: {e}. OpenGL overlay will be disabled.")
    _SHADERS_LOADED = False
    _VERT_SRC = ""
    _FRAG_SRC = ""


class _CRTOverlayGL(QOpenGLWidget):
    """OpenGL shader overlay. Uses QSettings for its configuration."""

    def __init__(self, parent: QWidget | None, settings: QSettings):
        fmt = QSurfaceFormat()
        fmt.setAlphaBufferSize(8)
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)

        super().__init__(parent)
        self.setFormat(fmt)

        self._settings = settings
        self.enabled = self._settings.value("crt_overlay_enabled", True, type=bool)
        self._accent_color = QColor(self._settings.value("accent_color", "#C06C84"))

        # Preset: "preset_a" -> 0, "preset_b" -> 1
        preset_str = self._settings.value("crt_overlay_preset", "preset_a", type=str)
        self._preset = 0 if preset_str == "preset_a" else 1

        # Direction and orientation
        dir_str = self._settings.value(
            "crt_overlay_direction", "top_to_bottom", type=str
        )
        self._horizontal = dir_str in ("left_to_right", "right_to_left")
        if dir_str in ("top_to_bottom", "left_to_right"):
            self._direction = 1.0  # forward (top to bottom | left to right)
        else:
            self._direction = 0.0  # reverse (bottom to top | right to left)

        self._singleband = self._settings.value(
            "crt_overlay_singleband", False, type=bool
        )

        self._t0 = _time.monotonic()
        self._prog: Optional[QOpenGLShaderProgram] = None
        self._vao_id: int = 0
        self._vbo_id: int = 0

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysStackOnTop)
        self.setStyleSheet("background: transparent;")

        if parent:
            self.setGeometry(0, 0, parent.width(), parent.height())

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(33 if self.enabled else 0)

    def set_accent_color(self, color: str) -> None:
        self._accent_color = QColor(color)
        self.update()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if enabled:
            self._timer.start(33)
        else:
            self._timer.stop()
        self.update()

    def set_preset(self, name: str) -> None:
        """Change visual style.
        'preset_a': soft, sine‑wave scanlines.
        'preset_b': harder scanlines, shadow mask.
        """
        name = name.lower()
        if name == "preset_a":
            self._preset = 0
        elif name == "preset_b":
            self._preset = 1
        else:
            return
        self.update()

    def set_direction(self, direction: str) -> None:
        """Set scan direction.
        Allowed: 'top_to_bottom', 'bottom_to_top', 'left_to_right', 'right_to_left'
        """
        self._horizontal = direction in ("left_to_right", "right_to_left")
        if direction in ("top_to_bottom", "left_to_right"):
            self._direction = 1.0
        else:
            self._direction = 0.0
        self.update()

    def set_singleband(self, singleband: bool) -> None:
        self._singleband = singleband
        self.update()

    def initializeGL(self) -> None:
        if not _SHADERS_LOADED:
            logger.error("Cannot initialize GL overlay: shaders not loaded.")
            self._prog = None
            return
        self._build_shader()
        self._build_geometry()
        gl.glClearColor(0.0, 0.0, 0.0, 0.0)

    def resizeGL(self, w: int, h: int) -> None:
        gl.glViewport(0, 0, w, h)

    def paintGL(self) -> None:
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)

        if not self.enabled or self._prog is None or not _SHADERS_LOADED:
            return

        elapsed = float(_time.monotonic() - self._t0)

        self._prog.bind()
        self._prog.setUniformValue("uTime", elapsed)
        self._prog.setUniformValue("uRes", float(self.width()), float(self.height()))
        self._prog.setUniformValue("uPreset", self._preset)
        self._prog.setUniformValue("uDirection", self._direction)
        self._prog.setUniformValue("uHorizontal", self._horizontal)
        self._prog.setUniformValue("uSingleBand", self._singleband)
        self._prog.setUniformValue(
            "uAccent",
            self._accent_color.redF(),
            self._accent_color.greenF(),
            self._accent_color.blueF(),
        )

        gl.glBindVertexArray(self._vao_id)
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glDrawArrays(gl.GL_TRIANGLE_STRIP, 0, 4)

        gl.glBindVertexArray(0)
        self._prog.release()

    def _build_shader(self) -> None:
        self._prog = QOpenGLShaderProgram(self)
        ok  = self._prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex,   _VERT_SRC)
        ok &= self._prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, _FRAG_SRC)
        ok &= self._prog.link()
        if not ok:
            logger.error(f"[CRTOverlay] shader error: {self._prog.log()}")
            self._prog = None

    def _build_geometry(self) -> None:
        """Upload a full-screen quad as a triangle strip (4 vertices)."""
        vertices = struct.pack(
            "8f",
            -1.0, -1.0,     # bottom-left
            1.0, -1.0,          # bottom-right
            -1.0, 1.0,          # top-left
            1.0, 1.0,           # top-right
        )

        # VAO
        # glGenVertexArrays(1) returns a numpy scalar OR a 1-element array
        # depending on PyOpenGL version.  numpy scalars have __getitem__ but
        # NOT __len__, so we key off __len__ to tell them apart.
        raw_vao = gl.glGenVertexArrays(1)
        self._vao_id = int(raw_vao[0]) if hasattr(raw_vao, "__len__") else int(raw_vao)
        gl.glBindVertexArray(self._vao_id)

        # VBO
        raw_vbo = gl.glGenBuffers(1)
        self._vbo_id = int(raw_vbo[0]) if hasattr(raw_vbo, "__len__") else int(raw_vbo)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._vbo_id)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, len(vertices), vertices, gl.GL_STATIC_DRAW)

        # layout(location = 0) in vec2 aPos
        gl.glVertexAttribPointer(0, 2, gl.GL_FLOAT, gl.GL_FALSE, 8, ctypes.c_void_p(0))
        gl.glEnableVertexAttribArray(0)

        gl.glBindVertexArray(0)


class _CRTOverlaySW(QWidget):
    """QPainter fallback used when OpenGL / PyOpenGL is unavailable."""

    def __init__(self, parent: QWidget | None, settings: QSettings):
        super().__init__(parent)
        self._settings = settings
        self.enabled = self._settings.value("crt_overlay_enabled", True, type=bool)
        self._accent_color = QColor(self._settings.value("accent_color", "#C06C84"))
        dir_str = self._settings.value("crt_overlay_direction", "top_to_bottom", type=str)
        self._direction = 1.0 if dir_str == "top_to_bottom" else 0.0
        self.scanline_offset = 0

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setStyleSheet("background-color: transparent;")
        if parent:
            self.setGeometry(0, 0, parent.width(), parent.height())

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50 if self.enabled else 0)

    def set_accent_color(self, color: str) -> None:
        self._accent_color = QColor(color)
        self.update()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if enabled:
            self._timer.start(50)
        else:
            self._timer.stop()
        self.update()

    def set_preset(self, name: str) -> None:
        """Presets only affect the GL path, QP fallback uses a simple moving bar.  We respect the direction change though."""
        name = name.lower()
        if name == "lottes" or name == "b":
            self._direction = 1.0      # top -> bottom
        else:
            self._direction = 0.0      # bottom -> top
        self.update()

    def set_singleband(self, singleband: bool):
        # singleband already
        return

    def _tick(self) -> None:
        if not self.enabled:
            return
        step = 6 if self._direction == 0.0 else -6
        self.scanline_offset = (self.scanline_offset + step) % max(1, self.height())
        self.update()

    def paintEvent(self, event) -> None:
        if not self.enabled:
            return
        painter = QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)
        r, g, b = (
            self._accent_color.red(),
            self._accent_color.green(),
            self._accent_color.blue(),
        )
        for y in range(0, self.height(), 8):
            painter.setBrush(QColor(r, g, b, 20))
            painter.drawRect(0, y, self.width(), 4)
        painter.setBrush(QColor(r, g, b, 10))
        painter.drawRect(0, self.scanline_offset, self.width(), 6)


def CRTOverlay(parent: QWidget | None, settings: QSettings) -> QWidget:
    """
    Return an available CRT overlay.

    - OpenGL and PyOpenGL present == GPU shader path        (_CRTOverlayGL)
    - Otherwise                   == QPainter software path (_CRTOverlaySW)

    Both implement the same API:
        .set_accent_color(str)
        .set_enabled(bool)
        .set_preset(str)
        .set_singleband(bool)
        .setGeometry(x, y, w, h)
    """
    force_sw = settings.value("crt_overlay_fsw", False, type=bool)
    force_gl = settings.value("crt_overlay_fgl", False, type=bool)

    if force_sw:
        return _CRTOverlaySW(parent, settings)
    if (force_gl or _GL_AVAILABLE) and _SHADERS_LOADED:
        return _CRTOverlayGL(parent, settings)
    if _GL_AVAILABLE and not _SHADERS_LOADED:
        logger.warning("OpenGL available but shaders missing – falling back to software overlay.")
    return _CRTOverlaySW(parent, settings)


def restart_crt_overlay(
    parent: QWidget,
    old_overlay: Optional[QWidget],
    settings: QSettings,
) -> QWidget:
    """
    Safely replace an existing CRT overlay with a new one.
    Handles deletion, etc. and then returns the new overlay.
    """
    if old_overlay is not None:
        old_overlay.hide()
        old_overlay.deleteLater()

    new_overlay = CRTOverlay(parent, settings)
    new_overlay.setGeometry(0, 0, parent.width(), parent.height())
    new_overlay.raise_()  # ensure it sits above other children
    new_overlay.show()

    return new_overlay