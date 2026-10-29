#!/usr/bin/env python3
"""
MotorGuard-ITF: prueba larga sin falla (tasa de falsas alarmas del detector embebido)
-------------------------------------------------------------------------------------
Protocolo declarado ANTES de correr (10-oct-2026), firmware 299a943 (detector direccional con
enclavamiento y severidad), sin cambios:

  - Motor sano: el SSR nunca se activa (el script envia '0' al inicio y cada 60 s por seguridad).
  - El operador arranca el script con el motor girando desde hace >= 5 min y cambia la carga del
    generador cada ~10 min (0 -> 25 -> 50 -> 75 -> 50 -> 25 -> 0 ...), sin tocar el lazo.
  - Duracion objetivo: 90 min de exposicion con Motor:ON (el tiempo con motor apagado o en
    WARMUP no cuenta; si el motor se apaga, el script espera y sigue sumando al volver).
  - Se registra cada bloque del firmware (corrientes, |I1|, proyeccion, racha, alarma, severidad).

Metricas (todas sobre la decision del Arduino, campo DIR):
  - Eventos de falsa alarma = transiciones de C=0 a C=1. Tasa por hora de exposicion, con
    limite superior al 95 % (Poisson; con 0 eventos el limite es 3/T).
  - Escalones de carga = cambio de |I1| > 3 % entre bloques consecutivos. Para cada escalon se
    registra si hubo alarma en los 30 s siguientes.
  - Alarmas atascadas = eventos que duran > 30 s.
Criterios propuestos: <= 1 falsa alarma por hora y 0 alarmas disparadas por escalones de carga.
"""

import argparse
import csv
import json
import math
import os
import re
import time
from datetime import datetime

import serial

PUERTO = "/dev/ttyACM0"
BAUD = 115200
SALIDA = os.path.expanduser('~/tesis_itf/prueba_larga')
RE_TRAMA = re.compile(r"\[MCSA\]\s+Motor:(\w+).*?IA=([\d.]+)A\s+IB=([\d.]+)A\s+IC=([\d.]+)A")
RE_RAW = re.compile(r"RAW:\s+R2=([-\d.]+),([-\d.]+)\s+I1=([-\d.]+)")
RE_DIR = re.compile(r"DIR:\s+P=([-\d.]+)\s+R=(\d+)\s+C=(\d)\s+REF=(\d)\s+CUSUM=(\d)\s+SEV=(\d)\s+ML=([-\d.]+)\s+PL=([-\d.]+)")
CLASES = ['SANO', 'LEVE', 'INTER', 'SEVERA']
ESCALON_REL = 0.03
VENTANA_ESCALON_S = 30.0
ATASCADA_S = 30.0


def chi2_sup_poisson(k, conf=0.95):
    """Limite superior exacto de una tasa Poisson con k eventos (en conteos)."""
    if k == 0:
        return -math.log(1 - conf)
    # busqueda simple: mu tal que P(X <= k | mu) = 1 - conf
    lo, hi = float(k), float(k) * 5 + 10
    for _ in range(100):
        mu = 0.5 * (lo + hi)
        p = sum(math.exp(-mu) * mu ** i / math.factorial(i) for i in range(k + 1))
        if p > 1 - conf:
            lo = mu
        else:
            hi = mu
    return 0.5 * (lo + hi)


