"""
Captura de pares entrelazados SANO/FALLA: el protocolo de ~/captura_dataset_multiclase.py (v4.2) llevado a
la app como máquina de estados (sin sleep: avanza con cada trama y con un tic de 100 ms).

Igual que el script:
- SANO: primera trama con Motor ON y SSR OFF recibida >= 'cooldown' s después del último apagado.
  Filtro 1: se compara con la mediana de los últimos SANO aceptados (tol_i); 4 rechazos seguidos reinician
  la referencia (cambio real de carga o temperatura).
- FALLA: el ON se fecha con la confirmación del firmware ("[DEBUG SSR] Exito"); se juntan las tramas con
  SSR encendido, t_desde_on >= t_min_on y recibidas antes de terminar el pulso; la FALLA es la última.
  Filtro 2: las dos últimas tramas del pulso deben ser consistentes (tol_i y tol_de2).
- Se acepta el par si delta_e2 (DE2 del firmware) >= umbral_e2 (0 por defecto: sin filtro).
- Mismos archivos: CSV (COLS), _descartes.csv, _serial.log y _meta.json.

Distinto del script, por los bloqueos de la app (decisión del 11-oct-2026):
- Cada '1' pasa por inyeccion/control.py: serie armada con disparo externo y confirmación humana por
  bloque de hasta 10 pulsos; entre bloques la captura espera a que la persona confirme de nuevo.
- El enfriamiento (cooldown) es >= 15 s (>= 20 s con SEVERA); el script permitía 8 s.
- Si un pulso se interrumpe (rechazo del firmware, PARO, motor apagado, conexión perdida), la captura
  se pausa en vez de reintentar sola; el motivo queda en el _meta.json.
- El _serial.log tiene las líneas que la app reconoce (tramas, [DEBUG SSR], mensajes); la copia completa
  del puerto, con los comandos enviados, es el registro crudo de la sesión (su ruta va en el _meta.json).
"""

import csv
import json
import math
import os
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from motorguard_dashboard.adquisicion.formato import (
    CARGAS_MAP, CLASES, COLS, buscar_para_continuar, carpeta_protegida, commit_firmware, fases_fuera,
    fila_dataset, nombre_base, pares_existentes, parse_line,
)
from motorguard_dashboard.inyeccion.control import (
    MAX_PULSOS_SERIE, PULSO_MAX_S, PULSO_MIN_S, ControlInyeccion, Confirmacion, PlanSerie, enfriamiento_minimo,
)
from motorguard_dashboard.telemetry.parser import Trama

MAX_PARES = 1000
MARGEN_VENTANA_S = 1.5     # la ventana de 4096 muestras (1.70 s) debe caber en el pulso (validación del script)
LINEAS_CONSOLA = 500


@dataclass
class ParametrosPares:
    clase: int                    # 1 LEVE, 2 INTER, 3 SEVERA
    carga: str                    # '0%', '25%', '50%', '75%'
    pares: int = 75
    duracion_pulso: float = 7.0
    t_min_on: float = 3.0
    cooldown: float = 15.0
    umbral_e2: float = 0.0
    tol_i: float = 0.06
    tol_de2: float = 0.35
    nota: str = ""
    continuar: bool = False

    @property
    def label(self) -> str:
        return CLASES[self.clase]


def validar_parametros(p: ParametrosPares) -> Optional[str]:
    """Motivo por el que los parámetros no son válidos, o None."""
    if p.clase not in (1, 2, 3):
        return "elige la clase (LEVE, INTER o SEVERA)"
    if p.carga not in CARGAS_MAP:
        return "elige la carga"
    if not 1 <= p.pares <= MAX_PARES:
        return f"los pares deben estar entre 1 y {MAX_PARES}"
    if not PULSO_MIN_S <= p.duracion_pulso <= PULSO_MAX_S:
        return f"el pulso debe durar entre {PULSO_MIN_S:g} y {PULSO_MAX_S:g} s"
    if p.t_min_on < 0:
        return "t_min_on no puede ser negativo"
    if p.duracion_pulso < p.t_min_on + MARGEN_VENTANA_S:
        return f"el pulso debe durar al menos t_min_on + {MARGEN_VENTANA_S:g} s"
    if p.cooldown < enfriamiento_minimo(p.label):
        return f"con taps {p.label} el enfriamiento debe ser de al menos {enfriamiento_minimo(p.label):g} s"
    if p.tol_i <= 0 or p.tol_de2 <= 0:
        return "las tolerancias deben ser positivas"
    if p.umbral_e2 < 0:
        return "el umbral de DE2 no puede ser negativo"
    return None


