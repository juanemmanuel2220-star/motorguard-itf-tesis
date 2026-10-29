#!/usr/bin/env python3
"""
MotorGuard-ITF: validacion en vivo del detector direccional (ensayo ciego)
-------------------------------------------------------------------------
Detector congelado, ajustado con el bloque LEVE del 06-oct-2026 (200 pares, 4 cargas):
    dR2(t) = R2(t)/I1(t) - mediana(R2/I1 en [t-11 s, t-6 s])
    alarma  si  proyeccion de dR2 sobre ANG_FALLA >= UMBRAL

Ensayo: N pruebas en orden aleatorio, mitad con pulso real del SSR (7 s) y mitad
simuladas (no se envia nada). El detector no recibe la etiqueta ni lee el campo SSR
de la trama; la etiqueta solo se usa al final para puntuar.

v2 (06-oct-2026, regla congelada ANTES de la sesion de validacion del 07-oct):
  Regla primaria = PERSISTENCIA: la alarma se confirma cuando PERSISTENCIA tramas
  consecutivas (~1.7 s cada una) tienen proyeccion >= UMBRAL. El contador corre sobre
  el flujo continuo de tramas, como lo haria el detector embebido.
  - Prueba = FALLA si hay alarma confirmada en alguna trama recibida entre el inicio
    de la prueba y T_PULSO + T_COLA s despues (misma ventana para reales y simuladas).
  - Falsas alarmas continuas = eventos de confirmacion en tiempo libre (sin pulso y con
    la referencia ya limpia del pulso anterior), reportadas por hora de exposicion.
  Motivo: en la sesion del 06-oct (25 pruebas, 75 %) hubo picos aislados de SANO de
  hasta 0.87 pp en una sola trama. La regla se eligio viendo esos datos, por eso se
  congela aqui y se valida en una sesion nueva.
  Regla secundaria (v1, solo para comparar): ultima trama entre 3.0 y 7.5 s.

v3 (07-oct-2026): --decision firmware puntua con la alarma del detector embebido
  (campo "DIR: ... C=" de la telemetria, firmware con detector_dir). El detector de la PC
  sigue corriendo en paralelo y se reporta la concordancia trama a trama.

v4 (07-oct-2026): duracion del pulso y pausas configurables (--t-pulso, --espera-min/max).
  Declarado antes de la repeticion con firmware: pulsos de 11 s (limite del firmware 12 s),
  pausas de 12 a 20 s, 20 pruebas. El detector no cambia.

v5 (08-oct-2026): validacion de severidad con el firmware enclavado (commit 299a943).
  Declarado antes de correr: un bloque por severidad (taps SEVERA, INTER, LEVE), 75 % de carga,
  20 pruebas (10 reales / 10 simuladas), pulsos de 11 s, pausas 12-20 s, --decision firmware.
  Por prueba real detectada se registra la severidad maxima reportada por el Arduino (SEV) en la
  ventana de la prueba, si la alarma se mantuvo enclavada desde su confirmacion hasta el fin del
  pulso y cuanto tardo en liberarse. Criterios: sensibilidad >= 0.90, especificidad >= 0.95,
  severidad correcta >= 90 % de las detecciones, enclavamiento >= 90 % de las detecciones.
  Todas las pruebas cuentan en las metricas primarias. Las pruebas reales con |dR2| maximo
  < 0.20 pp (lazo sin conduccion) se marcan 'sin_firma' y se reportan aparte como secundario.
  La equivalencia PC/firmware se mide sobre la racha movil (el firmware enclava; la PC no).

Uso: python3 validacion_vivo_direccional.py --carga 75% --pruebas 20 --clase SEVERA --decision firmware --t-pulso 11 --espera-min 12 --espera-max 20
"""

import argparse
import cmath
import csv
import json
import math
import os
import random
import re
import statistics as st
import sys
import time
from datetime import datetime

import serial

