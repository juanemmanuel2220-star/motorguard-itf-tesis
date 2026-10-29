"""
Geometría del detector direccional para dibujarla (tarjeta "Plano de la firma" en Monitoreo).

Reproduce el cálculo de detector_dir.cpp (firmware 299a943) a partir de los fasores crudos de cada trama
(campo RAW: R2, |I1|, V2 y |V1|, en valores pico y referidos a arg(V1)):
    z   = R2 / |I1| * 100                                 (pp de |I1|)
    ref = mediana por componente de z en [t - 11 s, t - 6 s] (con al menos 2 bloques)
    dz  = z - ref ;  P = Re{dz * e^(-j*ANG_FALLA)}
    al confirmar la alarma se congela base = ref; ML = |z - base|

Base congelada: en el bloque de confirmación se toma la referencia recalculada; desde el bloque siguiente
se despeja de lo que reporta el firmware, que con la alarma enclavada da PL = proyección y ML = |z - base|:
    z - base = (PL + j*s*sqrt(ML^2 - PL^2)) * e^(j*ANG_FALLA),  s = +-1 (la más cercana a la estimación)
así la base dibujada es la del firmware (salvo el redondeo a 3 decimales).

Es SOLO para dibujar: las decisiones (P, C, SEV, ML, PL) siempre son las del firmware. La app usa la hora
de recepción de cada trama y el firmware su millis(), así que un bloque en el borde de la ventana puede
entrar en un cálculo y no en el otro (en 2887 tramas reales de validacion_vivo coincidieron el 99 % dentro
de 0.01 pp). Para acercarse al firmware, los bloques a menos de 0.5 s de un borde se tratan como dudosos
y se elige la combinación (con o sin cada uno) cuya P coincide con la del firmware. Si ninguna coincide,
el dibujo de la referencia se marca "aproximado".
"""

import cmath
import itertools
import math
import re
import statistics
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from motorguard_dashboard.telemetry.parser import Trama

# Constantes de detector_dir.h (firmware 299a943); no se cambian sin repetir la validación ciega
ANG_FALLA_DEG = -81.4
UMBRAL_PP = 0.40
REF_DESDE_S = 11.0
REF_HASTA_S = 6.0
HIST_S = 30.0
HIST_N = 32
SEV_U1 = 1.626
SEV_U2 = 4.471
TOL_COINCIDE_PP = 0.01      # P recalculada vs P del firmware (se imprime con 3 decimales)
MARGEN_BORDE_S = 0.8        # bloques a menos de esto de un borde de la ventana: dudosos (reloj distinto)
MAX_DUDOSOS = 5

DIR_FALLA = cmath.exp(1j * math.radians(ANG_FALLA_DEG))   # vector unitario de la dirección de falla

_RE_RAW = re.compile(r"RAW: R2=(-?[\d.]+),(-?[\d.]+) I1=(-?[\d.]+) V2=(-?[\d.]+),(-?[\d.]+) V1=(-?[\d.]+)")


def proyectar(d: complex) -> float:
    """Componente de d en la dirección de falla (proyectar() de detector_dir.cpp)."""
    return d.real * DIR_FALLA.real + d.imag * DIR_FALLA.imag


@dataclass
class EstadoFirma:
    t: float
    z: complex                          # firma del bloque actual (pp de |I1|)
    estela: List[Tuple[float, complex]]  # bloques recientes (t, z), del más viejo al actual
    ref: Optional[complex]              # referencia móvil recalculada (None si no hay 2 bloques)
    dz: Optional[complex]
    p_app: Optional[float]
    p_fw: float
    ref_fw: bool
    enclavada: bool
    sev: int
    ml_fw: float
    pl_fw: float
    base: Optional[complex]             # referencia congelada al confirmar (None sin alarma o si no se vio)
    base_desconocida: bool              # alarma ya enclavada cuando empezó a verse (no hay base)
    v1: float                           # |V1| pico (V); referencia de ángulos
    v2: complex                         # V2 pico (V), referido a arg(V1)
    i1: float                           # |I1| pico (A)
    r2: complex                         # R2 pico (A), referido a arg(V1)
    notas: List[str] = field(default_factory=list)

    @property
    def coincide(self) -> bool:
        """La P recalculada coincide con la del firmware (si no, el dibujo de la referencia es aproximado)."""
        return self.p_app is not None and abs(self.p_app - self.p_fw) <= TOL_COINCIDE_PP

    @property
    def ml_app(self) -> Optional[float]:
        """|z - base| con la base recalculada (para comparar con ML del firmware)."""
        return abs(self.z - self.base) if self.base is not None else None

    @property
    def u2v(self) -> float:
        return abs(self.v2) / self.v1 * 100.0 if self.v1 > 0 else 0.0


def fasores_raw(t: Trama) -> Optional[Tuple[complex, float, complex, float]]:
    """(R2, |I1|, V2, |V1|) del campo RAW de la trama, o None."""
    m = _RE_RAW.search(t.texto)
    if not m:
        return None
    r2r, r2i, i1, v2r, v2i, v1 = map(float, m.groups())
    return complex(r2r, r2i), i1, complex(v2r, v2i), v1


