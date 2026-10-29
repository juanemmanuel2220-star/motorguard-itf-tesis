"""
Sección "Asistente": recomendaciones de inspección y mantenimiento con citas (RAG local con Qwen en
llama.cpp; opcionalmente un modelo externo por API elegido por el usuario).

- Apoyo, no diagnóstico: el diagnóstico es el del detector embebido validado.
- Al confirmarse una alarma se consulta automáticamente una vez por evento (desactivable), salvo si la alarma
  la provocó el usuario (serie de inyección o captura de Adquisición en curso, o un pulso en los últimos 30 s).
- Cada línea de la respuesta muestra sus citas; un clic en [n] muestra el fragmento citado y permite abrir
  el documento en esa página. Las líneas sin cita se marcan "sin fuente".
- Las respuestas se guardan en <registros>/asistente_AAAAMMDD.jsonl (sin claves de API).
- El asistente no tiene acceso al puerto serie (ver rag/__init__.py).
"""

import html
import json
import os
import re
import shutil
import subprocess
import time
from typing import Callable, List, Optional

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QTextBrowser, QVBoxLayout, QWidget,
)

from motorguard_dashboard.rag import catalogo
from motorguard_dashboard.rag.asistente import AVISO, ContextoAlarma, Respuesta, describir_fuente
from motorguard_dashboard.rag.proveedores import PRESETS, PROTOCOLOS, ClienteOpenAI, ErrorProveedor, protocolo_de_url
from motorguard_dashboard.sistema import bitacora, claves, rutas
from motorguard_dashboard.telemetry.parser import Trama
from motorguard_dashboard.ui.componentes import (
    FilasValor, Segmentado, boton, chip, etiqueta, poner_prop, separador, tarjeta,
)

SUGERENCIAS = ("¿Qué pruebas de aislamiento conviene hacer?", "¿Cómo se mide el índice de polarización?",
               "¿Cómo mantengo seco el devanado de un motor parado?", "¿Qué significa una alarma LEVE breve?",
               "¿Cómo funciona el detector y el lazo de inyección del banco?")
VENTANA_PULSO_S = 30.0
TITULOS_CORTOS = {"abb": "Manual ABB de motores BT", "nasa_rcm": "NASA · Guía RCM (2008)",
                  "femp_om": "DOE/FEMP · Guía O&M R3.0", "tesis": "Resultados de la tesis",
                  "banco": "Banco de pruebas de la tesis"}
CLAVE_AUTO = "asistente/auto_alarma"
CLAVE_MODELO_LOCAL = "asistente/modelo_local"
CLAVE_PROVEEDOR = "asistente/proveedor"
CLAVE_EXT_URL = "asistente/externo_url"
CLAVE_EXT_MODELO = "asistente/externo_modelo"
CLAVE_EXT_PRESET = "asistente/externo_preset"
CLAVE_EXT_PROTOCOLO = "asistente/externo_protocolo"
CLAVE_EXT_ESFUERZO = "asistente/externo_esfuerzo"
CLAVE_PRECARGA = "asistente/precargar_alarma"
ESFUERZOS = (("low", "Bajo"), ("medium", "Medio"), ("high", "Alto"))
CLAVE_EXT_ACEPTADO = "asistente/externo_aviso_aceptado"


def _licencia_corta(rec: catalogo.Recurso) -> str:
    if not rec.redistribuible:
        return "© ABB · solo uso local"
    return {"CC BY 4.0": "CC BY 4.0"}.get(rec.licencia, "Dominio público" if "público" in rec.licencia else rec.licencia)


def _b(v) -> bool:
    return v is True or str(v).lower() in ("true", "1")


from motorguard_dashboard.ui import marcas
from motorguard_dashboard.ui.conversacion import Conversacion, html_respuesta  # noqa: E402,F401 (compatibilidad)


