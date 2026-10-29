"""
Asistente de mantenimiento: recupera fragmentos, arma el prompt y revisa las citas de la respuesta.

- Apoyo, no diagnóstico: el diagnóstico es el del detector embebido validado. El asistente solo propone
  inspecciones y mantenimiento citando documento y página.
- Solo recibe valores de la trama (severidad, ML, |I1|, corrientes por fase, tiempo con alarma, decisión del
  firmware) y no puede enviar nada al Arduino (este módulo no conoce el puerto serie).
- Si ningún fragmento se parece lo suficiente a la pregunta, responde que no hay fuente SIN llamar al LLM.
- Revisión de la respuesta: cada línea se clasifica como "con cita válida", "con cita inexistente" o
  "sin cita"; las citas [n] fuera de rango se marcan.
- Si el modelo externo falla (sin red, error o tiempo agotado), se responde con el local y se avisa.
"""

import re
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from motorguard_dashboard.rag import catalogo
from motorguard_dashboard.rag.indice import INSTRUCCION_CONSULTA, UMBRAL_ABSTENCION, Indice, Resultado
from motorguard_dashboard.rag.proveedores import ClienteOpenAI, ErrorProveedor

K_FRAGMENTOS = 5
# Al alarmar, de la tesis se incluye siempre el cierre de §6 (falsas alarmas: confirmar con pruebas fuera de línea) y
# §7 (otras limitaciones). La búsqueda traía §1 (el banco de pruebas) y el modelo aplicaba al motor vigilado los
# porcentajes de espiras y la fase C del banco (evaluación preliminar del 13-oct).
SECCIONES_TESIS_ALARMA = (6, 7)
# Documentos que describen el banco de la tesis: al alarmar no compiten con los de mantenimiento (de la tesis solo
# entran las secciones fijas de arriba; el documento técnico del banco solo responde preguntas libres).
DOCS_BANCO = ("tesis", "banco")
MAX_TOKENS = 600
RELLENO_CHECKPOINT = 500          # tokens tras el prefijo de alarma en el calentamiento (ver precalentar_alarma)
AVISO = "Apoyo, no diagnóstico: el diagnóstico es el del detector embebido validado."
SIN_FUENTE = ("No encontré en los documentos indexados información que responda esta pregunta, así que no "
              "puedo dar una recomendación con fuente.")

SISTEMA = """Eres el asistente de mantenimiento de MotorGuard-ITF. Ayudas al personal técnico a decidir qué inspeccionar y qué mantenimiento hacer en un motor de inducción trifásico cuando un detector embebido reporta una posible falla entre espiras del devanado del estator.

Reglas obligatorias:
1. Usa SOLO la información de los fragmentos numerados. No agregues conocimiento propio.
2. Cada punto termina con la cita del fragmento que lo respalda entre corchetes, por ejemplo [2]. Si se apoya en varios, cítalos todos: [1][3].
3. Si los fragmentos no responden la pregunta, escribe solo: "Los documentos disponibles no cubren esto." No completes con suposiciones.
4. No inventes mediciones ni valores. Los únicos valores medidos son los de "Valores medidos"; no los cambies.
5. No afirmes que el motor tiene o no tiene una falla: el diagnóstico es del detector; tú das apoyo para la inspección y el mantenimiento.
6. Si un fragmento da una precaución de seguridad (desenergizar, bloquear, descargar el devanado), ponla primero.
7. Los fragmentos de "Resultados validados de la tesis" y del "Documento técnico del banco de pruebas" describen el banco de pruebas de la tesis, no el motor vigilado: no apliques al motor vigilado sus porcentajes de espiras, su fase con falla ni sus otras cifras. Ante una alarma, úsalos solo para decir qué tan confiable es. Esta regla no aplica a los manuales, guías ni artículos: sus cifras son de esos documentos y se atribuyen a ellos, no al banco.
8. Responde en español, en una lista de 3 a 4 puntos breves que empiecen con "- ", sin introducción ni despedida. Traduce al español lo que esté en inglés."""

_NOMBRE_SEV = {1: "LEVE", 2: "INTER", 3: "SEVERA"}
_RE_CITA = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)*)\]")


