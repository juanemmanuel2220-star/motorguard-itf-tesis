"""
Sección "Dashboard": el dashboard web que servía el Arduino por WiFi (handleRoot/handleStatus del .ino),
ahora con la lectura del cable USB.

- Todo lo que viene en cada trama se muestra siempre (no envía nada al firmware).
- Osciloscopio, espectro y THD/I_neg necesitan una consulta de solo lectura ('W', 'f', 's'): solo a
  petición, solo con el Arduino, nunca durante un pulso de inyección y como mucho una cada 5 s.
- No se incluyen los botones del dashboard web que actuaban sobre el banco (F1/F2/F3, TEST AUTO,
  vistas de la TFT): la inyección está en el panel con bloqueos de la sección Monitoreo.
"""

import time
from collections import deque
from typing import Callable, Dict, Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout, QWidget,
)

from motorguard_dashboard.telemetry.consultas import EspectroCritico, FormaOnda, Indicadores
from motorguard_dashboard.telemetry.parser import EventoSSR, Trama, campos_trama
from motorguard_dashboard.ui.componentes import BotonesZoom, FilasValor, boton, etiqueta, poner_prop, tarjeta
from motorguard_dashboard.ui.tema import SEV_TOKEN, estilizar_plot

FS_FIRMWARE = 2403.846        # Hz, temporizador del firmware (bloques de 4096 muestras)
INTERVALO_CONSULTA_S = 5.0
ESPERA_RESPUESTA_S = 5.0
HISTORIAL_S = 300
VENTANA_ONDA_MS = 100.0       # vista inicial del osciloscopio (~6 ciclos a 60 Hz)

# (etiqueta, clave en la trama, formato, unidad)
GRUPOS = [
    ("MCSA · fase crítica", [("Afund", "Afund", ".1f", ""), ("A55", "A55", ".1f", ""), ("f55", "f55", ".1f", "Hz"),
                             ("A65", "A65", ".1f", ""), ("f65", "f65", ".1f", "Hz"), ("P_RF", "P_RF", ".1f", "%"),
                             ("P_E2", "P_E2", ".1f", "%")]),
    ("Fortescue", [("U2V", "U2V", ".2f", "%"), ("U2I", "U2I", ".2f", "%"), ("E2", "E2", ".2f", "%"),
                   ("DE2", "DE2", ".2f", "%"), ("dV2", "dV2", ".2f", "%"), ("ANG", "ANG", ".1f", "°"),
                   ("|I1|", "I1", ".3f", "A")]),
    ("CUSUM anterior (informativo)", [("S", "S", ".2f", ""), ("Pcal", "Pcal", ".1f", "%"),
                                      ("Decisión", "CUSUM", ".0f", "")]),
    ("MCSA-HR", [("L2sM", "L2sM", ".2f", "dB"), ("L2sP", "L2sP", ".2f", "dB"), ("LrM", "LrM", ".2f", "dB"),
                 ("LrP", "LrP", ".2f", "dB"), ("L3", "L3", ".2f", "dB"), ("SNR2s", "SNR2s", ".2f", "dB"),
                 ("Deslizamiento s", "s", ".4f", ""), ("f0", "f0", ".3f", "Hz")]),
]

TARJETAS = (("va", "V_A", "V rms", "pa"), ("vb", "V_B", "V rms", "pb"), ("vc", "V_C", "V rms", "pc"),
            ("ia", "I_A", "A rms", "pa"), ("ib", "I_B", "A rms", "pb"), ("ic", "I_C", "A rms", "pc"),
            ("ssr", "SSR", "estado", "outline"), ("ton", "T_ON último", "ms", "outline"),
            ("act", "Activaciones", "en la sesión", "outline"))


def _plot(alto: int, eje_tiempo: bool = True) -> pg.PlotWidget:
    p = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem()} if eje_tiempo else None)
    p.setMinimumHeight(alto)
    p.setMouseEnabled(x=not eje_tiempo, y=False)
    p.hideButtons()
    return p


