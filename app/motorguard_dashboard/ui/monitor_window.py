"""
Ventana principal: muestra lo que reporta el firmware congelado 299a943, sin recalcular ni sintetizar
señales. Diseño "MotorGuard-ITF — Rediseño de la interfaz" (estilo Material 3, claro/oscuro).

Secciones (riel de navegación): Monitoreo (detector embebido, alarmas y, con el Arduino, inyección),
Dashboard (el dashboard web del Arduino, ahora por el cable), Adquisición (datasets nuevos con el banco,
solo con el Arduino) y Asistente (RAG, etapa 3).
La barra superior, el selector de tema y el botón PARO quedan visibles en todas las secciones.
En reproducción no hay ningún control que envíe comandos.
"""

import time
from collections import deque
from datetime import datetime
from typing import Dict, Optional

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QMainWindow, QMessageBox, QPlainTextEdit, QScrollArea, QStackedWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from motorguard_dashboard.inyeccion.control import ControlInyeccion
from motorguard_dashboard.sistema.bitacora import LOG, notificador
from motorguard_dashboard.telemetry.alarmas import EventoAlarma, RegistroAlarmas
from motorguard_dashboard.telemetry.parser import NOMBRES_SEV, EventoSSR, MensajeFirmware, Trama
from motorguard_dashboard.ui.adquisicion_tab import AdquisicionTab
from motorguard_dashboard.ui.asistente_tab import VENTANA_PULSO_S, AsistenteTab
from motorguard_dashboard.ui.componentes import (
    EscalaSeveridad, Segmentado, boton, chip, etiqueta, poner_prop, tarjeta,
)
from motorguard_dashboard.ui.dashboard_tab import DashboardTab
from motorguard_dashboard.ui.dialogos import DialogoAcercaDe, DialogoAjustes
from motorguard_dashboard.ui.panel_inyeccion import PanelInyeccion
from motorguard_dashboard.ui.plano_firma import PlanoFirmaTarjeta
from motorguard_dashboard.ui.tema import SEV_TOKEN, GestorTema, estilizar_plot, logo_pixmap

UMBRAL_P = 0.40          # pp, detector_dir.h DIR_UMBRAL
VENTANA_S = 300          # segundos visibles en la gráfica de P
SIN_DATOS_S = 5.0        # aviso si no llega una trama en este tiempo (el firmware manda una cada ~1.7 s)
MAX_FILAS_ALARMAS = 1000 # filas visibles en la tabla (el CSV guarda todas)
VIGILANTE_MS = 2000      # revisión de que el hilo de lectura siga vivo

SECCIONES = (("Monitoreo", "monitoreo", "detector embebido (firmware 299a943)"),
             ("Dashboard", "dashboard", "todo lo que trae cada trama, por el cable USB"),
             ("Adquisición", "adquisicion", "datasets nuevos con el banco"),
             ("Asistente", "asistente", "inspección y mantenimiento con citas"))


def _hora(t):
    return datetime.fromtimestamp(t).strftime("%H:%M:%S") if t is not None else "—"