class CapturaPares:
    ESPERA_CONFIRMACION, ESPERA_SANO, PULSO, PAUSADA, TERMINADA = (
        "ESPERA_CONFIRMACION", "ESPERA_SANO", "PULSO", "PAUSADA", "TERMINADA")

    def __init__(self, control: ControlInyeccion, params: ParametrosPares, carpeta: str, ahora: float,
                 origen: str = "", puerto: str = "", crudo_sesion: str = ""):
        error = validar_parametros(params)
        if error:
            raise ValueError(error)
        prot = carpeta_protegida(carpeta)
        if prot:
            raise ValueError(f"la app no escribe en {prot} (datos de la tesis): elige otra carpeta")
        self.control = control
        self.prm = params
        self.carpeta = carpeta
        self.consola = deque(maxlen=LINEAS_CONSOLA)
        self.n_dichas = 0                         # líneas emitidas en total (la interfaz muestra las nuevas)
        self.mensaje = ""
        os.makedirs(carpeta, exist_ok=True)

        ruta = None
        if params.continuar:
            ruta, msg = buscar_para_continuar(carpeta, params.label, params.carga)
            self._decir(f"[{'REANUDAR' if ruta else 'NUEVO'}] {msg}")
        if not ruta:
            ruta = os.path.join(carpeta, nombre_base(params.label, params.carga, datetime.fromtimestamp(ahora)))
            if not params.continuar:
                self._decir(f"[NUEVO] Creando archivo: {os.path.basename(ruta)}")
        self.ruta_csv = ruta
        self.p, corregido = pares_existentes(ruta)
        if corregido:
            self._decir("[CORRECCIÓN] Fila huérfana detectada: se descartó la última muestra")
        if self.p > 0:
            self._decir(f"[REANUDANDO] {self.p} pares ya registrados; se continúa hasta {params.pares}")

        existe = os.path.exists(ruta) and os.path.getsize(ruta) > 0
        self._f = open(ruta, 'a', newline='')
        self._w = csv.writer(self._f)
        if not existe:
            self._w.writerow(COLS)
            self._f.flush()
        self.ruta_descartes = ruta.replace('.csv', '_descartes.csv')
        nuevo_desc = not os.path.exists(self.ruta_descartes)
        self._f_desc = open(self.ruta_descartes, 'a', newline='')
        self._w_desc = csv.writer(self._f_desc)
        if nuevo_desc:
            self._w_desc.writerow(['timestamp', 'clase', 'carga', 'motivo', 'detalle'])
            self._f_desc.flush()
        self._f_crudo = open(ruta.replace('.csv', '_serial.log'), 'a', buffering=1)

        self.ruta_meta = ruta.replace('.csv', '_meta.json')
        try:
            with open(self.ruta_meta) as fm:
                self.meta = json.load(fm)
        except (OSError, ValueError):
            self.meta = {'sesiones': []}
        parametros = {'clase': params.clase, 'carga': params.carga, 'pares': params.pares, 'port': puerto,
                      'continuar': params.continuar, 'duracion_pulso': params.duracion_pulso,
                      't_min_on': params.t_min_on, 'cooldown': params.cooldown, 'umbral_e2': params.umbral_e2,
                      'nota': params.nota, 'tol_i': params.tol_i, 'tol_de2': params.tol_de2}
        self.sesion = {'inicio': self._hora(ahora), 'clase': params.label, 'carga': params.carga,
                       'pares_previos': self.p, 'firmware': commit_firmware(), 'nota': params.nota,
                       'parametros': parametros, 'origen': origen,
                       'protocolo': (f"captura_dataset_multiclase.py v4.2 en la app: bloques de hasta "
                                     f"{MAX_PULSOS_SERIE} pulsos con confirmación humana; pausa automática si "
                                     "un pulso se interrumpe"),
                       'registro_crudo_sesion': crudo_sesion, 'bloques': 0, 'pausas': []}
        self.meta['sesiones'].append(self.sesion)
        self._guardar_meta()

        self.n_desc = 0
        self.sanos_ref: List[dict] = []
        self.rechazos_sano = 0
        self.t_off: Optional[float] = None        # último apagado (o el inicio, como el ssr_off del script)
        self._t_sano_desde = math.inf
        self._pulso = None                        # Pulso del control en curso
        self._d_sano: Optional[dict] = None
        self._t_sano_off = 0.0
        self._fallas: List[dict] = []
        self._pulsos_bloque = 0
        self._n_bloque = 0
        self.ultimo_par: Optional[dict] = None
        self.estado = self.TERMINADA if self.p >= params.pares else self.ESPERA_CONFIRMACION
        if self.estado == self.TERMINADA:
            self._decir("[INFO] El objetivo ya fue completado en este archivo.")
            self._cerrar_archivos(ahora)

    # ================================================================ consultas
    @property
    def activa(self) -> bool:
        """Mientras haya una captura abierta (aunque esté pausada) el panel de inyección manual se bloquea."""
        return self.estado != self.TERMINADA

    @property
    def espera_confirmacion(self) -> bool:
        return self.estado in (self.ESPERA_CONFIRMACION, self.PAUSADA)

    def plan_bloque(self) -> PlanSerie:
        n = max(1, min(MAX_PULSOS_SERIE, self.prm.pares - self.p))
        return PlanSerie(self.prm.label, self.prm.duracion_pulso, n, self.prm.cooldown, externo=True)

    # ================================================================ órdenes
    def armar(self, conf: Confirmacion, ahora: float) -> List[str]:
        """Arma el bloque siguiente con la confirmación humana (la emite la interfaz tras el diálogo)."""
        if not self.espera_confirmacion:
            self.mensaje = "la captura no está esperando confirmación"
            return []
        cmds = self.control.iniciar_serie(conf, ahora)
        if not self.control.armada:
            self.mensaje = f"no se armó el bloque: {self.control.mensaje}"
            return cmds
        if 'previo' not in self.sesion:
            self.t_off = ahora
            t = self.control.ultima_trama
            d0 = parse_line(t.texto, t.t) if t is not None else None
            if d0:
                self.sesion['previo'] = {k: d0[k] for k in ('ia', 'ib', 'ic', 'va', 'vb', 'vc', 'u2v', 'u2i', 'de2_fw')}
                self._decir(f"[PREVIO] I = {d0['ia']:.2f}/{d0['ib']:.2f}/{d0['ic']:.2f} A | "
                            f"V = {d0['va']:.1f}/{d0['vb']:.1f}/{d0['vc']:.1f} V | U2V={d0['u2v']:.2f}% "
                            f"DE2={d0['de2_fw']:.2f}pp")
        if self.control.t_ultimo_apagado is not None:
            self.t_off = max(self.t_off or 0.0, self.control.t_ultimo_apagado)
        self._t_sano_desde = self.t_off + self.prm.cooldown
        self._pulsos_bloque = 0
        self._n_bloque = conf.plan.n_pulsos
        self.sesion['bloques'] += 1
        self._guardar_meta()
        self.estado = self.ESPERA_SANO
        self.mensaje = f"bloque {self.sesion['bloques']} armado ({self._n_bloque} pulsos): esperando trama SANO"
        self._decir(f"[BLOQUE {self.sesion['bloques']}] confirmado: hasta {self._n_bloque} pulsos de "
                    f"{self.prm.duracion_pulso:g} s, pausa {self.prm.cooldown:g} s")
        return cmds

    def pausar(self, ahora: float, motivo: str = "pausa pedida por el usuario") -> List[str]:
        """Detiene la captura sin cerrarla: apaga el SSR si hace falta y descarta el par a medias."""
        cmds: List[str] = []
        if self.estado in (self.ESPERA_SANO, self.PULSO):
            if self.control.pulso_actual is not None:
                cmds = self.control.paro(ahora)
            else:
                self.control.cancelar_armada("serie armada cancelada: captura en pausa")
            self._pulso = None
            self._marcar_pausa(ahora, motivo)
        return cmds

    def terminar(self, ahora: float, motivo: str = "terminada por el usuario") -> List[str]:
        if self.estado == self.TERMINADA:
            return []
        cmds = self.pausar(ahora, motivo) if self.estado in (self.ESPERA_SANO, self.PULSO) else []
        self.estado = self.TERMINADA
        self.mensaje = f"captura terminada ({motivo}): {self.p} pares"
        self._decir(f"[FIN] {motivo}. Total: {self.p} pares ({self.p * 2} muestras); descartes en esta sesión: "
                    f"{self.n_desc} ({100 * self.n_desc / max(1, self.n_desc + self.p - self.sesion['pares_previos']):.0f} %)")
        self._cerrar_archivos(ahora, motivo)
        return cmds

    # ================================================================ entradas
    def registrar_linea(self, t: float, texto: str):
        """Copia de una línea recibida en el _serial.log (mismo formato que el script)."""
        if self.estado != self.TERMINADA and texto:
            self._f_crudo.write(f"{t:.3f} {texto}\n")

    def procesar(self, obj, ahora: float) -> List[str]:
        if self.estado == self.TERMINADA:
            return []
        texto = getattr(obj, "texto", "")
        if obj.t is not None:
            self.registrar_linea(obj.t, texto)
        if not isinstance(obj, Trama):
            return []
        d = parse_line(texto, obj.t)
        if d is None:
            return []
        if self.estado == self.ESPERA_SANO and self.control.armada and d['t'] >= self._t_sano_desde \
                and d['motor'] == 'ON' and d['ssr'] == 'OFF':
            return self._evaluar_sano(d, ahora)
        if self.estado == self.PULSO:
            p = self._pulso
            if p.t_encendido is not None and d['ssr'] != 'OFF' and d['t'] - p.t_encendido >= self.prm.t_min_on \
                    and d['t'] < p.t_encendido + p.duracion:
                # Solo tramas cuya ventana de 1.70 s cae completa dentro del pulso
                self._fallas.append(d)
        return []

    def tic(self, ahora: float) -> List[str]:
        if self.estado == self.PULSO and self._pulso is not None and self._pulso.t_apagado is not None:
            return self._fin_pulso(ahora)
        if self.estado == self.ESPERA_SANO and not self.control.armada:
            # El control canceló la serie armada (PARO, 60 s sin pulso, conexión perdida...)
            self._marcar_pausa(ahora, self.control.mensaje or "la serie armada se canceló")
        return []

    def cerrar(self, ahora: float) -> List[str]:
        """Al cerrar la app."""
        return self.terminar(ahora, "app cerrada")

    # ================================================================ interno
    def _evaluar_sano(self, d: dict, ahora: float) -> List[str]:
        self._t_sano_desde = d['t'] + 1e-6      # si no se usa esta trama, la siguiente ya es candidata
        # Filtro 1: el SANO debe parecerse a los SANO recientes (detecta saltos de contacto)
        if len(self.sanos_ref) >= 3:
            ref = {k: sorted(x[k] for x in self.sanos_ref)[len(self.sanos_ref) // 2] for k in ('ia', 'ib', 'ic')}
            malas = fases_fuera(ref, d, self.prm.tol_i)
            if malas:
                self.rechazos_sano += 1
                if self.rechazos_sano >= 4:
                    # Cambio real y sostenido de carga o temperatura: se adopta el nivel nuevo
                    self._decir(f"  [FILTRO] 4 SANO seguidos fuera de la referencia: se reinicia la referencia "
                                f"({'; '.join(malas)})")
                    self.sanos_ref = [d]
                    self.rechazos_sano = 0
                else:
                    self._descartar(ahora, 'SANO inestable', '; '.join(malas))
                return []
        self.rechazos_sano = 0
        cmds = self.control.disparar(ahora)
        if "1" not in cmds:
            self.mensaje = f"SANO aceptado pero el pulso no salió: {self.control.mensaje}"
            return cmds
        self._pulso = self.control.pulso_actual
        self._d_sano = d
        self._t_sano_off = d['t'] - self.t_off
        self._fallas = []
        self._pulsos_bloque += 1
        self.estado = self.PULSO
        self.mensaje = f"par {self.p + 1}/{self.prm.pares}: pulso {self._pulsos_bloque}/{self._n_bloque} del bloque"
        return cmds

    def _fin_pulso(self, ahora: float) -> List[str]:
        p, self._pulso = self._pulso, None
        self.t_off = p.t_apagado
        self._t_sano_desde = self.t_off + self.prm.cooldown
        if p.resultado != "completo":
            self._marcar_pausa(ahora, f"pulso interrumpido: {p.resultado}"
                               + (f" ({p.motivo_rechazo})" if p.motivo_rechazo else ""))
            return []
        fallas, d_sano = self._fallas, self._d_sano
        tol = self.prm
        if len(fallas) < 2:
            # Filtro 2: las tramas dentro del mismo pulso deben ser consistentes
            self._descartar(ahora, 'Pulso con menos de 2 tramas completas',
                            f'{len(fallas)} trama(s) con t_desde_on >= {tol.t_min_on}s')
        else:
            a_, b_ = fallas[-2], fallas[-1]
            malas = fases_fuera(a_, b_, tol.tol_i)
            if a_['de2_fw'] == a_['de2_fw'] and abs(a_['de2_fw'] - b_['de2_fw']) > tol.tol_de2:
                malas.append(f"DE2 {a_['de2_fw']:.2f}->{b_['de2_fw']:.2f}pp")
            if malas:
                self._descartar(ahora, 'Salto dentro del pulso', '; '.join(malas))
            else:
                d_falla = fallas[-1]
                # Desplazamiento fasorial del firmware; con firmware antiguo, diferencia escalar de e2
                salto_e2 = d_falla['de2_fw'] if d_falla['de2_fw'] == d_falla['de2_fw'] else d_falla['e2'] - d_sano['e2']
                if salto_e2 >= tol.umbral_e2:
                    self._registrar_par(d_sano, d_falla, p.t_encendido, salto_e2, ahora)
                else:
                    self._descartar(ahora, 'Salto insuficiente', f'DE2={salto_e2:+.2f}pp < {tol.umbral_e2}')
        return self._siguiente(ahora)

    def _registrar_par(self, d_sano, d_falla, t_on, salto_e2, ahora):
        carga = CARGAS_MAP[self.prm.carga]
        sello = self._hora(ahora)
        t_falla_on = d_falla['t'] - t_on
        self._w.writerow(fila_dataset(d_sano, 0, carga, self.p * 2 + 1, -1.0, self._t_sano_off, 0.0, sello))
        self._w.writerow(fila_dataset(d_falla, self.prm.clase, carga, self.p * 2 + 2, t_falla_on, -1.0, salto_e2, sello))
        self._f.flush()
        n, lbl = self.prm.pares, self.prm.label
        self._decir(f"[{self.p + 1:3d}/{n}] SANO  -> e2={d_sano['e2']:4.2f}% | U2V={d_sano['u2v']:4.2f}% | "
                    f"I={d_sano['ic']:4.2f}A | t_off={self._t_sano_off:4.1f}s")
        self._decir(f"[{self.p + 1:3d}/{n}] {lbl:<5} -> e2={d_falla['e2']:4.2f}% | U2V={d_falla['u2v']:4.2f}% | "
                    f"I={d_falla['ic']:4.2f}A | t_on={t_falla_on:4.1f}s (Δe2=+{salto_e2:.2f}pp)")
        self.p += 1
        self.sanos_ref = (self.sanos_ref + [d_sano])[-5:]
        self.ultimo_par = {'n': self.p, 'e2_sano': d_sano['e2'], 'i_sano': d_sano['ic'], 't_off': self._t_sano_off,
                           'e2_falla': d_falla['e2'], 'i_falla': d_falla['ic'], 't_on': t_falla_on,
                           'delta_e2': salto_e2}

    def _siguiente(self, ahora: float) -> List[str]:
        if self.p >= self.prm.pares:
            self.control.cancelar_armada("captura completada: serie armada cancelada")
            return self.terminar(ahora, "captura completada")
        if self.control.armada:
            self.estado = self.ESPERA_SANO
        elif self._pulsos_bloque >= self._n_bloque:
            self.estado = self.ESPERA_CONFIRMACION
            self.mensaje = (f"bloque {self.sesion['bloques']} terminado: revisa la resistencia y el lazo, "
                            "y confirma el bloque siguiente")
            self._decir(f"[BLOQUE {self.sesion['bloques']}] terminado; {self.p}/{self.prm.pares} pares")
        else:
            self._marcar_pausa(ahora, self.control.mensaje or "la serie armada se canceló")
        return []

    def _marcar_pausa(self, ahora: float, motivo: str):
        self.estado = self.PAUSADA
        self.mensaje = f"captura en pausa: {motivo}"
        self.sesion['pausas'].append({'hora': self._hora(ahora), 'pares': self.p, 'motivo': motivo})
        self._guardar_meta()
        self._decir(f"[PAUSA] {motivo}")

    def _descartar(self, ahora: float, motivo: str, detalle: str):
        self.n_desc += 1
        self._w_desc.writerow([self._hora(ahora), self.prm.clase, self.prm.carga, motivo, detalle])
        self._f_desc.flush()
        self._decir(f"[{self.p + 1:3d}/{self.prm.pares}] {self.prm.label:<5} -> [DESCARTADO] {motivo}: {detalle}")

    def _cerrar_archivos(self, ahora: float, motivo: str = ""):
        self.sesion.update({'fin': self._hora(ahora), 'pares_total': self.p, 'descartes': self.n_desc})
        if motivo:
            self.sesion['motivo_fin'] = motivo
        self._guardar_meta()
        for f in (self._f, self._f_desc, self._f_crudo):
            try:
                f.close()
            except OSError:
                pass

    def _guardar_meta(self):
        tmp = self.ruta_meta + ".tmp"
        with open(tmp, 'w') as fm:
            json.dump(self.meta, fm, indent=2, ensure_ascii=False)
        os.replace(tmp, self.ruta_meta)

    def _decir(self, texto: str):
        self.consola.append(texto)
        self.n_dichas += 1

    @staticmethod
    def _hora(t: float) -> str:
        return datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M:%S')
