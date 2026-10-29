"""
Ingesta de documentos para el asistente: texto por página y fragmentos que NUNCA cruzan de página, para
que cada cita apunte a una sola página.

- PDF: texto con pdftotext (poppler) si está instalado; si no, con pypdf. La etiqueta de página impresa
  sale de pypdf (solo si es numérica: las etiquetas romanas de todo un documento no ayudan a encontrarla).
- Markdown (extracto de la tesis): cada sección "## " es una "página" citable como §N.
- Se descartan las páginas casi vacías, los índices (líneas de puntos), las páginas en blanco y, en
  documentos multilingües, las páginas en idiomas que no se indexan (Recurso.idiomas).
- Se quitan los encabezados y pies que se repiten en muchas páginas y se unen las palabras cortadas por guion.
"""

import os
import re
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

TAM_FRAGMENTO = 900          # caracteres
TRASLAPE = 150
MIN_CARACTERES_PAGINA = 200
REPETIDA_FRACCION = 0.3      # una línea en >= 30 % de las páginas es encabezado o pie

_STOP = {
    "en": "the and of to in is for be with that are on as by this or it an should from at which",
    "es": "de la el en y los las del que se por con para una un al es su o como debe",
    "de": "der die und das den des ist mit für von nicht auf eine zu im werden",
    "fr": "le la les de des et est pour dans une du un que en sur avec être",
    "it": "il la di e che per con del della una un dei sono gli le delle è",
    "pt": "o a de e do da que em para com os as um uma dos das não",
    "sv": "och att det för med som är på av en till inte ska om vid",
    "fi": "ja on ei että tai kun se ovat voi jos myös sekä tulee",
    "tr": "ve bir bu için ile da de olan veya gibi daha en olarak",
}
_STOP = {k: set(v.split()) for k, v in _STOP.items()}


@dataclass
class Pagina:
    doc: str
    pag: int                 # número de página del PDF (1 = primera) o de sección (§) en Markdown
    etiqueta: str            # página impresa ("" si no se conoce) o "§N"
    texto: str


@dataclass
class Fragmento:
    doc: str
    pag: int
    etiqueta: str
    texto: str


def idioma(texto: str) -> Optional[str]:
    palabras = re.findall(r"[a-zà-ÿäöüßğşıçãõâêôéèíóúñ]+", texto.lower())
    if len(palabras) < 20:
        return None
    cuentas = {k: sum(1 for p in palabras if p in s) for k, s in _STOP.items()}
    mejor = max(cuentas, key=cuentas.get)
    return mejor if cuentas[mejor] >= 5 else None


def _etiqueta_numerica(et: str) -> str:
    m = re.fullmatch(r"[A-Za-z]{0,2}(\d+)", et or "")
    return m.group(1) if m else ""