@dataclass
class ContextoAlarma:
    """Solo valores medidos de la trama; ninguno se estima ni se completa."""
    severidad: Optional[str] = None       # LEVE / INTER / SEVERA, o None sin alarma
    ml_pp: Optional[float] = None
    i1_pico: Optional[float] = None
    ia: Optional[float] = None
    ib: Optional[float] = None
    ic: Optional[float] = None
    segundos_alarma: Optional[float] = None
    decision: Optional[str] = None

    @classmethod
    def de_trama(cls, trama, evento=None) -> "ContextoAlarma":
        d = trama.dir
        enclavada = bool(d.enclavada) and evento is not None
        return cls(severidad=_NOMBRE_SEV.get(d.sev) if enclavada else None,
                   ml_pp=d.ml if enclavada else None, i1_pico=trama.i1, ia=trama.ia, ib=trama.ib, ic=trama.ic,
                   segundos_alarma=evento.duracion(trama.t) if enclavada else None, decision=trama.decision)

    def texto(self) -> str:
        filas = []
        if self.severidad:
            filas.append(f"- Alarma confirmada por el firmware, severidad {self.severidad}")
            if self.ml_pp is not None:
                filas.append(f"- Magnitud de la firma (ML): {self.ml_pp:.2f} pp de |I1|")
            if self.segundos_alarma is not None:
                filas.append(f"- Tiempo con la alarma activa: {self.segundos_alarma:.0f} s")
        else:
            filas.append("- Sin alarma confirmada en este momento")
        if self.i1_pico is not None:
            filas.append(f"- Corriente de secuencia positiva |I1|: {self.i1_pico:.3f} A pico")
        if None not in (self.ia, self.ib, self.ic):
            filas.append(f"- Corrientes por fase: A {self.ia:.2f} A, B {self.ib:.2f} A, C {self.ic:.2f} A")
        if self.decision:
            filas.append(f"- Decisión del firmware: {self.decision}")
        return "\n".join(filas)


def pregunta_alarma(ctx: ContextoAlarma) -> str:
    return (f"El detector confirmó una alarma {ctx.severidad} (posible cortocircuito entre espiras del estator). "
            "¿Qué inspecciones, pruebas y acciones de mantenimiento recomiendan los documentos, y con qué "
            "precauciones de seguridad?")


CONSULTA_ALARMA = ("inspección y pruebas del aislamiento del devanado del estator ante un cortocircuito entre espiras: "
                   "resistencia de aislamiento, índice de polarización, prueba de impulso, humedad, precauciones de "
                   "seguridad antes de inspeccionar")


_RE_CIFRA = re.compile(r"\b\d+[.,]\d+\b")


def _cifras_soportadas(textos: List[str]) -> set:
    """Conjunto de cifras decimales (exactas y redondeadas a 1–3 decimales) presentes en los textos de soporte."""
    soporte = set()
    for txt in textos:
        for m in _RE_CIFRA.findall(txt or ""):
            norm = m.replace(",", ".")
            soporte.add(norm)
            try:
                val = float(norm)
                soporte.update({f"{val:.1f}", f"{val:.2f}", f"{val:.3f}", f"{val:g}"})
            except ValueError:
                pass
    return soporte


@dataclass
class Linea:
    texto: str
    citas: List[int]
    invalidas: List[int]
    cifras_sin_soporte: List[str] = field(default_factory=list)

    @property
    def es_afirmacion(self) -> bool:
        t = self.texto.strip()
        return len(t) >= 25 and not t.endswith(":")


@dataclass
class Respuesta:
    pregunta: str
    texto: str
    fuentes: List[Resultado]
    lineas: List[Linea] = field(default_factory=list)
    modelo: str = ""
    abstencion: bool = False
    max_coseno: float = 0.0
    t_busqueda: float = 0.0
    t_primer_token: Optional[float] = None
    t_total: float = 0.0
    tokens_prompt: Optional[int] = None
    tokens_respuesta: Optional[int] = None
    cancelada: bool = False
    aviso: str = ""                      # p. ej., "el modelo externo falló; respondió el local"
    error: str = ""
    contexto: Optional[str] = None       # valores medidos que recibió el modelo (los de la trama al preguntar)

    @property
    def fraccion_citada(self) -> Optional[float]:
        af = [l for l in self.lineas if l.es_afirmacion]
        if not af:
            return None
        return sum(1 for l in af if l.citas and not l.invalidas) / len(af)

    @property
    def cifras_sin_soporte(self) -> List[str]:
        return [c for l in self.lineas for c in l.cifras_sin_soporte]