ANG_FALLA = -81.4   # grados, direccion media de la firma LEVE (4 cargas)
UMBRAL = 0.40       # pp de |I1|, umbral de exactitud balanceada (0.990 fuera de linea)
REF_VENTANA = (11.0, 6.0)   # la referencia usa tramas entre t-11 s y t-6 s
T_PULSO = 7.0
T_DECISION = (3.0, 7.5)   # ventana de la regla secundaria (v1)
PERSISTENCIA = 3          # tramas consecutivas >= UMBRAL para confirmar la alarma
T_COLA = 2.0              # s tras el fin de la prueba en que aun se acepta la confirmacion
                          # (la trama siguiente al OFF todavia contiene el pulso)

PUERTO = "/dev/ttyACM0"
BAUD = 115200
SALIDA = os.path.expanduser('~/tesis_itf/validacion_vivo')

RE_TRAMA = re.compile(r"\[MCSA\]\s+Motor:(\w+).*?IA=([\d.]+)A\s+IB=([\d.]+)A\s+IC=([\d.]+)A")
RE_RAW = re.compile(r"RAW:\s+R2=([-\d.]+),([-\d.]+)\s+I1=([-\d.]+)")
RE_DIR = re.compile(r"DIR:\s+P=([-\d.]+)\s+R=(\d+)\s+C=(\d)\s+REF=(\d)")
RE_SEV = re.compile(r"SEV=(\d)\s+ML=([-\d.]+)\s+PL=([-\d.]+)")
CLASES_SEV = ['SANO', 'LEVE', 'INTER', 'SEVERA']
U = cmath.exp(-1j * math.radians(ANG_FALLA))


class Detector:
    """Detector direccional sobre el residuo crudo; no conoce el estado del SSR."""

    def __init__(self):
        self.hist = []  # (t, r2/i1 en pp)

    def actualizar(self, t, r2, i1):
        z = r2 / i1 * 100.0
        ref = [x for (tt, x) in self.hist if t - REF_VENTANA[0] <= tt <= t - REF_VENTANA[1]]
        self.hist.append((t, z))
        self.hist = [(tt, x) for (tt, x) in self.hist if tt >= t - 30.0]
        if len(ref) < 2:
            return None
        zref = complex(st.median(x.real for x in ref), st.median(x.imag for x in ref))
        dz = z - zref
        return dz, (dz * U).real


def leer_trama(ser, f_serial):
    raw = ser.readline().decode('utf-8', errors='ignore').strip()
    if not raw:
        return None, raw
    f_serial.write(f"{time.time():.3f} {raw}\n")
    m, r = RE_TRAMA.search(raw), RE_RAW.search(raw)
    if not (m and r):
        return None, raw
    fw = RE_DIR.search(raw)
    sv = RE_SEV.search(raw)
    return {'t': time.time(), 'motor': m.group(1), 'ia': float(m.group(2)), 'ib': float(m.group(3)),
            'ic': float(m.group(4)), 'r2': complex(float(r.group(1)), float(r.group(2))),
            'i1': float(r.group(3)),
            'fw': (float(fw.group(1)), int(fw.group(2)), int(fw.group(3)), int(fw.group(4))) if fw else None,
            'sev': (int(sv.group(1)), float(sv.group(2)), float(sv.group(3))) if sv else None}, raw


