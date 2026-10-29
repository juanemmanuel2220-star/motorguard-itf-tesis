"""
Claves de API de los proveedores externos del asistente, en el llavero del sistema (Secret Service en
Linux, Credential Manager en Windows) mediante `keyring`.

Nunca se guardan en QSettings, en registros ni en archivos de la app. Si no hay llavero disponible, la clave
se conserva solo en memoria durante la sesión (hay que volver a escribirla al reabrir la app).
"""

from typing import Dict, Optional
from urllib.parse import urlparse

SERVICIO = "MotorGuard-ITF"
_memoria: Dict[str, str] = {}


def _cuenta(url: str) -> str:
    return urlparse(url).netloc or url


def _llavero():
    try:
        import keyring
        from keyring.backends import fail
        k = keyring.get_keyring()
        if isinstance(k, fail.Keyring):
            return None
        return keyring
    except Exception:                                            # noqa: BLE001 (sin llavero en este sistema)
        return None


def hay_llavero() -> bool:
    return _llavero() is not None


def guardar(url: str, clave: str) -> bool:
    """Guarda la clave; devuelve True si quedó en el llavero (False: solo en memoria)."""
    _memoria[_cuenta(url)] = clave
    k = _llavero()
    if k is None:
        return False
    try:
        k.set_password(SERVICIO, _cuenta(url), clave)
        return True
    except Exception:                                            # noqa: BLE001
        return False


def leer(url: str) -> Optional[str]:
    if _cuenta(url) in _memoria:
        return _memoria[_cuenta(url)]
    k = _llavero()
    if k is None:
        return None
    try:
        return k.get_password(SERVICIO, _cuenta(url))
    except Exception:                                            # noqa: BLE001
        return None


def borrar(url: str):
    _memoria.pop(_cuenta(url), None)
    k = _llavero()
    if k is not None:
        try:
            k.delete_password(SERVICIO, _cuenta(url))
        except Exception:                                        # noqa: BLE001 (no estaba)
            pass
