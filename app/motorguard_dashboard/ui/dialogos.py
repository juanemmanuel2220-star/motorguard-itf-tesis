"""
Diálogos de Ajustes y Acerca de.
"""

import os
import platform
from typing import Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QVBoxLayout

from motorguard_dashboard import FIRMWARE_COMPATIBLE, __version__
from motorguard_dashboard.sistema import bitacora, rutas
from motorguard_dashboard.ui.componentes import boton, etiqueta, separador
from motorguard_dashboard.ui.tema import logo_pixmap


def abrir_carpeta(ruta: str):
    os.makedirs(ruta, exist_ok=True)
    QDesktopServices.openUrl(QUrl.fromLocalFile(ruta))


class DialogoAjustes(QDialog):
    def __init__(self, parent=None, conf=None):
        super().__init__(parent)
        self._conf = conf
        self.setWindowTitle("Ajustes")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 18)
        lay.setSpacing(12)
        lay.addWidget(etiqueta("Ajustes", "tituloTarjeta"))

        lay.addWidget(etiqueta("Carpeta de registros (CSV de alarmas y pulsos, log crudo del puerto)", "etiqueta"))
        fila = QHBoxLayout()
        self.lbl_registros = etiqueta(rutas.dir_registros(self._conf), "mono")
        self.lbl_registros.setWordWrap(True)
        self.lbl_registros.setTextInteractionFlags(Qt.TextSelectableByMouse)
        fila.addWidget(self.lbl_registros, 1)
        b_cambiar = boton("Cambiar…", "contorno")
        b_cambiar.clicked.connect(self._cambiar_registros)
        b_abrir = boton("Abrir", "tonal")
        b_abrir.clicked.connect(lambda: abrir_carpeta(rutas.dir_registros(self._conf)))
        fila.addWidget(b_cambiar)
        fila.addWidget(b_abrir)
        lay.addLayout(fila)
        lay.addWidget(etiqueta("El cambio se aplica a la próxima sesión (la actual sigue escribiendo donde empezó).",
                               "secundario"))
        lay.addWidget(separador())

        lay.addWidget(etiqueta("Registro de la aplicación (errores y eventos internos)", "etiqueta"))
        fila2 = QHBoxLayout()
        ruta_log = bitacora.ruta_log() or os.path.join(rutas.dir_logs_app(), "app.log")
        lbl_log = etiqueta(ruta_log, "mono")
        lbl_log.setWordWrap(True)
        lbl_log.setTextInteractionFlags(Qt.TextSelectableByMouse)
        fila2.addWidget(lbl_log, 1)
        b_log = boton("Abrir carpeta", "tonal")
        b_log.clicked.connect(lambda: abrir_carpeta(os.path.dirname(ruta_log)))
        fila2.addWidget(b_log)
        lay.addLayout(fila2)

        cerrar = QHBoxLayout()
        cerrar.addStretch()
        b = boton("Cerrar")
        b.clicked.connect(self.accept)
        cerrar.addWidget(b)
        lay.addLayout(cerrar)

    def _cambiar_registros(self):
        ruta = QFileDialog.getExistingDirectory(self, "Carpeta de registros", rutas.dir_registros(self._conf))
        if ruta:
            rutas.poner_dir_registros(ruta, self._conf)
            self.lbl_registros.setText(rutas.dir_registros(self._conf))
            bitacora.LOG.info("Carpeta de registros cambiada a %s", ruta)


def _version_de(modulo: str, paquete: Optional[str] = None) -> str:
    try:
        m = __import__(modulo)
    except Exception:
        return "no disponible"
    v = getattr(m, "__version__", None)
    if v:
        return str(v)
    try:                                         # p. ej. keyring no tiene __version__
        from importlib.metadata import version
        return version(paquete or modulo)
    except Exception:
        return "?"


class DialogoAcercaDe(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Acerca de MotorGuard-ITF")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 18)
        lay.setSpacing(10)
        cab = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(logo_pixmap(84))
        cab.addWidget(logo, 0, Qt.AlignTop)
        tit = QVBoxLayout()
        tit.setSpacing(2)
        tit.addWidget(etiqueta("MotorGuard-ITF", "titulo"))
        tit.addWidget(etiqueta(f"Versión {__version__} · firmware compatible {FIRMWARE_COMPATIBLE}", "secundario"))
        desc = etiqueta("Monitoreo del detector embebido de fallas entre espiras (MCSA), inyección de fallas "
                        "con bloqueos de seguridad y asistente de mantenimiento.", "secundario")
        desc.setWordWrap(True)
        # Con el ajuste de línea, el diálogo calculaba su alto sin las líneas extra y la descripción se encimaba en la
        # versión (se notó al quitar la línea de autor, que lo hacía más alto): se reserva el alto de 3 líneas
        desc.setMinimumHeight(3 * desc.fontMetrics().lineSpacing() + 4)
        tit.addWidget(desc)
        cab.addLayout(tit, 1)
        lay.addLayout(cab)
        lay.addWidget(separador())
        lay.addWidget(etiqueta("Licencia: GPL-3.0-or-later. Software libre, sin garantía.", "secundario"))
        lay.addWidget(separador())
        lay.addWidget(etiqueta("Componentes de terceros", "etiqueta"))
        from PySide6 import __version__ as pyside
        from PySide6.QtCore import qVersion
        terceros = [
            (f"PySide6 {pyside} / Qt {qVersion()}", "LGPL-3.0"),
            (f"pyqtgraph {_version_de('pyqtgraph')}", "MIT"),
            (f"NumPy {_version_de('numpy')}", "BSD-3-Clause"),
            (f"pySerial {_version_de('serial')}", "BSD-3-Clause"),
            (f"pypdf {_version_de('pypdf')}", "BSD-3-Clause"),
            (f"keyring {_version_de('keyring')}", "MIT"),
            ("Fuentes Figtree y JetBrains Mono", "SIL OFL 1.1"),
            (f"Python {platform.python_version()}", "PSF"),
        ]
        # Asistente: el motor y los modelos se descargan con «Preparar asistente»; los logotipos solo identifican al
        # modelo que responde (las marcas son de sus dueños)
        from motorguard_dashboard.rag import catalogo
        terceros += [
            (f"llama.cpp {catalogo.LLAMA_BUILD} (se descarga)", "MIT"),
            ("Modelos Qwen3.5 y Qwen3-Embedding (se descargan)", "Apache-2.0"),
            ("Logotipos de Simple Icons 16.33.0", "CC0-1.0"),
        ]
        for nombre, lic in terceros:
            f = QHBoxLayout()
            f.addWidget(QLabel(nombre))
            f.addStretch()
            f.addWidget(etiqueta(lic, "secundario"))
            lay.addLayout(f)
        cerrar = QHBoxLayout()
        cerrar.addStretch()
        b = boton("Cerrar")
        b.clicked.connect(self.accept)
        cerrar.addWidget(b)
        lay.addLayout(cerrar)
