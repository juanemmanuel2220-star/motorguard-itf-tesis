"""
Conversación del asistente al estilo de un chat (aprobado por el autor el 13-oct):

- la pregunta del usuario, en una burbuja a la derecha;
- la respuesta, a la izquierda y sin burbuja: citas como enlaces con el documento y la página, líneas sin cita en
  gris («sin fuente»), citas inexistentes tachadas, la lista de fuentes y un pie gris (modelo · tiempo · % citado);
- una alarma confirmada, como tarjeta centrada con el color de su severidad;
- mientras genera, el texto aparece en vivo;
- con la conversación vacía se muestra una explicación y las sugerencias.

Cada mensaje es un widget propio (el texto enriquecido de Qt no admite bordes redondeados). Al llegar texto nuevo
solo se actualiza el último mensaje, y la vista baja al final salvo que el usuario haya subido a leer.
"""

import html
import re
import time
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from motorguard_dashboard.rag import catalogo
from motorguard_dashboard.rag.asistente import Respuesta, describir_fuente
from motorguard_dashboard.ui import marcas
from motorguard_dashboard.ui.componentes import boton, etiqueta, poner_prop

# Nombre corto de cada documento para las citas en línea
CORTOS = {"abb": "ABB", "nasa_rcm": "NASA RCM", "femp_om": "FEMP O&M", "usbr_3_1": "USBR 3-1", "usbr_3_4": "USBR 3-4",
          "usbr_4_1b": "USBR 4-1B", "ruzimov2025": "Ruzimov 2025", "chen2023": "Chen 2023", "tesis": "Tesis",
          "banco": "Banco"}
_RE_CITA = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)*)\]")
_RE_SEV = re.compile(r"\b(LEVE|INTER|SEVERA)\b")
_RE_ML = re.compile(r"\(ML\):\s*([0-9.]+)")
ANCHO_BURBUJA = 0.75          # fracción del ancho visible


def cita_corta(r) -> str:
    """'ABB p.100', 'Tesis §6'…: el documento y la página (del PDF) o la sección."""
    f = r.fragmento
    nombre = CORTOS.get(f.doc) or next((d.titulo for d in catalogo.DOCUMENTOS if d.clave == f.doc), f.doc)
    return f"{nombre} {f.etiqueta}" if f.etiqueta.startswith("§") else f"{nombre} p.{f.pag}"


def html_respuesta(r: Respuesta, t: dict, n_entrada: int) -> str:
    """Respuesta en HTML para un QLabel: citas como enlaces 'cita:<entrada>-<n>' con el documento y la página."""
    partes = []
    if r.error:
        partes.append(f"<p style='color:{t['error']}'>No se pudo responder: {html.escape(r.error)}</p>")
    if r.aviso:
        partes.append(f"<p style='color:{t['leveFg']}'>{html.escape(r.aviso)}</p>")
    for linea in r.lineas:
        txt = html.escape(linea.texto)

        def enlazar(m):
            out = []
            for n in (int(x) for x in re.split(r"[,;]", m.group(1)) if x.strip()):
                if 1 <= n <= len(r.fuentes):
                    out.append(f"<a href='cita:{n_entrada}-{n}' style='color:{t['primary']};text-decoration:none'>"
                               f"<span style='background:{t['primaryC']};color:{t['onPrimaryC']}'>"
                               f"&nbsp;{html.escape(cita_corta(r.fuentes[n - 1]))}&nbsp;</span></a>")
                else:
                    out.append(f"<span style='color:{t['error']}' title='cita inexistente'><s>[{n}]</s></span>")
            return " ".join(out)
        txt = _RE_CITA.sub(enlazar, txt)
        if linea.es_afirmacion and not linea.citas:
            txt = f"<span style='color:{t['muted']}'>{txt} <i>(sin fuente)</i></span>"
        elif linea.cifras_sin_soporte:
            cf = html.escape(", ".join(linea.cifras_sin_soporte))
            txt += (f" <span style='color:{t['leveFg']}' title='cifra no hallada en el fragmento citado'>"
                    f"<i>(verificar cifra: {cf})</i></span>")
        partes.append(f"<p style='margin:6px 0'>{txt}</p>")
    if r.abstencion or (not r.lineas and r.texto and not r.error):
        partes.append(f"<p>{html.escape(r.texto)}</p>")
    if r.fuentes and not r.abstencion:
        filas = "<br>".join(f"<a href='cita:{n_entrada}-{k}' style='color:{t['primary']};text-decoration:none'>[{k}]</a>"
                            f" {html.escape(describir_fuente(f))}" for k, f in enumerate(r.fuentes, 1))
        partes.append(f"<p style='color:{t['muted']};font-size:small;margin-top:10px'>Fuentes:<br>{filas}</p>")
    return "".join(partes)