class PlanoFirma:
    """Sigue las tramas y devuelve el estado geométrico de cada una (None si no hay firma que dibujar)."""

    def __init__(self):
        self.hist: List[Tuple[float, complex]] = []
        self.base: Optional[complex] = None
        self._c_prev = False
        self._ref_prev = False
        self._visto_sin_alarma = False
        self._base_del_fw = False
        self._cond_base = 0.0
        self.ultimo: Optional[EstadoFirma] = None

    def reiniciar(self):
        self.hist.clear()
        self.base = None
        self._c_prev = False
        self._ref_prev = False
        self._visto_sin_alarma = False
        self._base_del_fw = False
        self._cond_base = 0.0

    @staticmethod
    def base_desde_firmware(z: complex, pl: float, ml: float, cerca: Optional[complex]) -> complex:
        """Base congelada a partir de z, PL y ML del firmware (de las dos soluciones, la más cercana a 'cerca')."""
        perp = math.sqrt(max(0.0, ml * ml - pl * pl))
        sols = [z - complex(pl, s * perp) * DIR_FALLA for s in (1.0, -1.0)]
        if cerca is None:
            return sols[0]
        return min(sols, key=lambda b: abs(b - cerca))

    @staticmethod
    def _referencia(z: complex, seguros: List[complex], dudosos: List[Tuple[complex, bool]],
                    p_fw: float) -> Optional[complex]:
        """Mediana por componente; entre las combinaciones de bloques dudosos, la que reproduce P del firmware
        (empezando por la que dicta el reloj de la app)."""
        def med(v):
            return complex(statistics.median(x.real for x in v), statistics.median(x.imag for x in v))
        natural = tuple(dentro for _, dentro in dudosos)
        opciones = [natural] + [c for c in itertools.product((True, False), repeat=len(dudosos)) if c != natural]
        mejor = None
        for combo in opciones:
            v = seguros + [zz for (zz, _), usar in zip(dudosos, combo) if usar]
            if len(v) < 2:
                continue
            ref = med(v)
            if abs(proyectar(z - ref) - p_fw) <= TOL_COINCIDE_PP:
                return ref
            if combo == natural:
                mejor = ref                      # si nada coincide, se dibuja la del reloj de la app
        return mejor

    def procesar(self, t: Trama) -> Optional[EstadoFirma]:
        if t.t is None:
            return None
        if t.motor != "ON":
            # El firmware reinicia el detector con el motor apagado o en WARMUP (dir_init)
            self.reiniciar()
            self.ultimo = None
            return None
        raw = fasores_raw(t)
        if raw is None:
            return None
        r2, i1, v2, v1 = raw
        if i1 < 1e-6:
            return self.ultimo
        d = t.dir
        if self._ref_prev and not d.ref:
            self.hist.clear()                  # el firmware reinició su historial (dir_init con el motor girando)
        if self.hist and t.t <= self.hist[-1][0]:
            self.reiniciar()                   # la hora retrocedió (otra corrida en el mismo log)
        z = r2 / i1 * 100.0
        seguros, dudosos = [], []
        for tt, zz in self.hist:
            edad = t.t - tt
            if REF_HASTA_S + MARGEN_BORDE_S <= edad <= REF_DESDE_S - MARGEN_BORDE_S:
                seguros.append(zz)
            elif REF_HASTA_S - MARGEN_BORDE_S <= edad <= REF_DESDE_S + MARGEN_BORDE_S:
                dudosos.append((zz, REF_HASTA_S <= edad <= REF_DESDE_S))
        self.hist = [(tt, zz) for tt, zz in self.hist if t.t - tt <= HIST_S][-(HIST_N - 1):] + [(t.t, z)]

        ref = dz = p_app = None
        # Sin referencia en el firmware (REF=0) su P no se actualiza: tampoco se dibuja la referencia
        if d.ref:
            ref = self._referencia(z, seguros, dudosos[:MAX_DUDOSOS], d.p)
            if ref is not None:
                dz = z - ref
                p_app = proyectar(dz)

        notas = []
        if not d.enclavada:
            self.base = None
            self._base_del_fw = False
            self._cond_base = 0.0
            self._visto_sin_alarma = True
        elif not self._c_prev and self._visto_sin_alarma:
            self.base = ref                    # confirmación vista: se congela la referencia, como el firmware
            if ref is None:
                notas.append("sin referencia recalculada al confirmar")
        elif self._c_prev or not self._visto_sin_alarma:
            # Desde el bloque siguiente a la confirmación, ML = |z - base| y PL = proyección: la base sale de lo
            # que reporta el firmware. Con ML ~ PL el despeje amplifica el redondeo a 3 decimales, así que se
            # conserva la del bloque mejor condicionado (mayor componente perpendicular relativa).
            # Si la alarma ya estaba enclavada al abrir la app, las dos soluciones son posibles: se toma una.
            if self.base is None:
                notas.append("alarma ya enclavada al empezar: de las dos bases posibles se dibuja una")
            cond = math.sqrt(max(0.0, d.ml * d.ml - d.pl * d.pl)) / d.ml if d.ml > 1e-6 else 1.0
            if not self._base_del_fw or cond > self._cond_base:
                self.base = self.base_desde_firmware(z, d.pl, d.ml, self.base)
                self._cond_base = cond
                self._base_del_fw = True
        self._c_prev = d.enclavada
        self._ref_prev = d.ref

        e = EstadoFirma(t=t.t, z=z, estela=list(self.hist), ref=ref, dz=dz, p_app=p_app, p_fw=d.p, ref_fw=d.ref,
                        enclavada=d.enclavada, sev=d.sev, ml_fw=d.ml, pl_fw=d.pl,
                        base=self.base if d.enclavada else None,
                        base_desconocida=d.enclavada and self.base is None,
                        v1=v1, v2=v2, i1=i1, r2=r2, notas=notas)
        self.ultimo = e
        return e
