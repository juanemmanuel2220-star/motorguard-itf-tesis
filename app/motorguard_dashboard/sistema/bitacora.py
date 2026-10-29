"""
Registro de la aplicación (app.log, con rotación) y captura de toda excepción no atendida.

Una excepción en un slot de Qt, en un hilo de Python o un mensaje crítico de Qt queda en app.log con su
traza y se avisa a la interfaz (señal `notificador.error`); la aplicación sigue funcionando.
"""

import logging
import logging.handlers
import os
import platform
import sys
import threading
from typing import Optional

from PySide6.QtCore import QObject, QtMsgType, Signal, qInstallMessageHandler

LOG = logging.getLogger("motorguard")
LOG.addHandler(logging.NullHandler())   # sin configurar (p. ej. en pruebas) no imprime nada
MAX_BYTES = 5 * 1024 * 1024
RESPALDOS = 3

# Avisos de Qt que no indican un problema de la app (ruido de la plataforma)
_RUIDO_QT = ("propagateSizeHints", "This plugin does not support", "QSocketNotifier")


class Notificador(QObject):
    error = Signal(str)   # resumen de una línea (se emite desde cualquier hilo; Qt lo entrega en el principal)


notificador = Notificador()
_ruta_actual: Optional[str] = None


def ruta_log() -> Optional[str]:
    return _ruta_actual


def configurar(dir_logs: str, nivel=logging.INFO, a_consola: bool = True) -> str:
    """Prepara app.log en `dir_logs` e instala los capturadores de excepciones. Devuelve la ruta."""
    global _ruta_actual
    os.makedirs(dir_logs, exist_ok=True)
    ruta = os.path.join(dir_logs, "app.log")
    for h in list(LOG.handlers):
        LOG.removeHandler(h)
        h.close()
    LOG.addHandler(logging.NullHandler())
    archivo = logging.handlers.RotatingFileHandler(ruta, maxBytes=MAX_BYTES, backupCount=RESPALDOS, encoding="utf-8")
    archivo.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s [%(threadName)s] %(message)s"))
    LOG.addHandler(archivo)
    if a_consola:
        consola = logging.StreamHandler(sys.stderr)
        consola.setLevel(logging.WARNING)
        consola.setFormatter(logging.Formatter("MotorGuard-ITF %(levelname)s: %(message)s"))
        LOG.addHandler(consola)
    LOG.setLevel(nivel)
    LOG.propagate = False
    _ruta_actual = ruta

    sys.excepthook = _excepcion_python
    threading.excepthook = _excepcion_hilo
    qInstallMessageHandler(_mensaje_qt)
    return ruta


def restablecer():
    """Deja el registro sin archivo y los capturadores originales (lo usan las pruebas)."""
    global _ruta_actual
    for h in list(LOG.handlers):
        LOG.removeHandler(h)
        h.close()
    LOG.addHandler(logging.NullHandler())
    sys.excepthook = sys.__excepthook__
    threading.excepthook = threading.__excepthook__
    qInstallMessageHandler(None)
    _ruta_actual = None


def registrar_arranque(version: str, modo: str):
    try:
        from PySide6 import __version__ as pyside
        from PySide6.QtCore import qVersion
        qt = qVersion()
    except Exception:  # pragma: no cover - solo informativo
        pyside = qt = "?"
    LOG.info("Inicio MotorGuard-ITF %s | modo: %s | Python %s | PySide6 %s / Qt %s | %s",
             version, modo, platform.python_version(), pyside, qt, platform.platform())


def _avisar(resumen: str):
    try:
        notificador.error.emit(resumen)
    except RuntimeError:
        pass  # el notificador ya no existe (cierre de la app)


def _excepcion_python(tipo, valor, traza):
    if issubclass(tipo, KeyboardInterrupt):
        sys.__excepthook__(tipo, valor, traza)
        return
    LOG.error("Excepción no atendida", exc_info=(tipo, valor, traza))
    _avisar(f"{tipo.__name__}: {valor}")


def _excepcion_hilo(args):
    if args.exc_type is SystemExit:
        return
    nombre = args.thread.name if args.thread else "?"
    LOG.error("Excepción no atendida en el hilo %s", nombre,
              exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    _avisar(f"{args.exc_type.__name__} en el hilo {nombre}: {args.exc_value}")


def _mensaje_qt(tipo, contexto, mensaje):
    if any(r in mensaje for r in _RUIDO_QT):
        return
    if tipo in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
        LOG.error("Qt: %s", mensaje)
        _avisar(f"Qt: {mensaje}")
    elif tipo == QtMsgType.QtWarningMsg:
        LOG.warning("Qt: %s", mensaje)
    else:
        LOG.debug("Qt: %s", mensaje)
