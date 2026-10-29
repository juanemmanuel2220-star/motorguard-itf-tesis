"""
Piezas de interfaz del diseño (tarjetas, chips, botones segmentados, filas clave-valor).
El aspecto lo da la hoja de estilos de ui/tema.py a través de propiedades dinámicas (rol, variante...).
"""

from typing import Callable, Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from motorguard_dashboard.ui.tema import repulir


def etiqueta(texto: str = "", rol: Optional[str] = None, **props) -> QLabel:
    lbl = QLabel(texto)
    if rol:
        lbl.setProperty("rol", rol)
    for k, v in props.items():
        lbl.setProperty(k, v)
    return lbl


def poner_prop(w, nombre: str, valor):
    if w.property(nombre) != valor:
        w.setProperty(nombre, valor)
        repulir(w)


def chip(texto: str = "", estado: Optional[str] = None) -> QLabel:
    c = etiqueta(texto, "chip")
    if estado:
        c.setProperty("estado", estado)
    c.setAlignment(Qt.AlignCenter)
    return c


def boton(texto: str, variante: Optional[str] = None) -> QPushButton:
    b = QPushButton(texto)
    if variante:
        b.setProperty("variante", variante)
    b.setCursor(Qt.PointingHandCursor)
    return b


def separador() -> QFrame:
    s = QFrame()
    s.setProperty("rol", "separador")
    return s


def tarjeta(titulo: Optional[str] = None, subtitulo: Optional[str] = None, rol: str = "tarjeta",
            margen: Tuple[int, int, int, int] = (22, 20, 22, 20), espacio: int = 12,
            extra: Optional[QWidget] = None) -> Tuple[QFrame, QVBoxLayout]:
    marco = QFrame()
    marco.setProperty("rol", rol)
    lay = QVBoxLayout(marco)
    lay.setContentsMargins(*margen)
    lay.setSpacing(espacio)
    if titulo:
        cab = QHBoxLayout()
        cab.setSpacing(8)
        cab.addWidget(etiqueta(titulo, "tituloTarjeta"))
        cab.addStretch()
        if subtitulo:
            cab.addWidget(etiqueta(subtitulo, "secundario"))
        if extra is not None:
            cab.addWidget(extra)
        lay.addLayout(cab)
    return marco, lay


class BotonesZoom(QWidget):
    """Botones − / + / Ajustar para una gráfica de pyqtgraph (pedido por el autor, 17-oct).

    modo "tiempo": + muestra la mitad del tiempo y − el doble, siguiendo siempre el dato más reciente (llamar a
    aplicar() después de cada actualización); el eje Y se ajusta a lo visible. Ajustar vuelve a todo el historial.
    modo "libre": + y − acercan y alejan alrededor del centro; Ajustar encuadra todo."""

    FACTOR = 0.5

    def __init__(self, plot, modo: str = "libre", parent=None):
        super().__init__(parent)
        self.plot, self.modo = plot, modo
        self.ventana: Optional[float] = None          # segundos visibles (modo tiempo); None = todo
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.botones = {}
        for clave, texto, ayuda in (("menos", "−", "Alejar"), ("mas", "+", "Acercar"),
                                    ("ajustar", "Ajustar", "Ver todo")):
            b = boton(texto, "zoom")
            b.setToolTip(ayuda)
            b.setFixedHeight(30)
            if clave != "ajustar":
                b.setFixedWidth(36)
            else:
                b.setStyleSheet("font-size: 13px;")
            b.clicked.connect(lambda _=False, c=clave: self._clic(c))
            lay.addWidget(b)
            self.botones[clave] = b

    def _clic(self, clave: str):
        vb = self.plot.getViewBox()
        if clave == "ajustar":
            self.ventana = None
            vb.enableAutoRange()
            return
        if self.modo == "libre":
            f = self.FACTOR if clave == "mas" else 1 / self.FACTOR
            vb.scaleBy((f, f))
            return
        (x0, x1), _ = vb.viewRange()
        actual = self.ventana or (x1 - x0)
        self.ventana = max(5.0, actual * (self.FACTOR if clave == "mas" else 1 / self.FACTOR))
        self.aplicar()

    def aplicar(self):
        """Modo tiempo: muestra los últimos `ventana` segundos y ajusta Y a lo visible."""
        if self.modo != "tiempo" or self.ventana is None:
            return
        vb = self.plot.getViewBox()
        limites = vb.childrenBounds()[0]
        if not limites:
            return
        fin = limites[1]
        vb.setAutoVisible(y=True)
        vb.enableAutoRange(axis="y")
        vb.setXRange(fin - self.ventana, fin, padding=0)


