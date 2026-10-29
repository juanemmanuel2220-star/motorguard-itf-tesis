"""
Registro de eventos de alarma a partir del campo DIR del firmware.

Una alarma empieza cuando C pasa de 0 a 1 (alarma confirmada y enclavada por el firmware) y termina
cuando C vuelve a 0, cuando el motor se apaga o cuando se pierde la conexión. El registro no decide
nada: solo anota lo que reporta el detector embebido validado.

CSV de salida (una fila por alarma al cerrarse, y una fila por mensaje del SSR o de conexión) en la
carpeta de registros de Ajustes (sistema/rutas.py), nunca en dataset/ ni en validacion_vivo/.
"""

import csv
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from motorguard_dashboard.telemetry.parser import NOMBRES_SEV, EventoSSR, Trama

MAX_EVENTOS_MEMORIA = 1000    # en memoria (como la tabla); el CSV guarda todos

COLUMNAS = [
    "tipo", "inicio", "t_inicio", "fin", "t_fin", "duracion_s",
    "sev_inicial", "sev_max", "ml_inicial", "ml_max", "p_inicial",
    "i1_A", "ia_A", "ib_A", "ic_A", "n_tramas", "motivo_fin", "detalle",
]


def _iso(t: Optional[float]) -> str:
    return datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S") if t is not None else ""


@dataclass
class EventoAlarma:
    id: int
    t_inicio: float
    sev_inicial: int
    ml_inicial: float
    p_inicial: float
    i1: float
    ia: float
    ib: float
    ic: float
    ya_activa: bool          # la sesión empezó con la alarma ya enclavada (inicio real desconocido)
    sev_max: int = 0
    ml_max: float = 0.0
    n_tramas: int = 0
    t_ultima: float = 0.0
    t_fin: Optional[float] = None
    motivo_fin: Optional[str] = None

    @property
    def abierta(self) -> bool:
        return self.t_fin is None

    def duracion(self, t_ahora: Optional[float] = None) -> Optional[float]:
        fin = self.t_fin if self.t_fin is not None else t_ahora
        return None if fin is None else fin - self.t_inicio


class RegistroAlarmas:
    def __init__(self, ruta_csv: Optional[str] = None):
        self.ruta_csv = ruta_csv
        self.eventos: List[EventoAlarma] = []
        self._n_eventos = 0
        self._abierta: Optional[EventoAlarma] = None
        self._hubo_trama = False
        self._ignorar_hasta = None
        self._f = None
        self._w = None
        if ruta_csv:
            os.makedirs(os.path.dirname(ruta_csv), exist_ok=True)
            self._f = open(ruta_csv, "w", newline="", encoding="utf-8")
            self._w = csv.writer(self._f)
            self._w.writerow(COLUMNAS)
            self._f.flush()

    @property
    def abierta(self) -> Optional[EventoAlarma]:
        return self._abierta

    # ------------------------------------------------------------------ entrada
    def procesar(self, obj) -> Optional[EventoAlarma]:
        """Procesa una línea parseada; devuelve la alarma que se abrió, actualizó o cerró (o None)."""
        if isinstance(obj, EventoSSR):
            if obj.tipo != "solicitud":
                self.anotar(obj.t, "SSR", obj.texto)
            return None
        if not isinstance(obj, Trama):
            return None

        if self._ignorar_hasta is not None:
            t_obj = obj.t if obj.t is not None else time.time()
            if obj.dir.enclavada and obj.motor != "OFF" and t_obj < self._ignorar_hasta:
                self._hubo_trama = True
                return None                    # aún llegan tramas de antes de la 'r'
            self._ignorar_hasta = None
        ev = self._abierta
        if ev is not None and (not obj.dir.enclavada or obj.motor == "OFF"):
            motivo = "motor apagado" if obj.motor == "OFF" else "liberada por el firmware"
            return self._cerrar(obj.t, motivo)
        if ev is None and obj.dir.enclavada and obj.motor != "OFF":
            self._n_eventos += 1
            ev = EventoAlarma(
                id=self._n_eventos, t_inicio=obj.t, sev_inicial=obj.dir.sev,
                ml_inicial=obj.dir.ml, p_inicial=obj.dir.p, i1=obj.i1,
                ia=obj.ia, ib=obj.ib, ic=obj.ic, ya_activa=not self._hubo_trama,
            )
            self.eventos.append(ev)
            if len(self.eventos) > MAX_EVENTOS_MEMORIA:
                del self.eventos[:-MAX_EVENTOS_MEMORIA]
            self._abierta = ev
        self._hubo_trama = True
        if ev is not None:
            ev.n_tramas += 1
            ev.sev_max = max(ev.sev_max, obj.dir.sev)
            ev.ml_max = max(ev.ml_max, obj.dir.ml)
            ev.t_ultima = obj.t
        return ev

    def liberacion_manual(self, t: float) -> Optional[EventoAlarma]:
        """El usuario envió 'r' (reinicio del detector) para liberar una alarma atascada. Se cierra la alarma abierta
        con ese motivo y, hasta la primera trama sin enclavamiento (o 10 s), no se abre otra: las tramas que el
        firmware envió antes de procesar la 'r' todavía la traen enclavada."""
        self.anotar(t, "REINICIO", "liberación manual del detector ('r') por el usuario")
        self._ignorar_hasta = t + 10.0
        if self._abierta is None:
            return None
        return self._cerrar(self._abierta.t_ultima, "liberada manualmente (r)")

    def conexion_perdida(self, t: float, detalle: str,
                         motivo: str = "conexión perdida (fin real desconocido)") -> Optional[EventoAlarma]:
        """La alarma abierta se cierra sin saber cuándo se liberó: se usa la última trama recibida."""
        self.anotar(t, "CONEXION", detalle)
        if self._abierta is None:
            return None
        return self._cerrar(self._abierta.t_ultima, motivo)

    def cerrar_sesion(self, t: float) -> Optional[EventoAlarma]:
        ev = None
        if self._abierta is not None:
            ev = self._cerrar(self._abierta.t_ultima, "sesión cerrada con la alarma activa")
        if self._f:
            self._f.close()
            self._f = None
            self._w = None
        return ev

    def anotar(self, t: Optional[float], tipo: str, detalle: str):
        if self._w:
            self._w.writerow([tipo, _iso(t), f"{t:.3f}" if t is not None else ""] + [""] * 14 + [detalle])
            self._f.flush()

    # ------------------------------------------------------------------ interno
    def _cerrar(self, t_fin: float, motivo: str) -> EventoAlarma:
        ev = self._abierta
        ev.t_fin = t_fin
        ev.motivo_fin = motivo
        self._abierta = None
        if self._w:
            self._w.writerow([
                "ALARMA", _iso(ev.t_inicio), f"{ev.t_inicio:.3f}", _iso(ev.t_fin), f"{ev.t_fin:.3f}",
                f"{ev.duracion():.1f}", NOMBRES_SEV[ev.sev_inicial], NOMBRES_SEV[ev.sev_max],
                f"{ev.ml_inicial:.3f}", f"{ev.ml_max:.3f}", f"{ev.p_inicial:.3f}",
                f"{ev.i1:.4f}", f"{ev.ia:.2f}", f"{ev.ib:.2f}", f"{ev.ic:.2f}", ev.n_tramas, motivo,
                "alarma ya activa al iniciar la sesión" if ev.ya_activa else "",
            ])
            self._f.flush()
        return ev
