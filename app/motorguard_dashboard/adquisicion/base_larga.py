"""
Prueba larga sin falla (tasa de falsas alarmas del detector embebido): el protocolo y las métricas de
~/prueba_larga_sin_falla.py llevados a la app, con las mismas regex, columnas y resumen.

- Motor sano: nunca se envía '1'. Se envía '0' al iniciar, cada 60 s y al terminar (como el script).
- Exposición = tiempo con Motor:ON (huecos de más de 5 s entre bloques no cuentan).
- Eventos de falsa alarma = flancos C 0 -> 1; tasa por hora con límite superior al 95 % (Poisson).
- Escalón de carga = cambio de |I1| > 3 % entre bloques ON consecutivos; alarma en los 30 s siguientes.
- Alarmas atascadas = eventos de más de 30 s.
Archivos: larga_<fecha>_tramas.csv, _serial.log y _resumen.json en la carpeta elegida.
"""

import csv
import json
import math
import os
import re
from collections import deque
from datetime import datetime
from typing import List, Optional

from motorguard_dashboard import FIRMWARE_COMPATIBLE
from motorguard_dashboard.adquisicion.formato import carpeta_protegida

RE_TRAMA = re.compile(r"\[MCSA\]\s+Motor:(\w+).*?IA=([\d.]+)A\s+IB=([\d.]+)A\s+IC=([\d.]+)A")
RE_RAW = re.compile(r"RAW:\s+R2=([-\d.]+),([-\d.]+)\s+I1=([-\d.]+)")
RE_DIR = re.compile(r"DIR:\s+P=([-\d.]+)\s+R=(\d+)\s+C=(\d)\s+REF=(\d)\s+CUSUM=(\d)\s+SEV=(\d)\s+ML=([-\d.]+)\s+PL=([-\d.]+)")
CLASES = ['SANO', 'LEVE', 'INTER', 'SEVERA']
ESCALON_REL = 0.03
VENTANA_ESCALON_S = 30.0
ATASCADA_S = 30.0
SEGURO_S = 60.0
LINEAS_CONSOLA = 500


def chi2_sup_poisson(k, conf=0.95):
    """Límite superior exacto de una tasa Poisson con k eventos (en conteos)."""
    if k == 0:
        return -math.log(1 - conf)
    lo, hi = float(k), float(k) * 5 + 10
    for _ in range(100):
        mu = 0.5 * (lo + hi)
        p = sum(math.exp(-mu) * mu ** i / math.factorial(i) for i in range(k + 1))
        if p > 1 - conf:
            lo = mu
        else:
            hi = mu
    return 0.5 * (lo + hi)


def validar(minutos: float, max_horas: float) -> Optional[str]:
    if not 1 <= minutos <= 24 * 60:
        return "la exposición objetivo debe estar entre 1 min y 24 h"
    if not 0.1 <= max_horas <= 48:
        return "el tiempo máximo debe estar entre 0.1 y 48 h"
    if max_horas * 60 < minutos:
        return "el tiempo máximo no alcanza para la exposición objetivo"
    return None