def nombre_respuesta(modelo: str) -> str:
    """'claude-sonnet-5-5 (externo)' -> 'Claude Sonnet 5.5 (externo)'."""
    nombre, sep, resto = modelo.partition(" (")
    return marcas.nombre_modelo(nombre) + (sep + resto if sep else "")


def pie_respuesta(r: Respuesta) -> str:
    pie = []
    if r.modelo:
        pie.append(nombre_respuesta(r.modelo))
    if r.t_total:
        pie.append(f"{r.t_total:.0f} s")
    if r.fraccion_citada is not None:
        pie.append(f"{100 * r.fraccion_citada:.0f} % de líneas con cita")
    if r.cancelada:
        pie.append("cancelada")
    return " · ".join(pie)


class _Mensaje(QWidget):
    """Un turno: la pregunta (burbuja) o la tarjeta de alarma, y la respuesta (en vivo o terminada)."""

    def __init__(self, conv: "Conversacion", k: int):
        super().__init__()
        self.conv, self.k = conv, k
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 6, 0, 6)
        self.lay.setSpacing(8)
        self.cabeza: Optional[QWidget] = None
        self.burbuja: Optional[QFrame] = None
        self.texto = QLabel()
        self.texto.setWordWrap(True)
        self.texto.setTextFormat(Qt.RichText)
        self.texto.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.texto.setOpenExternalLinks(False)
        self.texto.linkActivated.connect(lambda url: conv.al_citar(QUrl(url)))
        self.texto.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.pie = etiqueta("", "pieRespuesta")
        self.pie.setVisible(False)
        self._clave = None

    def poner(self, e: dict, t: dict):
        if self.cabeza is None:
            self._cabeza(e, t)
            self.lay.addWidget(self.texto)
            self.lay.addWidget(self.pie)
        r = e["r"]
        clave = (id(r), len(e["texto"]), id(t))
        if clave == self._clave:
            return
        self._clave = clave
        if r is None:
            vivo = html.escape(e["texto"]).replace("\n", "<br>")
            self.texto.setText(vivo + f" <span style='color:{t['primary']}'>▍</span>" if vivo else
                               f"<i style='color:{t['muted']}'>buscando en los documentos y generando…</i>")
            self.pie.setVisible(False)
        else:
            self.texto.setText(html_respuesta(r, t, self.k))
            pie = pie_respuesta(r)
            slug = marcas.marca(r.modelo)
            logo = (f"<img src='{marcas.ruta_png(slug, marcas.color(slug, t), 14)}' width='14' height='14' "
                    f"style='vertical-align: middle'>&nbsp;" if slug else "")
            self.pie.setTextFormat(Qt.RichText)
            self.pie.setText(logo + html.escape(pie))
            self.pie.setVisible(bool(pie))
            if e["alarma"] and r.contexto:
                self._completar_alarma(r.contexto)

    def _cabeza(self, e: dict, t: dict):
        fila = QHBoxLayout()
        fila.setContentsMargins(0, 0, 0, 0)
        if e["alarma"]:
            m = _RE_SEV.search(e["pregunta"])
            sev = m.group(1) if m else ""
            self._sev = sev
            self.cabeza = etiqueta(f"⚠ Alarma {sev} confirmada · {e.get('hora', time.strftime('%H:%M:%S'))}".replace("  ", " "))
            self.cabeza.setProperty("chipSev", {"LEVE": "leve", "INTER": "inter", "SEVERA": "severa"}.get(sev, "inter"))
            self.cabeza.setAlignment(Qt.AlignCenter)
            fila.addStretch()
            fila.addWidget(self.cabeza)
            fila.addStretch()
        else:
            self.burbuja = QFrame()
            self.burbuja.setProperty("rol", "burbuja")
            lb = QVBoxLayout(self.burbuja)
            lb.setContentsMargins(16, 10, 16, 10)
            q = QLabel(html.escape(e["pregunta"]))
            q.setWordWrap(True)
            self._q = q
            q.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lb.addWidget(q)
            self.cabeza = self.burbuja
            fila.addStretch()
            fila.addWidget(self.burbuja)
            self.ajustar_ancho(self.conv.viewport().width())
        self.lay.addLayout(fila)

    def _completar_alarma(self, contexto: str):
        m = _RE_ML.search(contexto)
        if m and "ML" not in self.cabeza.text():
            self.cabeza.setText(self.cabeza.text() + f" · ML {float(m.group(1)):.2f} pp")

    def ajustar_ancho(self, ancho: int):
        """La burbuja toma el ancho de su texto, hasta ANCHO_BURBUJA del área visible (después, varias líneas)."""
        if self.burbuja is not None:
            tope = max(240, int(ancho * ANCHO_BURBUJA))
            texto = self._q.fontMetrics().horizontalAdvance(self._q.text()) + 32 + 6   # márgenes de la burbuja
            self.burbuja.setFixedWidth(min(texto, tope))