def main():
    ap = argparse.ArgumentParser(description="Validacion en vivo, ciega, del detector direccional")
    ap.add_argument('--carga', required=True, choices=['0%', '25%', '50%', '75%'])
    ap.add_argument('--pruebas', type=int, default=40, help="numero total de pruebas (par: mitad reales, mitad simuladas)")
    ap.add_argument('--semilla', type=int, default=None)
    ap.add_argument('--clase', default='LEVE', choices=['LEVE', 'INTER', 'SEVERA'],
                    help="taps conectados: severidad esperada en las pruebas reales")
    ap.add_argument('--port', default=PUERTO)
    ap.add_argument('--t-pulso', type=float, default=T_PULSO, help="duracion de cada prueba en s (default 7; max 11.5)")
    ap.add_argument('--espera-min', type=float, default=15.0, help="pausa minima entre pruebas en s (default 15; min 12)")
    ap.add_argument('--espera-max', type=float, default=30.0, help="pausa maxima entre pruebas en s (default 30)")
    ap.add_argument('--decision', choices=['pc', 'firmware'], default='pc',
                    help="fuente de la alarma que se puntua (default: pc)")
    args = ap.parse_args()
    if not (3.0 <= args.t_pulso <= 11.5):
        sys.exit("--t-pulso debe estar entre 3 y 11.5 s (el firmware corta el SSR a los 12 s)")
    if args.espera_min < 12.0 or args.espera_max < args.espera_min:
        sys.exit("--espera-min >= 12 s (la referencia debe quedar limpia del pulso anterior) y --espera-max >= --espera-min")
    t_pulso = args.t_pulso
    t_decision = (T_DECISION[0], t_pulso + 0.5)

    semilla = args.semilla if args.semilla is not None else int(time.time())
    rng = random.Random(semilla)
    plan = ['REAL'] * (args.pruebas // 2) + ['SIMULADA'] * (args.pruebas - args.pruebas // 2)
    rng.shuffle(plan)
    esperas = [rng.uniform(args.espera_min, args.espera_max) for _ in plan]

    os.makedirs(SALIDA, exist_ok=True)
    base = os.path.join(SALIDA, f"vivo_{args.clase}_{args.carga}_{datetime.now().strftime('%Y%m%d_%H%M')}")
    f_tramas = open(base + '_tramas.csv', 'w', newline='')
    w_tramas = csv.writer(f_tramas)
    w_tramas.writerow(['t', 'prueba', 'fase', 't_desde_real', 'ia', 'ib', 'ic', 'dr2_re', 'dr2_im', 'proy', 'alarma',
                       'racha', 'confirmada', 'pc_racha', 'pc_confirmada', 'fw_proy', 'fw_racha', 'fw_confirmada', 'fw_ref',
                       'fw_sev', 'fw_ml', 'fw_pl', 'pc_mag'])
    f_serial = open(base + '_serial.log', 'w', buffering=1)

    print("=" * 78)
    print(f"  VALIDACION EN VIVO (CIEGA) - detector direccional congelado")
    print(f"  ANG={ANG_FALLA} deg  UMBRAL={UMBRAL} pp  PERSISTENCIA={PERSISTENCIA} tramas | carga {args.carga} | taps {args.clase}")
    print(f"  Decision puntuada: {args.decision.upper()} | pulso {t_pulso:.1f} s | pausas {args.espera_min:.0f}-{args.espera_max:.0f} s")
    print(f"  {args.pruebas} pruebas en orden aleatorio (semilla {semilla}); salida: {base}_*")
    print("=" * 78)

    # El plan se guarda desde el inicio para poder puntuar aunque el ensayo se interrumpa
    with open(base + '_plan.json', 'w') as fh:
        json.dump({'semilla': semilla, 'plan': plan, 'esperas': esperas}, fh, indent=2)

    ser = serial.Serial(args.port, BAUD, timeout=1)
    time.sleep(0.5)
    ser.reset_input_buffer()
    ser.write(b'0\n')
    det = Detector()
    resultados = []
    estado = {'prueba': 0, 'fase': 'LIBRE', 'fin_real': -1e9, 'ssr_ok': False,
              'racha': 0, 'conf_t': [], 'concuerdan': 0, 'comparadas': 0}  # conf_t: tramas con alarma confirmada

    def procesar(d):
        out = det.actualizar(d['t'], d['r2'], d['i1'])
        if out is None:
            return None
        dz, p = out
        alarma = p >= UMBRAL
        estado['racha'] = estado['racha'] + 1 if alarma else 0
        pc_conf = estado['racha'] >= PERSISTENCIA
        fw = d['fw']
        if args.decision == 'firmware':
            if fw is None:
                raise RuntimeError("La telemetria no trae el campo DIR: flashea el firmware con detector_dir")
            racha, confirmada = fw[1], bool(fw[2])
        else:
            racha, confirmada = estado['racha'], pc_conf
        if fw is not None and fw[3]:
            # equivalencia sobre la racha movil (el firmware enclava la alarma y la PC no)
            estado['comparadas'] += 1
            estado['concuerdan'] += int(fw[1] == estado['racha'])
        if confirmada:
            estado['conf_t'].append(d['t'])
        w_tramas.writerow([f"{d['t']:.3f}", estado['prueba'], estado['fase'], f"{d['t'] - estado['fin_real']:.1f}", d['ia'], d['ib'], d['ic'],
                           f"{dz.real:.4f}", f"{dz.imag:.4f}", f"{p:.4f}", int(alarma), racha, int(confirmada),
                           estado['racha'], int(pc_conf)] + ([f"{fw[0]:.4f}", fw[1], fw[2], fw[3]] if fw else ['', '', '', ''])
                          + ([d['sev'][0], f"{d['sev'][1]:.3f}", f"{d['sev'][2]:.3f}"] if d['sev'] else ['', '', ''])
                          + [f"{abs(dz):.4f}"])
        marca = "  <<< ALARMA CONFIRMADA" if confirmada else (f"  < sobre umbral ({racha}/{PERSISTENCIA})" if racha else "")
        extra = f" | fw={fw[0]:+.2f}" if fw else ""
        if d['sev'] and d['sev'][0]:
            extra += f" | {CLASES_SEV[d['sev'][0]]} |dR2|={d['sev'][1]:.2f}"
        print(f"    proy={p:+.2f} pp  |dR2|={abs(dz):.2f}{extra}{marca}")
        return p

    def escuchar(segundos, ventana=None):
        """Lee tramas durante 'segundos'; devuelve las proyecciones dentro de la ventana relativa."""
        t0 = time.time()
        dentro = []
        while time.time() - t0 < segundos:
            d, raw = leer_trama(ser, f_serial)
            if '[DEBUG SSR] Exito' in raw:
                estado['ssr_ok'] = True
            elif '[DEBUG SSR] Rechazado' in raw:
                print(f"    {raw}")
            if not d:
                continue
            if d['motor'] != 'ON':
                raise RuntimeError("El firmware dejo de reportar Motor:ON")
            p = procesar(d)
            if ventana and p is not None and ventana[0] <= d['t'] - t0 <= ventana[1]:
                dentro.append(p)
        return dentro

    try:
        print("\n[PREVIO] Esperando Motor:ON (warmup del firmware, max 120 s)...")
        t_lim = time.time() + 120.0
        while time.time() < t_lim:
            d, _ = leer_trama(ser, f_serial)
            if d and d['motor'] == 'ON':
                print(f"[PREVIO] Motor ON | I = {d['ia']:.2f}/{d['ib']:.2f}/{d['ic']:.2f} A")
                break
        else:
            raise RuntimeError("El firmware no reporto Motor:ON en 120 s")
        print("[PREVIO] Llenando la referencia del detector (20 s)...")
        escuchar(20.0)
        for k, (tipo, espera) in enumerate(zip(plan, esperas), 1):
            estado.update(prueba=0, fase='LIBRE')
            escuchar(espera)
            estado.update(prueba=k, fase='PRUEBA')
            print(f"\n[{k:2d}/{len(plan)}] prueba en curso (etiqueta oculta hasta el final)")
            estado['ssr_ok'] = False
            t_ini = time.time()
            if tipo == 'REAL':
                ser.write(b'1\n')
            proys = escuchar(t_pulso, ventana=t_decision)
            t_fin = time.time()
            if tipo == 'REAL':
                ser.write(b'0\n')
                estado['fin_real'] = t_fin
            estado.update(fase='DRENADO')
            escuchar(4.0)
            decision = any(t_ini <= tc <= t_ini + t_pulso + T_COLA for tc in estado['conf_t'])
            decision_v1 = (proys[-1] >= UMBRAL) if proys else None
            if tipo == 'REAL' and not estado['ssr_ok']:
                decision = decision_v1 = None  # el firmware no confirmo el pulso: prueba invalida
                print("    [AVISO] el firmware no confirmo el SSR; la prueba se anula")
            resultados.append({'prueba': k, 'tipo': tipo, 'proys': proys, 'alarma': decision, 'alarma_v1': decision_v1,
                               't_ini': t_ini, 't_fin': t_fin})
            print(f"[{k:2d}/{len(plan)}] decision del detector: {'FALLA' if decision else 'SANO' if decision is not None else 'SIN TRAMA'}")
    except KeyboardInterrupt:
        print("\n[DETENIDO] por el usuario")
    except RuntimeError as e:
        print(f"\n[DETENIDO] {e}; se puntuan las pruebas completas")
    finally:
        ser.write(b'0\n')
        ser.flush()
        ser.close()
        f_tramas.close()
        f_serial.close()
        print("[SEGURIDAD] SSR apagado y puerto cerrado.")

    # Puntuacion (aqui se revela la etiqueta)
    val = [r for r in resultados if r['alarma'] is not None]

    def matriz(clave):
        return (sum(r['tipo'] == 'REAL' and r[clave] for r in val),
                sum(r['tipo'] == 'REAL' and not r[clave] for r in val),
                sum(r['tipo'] == 'SIMULADA' and r[clave] for r in val),
                sum(r['tipo'] == 'SIMULADA' and not r[clave] for r in val))
    tp, fn, fp, tn = matriz('alarma')
    tp1, fn1, fp1, tn1 = matriz('alarma_v1')

    # Falsas alarmas continuas: tramas libres con la referencia ya limpia del pulso anterior
    libres, eventos, t_expo, previa = [], 0, 0.0, None
    with open(base + '_tramas.csv') as fh:
        for row in csv.DictReader(fh):
            ok = row['fase'] == 'LIBRE' and float(row['t_desde_real']) >= 12.0
            t = float(row['t'])
            if ok:
                libres.append(int(row['alarma']))
                if previa is not None and previa[0] and t - previa[1] < 5.0:
                    t_expo += t - previa[1]
                # evento = transicion a confirmada dentro del tiempo libre
                if int(row['confirmada']) and int(row['racha']) == PERSISTENCIA:
                    eventos += 1
            previa = (ok, t)
    # Severidad, enclavamiento y liberacion por prueba (a partir de las tramas registradas)
    tr = []
    with open(base + '_tramas.csv') as fh:
        for row in csv.DictReader(fh):
            tr.append(row)
    for r in resultados:
        ven = [x for x in tr if r['t_ini'] <= float(x['t']) <= r['t_fin'] + T_COLA]
        sevs = [int(x['fw_sev']) for x in ven if x['fw_sev'] != '']
        r['sev_max'] = max(sevs) if sevs else 0
        mags = [float(x['pc_mag']) for x in ven if x['pc_mag'] != '' and float(x['t']) <= r['t_fin']]
        r['dr2_max'] = max(mags) if mags else None
        r['sin_firma'] = r['tipo'] == 'REAL' and (r['dr2_max'] is None or r['dr2_max'] < 0.20)
        # enclavamiento: desde la primera confirmacion dentro del pulso hasta su fin, siempre confirmada
        pul = [x for x in ven if float(x['t']) <= r['t_fin'] and x['confirmada'] != '']
        conf = [int(x['confirmada']) for x in pul]
        if 1 in conf:
            r['enclavada_ok'] = all(conf[conf.index(1):])
            post = [float(x['t']) - r['t_fin'] for x in tr if float(x['t']) > r['t_fin'] and x['confirmada'] == '0']
            r['liberada_s'] = round(post[0], 1) if post else None
        else:
            r['enclavada_ok'] = None
            r['liberada_s'] = None
    esperada = CLASES_SEV.index(args.clase)
    det = [r for r in val if r['tipo'] == 'REAL' and r['alarma']]
    sev_ok = sum(r['sev_max'] == esperada for r in det)
    encl_ok = sum(bool(r.get('enclavada_ok')) for r in det)
    dist_sev = {c: sum(r['sev_max'] == i for r in det) for i, c in enumerate(CLASES_SEV) if i}
    lib = [r['liberada_s'] for r in det if r.get('liberada_s') is not None]
    sinf = [r['prueba'] for r in val if r.get('sin_firma')]
    v2 = [r for r in val if not r.get('sin_firma')]
    tp2 = sum(r['tipo'] == 'REAL' and r['alarma'] for r in v2)
    fn2 = sum(r['tipo'] == 'REAL' and not r['alarma'] for r in v2)

    resumen = {
        'fecha': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'carga': args.carga, 'clase': args.clase,
        'decision': args.decision, 't_pulso': t_pulso, 'esperas_rango': [args.espera_min, args.espera_max],
        'concordancia_pc_fw': {'comparadas': estado['comparadas'], 'concuerdan': estado['concuerdan']},
        'semilla': semilla, 'ang_falla': ANG_FALLA, 'umbral': UMBRAL, 'persistencia': PERSISTENCIA,
        't_cola': T_COLA, 'regla_primaria': 'persistencia (v2)', 'plan': plan,
        'TP': tp, 'FN': fn, 'FP': fp, 'TN': tn,
        'sensibilidad': tp / max(1, tp + fn), 'especificidad': tn / max(1, tn + fp),
        'v1_ultima_trama': {'TP': tp1, 'FN': fn1, 'FP': fp1, 'TN': tn1},
        'tramas_libres': len(libres), 'tramas_libres_sobre_umbral': sum(libres),
        'eventos_falsa_alarma_continua': eventos, 'minutos_libres': round(t_expo / 60.0, 1),
        'falsas_alarmas_por_hora': round(eventos / (t_expo / 3600.0), 2) if t_expo > 0 else None,
        'severidad_esperada': args.clase, 'severidad_correcta': sev_ok, 'detectadas': len(det),
        'severidad_distribucion': dist_sev, 'enclavamiento_ok': encl_ok,
        'liberacion_s': {'min': min(lib), 'max': max(lib)} if lib else None,
        'reales_sin_firma': sinf, 'secundario_sin_reales_sin_firma': {'TP': tp2, 'FN': fn2},
        'pruebas': resultados,
    }
    with open(base + '_resumen.json', 'w') as fh:
        json.dump(resumen, fh, indent=2, ensure_ascii=False)

    print("\n" + "=" * 78)
    print(f"  REGLA PRIMARIA ({PERSISTENCIA} tramas) - {len(val)} pruebas validas: TP={tp} FN={fn} FP={fp} TN={tn}")
    print(f"  Sensibilidad {resumen['sensibilidad']:.3f} | Especificidad {resumen['especificidad']:.3f}")
    print(f"  Falsas alarmas continuas: {eventos} eventos en {resumen['minutos_libres']} min libres "
          f"({sum(libres)} de {len(libres)} tramas sobre el umbral)")
    print(f"  Regla v1 (ultima trama, comparacion): TP={tp1} FN={fn1} FP={fp1} TN={tn1}")
    if estado['comparadas']:
        print(f"  Concordancia PC vs firmware (racha movil): {estado['concuerdan']} de {estado['comparadas']} tramas")
    if det:
        print(f"  SEVERIDAD esperada {args.clase}: correcta en {sev_ok} de {len(det)} detecciones | distribucion {dist_sev}")
        print(f"  Enclavamiento hasta el fin del pulso: {encl_ok} de {len(det)}"
              + (f" | liberacion {min(lib):.1f}-{max(lib):.1f} s tras el pulso" if lib else ""))
    if sinf:
        print(f"  [AVISO] pruebas reales sin firma (lazo sin conduccion?): {sinf} -> secundario sin ellas: TP={tp2} FN={fn2}")
    print(f"  Detalle: {base}_resumen.json")
    print("=" * 78)


if __name__ == '__main__':
    main()
