"""
Sección "Adquisición": captura de datasets nuevos con el banco, con los protocolos de los scripts del autor
(adquisicion/pares.py y adquisicion/base_larga.py). Solo existe con el Arduino.

Seguridad: cada '1' sale de inyeccion/control.py (serie armada con disparo externo) y cada bloque de hasta
10 pulsos pide el mismo diálogo de confirmación que la inyección manual. Mientras haya una captura abierta,
la inyección manual y las consultas del Dashboard quedan bloqueadas. El PARO de la barra superior detiene
el pulso y deja la captura en pausa. La prueba larga sin falla nunca envía '1'.
"""

import os
import time
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QSpinBox, QVBoxLayout, QWidget,
)

from motorguard_dashboard import __version__
from motorguard_dashboard.adquisicion import formato
from motorguard_dashboard.adquisicion.base_larga import PruebaLarga, validar as validar_larga
from motorguard_dashboard.adquisicion.pares import MAX_PARES, CapturaPares, ParametrosPares, validar_parametros
from motorguard_dashboard.inyeccion.control import (
    MAX_PULSOS_SERIE, PULSO_MAX_S, PULSO_MIN_S, ControlInyeccion, PlanSerie, enfriamiento_minimo,
)
from motorguard_dashboard.sistema import bitacora, rutas
from motorguard_dashboard.ui.componentes import FilasValor, Segmentado, boton, etiqueta, poner_prop, tarjeta
from motorguard_dashboard.ui.panel_inyeccion import DialogoSeguridad

TIC_MS = 100
CLASES_UI = ((1, "LEVE"), (2, "INTER"), (3, "SEVERA"))
CARGAS_UI = ("0%", "25%", "50%", "75%")
ORIGEN = f"MotorGuard-ITF {__version__} (sección Adquisición)"


def _spin(minimo, maximo, valor, paso, sufijo="", decimales=2):
    s = QDoubleSpinBox()
    s.setRange(minimo, maximo)
    s.setDecimals(decimales)
    s.setSingleStep(paso)
    s.setValue(valor)
    if sufijo:
        s.setSuffix(sufijo)
    return s


