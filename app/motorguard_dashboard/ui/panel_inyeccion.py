"""
Panel de inyección de fallas (etapa 2). Toda la lógica de seguridad está en inyeccion/control.py;
este panel solo arma el plan, pide la confirmación humana y envía lo que el control indique.
El botón PARO está en la barra superior de la ventana (visible en todas las secciones).
"""

import time
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QProgressBar, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from motorguard_dashboard.inyeccion.control import (
    ControlInyeccion, PlanSerie, TAPS, MAX_PULSOS_SERIE, PULSO_MAX_S, PULSO_MIN_S, enfriamiento_minimo,
    validar_plan,
)
from motorguard_dashboard.telemetry.parser import NOMBRES_SEV
from motorguard_dashboard.ui.componentes import boton, etiqueta, poner_prop, separador

TIC_MS = 100
MAX_FILAS_PULSOS = 200   # filas visibles (el CSV de pulsos guarda todas)


class DialogoSeguridad(QDialog):
    """Confirmación explícita antes de cada serie. 'Inyectar' solo se habilita con todo marcado."""

    def __init__(self, plan: PlanSerie, parent=None, aviso: Optional[str] = None, resumen: Optional[str] = None):
        super().__init__(parent)
        self.setWindowTitle("Confirmar inyección")
        self.setModal(True)
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 18)
        lay.setSpacing(12)
        lay.addWidget(etiqueta("Se encenderá el SSR del lazo de falla (fase C)", "tituloTarjeta"))
        total = plan.n_pulsos * plan.duracion_s + (plan.n_pulsos - 1) * plan.pausa_s
        resumen = etiqueta(resumen or f"Taps declarados: {plan.taps} · {plan.n_pulsos} pulso(s) de {plan.duracion_s:g} s · "
                                     f"pausa de {plan.pausa_s:g} s (≈ {total:.0f} s en total)", "secundario")
        resumen.setWordWrap(True)
        lay.addWidget(resumen)
        self.casillas = [
            QCheckBox("Nadie toca el lazo de inyección (taps, fusible, resistencia, SSR)."),
            QCheckBox(f"Los taps conectados son los de {plan.taps}."),
            QCheckBox("La resistencia limitadora tiene su ventilador encendido."),
        ]
        if plan.taps == "SEVERA":
            # El 08-oct la resistencia se soltó tres veces durante la captura SEVERA (lazo abierto)
            self.casillas.append(QCheckBox("Taps SEVERA: fusible de 10 A rápido, SSR sobre su disipador y "
                                           "resistencia bien fijada (terminales de ojillo)."))
        for c in self.casillas:
            c.toggled.connect(self._revisar)
            lay.addWidget(c)
        if aviso:
            av = etiqueta(f"Aviso: {aviso}.", "aviso")
            av.setWordWrap(True)
            lay.addWidget(av)
        lay.addWidget(etiqueta("El botón PARO de la barra superior envía '0' en cualquier momento.", "secundario"))
        self.botones = QDialogButtonBox()
        btn_no = self.botones.addButton("Cancelar", QDialogButtonBox.RejectRole)
        btn_no.setProperty("variante", "contorno")
        btn_no.setDefault(True)
        self.btn_ok = self.botones.addButton("Inyectar", QDialogButtonBox.AcceptRole)
        self.botones.accepted.connect(self.accept)
        self.botones.rejected.connect(self.reject)
        lay.addWidget(self.botones)
        self._revisar()

    def _revisar(self):
        self.btn_ok.setEnabled(all(c.isChecked() for c in self.casillas))

    def accept(self):
        if all(c.isChecked() for c in self.casillas):
            super().accept()


