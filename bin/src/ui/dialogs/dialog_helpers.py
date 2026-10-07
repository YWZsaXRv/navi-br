from PyQt6.QtCore import QEvent, QItemSelectionModel, QObject, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLayout,
    QMessageBox,
)

from ui.bottom_titlebar import ALTURA_BARRA, BottomTitleBar
from ui.frameless import Alcas


def traduz_rotulos(dialogo, mapa, titulo=None):
    """renomeia título, rótulos, grupos e botões do diálogo nativo do qt (pt-br)."""
    if titulo is not None:
        dialogo.setWindowTitle(titulo)
    for rotulo in dialogo.findChildren(QLabel):
        novo = mapa.get(rotulo.text())
        if novo is not None:
            rotulo.setText(novo)
    for grupo in dialogo.findChildren(QGroupBox):
        novo = mapa.get(grupo.title())
        if novo is not None:
            grupo.setTitle(novo)
    for botao in dialogo.findChildren(QAbstractButton):
        novo = mapa.get(botao.text())
        if novo is not None:
            botao.setText(novo)


class FiltroVimListas(QObject):
    """j/k linha a linha em listas: o Qt usa j/k como busca incremental
    e engole a tecla antes do diálogo ver. secoes=True: h/l e setas
    esquerda/direita trocam de lista (seção) dentro do mesmo diálogo."""

    def __init__(self, parent=None, secoes=False, ao_topo=None):
        super().__init__(parent)
        self.secoes = secoes
        self.ao_topo = ao_topo

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Type.KeyPress:
            return False
        if not isinstance(obj, QAbstractItemView):
            return False

        k = event.key()

        if k in (Qt.Key.Key_J, Qt.Key.Key_K):
            modelo = obj.model()
            cnt = modelo.rowCount() if modelo is not None else 0
            cur = obj.currentIndex().row() if obj.currentIndex().isValid() else -1
            if k == Qt.Key.Key_J:
                if cnt:
                    self._vai_para(obj, modelo, min(cnt - 1, cur + 1))
            else:
                if cur <= 0 and self.ao_topo is not None:
                    self.ao_topo()
                elif cnt:
                    self._vai_para(obj, modelo, max(0, cur - 1))
            return True

        if self.secoes and k in (
            Qt.Key.Key_H,
            Qt.Key.Key_L,
            Qt.Key.Key_Left,
            Qt.Key.Key_Right,
        ):
            vistas = [
                v
                for v in obj.window().findChildren(QAbstractItemView)
                if v.isVisibleTo(obj.window())
            ]
            vistas.sort(key=lambda v: (v.mapTo(obj.window(), v.rect().topLeft()).y(),
                                       v.mapTo(obj.window(), v.rect().topLeft()).x()))
            if vistas:
                alvo = None
                for i, v in enumerate(vistas):
                    if v is obj:
                        if k in (Qt.Key.Key_L, Qt.Key.Key_Right):
                            alvo = vistas[(i + 1) % len(vistas)]
                        else:
                            alvo = vistas[(i - 1) % len(vistas)]
                        break
                if alvo is not None:
                    alvo.setFocus()
                    return True
            return False

        return False

    @staticmethod
    def _vai_para(view, modelo, nr):
        idx = modelo.index(nr, 0)
        view.setCurrentIndex(idx)
        sel = view.selectionModel()
        if sel is not None:
            sel.setCurrentIndex(
                idx, QItemSelectionModel.SelectionFlag.ClearAndSelect
            )


def tira_icones_padrao(widgeto) -> None:
    """ok e cancelar saem com ícone do estilo; aqui é texto puro."""
    if isinstance(widgeto, (QDialogButtonBox, QMessageBox)):
        caixas = [widgeto]
    else:
        caixas = widgeto.findChildren(QDialogButtonBox)
    for caixa in caixas:
        for botao in caixa.buttons():
            botao.setIcon(QIcon())