class Conversacion(QScrollArea):
    """Lista de mensajes con desplazamiento. mostrar() sincroniza con las entradas de la sección Asistente."""

    def __init__(self, al_citar: Callable[[QUrl], None], sugerencias: List[QWidget], parent=None):
        super().__init__(parent)
        self.setObjectName("conversacion")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.al_citar = al_citar
        cont = QWidget()
        self.lay = QVBoxLayout(cont)
        self.lay.setContentsMargins(8, 8, 16, 8)
        self.lay.setSpacing(10)
        # Estado vacío: explicación y sugerencias
        self.vacio = QWidget()
        lv = QVBoxLayout(self.vacio)
        lv.setContentsMargins(0, 40, 0, 0)
        lv.setSpacing(14)
        self.lbl_vacio = etiqueta("", "secundario")
        self.lbl_vacio.setWordWrap(True)
        self.lbl_vacio.setAlignment(Qt.AlignCenter)
        lv.addWidget(self.lbl_vacio)
        for b in sugerencias:
            fila = QHBoxLayout()
            fila.addStretch()
            fila.addWidget(b)
            fila.addStretch()
            lv.addLayout(fila)
        self.lay.addWidget(self.vacio)
        self.lay.addStretch()
        self.setWidget(cont)
        self.setMinimumHeight(380)
        self._mensajes: List[_Mensaje] = []
        self._t_id = None

    def _al_final(self) -> bool:
        sb = self.verticalScrollBar()
        return sb.value() >= sb.maximum() - 40

    def mostrar(self, entradas: List[dict], t: dict, listo: bool):
        if id(t) != self._t_id:                        # cambio de tema: se rehacen los mensajes
            self._t_id = id(t)
            for m in self._mensajes:
                m.setParent(None)
                m.deleteLater()
            self._mensajes = []
        self.vacio.setVisible(not entradas)
        self.lbl_vacio.setText("Pregunte sobre inspección o mantenimiento del motor. Cada recomendación lleva su "
                               "fuente (documento y página); lo que ningún documento respalda se marca «sin fuente»."
                               + ("" if listo else "\n\nEl asistente todavía no está listo."))
        bajar = self._al_final() or len(entradas) > len(self._mensajes)
        while len(self._mensajes) < len(entradas):
            m = _Mensaje(self, len(self._mensajes))
            self.lay.insertWidget(self.lay.count() - 1, m)
            self._mensajes.append(m)
        for m, e in zip(self._mensajes, entradas):
            m.poner(e, t)
        if bajar:
            QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(self.verticalScrollBar().maximum()))

    def html(self) -> str:
        """Texto de todas las respuestas (para las pruebas)."""
        return "".join(m.texto.text() for m in self._mensajes)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        for m in self._mensajes:
            m.ajustar_ancho(self.viewport().width())
