from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLayout,
    QMessageBox,
    QVBoxLayout,
)

from ui.bottom_titlebar import ALTURA_BARRA, BottomTitleBar
from ui.frameless import Alcas


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
    return caixa.exec() == QMessageBox.StandardButton.Yes


def aplicar_barra_titulo(dialogo: QDialog) -> None:
    """troca a moldura nativa pela barra win95 e devolve o resize nas bordas."""
    dialogo.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)

    # status e steamless guardam o layout no atributo `layout` e escondem o método
    layout = getattr(dialogo, "layout", None)
    if not isinstance(layout, QLayout):
        layout = dialogo.layout()

    if isinstance(layout, QVBoxLayout):
        # a barra fica fora do layout, de ponta a ponta; o conteúdo só desce
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