class DialogoExterno(QDialog):
    """Configura un proveedor externo: API compatible con OpenAI o nativa de Anthropic (la clave va al llavero)."""

    def __init__(self, conf: QSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Modelo externo por API")
        self.conf = conf
        lay = QVBoxLayout(self)
        nota = QLabel("Opcional. El modelo local sigue siendo el predeterminado. Se usa una <b>clave de API</b> del "
                      "proveedor (no una suscripción de chat). La clave se guarda en el llavero del sistema"
                      + ("" if claves.hay_llavero() else " — <b>no hay llavero: solo durante esta sesión</b>") + ".")
        nota.setWordWrap(True)
        nota.setTextFormat(Qt.RichText)
        lay.addWidget(nota)
        form = QFormLayout()
        self.cmb_preset = QComboBox()
        self.cmb_preset.addItems(list(PRESETS))
        self.txt_url = QLineEdit(str(conf.value(CLAVE_EXT_URL, "")))
        self.txt_clave = QLineEdit()
        self.txt_clave.setEchoMode(QLineEdit.Password)
        self.txt_clave.setPlaceholderText("(guardada)" if self.txt_url.text() and claves.leer(self.txt_url.text())
                                          else "clave de API")
        self.cmb_protocolo = QComboBox()
        for clave, texto in PROTOCOLOS.items():
            self.cmb_protocolo.addItem(texto, clave)
        prot = str(conf.value(CLAVE_EXT_PROTOCOLO, "")) or protocolo_de_url(self.txt_url.text())
        self.cmb_protocolo.setCurrentIndex(max(0, self.cmb_protocolo.findData(prot)))
        self.cmb_modelo = QComboBox()
        self.cmb_modelo.setEditable(True)
        self.cmb_modelo.setCurrentText(str(conf.value(CLAVE_EXT_MODELO, "")))
        preset = str(conf.value(CLAVE_EXT_PRESET, ""))
        if preset in PRESETS:
            self.cmb_preset.setCurrentText(preset)
        self.cmb_preset.currentTextChanged.connect(self._preset)
        if not self.txt_url.text():
            self._preset(self.cmb_preset.currentText())
        form.addRow("Proveedor", self.cmb_preset)
        form.addRow("URL de la API", self.txt_url)
        form.addRow("Protocolo", self.cmb_protocolo)
        form.addRow("Clave", self.txt_clave)
        fila = QHBoxLayout()
        fila.addWidget(self.cmb_modelo, 1)
        self.btn_modelos = QPushButton("Cargar modelos")
        self.btn_modelos.clicked.connect(self._cargar_modelos)
        fila.addWidget(self.btn_modelos)
        form.addRow("Modelo", fila)
        lay.addLayout(form)
        self.lbl_msg = etiqueta("", "secundario")
        self.lbl_msg.setWordWrap(True)
        lay.addWidget(self.lbl_msg)
        self.chk_aviso = QCheckBox("Entiendo que, al usar este proveedor, salen de la PC la pregunta, los valores de "
                                   "la alarma y los fragmentos de los documentos (incluido el manual ABB).")
        self.chk_aviso.setChecked(_b(conf.value(CLAVE_EXT_ACEPTADO + "/" + self._host(), False)))
        lay.addWidget(self.chk_aviso)
        botones = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.btn_guardar = botones.button(QDialogButtonBox.Save)
        botones.accepted.connect(self._guardar)
        botones.rejected.connect(self.reject)
        lay.addWidget(botones)
        self.chk_aviso.toggled.connect(self._validar)
        self.txt_url.textChanged.connect(self._validar)
        self.cmb_modelo.currentTextChanged.connect(self._validar)
        self._validar()

    def _host(self) -> str:
        from urllib.parse import urlparse
        return urlparse(self.txt_url.text()).netloc or "sin_url"

    def _preset(self, nombre: str):
        url = PRESETS.get(nombre, "")
        if url or nombre == "URL personalizada":
            self.txt_url.setText(url)
        if url:
            self.cmb_protocolo.setCurrentIndex(self.cmb_protocolo.findData(protocolo_de_url(url)))

    def _clave(self) -> Optional[str]:
        return self.txt_clave.text().strip() or claves.leer(self.txt_url.text())

    def _validar(self):
        ok = bool(self.txt_url.text().startswith("https://") or self.txt_url.text().startswith("http://127.0.0.1"))
        self.btn_guardar.setEnabled(ok and bool(self.cmb_modelo.currentText().strip()) and self.chk_aviso.isChecked())

    def _cargar_modelos(self):
        self.lbl_msg.setText("Consultando modelos…")
        self.repaint()
        try:
            ids = ClienteOpenAI(self.txt_url.text(), clave=self._clave(), timeout=15,
                                protocolo=self.cmb_protocolo.currentData()).modelos()
        except ErrorProveedor as e:
            self.lbl_msg.setText(f"No se pudo consultar: {e}")
            return
        actual = self.cmb_modelo.currentText()
        self.cmb_modelo.clear()
        self.cmb_modelo.addItems(ids)
        if actual:
            self.cmb_modelo.setCurrentText(actual)
        self.lbl_msg.setText(f"{len(ids)} modelos disponibles.")

    def _guardar(self):
        url = self.txt_url.text().strip()
        if self.txt_clave.text().strip():
            en_llavero = claves.guardar(url, self.txt_clave.text().strip())
            if not en_llavero:
                self.lbl_msg.setText("No hay llavero: la clave se usará solo en esta sesión.")
        self.conf.setValue(CLAVE_EXT_URL, url)
        self.conf.setValue(CLAVE_EXT_MODELO, self.cmb_modelo.currentText().strip())
        self.conf.setValue(CLAVE_EXT_PRESET, self.cmb_preset.currentText())
        self.conf.setValue(CLAVE_EXT_PROTOCOLO, self.cmb_protocolo.currentData())
        self.conf.setValue(CLAVE_EXT_ACEPTADO + "/" + self._host(), True)
        self.accept()


class AsistenteTab(QWidget):
    def __init__(self, tema=None, provocada: Optional[Callable[[], bool]] = None,
                 conf: Optional[QSettings] = None, parent=None):
        super().__init__(parent)
        self._tema = tema
        self._t = tema.t if tema else {}
        self._provocada = provocada or (lambda: False)
        self._conf = conf or rutas.ajustes()
        self.servicio = None
        self._consultadas = set()
        self._entradas: List[dict] = []         # {"pregunta", "alarma", "texto" (en vivo), "r": Respuesta|None}
        self._ctx: Optional[ContextoAlarma] = None
        self._redibujo = QTimer(self)
        self._redibujo.setSingleShot(True)
        self._redibujo.setInterval(150)
        self._redibujo.timeout.connect(self._render)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 4, 20)
        lay.setSpacing(20)

        aviso = QFrame()
        aviso.setProperty("rol", "nota")
        la = QHBoxLayout(aviso)
        la.setContentsMargins(18, 14, 18, 14)
        la.setSpacing(12)
        ic = QLabel()
        if tema:
            tema.registrar_icono(ic, "info", "onPrimaryC", 22)
        la.addWidget(ic, 0, Qt.AlignTop)
        txt = QLabel(f"<b>{AVISO.split(':')[0]}.</b> {AVISO.split(':', 1)[1].strip().capitalize()} El asistente "
                     "propone inspecciones y mantenimiento citando el documento y la página de cada recomendación; "
                     "si no encuentra fuente, lo dice.")
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
        cont_izq.setMinimumWidth(360)
        cont_izq.setMaximumWidth(460)

        # --- contexto de la alarma (solo valores medidos)
        caja_c, lc = tarjeta()
        cab = QHBoxLayout()
        cab.addWidget(etiqueta("Alarma", "tituloTarjeta"))
        cab.addStretch()
        self.chip_sev = etiqueta("SIN ALARMA", chipSev="sano")
        cab.addWidget(self.chip_sev)
        lc.addLayout(cab)
        nota = etiqueta("Solo valores medidos de la trama; el asistente no inventa mediciones", "secundario")
        nota.setWordWrap(True)
        lc.addWidget(nota)
        self.filas = FilasValor([("inicio", "Inicio"), ("tiempo", "Tiempo con alarma"),
                                 ("ml", "Magnitud de la firma (ML)"), ("i1", "Carga |I1|"),
                                 ("i", "I_A · I_B · I_C"), ("decision", "Decisión del firmware")])
        lc.addWidget(self.filas)
        self.btn_recomendar = boton("Recomendar para esta alarma", "tonal")
        self.btn_recomendar.setEnabled(False)
        self.btn_recomendar.clicked.connect(self._recomendar_alarma)
        lc.addWidget(self.btn_recomendar)
        self.chk_auto = QCheckBox("Recomendar al confirmarse una alarma")
        self.chk_auto.setChecked(_b(self._conf.value(CLAVE_AUTO, True)))
        self.chk_auto.toggled.connect(lambda v: self._conf.setValue(CLAVE_AUTO, v))
        lc.addWidget(self.chk_auto)
        self.chk_precarga = QCheckBox("Precargar la consulta de alarma al abrir")
        self.chk_precarga.setToolTip("Con el modelo local, la respuesta a una alarma baja de ~3 a ~1.5 min, pero al "
                                     "abrir la app el modelo pasa 2–3 min preparándose. Desactívala para "
                                     "demostraciones rápidas. Con el modelo externo no hace falta y se omite sola.")
        self.chk_precarga.setChecked(_b(self._conf.value(CLAVE_PRECARGA, True)))
        self.chk_precarga.toggled.connect(self._cambiar_precarga)
        lc.addWidget(self.chk_precarga)
        izq.addWidget(caja_c)

        # --- modelo y estado del servicio
        caja_m, lm = tarjeta("Modelo")
        self.sel_modelo = Segmentado([("local", "Local"), ("externo", "Externo (API)")],
                                     str(self._conf.value(CLAVE_PROVEEDOR, "local")))
        self.sel_modelo.elegido.connect(self._elegir_proveedor)
        lm.addWidget(self.sel_modelo)
        # Modelo activo: logotipo, nombre y de dónde responde
        fila_m = QHBoxLayout()
        fila_m.setSpacing(12)
        self.lbl_logo = QLabel()
        self.lbl_logo.setFixedSize(44, 44)
        self.lbl_logo.setAlignment(Qt.AlignCenter)
        self.lbl_logo.setProperty("rol", "contenedorIcono")
        fila_m.addWidget(self.lbl_logo, 0, Qt.AlignTop)
        textos_m = QVBoxLayout()
        textos_m.setSpacing(2)
        self.lbl_nombre_modelo = QLabel()
        self.lbl_nombre_modelo.setStyleSheet("font-size: 16px; font-weight: 700;")
        self.lbl_externo = etiqueta("", "secundario")      # de dónde responde (local / proveedor externo)
        self.lbl_externo.setWordWrap(True)
        textos_m.addWidget(self.lbl_nombre_modelo)
        textos_m.addWidget(self.lbl_externo)
        fila_m.addLayout(textos_m, 1)
        lm.addLayout(fila_m)
        # Esfuerzo de razonamiento (modelos de Claude): más bajo, más rápido y barato
        self.caja_esfuerzo = QWidget()
        le = QVBoxLayout(self.caja_esfuerzo)
        le.setContentsMargins(0, 0, 0, 0)
        le.setSpacing(6)
        le.addWidget(etiqueta("Esfuerzo de razonamiento", "etiqueta"))
        self.sel_esfuerzo = Segmentado(list(ESFUERZOS), str(self._conf.value(CLAVE_EXT_ESFUERZO, "low")))
        self.sel_esfuerzo.setToolTip("Bajo: más rápido y barato (recomendado para estas respuestas cortas con "
                                     "fragmentos). Alto: razona más antes de responder; tarda y cuesta más.")
        self.sel_esfuerzo.elegido.connect(self._elegir_esfuerzo)
        le.addWidget(self.sel_esfuerzo)
        lm.addWidget(self.caja_esfuerzo)
        self.cmb_local = QComboBox()
        for rec in catalogo.MODELOS_LLM:
            self.cmb_local.addItem(f"{rec.titulo} (local, {rec.tam / 1e9:.1f} GB)", rec.clave)
        idx = self.cmb_local.findData(str(self._conf.value(CLAVE_MODELO_LOCAL, catalogo.MODELO_LLM.clave)))
        self.cmb_local.setCurrentIndex(max(0, idx))
        self.cmb_local.currentIndexChanged.connect(self._cambiar_local)
        lm.addWidget(self.cmb_local)
        self.btn_externo = boton("Configurar modelo externo…", "contorno")
        self.btn_externo.clicked.connect(self._configurar_externo)
        lm.addWidget(self.btn_externo)
        lm.addWidget(separador())
        self.lbl_servicio = etiqueta("Asistente apagado", "secundario")
        self.lbl_servicio.setWordWrap(True)
        lm.addWidget(self.lbl_servicio)
        self.barra = QProgressBar()
        self.barra.setVisible(False)
        lm.addWidget(self.barra)
        self.btn_preparar = boton("Preparar asistente", "tonal")
        self.btn_preparar.setToolTip("Descarga el motor llama.cpp, los modelos Qwen y los documentos de sus "
                                     "fuentes oficiales, y construye el índice")
        self.btn_preparar.clicked.connect(self._preparar)
        lm.addWidget(self.btn_preparar)
        izq.addWidget(caja_m)

        # --- fuentes
        caja_f, self.lay_fuentes = tarjeta("Fuentes", "de uso legal · índice local")
        self._filas_fuentes = {}
        for rec in catalogo.DOCUMENTOS:
            self.lay_fuentes.addWidget(separador())
            fila_w = QWidget()
            fila = QHBoxLayout(fila_w)
            fila.setContentsMargins(0, 2, 0, 2)
            fila.setSpacing(10)
            textos = QVBoxLayout()
            textos.setSpacing(1)
            t1 = QLabel(TITULOS_CORTOS.get(rec.clave, rec.titulo))
            t1.setStyleSheet("font-weight: 600;")
            t2 = etiqueta(_licencia_corta(rec), "secundario")
            textos.addWidget(t1)
            textos.addWidget(t2)
            fila.addLayout(textos, 1)
            c = chip("—", "neutro")
            fila.addWidget(c, 0, Qt.AlignVCenter)
            fila_w.setToolTip(f"{rec.titulo}\n{rec.detalle}\n{rec.licencia}")
            self.lay_fuentes.addWidget(fila_w)
            self._filas_fuentes[rec.clave] = c
        izq.addWidget(caja_f)
        izq.addStretch()
        cols.addWidget(cont_izq, 0, Qt.AlignTop)

        # --- conversación
        der = QVBoxLayout()
        der.setSpacing(20)
        caja_r, lr = tarjeta("Conversación")
        self._botones_sug = []
        for q in SUGERENCIAS:
            b = boton(q, "filtro")
            b.clicked.connect(lambda _=False, q=q: self._preguntar(q))
            self._botones_sug.append(b)
        self.conversacion = Conversacion(self._cita, self._botones_sug)
        lr.addWidget(self.conversacion, 1)
        # Caja de entrada redondeada: ↑ envía; mientras genera, ■ detiene
        self.caja_entrada = QFrame()
        self.caja_entrada.setProperty("rol", "cajaEntrada")
        fila = QHBoxLayout(self.caja_entrada)
        fila.setContentsMargins(14, 4, 6, 4)
        self.txt_pregunta = QLineEdit()
        self.txt_pregunta.setPlaceholderText("Pregunte sobre inspección o mantenimiento del motor…")
        self.txt_pregunta.returnPressed.connect(self._preguntar)
        fila.addWidget(self.txt_pregunta, 1)
        self.btn_preguntar = boton("", "enviar")
        self.btn_preguntar.setToolTip("Preguntar (Enter)")
        self.btn_preguntar.clicked.connect(self._preguntar)
        fila.addWidget(self.btn_preguntar)
        self.btn_cancelar = boton("", "detener")
        self.btn_cancelar.setToolTip("Detener la respuesta")
        self.btn_cancelar.setEnabled(False)
        self.btn_cancelar.setVisible(False)
        self.btn_cancelar.clicked.connect(self._cancelar)
        fila.addWidget(self.btn_cancelar)
        if self._tema is not None:
            self._tema.registrar_icono(self.btn_preguntar, "enviar", "onPrimary", 18)
            self._tema.registrar_icono(self.btn_cancelar, "detener", "surface", 16)
        lr.addWidget(self.caja_entrada)
        self.lbl_cola = etiqueta("", "secundario")
        self.lbl_cola.setWordWrap(True)
        self.lbl_cola.setVisible(False)
        lr.addWidget(self.lbl_cola)
        der.addWidget(caja_r)

        self.caja_frag, lfr = tarjeta("Fragmento citado")
        self.lbl_frag = etiqueta("", "secundario")
        self.lbl_frag.setWordWrap(True)
        lfr.addWidget(self.lbl_frag)
        self.txt_frag = QTextBrowser()
        self.txt_frag.setMaximumHeight(200)
        lfr.addWidget(self.txt_frag)
        self.btn_abrir = boton("Abrir el documento en esa página", "contorno")
        self.btn_abrir.clicked.connect(self._abrir_documento)
        lfr.addWidget(self.btn_abrir, 0, Qt.AlignLeft)
        self.caja_frag.setVisible(False)
        self._frag_actual = None
        der.addWidget(self.caja_frag)
        der.addStretch()
        cols.addLayout(der, 1)
        lay.addLayout(cols)
        lay.addStretch()

        self._actualizar_externo()
        self._actualizar_botones()
        self._render()
        try:
            from motorguard_dashboard.rag import biblioteca
            self._on_documentos(biblioteca.estado_documentos(rutas.dir_documentos(self._conf)))
        except OSError:
            pass

    # ================================================================ servicio
    def iniciar_servicio(self, servicio=None):
        """Crea y arranca el servicio (en app.py; las pruebas pasan uno propio o no lo arrancan)."""
        if self.servicio is not None:
            return
        if servicio is None:
            from motorguard_dashboard.ui.asistente_servicio import ServicioAsistente
            servicio = ServicioAsistente(rutas.dir_asistente(), lambda: rutas.dir_documentos(self._conf),
                                         self._rec_local())
        self.servicio = servicio
        servicio.sig_estado.connect(self._on_estado)
        servicio.sig_progreso.connect(self._on_progreso)
        servicio.sig_token.connect(self._on_token)
        servicio.sig_inicio_respuesta.connect(self._on_inicio)
        servicio.sig_respuesta.connect(self._on_respuesta)
        servicio.sig_documentos.connect(self._on_documentos)
        servicio.precargar = self.chk_precarga.isChecked()
        self._aplicar_externo()
        self._on_documentos(servicio.documentos())
        servicio.iniciar()
        self._actualizar_botones()

    def cerrar(self):
        if self.servicio is not None:
            self.servicio.cerrar()

    def _rec_local(self) -> catalogo.Recurso:
        clave = self.cmb_local.currentData()
        return next((r for r in catalogo.MODELOS_LLM if r.clave == clave), catalogo.MODELO_LLM)

    def _on_estado(self, estado: str, texto: str):
        self.lbl_servicio.setText(texto)
        self.barra.setVisible(estado in ("preparando", "indexando"))
        self._actualizar_botones()
        self._render()          # el texto de la conversación vacía decía «todavía no está listo» ya con el modelo listo

    def _on_progreso(self, etapa: str, n: int, total: int):
        self.barra.setVisible(True)
        self.barra.setMaximum(max(1, total))
        self.barra.setValue(n)
        self.barra.setFormat(f"{etapa}: {n}/{total}")

    def _on_documentos(self, estados):
        for e in estados:
            c = self._filas_fuentes.get(e.rec.clave)
            if c is None:
                continue
            texto, est = {"listo": ("Disponible", "bien"), "distinto": ("Versión distinta", "aviso"),
                          "falta": ("Falta", "neutro")}[e.estado]
            c.setText(texto)
            poner_prop(c, "estado", est)
            c.setToolTip(e.ruta)

    def _actualizar_botones(self):
        listo = self.servicio is not None and self.servicio.listo
        ocupado = self.servicio is not None and self.servicio.ocupado
        for b in [self.btn_preguntar] + self._botones_sug:
            b.setEnabled(listo)
        self.btn_cancelar.setEnabled(ocupado and listo)
        self.btn_cancelar.setVisible(ocupado and listo)
        self.btn_preguntar.setVisible(not (ocupado and listo))
        self.btn_recomendar.setEnabled(listo and self._ctx is not None and self._ctx.severidad is not None)
        self.btn_preparar.setEnabled(self.servicio is not None and self.servicio.estado in ("falta", "error", "apagado"))

    # ================================================================ proveedor
    def _cliente_externo(self) -> Optional[ClienteOpenAI]:
        url = str(self._conf.value(CLAVE_EXT_URL, ""))
        modelo = str(self._conf.value(CLAVE_EXT_MODELO, ""))
        if not url or not modelo:
            return None
        from urllib.parse import urlparse
        if not _b(self._conf.value(CLAVE_EXT_ACEPTADO + "/" + (urlparse(url).netloc or "sin_url"), False)):
            return None
        prot = str(self._conf.value(CLAVE_EXT_PROTOCOLO, "")) or protocolo_de_url(url)
        return ClienteOpenAI(url, modelo, clave=claves.leer(url), timeout=60, nombre=f"{modelo} (externo)",
                             protocolo=prot if prot in PROTOCOLOS else None,
                             esfuerzo=str(self._conf.value(CLAVE_EXT_ESFUERZO, "low")))

    def _aplicar_externo(self):
        if self.servicio is None:
            return
        usar = str(self._conf.value(CLAVE_PROVEEDOR, "local")) == "externo"
        self.servicio.externo = self._cliente_externo() if usar else None
        if hasattr(self.servicio, "precargar_si_conviene"):
            self.servicio.precargar_si_conviene()          # al volver al modelo local, se precarga si hace falta

    def _cambiar_precarga(self, activa: bool):
        self._conf.setValue(CLAVE_PRECARGA, activa)
        if self.servicio is not None:
            self.servicio.precargar = activa
            if hasattr(self.servicio, "precargar_si_conviene"):
                self.servicio.precargar_si_conviene()

    def _actualizar_externo(self):
        """Tarjeta Modelo: logotipo y nombre del modelo que responde, de dónde responde y el esfuerzo (Claude)."""
        cli = self._cliente_externo()
        usar = str(self._conf.value(CLAVE_PROVEEDOR, "local")) == "externo"
        self.cmb_local.setVisible(not usar)
        t = self._t or {"on": "#191C21", "surface2": "#F0F2F8", "muted": "#474B55"}
        if usar and cli is not None:
            slug = marcas.marca(cli.modelo, cli.base_url)
            self.lbl_nombre_modelo.setText(marcas.nombre_modelo(cli.modelo))
            self.lbl_externo.setText(f"{marcas.proveedor(cli.base_url)} · API externa · si falla, responde el local")
            self.caja_esfuerzo.setVisible(cli.protocolo == "anthropic")
        elif usar:
            slug = None
            self.lbl_nombre_modelo.setText("Sin modelo externo")
            self.lbl_externo.setText("Configúralo con «Configurar modelo externo…».")
            self.caja_esfuerzo.setVisible(False)
        else:
            rec = self._rec_local()
            slug = marcas.marca(rec.titulo)
            self.lbl_nombre_modelo.setText(rec.titulo)
            self.lbl_externo.setText("Local en esta PC · sin internet")
            self.caja_esfuerzo.setVisible(False)
        if slug:
            self.lbl_logo.setPixmap(marcas.pixmap(slug, marcas.color(slug, t), 26))
        elif t.get("muted"):
            from motorguard_dashboard.ui.tema import icono
            from PySide6.QtCore import QSize
            self.lbl_logo.setPixmap(icono("asistente", t["muted"], 24).pixmap(QSize(24, 24)))

    def _elegir_esfuerzo(self, clave: str):
        self._conf.setValue(CLAVE_EXT_ESFUERZO, clave)
        self._aplicar_externo()
        self._actualizar_externo()

    def _elegir_proveedor(self, clave: str):
        if clave == "externo" and self._cliente_externo() is None:
            if not self._configurar_externo():
                self.sel_modelo.marcar("local")
                return
        self._conf.setValue(CLAVE_PROVEEDOR, clave)
        self._aplicar_externo()
        self._actualizar_externo()

    def _configurar_externo(self) -> bool:
        dlg = DialogoExterno(self._conf, self)
        ok = dlg.exec() == QDialog.Accepted
        self._aplicar_externo()
        self._actualizar_externo()
        return ok

    def _cambiar_local(self, _idx: int):
        rec = self._rec_local()
        self._conf.setValue(CLAVE_MODELO_LOCAL, rec.clave)
        self._actualizar_externo()
        if self.servicio is not None:
            self.servicio.cambiar_modelo(rec)

    # ================================================================ preguntas
    def _preguntar(self, texto: Optional[str] = None):
        q = (texto if isinstance(texto, str) else self.txt_pregunta.text()).strip()
        if not q or self.servicio is None or not self.servicio.listo:
            return
        self.txt_pregunta.clear()
        motivo = self.servicio.motivo_espera()
        self.servicio.preguntar(q, self._ctx)
        if motivo:
            self.lbl_cola.setText(f"«{q}» está en cola: {motivo}")
            self.lbl_cola.setVisible(True)

    def _recomendar_alarma(self):
        if self.servicio is not None and self._ctx is not None and self._ctx.severidad:
            self.servicio.preguntar("", self._ctx, alarma=True)

    def _cancelar(self):
        if self.servicio is not None:
            self.servicio.cancelar()

    def _preparar(self):
        if self.servicio is not None:
            self.servicio.preparar()

    def _on_inicio(self, pregunta: str, alarma: bool):
        self.lbl_cola.setVisible(False)
        self._entradas.append({"pregunta": pregunta, "alarma": alarma, "texto": "", "r": None,
                               "hora": time.strftime("%H:%M:%S")})
        self.btn_cancelar.setEnabled(True)
        self.btn_cancelar.setVisible(True)
        self.btn_preguntar.setVisible(False)
        self._render()

    def _on_token(self, trozo: str):
        if self._entradas and self._entradas[-1]["r"] is None:
            self._entradas[-1]["texto"] += trozo
            if not self._redibujo.isActive():
                self._redibujo.start()

    def _on_respuesta(self, r: Respuesta):
        if not self._entradas or self._entradas[-1]["r"] is not None:
            self._entradas.append({"pregunta": r.pregunta, "alarma": False, "texto": "", "r": r,
                                   "hora": time.strftime("%H:%M:%S")})
        else:
            self._entradas[-1]["r"] = r
        self._render()
        self._actualizar_botones()
        self._guardar_respuesta(r, self._entradas[-1]["alarma"])

    def _guardar_respuesta(self, r: Respuesta, alarma: bool):
        try:
            carpeta = rutas.dir_registros(self._conf)
            os.makedirs(carpeta, exist_ok=True)
            ruta = os.path.join(carpeta, time.strftime("asistente_%Y%m%d.jsonl"))
            fila = {"hora": time.strftime("%Y-%m-%d %H:%M:%S"), "alarma": alarma, "pregunta": r.pregunta,
                    # El contexto que recibió el modelo, no el de la trama actual: una alarma tarda ~80 s en
                    # responderse y para entonces pudo liberarse o el motor apagarse (banco, 13-oct)
                    "contexto": r.contexto,
                    "modelo": r.modelo, "abstencion": r.abstencion, "max_coseno": round(r.max_coseno, 4),
                    "respuesta": r.texto, "aviso": r.aviso, "error": r.error, "cancelada": r.cancelada,
                    "fuentes": [describir_fuente(f) for f in r.fuentes],
                    "fraccion_citada": r.fraccion_citada, "t_busqueda_s": round(r.t_busqueda, 2),
                    "t_primer_token_s": r.t_primer_token and round(r.t_primer_token, 2),
                    "t_total_s": round(r.t_total, 2), "tokens_prompt": r.tokens_prompt,
                    "tokens_respuesta": r.tokens_respuesta}
            with open(ruta, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(fila, ensure_ascii=False) + "\n")
        except OSError as e:
            bitacora.LOG.warning("Asistente: no se pudo guardar la respuesta: %s", e)

    def _render(self):
        t = self._t or {"primary": "#2457A6", "primaryC": "#D8E2FF", "onPrimaryC": "#001A41", "muted": "#474B55",
                        "error": "#B3261E", "leveFg": "#7A5300", "surface2": "#F0F2F8", "on": "#191C21"}
        self.conversacion.mostrar(self._entradas, t, self.servicio is not None and self.servicio.listo)

    def _cita(self, url: QUrl):
        m = re.fullmatch(r"cita:(\d+)-(\d+)", url.toString())
        if not m:
            return
        e, n = int(m.group(1)), int(m.group(2))
        if e >= len(self._entradas) or self._entradas[e]["r"] is None:
            return
        fuentes = self._entradas[e]["r"].fuentes
        if not 1 <= n <= len(fuentes):
            return
        f = fuentes[n - 1]
        self._frag_actual = f.fragmento
        self.lbl_frag.setText(f"[{n}] {describir_fuente(f)}")
        self.txt_frag.setPlainText(f.fragmento.texto)
        self.caja_frag.setVisible(True)

    def _abrir_documento(self):
        f = self._frag_actual
        if f is None:
            return
        from motorguard_dashboard.rag.ingesta import ruta_documento
        rec = next((r for r in catalogo.DOCUMENTOS if r.clave == f.doc), None)
        if rec is None:
            return
        ruta = ruta_documento(rec, rutas.dir_documentos(self._conf))
        if not os.path.exists(ruta):
            QMessageBox.information(self, "Documento", f"No se encontró {ruta}.")
            return
        if ruta.endswith(".pdf") and shutil.which("evince"):
            subprocess.Popen(["evince", "-i", str(f.pag), ruta], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(ruta))

    # ================================================================ tema y contexto
    def aplicar_tema(self, t: dict):
        self._t = t
        for w in self.findChildren(QLabel):
            if w.property("rol") == "contenedorIcono":
                w.setStyleSheet(f"background: {t['surface2']}; border-radius: 12px;")
        self._actualizar_externo()
        self._render()

    def contexto(self, trama: Trama, evento=None):
        """Actualiza el contexto con la trama más reciente y la alarma abierta (si hay); dispara la consulta
        automática una vez por alarma."""
        v = self.filas.valores
        self._ctx = ContextoAlarma.de_trama(trama, evento)
        if trama.dir.enclavada and evento is not None:
            poner_prop(self.chip_sev, "chipSev", {1: "leve", 2: "inter", 3: "severa"}.get(trama.dir.sev, "inter"))
            self.chip_sev.setText(trama.dir.nombre_sev if trama.dir.sev else "ALARMA")
            v["inicio"].setText(time.strftime("%H:%M:%S", time.localtime(evento.t_inicio)))
            v["tiempo"].setText(f"{evento.duracion(trama.t):.0f} s")
            v["ml"].setText(f"{trama.dir.ml:.2f} pp")
            self._auto(evento)
        else:
            poner_prop(self.chip_sev, "chipSev", "sano")
            self.chip_sev.setText("SIN ALARMA")
            for k in ("inicio", "tiempo", "ml"):
                v[k].setText("—")
        v["i1"].setText(f"{trama.i1:.3f} A pico")
        v["i"].setText(f"{trama.ia:.2f} · {trama.ib:.2f} · {trama.ic:.2f} A")
        v["decision"].setText(trama.decision)
        self.btn_recomendar.setEnabled(self.servicio is not None and self.servicio.listo
                                       and self._ctx.severidad is not None)

    def _auto(self, evento):
        clave = round(evento.t_inicio, 3)
        if clave in self._consultadas or self._ctx is None or self._ctx.severidad is None:
            return
        self._consultadas.add(clave)
        if not self.chk_auto.isChecked() or self.servicio is None or not self.servicio.listo:
            return
        if self._provocada():
            bitacora.LOG.info("Asistente: alarma provocada por inyección o captura; sin consulta automática")
            return
        self.servicio.preguntar("", self._ctx, alarma=True)