def analizar(texto: str, n_fuentes: int, fuentes: Optional[List[Resultado]] = None,
             contexto: Optional[str] = None) -> List[Linea]:
    lineas = []
    for cruda in texto.splitlines():
        t = cruda.strip()
        if not t:
            continue
        nums = [int(x) for g in _RE_CITA.findall(t) for x in re.split(r"[,;]", g) if x.strip()]
        validas = sorted(set(n for n in nums if 1 <= n <= n_fuentes))
        invalidas = sorted(set(n for n in nums if not 1 <= n <= n_fuentes))
        sin_soporte = []
        if fuentes and validas:
            limpio = _RE_CITA.sub("", t)
            cifras = _RE_CIFRA.findall(limpio)
            if cifras:
                textos_cita = [fuentes[n - 1].fragmento.texto for n in validas if 1 <= n <= len(fuentes)]
                if contexto:
                    textos_cita.append(contexto)
                soporte = _cifras_soportadas(textos_cita)
                for c in cifras:
                    if c.replace(",", ".") not in soporte and c not in sin_soporte:
                        sin_soporte.append(c)
        lineas.append(Linea(t, validas, invalidas, sin_soporte))
    return lineas


def describir_fuente(r: Resultado) -> str:
    rec = {x.clave: x for x in catalogo.DOCUMENTOS}.get(r.fragmento.doc)
    titulo = rec.titulo if rec else r.fragmento.doc
    f = r.fragmento
    if f.etiqueta.startswith("§"):
        return f"{titulo}, {f.etiqueta}"
    impresa = f" (impresa {f.etiqueta})" if f.etiqueta and f.etiqueta != str(f.pag) else ""
    return f"{titulo}, pág. {f.pag} del PDF{impresa}"


def construir_mensajes(pregunta: str, fuentes: List[Resultado], ctx: Optional[ContextoAlarma]) -> List[dict]:
    bloques = [f"[{k}] {describir_fuente(r)}:\n{r.fragmento.texto}" for k, r in enumerate(fuentes, start=1)]
    usuario = "Fragmentos:\n\n" + "\n\n".join(bloques)
    if ctx is not None:
        usuario += "\n\nValores medidos (de la trama del detector):\n" + ctx.texto()
    usuario += f"\n\nPregunta: {pregunta}"
    return [{"role": "system", "content": SISTEMA}, {"role": "user", "content": usuario}]


def _slot(cliente: ClienteOpenAI, alarma: bool) -> dict:
    """En el llama-server local, cada tipo de consulta usa su slot: el de alarma conserva en caché el prefijo
    (sistema + fragmentos), que es igual en todas las alarmas porque la consulta de búsqueda es fija."""
    if cliente.slot_alarma is None:
        return {}
    return {"id_slot": cliente.slot_alarma if alarma else 0}


