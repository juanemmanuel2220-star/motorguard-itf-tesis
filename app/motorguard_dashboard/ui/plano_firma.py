"""
Tarjeta "Plano de la firma" (Monitoreo): el método del detector direccional dibujado en el plano complejo.

- Estela de z = R2/|I1| (pp de |I1|, referida a arg(V1)) de los últimos ~30 s.
- Referencia móvil (mediana de z entre t-11 y t-6 s) y la flecha dz = z - referencia.
- Dirección de falla (-81.4°) desde la referencia, la línea del umbral (P = 0.40 pp) y la zona de alarma.
- Proyección de dz sobre la dirección de falla: su largo es P.
- Con la alarma enclavada: base congelada y anillos de severidad (|z - base| = 1.626 y 4.471 pp).
- A la derecha, los fasores de secuencia que manda el firmware (V1 de referencia, V2 ampliado) y valores.

La geometría la recalcula telemetry/firma.py a partir del campo RAW; las decisiones que se muestran (P, C,
SEV, ML) son siempre las del firmware. Si la P recalculada no coincide, se avisa "referencia aproximada".
"""

import math
import time
from typing import List, Optional

import pyqtgraph as pg
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPolygonF
from PySide6.QtWidgets import QGraphicsPolygonItem, QHBoxLayout, QVBoxLayout, QWidget

from motorguard_dashboard.telemetry.firma import (
    ANG_FALLA_DEG, DIR_FALLA, SEV_U1, SEV_U2, UMBRAL_PP, EstadoFirma, PlanoFirma,
)
from motorguard_dashboard.telemetry.parser import NOMBRES_SEV, Trama
from motorguard_dashboard.ui.componentes import FilasValor, etiqueta, poner_prop, tarjeta
from motorguard_dashboard.ui.tema import estilizar_plot

NIVELES_ESTELA = 18
AMPLIA_V2 = 10.0           # V2 se dibuja 10 veces más grande que V1 (si no, no se ve: U2V ~ 1-5 %)
SPAN_MIN_PP = 1.2          # ventana mínima del plano (pp)
DIBUJO_MIN_S = 0.15        # en reproducciones aceleradas se redibuja como mucho cada 150 ms (~19 ms por dibujo)
PERP = DIR_FALLA * 1j      # perpendicular a la dirección de falla


def proyectar_perp(d: complex) -> float:
    """Componente de d perpendicular a la dirección de falla."""
    return d.real * PERP.real + d.imag * PERP.imag


def _color(hex_, alfa: float) -> QColor:
    c = QColor(hex_)
    c.setAlphaF(alfa)
    return c


def _circulo(c: complex, r: float, n: int = 120):
    ang = [2 * math.pi * k / n for k in range(n + 1)]
    return [c.real + r * math.cos(a) for a in ang], [c.imag + r * math.sin(a) for a in ang]


def _flecha(a: complex, b: complex, cabeza: float):
    """Segmento a->b con punta, como listas x, y separadas por NaN."""
    nan = float("nan")
    xs, ys = [a.real, b.real, nan], [a.imag, b.imag, nan]
    d = b - a
    if abs(d) > 1e-9:
        u = d / abs(d)
        for giro in (math.radians(155), math.radians(-155)):
            p = b + cabeza * u * complex(math.cos(giro), math.sin(giro))
            xs += [b.real, p.real, nan]
            ys += [b.imag, p.imag, nan]
    return xs, ys


