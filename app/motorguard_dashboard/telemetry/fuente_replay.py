"""
Reproducción de un log real (*_serial.log) con el mismo ritmo con el que se grabó.

Es el modo sin Arduino de la app: no genera datos, entrega las líneas medidas en el banco
con su marca de tiempo original (opcionalmente acelerado).
"""

import os
import re
import time
from typing import Callable, Iterator, Optional, Tuple

from PySide6.QtCore import QThread, Signal

from motorguard_dashboard.telemetry.consultas import AcumuladorRespuestas
from motorguard_dashboard.telemetry.parser import Linea, parsear_linea, separar_marca_tiempo

# Marca de tiempo en cualquier línea, también en las de datos de un volcado ("1791.123 2255,1641,1853")
_RE_MARCA_GENERAL = re.compile(r"^\s*(\d+(?:\.\d+)?)s?\s+(.*)$")


def lineas_con_ritmo(
    ruta: str,
    velocidad: float = 1.0,
    dormir: Callable[[float], None] = time.sleep,
    detener: Callable[[], bool] = lambda: False,
) -> Iterator[Tuple[str, Optional[Linea]]]:
    """Genera (línea, objeto parseado) esperando entre líneas lo que indican sus marcas de tiempo."""
    t_prev: Optional[float] = None
    with open(ruta, encoding="utf-8", errors="ignore") as f:
        for linea in f:
            if detener():
                return
            linea = linea.rstrip("\n")
            t, _ = separar_marca_tiempo(linea.strip())
            if t is not None:
                if t_prev is not None and t > t_prev:
                    espera = (t - t_prev) / velocidad
                    # Dormir en tramos cortos para poder detener la reproducción a mitad de una espera
                    while espera > 0 and not detener():
                        tramo = min(espera, 0.1)
                        dormir(tramo)
                        espera -= tramo
                    if detener():
                        return
                t_prev = t
            yield linea, parsear_linea(linea)


class FuenteReplay(QThread):
    """Hilo que reproduce un log y emite las líneas parseadas, igual que la fuente serie."""
    sig_dato = Signal(object)          # Trama | EventoSSR | MensajeFirmware (con t del archivo)
    sig_descartada = Signal(str)       # trama [MCSA] que no se pudo leer completa
    sig_estado = Signal(bool, str)     # (activa, mensaje)
    sig_respuesta = Signal(object)     # respuestas a consultas que hayan quedado grabadas en el log

    def __init__(self, ruta: str, velocidad: float = 1.0):
        super().__init__()
        self.ruta = ruta
        self.velocidad = velocidad
        self._detener = False

    def detener(self):
        self._detener = True
        self.wait(2000)

    def run(self):
        nombre = os.path.basename(self.ruta)
        self.sig_estado.emit(True, f"REPRODUCCIÓN ×{self.velocidad:g}: {nombre}")
        acum = AcumuladorRespuestas()
        for linea, obj in lineas_con_ritmo(self.ruta, self.velocidad, detener=lambda: self._detener):
            m = _RE_MARCA_GENERAL.match(linea)
            t, texto = (float(m.group(1)), m.group(2)) if m else (None, linea)
            consumida, resp = acum.alimentar(texto, t)
            if resp is not None:
                self.sig_respuesta.emit(resp)
            if consumida:
                continue
            if obj is not None:
                self.sig_dato.emit(obj)
            elif "[MCSA]" in linea:
                self.sig_descartada.emit(linea)
        self.sig_estado.emit(False, f"Reproducción terminada: {nombre}")