class DashboardTab(QWidget):
    def __init__(self, consultar: Optional[Callable[[str], bool]] = None,
                 hay_pulso: Callable[[], bool] = lambda: False, tema=None, parent=None):
        """consultar=None en reproducción: no se crean los botones de consulta."""
        super().__init__(parent)
        self._consultar = consultar
        self._hay_pulso = hay_pulso
        self._tema = tema
        self.t = tema.t if tema else None
        self._conectado = False
        self._t_ultima_consulta = -1e9
        self._pendiente = None          # (comando, t_envío)
        self._activaciones = 0
        self._hist = deque()            # (t, ia, ib, ic, u2i, e2)
        self._espectro: Optional[EspectroCritico] = None
        self._hist_pendiente = False
        self._construir()
        if consultar is not None:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._revisar_botones)
            self._timer.start(250)

    # ================================================================ interfaz
    def _construir(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 4, 20)
        lay.setSpacing(20)

        self.banner = QFrame()
        self.banner.setProperty("sev", "apagado")
        self.banner.setStyleSheet("QFrame { border-radius: 24px; }")
        fb = QHBoxLayout(self.banner)
        fb.setContentsMargins(24, 16, 24, 16)
        fb.setSpacing(20)
        self.lbl_banner_estado = QLabel("ESPERANDO DATOS")
        self.lbl_banner_estado.setStyleSheet("font-size: 26px; font-weight: 800;")
        self.lbl_banner_detalle = QLabel("")
        self.lbl_banner_detalle.setStyleSheet("font-weight: 600;")
        self.lbl_banner_hora = etiqueta("", "mono")
        fb.addWidget(self.lbl_banner_estado)
        fb.addWidget(self.lbl_banner_detalle, 1)
        fb.addWidget(self.lbl_banner_hora)
        lay.addWidget(self.banner)

        rejilla = QGridLayout()
        rejilla.setSpacing(12)
        self.tarjetas: Dict[str, QLabel] = {}
        self._puntos_kpi = {}
        for k, (clave, nombre, unidad, token) in enumerate(TARJETAS):
            caja, v = tarjeta(margen=(16, 14, 16, 14), espacio=2)
            caja.setStyleSheet("QFrame { border-radius: 20px; }")
            cab = QHBoxLayout()
            cab.setSpacing(6)
            punto = QLabel()
            punto.setFixedSize(8, 8)
            self._puntos_kpi[clave] = (punto, token)
            cab.addWidget(punto)
            cab.addWidget(etiqueta(nombre, "etiqueta"))
            cab.addStretch()
            v.addLayout(cab)
            val = etiqueta("--", "mono")
            val.setStyleSheet("font-size: 22px;")
            v.addWidget(val)
            v.addWidget(etiqueta(unidad, "secundario"))
            rejilla.addWidget(caja, k // 5, k % 5)
            self.tarjetas[clave] = val
        lay.addLayout(rejilla)

        fila_g = QHBoxLayout()
        fila_g.setSpacing(16)
        self.valores = {}
        for grupo, items in GRUPOS:
            caja, v = tarjeta(margen=(20, 18, 20, 14), espacio=6)
            v.addWidget(etiqueta(grupo, "tituloGrupo"))
            filas = FilasValor([(clave, et) for et, clave, _, _ in items])
            v.addWidget(filas)
            v.addStretch()
            for et, clave, fmt, unidad in items:
                self.valores[clave] = (filas.valores[clave], fmt, unidad)
            fila_g.addWidget(caja, 1, Qt.AlignTop)
        lay.addLayout(fila_g)

        fila_h = QHBoxLayout()
        fila_h.setSpacing(16)
        self.plot_i = _plot(210)
        self.zoom_i = BotonesZoom(self.plot_i, "tiempo")
        caja_i, li = tarjeta("Corrientes por fase", "A rms", extra=self.zoom_i)
        self.plot_i.addLegend(offset=(8, 4))
        self.curvas_i = [self.plot_i.plot([], [], name=f"I_{f}") for f in "ABC"]
        li.addWidget(self.plot_i)
        self.plot_u = _plot(210)
        self.zoom_u = BotonesZoom(self.plot_u, "tiempo")
        caja_u, lu = tarjeta("Desbalance de secuencia negativa", "%", extra=self.zoom_u)
        self.plot_u.addLegend(offset=(8, 4))
        self.curva_u2i = self.plot_u.plot([], [], name="U2I")
        self.curva_e2 = self.plot_u.plot([], [], name="E2")
        lu.addWidget(self.plot_u)
        fila_h.addWidget(caja_i, 1)
        fila_h.addWidget(caja_u, 1)
        lay.addLayout(fila_h)

        # --- capturas a petición
        caja_q, lq = tarjeta()
        cab_q = QHBoxLayout()
        texto = QVBoxLayout()
        texto.setSpacing(4)
        texto.addWidget(etiqueta("Capturas a petición", "tituloTarjeta"))
        nota = etiqueta("Consultas de solo lectura al firmware. Mientras imprime, su ciclo se detiene: un volcado "
                        "real del 06-oct tardó 0.78 s y retrasó 0.85 s la trama siguiente, sin perder bloques. "
                        "No usar en sesiones de validación; bloqueadas durante un pulso.", "secundario")
        nota.setWordWrap(True)
        texto.addWidget(nota)
        cab_q.addLayout(texto, 1)
        self.botones = {}
        if self._consultar is not None:
            for cmd, et, var, ic in (("W", "Osciloscopio", "tonal", "onda"), ("f", "Espectro 50–70 Hz", "tonal", "barras"),
                                     ("s", "THD e I_neg", "contorno", None)):
                b = boton(et, var)
                b.setEnabled(False)              # se habilita cuando _revisar_botones no encuentra bloqueos
                if ic and self._tema:
                    self._tema.registrar_icono(b, ic, "onPrimaryC", 16)
                b.clicked.connect(lambda _=False, c=cmd: self._pedir(c))
                cab_q.addWidget(b, 0, Qt.AlignTop)
                self.botones[cmd] = b
        else:
            cab_q.addWidget(etiqueta("Solo con el Arduino conectado", "secundario"), 0, Qt.AlignTop)
        lq.addLayout(cab_q)
        self.lbl_consulta = etiqueta("", "secundario")
        lq.addWidget(self.lbl_consulta)

        fila_c = QHBoxLayout()
        fila_c.setSpacing(16)
        caja_o = QFrame()
        caja_o.setProperty("rol", "contenedor")
        lo = QVBoxLayout(caja_o)
        lo.setContentsMargins(16, 14, 16, 14)
        cab_o = QHBoxLayout()
        cab_o.addWidget(etiqueta("Osciloscopio · corrientes crudas", "tituloGrupo"))
        cab_o.addStretch()
        self.lbl_onda = etiqueta("sin captura", "secundario")
        cab_o.addWidget(self.lbl_onda)
        lo.addLayout(cab_o)
        self.plot_onda = _plot(240, eje_tiempo=False)
        self.zoom_onda = BotonesZoom(self.plot_onda, "libre")
        cab_o.addWidget(self.zoom_onda)
        self.plot_onda.setLabel("bottom", "tiempo", units="ms")
        self.plot_onda.getAxis("bottom").enableAutoSIPrefix(False)   # si no, escribiría "kms" o "μms"
        self.plot_onda.setLabel("left", "cuentas ADC − media")
        self.plot_onda.addLegend(offset=(8, 4))
        self.curvas_onda = [self.plot_onda.plot([], [], name=f"I_{f}") for f in "ABC"]
        lo.addWidget(self.plot_onda)
        lo.addWidget(etiqueta("Sin calibrar · el firmware no envía voltaje en esta consulta · rueda del ratón "
                              "para recorrer los 852 ms", "secundario"))
        caja_e = QFrame()
        caja_e.setProperty("rol", "contenedor")
        le = QVBoxLayout(caja_e)
        le.setContentsMargins(16, 14, 16, 14)
        cab_e = QHBoxLayout()
        cab_e.addWidget(etiqueta("Espectro de la fase crítica", "tituloGrupo"))
        cab_e.addStretch()
        le.addLayout(cab_e)
        self.pila_esp = QStackedWidget()
        vacio = etiqueta("Sin captura\nPulsa «Espectro 50–70 Hz» para pedirlo. Los picos laterales que "
                         "reporte el firmware se marcan en color.", "vacio")
        vacio.setAlignment(Qt.AlignCenter)
        vacio.setWordWrap(True)
        self.plot_esp = _plot(220, eje_tiempo=False)
        self.zoom_esp = BotonesZoom(self.plot_esp, "libre")
        cab_e.addWidget(self.zoom_esp)
        self.plot_esp.setLabel("bottom", "frecuencia", units="Hz")
        self.plot_esp.setLabel("left", "amplitud (firmware)")
        self.barras = pg.BarGraphItem(x=[], height=[], width=0.7)
        self.plot_esp.addItem(self.barras)
        self.pila_esp.addWidget(vacio)
        self.pila_esp.addWidget(self.plot_esp)
        le.addWidget(self.pila_esp, 1)
        self.lbl_espectro = etiqueta("", "secundario")
        self.lbl_espectro.setWordWrap(True)
        self.lbl_indicadores = etiqueta("THD — · I_neg —", "mono")
        self.lbl_indicadores.setWordWrap(True)
        le.addWidget(self.lbl_espectro)
        le.addWidget(self.lbl_indicadores)
        fila_c.addWidget(caja_o, 3)
        fila_c.addWidget(caja_e, 2)
        lq.addLayout(fila_c)
        lay.addWidget(caja_q)
        lay.addStretch()

    # ================================================================ tema
    def aplicar_tema(self, t: dict):
        self.t = t
        for p in (self.plot_i, self.plot_u, self.plot_onda, self.plot_esp):
            estilizar_plot(p, t)
        for c, tok in zip(self.curvas_i, ("pa", "pb", "pc")):
            c.setPen(pg.mkPen(t[tok], width=2))
        for c, tok in zip(self.curvas_onda, ("pa", "pb", "pc")):
            c.setPen(pg.mkPen(t[tok], width=1.6))
        self.curva_u2i.setPen(pg.mkPen(t["primary"], width=2))
        self.curva_e2.setPen(pg.mkPen(t["pb"], width=2))
        for p in (self.plot_i, self.plot_u, self.plot_onda):  # las muestras de la leyenda toman el color nuevo
            leyenda = p.getPlotItem().legend
            if leyenda is not None:
                for muestra, _ in leyenda.items:
                    muestra.update()
        for punto, tok in self._puntos_kpi.values():
            punto.setStyleSheet(f"background: {t[tok]}; border-radius: 2px;")
        if self._espectro is not None:
            self._pintar_espectro(self._espectro)

    # ================================================================ datos
    def procesar(self, obj):
        if isinstance(obj, Trama):
            self._mostrar_trama(obj)
        elif isinstance(obj, EventoSSR):
            if obj.tipo == "encendido":
                self._activaciones += 1
                self.tarjetas["act"].setText(str(self._activaciones))
            elif obj.tipo == "apagado" and obj.t_on_ms is not None:
                self.tarjetas["ton"].setText(str(obj.t_on_ms))

    def _mostrar_trama(self, t: Trama):
        if t.motor == "OFF":
            sev, estado, detalle = "apagado", "MOTOR OFF", "sin señal de motor"
        elif t.motor == "WARMUP":
            sev, estado, detalle = "apagado", "WARMUP", "calentamiento del firmware"
        else:
            sev = SEV_TOKEN[t.dir.sev] if t.dir.enclavada else "sano"
            estado = t.decision
            detalle = ("Alarma enclavada · " if t.dir.enclavada else "") + \
                      f"decisión del firmware {t.decision} · SSR {t.ssr}"
        poner_prop(self.banner, "sev", sev)
        self.lbl_banner_estado.setText(estado)
        self.lbl_banner_detalle.setText(detalle)
        self.lbl_banner_hora.setText(time.strftime("%H:%M:%S", time.localtime(t.t)) if t.t else "")
        for clave, v, fmt in (("va", t.va, ".1f"), ("vb", t.vb, ".1f"), ("vc", t.vc, ".1f"),
                              ("ia", t.ia, ".2f"), ("ib", t.ib, ".2f"), ("ic", t.ic, ".2f")):
            self.tarjetas[clave].setText(format(v, fmt))
        self.tarjetas["ssr"].setText(t.ssr)
        campos = campos_trama(t)
        for clave, (lbl, fmt, unidad) in self.valores.items():
            v = campos.get(clave)
            lbl.setText("—" if v is None else f"{format(v, fmt)} {unidad}".strip())

        self._hist.append((t.t, t.ia, t.ib, t.ic, campos.get("U2I"), campos.get("E2")))
        while self._hist and self._hist[0][0] < t.t - HISTORIAL_S:
            self._hist.popleft()
        if self.isVisible():
            self._redibujar_historial()
        else:
            self._hist_pendiente = True         # se dibuja al mostrar la sección

    def _redibujar_historial(self):
        self._hist_pendiente = False
        if not self._hist:
            return
        h = np.array([[x if x is not None else np.nan for x in fila] for fila in self._hist], dtype=float)
        for k, c in enumerate(self.curvas_i):
            c.setData(h[:, 0], h[:, k + 1])
        self.curva_u2i.setData(h[:, 0], h[:, 4], connect="finite")
        self.zoom_i.aplicar()
        self.zoom_u.aplicar()
        self.curva_e2.setData(h[:, 0], h[:, 5], connect="finite")

    def showEvent(self, evento):
        super().showEvent(evento)
        if self._hist_pendiente:
            self._redibujar_historial()

    def respuesta(self, r):
        """Respuesta a una consulta (de la fuente serie o grabada en un log reproducido)."""
        self._pendiente = None
        if isinstance(r, FormaOnda):
            if not r.completa:
                self.lbl_consulta.setText(f"Volcado incompleto ({len(r.ia)}/{r.n_declarado}); no se muestra")
                return
            t_ms = np.arange(len(r.ia)) / FS_FIRMWARE * 1000.0
            for c, datos in zip(self.curvas_onda, (r.ia, r.ib, r.ic)):
                d = np.asarray(datos, dtype=float)
                c.setData(t_ms, d - d.mean())
            self.plot_onda.setXRange(0, VENTANA_ONDA_MS, padding=0)
            self.lbl_onda.setText(f"{len(r.ia)} muestras · {len(r.ia) / FS_FIRMWARE * 1000:.0f} ms")
            self.lbl_consulta.setText(f"Osciloscopio: {len(r.ia)} muestras por fase "
                                      f"({len(r.ia) / FS_FIRMWARE * 1000:.0f} ms a {FS_FIRMWARE:g} Hz)")
        elif isinstance(r, EspectroCritico):
            self._espectro = r
            self._pintar_espectro(r)
            self.pila_esp.setCurrentIndex(1)
            resumen = "  ".join(f"{p['fase']}: A55={p['a55']:.1f} ({p['f55']:.1f} Hz) A65={p['a65']:.1f}"
                                f" ({p['f65']:.1f} Hz)" for p in r.por_fase)
            self.lbl_espectro.setText(f"Fase crítica {r.fase} · A_fund = {r.a_fund} · picos laterales "
                                      f"{r.f55p} / {r.f65p} Hz · {resumen}")
            self.lbl_consulta.setText("Espectro recibido")
        elif isinstance(r, Indicadores):
            v = r.valores
            self.lbl_indicadores.setText(
                f"THD = {v.get('thd')}   I_neg = {v.get('ineg')}   A50 = {v.get('f50')}   A70 = {v.get('f70')}   "
                f"(fase C: V = {v.get('vc')} V, I = {v.get('ic')} A)")
            self.lbl_consulta.setText("THD / I_neg recibidos")

    def _pintar_espectro(self, r: EspectroCritico):
        t = self.t or {}
        xs = [f for f, _ in r.puntos]
        ys = [a for _, a in r.puntos]
        # Verde: fundamental; color de alarma: la barra más cercana a cada pico lateral que reporta el firmware
        picos = {min(xs, key=lambda x: abs(x - fp)) for fp in (r.f55p, r.f65p) if fp is not None} if xs else set()
        colores = [t.get("sanoFg", "#17663F") if abs(f - 60) < 0.5 else
                   (t.get("interFg", "#A3410C") if f in picos else t.get("primary", "#2457A6")) for f in xs]
        self.barras.setOpts(x=xs, height=ys, brushes=colores, pens=[pg.mkPen(None)] * len(xs))

    def conexion(self, ok: bool):
        self._conectado = ok
        if not ok:
            self._pendiente = None

    # ================================================================ consultas
    def _bloqueo_consulta(self) -> Optional[str]:
        if not self._conectado:
            return "sin conexión"
        if self._hay_pulso():
            return "hay una inyección en curso"
        if self._pendiente is not None:
            return f"esperando la respuesta de '{self._pendiente[0]}'"
        resta = self._t_ultima_consulta + INTERVALO_CONSULTA_S - time.monotonic()
        if resta > 0:
            return f"espera {resta:.0f} s entre consultas"
        return None

    def _pedir(self, cmd):
        if self._bloqueo_consulta() or self._consultar is None:
            return
        if self._consultar(cmd):
            self._pendiente = (cmd, time.monotonic())
            self._t_ultima_consulta = time.monotonic()
            self.lbl_consulta.setText(f"Consulta '{cmd}' enviada…")
        else:
            self.lbl_consulta.setText("No se pudo enviar la consulta (sin conexión)")

    def _revisar_botones(self):
        if self._pendiente and time.monotonic() - self._pendiente[1] > ESPERA_RESPUESTA_S:
            self.lbl_consulta.setText(f"Sin respuesta a '{self._pendiente[0]}' en {ESPERA_RESPUESTA_S:g} s")
            self._pendiente = None
        motivo = self._bloqueo_consulta()
        for b in self.botones.values():
            b.setEnabled(motivo is None)
            b.setToolTip(motivo or "")
