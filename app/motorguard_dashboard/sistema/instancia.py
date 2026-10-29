"""
Una sola ventana a la vez usando el Arduino (dos ventanas se pelearían el puerto y el SSR).
Las reproducciones de logs no toman el bloqueo y pueden abrirse varias.
"""

import os
from typing import Optional, Tuple

from PySide6.QtCore import QLockFile


class InstanciaUnica:
    def __init__(self, ruta_bloqueo: str):
        os.makedirs(os.path.dirname(ruta_bloqueo), exist_ok=True)
        self._lock = QLockFile(ruta_bloqueo)
        self._lock.setStaleLockTime(0)   # solo cuenta como abandonado si el proceso dueño ya no existe

    def tomar(self) -> Tuple[bool, Optional[int]]:
        """(tomado, pid del otro proceso si no se pudo)."""
        if self._lock.tryLock(200):
            return True, None
        info = self._lock.getLockInfo()   # PySide6: (pid, equipo, app); C++: (ok, pid, equipo, app)
        pid = info[1] if len(info) == 4 else (info[0] if info else None)
        return False, (int(pid) if isinstance(pid, int) and pid > 0 else None)

    def soltar(self):
        if self._lock.isLocked():
            self._lock.unlock()
