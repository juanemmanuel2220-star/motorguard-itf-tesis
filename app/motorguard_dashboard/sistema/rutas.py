"""
Rutas de la aplicación, válidas en Linux y en Windows.

- Datos internos (app.log, bloqueo de instancia): carpeta de datos del usuario + "MotorGuard-ITF"
  (Linux: ~/.local/share/MotorGuard-ITF; Windows: %LOCALAPPDATA%\\MotorGuard-ITF).
- Registros de las sesiones (CSV de alarmas y pulsos, log crudo): configurable en Ajustes; por defecto
  Documentos/MotorGuard-ITF/registros.
- Carpeta inicial para elegir un log a reproducir: la última usada.
- Datos de la sección Adquisición (datasets nuevos): configurable en esa sección; por defecto
  Documentos/MotorGuard-ITF/adquisicion. Nunca una carpeta de datos de la tesis (adquisicion/formato.py).
- Asistente: motor (llama/), modelos (modelos/) e índice (indice/) en la carpeta de datos internos;
  documentos en una carpeta configurable (por defecto <datos internos>/asistente/documentos).
"""

import os
from typing import Optional

from PySide6.QtCore import QSettings, QStandardPaths

ORG, APP = "Tesis-ITF", "MotorGuard-ITF"
CLAVE_REGISTROS = "registros/carpeta"
CLAVE_REPRODUCCION = "reproduccion/ultima_carpeta"
CLAVE_ADQUISICION = "adquisicion/carpeta"
CLAVE_DOCUMENTOS = "asistente/documentos"


def ajustes() -> QSettings:
    return QSettings(ORG, APP)


def _ubicacion(tipo) -> str:
    ruta = QStandardPaths.writableLocation(tipo)
    return ruta or os.path.expanduser("~")


def dir_datos_app() -> str:
    """Carpeta de datos internos; no depende del nombre de la QApplication."""
    return os.path.join(_ubicacion(QStandardPaths.GenericDataLocation), APP)


def dir_logs_app() -> str:
    return os.path.join(dir_datos_app(), "logs")


def dir_registros_defecto() -> str:
    return os.path.join(_ubicacion(QStandardPaths.DocumentsLocation), APP, "registros")


def dir_registros(conf: Optional[QSettings] = None) -> str:
    conf = conf or ajustes()
    return str(conf.value(CLAVE_REGISTROS, dir_registros_defecto()))


def poner_dir_registros(ruta: str, conf: Optional[QSettings] = None):
    (conf or ajustes()).setValue(CLAVE_REGISTROS, os.path.abspath(os.path.expanduser(ruta)))


def dir_adquisicion_defecto() -> str:
    return os.path.join(_ubicacion(QStandardPaths.DocumentsLocation), APP, "adquisicion")


def dir_adquisicion(conf: Optional[QSettings] = None) -> str:
    conf = conf or ajustes()
    return str(conf.value(CLAVE_ADQUISICION, dir_adquisicion_defecto()))


def poner_dir_adquisicion(ruta: str, conf: Optional[QSettings] = None):
    (conf or ajustes()).setValue(CLAVE_ADQUISICION, os.path.abspath(os.path.expanduser(ruta)))


def dir_reproduccion(conf: Optional[QSettings] = None) -> str:
    conf = conf or ajustes()
    previa = conf.value(CLAVE_REPRODUCCION, "")
    if previa and os.path.isdir(str(previa)):
        return str(previa)
    return _ubicacion(QStandardPaths.HomeLocation)


def recordar_dir_reproduccion(ruta_archivo: str, conf: Optional[QSettings] = None):
    (conf or ajustes()).setValue(CLAVE_REPRODUCCION, os.path.dirname(os.path.abspath(ruta_archivo)))


def dir_asistente() -> str:
    return os.path.join(dir_datos_app(), "asistente")


def dir_documentos(conf: Optional[QSettings] = None) -> str:
    conf = conf or ajustes()
    return str(conf.value(CLAVE_DOCUMENTOS, os.path.join(dir_asistente(), "documentos")))


def poner_dir_documentos(ruta: str, conf: Optional[QSettings] = None):
    (conf or ajustes()).setValue(CLAVE_DOCUMENTOS, os.path.abspath(os.path.expanduser(ruta)))
