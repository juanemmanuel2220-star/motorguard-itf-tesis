"""
Registro crudo de lo recibido y enviado por el puerto serie, con rotación para sesiones largas.

Cada línea lleva la marca "<t> " como los scripts de validación (reproducible con --replay).
Se abre un archivo nuevo cada `max_s` segundos o cuando el actual pasa de `max_bytes`:
  sesion_<sello>_serial.log, sesion_<sello>_p002_serial.log, sesion_<sello>_p003_serial.log, ...
"""

import os
import time
from typing import Optional

MAX_BYTES = 100 * 1024 * 1024
MAX_S = 24 * 3600


class RegistroCrudo:
    def __init__(self, ruta: str, max_bytes: int = MAX_BYTES, max_s: float = MAX_S,
                 reloj=time.monotonic):
        self.ruta_base = ruta
        self.max_bytes = max_bytes
        self.max_s = max_s
        self._reloj = reloj
        self.parte = 0
        self.ruta: Optional[str] = None
        self._f = None
        self._t_inicio = 0.0
        self._bytes = 0

    def _ruta_parte(self, n: int) -> str:
        if n == 1:
            return self.ruta_base
        base, sufijo = self.ruta_base, "_serial.log"
        if base.endswith(sufijo):
            return f"{base[:-len(sufijo)]}_p{n:03d}{sufijo}"
        raiz, ext = os.path.splitext(base)
        return f"{raiz}_p{n:03d}{ext}"

    def _abrir_siguiente(self):
        self.cerrar()
        self.parte += 1
        self.ruta = self._ruta_parte(self.parte)
        os.makedirs(os.path.dirname(self.ruta) or ".", exist_ok=True)
        self._f = open(self.ruta, "a", buffering=1, encoding="utf-8")
        self._bytes = os.path.getsize(self.ruta)
        self._t_inicio = self._reloj()

    def escribir(self, t: float, texto: str):
        if self._f is None or self._bytes >= self.max_bytes or self._reloj() - self._t_inicio >= self.max_s:
            self._abrir_siguiente()
        linea = f"{t:.3f} {texto}\n"
        self._f.write(linea)
        self._bytes += len(linea.encode("utf-8"))

    def cerrar(self):
        if self._f is not None:
            self._f.close()
            self._f = None
