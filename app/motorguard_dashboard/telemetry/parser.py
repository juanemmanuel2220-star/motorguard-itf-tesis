"""
Parser de la telemetría serie del firmware PRUEBA_MODELO_1 (commit 299a943).

Formato de referencia: PRUEBA_MODELO_1.ino, Serial.printf de la trama [MCSA] (l. 1419)
y mensajes [DEBUG SSR] de ssrOn()/ssrOff() (l. 780-818).

Una trama [MCSA] solo se acepta completa: debe terminar con el campo DIR íntegro.
Una línea cortada por el puerto serie se descarta en lugar de rellenarse con valores por defecto.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple, Union

NOMBRES_SEV = ("SANO", "LEVE", "INTER", "SEVERA")

# Marca de tiempo que anteponen los scripts de captura: "1791580418.950 " (Unix) o "6.78s " (relativa)
_RE_MARCA = re.compile(r"^(\d+(?:\.\d+)?)(s?)\s+(?=\[)")

_RE_MCSA = re.compile(
    r"^\[MCSA\] Motor:(OFF|WARMUP|ON) \|"
    r".*?\| VA=(-?[\d.]+)V VB=(-?[\d.]+)V VC=(-?[\d.]+)V \| IA=(-?[\d.]+)A IB=(-?[\d.]+)A IC=(-?[\d.]+)A \|"
    r".*?\| (SANO|LEVE|INTER|SEVERA|WARMUP) \| SSR:(\S+)\s*\|"
    r".*?\| RAW: R2=\S+ I1=(-?[\d.]+) "
    # P, ML y PL se imprimen con %.3f: exigir los 3 decimales detecta también un corte en el último dígito
    r".*?\| DIR: P=(-?\d+\.\d{3}) R=(\d+) C=([01]) REF=([01]) CUSUM=(-?\d+) SEV=([0-3]) "
    r"ML=(-?\d+\.\d{3}) PL=(-?\d+\.\d{3})\s*$"
)

_RE_SSR_SOLICITUD = re.compile(r"^\[DEBUG SSR\] Solicitud F(\d) \| I_rms=([\d.]+)A \| Cooldown=(\d+) ms")
_RE_SSR_EXITO = re.compile(r"^\[DEBUG SSR\] Exito: GPIO (\d+) puesto en (HIGH|LOW)")
_RE_SSR_APAGADO = re.compile(r"^\[DEBUG SSR\] Apagado\. Forzado: ([01]) \| T_ON: (\d+) ms")
_RE_SSR_RECHAZO = re.compile(r"^\[DEBUG SSR\] Rechazado: (.+?)\.?\s*$")


@dataclass(frozen=True)
class CampoDir:
    """Campo DIR del detector direccional embebido (detector_dir.h)."""
    p: float            # proyección de la firma sobre la dirección de falla (pp de |I1|)
    racha: int          # bloques consecutivos con P sobre el umbral
    enclavada: bool     # C=1: alarma confirmada y enclavada
    ref: bool           # REF=1: hay referencia suficiente
    cusum: int          # decisión del detector CUSUM anterior (solo informativa)
    sev: int            # 0 sano, 1 LEVE, 2 INTER, 3 SEVERA (enclavada)
    ml: float           # magnitud de la firma contra la base congelada (pp)
    pl: float           # proyección contra la base congelada (pp)

    @property
    def nombre_sev(self) -> str:
        return NOMBRES_SEV[self.sev]


@dataclass(frozen=True)
class Trama:
    """Una trama [MCSA] completa (un bloque de 4096 muestras, ~1.7 s)."""
    t: Optional[float]  # marca de tiempo del archivo (None si la línea viene directo del puerto)
    motor: str          # OFF / WARMUP / ON
    decision: str       # SANO / LEVE / INTER / SEVERA / WARMUP
    ssr: str            # OFF / F1(LEVE) / ...
    va: float
    vb: float
    vc: float
    ia: float
    ib: float
    ic: float
    i1: float           # |I1| (A pico), referencia de la carga
    dir: CampoDir
    texto: str = field(default="", repr=False, compare=False)  # línea original (sin marca de tiempo)


@dataclass(frozen=True)
class EventoSSR:
    """Mensaje [DEBUG SSR] del firmware."""
    t: Optional[float]
    tipo: str                       # 'solicitud' | 'encendido' | 'apagado' | 'rechazado'
    texto: str
    forzado: Optional[bool] = None  # solo en 'apagado' (1 = corte por watchdog/sobrecorriente)
    t_on_ms: Optional[int] = None   # solo en 'apagado'
    motivo: Optional[str] = None    # solo en 'rechazado'


@dataclass(frozen=True)
class MensajeFirmware:
    """Otra línea del firmware que empieza con '[' (Zero SSR, RED, bitácora, etc.)."""
    t: Optional[float]
    texto: str


Linea = Union[Trama, EventoSSR, MensajeFirmware]


def separar_marca_tiempo(linea: str) -> Tuple[Optional[float], str]:
    """Quita la marca de tiempo que agregan los scripts de captura, si la hay."""
    m = _RE_MARCA.match(linea)
    if not m:
        return None, linea
    return float(m.group(1)), linea[m.end():]


_RE_CAMPO = re.compile(r"(?<![\w.])([A-Za-z][A-Za-z0-9_]*)=(-?\d+(?:\.\d+)?)")
_RE_FREC = re.compile(r"\b(A55|A65)=-?[\d.]+\((-?[\d.]+)Hz\)")


def campos_trama(t: "Trama") -> Dict[str, float]:
    """Todos los campos numéricos KEY=valor de la trama tal como los imprime el firmware
    (Afund, A55, P_RF, U2V, E2, L2sM, S, Pcal, DE2, ANG, ...). Para A55/A65 agrega f55/f65 (Hz).
    Si un nombre se repite, se conserva el primero (en la trama 299a943 no hay repetidos)."""
    campos: Dict[str, float] = {}
    for k, v in _RE_CAMPO.findall(t.texto):
        campos.setdefault(k, float(v))
    for k, f in _RE_FREC.findall(t.texto):
        campos["f" + k[1:]] = float(f)
    return campos


def parsear_linea(linea: str) -> Optional[Linea]:
    """Convierte una línea en Trama, EventoSSR o MensajeFirmware; None si no se reconoce."""
    t, texto = separar_marca_tiempo(linea.strip())
    if not texto.startswith("["):
        return None

    if texto.startswith("[MCSA]"):
        m = _RE_MCSA.match(texto)
        if not m:
            return None
        g = m.groups()
        return Trama(
            t=t, motor=g[0], decision=g[7], ssr=g[8],
            va=float(g[1]), vb=float(g[2]), vc=float(g[3]),
            ia=float(g[4]), ib=float(g[5]), ic=float(g[6]),
            i1=float(g[9]),
            dir=CampoDir(
                p=float(g[10]), racha=int(g[11]), enclavada=g[12] == "1", ref=g[13] == "1",
                cusum=int(g[14]), sev=int(g[15]), ml=float(g[16]), pl=float(g[17]),
            ),
            texto=texto,
        )

    if texto.startswith("[DEBUG SSR]"):
        if _RE_SSR_SOLICITUD.match(texto):
            return EventoSSR(t=t, tipo="solicitud", texto=texto)
        if _RE_SSR_EXITO.match(texto):
            return EventoSSR(t=t, tipo="encendido", texto=texto)
        m = _RE_SSR_APAGADO.match(texto)
        if m:
            return EventoSSR(t=t, tipo="apagado", texto=texto,
                             forzado=m.group(1) == "1", t_on_ms=int(m.group(2)))
        m = _RE_SSR_RECHAZO.match(texto)
        if m:
            return EventoSSR(t=t, tipo="rechazado", texto=texto, motivo=m.group(1))
        return MensajeFirmware(t=t, texto=texto)

    return MensajeFirmware(t=t, texto=texto)