class AdquisicionTab(QWidget):
    def __init__(self, control: Optional[ControlInyeccion], enviar: Optional[Callable[[str], bool]], tema=None,
                 puerto: Callable[[], str] = lambda: "", crudo_sesion: str = "", conf=None, parent=None):
        super().__init__(parent)
        self.control = control
        self._enviar_fn = enviar
        self._tema = tema
        self._puerto = puerto
        self._crudo_sesion = crudo_sesion
        self._conf = conf
        self.captura: Optional[CapturaPares] = None
        self.larga: Optional[PruebaLarga] = None
        self._visto = 0                 # líneas de la consola ya mostradas
        self._origen_consola = None
        self._clase = 0
        self._carga = ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 4, 20)
        lay.setSpacing(20)
        if control is None:
            caja, lc = tarjeta("Adquisición de datos")
            lc.addWidget(etiqueta("Solo con el Arduino conectado: en una reproducción de logs no se adquiere nada.",
                                  "secundario"))
            lay.addWidget(caja)
            lay.addStretch()
            return
        self._construir(lay)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tic)
        self._timer.start(TIC_MS)
        self._refrescar()

    # ================================================================== interfaz
    def _construir(self, lay):
        aviso = QFrame()
        aviso.setProperty("rol", "nota")
        la = QHBoxLayout(aviso)
        la.setContentsMargins(18, 12, 18, 12)
        txt = QLabel("Protocolos de <b>captura_dataset_multiclase.py</b> (v4.2) y <b>prueba_larga_sin_falla.py</b>, "
                     "con los mismos archivos de salida. Cada bloque de hasta 10 pulsos pide confirmación; "
                     "el enfriamiento mínimo es de 15 s (20 s con SEVERA). <b>Alimentación cortada para tocar el "
                     "lazo; nadie lo toca con el motor encendido.</b>")
        txt.setTextFormat(Qt.RichText)
        txt.setWordWrap(True)
        la.addWidget(txt, 1)
        lay.addWidget(aviso)

        cols = QHBoxLayout()
        cols.setSpacing(20)
        izq = QVBoxLayout()
        izq.setSpacing(20)
        cont_izq = QWidget()
        cont_izq.setLayout(izq)
        cont_izq.setMinimumWidth(380)
        cont_izq.setMaximumWidth(480)
        der = QVBoxLayout()
        der.setSpacing(20)
        cols.addWidget(cont_izq, 0, Qt.AlignTop)
        cols.addLayout(der, 1)
        lay.addLayout(cols)

        # --- modo y carpeta
        caja_m, lm = tarjeta("Qué adquirir")
        self.selector_modo = Segmentado((("pares", "Pares SANO/FALLA"), ("larga", "Base sin falla")), "pares")
        self.selector_modo.elegido.connect(self.elegir_modo)
        lm.addWidget(self.selector_modo, 0, Qt.AlignLeft)
        lm.addWidget(etiqueta("Carpeta de datos", "etiqueta"))
        fila_c = QHBoxLayout()
        self.lbl_carpeta = etiqueta(rutas.dir_adquisicion(self._conf), "mono")
        self.lbl_carpeta.setWordWrap(True)
        self.lbl_carpeta.setTextInteractionFlags(Qt.TextSelectableByMouse)
        fila_c.addWidget(self.lbl_carpeta, 1)
        self.btn_carpeta = boton("Cambiar…", "contorno")
        self.btn_carpeta.clicked.connect(self._cambiar_carpeta)
        fila_c.addWidget(self.btn_carpeta)
        lm.addLayout(fila_c)
        self.lbl_carpeta_aviso = etiqueta("", "aviso")
        self.lbl_carpeta_aviso.setWordWrap(True)
        lm.addWidget(self.lbl_carpeta_aviso)
        izq.addWidget(caja_m)

        # --- parámetros
        # Dos tarjetas que se muestran u ocultan (un QStackedWidget estiraría la corta a la altura de la larga)
        self._modo = "pares"
        self.form_pares = self._form_pares()
        self.form_larga = self._form_larga()
        self.form_larga.setVisible(False)
        izq.addWidget(self.form_pares)
        izq.addWidget(self.form_larga)
        izq.addStretch()

        # --- estado y acciones
        caja_e, le = tarjeta()
        cab = QHBoxLayout()
        self.lbl_estado = etiqueta("Sin captura", "tituloTarjeta")
        self.lbl_estado.setWordWrap(True)
        cab.addWidget(self.lbl_estado, 1)
        self.lbl_avance = etiqueta("", "mono")
        cab.addWidget(self.lbl_avance)
        le.addLayout(cab)
        self.barra = QProgressBar()
        self.barra.setRange(0, 1000)
        self.barra.setTextVisible(False)
        self.barra.setAccessibleName("Avance de la adquisición")
        le.addWidget(self.barra)
        self.filas = FilasValor([("a", ""), ("b", ""), ("c", ""), ("d", "")])
        le.addWidget(self.filas)
        self.lbl_msg = etiqueta("", "secundario")
        self.lbl_msg.setWordWrap(True)
        le.addWidget(self.lbl_msg)
        fila_b = QHBoxLayout()
        fila_b.setSpacing(10)
        self.btn_iniciar = boton("Iniciar…")
        if self._tema:
            self._tema.registrar_icono(self.btn_iniciar, "adquisicion", "onPrimary", 16)
        self.btn_iniciar.clicked.connect(self._on_iniciar)
        self.btn_pausar = boton("Pausar", "tonal")
        self.btn_pausar.clicked.connect(self._on_pausar)
        self.btn_terminar = boton("Terminar", "contorno")
        self.btn_terminar.clicked.connect(self._on_terminar)
        for b in (self.btn_iniciar, self.btn_pausar, self.btn_terminar):
            fila_b.addWidget(b)
        fila_b.addStretch()
        le.addLayout(fila_b)
        self.lbl_bloqueo = etiqueta("", "aviso")
        self.lbl_bloqueo.setWordWrap(True)
        le.addWidget(self.lbl_bloqueo)
        self.lbl_arranque = etiqueta("", "aviso")
        self.lbl_arranque.setWordWrap(True)
        self.lbl_arranque.setVisible(False)
        le.addWidget(self.lbl_arranque)
        der.addWidget(caja_e)

        caja_k, lk = tarjeta("Consola")
        self.txt = QPlainTextEdit()
        self.txt.setProperty("rol", "log")
        self.txt.setReadOnly(True)
        self.txt.setMaximumBlockCount(2000)
        self.txt.setMinimumHeight(260)
        lk.addWidget(self.txt)
        self.lbl_archivos = etiqueta("", "secundario")
        self.lbl_archivos.setWordWrap(True)
        self.lbl_archivos.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lk.addWidget(self.lbl_archivos)
        der.addWidget(caja_k)
        der.addStretch()
        self._revisar_carpeta()

    def _form_pares(self) -> QWidget:
        caja, lay = tarjeta("Pares SANO/FALLA")
        lay.addWidget(etiqueta("Clase = taps conectados", "etiqueta"))
        fila = QHBoxLayout()
        fila.setSpacing(8)
        self.grupo_clase = QButtonGroup(self)
        self.botones_clase = {}
        for clase, nombre in CLASES_UI:
            b = boton(nombre, "filtro")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, c=clase: self.elegir_clase(c))
            self.grupo_clase.addButton(b)
            fila.addWidget(b)
            self.botones_clase[clase] = b
        fila.addStretch()
        lay.addLayout(fila)
        lay.addWidget(etiqueta("Carga del generador", "etiqueta"))
        fila2 = QHBoxLayout()
        fila2.setSpacing(8)
        self.grupo_carga = QButtonGroup(self)
        self.botones_carga = {}
        for carga in CARGAS_UI:
            b = boton(carga, "filtro")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, c=carga: self.elegir_carga(c))
            self.grupo_carga.addButton(b)
            fila2.addWidget(b)
            self.botones_carga[carga] = b
        fila2.addStretch()
        lay.addLayout(fila2)

        rej = QGridLayout()
        rej.setHorizontalSpacing(12)
        rej.setVerticalSpacing(4)
        self.spn_pares = QSpinBox()
        self.spn_pares.setRange(1, MAX_PARES)
        self.spn_pares.setValue(75)
        self.spn_dur = _spin(PULSO_MIN_S, PULSO_MAX_S, 7.0, 0.5, " s", 1)
        self.spn_tmin = _spin(0.0, 9.5, 3.0, 0.1, " s", 1)
        self.spn_cool = _spin(enfriamiento_minimo(""), 300.0, enfriamiento_minimo(""), 1.0, " s", 1)
        self.spn_umbral = _spin(0.0, 20.0, 0.0, 0.1, " pp", 2)
        self.spn_tol_i = _spin(0.01, 1.0, 0.06, 0.01, " A", 2)
        self.spn_tol_de2 = _spin(0.05, 5.0, 0.35, 0.05, " pp", 2)
        self.lbl_cool = etiqueta("Enfriamiento (≥ 15 s)", "etiqueta")
        campos = ((etiqueta("Pares", "etiqueta"), self.spn_pares), (etiqueta("Pulso (≤ 11 s)", "etiqueta"), self.spn_dur),
                  (etiqueta("t mín. desde ON", "etiqueta"), self.spn_tmin), (self.lbl_cool, self.spn_cool),
                  (etiqueta("Umbral ΔE2", "etiqueta"), self.spn_umbral), (etiqueta("Tol. corriente", "etiqueta"), self.spn_tol_i),
                  (etiqueta("Tol. ΔE2", "etiqueta"), self.spn_tol_de2))
        for i, (lbl, w) in enumerate(campos):
            fila_g, col = divmod(i, 3)
            rej.addWidget(lbl, fila_g * 2, col)
            rej.addWidget(w, fila_g * 2 + 1, col)
            lbl.setBuddy(w)
        lay.addLayout(rej)
        lay.addWidget(etiqueta("Umbral ΔE2 = 0: sin filtro (filtrar por ΔE2 sesga el dataset).", "secundario"))
        lay.addWidget(etiqueta("Nota del banco (va al _meta.json)", "etiqueta"))
        self.txt_nota = QLineEdit()
        self.txt_nota.setPlaceholderText("p. ej. taps INTER fase C, I_lazo=3.3 A pinza, carga 50 %")
        lay.addWidget(self.txt_nota)
        self.chk_continuar = QCheckBox("Continuar el archivo más reciente de esta clase y carga")
        lay.addWidget(self.chk_continuar)
        return caja

    def _form_larga(self) -> QWidget:
        caja, lay = tarjeta("Base sin falla")
        texto = etiqueta("Tasa de falsas alarmas del detector con el motor sano: nunca se envía '1' (se envía '0' "
                         "cada 60 s). Arranca con el motor girando desde hace ≥ 5 min y cambia la carga cada ~10 min "
                         "(0 → 25 → 50 → 75 → 50 → 25…) sin tocar el lazo.", "secundario")
        texto.setWordWrap(True)
        lay.addWidget(texto)
        rej = QGridLayout()
        rej.setHorizontalSpacing(12)
        self.spn_minutos = _spin(1.0, 1440.0, 90.0, 5.0, " min", 0)
        self.spn_horas = _spin(0.1, 48.0, 3.0, 0.5, " h", 1)
        for col, (t, w) in enumerate((("Exposición con motor ON", self.spn_minutos), ("Tiempo máximo", self.spn_horas))):
            lbl = etiqueta(t, "etiqueta")
            lbl.setBuddy(w)
            rej.addWidget(lbl, 0, col)
            rej.addWidget(w, 1, col)
        lay.addLayout(rej)
        lay.addWidget(etiqueta("Nota (va al _resumen.json)", "etiqueta"))
        self.txt_nota_larga = QLineEdit()
        lay.addWidget(self.txt_nota_larga)
        return caja

    def aplicar_tema(self, t: dict):
        pass

    # ================================================================== estado público
    @property
    def activa(self) -> bool:
        return (self.captura is not None and self.captura.activa) or (self.larga is not None and self.larga.activa)

    def bloqueo_inyeccion(self) -> Optional[str]:
        """Para el panel de inyección manual."""
        if self.captura is not None and self.captura.activa:
            return "hay una captura de pares abierta en Adquisición"
        if self.larga is not None and self.larga.activa:
            return "prueba larga sin falla en curso: no se inyecta"
        return None

    def modo(self) -> str:
        return self._modo

    def elegir_modo(self, modo: str):
        if self.activa:
            self.selector_modo.marcar(self.modo())
            return
        self._modo = modo
        self.form_pares.setVisible(modo == "pares")
        self.form_larga.setVisible(modo == "larga")
        self.selector_modo.marcar(modo)
        self._refrescar()

    def elegir_clase(self, clase: int):
        self._clase = clase
        self.botones_clase[clase].setChecked(True)
        minimo = enfriamiento_minimo(dict(CLASES_UI)[clase])
        self.spn_cool.setMinimum(minimo)
        self.lbl_cool.setText(f"Enfriamiento (≥ {minimo:g} s)")
        self._refrescar()

    def elegir_carga(self, carga: str):
        self._carga = carga
        self.botones_carga[carga].setChecked(True)
        self._refrescar()

    def poner_carpeta(self, ruta: str):
        rutas.poner_dir_adquisicion(ruta, self._conf)
        self.lbl_carpeta.setText(rutas.dir_adquisicion(self._conf))
        self._revisar_carpeta()
        self._refrescar()

    def parametros(self) -> ParametrosPares:
        return ParametrosPares(
            clase=self._clase, carga=self._carga, pares=self.spn_pares.value(), duracion_pulso=self.spn_dur.value(),
            t_min_on=self.spn_tmin.value(), cooldown=self.spn_cool.value(), umbral_e2=self.spn_umbral.value(),
            tol_i=self.spn_tol_i.value(), tol_de2=self.spn_tol_de2.value(), nota=self.txt_nota.text().strip(),
            continuar=self.chk_continuar.isChecked())

    # ================================================================== acciones
    def _cambiar_carpeta(self):
        ruta = QFileDialog.getExistingDirectory(self, "Carpeta de datos de la adquisición", rutas.dir_adquisicion(self._conf))
        if ruta:
            self.poner_carpeta(ruta)

    def _revisar_carpeta(self):
        prot = formato.carpeta_protegida(rutas.dir_adquisicion(self._conf))
        self.lbl_carpeta_aviso.setText(f"No se puede usar: {prot} guarda datos de la tesis." if prot else "")
        self.lbl_carpeta_aviso.setVisible(bool(prot))

    def motivo_no_iniciar(self, ahora: float) -> Optional[str]:
        carpeta = rutas.dir_adquisicion(self._conf)
        if formato.carpeta_protegida(carpeta):
            return "la carpeta de datos es de la tesis: elige otra"
        if self.control.en_curso:
            return "hay una serie de inyección en curso"
        if self.modo() == "pares":
            prm = self.parametros()
            error = validar_parametros(prm)
            if error:
                return error
            return self.control.bloqueo(ahora, prm.label, con_enfriamiento=False)
        error = validar_larga(self.spn_minutos.value(), self.spn_horas.value())
        if error:
            return error
        return None if self.control.conectado else "sin conexión con el Arduino"

    def _on_iniciar(self):
        ahora = time.time()
        if self.captura is not None and self.captura.activa:
            self.confirmar_bloque()
            return
        if self.activa or self.motivo_no_iniciar(ahora):
            return
        if self.modo() == "larga":
            self.iniciar_larga()
            return
        prm = self.parametros()
        carpeta = rutas.dir_adquisicion(self._conf)
        previos = 0
        if prm.continuar:
            ruta, _ = formato.buscar_para_continuar(carpeta, prm.label, prm.carga) if os.path.isdir(carpeta) else (None, "")
            previos = formato.pares_existentes(ruta, corregir=False)[0] if ruta else 0
        if previos >= prm.pares:
            self.lbl_msg.setText(f"El archivo a continuar ya tiene {previos} pares (objetivo {prm.pares}).")
            return
        plan = PlanSerie(prm.label, prm.duracion_pulso, min(MAX_PULSOS_SERIE, prm.pares - previos), prm.cooldown,
                         externo=True)
        if not self._dialogo(plan, prm, primero=True):
            self.lbl_msg.setText("Captura cancelada en el diálogo: no se creó ningún archivo.")
            return
        ahora = time.time()
        try:
            self.captura = CapturaPares(self.control, prm, carpeta, ahora, origen=ORIGEN, puerto=self._puerto(),
                                        crudo_sesion=self._crudo_sesion)
        except (ValueError, OSError) as e:
            self.lbl_msg.setText(f"No se pudo iniciar: {e}")
            return
        self.larga = None
        self._nueva_consola(self.captura)
        bitacora.LOG.info("Adquisición de pares iniciada: %s", self.captura.ruta_csv)
        if self.captura.activa:
            plan = self.captura.plan_bloque()
            conf = self.control.emitir_confirmacion(plan, ahora)
            self._enviar(self.captura.armar(conf, ahora))
        self._refrescar()

    def confirmar_bloque(self):
        """Bloque siguiente (o reanudar tras una pausa): mismo diálogo de seguridad."""
        cap = self.captura
        if cap is None or not cap.espera_confirmacion:
            return
        plan = cap.plan_bloque()
        if self.control.en_curso or self.control.bloqueo(time.time(), plan.taps, con_enfriamiento=False):
            return
        if not self._dialogo(plan, cap.prm, primero=False):
            cap.mensaje = "bloque no confirmado: la captura sigue esperando"
            self._refrescar()
            return
        ahora = time.time()
        conf = self.control.emitir_confirmacion(plan, ahora)
        self._enviar(cap.armar(conf, ahora))

    def _dialogo(self, plan: PlanSerie, prm: ParametrosPares, primero: bool) -> bool:
        resumen = (f"{'Primer bloque' if primero else 'Bloque siguiente'} de la captura {prm.label} con carga "
                   f"{prm.carga}: hasta {plan.n_pulsos} pulso(s) de {plan.duracion_s:g} s, cada uno después de una "
                   f"trama SANO, con pausa ≥ {plan.pausa_s:g} s. Objetivo: {prm.pares} pares.")
        dlg = DialogoSeguridad(plan, self, aviso=self.control.aviso_arranque(time.time()), resumen=resumen)
        return dlg.exec() == QDialog.Accepted

    def iniciar_larga(self):
        ahora = time.time()
        try:
            self.larga = PruebaLarga(rutas.dir_adquisicion(self._conf), ahora, self.spn_minutos.value(),
                                     self.spn_horas.value(), self.txt_nota_larga.text().strip(), origen=ORIGEN,
                                     crudo_sesion=self._crudo_sesion)
        except (ValueError, OSError) as e:
            self.lbl_msg.setText(f"No se pudo iniciar: {e}")
            return
        self.captura = None
        self._nueva_consola(self.larga)
        bitacora.LOG.info("Prueba larga sin falla iniciada: %s", self.larga.base)
        self._enviar(self.larga.tic(ahora))

    def _on_pausar(self):
        if self.captura is not None and self.captura.estado in (self.captura.ESPERA_SANO, self.captura.PULSO):
            self._enviar(self.captura.pausar(time.time()))

    def _on_terminar(self):
        if not self.activa:
            return
        texto = ("¿Terminar la captura? Se cierran los archivos; puedes seguirla después con «Continuar»."
                 if self.captura is not None and self.captura.activa else
                 "¿Terminar la prueba larga? Se puntúa lo registrado hasta ahora.")
        if QMessageBox.question(self, "Terminar", texto) == QMessageBox.Yes:
            self.terminar()

    def terminar(self, motivo: Optional[str] = None):
        ahora = time.time()
        if self.captura is not None and self.captura.activa:
            self._enviar(self.captura.terminar(ahora, motivo or "terminada por el usuario"))
        if self.larga is not None and self.larga.activa:
            self._enviar(self.larga.terminar(ahora, motivo or "terminada por el usuario; se puntúa lo registrado"))
        self._refrescar()

    # ================================================================== entradas de la ventana
    def procesar(self, obj):
        if self.control is None:
            return
        ahora = time.time()
        if self.captura is not None and self.captura.activa:
            self._enviar(self.captura.procesar(obj, ahora))
        elif self.larga is not None and self.larga.activa:
            self._enviar(self.larga.procesar(obj, ahora))

    def linea_descartada(self, linea: str):
        """Trama cortada por el puerto: no se usa, pero queda en el _serial.log como en el script."""
        t = time.time()
        if self.captura is not None and self.captura.activa:
            self.captura.registrar_linea(t, linea)

    def conexion(self, ok: bool):
        self._refrescar()

    def cerrar(self):
        if self.control is None:
            return
        self._timer.stop()
        ahora = time.time()
        if self.captura is not None and self.captura.activa:
            self._enviar(self.captura.cerrar(ahora))
        if self.larga is not None and self.larga.activa:
            self._enviar(self.larga.cerrar(ahora))

    def _enviar(self, cmds):
        for c in cmds:
            if not self._enviar_fn(c) and c == "0":
                self.lbl_msg.setText("⚠ no se pudo enviar '0' (sin conexión). El firmware apaga el SSR a los 12 s "
                                     "y la app envía '0' al reconectar.")
        self._refrescar()

    def _tic(self):
        ahora = time.time()
        if self.captura is not None and self.captura.activa:
            self._enviar(self.captura.tic(ahora))
        elif self.larga is not None and self.larga.activa:
            self._enviar(self.larga.tic(ahora))
        else:
            self._refrescar()

    # ================================================================== refresco
    def _nueva_consola(self, origen):
        self._origen_consola = origen
        self._visto = 0
        self.txt.clear()

    def _volcar_consola(self):
        o = self._origen_consola
        if o is None:
            return
        nuevas = o.n_dichas - self._visto
        if nuevas <= 0:
            return
        lineas = list(o.consola)[-min(nuevas, len(o.consola)):]
        for linea in lineas:
            self.txt.appendPlainText(linea)
        self._visto = o.n_dichas

    def _poner_filas(self, filas):
        for clave, (texto, valor) in zip("abcd", filas + [("", "")] * (4 - len(filas))):
            self.filas.valores[clave].setText(valor)
            fila_lay = self._fila_layout(clave)
            if fila_lay is not None:
                fila_lay.itemAt(0).widget().setText(texto)

    def _fila_layout(self, clave):
        # Las filas de FilasValor son QHBoxLayout (etiqueta, estiramiento, valor) dentro de su QVBoxLayout
        lay = self.filas.layout()
        objetivo = self.filas.valores[clave]
        for i in range(lay.count()):
            item = lay.itemAt(i)
            sub = item.layout()
            if sub is not None and sub.indexOf(objetivo) >= 0:
                return sub
        return None

    def _refrescar(self):
        if self.control is None:
            return
        ahora = time.time()
        self._volcar_consola()
        activa = self.activa
        for w in (self.form_pares, self.form_larga, self.btn_carpeta, self.selector_modo):
            w.setEnabled(not activa)
        cap, larga = self.captura, self.larga

        if cap is not None and (cap.activa or self._origen_consola is cap):
            titulo = {cap.ESPERA_CONFIRMACION: "Esperando confirmación del bloque",
                      cap.ESPERA_SANO: "Esperando trama SANO", cap.PULSO: "Pulso en curso",
                      cap.PAUSADA: "Captura en pausa", cap.TERMINADA: "Captura terminada"}[cap.estado]
            self.lbl_estado.setText(f"{titulo} · {cap.prm.label} {cap.prm.carga}")
            self.lbl_avance.setText(f"{cap.p} / {cap.prm.pares} pares")
            self.barra.setValue(int(1000 * cap.p / max(1, cap.prm.pares)))
            u = cap.ultimo_par
            nuevos = cap.p - cap.sesion["pares_previos"]
            self._poner_filas([
                ("Descartes (esta sesión)", f"{cap.n_desc} ({100 * cap.n_desc / max(1, cap.n_desc + nuevos):.0f} %)"),
                ("Bloque", f"{cap.sesion['bloques']} · pulsos {cap._pulsos_bloque}/{cap._n_bloque}"),
                ("Último par", f"Δe2 {u['delta_e2']:+.2f} pp · I {u['i_sano']:.2f}→{u['i_falla']:.2f} A" if u else "—"),
                ("Tiempos", f"t_off {u['t_off']:.1f} s · t_on {u['t_on']:.1f} s" if u else "—"),
            ])
            self.lbl_msg.setText(cap.mensaje)
            self.lbl_archivos.setText(f"CSV: {cap.ruta_csv}")
        elif larga is not None:
            self.lbl_estado.setText("Prueba larga en curso" if larga.activa else "Prueba larga terminada")
            self.lbl_avance.setText(f"{larga.expo / 60:.1f} / {larga.minutos:g} min")
            self.barra.setValue(int(1000 * min(1.0, larga.expo / (larga.minutos * 60))))
            r = larga.resumen
            self._poner_filas([
                ("Falsas alarmas", str(r["eventos_falsa_alarma"] if r else larga.n_eventos)),
                ("Escalones de carga", str(len(larga.escalones))),
                ("Tiempo transcurrido", f"{(ahora - larga.t_ini) / 60:.0f} min" if larga.activa else "—"),
                ("Tasa (sup. 95 %)", f"{r['tasa_por_hora']} /h ({r['tasa_sup95_por_hora']} /h)" if r else "al terminar"),
            ])
            self.lbl_msg.setText(f"Terminada: {larga.motivo_fin}" if larga.motivo_fin
                                 else "Nunca se envía '1'; '0' cada 60 s.")
            self.lbl_archivos.setText(f"Archivos: {larga.base}_tramas.csv, _serial.log y _resumen.json")
        else:
            self.lbl_estado.setText("Sin captura")
            self.lbl_avance.setText("")
            self.barra.setValue(0)
            self._poner_filas([])
            self.lbl_msg.setText("Elige qué adquirir y los parámetros; «Iniciar…» pide la confirmación de seguridad "
                                 "antes de crear los archivos." if self._modo == "pares" else
                                 "«Iniciar…» crea los archivos y empieza a contar la exposición con el motor en ON.")
            self.lbl_archivos.setText("")
        self.filas.setVisible(bool(cap is not None and (cap.activa or self._origen_consola is cap) or larga is not None))

        # Botones
        motivo = None
        if cap is not None and cap.activa:
            texto_ini = "Reanudar…" if cap.estado == cap.PAUSADA else "Confirmar bloque…"
            habil = cap.espera_confirmacion
            if habil:
                motivo = (("hay una serie de inyección en curso" if self.control.en_curso else None)
                          or self.control.bloqueo(ahora, cap.prm.label, con_enfriamiento=False))
            self.btn_iniciar.setText(texto_ini)
            self.btn_iniciar.setEnabled(habil and motivo is None)
            self.btn_pausar.setEnabled(cap.estado in (cap.ESPERA_SANO, cap.PULSO))
            self.btn_terminar.setEnabled(True)
        elif larga is not None and larga.activa:
            self.btn_iniciar.setText("Iniciar…")
            self.btn_iniciar.setEnabled(False)
            self.btn_pausar.setEnabled(False)
            self.btn_terminar.setEnabled(True)
        else:
            motivo = self.motivo_no_iniciar(ahora)
            self.btn_iniciar.setText("Iniciar…")
            self.btn_iniciar.setEnabled(motivo is None)
            self.btn_pausar.setEnabled(False)
            self.btn_terminar.setEnabled(False)
        self.lbl_bloqueo.setText(f"Bloqueado: {motivo}" if motivo else "")
        self.lbl_bloqueo.setVisible(bool(motivo))
        aviso = self.control.aviso_arranque(ahora)
        self.lbl_arranque.setVisible(aviso is not None)
        if aviso:
            self.lbl_arranque.setText(f"Aviso: {aviso}")