def create_accept_button(on_accept):
    # cancelar e fechar são o x da barra: sobra só o que salva
    buttons = QDialogButtonBox()
    ok_btn = buttons.addButton(QDialogButtonBox.StandardButton.Ok)
    ok_btn.setText("OK")
    tira_icones_padrao(buttons)
    buttons.accepted.connect(on_accept)
    return buttons


def pergunta_sim_nao(parent, titulo, texto, sim_por_padrao=True) -> bool:
    """pergunta sim/não em pt-br, sem o ícone que desloca o texto."""
    caixa = QMessageBox(parent)
    caixa.setWindowTitle(titulo)
    caixa.setText(texto)
    caixa.setStandardButtons(
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    caixa.button(QMessageBox.StandardButton.Yes).setText("Sim")
    caixa.button(QMessageBox.StandardButton.No).setText("Não")
    padrao = (
        QMessageBox.StandardButton.Yes
        if sim_por_padrao
        else QMessageBox.StandardButton.No
    )
    caixa.setDefaultButton(padrao)
    leiaute = caixa.layout()
    if isinstance(leiaute, QGridLayout):
        # sem ícone o qt deixa um vão na coluna 0 que empurra o texto
        espacador = leiaute.itemAtPosition(0, 0)
        if espacador is not None:
            leiaute.removeItem(espacador)
        leiaute.setHorizontalSpacing(0)
        leiaute.setColumnStretch(0, 0)
        leiaute.setColumnStretch(1, 1)
    tira_icones_padrao(caixa)
    aplicar_barra_titulo(caixa)
    return caixa.exec() == QMessageBox.StandardButton.Yes


def aplicar_barra_titulo(dialogo: QDialog) -> None:
    """troca a moldura nativa pela barra win95 e devolve o resize nas bordas."""
    dialogo.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)

    # status e steamless guardam o layout no atributo `layout` e escondem o método
    layout = getattr(dialogo, "layout", None)
    if not isinstance(layout, QLayout):
        layout = dialogo.layout()

    if isinstance(layout, QLayout):
        # a barra fica fora do layout, de ponta a ponta; o conteúdo só desce
        # (qbox, grid...: o messagebox dos sim/não é grid)
        margens = layout.contentsMargins()
        layout.setContentsMargins(
            margens.left(),
            margens.top() + ALTURA_BARRA,
            margens.right(),
            margens.bottom(),
        )

    barra = BottomTitleBar(
        dialogo,
        com_acoes=False,
        com_minimizar=False,
        com_maximizar=False,
    )
    barra.setGeometry(0, 0, dialogo.width(), ALTURA_BARRA)
    barra.show()
    dialogo.barra_titulo = barra

    # tudo no mesmo tamanho: cola no topo da mãe e parece uma janela só
    pai = dialogo.parentWidget()
    destino = pai.geometry().topLeft() if pai is not None else None
    if destino is not None:
        dialogo.move(destino)

    # sem moldura nativa não sobra resize: as alças em volta repõem
    dialogo.alcas = Alcas(dialogo)
    dialogo.acompanha_barra = _AcompanhaBarra(barra, dialogo, destino)


class _AcompanhaBarra(QObject):
    """barra colada no topo e janela em cima da mãe, em qualquer largura."""

    def __init__(self, barra: BottomTitleBar, janela: QDialog, destino):
        super().__init__(janela)
        self.barra = barra
        self.janela = janela
        self.destino = destino
        self._encaixes = 0
        janela.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.janela:
            tipo = event.type()
            if tipo == QEvent.Type.Resize:
                self.barra.setGeometry(0, 0, self.janela.width(), ALTURA_BARRA)
            elif tipo == QEvent.Type.Move and self._encaixes < 3:
                # depois do show o wm recoloca a flutuante uns pixels pra baixo e
                # aparece a barra da janela de trás; devolve na hora
                if self.destino is not None and self.janela.pos() != self.destino:
                    self._encaixes += 1
                    self.janela.move(self.destino)
        return super().eventFilter(obj, event)