class Segmentado(QWidget):
    """Botón segmentado exclusivo (p. ej. Sistema | Claro | Oscuro)."""
    elegido = Signal(str)

    def __init__(self, opciones: Sequence[Tuple[str, str]], actual: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.grupo = QButtonGroup(self)
        self.grupo.setExclusive(True)
        self.botones: Dict[str, QPushButton] = {}
        for i, (clave, texto) in enumerate(opciones):
            b = boton(texto, "seg")
            b.setCheckable(True)
            pos = "ini" if i == 0 else ("fin" if i == len(opciones) - 1 else "medio")
            b.setProperty("pos", pos)
            # Las esquinas van en la hoja propia del botón: en la global Qt no siempre las respeta por esquina
            if pos == "ini":
                b.setStyleSheet("QPushButton { border-top-left-radius: 19px; border-bottom-left-radius: 19px; }")
            elif pos == "fin":
                b.setStyleSheet("QPushButton { border-top-right-radius: 19px; border-bottom-right-radius: 19px; }")
            b.setChecked(clave == actual)
            b.clicked.connect(lambda _=False, c=clave: self.elegido.emit(c))
            self.grupo.addButton(b)
            lay.addWidget(b)
            self.botones[clave] = b

    def marcar(self, clave: str):
        if clave in self.botones:
            self.botones[clave].setChecked(True)


class FilasValor(QWidget):
    """Lista de filas 'etiqueta ........ valor' con divisores, como en las tarjetas del diseño."""

    def __init__(self, claves: List[Tuple[str, str]], parent=None):
        """claves: [(id, etiqueta visible)]"""
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.valores: Dict[str, QLabel] = {}
        for clave, texto in claves:
            lay.addWidget(separador())
            fila = QHBoxLayout()
            fila.setContentsMargins(0, 7, 0, 7)
            fila.addWidget(etiqueta(texto, "secundario"))
            fila.addStretch()
            v = etiqueta("—", "mono")
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            fila.addWidget(v)
            lay.addLayout(fila)
            self.valores[clave] = v


def expandir_horizontal(w: QWidget):
    w.setSizePolicy(QSizePolicy.Expanding, w.sizePolicy().verticalPolicy())


class EscalaSeveridad(QWidget):
    """Barra LEVE | INTER | SEVERA con los umbrales del clasificador embebido y un marcador en la ML actual.
    Escala de 0 a 8 pp; umbrales 1.626 y 4.471 pp (detector_dir.h, DIR_SEV_U1/U2)."""
    U1, U2, MAXIMO = 1.626, 4.471, 8.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(22)
        self.ml: Optional[float] = None
        self.colores = ("#7A5300", "#A3410C", "#B3261E", "#3B1500")   # leve, inter, severa, marcador

    def poner(self, ml: Optional[float], colores: Optional[Tuple[str, str, str, str]] = None):
        self.ml = ml
        if colores:
            self.colores = colores
        self.update()

    def paintEvent(self, _):
        from PySide6.QtGui import QColor, QPainter, QPainterPath
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        y, alto, hueco = (h - 10) / 2, 10, 3
        cortes = [0, self.U1 / self.MAXIMO * w, self.U2 / self.MAXIMO * w, w]
        for k in range(3):
            x0 = cortes[k] + (hueco / 2 if k else 0)
            x1 = cortes[k + 1] - (hueco / 2 if k < 2 else 0)
            camino = QPainterPath()
            camino.addRoundedRect(x0, y, x1 - x0, alto, 5 if k in (0, 2) else 1, 5 if k in (0, 2) else 1)
            p.fillPath(camino, QColor(self.colores[k]))
        if self.ml is not None:
            x = max(2.0, min(w - 2.0, self.ml / self.MAXIMO * w))
            marca = QPainterPath()
            marca.addRoundedRect(x - 2, 0, 4, h, 2, 2)
            p.fillPath(marca, QColor(self.colores[3]))
        p.end()
