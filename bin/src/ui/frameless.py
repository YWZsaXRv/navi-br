from typing import Dict

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QWidget

# mesma folga da barra: o miolo de 6px não arrasta nem redimensiona
LARGURA_ALCA = 6

ARESTAS = (
    "top_left",
    "top_right",
    "bottom_left",
    "bottom_right",
    "left",
    "right",
    "top",
    "bottom",
)

_CURSOR = {
    "left": Qt.CursorShape.SizeHorCursor,
    "right": Qt.CursorShape.SizeHorCursor,
    "top": Qt.CursorShape.SizeVerCursor,
    "bottom": Qt.CursorShape.SizeVerCursor,
    "top_left": Qt.CursorShape.SizeFDiagCursor,
    "top_right": Qt.CursorShape.SizeBDiagCursor,
    "bottom_left": Qt.CursorShape.SizeBDiagCursor,
    "bottom_right": Qt.CursorShape.SizeFDiagCursor,
}

_ARESTA_QT = {
    "left": Qt.Edge.LeftEdge,
    "right": Qt.Edge.RightEdge,
    "top": Qt.Edge.TopEdge,
    "bottom": Qt.Edge.BottomEdge,
    "top_left": Qt.Edge.LeftEdge | Qt.Edge.TopEdge,
    "top_right": Qt.Edge.RightEdge | Qt.Edge.TopEdge,
    "bottom_left": Qt.Edge.LeftEdge | Qt.Edge.BottomEdge,
    "bottom_right": Qt.Edge.RightEdge | Qt.Edge.BottomEdge,
}


def cursor_da_aresta(aresta: str) -> Qt.CursorShape:
    return _CURSOR.get(aresta, Qt.CursorShape.ArrowCursor)


class Alca(QWidget):
    """bloco invisível numa borda: o arraste redimensiona a janela."""

    def __init__(self, aresta: str, janela: QWidget):
        super().__init__(janela)
        self.aresta = aresta
        self.janela = janela
        self._arrastando = False
        self._origem = None
        self._geometria = None
        self.setStyleSheet("background: transparent;")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return

        handle = self.janela.windowHandle()

        # o sistema faz melhor (borda viva, snap); sem ele a gente arrasta na mão
        if handle and handle.isExposed() and handle.startSystemResize(self._aresta_qt()):
            event.accept()
            return

        self._arrastando = True
        self._origem = event.globalPosition().toPoint()
        self._geometria = self.janela.geometry()
        self.grabMouse()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._arrastando:
            return

        delta = event.globalPosition().toPoint() - self._origem
        x, y, w, h = (
            self._geometria.x(),
            self._geometria.y(),
            self._geometria.width(),
            self._geometria.height(),
        )

        if "right" in self.aresta:
            w += delta.x()
        if "bottom" in self.aresta:
            h += delta.y()
        if "left" in self.aresta:
            x += delta.x()
            w -= delta.x()
        if "top" in self.aresta:
            y += delta.y()
            h -= delta.y()

        w = max(w, self.janela.minimumWidth())
        h = max(h, self.janela.minimumHeight())
        self.janela.setGeometry(x, y, w, h)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._arrastando:
            self.releaseMouse()
            self._arrastando = False
        event.accept()

    def _aresta_qt(self) -> Qt.Edge:
        return _ARESTA_QT.get(self.aresta, Qt.Edge.RightEdge)


class Alcas(QObject):
    """as oito alças em volta de uma janela sem moldura."""

    def __init__(self, janela: QWidget):
        super().__init__(janela)
        self.janela = janela
        self.blocos: Dict[str, Alca] = {}
        for aresta in ARESTAS:
            bloco = Alca(aresta, janela)
            bloco.setCursor(cursor_da_aresta(aresta))
            self.blocos[aresta] = bloco

        janela.installEventFilter(self)
        self.atualizar()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.janela and event.type() == QEvent.Type.Resize:
            self.atualizar()
        return super().eventFilter(obj, event)

    def atualizar(self) -> None:
        largura, altura = self.janela.width(), self.janela.height()
        a = LARGURA_ALCA
        geometrias = {
            "top_left": (0, 0, a, a),
            "top_right": (largura - a, 0, a, a),
            "bottom_left": (0, altura - a, a, a),
            "bottom_right": (largura - a, altura - a, a, a),
            "left": (0, a, a, altura - 2 * a),
            "right": (largura - a, a, a, altura - 2 * a),
            "top": (a, 0, largura - 2 * a, a),
            "bottom": (a, altura - a, largura - 2 * a, a),
        }
        for nome, (x, y, larg, alt) in geometrias.items():
            bloco = self.blocos.get(nome)
            if bloco:
                bloco.setGeometry(x, y, larg, alt)
                bloco.raise_()
