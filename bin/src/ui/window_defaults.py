"""tamanho padrão de todas as janelas."""

from typing import Optional

from PyQt6.QtWidgets import QWidget

# trocar aqui quando quiser mais ou menos
LARGURA = 560
ALTURA = 660

# recuo lateral de tudo que fica na parte de baixo (bate com a barra de progresso)
RECUO_LATERAL = 20
# espaço vertical entre blocos vizinhos: rodapé, botões da fila e título
GAP = 8


def aplicar(widget: QWidget, parent: Optional[QWidget] = None) -> None:
    """fixa o tamanho padrão e centraliza na janela mãe."""
    widget.setMinimumSize(LARGURA, ALTURA)
    widget.resize(LARGURA, ALTURA)

    if parent is None:
        return

    quadro = widget.frameGeometry()
    quadro.moveCenter(parent.frameGeometry().center())
    widget.move(quadro.topLeft())
