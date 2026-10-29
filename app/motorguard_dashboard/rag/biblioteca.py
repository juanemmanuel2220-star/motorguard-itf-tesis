"""
Estado de los documentos del catálogo y construcción o carga del índice.

- Un documento está "listo" si existe; "distinto" si su SHA-256 no es el de la versión evaluada (se indexa
  igual, pero se avisa); "falta" si no está.
- El manifiesto del índice guarda el SHA-256 de cada documento indexado y el del modelo de embeddings: si
  cambia algo, el índice se reconstruye.
"""

import os
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from motorguard_dashboard.rag import catalogo
from motorguard_dashboard.rag.descargas import sha256_archivo
from motorguard_dashboard.rag.indice import Indice
from motorguard_dashboard.rag.ingesta import fragmentos_documento, ruta_documento

_cache_sha: Dict[tuple, str] = {}


def _sha(ruta: str) -> str:
    st = os.stat(ruta)
    clave = (ruta, st.st_size, st.st_mtime_ns)
    if clave not in _cache_sha:
        _cache_sha[clave] = sha256_archivo(ruta)
    return _cache_sha[clave]


@dataclass
class EstadoDoc:
    rec: catalogo.Recurso
    ruta: str
    estado: str                 # "listo" | "distinto" | "falta"
    sha256: Optional[str]


def estado_documentos(carpeta_docs: str) -> List[EstadoDoc]:
    salida = []
    for rec in catalogo.DOCUMENTOS:
        ruta = ruta_documento(rec, carpeta_docs)
        if not os.path.isfile(ruta):
            salida.append(EstadoDoc(rec, ruta, "falta", None))
            continue
        sha = _sha(ruta)
        estado = "distinto" if rec.sha256 and sha != rec.sha256 else "listo"
        salida.append(EstadoDoc(rec, ruta, estado, sha))
    return salida


def manifiesto(estados: List[EstadoDoc]) -> dict:
    return {"documentos": {e.rec.clave: [e.sha256, list(e.rec.paginas or ()), list(e.rec.idiomas)]
                           for e in estados if e.estado != "falta"},
            "modelo_embeddings": catalogo.MODELO_EMB.sha256}


def titulos() -> Dict[str, catalogo.Recurso]:
    return {r.clave: r for r in catalogo.DOCUMENTOS}


def dir_indice(dir_asistente: str) -> str:
    return os.path.join(dir_asistente, "indice")


def cargar_o_construir(dir_asistente: str, carpeta_docs: str, embed: Optional[Callable] = None,
                       progreso: Optional[Callable[[str, int, int], None]] = None,
                       cancelado: Callable[[], bool] = lambda: False) -> Optional[Indice]:
    """Carga el índice si está vigente; si no y hay embed, lo reconstruye. Devuelve None si no se puede."""
    estados = estado_documentos(carpeta_docs)
    man = manifiesto(estados)
    previo = Indice.cargar(dir_indice(dir_asistente))
    if previo is not None and previo.vigente(man):
        return previo
    if embed is None or not man["documentos"]:
        return None
    frags = []
    listos = [e for e in estados if e.estado != "falta"]
    for k, e in enumerate(listos):
        if progreso:
            progreso(f"Leyendo {e.rec.titulo}", k, len(listos))
        frags.extend(fragmentos_documento(e.ruta, e.rec.clave, e.rec.idiomas, e.rec.paginas))
    def prog(n, total):
        if progreso:
            progreso("Indexando fragmentos", n, total)
    ind = Indice.construir(frags, embed, man, prog, cancelado=cancelado, previo=previo)
    ind.guardar(dir_indice(dir_asistente))
    return ind
