"""
Índice híbrido del asistente: embeddings (Qwen3-Embedding por llama-server) + BM25, fusionados con RRF.

- Los documentos están en inglés y en español, y las preguntas en español: los embeddings multilingües
  cubren el cruce de idiomas; para BM25 la consulta se amplía con un glosario fijo ES→EN del dominio.
- Abstención: si el fragmento más parecido (coseno) queda bajo UMBRAL_ABSTENCION, no hay fuente y el
  asistente responde sin llamar al LLM. El umbral se fija con preguntas de desarrollo, no con las de la
  evaluación (rag_eval/).
- Se guarda en una carpeta (manifiesto.json + fragmentos.json + embeddings.npy) y se reconstruye si cambia
  un documento (SHA-256), el modelo de embeddings o la versión del fragmentado.
"""

import json
import math
import os
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np

from motorguard_dashboard.rag.ingesta import Fragmento

VERSION = 1
K_RRF = 15
UMBRAL_ABSTENCION = 0.49          # coseno; punto medio entre preguntas de desarrollo fuera de tema (máx. 0.412) y pertinentes (mín. 0.564), 13-oct
MAX_POR_PAGINA = 2
MAX_POR_DOC = 3
INSTRUCCION_CONSULTA = ("Instruct: Given a question about the maintenance, inspection or testing of an electric "
                        "motor, retrieve passages that answer it\nQuery: ")

_STOP = set("""
a al algo como con de del el ella en es esta este esto la las lo los mas o para pero por que se si sin su sus un una
uno y the a an and are as at be by for from has have in is it its of on or that the this to was were will with
can should may must not be been being which what when how do does if into than then there these those such
qué cuál cuáles cómo cuándo debo debe hay mi motor motores
segun puede pueden cuanto cuanta cuantos cuantas donde quien cual cuales basa hacer hace dice indica significa
tiene tienen quedan queda evitar entre sobre tras ante bajo hacia hasta desde
""".split())

# Glosario ES -> EN para BM25 (los embeddings ya son multilingües)
GLOSARIO = {
    "aislamiento": "insulation", "devanado": "winding", "devanados": "windings", "bobinado": "winding",
    "espiras": "turns turn-to-turn", "espira": "turn", "estator": "stator", "rotor": "rotor",
    "cortocircuito": "short circuit", "resistencia": "resistance", "megohmetro": "megohmmeter megger",
    "megometro": "megohmmeter megger", "indice": "index", "polarizacion": "polarization",
    "impulso": "surge impulse", "humedad": "moisture humidity damp", "secado": "drying dry",
    "temperatura": "temperature", "rodamiento": "bearing", "rodamientos": "bearings", "lubricacion": "lubrication",
    "vibracion": "vibration", "termografia": "thermography infrared", "corriente": "current",
    "desbalance": "unbalance imbalance", "voltaje": "voltage", "tension": "voltage", "falla": "fault failure",
    "fallas": "faults failures", "prueba": "test testing", "pruebas": "tests testing", "inspeccion": "inspection",
    "mantenimiento": "maintenance", "predictivo": "predictive", "preventivo": "preventive",
    "frecuencia": "frequency interval", "periodicidad": "interval frequency", "limpieza": "cleaning",
    "calentamiento": "heating overheating", "sobrecalentamiento": "overheating", "arranque": "starting start",
    "seguridad": "safety", "bloqueo": "lockout", "desenergizar": "de-energize energized deenergized lockout",
    "desenergizado": "energized deenergized lockout", "carga": "load",
    "firma": "signature", "analisis": "analysis", "electrico": "electrical", "electrica": "electrical",
    "tierra": "ground", "puesta": "grounding", "almacenamiento": "storage", "calentadores": "heaters",
    "aceptable": "acceptable minimum", "minimo": "minimum", "valor": "value", "hipot": "hipot high potential",
    "potencial": "potential", "descargas": "discharge", "parciales": "partial", "barniz": "varnish",
    "rebobinado": "rewind rewinding", "reparacion": "repair", "tendencia": "trend trending",
    "condensacion": "condensation dew", "rocio": "dew point", "parado": "idle standstill stopped",
    "inactivo": "idle", "calentarse": "heated heat space heaters", "calentar": "heat heated space heaters",
    "calentador": "heater space heaters", "absorcion": "absorption dielectric",
    "dielectrica": "dielectric absorption", "interpreta": "interpret interpretation",
    "interpretacion": "interpretation", "envolvente": "envelope starting", "metodo": "method",
    "fase": "phase", "fases": "phases", "ubicar": "locate position", "localizar": "locate position",
    "posicion": "position", "secuencia": "sequence", "negativa": "negative", "positiva": "positive",
    "inversor": "inverter", "variador": "inverter drive vfd", "comparacion": "comparison",
    "rutinario": "routine", "rutinaria": "routine", "critico": "critical", "criticos": "critical",
    "anualmente": "annually annual", "anual": "annual annually", "horno": "oven bake",
    "secar": "dry drying", "secarse": "dry drying", "humedo": "damp wet moisture",
    "carcasa": "frame ground", "bornes": "terminals", "cables": "cables leads",
    "barras": "bars broken rotor", "rotas": "broken bars",
    "relacion": "ratio", "aceptables": "acceptable", "efecto": "effect", "trifasico": "three-phase",
    "menos": "less", "cada": "interval frequency",
    "sensor": "sensors acs712 zmpt101b", "sensores": "sensor sensors acs712 zmpt101b",
}