def _texto_pdftotext(ruta: str) -> Optional[List[str]]:
    if not shutil.which("pdftotext"):
        return None
    try:
        r = subprocess.run(["pdftotext", "-enc", "UTF-8", ruta, "-"], capture_output=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    paginas = r.stdout.decode("utf-8", errors="replace").split("\f")
    if paginas and not paginas[-1].strip():
        paginas.pop()
    return paginas


def paginas_pdf(ruta: str, doc: str) -> List[Pagina]:
    from pypdf import PdfReader
    lector = PdfReader(ruta)
    try:
        etiquetas = list(lector.page_labels)
    except Exception:                                            # noqa: BLE001 (PDF sin etiquetas válidas)
        etiquetas = []
    textos = _texto_pdftotext(ruta)
    if textos is None or len(textos) != len(lector.pages):
        textos = [(p.extract_text() or "") for p in lector.pages]
    return [Pagina(doc, k + 1, _etiqueta_numerica(etiquetas[k]) if k < len(etiquetas) else "", t)
            for k, t in enumerate(textos)]


def paginas_md(ruta: str, doc: str) -> List[Pagina]:
    texto = open(ruta, encoding="utf-8").read()
    partes = re.split(r"(?m)^## ", texto)
    paginas = []
    for k, parte in enumerate(partes[1:], start=1):
        titulo, _, cuerpo = parte.partition("\n")
        paginas.append(Pagina(doc, k, f"§{k}", f"{titulo.strip()}\n{cuerpo.strip()}"))
    return paginas


def _quitar_repetidas(paginas: List[Pagina]) -> None:
    if len(paginas) < 5:
        return
    def clave(linea):
        return re.sub(r"\d+", "#", re.sub(r"\s+", " ", linea.strip().lower()))
    cuenta = Counter()
    for p in paginas:
        cuenta.update({clave(l) for l in p.texto.splitlines() if l.strip()})
    repetidas = {c for c, n in cuenta.items() if n >= REPETIDA_FRACCION * len(paginas) and len(c) > 3}
    for p in paginas:
        p.texto = "\n".join(l for l in p.texto.splitlines() if clave(l) not in repetidas)


def _normalizar(texto: str) -> str:
    texto = texto.replace("­", "").replace("ﬁ", "fi").replace("ﬂ", "fl")
    texto = re.sub(r"(\w)-\n\s*(\w)", r"\1\2", texto)                 # palabra cortada por guion
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n\s*\n+", "\n\n", texto)
    return texto.strip()


def _descartable(texto: str) -> bool:
    if len(texto) < MIN_CARACTERES_PAGINA:
        return True
    if len(re.findall(r"(?:\.\s?){6,}", texto)) >= 5:                # índice con líneas de puntos
        return True
    return bool(re.search(r"intentionally left blank", texto, re.I)) and len(texto) < 400


def paginas_documento(ruta: str, doc: str, idiomas: Iterable[str] = ("en", "es"),
                      rangos: Optional[Sequence[Tuple[int, int]]] = None) -> List[Pagina]:
    """Páginas útiles de un documento, ya limpias (solo las de los rangos de páginas del PDF, si se dan)."""
    if ruta.lower().endswith(".md"):
        paginas = paginas_md(ruta, doc)
    else:
        paginas = paginas_pdf(ruta, doc)
        _quitar_repetidas(paginas)
        for p in paginas:                                       # números de página sueltos
            p.texto = re.sub(r"(?m)^\s*\d{1,4}\s*$", "", p.texto)
    idiomas = set(idiomas)
    salida = []
    for p in paginas:
        if rangos and not any(a <= p.pag <= b for a, b in rangos):
            continue
        p.texto = _normalizar(p.texto)
        if _descartable(p.texto):
            continue
        if not ruta.lower().endswith(".md") and idioma(p.texto) not in idiomas:
            continue
        salida.append(p)
    return salida


def fragmentar(p: Pagina, tam: int = TAM_FRAGMENTO, traslape: int = TRASLAPE) -> List[Fragmento]:
    """Parte una página en fragmentos de ~tam caracteres con traslape, cortando en fin de oración si se puede."""
    texto = re.sub(r"\s+", " ", p.texto).strip()
    if len(texto) <= tam * 1.3:
        return [Fragmento(p.doc, p.pag, p.etiqueta, texto)]
    tramos, ini = [], 0
    while True:
        fin = ini + tam
        if fin >= len(texto) or len(texto) - fin < tam // 4:   # el resto corto va con este tramo
            tramos.append((ini, len(texto)))
            break
        corte = max(texto.rfind(". ", ini + tam // 2, fin), texto.rfind("; ", ini + tam // 2, fin))
        if corte > 0:
            fin = corte + 1
        else:
            espacio = texto.rfind(" ", ini + tam // 2, fin)
            fin = espacio if espacio > 0 else fin
        tramos.append((ini, fin))
        espacio = texto.find(" ", fin - traslape)
        ini = espacio + 1 if 0 < espacio < fin else fin
    return [Fragmento(p.doc, p.pag, p.etiqueta, texto[a:b].strip()) for a, b in tramos]


def fragmentos_documento(ruta: str, doc: str, idiomas: Iterable[str] = ("en", "es"),
                         rangos: Optional[Sequence[Tuple[int, int]]] = None) -> List[Fragmento]:
    salida = []
    for p in paginas_documento(ruta, doc, idiomas, rangos):
        salida.extend(fragmentar(p))
    return salida


def ruta_documento(rec, carpeta_docs: str) -> str:
    """Ruta local del documento del catálogo (los que vienen con la app están en rag/datos/)."""
    if rec.en_paquete:
        return os.path.join(os.path.dirname(__file__), "datos", rec.archivo)
    return os.path.join(carpeta_docs, rec.archivo)
