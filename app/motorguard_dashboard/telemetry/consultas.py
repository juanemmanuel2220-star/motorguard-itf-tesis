"""
Consultas de solo lectura al firmware 299a943 y lectura de sus respuestas de varias líneas.

Solo se usan a petición del usuario (pestaña Dashboard), nunca durante un pulso de inyección:
  'W' -> volcado de 2048 muestras crudas de IA, IB, IC (cuentas ADC, sin calibrar)  (.ino l. 1502)
  'f' -> espectro 50-70 Hz de la fase crítica + resumen A55/A65 por fase             (printSpectrum)
  's' -> JSON con THD, I_neg, A50/A70, etc.                                           (.ino l. 1516)
Mientras el firmware imprime, su ciclo se detiene: en el log real del 06-oct (estabilidad5min_*) un
volcado 'W' duró 0.78 s y la trama siguiente llegó 0.85 s tarde (sin perder bloques).

Comandos con efectos (t enciende el SSR 700 ms; r reinicia el detector; k/K/n/b/p/h/l...) NO están aquí.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

CONSULTAS_LECTURA = {"W": "osciloscopio (corrientes crudas)", "f": "espectro 50-70 Hz", "s": "THD e I_neg"}

_RE_TRIPLE = re.compile(r"^(-?\d+),(-?\d+),(-?\d+)$")
_RE_FASE = re.compile(
    r"^\[FASE ([ABC]) [^\]]*\] Irms=([\d.]+)A \| Afund=([\d.]+) \| A55=([\d.]+)\(([\d.]+)Hz\)\[r55=([\d.]+)\] \| "
    r"A65=([\d.]+)\(([\d.]+)Hz\)\[r65=([\d.]+)\]")
_RE_CRITICA = re.compile(r"^>>> Fase Critica: FASE ([ABC]) \| .*Diagnostico IA: (\S+)")
_RE_FUND = re.compile(r"^Fundamental: A_fund = ([\d.]+)")
_RE_PICOS = re.compile(r"^Picos: f55p = ([\d.]+) Hz \(A55 = ([\d.]+)\) \| f65p = ([\d.]+) Hz \(A65 = ([\d.]+)\)")
_RE_FILA = re.compile(r"^(\d+\.\d) Hz \|\s*(-?[\d.]+) \|")
MAX_LINEAS_WAVE = 2100
MAX_LINEAS_FFT = 60


@dataclass
class FormaOnda:
    t: Optional[float]
    n_declarado: int
    ia: List[int] = field(default_factory=list)
    ib: List[int] = field(default_factory=list)
    ic: List[int] = field(default_factory=list)

    @property
    def completa(self) -> bool:
        return len(self.ia) == self.n_declarado


@dataclass
class EspectroCritico:
    t: Optional[float]
    fase: str = ""
    diagnostico: str = ""
    a_fund: Optional[float] = None
    f55p: Optional[float] = None       # picos de banda lateral que reporta el firmware (Hz)
    f65p: Optional[float] = None
    puntos: List[Tuple[float, float]] = field(default_factory=list)   # (Hz, amplitud del firmware)
    por_fase: List[Dict[str, float]] = field(default_factory=list)    # irms, afund, a55, f55, r55, a65, f65, r65


@dataclass
class Indicadores:
    t: Optional[float]
    valores: Dict[str, object] = field(default_factory=dict)


Respuesta = object  # FormaOnda | EspectroCritico | Indicadores


class AcumuladorRespuestas:
    """Junta las líneas de una respuesta de varias líneas. alimentar() devuelve (consumida, respuesta)."""

    def __init__(self):
        self._modo = None
        self._resp = None
        self._n = 0

    def alimentar(self, texto: str, t: Optional[float] = None) -> Tuple[bool, Optional[Respuesta]]:
        texto = texto.strip()
        if self._modo is None:
            if texto.startswith("[WAVE] begin"):
                m = re.search(r"n=(\d+)", texto)
                self._modo, self._resp, self._n = "W", FormaOnda(t, int(m.group(1)) if m else 0), 0
                return True, None
            if "BARRIDO FFT MULTIFASE" in texto:
                self._modo, self._resp, self._n = "f", EspectroCritico(t), 0
                return True, None
            if texto.startswith("{") and texto.endswith("}") and '"thd"' in texto:
                try:
                    return True, Indicadores(t, json.loads(texto))
                except ValueError:
                    return False, None
            return False, None

        self._n += 1
        if self._modo == "W":
            if texto.startswith("[WAVE] end"):
                return True, self._terminar()
            m = _RE_TRIPLE.match(texto)
            if m and self._n <= MAX_LINEAS_WAVE:
                self._resp.ia.append(int(m.group(1)))
                self._resp.ib.append(int(m.group(2)))
                self._resp.ic.append(int(m.group(3)))
                return True, None
            self._abandonar()          # algo inesperado: no se inventa el resto del volcado
            return False, None

        # modo 'f'
        e = self._resp
        if self._n > MAX_LINEAS_FFT:
            self._abandonar()
            return False, None
        if texto.startswith("[MCSA]"):
            self._abandonar()
            return False, None
        m = _RE_FASE.match(texto)
        if m:
            g = m.groups()
            e.por_fase.append({"fase": g[0], "irms": float(g[1]), "afund": float(g[2]), "a55": float(g[3]),
                               "f55": float(g[4]), "r55": float(g[5]), "a65": float(g[6]), "f65": float(g[7]),
                               "r65": float(g[8])})
        elif _RE_CRITICA.match(texto):
            m = _RE_CRITICA.match(texto)
            e.fase, e.diagnostico = m.group(1), m.group(2)
        elif _RE_FUND.match(texto):
            e.a_fund = float(_RE_FUND.match(texto).group(1))
        elif _RE_PICOS.match(texto):
            m = _RE_PICOS.match(texto)
            e.f55p, e.f65p = float(m.group(1)), float(m.group(3))
        elif _RE_FILA.match(texto):
            m = _RE_FILA.match(texto)
            e.puntos.append((float(m.group(1)), float(m.group(2))))
        elif re.fullmatch(r"=+", texto) and e.puntos:
            return True, self._terminar()
        return True, None

    def _terminar(self):
        r = self._resp
        self._abandonar()
        return r

    def _abandonar(self):
        self._modo, self._resp, self._n = None, None, 0

    @property
    def esperando(self) -> bool:
        return self._modo is not None