class DialogoLiberar(QDialog):
    """Confirmación para liberar una alarma enclavada con 'r' (reinicio del detector del firmware)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Liberar alarma")
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.addWidget(etiqueta("Se reiniciará el detector embebido ('r')", "tituloTarjeta"))
        txt = etiqueta(
            "La alarma enclavada se libera y el detector rehace su referencia con el motor tal como está ahora "
            "(unos 8–11 s sin decisión). El SSR no se toca. Úsalo con una falsa alarma que no se libera sola, "
            "por ejemplo tras el arranque o tras un cambio del motor sano.", "secundario")
        txt.setWordWrap(True)
        lay.addWidget(txt)
        aviso = etiqueta("Si la falla es real y sigue presente, el detector NO volverá a alarmar: la nueva referencia "
                         "ya la incluye. Confírmala con las pruebas fuera de línea.", "aviso")
        aviso.setWordWrap(True)
        lay.addWidget(aviso)
        self.casilla = QCheckBox("Confirmo que es una falsa alarma y entiendo que, si la falla es real, no se "
                                 "volverá a detectar.")
        lay.addWidget(self.casilla)
        botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.btn_ok = botones.button(QDialogButtonBox.Ok)
        self.btn_ok.setText("Liberar alarma")
        self.btn_ok.setEnabled(False)
        self.casilla.toggled.connect(self.btn_ok.setEnabled)
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        lay.addWidget(botones)
        self.resize(520, 260)


def _envolver_scroll(w: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.NoFrame)
    sa.setWidget(w)
    return sa


class MonitorWindow(QMainWindow):
    def __init__(self, fuente, registro: RegistroAlarmas, es_replay: bool, descripcion: str,
                 control: Optional[ControlInyeccion] = None, tema: Optional[GestorTema] = None,
                 demo: bool = False):
        super().__init__()
        self.fuente = fuente
        self.control = None if es_replay else control
        self.panel_iny: Optional[PanelInyeccion] = None
        self.registro = registro
        self.es_replay = es_replay
        self.demo = demo
        self.tema = tema or GestorTema(QApplication.instance(), persistir=False)
        self.t = self.tema.t
        self.setWindowTitle(f"MotorGuard-ITF ({descripcion})")
        self.resize(1440, 920)

        self._conectado = False
        self._t_rx = None              # time.monotonic() de la última trama recibida
        self._n_tramas = 0
        self._n_descartadas = 0
        self._serie = deque()          # (t, p, sev si enclavada o None)
        self._filas: Dict[int, int] = {}
        self._ultima: Optional[Trama] = None
        self._cerrando = False
        self._n_errores = 0
        self._serie_pendiente = False
        self._pen_borde = None
        self._brochas = {}

        self._construir()
        self.tema.cambiado.connect(self._aplicar_tema)
        self._aplicar_tema(self.tema.t)

        fuente.sig_dato.connect(self._on_dato)
        fuente.sig_descartada.connect(self._on_descartada)
        fuente.sig_estado.connect(self._on_estado)
        fuente.sig_respuesta.connect(self.dashboard.respuesta)

        self._reloj = QTimer(self)
        self._reloj.timeout.connect(self._tic)
        self._reloj.start(1000)
        notificador.error.connect(self._on_error_interno)
        if not es_replay:
            self._vigilante = QTimer(self)
            self._vigilante.timeout.connect(self._vigilar_fuente)
            self._vigilante.start(VIGILANTE_MS)
        fuente.start()

    # ================================================================== estructura
    def _construir(self):
        raiz = QWidget()
        raiz.setObjectName("raiz")
        self.setCentralWidget(raiz)
        fila = QHBoxLayout(raiz)
        fila.setContentsMargins(0, 0, 0, 0)
        fila.setSpacing(0)

        # --- riel de navegación
        riel = QFrame()
        riel.setObjectName("riel")
        riel.setFixedWidth(96)
        lay_r = QVBoxLayout(riel)
        lay_r.setContentsMargins(8, 20, 8, 20)
        lay_r.setSpacing(14)
        logo = QLabel()
        logo.setObjectName("logo")
        logo.setFixedSize(56, 56)
        logo.setAlignment(Qt.AlignCenter)
        logo.setPixmap(logo_pixmap(56))
        logo.setToolTip("MotorGuard-ITF")
        lay_r.addWidget(logo, 0, Qt.AlignHCenter)
        lay_r.addSpacing(10)
        self.nav = {}
        for i, (nombre, ic, _) in enumerate(SECCIONES):
            item = QVBoxLayout()
            item.setSpacing(4)
            pill = boton("", "navPill")
            pill.setCheckable(True)
            pill.setAccessibleName(nombre)
            pill.setToolTip(nombre)
            self.tema.registrar_icono(pill, ic, "on", 20)
            pill.clicked.connect(lambda _=False, k=i: self.ir_a(k))
            lbl = etiqueta(nombre, "navEtiqueta")
            lbl.setAlignment(Qt.AlignCenter)
            item.addWidget(pill, 0, Qt.AlignHCenter)
            item.addWidget(lbl)
            lay_r.addLayout(item)
            self.nav[i] = (pill, lbl)
        lay_r.addStretch()
        for nombre, ic, accion in (("Ajustes", "ajustes", self._abrir_ajustes),
                                   ("Acerca de", "info", self._abrir_acerca)):
            item = QVBoxLayout()
            item.setSpacing(4)
            pill = boton("", "navPill")
            pill.setAccessibleName(nombre)
            pill.setToolTip(nombre)
            self.tema.registrar_icono(pill, ic, "on", 20)
            pill.clicked.connect(accion)
            lbl = etiqueta(nombre, "navEtiqueta")
            lbl.setAlignment(Qt.AlignCenter)
            item.addWidget(pill, 0, Qt.AlignHCenter)
            item.addWidget(lbl)
            lay_r.addLayout(item)
        fila.addWidget(riel)

        # --- columna principal
        col = QVBoxLayout()
        col.setContentsMargins(28, 20, 28, 12)
        col.setSpacing(16)
        fila.addLayout(col, 1)

        barra = QHBoxLayout()
        barra.setSpacing(10)
        titulos = QVBoxLayout()
        titulos.setSpacing(2)
        self.lbl_titulo = etiqueta("Monitoreo", "titulo")
        self.lbl_subtitulo = etiqueta("", "subtitulo")
        self.lbl_subtitulo.setWordWrap(True)
        self.lbl_subtitulo.setMinimumWidth(150)
        titulos.addWidget(self.lbl_titulo)
        titulos.addWidget(self.lbl_subtitulo)
        barra.addLayout(titulos)
        barra.addStretch()
        self.lbl_fuente = chip("Iniciando…")
        self.lbl_fuente.setMaximumWidth(270)
        self._texto_fuente = ""
        self.lbl_motor = chip("Motor —", "neutro")
        self.lbl_frescura = chip("", "tenue")
        self.lbl_frescura.setFixedWidth(190)
        self.lbl_error = chip("", "mal")
        self.lbl_error.setVisible(False)
        # Modo demo (solo capturas): siempre a la vista, para que ninguna captura pase por una sesión real
        self.lbl_demo = chip("DEMO · simulador del firmware", "aviso")
        self.lbl_demo.setToolTip("Tramas reales del banco (09-oct) reproducidas por un simulador; los comandos no "
                                 "llegan a ningún hardware. Registros en registros/demo/.")
        self.lbl_demo.setVisible(self.demo)
        for c in (self.lbl_demo, self.lbl_error, self.lbl_fuente, self.lbl_motor, self.lbl_frescura):
            c.setFixedHeight(36)
            barra.addWidget(c, 0, Qt.AlignVCenter)
        self.selector_tema = Segmentado((("sistema", "Sistema"), ("claro", "Claro"), ("oscuro", "Oscuro")),
                                        self.tema.modo)
        for clave, b in self.selector_tema.botones.items():
            self.tema.registrar_icono(b, clave, "on", 16)
            b.setToolTip({"sistema": "Seguir el tema del dispositivo", "claro": "Siempre claro",
                          "oscuro": "Siempre oscuro"}[clave])
        self.selector_tema.elegido.connect(self.tema.poner_modo)
        barra.addWidget(self.selector_tema, 0, Qt.AlignVCenter)
        self.btn_paro = None
        if self.control is not None:
            self.btn_paro = boton("PARO", "paro")
            self.btn_paro.setToolTip("Apaga el SSR y cancela la serie (visible en todas las secciones)")
            self.tema.registrar_icono(self.btn_paro, "paro", "onError", 18)
            barra.addWidget(self.btn_paro)
        col.addLayout(barra)

        self.paginas = QStackedWidget()
        col.addWidget(self.paginas, 1)
        self.adquisicion = AdquisicionTab(
            self.control, None if self.control is None else self.fuente.enviar, tema=self.tema,
            puerto=lambda: getattr(self.fuente, "puerto_actual", ""),
            crudo_sesion=getattr(self.fuente, "ruta_crudo", "") or "")
        self.paginas.addWidget(self._construir_monitoreo())      # cada columna lleva su propio desplazamiento
        self.dashboard = DashboardTab(
            consultar=None if self.es_replay else self.fuente.consultar,
            # Durante una adquisición tampoco: una consulta puede retrasar una trama del protocolo
            hay_pulso=((lambda: self.control.en_curso or self.adquisicion.activa) if self.control is not None
                       else (lambda: False)),
            tema=self.tema)
        self.paginas.addWidget(_envolver_scroll(self.dashboard))
        self.paginas.addWidget(_envolver_scroll(self.adquisicion))
        self.asistente = AsistenteTab(tema=self.tema, provocada=self._alarma_provocada)
        self.paginas.addWidget(_envolver_scroll(self.asistente))

        self.lbl_pie = etiqueta(f"Registro: {self.registro.ruta_csv or '(sin archivo)'}", "secundario")
        col.addWidget(self.lbl_pie)
        self.ir_a(0)

    def ir_a(self, k: int):
        """Cambia de sección (0 Monitoreo, 1 Dashboard, 2 Adquisición, 3 Asistente)."""
        self.paginas.setCurrentIndex(k)
        if k == 0 and self._serie_pendiente:
            self._pintar_serie()
        if k == 0:
            self.plano.mostrar_pendiente()
        nombre, _, sub = SECCIONES[k]
        self.lbl_titulo.setText(nombre)
        self.lbl_subtitulo.setText(sub)
        for i, (pill, lbl) in self.nav.items():
            pill.setChecked(i == k)
            poner_prop(lbl, "activo", "true" if i == k else "false")

    @property
    def secciones(self):
        return [s[0] for s in SECCIONES]

    # ------------------------------------------------------------------ página Monitoreo
    def _construir_monitoreo(self) -> QWidget:
        pagina = QWidget()
        cols = QHBoxLayout(pagina)
        cols.setContentsMargins(0, 4, 4, 20)
        cols.setSpacing(20)
        izq = QVBoxLayout()
        izq.setSpacing(20)
        izq.setContentsMargins(0, 0, 12, 0)     # espacio para la barra de desplazamiento
        der = QVBoxLayout()
        der.setSpacing(20)
        der.setContentsMargins(0, 0, 12, 0)
        # Cada columna con su propio desplazamiento (pedido por el autor, 17-oct): la de estado e inyección y la de
        # gráficas ya no se mueven juntas
        cont_izq = QWidget()
        cont_izq.setLayout(izq)
        self.scroll_izq = _envolver_scroll(cont_izq)
        self.scroll_izq.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_izq.setMinimumWidth(392)
        self.scroll_izq.setMaximumWidth(472)
        cont_der = QWidget()
        cont_der.setLayout(der)
        self.scroll_der = _envolver_scroll(cont_der)
        cols.addWidget(self.scroll_izq)
        cols.addWidget(self.scroll_der, 1)

        # --- estado del detector (tarjeta con el color de la severidad)
        self.hero = QFrame()
        self.hero.setProperty("sev", "apagado")
        lay_h = QVBoxLayout(self.hero)
        lay_h.setContentsMargins(24, 22, 24, 22)
        lay_h.setSpacing(12)
        cab = QHBoxLayout()
        cab.addWidget(etiqueta("DETECTOR EMBEBIDO · CAMPO DIR", "encabezado"))
        cab.addStretch()
        self.lbl_enclave = chip("ENCLAVADA", "enclave_inter")
        self.lbl_enclave.setFixedHeight(28)
        self.lbl_enclave.setVisible(False)
        cab.addWidget(self.lbl_enclave)
        # Liberar una alarma atascada con 'r' (aprobado por el autor el 16-oct); solo con el Arduino
        self.btn_liberar = boton("Liberar alarma", "contorno")
        self.btn_liberar.setToolTip("Reinicia el detector ('r') para liberar una falsa alarma enclavada")
        self.btn_liberar.setVisible(False)
        self.btn_liberar.clicked.connect(self._liberar_alarma)
        lay_h.addLayout(cab)
        self.lbl_alarma = etiqueta("—", "cifraGrande")
        self.lbl_desde = etiqueta("esperando datos…")
        self.lbl_desde.setStyleSheet("font-size: 15px; font-weight: 600;")
        lay_h.addWidget(self.lbl_alarma)
        lay_h.addWidget(self.lbl_desde)
        # En su propia fila: junto al título y al chip ENCLAVADA no cabía en la columna (máx. 472 px) y se cortaba
        lay_h.addWidget(self.btn_liberar, 0, Qt.AlignLeft)
        metricas = QHBoxLayout()
        metricas.setSpacing(8)
        self.metricas = {}
        for clave in ("P", "ML", "PL"):
            caja = QFrame()
            caja.setProperty("rol", "sobre")
            v = QVBoxLayout(caja)
            v.setContentsMargins(12, 10, 12, 10)
            v.setSpacing(0)
            et = QLabel(clave)
            et.setStyleSheet("font-size: 12px; font-weight: 600;")
            val = etiqueta("—", "mono")
            val.setStyleSheet("font-size: 18px;")
            v.addWidget(et)
            v.addWidget(val)
            v.addWidget(QLabel("pp"))
            metricas.addWidget(caja)
            self.metricas[clave] = val
        lay_h.addLayout(metricas)
        self.lbl_escala = QLabel("Severidad por |ΔR2|")
        self.lbl_escala.setStyleSheet("font-size: 12px; font-weight: 600;")
        lay_h.addWidget(self.lbl_escala)
        self.escala = EscalaSeveridad()
        lay_h.addWidget(self.escala)
        marcas = QHBoxLayout()
        for txt in ("LEVE", "1.626", "INTER", "4.471", "SEVERA"):
            m = etiqueta(txt, "mono")
            m.setStyleSheet("font-size: 11px; font-weight: 500;")
            marcas.addWidget(m)
            if txt != "SEVERA":
                marcas.addStretch()
        lay_h.addLayout(marcas)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        self.lbl_racha = etiqueta("Racha —", "sobreChip")
        self.lbl_ref = etiqueta("Referencia —", "sobreChip")
        self.lbl_cusum = etiqueta("CUSUM (info) —", "sobreChip")
        for c in (self.lbl_racha, self.lbl_ref, self.lbl_cusum):
            chips.addWidget(c)
        chips.addStretch()
        lay_h.addLayout(chips)
        izq.addWidget(self.hero)

        # --- valores por fase
        caja_f, lay_f = tarjeta("Valores por fase", "rms, del firmware")
        rejilla = QHBoxLayout()
        rejilla.setSpacing(10)
        self.lbl_v, self.lbl_i, self.puntos_fase = {}, {}, {}
        for fase in "ABC":
            c = QFrame()
            c.setProperty("rol", "contenedor")
            v = QVBoxLayout(c)
            v.setContentsMargins(12, 12, 12, 12)
            v.setSpacing(4)
            cab_f = QHBoxLayout()
            cab_f.setSpacing(6)
            punto = QLabel()
            punto.setFixedSize(10, 10)
            self.puntos_fase[fase] = punto
            cab_f.addWidget(punto)
            cab_f.addWidget(etiqueta(f"Fase {fase}", "etiqueta"))
            cab_f.addStretch()
            v.addLayout(cab_f)
            self.lbl_i[fase] = etiqueta("—", "cifra")
            self.lbl_v[fase] = etiqueta("—", "cifraChica")
            v.addWidget(self.lbl_i[fase])
            v.addWidget(self.lbl_v[fase])
            rejilla.addWidget(c)
        lay_f.addLayout(rejilla)
        self.lbl_i1 = etiqueta("|I1| —", "secundario")
        self.lbl_i1.setTextFormat(Qt.RichText)
        self.lbl_i1.setWordWrap(True)
        lay_f.addWidget(self.lbl_i1)
        izq.addWidget(caja_f)

        # --- inyección (solo con el Arduino)
        if self.control is not None:
            caja_i, lay_i = tarjeta("Inyección de falla")
            lay_i.addWidget(etiqueta("SSR · fase C · solo con el Arduino conectado", "secundario"))
            self.panel_iny = PanelInyeccion(self.control, self.fuente.enviar, tema=self.tema)
            lay_i.addWidget(self.panel_iny)
            izq.addWidget(caja_i)
            self.btn_paro.clicked.connect(self.panel_iny._on_paro)
            self.panel_iny.bloqueo_externo = self.adquisicion.bloqueo_inyeccion
        izq.addStretch()

        # --- gráfica de P
        caja_p, lay_p = tarjeta()
        cab_p = QHBoxLayout()
        tit_p = QVBoxLayout()
        tit_p.setSpacing(2)
        tit_p.addWidget(etiqueta("Proyección de la firma P", "tituloTarjeta"))
        tit_p.addWidget(etiqueta("pp de |I1| · referencia móvil t−11…t−6 s · últimos 5 min", "secundario"))
        cab_p.addLayout(tit_p)
        cab_p.addStretch()
        self.leyenda_p = etiqueta("", "etiqueta")
        self.leyenda_p.setTextFormat(Qt.RichText)
        cab_p.addWidget(self.leyenda_p)
        lay_p.addLayout(cab_p)
        self.plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem()})
        self.plot.setMinimumHeight(300)
        self.plot.setLabel("left", "P", units="pp")
        # "pp" no es una unidad SI: sin esto pyqtgraph escala el eje y escribe "mpp" (mili-pp) con valores chicos
        self.plot.getAxis("left").enableAutoSIPrefix(False)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.hideButtons()
        self.curva_p = self.plot.plot([], [])
        self.puntos_alarma = pg.ScatterPlotItem(size=9)
        self.plot.addItem(self.puntos_alarma)
        self.linea_umbral = pg.InfiniteLine(pos=UMBRAL_P, angle=0, movable=False)
        self.plot.addItem(self.linea_umbral)
        lay_p.addWidget(self.plot)
        lay_p.addWidget(etiqueta("Durante la alarma P cae porque la referencia móvil absorbe la falla; "
                                 "el firmware decide con PL, contra la base congelada.", "secundario"))
        der.addWidget(caja_p)

        # --- plano de la firma (método del detector en el plano complejo)
        self.plano = PlanoFirmaTarjeta(tema=self.tema)
        der.addWidget(self.plano)

        # --- eventos de alarma
        caja_t, lay_t = tarjeta("Eventos de alarma", "se guardan en app_registros/")
        self.tabla = QTableWidget(0, 9)
        self.tabla.setHorizontalHeaderLabels(
            ["#", "Inicio", "Fin", "Duración", "Sev. inicial", "Sev. máx.", "ML máx. (pp)", "|I1| (A)", "Motivo de fin"])
        self.tabla.verticalHeader().setVisible(False)
        # Anchos fijos (ajustables a mano): "ajustar al contenido" recalcula todas las filas en cada cambio y,
        # en sesiones largas, cada actualización tardaba más (prueba de resistencia acelerada)
        cab_t = self.tabla.horizontalHeader()
        cab_t.setSectionResizeMode(QHeaderView.Interactive)
        cab_t.setStretchLastSection(True)
        cab_t.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for col, ancho in enumerate((44, 92, 92, 86, 96, 92, 104, 76)):
            self.tabla.setColumnWidth(col, ancho)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setShowGrid(False)
        self.tabla.setMinimumHeight(230)
        self.tabla.setFocusPolicy(Qt.NoFocus)
        lay_t.addWidget(self.tabla)
        der.addWidget(caja_t)

        # --- mensajes del firmware
        caja_m, lay_m = tarjeta("Mensajes del firmware", "SSR · Zero SSR · red · IA")
        self.txt = QPlainTextEdit()
        self.txt.setProperty("rol", "log")
        self.txt.setReadOnly(True)
        self.txt.setMaximumBlockCount(300)
        self.txt.setMinimumHeight(200)
        lay_m.addWidget(self.txt)
        der.addWidget(caja_m)
        der.addStretch()
        return pagina

    # ================================================================== tema
    @Slot(dict)
    def _aplicar_tema(self, t: dict):
        self.t = t
        estilizar_plot(self.plot, t)
        self.curva_p.setPen(pg.mkPen(t["primary"], width=2))
        self.linea_umbral.setPen(pg.mkPen(t["error"], width=1.5, style=Qt.DashLine))
        # Pincel y brochas de los puntos de alarma: se crean una vez por tema y se reutilizan (pyqtgraph
        # guarda en caché los símbolos por pincel/brocha; crearlos en cada trama costaba ~20 ms)
        self._pen_borde = pg.mkPen(t["plotBg"], width=2)
        self._brochas = {sev: pg.mkBrush(t[SEV_TOKEN[sev] + "Fg"]) for sev in (0, 1, 2, 3)}
        self._serie_pendiente = True
        self.leyenda_p.setText(
            f'<span style="color:{t["primary"]}">━━</span> P &nbsp;&nbsp; '
            f'<span style="color:{t["error"]}">╍╍</span> Umbral {UMBRAL_P:.2f} pp &nbsp;&nbsp; '
            f'<span style="color:{t["interFg"]}">●</span> Bloque con alarma')
        for fase, token in (("A", "pa"), ("B", "pb"), ("C", "pc")):
            self.puntos_fase[fase].setStyleSheet(f"background: {t[token]}; border-radius: 3px;")
        self._pintar_serie()
        if self._ultima is not None:
            self._mostrar_trama(self._ultima)
        for fila in range(self.tabla.rowCount()):
            item = self.tabla.item(fila, 5)
            if item is not None:
                sev = NOMBRES_SEV.index(item.text()) if item.text() in NOMBRES_SEV else 0
                item.setForeground(QColor(t[SEV_TOKEN[sev] + "Fg"]))
        self.plano.aplicar_tema(t)
        self.dashboard.aplicar_tema(t)
        self.asistente.aplicar_tema(t)
        self.adquisicion.aplicar_tema(t)
        if self.panel_iny is not None:
            self.panel_iny.aplicar_tema(t)
        self.selector_tema.marcar(self.tema.modo)

    # ================================================================== datos
    @Slot(object)
    def _on_dato(self, obj):
        ev = self.registro.procesar(obj)
        if ev is not None:
            self._actualizar_fila(ev)
        if self.panel_iny is not None:
            self.panel_iny.procesar(obj)
        self.adquisicion.procesar(obj)
        self.dashboard.procesar(obj)
        if isinstance(obj, Trama):
            self._t_rx = time.monotonic()
            self._n_tramas += 1
            self._serie.append((obj.t, obj.dir.p, obj.dir.sev if obj.dir.enclavada else None))
            while self._serie and self._serie[0][0] < obj.t - VENTANA_S:
                self._serie.popleft()
            self._mostrar_trama(obj)
            self._pintar_serie()
            self.plano.procesar(obj, visible=self.paginas.currentIndex() == 0)
            self.asistente.contexto(obj, self.registro.abierta)
        elif isinstance(obj, (EventoSSR, MensajeFirmware)):
            self.txt.appendPlainText(f"{_hora(obj.t)}  {obj.texto}")

    def _mostrar_trama(self, t: Trama):
        self._ultima = t
        d, tk = t.dir, self.t
        estado_motor = {"ON": "bien", "WARMUP": "aviso", "OFF": "neutro"}[t.motor]
        minutos = self.control.minutos_encendido(time.time()) if self.control is not None else None
        self.lbl_motor.setText(f"Motor {t.motor}" + (f" · {minutos:.0f} min" if minutos is not None and t.motor != "OFF" else ""))
        poner_prop(self.lbl_motor, "estado", estado_motor)

        if t.motor == "OFF":
            sev, grande, sub = "apagado", "MOTOR OFF", "sin señal de motor"
        elif t.motor == "WARMUP":
            sev, grande, sub = "apagado", "WARMUP", "calentamiento del firmware: no se inyecta"
        elif d.enclavada:
            sev = SEV_TOKEN[d.sev]
            grande = d.nombre_sev if d.sev else "ALARMA"
            ab = self.registro.abierta
            sub = (f"Alarma desde {_hora(ab.t_inicio)} · {ab.duracion(t.t):.0f} s" if ab is not None
                   else "Alarma enclavada")
        else:
            sev, grande = "sano", "SANO"
            sub = "sin alarma" if d.ref else "sin referencia todavía (REF=0)"
        poner_prop(self.hero, "sev", sev)
        self.lbl_alarma.setText(grande)
        self.lbl_desde.setText(sub)
        enclavada = d.enclavada and t.motor != "OFF"
        self.lbl_enclave.setVisible(enclavada)
        self.btn_liberar.setVisible(enclavada and self.control is not None)
        motivo = self._bloqueo_liberar(t)
        self.btn_liberar.setEnabled(motivo is None)
        self.btn_liberar.setToolTip("Reinicia el detector ('r') para liberar una falsa alarma enclavada"
                                    if motivo is None else f"No disponible: {motivo}")
        if enclavada:
            poner_prop(self.lbl_enclave, "estado", f"enclave_{sev}")
        self.metricas["P"].setText(f"{d.p:+.3f}")
        self.metricas["ML"].setText(f"{d.ml:.3f}")
        self.metricas["PL"].setText(f"{d.pl:+.3f}")
        self.lbl_escala.setText(f"Severidad por |ΔR2| · ML = {d.ml:.2f} pp" if d.enclavada
                                else "Severidad por |ΔR2| (se mide al confirmar la alarma)")
        on = tk.get(sev + "On", tk["on"])
        self.escala.poner(d.ml if d.enclavada else None, (tk["leveFg"], tk["interFg"], tk["severaFg"], on))
        self.lbl_racha.setText(f"Racha {d.racha} bloques")
        self.lbl_ref.setText("Referencia OK" if d.ref else "Sin referencia")
        self.lbl_cusum.setText(f"CUSUM (info) {d.cusum}")

        for fase, v, i in (("A", t.va, t.ia), ("B", t.vb, t.ib), ("C", t.vc, t.ic)):
            self.lbl_i[fase].setText(f"{i:.2f} A")
            self.lbl_v[fase].setText(f"{v:.1f} V")
        self.lbl_i1.setText(
            f'|I1| <b style="color:{tk["on"]}">{t.i1:.3f} A</b> pico (carga) &nbsp;·&nbsp; '
            f'Decisión <b style="color:{tk["on"]}">{t.decision}</b> &nbsp;·&nbsp; '
            f'SSR <b style="color:{tk["on"]}">{t.ssr}</b>')

    def _pintar_serie(self):
        if not self._serie or self._pen_borde is None:
            return
        if self.paginas.currentIndex() != 0:
            self._serie_pendiente = True      # se dibuja al volver a Monitoreo
            return
        self._serie_pendiente = False
        xs = [s[0] for s in self._serie]
        self.curva_p.setData(xs, [s[1] for s in self._serie])
        alarma = [s for s in self._serie if s[2] is not None]
        self.puntos_alarma.setData(x=[s[0] for s in alarma], y=[s[1] for s in alarma], pen=self._pen_borde,
                                   brush=[self._brochas[s[2] if s[2] else 2] for s in alarma])
        self.plot.setXRange(xs[-1] - VENTANA_S, xs[-1], padding=0)

    def _bloqueo_liberar(self, t: Trama) -> Optional[str]:
        if self.control is None:
            return "solo con el Arduino conectado"
        if t.motor != "ON":
            return f"motor en {t.motor}"
        if self.control.en_curso or self.control.armada:
            return "hay un pulso o una serie de inyección en curso"
        if self.adquisicion.activa:
            return "hay una captura de Adquisición abierta"
        return None

    def _liberar_alarma(self):
        if self._ultima is None or self._bloqueo_liberar(self._ultima) is not None:
            return
        dlg = DialogoLiberar(self)
        if dlg.exec() != QDialog.Accepted:
            return
        if not self.fuente.reiniciar_detector():
            QMessageBox.warning(self, "Liberar alarma", "No se pudo enviar 'r': sin conexión con el Arduino.")
            return
        LOG.info("Alarma liberada manualmente: se envió 'r' (reinicio del detector)")
        ev = self.registro.liberacion_manual(time.time())
        if ev is not None:
            self._actualizar_fila(ev)
        self.btn_liberar.setVisible(False)

    def _actualizar_fila(self, ev: EventoAlarma):
        fila = self._filas.get(ev.id)
        nueva = fila is None
        if fila is None:
            if self.tabla.rowCount() >= MAX_FILAS_ALARMAS:
                # Se descarta la fila más vieja de la pantalla (el CSV conserva todas)
                self.tabla.removeRow(0)
                self._filas = {k: v - 1 for k, v in self._filas.items() if v > 0}
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            self._filas[ev.id] = fila
        dur = ev.duracion(ev.t_ultima)
        valores = [
            str(ev.id), _hora(ev.t_inicio) + (" *" if ev.ya_activa else ""),
            "en curso" if ev.abierta else _hora(ev.t_fin),
            f"{dur:.1f} s" if dur is not None else "—",
            NOMBRES_SEV[ev.sev_inicial], NOMBRES_SEV[ev.sev_max], f"{ev.ml_max:.2f}",
            f"{ev.i1:.2f}", ev.motivo_fin or "",
        ]
        for col, v in enumerate(valores):
            item = self.tabla.item(fila, col)
            if item is not None and item.text() == v:
                continue                                   # solo se reescriben las celdas que cambian
            item = QTableWidgetItem(v)
            if col == 5:
                item.setForeground(QColor(self.t[SEV_TOKEN[ev.sev_max] + "Fg"]))
            self.tabla.setItem(fila, col, item)
        if nueva:
            self.tabla.scrollToBottom()

    @Slot(str)
    def _on_descartada(self, linea):
        self._n_descartadas += 1
        self.adquisicion.linea_descartada(linea)

    @Slot(bool, str)
    def _on_estado(self, ok, msg):
        if self._conectado and not ok:
            motivo = ("fin del archivo reproducido" if self.es_replay
                      else "conexión perdida (fin real desconocido)")
            ev = self.registro.conexion_perdida(time.time(), msg, motivo)
            if ev is not None:
                self._actualizar_fila(ev)
        self._conectado = ok
        if self.panel_iny is not None:
            self.panel_iny.conexion(ok)
        self.adquisicion.conexion(ok)
        self.dashboard.conexion(ok)
        self._texto_fuente = ("● " if ok else "○ ") + msg
        metr = self.lbl_fuente.fontMetrics()
        self.lbl_fuente.setText(metr.elidedText(self._texto_fuente, Qt.ElideMiddle, 236))
        self.lbl_fuente.setToolTip(self._texto_fuente)
        poner_prop(self.lbl_fuente, "estado", None if ok else ("neutro" if self.es_replay else "mal"))

    def _tic(self):
        partes = [f"{self._n_tramas} tramas"]
        if self._n_descartadas:
            partes.append(f"{self._n_descartadas} descartadas")
        aviso = False
        if self._t_rx is not None:
            edad = time.monotonic() - self._t_rx
            if self._conectado and edad > SIN_DATOS_S:
                partes.insert(0, f"Sin datos hace {edad:.0f} s")
                aviso = True
            elif self._conectado:
                partes.insert(0, f"Hace {edad:.0f} s")
        elif self._conectado:
            partes.insert(0, "Esperando la primera trama…")
        self.lbl_frescura.setText(" · ".join(partes[:2]))
        self.lbl_frescura.setToolTip(" · ".join(partes))
        poner_prop(self.lbl_frescura, "estado", "aviso" if aviso else "tenue")

    # ================================================================== robustez y diálogos
    def _vigilar_fuente(self):
        """Si el hilo de lectura terminó sin que se le pidiera, se reinicia (y queda en app.log)."""
        if self._cerrando or self.fuente.isRunning() or getattr(self.fuente, "detenida", True):
            return
        LOG.error("El hilo de lectura del puerto terminó inesperadamente; se reinicia")
        if self.fuente.reiniciar():
            self._on_error_interno("la lectura del puerto se detuvo y se reinició")

    @Slot(str)
    def _on_error_interno(self, resumen: str):
        self._n_errores += 1
        self.lbl_error.setText(f"⚠ {self._n_errores} error(es) interno(s)")
        self.lbl_error.setToolTip(f"Último: {resumen}\nDetalle en app.log (Ajustes → Abrir carpeta)")
        self.lbl_error.setVisible(True)

    def _abrir_ajustes(self):
        DialogoAjustes(self).exec()

    def _abrir_acerca(self):
        DialogoAcercaDe(self).exec()

    def _alarma_provocada(self) -> bool:
        """La alarma la provocó el usuario: serie de inyección o captura en curso, o un pulso reciente."""
        if self.adquisicion.activa:
            return True
        c = self.control
        if c is None:
            return False
        if c.en_curso or c.armada:
            return True
        ult = c.pulsos[-1] if c.pulsos else None
        return ult is not None and (ult.t_apagado is None or time.time() - ult.t_apagado < VENTANA_PULSO_S)

    def closeEvent(self, event):
        self._cerrando = True
        self._reloj.stop()
        if not self.es_replay:
            self._vigilante.stop()
        try:
            notificador.error.disconnect(self._on_error_interno)
        except (RuntimeError, TypeError):
            pass
        self.adquisicion.cerrar()            # cierra los archivos de una captura abierta (y envía '0' si hace falta)
        self.asistente.cerrar()              # detiene los llama-server del asistente
        if self.panel_iny is not None:
            self.panel_iny.cerrar()          # envía '0' antes de soltar el puerto
        for sig, slot in ((self.fuente.sig_dato, self._on_dato), (self.fuente.sig_estado, self._on_estado),
                          (self.fuente.sig_descartada, self._on_descartada),
                          (self.fuente.sig_respuesta, self.dashboard.respuesta)):
            sig.disconnect(slot)
        try:
            self.tema.cambiado.disconnect(self._aplicar_tema)
        except (RuntimeError, TypeError):
            pass
        self.fuente.detener()
        self.registro.cerrar_sesion(time.time())
        event.accept()