class PlanoFirmaTarjeta(QWidget):
    def __init__(self, tema=None, parent=None):
        super().__init__(parent)
        self.t = tema.t if tema else None
        self.calculo = PlanoFirma()
        self.estado: Optional[EstadoFirma] = None
        self._pendiente = False
        self._rango = None             # (cx, cy, span) del plano
        self._brochas: List = []
        self._t_dibujo = 0.0
        self._diferido = QTimer(self)
        self._diferido.setSingleShot(True)
        self._diferido.timeout.connect(self.mostrar_pendiente)
        self._construir()

    # ================================================================== interfaz
    def _construir(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        caja, lc = tarjeta()
        lay.addWidget(caja)
        cab = QHBoxLayout()
        tit = QVBoxLayout()
        tit.setSpacing(2)
        tit.addWidget(etiqueta("Plano de la firma", "tituloTarjeta"))
        tit.addWidget(etiqueta("z = R2/|I1| en pp de |I1|, referida a la fase de V1 · método de detector_dir.h",
                               "secundario"))
        cab.addLayout(tit)
        cab.addStretch()
        lc.addLayout(cab)
        self.leyenda = etiqueta("", "etiqueta")
        self.leyenda.setTextFormat(Qt.RichText)
        self.leyenda.setWordWrap(True)

        fila = QHBoxLayout()
        fila.setSpacing(16)
        self.plot = pg.PlotWidget()
        self.plot.setMinimumHeight(420)
        self.plot.setAspectLocked(True)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.hideButtons()
        for eje, texto in (("bottom", "Re{z}"), ("left", "Im{z}")):
            self.plot.setLabel(eje, texto, units="pp")
            self.plot.getAxis(eje).enableAutoSIPrefix(False)
        fila.addWidget(self.plot, 3)

        self.zona = QGraphicsPolygonItem()
        self.zona.setPen(pg.mkPen(None))
        self.plot.addItem(self.zona)
        self.anillos = [self.plot.plot([], []), self.plot.plot([], [])]
        self.textos_anillo = [pg.TextItem(anchor=(0.5, 1)), pg.TextItem(anchor=(0.5, 1))]
        self.dir_falla = self.plot.plot([], [])
        self.texto_dir = pg.TextItem(anchor=(0, 0.5))
        self.umbral = pg.InfiniteLine(angle=ANG_FALLA_DEG + 90, movable=False)
        self.plot.addItem(self.umbral)
        self.linea_estela = self.plot.plot([], [])
        self.estela = pg.ScatterPlotItem(size=7)
        self.plot.addItem(self.estela)
        self.proyeccion = self.plot.plot([], [])
        self.pie = pg.ScatterPlotItem(size=7, symbol="s")
        self.plot.addItem(self.pie)
        self.texto_p = pg.TextItem(anchor=(1, 0.5))
        self.linea_ml = self.plot.plot([], [])
        self.flecha = self.plot.plot([], [], connect="finite")
        self.ref = pg.ScatterPlotItem(size=13, symbol="o")
        self.plot.addItem(self.ref)
        self.base = pg.ScatterPlotItem(size=13, symbol="d")
        self.plot.addItem(self.base)
        self.actual = pg.ScatterPlotItem(size=11, symbol="o")
        self.plot.addItem(self.actual)
        for ti in self.textos_anillo + [self.texto_dir, self.texto_p]:
            self.plot.addItem(ti)

        der = QVBoxLayout()
        der.setSpacing(8)
        der.addWidget(etiqueta("Fasores de secuencia (RAW)", "etiqueta"))
        self.plot_sec = pg.PlotWidget()
        self.plot_sec.setFixedSize(230, 230)
        self.plot_sec.setAspectLocked(True)
        self.plot_sec.setMouseEnabled(x=False, y=False)
        self.plot_sec.hideButtons()
        self.plot_sec.hideAxis("left")
        self.plot_sec.hideAxis("bottom")
        self.plot_sec.setRange(xRange=(-1.15, 1.15), yRange=(-1.15, 1.15), padding=0)
        self.circ_sec = self.plot_sec.plot(*_circulo(0j, 1.0))
        self.f_v1 = self.plot_sec.plot([], [], connect="finite")
        self.f_v2 = self.plot_sec.plot([], [], connect="finite")
        self.t_v1 = pg.TextItem(anchor=(1, 0))
        self.t_v2 = pg.TextItem(anchor=(0, 0))
        for ti in (self.t_v1, self.t_v2):
            self.plot_sec.addItem(ti)
        der.addWidget(self.plot_sec, 0, Qt.AlignHCenter)
        self.valores = FilasValor([("p", "P firmware / recalculada"), ("dz", "|dz| (pp)"), ("ml", "ML firmware (pp)"),
                                   ("z", "z (pp)"), ("v", "|V1| · U2V"), ("i", "|I1| · |R2|")])
        der.addWidget(self.valores)
        der.addStretch()
        cont = QWidget()
        cont.setLayout(der)
        cont.setFixedWidth(300)
        fila.addWidget(cont)
        lc.addLayout(fila)
        lc.addWidget(self.leyenda)

        self.lbl_nota = etiqueta("", "secundario")
        self.lbl_nota.setWordWrap(True)
        lc.addWidget(self.lbl_nota)
        ayuda = etiqueta(
            "Cómo leerlo: cada punto es un bloque (~1.7 s). La flecha va de la referencia móvil a la firma actual "
            "(dz). P es la sombra de dz sobre la dirección de falla: si la punta pasa la línea roja durante 3 bloques "
            "seguidos (~5 s), el firmware confirma la alarma, congela la base y mide la severidad con la distancia "
            "de z a la base (anillos). Un cambio de carga mueve z en otra dirección y casi no cambia P. "
            "V2 se dibuja ×10; el ángulo de I1 no viene en la trama.", "secundario")
        ayuda.setWordWrap(True)
        lc.addWidget(ayuda)

    # ================================================================== tema
    def aplicar_tema(self, t: dict):
        self.t = t
        estilizar_plot(self.plot, t)
        self.plot_sec.setBackground(t["plotBg"])
        self._brochas = [pg.mkBrush(_color(t["primary"], 0.12 + 0.6 * k / (NIVELES_ESTELA - 1)))
                         for k in range(NIVELES_ESTELA)]
        self._brochas_sev = [pg.mkBrush(t[k]) for k in ("sanoFg", "leveFg", "interFg", "severaFg")]
        self._pen_base = pg.mkPen(t["on"], width=1.5)
        self.zona.setBrush(pg.mkBrush(_color(t["error"], 0.07)))
        self.umbral.setPen(pg.mkPen(t["error"], width=1.5, style=Qt.DashLine))
        self.dir_falla.setPen(pg.mkPen(t["muted"], width=1.2, style=Qt.DashDotLine))
        self.linea_estela.setPen(pg.mkPen(_color(t["primary"], 0.35), width=1))
        self.estela.setPen(pg.mkPen(None))
        self.proyeccion.setPen(pg.mkPen(t["on"], width=1.2, style=Qt.DotLine))
        self.pie.setPen(pg.mkPen(t["on"]))
        self.pie.setBrush(pg.mkBrush(t["plotBg"]))
        self.flecha.setPen(pg.mkPen(t["primary"], width=2.5))
        self.ref.setPen(pg.mkPen(t["on"], width=2))
        self.ref.setBrush(pg.mkBrush(t["plotBg"]))
        self.actual.setPen(pg.mkPen(t["plotBg"], width=2))
        self.actual.setBrush(pg.mkBrush(t["primary"]))
        self.anillos[0].setPen(pg.mkPen(t["interFg"], width=1.5, style=Qt.DashLine))
        self.anillos[1].setPen(pg.mkPen(t["severaFg"], width=1.5, style=Qt.DashLine))
        self.linea_ml.setPen(pg.mkPen(t["interFg"], width=1.2, style=Qt.DotLine))
        for ti, tok in ((self.textos_anillo[0], "interFg"), (self.textos_anillo[1], "severaFg"),
                        (self.texto_dir, "muted"), (self.texto_p, "on"), (self.t_v1, "on"), (self.t_v2, "primary")):
            ti.setColor(QColor(t[tok]))
        self.circ_sec.setPen(pg.mkPen(t["outlineV"], width=1))
        self.f_v1.setPen(pg.mkPen(t["on"], width=2.5))
        self.f_v2.setPen(pg.mkPen(t["primary"], width=2.5))
        self.leyenda.setText(
            f'<span style="color:{t["primary"]}">●</span> z (estela 30 s) &nbsp; '
            f'<span style="color:{t["on"]}">○</span> referencia &nbsp; '
            f'<span style="color:{t["primary"]}">➜</span> dz &nbsp; '
            f'<span style="color:{t["muted"]}">╍</span> dirección de falla {ANG_FALLA_DEG:g}° &nbsp; '
            f'<span style="color:{t["error"]}">╍</span> umbral {UMBRAL_PP:.2f} pp &nbsp; '
            f'<span style="color:{t["on"]}">◆</span> base congelada &nbsp; '
            f'<span style="color:{t["interFg"]}">┈</span> ML = |z − base| &nbsp; '
            f'<span style="color:{t["interFg"]}">◯</span> anillos de severidad')
        self._pendiente = True
        self.dibujar()

    # ================================================================== datos
    def procesar(self, trama: Trama, visible: bool = True):
        e = self.calculo.procesar(trama)
        if trama.motor != "ON":
            self.estado = None
            self._rango = None
        elif e is not None:
            self.estado = e
        self._pendiente = True
        if not visible:
            return
        espera = self._t_dibujo + DIBUJO_MIN_S - time.monotonic()
        if espera <= 0:
            self.dibujar()
        elif not self._diferido.isActive():
            self._diferido.start(int(espera * 1000) + 1)

    def mostrar_pendiente(self):
        if self._pendiente:
            self.dibujar()

    # ================================================================== dibujo
    def _limpiar(self):
        for item in (self.linea_estela, self.proyeccion, self.flecha, self.dir_falla, self.linea_ml, *self.anillos):
            item.setData([], [])
        for item in (self.estela, self.pie, self.ref, self.base, self.actual):
            item.setData([], [])
        self.zona.setPolygon(QPolygonF())
        self.umbral.setVisible(False)
        for ti in self.textos_anillo + [self.texto_dir, self.texto_p]:
            ti.setText("")

    def dibujar(self):
        if self.t is None:
            return
        self._pendiente = False
        self._t_dibujo = time.monotonic()
        e = self.estado
        if e is None:
            self._limpiar()
            self.lbl_nota.setText("Sin firma que dibujar: el detector solo trabaja con el motor en ON (fuera de WARMUP).")
            for k in self.valores.valores.values():
                k.setText("—")
            self._dibujar_secuencia(None)
            return

        # --- estela
        pts = e.estela
        n = len(pts)
        self.linea_estela.setData([z.real for _, z in pts], [z.imag for _, z in pts])
        brochas = [self._brochas[max(0, NIVELES_ESTELA - n + i)] for i in range(n)]
        self.estela.setData(x=[z.real for _, z in pts], y=[z.imag for _, z in pts], brush=brochas)
        self.actual.setData([e.z.real], [e.z.imag])

        # --- rango del plano (se mueve solo cuando hace falta, para no marear)
        nucleo = [e.z] + ([e.ref, e.ref + UMBRAL_PP * DIR_FALLA] if e.ref is not None else []) \
            + ([e.base] if e.base is not None else [])
        self._ajustar_rango(nucleo, [z for _, z in pts])
        cx, cy, span = self._rango
        largo = 3 * span
        cabeza = 0.045 * span

        # --- referencia, dirección de falla, umbral, zona de alarma, dz y proyección
        if e.ref is not None:
            r = e.ref
            self.ref.setData([r.real], [r.imag])
            a, b = r, r + largo * DIR_FALLA
            self.dir_falla.setData([a.real, b.real], [a.imag, b.imag])
            u = r + UMBRAL_PP * DIR_FALLA
            self.umbral.setPos(QPointF(u.real, u.imag))
            self.umbral.setVisible(True)
            esquinas = [u + largo * PERP, u - largo * PERP, u - largo * PERP + largo * DIR_FALLA,
                        u + largo * PERP + largo * DIR_FALLA]
            self.zona.setPolygon(QPolygonF([QPointF(c.real, c.imag) for c in esquinas]))
            # Etiquetas del lado contrario a z, para no tapar la flecha
            lado = -1.0 if proyectar_perp(e.z - r) > 0 else 1.0
            etq = r + 0.25 * span * DIR_FALLA + lado * 0.03 * span * PERP
            self.texto_dir.setAnchor((0, 0.5) if lado > 0 else (1, 0.5))
            self.texto_dir.setText(f"dirección de falla {ANG_FALLA_DEG:g}°")
            self.texto_dir.setPos(etq.real, etq.imag)
            self.flecha.setData(*_flecha(r, e.z, cabeza))
            pie = r + e.p_app * DIR_FALLA
            self.proyeccion.setData([e.z.real, pie.real], [e.z.imag, pie.imag])
            self.pie.setData([pie.real], [pie.imag])
            self.texto_p.setText(f"P = {e.p_fw:+.2f} pp")
            pos = pie + lado * 0.04 * span * PERP
            self.texto_p.setAnchor((0, 0.5) if lado > 0 else (1, 0.5))
            self.texto_p.setPos(pos.real, pos.imag)
        else:
            for item in (self.ref, self.pie):
                item.setData([], [])
            for item in (self.dir_falla, self.flecha, self.proyeccion):
                item.setData([], [])
            self.umbral.setVisible(False)
            self.zona.setPolygon(QPolygonF())
            self.texto_dir.setText("")
            self.texto_p.setText("")

        # --- base congelada y anillos de severidad
        if e.base is not None:
            b = e.base
            # Brochas creadas una vez por tema (crearlas en cada trama es lento en pyqtgraph)
            self.base.setData([b.real], [b.imag], brush=self._brochas_sev[e.sev], pen=self._pen_base)
            hacia = (e.z - b) / abs(e.z - b) if abs(e.z - b) > 1e-6 else DIR_FALLA
            hacia *= complex(math.cos(0.45), math.sin(0.45))      # junto a la línea base -> z, sin taparla
            for k, (radio, nombre) in enumerate(((SEV_U1, "INTER"), (SEV_U2, "SEVERA"))):
                self.anillos[k].setData(*_circulo(b, radio))
                p = b + radio * hacia
                self.textos_anillo[k].setText(f"{radio:g} pp · {nombre}")
                self.textos_anillo[k].setPos(p.real, p.imag)
            self.linea_ml.setData([b.real, e.z.real], [b.imag, e.z.imag])
        else:
            self.base.setData([], [])
            for k in range(2):
                self.anillos[k].setData([], [])
                self.textos_anillo[k].setText("")
            self.linea_ml.setData([], [])

        # --- valores y notas
        v = self.valores.valores
        v["p"].setText(f"{e.p_fw:+.3f} / " + (f"{e.p_app:+.3f}" if e.p_app is not None else "—"))
        v["dz"].setText(f"{abs(e.dz):.3f}" if e.dz is not None else "—")
        v["ml"].setText(f"{e.ml_fw:.3f} · {NOMBRES_SEV[e.sev]}" if e.enclavada else "— (sin alarma)")
        v["z"].setText(f"{e.z.real:+.3f} {e.z.imag:+.3f}j")
        v["v"].setText(f"{e.v1:.1f} V · {e.u2v:.2f} %")
        v["i"].setText(f"{e.i1:.3f} A · {abs(e.r2) * 1000:.1f} mA")
        notas = []
        if not e.ref_fw:
            notas.append("El firmware aún no tiene referencia (REF=0): hacen falta bloques de hace 6 a 11 s.")
        elif e.ref is not None and not e.coincide:
            notas.append(f"Referencia aproximada: la P recalculada ({e.p_app:+.3f}) no coincide con la del firmware "
                         f"({e.p_fw:+.3f}); la app fecha los bloques al recibirlos y el firmware con su reloj.")
        if e.enclavada:
            notas.append(f"Alarma enclavada ({NOMBRES_SEV[e.sev]}): la severidad sale de ML = |z − base| = "
                         f"{e.ml_fw:.2f} pp. P vuelve a cero porque la referencia móvil alcanza a z; la base no se mueve.")
        notas += e.notas
        self.lbl_nota.setText(" ".join(notas) or "Decisiones del firmware; el dibujo se recalcula con el campo RAW.")
        poner_prop(self.lbl_nota, "rol", "aviso" if (e.ref is not None and not e.coincide) else "secundario")
        self._dibujar_secuencia(e)

    def _ajustar_rango(self, nucleo: List[complex], estela: List[complex]):
        xs = [c.real for c in nucleo]
        ys = [c.imag for c in nucleo]
        cx0, cy0 = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        span0 = max(max(xs) - min(xs), max(ys) - min(ys), SPAN_MIN_PP / 1.3)
        # La estela entra si no está lejísimos (un bloque anómalo no debe alejar todo el dibujo)
        lim = max(3 * span0, 2.0)
        cerca = [c for c in estela if abs(c.real - cx0) <= lim and abs(c.imag - cy0) <= lim]
        xs += [c.real for c in cerca]
        ys += [c.imag for c in cerca]
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        span = max(max(xs) - min(xs), max(ys) - min(ys), SPAN_MIN_PP / 1.3) * 1.3
        if self._rango is not None:
            ocx, ocy, ospan = self._rango
            dentro = all(abs(x - ocx) <= 0.45 * ospan and abs(y - ocy) <= 0.45 * ospan for x, y in zip(xs, ys))
            if dentro and span > 0.45 * ospan:
                return                         # todo cabe y no sobra demasiado: no se mueve
        self._rango = (cx, cy, span)
        self.plot.setRange(xRange=(cx - span / 2, cx + span / 2), yRange=(cy - span / 2, cy + span / 2), padding=0)

    def _dibujar_secuencia(self, e: Optional[EstadoFirma]):
        if e is None or e.v1 <= 0:
            self.f_v1.setData([], [])
            self.f_v2.setData([], [])
            self.t_v1.setText("")
            self.t_v2.setText("")
            return
        self.f_v1.setData(*_flecha(0j, 1 + 0j, 0.08))
        self.t_v1.setText(f"V1 {e.v1:.0f} V")
        self.t_v1.setPos(1.0, 0.0)
        v2 = e.v2 / e.v1 * AMPLIA_V2
        if abs(v2) > 1.1:
            v2 = v2 / abs(v2) * 1.1
        self.f_v2.setData(*_flecha(0j, v2, 0.08))
        self.t_v2.setText(f"V2 ×{AMPLIA_V2:g} ({e.u2v:.2f} %)")
        self.t_v2.setPos(v2.real, v2.imag)