class PruebaLarga:
    def __init__(self, carpeta: str, ahora: float, minutos: float = 90.0, max_horas: float = 3.0, nota: str = "",
                 origen: str = "", crudo_sesion: str = ""):
        error = validar(minutos, max_horas)
        if error:
            raise ValueError(error)
        prot = carpeta_protegida(carpeta)
        if prot:
            raise ValueError(f"la app no escribe en {prot} (datos de la tesis): elige otra carpeta")
        os.makedirs(carpeta, exist_ok=True)
        self.minutos, self.max_horas, self.nota = minutos, max_horas, nota
        self.origen, self.crudo_sesion = origen, crudo_sesion
        self.base = os.path.join(carpeta, f"larga_{datetime.fromtimestamp(ahora).strftime('%Y%m%d_%H%M')}")
        self._f_tr = open(self.base + '_tramas.csv', 'w', newline='')
        self._w = csv.writer(self._f_tr)
        self._w.writerow(['t', 'motor', 'ia', 'ib', 'ic', 'i1', 'proy', 'racha', 'alarma', 'sev', 'ml', 'pl',
                          'cusum', 'escalon'])
        self._f_ser = open(self.base + '_serial.log', 'w', buffering=1)
        self.consola = deque(maxlen=LINEAS_CONSOLA)
        self.n_dichas = 0                         # líneas emitidas en total (la interfaz muestra las nuevas)
        self.t_ini = ahora
        self.expo = 0.0
        self.prev = None
        self.eventos: List[dict] = []
        self.escalones: List[dict] = []
        self.evento: Optional[dict] = None
        self.ult_seguro: Optional[float] = None   # None: '0' pendiente de enviar al iniciar
        self.proximo_reporte = 300.0
        self.activa = True
        self.resumen: Optional[dict] = None
        self.motivo_fin = ""
        self._decir(f"PRUEBA LARGA SIN FALLA: objetivo {minutos:.0f} min con motor encendido (máx. {max_horas:g} h). "
                    "Cambia la carga cada ~10 min (0->25->50->75->50->25...) sin tocar el lazo.")

    @property
    def n_eventos(self) -> int:
        return len(self.eventos) + (1 if self.evento else 0)

    # ================================================================ entradas
    def procesar(self, obj, ahora: float) -> List[str]:
        if not self.activa or obj.t is None:
            return []
        raw, t = getattr(obj, "texto", ""), obj.t
        if not raw:
            return []
        self._f_ser.write(f"{t:.3f} {raw}\n")
        m, r, d = RE_TRAMA.search(raw), RE_RAW.search(raw), RE_DIR.search(raw)
        if not (m and r and d):
            return []
        motor = m.group(1)
        i1 = float(r.group(3))
        proy, racha, alarma, sev = float(d.group(1)), int(d.group(2)), int(d.group(3)), int(d.group(6))
        esc = 0
        if motor != 'ON':
            self.prev = None
            if self.evento:
                self.evento['t_fin'] = t
                self.evento['cortado_por_motor'] = True
                self.eventos.append(self.evento)
                self.evento = None
            self._w.writerow([f"{t:.3f}", motor, m.group(2), m.group(3), m.group(4), i1, proy, racha, alarma, sev,
                              d.group(7), d.group(8), d.group(5), 0])
            return self._revisar_fin(t)
        if self.prev is not None:
            dt = t - self.prev[0]
            if dt < 5.0:
                self.expo += dt
            if self.prev[1] > 1e-6 and abs(i1 - self.prev[1]) / self.prev[1] > ESCALON_REL:
                esc = 1
                self.escalones.append({'t': t, 'de': self.prev[1], 'a': i1})
                self._decir(f"[{(t - self.t_ini) / 60:6.1f} min] escalón de carga: |I1| {self.prev[1]:.2f} -> {i1:.2f} A")
        if alarma and self.evento is None:
            ult_esc = [e for e in self.escalones if 0 <= t - e['t'] <= VENTANA_ESCALON_S]
            self.evento = {'t_ini': t, 'sev_max': sev, 'tras_escalon': bool(ult_esc)}
            self._decir(f"[{(t - self.t_ini) / 60:6.1f} min] <<< FALSA ALARMA {CLASES[sev]} (proy {proy:+.2f} pp)"
                        + (" tras escalón de carga" if ult_esc else ""))
        elif alarma and self.evento:
            self.evento['sev_max'] = max(self.evento['sev_max'], sev)
        elif not alarma and self.evento:
            self.evento['t_fin'] = t
            self.eventos.append(self.evento)
            self._decir(f"[{(t - self.t_ini) / 60:6.1f} min]     alarma liberada tras {t - self.evento['t_ini']:.1f} s")
            self.evento = None
        self._w.writerow([f"{t:.3f}", motor, m.group(2), m.group(3), m.group(4), i1, proy, racha, alarma, sev,
                          d.group(7), d.group(8), d.group(5), esc])
        self.prev = (t, i1, alarma)
        if self.expo >= self.proximo_reporte:
            self.proximo_reporte += 300.0
            self._decir(f"[{(t - self.t_ini) / 60:6.1f} min] exposición {self.expo / 60:.1f} min | eventos {self.n_eventos}")
        return self._revisar_fin(t)

    def tic(self, ahora: float) -> List[str]:
        """'0' al iniciar y cada 60 s (el SSR nunca se enciende en esta prueba); fin por tiempo máximo."""
        if not self.activa:
            return []
        if ahora - self.t_ini >= self.max_horas * 3600.0:
            return self.terminar(ahora, f"tiempo máximo de {self.max_horas:g} h")
        if self.ult_seguro is None or ahora - self.ult_seguro > SEGURO_S:
            self.ult_seguro = ahora
            return ["0"]
        return []

    def terminar(self, ahora: float, motivo: str = "terminada por el usuario; se puntúa lo registrado") -> List[str]:
        if not self.activa:
            return []
        self.activa = False
        self.motivo_fin = motivo
        self._f_tr.close()
        self._f_ser.close()
        if self.evento:
            self.evento['t_fin'] = ahora
            self.evento['abierto_al_final'] = True
            self.eventos.append(self.evento)
            self.evento = None
        self.resumen = self._resumen()
        with open(self.base + '_resumen.json', 'w') as fh:
            json.dump(self.resumen, fh, indent=2, ensure_ascii=False)
        r = self.resumen
        self._decir(f"[FIN] {motivo}")
        self._decir(f"Exposición con motor encendido: {self.expo / 60:.1f} min")
        self._decir(f"Falsas alarmas: {r['eventos_falsa_alarma']} eventos -> {r['tasa_por_hora']} por hora "
                    f"(límite sup. 95 %: {r['tasa_sup95_por_hora']} /h)")
        self._decir(f"Escalones de carga: {r['escalones_de_carga']} | con alarma en 30 s: {r['escalones_con_alarma_30s']}")
        self._decir(f"Alarmas atascadas (> {ATASCADA_S:.0f} s): {r['alarmas_atascadas_>30s']}")
        return ["0"]

    def cerrar(self, ahora: float) -> List[str]:
        return self.terminar(ahora, "app cerrada; se puntúa lo registrado")

    # ================================================================ interno
    def _revisar_fin(self, t: float) -> List[str]:
        if self.expo >= self.minutos * 60.0:
            return self.terminar(t, f"exposición objetivo de {self.minutos:g} min alcanzada")
        return []

    def _resumen(self) -> dict:
        horas = self.expo / 3600.0
        eventos, escalones = self.eventos, self.escalones
        k = len(eventos)
        sup = chi2_sup_poisson(k) / horas if horas > 0 else None
        tras = [e for e in eventos if e.get('tras_escalon')]
        atasc = [e for e in eventos if e['t_fin'] - e['t_ini'] > ATASCADA_S]
        esc_con_alarma = sum(any(0 <= ev['t_ini'] - e['t'] <= VENTANA_ESCALON_S for ev in eventos) for e in escalones)
        return {
            'fecha': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'firmware': FIRMWARE_COMPATIBLE, 'nota': self.nota,
            'origen': self.origen, 'registro_crudo_sesion': self.crudo_sesion,
            'parametros': {'minutos': self.minutos, 'max_horas': self.max_horas}, 'motivo_fin': self.motivo_fin,
            'exposicion_min': round(self.expo / 60.0, 1), 'eventos_falsa_alarma': k,
            'tasa_por_hora': round(k / horas, 2) if horas > 0 else None,
            'tasa_sup95_por_hora': round(sup, 2) if sup is not None else None,
            'escalones_de_carga': len(escalones), 'escalones_con_alarma_30s': esc_con_alarma,
            'alarmas_tras_escalon': len(tras), 'alarmas_atascadas_>30s': len(atasc),
            'eventos': [{**e, 'duracion_s': round(e['t_fin'] - e['t_ini'], 1),
                         'sev_max': CLASES[e['sev_max']]} for e in eventos],
            'escalones': escalones,
        }

    def _decir(self, texto: str):
        self.consola.append(texto)
        self.n_dichas += 1