def main():
    ap = argparse.ArgumentParser(description="Prueba larga sin falla: falsas alarmas del detector embebido")
    ap.add_argument('--minutos', type=float, default=90.0, help="exposicion objetivo con Motor:ON (default 90)")
    ap.add_argument('--max-horas', type=float, default=3.0, help="tiempo total maximo de la prueba (default 3 h)")
    ap.add_argument('--nota', default='')
    ap.add_argument('--port', default=PUERTO)
    args = ap.parse_args()

    os.makedirs(SALIDA, exist_ok=True)
    base = os.path.join(SALIDA, f"larga_{datetime.now().strftime('%Y%m%d_%H%M')}")
    f_tr = open(base + '_tramas.csv', 'w', newline='')
    w = csv.writer(f_tr)
    w.writerow(['t', 'motor', 'ia', 'ib', 'ic', 'i1', 'proy', 'racha', 'alarma', 'sev', 'ml', 'pl', 'cusum', 'escalon'])
    f_ser = open(base + '_serial.log', 'w', buffering=1)

    print("=" * 78)
    print(f"  PRUEBA LARGA SIN FALLA - objetivo {args.minutos:.0f} min con motor encendido")
    print(f"  Cambia la carga cada ~10 min (0->25->50->75->50->25...) sin tocar el lazo.")
    print(f"  Salida: {base}_*   (Ctrl+C para terminar antes; se puntua lo registrado)")
    print("=" * 78)

    ser = serial.Serial(args.port, BAUD, timeout=1)
    time.sleep(0.5)
    ser.reset_input_buffer()
    ser.write(b'0\n')

    t_ini = time.time()
    expo = 0.0
    prev = None              # (t, i1, alarma) del bloque ON anterior
    eventos = []             # alarmas: dict(t_ini, t_fin, sev_max, escalon_previo)
    escalones = []           # dict(t, de, a)
    evento = None
    ult_seguro = time.time()
    proximo_reporte = 300.0
    try:
        while expo < args.minutos * 60.0 and time.time() - t_ini < args.max_horas * 3600.0:
            if time.time() - ult_seguro > 60.0:
                ser.write(b'0\n')
                ult_seguro = time.time()
            raw = ser.readline().decode('utf-8', errors='ignore').strip()
            if not raw:
                continue
            t = time.time()
            f_ser.write(f"{t:.3f} {raw}\n")
            m, r, d = RE_TRAMA.search(raw), RE_RAW.search(raw), RE_DIR.search(raw)
            if not (m and r and d):
                continue
            motor = m.group(1)
            i1 = float(r.group(3))
            proy, racha, alarma, sev = float(d.group(1)), int(d.group(2)), int(d.group(3)), int(d.group(6))
            esc = 0
            if motor != 'ON':
                prev = None
                if evento:
                    evento['t_fin'] = t
                    evento['cortado_por_motor'] = True
                    eventos.append(evento)
                    evento = None
                w.writerow([f"{t:.3f}", motor, m.group(2), m.group(3), m.group(4), i1, proy, racha, alarma, sev,
                            d.group(7), d.group(8), d.group(5), 0])
                continue
            if prev is not None:
                dt = t - prev[0]
                if dt < 5.0:
                    expo += dt
                if prev[1] > 1e-6 and abs(i1 - prev[1]) / prev[1] > ESCALON_REL:
                    esc = 1
                    escalones.append({'t': t, 'de': prev[1], 'a': i1})
                    print(f"[{(t - t_ini) / 60:6.1f} min] escalon de carga: |I1| {prev[1]:.2f} -> {i1:.2f} A")
            if alarma and evento is None:
                ult_esc = [e for e in escalones if 0 <= t - e['t'] <= VENTANA_ESCALON_S]
                evento = {'t_ini': t, 'sev_max': sev, 'tras_escalon': bool(ult_esc)}
                print(f"[{(t - t_ini) / 60:6.1f} min] <<< FALSA ALARMA {CLASES[sev]} (proy {proy:+.2f} pp)"
                      + (" tras escalon de carga" if ult_esc else ""))
            elif alarma and evento:
                evento['sev_max'] = max(evento['sev_max'], sev)
            elif not alarma and evento:
                evento['t_fin'] = t
                eventos.append(evento)
                print(f"[{(t - t_ini) / 60:6.1f} min]     alarma liberada tras {t - evento['t_ini']:.1f} s")
                evento = None
            w.writerow([f"{t:.3f}", motor, m.group(2), m.group(3), m.group(4), i1, proy, racha, alarma, sev,
                        d.group(7), d.group(8), d.group(5), esc])
            prev = (t, i1, alarma)
            if expo >= proximo_reporte:
                proximo_reporte += 300.0
                print(f"[{(t - t_ini) / 60:6.1f} min] exposicion {expo / 60:.1f} min | eventos {len(eventos) + (1 if evento else 0)}")
    except KeyboardInterrupt:
        print("\n[DETENIDO] por el usuario; se puntua lo registrado")
    finally:
        ser.write(b'0\n')
        ser.flush()
        ser.close()
        f_tr.close()
        f_ser.close()
        print("[SEGURIDAD] SSR apagado y puerto cerrado.")

    if evento:
        evento['t_fin'] = time.time()
        evento['abierto_al_final'] = True
        eventos.append(evento)
    horas = expo / 3600.0
    k = len(eventos)
    sup = chi2_sup_poisson(k) / horas if horas > 0 else None
    tras = [e for e in eventos if e.get('tras_escalon')]
    atasc = [e for e in eventos if e['t_fin'] - e['t_ini'] > ATASCADA_S]
    esc_con_alarma = sum(any(0 <= ev['t_ini'] - e['t'] <= VENTANA_ESCALON_S for ev in eventos) for e in escalones)
    res = {
        'fecha': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'firmware': '299a943', 'nota': args.nota,
        'exposicion_min': round(expo / 60.0, 1), 'eventos_falsa_alarma': k,
        'tasa_por_hora': round(k / horas, 2) if horas > 0 else None,
        'tasa_sup95_por_hora': round(sup, 2) if sup is not None else None,
        'escalones_de_carga': len(escalones), 'escalones_con_alarma_30s': esc_con_alarma,
        'alarmas_tras_escalon': len(tras), 'alarmas_atascadas_>30s': len(atasc),
        'eventos': [{**e, 'duracion_s': round(e['t_fin'] - e['t_ini'], 1),
                     'sev_max': CLASES[e['sev_max']]} for e in eventos],
        'escalones': escalones,
    }
    with open(base + '_resumen.json', 'w') as fh:
        json.dump(res, fh, indent=2, ensure_ascii=False)
    print("\n" + "=" * 78)
    print(f"  Exposicion con motor encendido: {expo / 60:.1f} min")
    print(f"  Falsas alarmas: {k} eventos -> {res['tasa_por_hora']} por hora (limite sup. 95 %: {res['tasa_sup95_por_hora']} /h)")
    print(f"  Escalones de carga detectados: {len(escalones)} | con alarma en 30 s: {esc_con_alarma}")
    print(f"  Alarmas atascadas (> {ATASCADA_S:.0f} s): {len(atasc)}")
    print(f"  Detalle: {base}_resumen.json")
    print("=" * 78)


if __name__ == '__main__':
    main()