class PanelInyeccion(QWidget):
    def __init__(self, control: ControlInyeccion, enviar: Callable[[str], bool], tema=None, parent=None):
        super().__init__(parent)
        self.control = control
        # Motivo externo para bloquear la inyección manual (la sección Adquisición mientras captura)
        self.bloqueo_externo: Callable[[], Optional[str]] = lambda: None
        self._enviar_fn = enviar
        self._tema = tema
        self.t = tema.t if tema else None
        self._filas = {}
        self._abiertos_antes = set()
        self._taps = ""
        self._construir()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tic)
        self._timer.start(TIC_MS)

    # ------------------------------------------------------------------ interfaz
    def _construir(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        lay.addWidget(etiqueta("Taps conectados", "etiqueta"))
        fila_t = QHBoxLayout()
        fila_t.setSpacing(8)
        self.grupo_taps = QButtonGroup(self)
        self.grupo_taps.setExclusive(True)
        self.botones_taps = {}
        for t in TAPS:
            b = boton(t, "filtro")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, x=t: self.elegir_taps(x))
            self.grupo_taps.addButton(b)
            fila_t.addWidget(b)
            self.botones_taps[t] = b
        fila_t.addStretch()
        lay.addLayout(fila_t)

        campos = QGridLayout()
        campos.setHorizontalSpacing(10)
        campos.setVerticalSpacing(4)
        self.spn_dur = QDoubleSpinBox()
        self.spn_dur.setRange(PULSO_MIN_S, PULSO_MAX_S)
        self.spn_dur.setSingleStep(0.5)
        self.spn_dur.setValue(5.0)
        self.spn_dur.setSuffix(" s")
        self.spn_n = QSpinBox()
        self.spn_n.setRange(1, MAX_PULSOS_SERIE)
        self.spn_pausa = QDoubleSpinBox()
        self.spn_pausa.setRange(enfriamiento_minimo(""), 300)
        self.spn_pausa.setValue(20.0)
        self.spn_pausa.setSuffix(" s")
        self.lbl_pausa = etiqueta("Pausa (≥ 15 s)", "etiqueta")
        for col, (texto, w) in enumerate(((etiqueta("Duración (≤ 11 s)", "etiqueta"), self.spn_dur),
                                          (etiqueta(f"Pulsos (≤ {MAX_PULSOS_SERIE})", "etiqueta"), self.spn_n),
                                          (self.lbl_pausa, self.spn_pausa))):
            campos.addWidget(texto, 0, col)
            campos.addWidget(w, 1, col)
            texto.setBuddy(w)
        lay.addLayout(campos)

        caja = QFrame()
        caja.setProperty("rol", "contenedor")
        lc = QVBoxLayout(caja)
        lc.setContentsMargins(14, 12, 14, 12)
        lc.setSpacing(8)
        cab = QHBoxLayout()
        self.lbl_estado = QLabel("Sin pulsos en curso")
        self.lbl_estado.setStyleSheet("font-weight: 700;")
        self.lbl_estado.setWordWrap(True)
        self.lbl_avance = etiqueta("", "mono")
        cab.addWidget(self.lbl_estado, 1)
        cab.addWidget(self.lbl_avance)
        lc.addLayout(cab)
        self.barra = QProgressBar()
        self.barra.setRange(0, 1000)
        self.barra.setTextVisible(False)
        self.barra.setAccessibleName("Avance del pulso")
        lc.addWidget(self.barra)
        self.lbl_detalle = etiqueta("El firmware corta a los 12 s; la app, a la duración pedida (≤ 11 s).",
                                    "secundario")
        self.lbl_detalle.setWordWrap(True)
        lc.addWidget(self.lbl_detalle)
        lay.addWidget(caja)

        fila_b = QHBoxLayout()
        fila_b.setSpacing(12)
        self.btn_inyectar = boton("Inyectar…")
        self.btn_inyectar.setEnabled(False)      # lo habilita _refrescar solo si no hay bloqueos
        if self._tema:
            self._tema.registrar_icono(self.btn_inyectar, "rayo", "onPrimary", 16)
        self.btn_inyectar.clicked.connect(self._on_inyectar)
        fila_b.addWidget(self.btn_inyectar)
        self.lbl_bloqueo = etiqueta("", "aviso")
        self.lbl_bloqueo.setWordWrap(True)
        fila_b.addWidget(self.lbl_bloqueo, 1)
        lay.addLayout(fila_b)
        self.lbl_arranque = etiqueta("", "aviso")
        self.lbl_arranque.setWordWrap(True)
        self.lbl_arranque.setVisible(False)
        lay.addWidget(self.lbl_arranque)

        lay.addWidget(separador())
        self.tabla = QTableWidget(0, 6)
        self.tabla.setHorizontalHeaderLabels(["#", "Taps", "Firmware", "Resultado", "Alarma", "Sev."])
        self.tabla.verticalHeader().setVisible(False)
        # Anchos fijos y "Resultado" estirable: así cabe en la tarjeta sin barra horizontal (antes se cortaban
        # "Alarma" y "Sev."; revisión visual, 16-oct). El texto largo se recorta y se ve completo al pasar el ratón.
        cab = self.tabla.horizontalHeader()
        cab.setStretchLastSection(False)
        for col, ancho in enumerate((30, 60, 80, 0, 60, 60)):
            if ancho:
                cab.setSectionResizeMode(col, QHeaderView.Fixed)
                self.tabla.setColumnWidth(col, ancho)
        cab.setSectionResizeMode(3, QHeaderView.Stretch)
        self.tabla.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tabla.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setShowGrid(False)
        self.tabla.setFocusPolicy(Qt.NoFocus)
        self.tabla.setMaximumHeight(170)
        lay.addWidget(self.tabla)

    def aplicar_tema(self, t: dict):
        self.t = t

    def elegir_taps(self, taps: str):
        """Taps conectados declarados por el usuario ('LEVE', 'INTER' o 'SEVERA')."""
        if taps not in TAPS:
            raise ValueError(taps)
        self._taps = taps
        self.botones_taps[taps].setChecked(True)
        minimo = enfriamiento_minimo(taps)
        self.spn_pausa.setMinimum(minimo)
        self.lbl_pausa.setText(f"Pausa (≥ {minimo:g} s)")
        self._refrescar()

    def plan(self) -> PlanSerie:
        return PlanSerie(self._taps, self.spn_dur.value(), self.spn_n.value(), self.spn_pausa.value())

    # ------------------------------------------------------------------ acciones
    def _on_inyectar(self):
        plan = self.plan()
        if validar_plan(plan) or self.control.bloqueo(time.time(), plan.taps) or self.bloqueo_externo():
            return
        dlg = DialogoSeguridad(plan, self, aviso=self.control.aviso_arranque(time.time()))
        if dlg.exec() != QDialog.Accepted:
            self.control.mensaje = "inyección cancelada en el diálogo"
            return
        ahora = time.time()
        conf = self.control.emitir_confirmacion(plan, ahora)
        self._enviar(self.control.iniciar_serie(conf, ahora))

    def _on_paro(self):
        self._enviar(self.control.paro(time.time()))

    def procesar(self, obj):
        self._enviar(self.control.procesar(obj, time.time()))

    def conexion(self, ok: bool):
        self._enviar(self.control.conexion(ok, time.time()))

    def cerrar(self):
        self._timer.stop()
        self._enviar(self.control.cerrar(time.time()))

    def _enviar(self, cmds):
        for c in cmds:
            if not self._enviar_fn(c) and c == "0":
                self.control.mensaje = ("⚠ no se pudo enviar '0' (sin conexión). El firmware apaga el SSR "
                                        "a los 12 s y la app envía '0' al reconectar.")
        self._refrescar()

    def _tic(self):
        self._enviar(self.control.tic(time.time()))

    # ------------------------------------------------------------------ estado
    def _refrescar(self):
        ahora = time.time()
        plan = self.plan()
        c = self.control
        motivo = self.bloqueo_externo() or validar_plan(plan) or c.bloqueo(ahora, plan.taps)
        if c.en_curso:
            motivo = motivo or "serie en curso"
        self.btn_inyectar.setEnabled(motivo is None)
        self.lbl_bloqueo.setText(f"Bloqueado: {motivo}" if motivo else "Listo para inyectar")
        poner_prop(self.lbl_bloqueo, "rol", "aviso" if motivo else "secundario")
        aviso = c.aviso_arranque(ahora)
        self.lbl_arranque.setVisible(aviso is not None)
        if aviso:
            self.lbl_arranque.setText(f"Aviso: {aviso}")

        p = c.pulso_actual
        if p is not None and c.estado == c.ENCENDIDO and p.t_encendido is not None:
            trans = min(ahora - p.t_encendido, p.duracion)
            self.lbl_estado.setText(f"Pulso {p.pulso_en_serie} en curso · {p.taps}")
            self.lbl_avance.setText(f"{trans:.1f} / {p.duracion:g} s")
            self.barra.setValue(int(1000 * trans / p.duracion))
        else:
            titulo = {c.ESPERA_ENCENDIDO: "Esperando confirmación del firmware…",
                      c.ESPERA_APAGADO: "Apagando: esperando confirmación…",
                      c.PAUSA: "Pausa entre pulsos"}.get(c.estado, "Sin pulsos en curso")
            self.lbl_estado.setText(titulo)
            resta = c.enfriamiento_restante(ahora, plan.taps or None)
            self.lbl_avance.setText(f"enfriamiento {resta:.0f} s" if resta > 0 else "")
            self.barra.setValue(0)
        self.lbl_detalle.setText(c.mensaje or "El firmware corta a los 12 s; la app, a la duración pedida (≤ 11 s).")

        # Solo se revisan las filas nuevas y las de pulsos que pueden cambiar (o que acaban de cerrarse): revisar
        # las 200 filas 10 veces por segundo subía el CPU de la app de ~9 % a ~20 % en la prueba de resistencia.
        abiertos = {p.n for p in c.pulsos_abiertos}
        revisar = abiertos | self._abiertos_antes
        self._abiertos_antes = abiertos
        for p in c.pulsos[-MAX_FILAS_PULSOS:]:
            fila = self._filas.get(p.n)
            if fila is not None and p.n not in revisar:
                continue
            if fila is None:
                if self.tabla.rowCount() >= MAX_FILAS_PULSOS:
                    self.tabla.removeRow(0)
                    self._filas = {k: v - 1 for k, v in self._filas.items() if v > 0}
                fila = self.tabla.rowCount()
                self.tabla.insertRow(fila)
                self._filas[p.n] = fila
            vals = [f"{p.serie}.{p.pulso_en_serie}", p.taps, p.confirmacion_fw, p.resultado or "en curso",
                    "sí" if p.alarma else "no", NOMBRES_SEV[p.sev_max] if p.alarma else ""]
            for col, v in enumerate(vals):
                if self.tabla.item(fila, col) is None or self.tabla.item(fila, col).text() != v:
                    item = QTableWidgetItem(v)
                    item.setToolTip(v)
                    self.tabla.setItem(fila, col, item)