# Menciones explícitas de autor o fuente en la pregunta -> claves de documento asociadas
AUTOR_DOC = {
    "abb": ("abb",), "nasa": ("nasa_rcm",), "rcm": ("nasa_rcm",),
    "femp": ("femp_om",), "doe": ("femp_om",),
    "usbr": ("usbr_3_1", "usbr_3_4", "usbr_4_1b"), "fist": ("usbr_3_1", "usbr_3_4", "usbr_4_1b"),
    "ruzimov": ("ruzimov2025",), "chen": ("chen2023",),
    "banco": ("banco", "tesis"), "tesis": ("tesis", "banco"),
}


def _sin_acentos(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))


def tokens(texto: str) -> List[str]:
    return [w for w in re.findall(r"[a-z0-9]+", _sin_acentos(texto.lower())) if len(w) > 1 and w not in _STOP]


def ampliar_consulta(texto: str) -> List[str]:
    tk = tokens(texto)
    extra = []
    for w in tk:
        if w in GLOSARIO:
            extra.extend(tokens(GLOSARIO[w]))
    return tk + extra


@dataclass
class Resultado:
    fragmento: Fragmento
    rrf: float
    coseno: float
    bm25: float


class Indice:
    def __init__(self, fragmentos: List[Fragmento], embeddings: np.ndarray, manifiesto: Optional[dict] = None):
        self.fragmentos = fragmentos
        self.emb = embeddings.astype(np.float32)
        norm = np.linalg.norm(self.emb, axis=1, keepdims=True)
        self.emb /= np.maximum(norm, 1e-9)
        self.manifiesto = manifiesto or {}
        self._tf = [Counter(tokens(f.texto)) for f in fragmentos]
        self._largo = np.array([sum(c.values()) for c in self._tf], dtype=np.float64)
        self._largo_medio = float(self._largo.mean()) if len(self._largo) else 1.0
        df = Counter()
        for c in self._tf:
            df.update(c.keys())
        n = len(fragmentos)
        self._idf = {w: math.log(1 + (n - d + 0.5) / (d + 0.5)) for w, d in df.items()}

    def __len__(self):
        return len(self.fragmentos)

    # ---------------------------------------------------------------- construcción y disco
    @classmethod
    def construir(cls, fragmentos: List[Fragmento], embed: Callable[[List[str]], np.ndarray],
                  manifiesto: dict, progreso: Optional[Callable[[int, int], None]] = None,
                  lote: int = 16, cancelado: Callable[[], bool] = lambda: False,
                  previo: Optional["Indice"] = None) -> "Indice":
        """Con un índice previo del mismo modelo de embeddings, reutiliza el vector de cada fragmento idéntico
        (documento, página y texto) y solo calcula los nuevos: agregar un documento no reindexa los demás."""
        reuso = {}
        if (previo is not None and previo.manifiesto.get("modelo_embeddings") == manifiesto.get("modelo_embeddings")
                and previo.manifiesto.get("version") == VERSION):
            reuso = {(f.doc, f.pag, f.texto): previo.emb[i] for i, f in enumerate(previo.fragmentos)}
        nuevos = [i for i, f in enumerate(fragmentos) if (f.doc, f.pag, f.texto) not in reuso]
        calculados = {}
        for j in range(0, len(nuevos), lote):
            if cancelado():
                raise InterruptedError("indexado cancelado")
            grupo = nuevos[j:j + lote]
            for i, v in zip(grupo, embed([fragmentos[i].texto for i in grupo])):
                calculados[i] = v
            if progreso:
                progreso(min(len(nuevos), j + lote), len(nuevos))
        filas = [calculados[i] if i in calculados else reuso[(f.doc, f.pag, f.texto)] for i, f in enumerate(fragmentos)]
        emb = np.vstack(filas).astype(np.float32) if filas else np.zeros((0, 1), np.float32)
        return cls(fragmentos, emb, dict(manifiesto, version=VERSION))

    def guardar(self, carpeta: str):
        tmp = carpeta + ".tmp"
        os.makedirs(tmp, exist_ok=True)
        np.save(os.path.join(tmp, "embeddings.npy"), self.emb)
        with open(os.path.join(tmp, "fragmentos.json"), "w", encoding="utf-8") as fh:
            json.dump([asdict(f) for f in self.fragmentos], fh, ensure_ascii=False)
        with open(os.path.join(tmp, "manifiesto.json"), "w", encoding="utf-8") as fh:
            json.dump(self.manifiesto, fh, ensure_ascii=False, indent=1)
        if os.path.isdir(carpeta):
            import shutil
            shutil.rmtree(carpeta)
        os.replace(tmp, carpeta)

    @classmethod
    def cargar(cls, carpeta: str) -> Optional["Indice"]:
        try:
            with open(os.path.join(carpeta, "manifiesto.json"), encoding="utf-8") as fh:
                man = json.load(fh)
            with open(os.path.join(carpeta, "fragmentos.json"), encoding="utf-8") as fh:
                frags = [Fragmento(**d) for d in json.load(fh)]
            emb = np.load(os.path.join(carpeta, "embeddings.npy"))
        except (OSError, ValueError, TypeError):
            return None
        if len(frags) != len(emb):
            return None
        return cls(frags, emb, man)

    def vigente(self, manifiesto: dict) -> bool:
        """El índice corresponde a estos documentos y a este modelo de embeddings."""
        # Se compara como JSON: al guardarlo, las tuplas (rangos de páginas) se vuelven listas
        return json.loads(json.dumps(self.manifiesto)) == json.loads(json.dumps(dict(manifiesto, version=VERSION)))

    # ---------------------------------------------------------------- búsqueda
    def bm25(self, consulta_tokens: Sequence[str], k1: float = 1.5, b: float = 0.75) -> np.ndarray:
        puntos = np.zeros(len(self.fragmentos))
        q = Counter(consulta_tokens)
        for i, tf in enumerate(self._tf):
            s = 0.0
            for w in q:
                f = tf.get(w)
                if f:
                    s += self._idf[w] * f * (k1 + 1) / (f + k1 * (1 - b + b * self._largo[i] / self._largo_medio))
            puntos[i] = s
        return puntos

    def buscar(self, consulta: str, vec_consulta: np.ndarray, k: int = 5,
               docs: Optional[Sequence[str]] = None) -> List[Resultado]:
        """Los k mejores fragmentos (RRF de coseno y BM25), con tope por página y diversidad por documento."""
        if not self.fragmentos:
            return []
        v = vec_consulta.astype(np.float32).ravel()
        v /= max(float(np.linalg.norm(v)), 1e-9)
        cos = self.emb @ v
        q_tk = ampliar_consulta(consulta)
        bm = self.bm25(q_tk)
        permitido = np.ones(len(self.fragmentos), bool)
        if docs is not None:
            permitido = np.array([f.doc in docs for f in self.fragmentos])
        docs_mencionados = {d for w in q_tk if w in AUTOR_DOC for d in AUTOR_DOC[w]}
        rrf: Dict[int, float] = {}
        for puntos in (cos, bm):
            orden = [i for i in np.argsort(-puntos) if permitido[i]]
            for r, i in enumerate(orden):
                if puntos is bm and bm[i] <= 0:
                    break
                rrf[int(i)] = rrf.get(int(i), 0.0) + 1.0 / (K_RRF + r + 1)
        if docs_mencionados:
            bono = 1.0 / (K_RRF + 5)
            for i in list(rrf):
                if self.fragmentos[i].doc in docs_mencionados:
                    rrf[i] += bono
        salida, por_pagina, por_doc, diferidos = [], Counter(), Counter(), []
        for i in sorted(rrf, key=rrf.get, reverse=True):
            f = self.fragmentos[i]
            if por_pagina[(f.doc, f.pag)] >= MAX_POR_PAGINA:
                continue
            if docs is None and f.doc not in docs_mencionados and por_doc[f.doc] >= MAX_POR_DOC:
                diferidos.append(i)
                continue
            por_pagina[(f.doc, f.pag)] += 1
            por_doc[f.doc] += 1
            salida.append(Resultado(f, rrf[i], float(cos[i]), float(bm[i])))
            if len(salida) == k:
                break
        for i in diferidos:
            if len(salida) == k:
                break
            f = self.fragmentos[i]
            if por_pagina[(f.doc, f.pag)] < MAX_POR_PAGINA:
                por_pagina[(f.doc, f.pag)] += 1
                salida.append(Resultado(f, rrf[i], float(cos[i]), float(bm[i])))
        return salida

    def max_coseno(self, vec_consulta: np.ndarray) -> float:
        v = vec_consulta.astype(np.float32).ravel()
        v /= max(float(np.linalg.norm(v)), 1e-9)
        return float((self.emb @ v).max()) if len(self.emb) else 0.0