class Asistente:
    def __init__(self, indice: Indice, cliente_emb: ClienteOpenAI, cliente_llm: ClienteOpenAI,
                 respaldo_llm: Optional[ClienteOpenAI] = None, k: int = K_FRAGMENTOS,
                 umbral: float = UMBRAL_ABSTENCION):
        self.indice = indice
        self.emb = cliente_emb
        self.llm = cliente_llm
        self.respaldo = respaldo_llm
        self.k = k
        self.umbral = umbral

    def recuperar(self, consulta: str, alarma: bool = False):
        vec = self.emb.embeddings([INSTRUCCION_CONSULTA + consulta])[0]
        if alarma:
            # Para una alarma: k - 1 fragmentos de mantenimiento y, siempre, el cierre de las secciones de la tesis
            # sobre falsas alarmas y limitaciones (SECCIONES_TESIS_ALARMA)
            otros = [c for c in {f.doc for f in self.indice.fragmentos} if c not in DOCS_BANCO]
            fuentes = self.indice.buscar(consulta, vec, self.k - 1, docs=otros) + self._tesis_alarma(vec)
        else:
            fuentes = self.indice.buscar(consulta, vec, self.k)
        return fuentes, self.indice.max_coseno(vec)

    def _tesis_alarma(self, vec) -> List[Resultado]:
        """Último fragmento de cada sección de SECCIONES_TESIS_ALARMA (el que cierra con la consecuencia práctica)."""
        v = vec.astype("float32").ravel()
        v /= max(float((v @ v) ** 0.5), 1e-9)
        salida = []
        for sec in SECCIONES_TESIS_ALARMA:
            idx = [i for i, f in enumerate(self.indice.fragmentos) if f.doc == "tesis" and f.pag == sec]
            if idx:
                salida.append(Resultado(self.indice.fragmentos[idx[-1]], 0.0, float(self.indice.emb[idx[-1]] @ v), 0.0))
        return salida

    def precalentar_alarma(self, cancelado: Callable[[], bool] = lambda: False) -> Optional[int]:
        """Procesa por adelantado, en su slot, el prefijo de la consulta de alarma (sistema + fragmentos + inicio de
        los valores medidos). Devuelve el largo del prefijo en tokens.

        Qwen3.5 es híbrido (capas recurrentes): llama-server solo puede retomar un prompt desde un checkpoint, y
        crea uno unos 516 tokens antes del final de cada prompt (n_ubatch = 512). Por eso el calentamiento es el
        prefijo común seguido de RELLENO_CHECKPOINT tokens: el checkpoint cae justo antes del final del prefijo y la
        alarma real solo procesa los valores medidos y la pregunta (medido el 13-oct: 177 de 1569 tokens)."""
        if self.llm.slot_alarma is None:
            return None
        fuentes, _ = self.recuperar(CONSULTA_ALARMA, alarma=True)
        kw = {k: v for k, v in self.llm.extra_chat.items() if k == "chat_template_kwargs"}
        tokens = []
        for sev in _NOMBRE_SEV.values():      # el prefijo común termina donde empieza la severidad
            ctx = ContextoAlarma(sev, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, sev)
            prompt = self.llm.llama("/apply-template", dict(messages=construir_mensajes(pregunta_alarma(ctx),
                                                                                         fuentes, ctx), **kw))
            tokens.append(self.llm.llama("/tokenize", {"content": prompt["prompt"], "parse_special": True})["tokens"])
            if cancelado():
                return None
        prefijo = min(next((i for i, (x, y) in enumerate(zip(tokens[0], t)) if x != y), len(t)) for t in tokens[1:])
        cola = tokens[0][prefijo:] or [tokens[0][-1]]
        relleno = (cola * (RELLENO_CHECKPOINT // len(cola) + 1))[:RELLENO_CHECKPOINT]
        self.llm.llama("/completion", {"prompt": tokens[0][:prefijo] + relleno, "n_predict": 1, "cache_prompt": True,
                                       "id_slot": self.llm.slot_alarma})
        return prefijo

    def responder(self, pregunta: str, ctx: Optional[ContextoAlarma] = None, alarma: bool = False,
                  al_token: Optional[Callable[[str], None]] = None,
                  cancelado: Callable[[], bool] = lambda: False) -> Respuesta:
        t0 = time.monotonic()
        consulta = CONSULTA_ALARMA if alarma else pregunta
        fuentes, max_cos = self.recuperar(consulta, alarma)
        r = Respuesta(pregunta, "", fuentes, max_coseno=max_cos, t_busqueda=time.monotonic() - t0,
                      contexto=ctx.texto() if ctx is not None else None)
        if not alarma and max_cos < self.umbral:
            r.abstencion, r.texto, r.fuentes = True, SIN_FUENTE, []
            r.t_total = time.monotonic() - t0
            return r
        mensajes = construir_mensajes(pregunta, fuentes, ctx)
        cliente = self.llm
        try:
            res = cliente.chat(mensajes, MAX_TOKENS, al_token=al_token, cancelado=cancelado,
                               extra=_slot(cliente, alarma))
        except ErrorProveedor as e:
            if self.respaldo is None or cliente is self.respaldo:
                r.error = str(e)
                r.t_total = time.monotonic() - t0
                return r
            r.aviso = f"El modelo externo falló ({e}); respondió el modelo local."
            if al_token:
                al_token("\n")
            res = self.respaldo.chat(mensajes, MAX_TOKENS, al_token=al_token, cancelado=cancelado,
                                     extra=_slot(self.respaldo, alarma))
        r.texto = res.texto.strip()
        r.modelo = res.modelo
        r.t_primer_token = res.t_primer_token
        r.tokens_prompt, r.tokens_respuesta = res.tokens_prompt, res.tokens_respuesta
        r.cancelada = res.cancelado
        r.lineas = analizar(r.texto, len(fuentes), fuentes=fuentes, contexto=r.contexto)
        r.t_total = time.monotonic() - t0
        return r
