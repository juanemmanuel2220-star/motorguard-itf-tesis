"""
Descarga de los recursos del catálogo con verificación SHA-256 (sin dependencias: urllib).

- Se descarga a "<archivo>.part" y se reanuda con Range si se interrumpe; al terminar se verifica el
  SHA-256 y se renombra. Si el SHA-256 no coincide, el archivo se borra (modelos y runtime) o se conserva
  marcado como "versión distinta" (documentos, cuya fuente oficial puede actualizarlos).
- El runtime de llama.cpp se extrae a <dir>/llama/ conservando solo llama-server y sus bibliotecas.
"""

import hashlib
import os
import shutil
import tarfile
import time
import urllib.error
import urllib.request
from typing import Callable, Optional

from motorguard_dashboard.rag.catalogo import Recurso

AGENTE = "MotorGuard-ITF/1.0 (asistente de mantenimiento; tesis UASLP)"
BLOQUE = 1 << 20


REINTENTOS = 8
VEL_MIN = 300_000           # B/s; por debajo de esto durante VENTANA_S se reconecta y se reanuda
VENTANA_S = 20.0


class ErrorDescarga(Exception):
    pass


class _Lenta(Exception):
    pass


def sha256_archivo(ruta: str) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as fh:
        for b in iter(lambda: fh.read(BLOQUE), b""):
            h.update(b)
    return h.hexdigest()


def descargar(rec: Recurso, carpeta: str, progreso: Optional[Callable[[int, Optional[int]], None]] = None,
              cancelado: Callable[[], bool] = lambda: False, estricto: bool = True, url: str = "") -> str:
    """Descarga rec a carpeta/rec.archivo y devuelve su SHA-256. Si ya existe con el SHA-256 correcto, no hace nada.
    estricto=False (documentos): un SHA-256 distinto no es error (lo decide quien llama)."""
    url = url or rec.url
    if not url:
        raise ErrorDescarga(f"{rec.titulo or rec.clave}: sin URL de descarga")
    os.makedirs(carpeta, exist_ok=True)
    final = os.path.join(carpeta, rec.archivo)
    if os.path.exists(final) and rec.sha256 and sha256_archivo(final) == rec.sha256:
        return rec.sha256
    parcial = final + ".part"
    for _ in range(REINTENTOS):
        try:
            _bajar(url, parcial, rec, progreso, cancelado)
            break
        except _Lenta:
            continue                                             # otra conexión suele ir a otro servidor del CDN
    else:
        raise ErrorDescarga(f"{rec.titulo or rec.clave}: la descarga va demasiado lenta; reintente más tarde")
    sha = sha256_archivo(parcial)
    if rec.sha256 and sha != rec.sha256 and estricto:
        os.remove(parcial)
        raise ErrorDescarga(f"{rec.archivo}: SHA-256 distinto al esperado ({sha[:12]}… ≠ {rec.sha256[:12]}…)")
    os.replace(parcial, final)
    return sha


def _bajar(url, parcial, rec, progreso, cancelado):
    ya = os.path.getsize(parcial) if os.path.exists(parcial) else 0
    req = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    if ya:
        req.add_header("Range", f"bytes={ya}-")
    try:
        resp = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as e:
        if e.code == 416:                                        # ya estaba completo
            return
        raise ErrorDescarga(f"{rec.titulo or rec.clave}: {e}") from e
    except Exception as e:                                       # noqa: BLE001 (se informa tal cual)
        raise ErrorDescarga(f"{rec.titulo or rec.clave}: {e}") from e
    with resp:
        if ya and resp.status != 206:
            ya = 0                                               # el servidor no reanuda: desde cero
        total = rec.tam
        largo = resp.headers.get("Content-Length")
        if largo and largo.isdigit():
            total = ya + int(largo)
        with open(parcial, "ab" if ya else "wb") as fh:
            n = ya
            t_ven, n_ven = time.monotonic(), n
            while True:
                if cancelado():
                    raise ErrorDescarga("cancelada")
                b = resp.read(BLOQUE)
                if not b:
                    break
                fh.write(b)
                n += len(b)
                if progreso:
                    progreso(n, total)
                ahora = time.monotonic()
                if ahora - t_ven >= VENTANA_S:
                    if (n - n_ven) / (ahora - t_ven) < VEL_MIN:
                        raise _Lenta()
                    t_ven, n_ven = ahora, n


# Bibliotecas de otras herramientas de llama.cpp que llama-server no carga
_SOBRAN = ("-bench-impl", "-cli-impl", "-completion-impl", "-fit-params-impl", "-perplexity-impl",
           "-quantize-impl", "libggml-rpc")


def extraer_runtime(tar_gz: str, destino: str) -> str:
    """Extrae llama-server y sus bibliotecas (.so) a destino; devuelve la ruta de llama-server."""
    tmp = destino + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    with tarfile.open(tar_gz) as tf:
        for m in tf.getmembers():
            nombre = os.path.basename(m.name)
            if not (m.isfile() or m.issym()):
                continue
            if any(x in nombre for x in _SOBRAN):
                continue
            if nombre in ("llama-server", "LICENSE") or ".so" in nombre:
                if m.issym():
                    os.symlink(os.path.basename(m.linkname), os.path.join(tmp, nombre))
                else:
                    with tf.extractfile(m) as src, open(os.path.join(tmp, nombre), "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    os.chmod(os.path.join(tmp, nombre), 0o755 if nombre == "llama-server" else 0o644)
    if not os.path.exists(os.path.join(tmp, "llama-server")):
        shutil.rmtree(tmp)
        raise ErrorDescarga("el paquete de llama.cpp no trae llama-server")
    shutil.rmtree(destino, ignore_errors=True)
    os.replace(tmp, destino)
    return os.path.join(destino, "llama-server")
