#!/usr/bin/env python3
"""
MotorGuard-ITF: Capturador Robusto Multiclase vía USB Serial v4.0
-----------------------------------------------------------------
Permite adquirir datasets entrelazados (SANO vs FALLA) para cualquier
nivel de severidad (LEVE, INTERMEDIA, SEVERA) utilizando el MISMO
relevador físico (SSR 1 / GPIO 8) con resistencia limitadora de 5 ohms.

Autor: Emmanuel Luna (UASLP)
Fecha: Septiembre 2026

v4.1 (2026-10-01): sincronizacion de etiquetas con la ventana de analisis.
  - El ON se fecha con la confirmacion del firmware ("[DEBUG SSR] Exito").
  - FALLA: ultima trama recibida con t_desde_on >= --t-min-on (la ventana de
    4096 muestras = 1.70 s debe quedar completa dentro del pulso).
  - SANO: se vacia el bufer serial y se exige t_desde_off >= --cooldown, para no
    etiquetar como clase 0 tramas del drenado post-falla. No se filtra por la
    prediccion del firmware (evita sesgo circular); se registra en 'pred_fw'.
  - Umbral de aceptacion configurable (--umbral-e2, default 1.0 pp).
  - Columnas extra al final: t_desde_on, t_desde_off, va, vb, ia, ib, delta_e2, pred_fw.

v4.2 (2026-10-06): sin umbral de DE2 por defecto (--umbral-e2 0).
  - Filtrar por DE2 sesgaba el dataset hacia las firmas LEVE mas faciles: el par
    se acepta por los filtros de estabilidad, no por la variable a clasificar.
  - Comprobacion previa: motor ON y lectura de corrientes antes del primer pulso.
  - Columnas de fasores crudos (r2, i1, v2, v1) y FallaMax; copia completa del
    puerto serie en <csv>_serial.log.
  - Archivo <csv>_meta.json con condiciones de la sesion (commit del firmware,
    parametros, nota del banco) y resumen final (pares, descartes).
"""

import sys
import os
import time
import csv
import re
import glob
import argparse
import json
import subprocess
import serial
from datetime import datetime
from typing import Optional, Dict, Any, List

DATASET_DIR = os.path.expanduser('~/tesis_itf/dataset')
os.makedirs(DATASET_DIR, exist_ok=True)

DEFAULT_PORT = "/dev/ttyACM0"
BAUD = 115200

CLASES = {
    0: 'SANO',
    1: 'LEVE',
    2: 'INTER',
    3: 'SEVERA'
}

CARGAS_LABEL = {
    0: '0%',
    1: '25%',
    2: '50%',
    3: '75%'
}

CARGAS_MAP = {'0%': 0, '25%': 1, '50%': 2, '75%': 3}

COLS = [
    'clase', 'label', 'carga', 'carga_label', 'n_muestra', 'timestamp',
    'V_rms', 'I_rms', 'A_55', 'A_65', 'A_50', 'A_70', 'A_fund', 'I_neg', 'THD',
    'e2', 'u2v', 'u2i', 'dom',
    'hr_l2sm', 'hr_l2sp', 'hr_lrm', 'hr_lrp', 'hr_l3', 'hr_l3rm', 'hr_l3rp',
    'hr_snr2s', 'hr_s', 'hr_sok', 'hr_f0', 'cusum_s', 'p_cal',
    't_desde_on', 't_desde_off', 'va', 'vb', 'ia', 'ib', 'delta_e2', 'pred_fw',
    'de2_fw', 'dv2', 'ang_de2',
    'falla_max', 'r2_re', 'r2_im', 'i1', 'v2_re', 'v2_im', 'v1'
]

MCSA_REGEX = re.compile(
    r"\[MCSA\]\s+Motor:(\w+)\s+\|\s+FallaMax:([A-Za-z0-9 ]+)\s+\|\s+"
    r"VA=([\d\.]+)V\s+VB=([\d\.]+)V\s+VC=([\d\.]+)V\s+\|\s+"
    r"IA=([\d\.]+)A\s+IB=([\d\.]+)A\s+IC=([\d\.]+)A\s+\|\s+"
    r"Afund=([\d\.]+)\s+A55=([\d\.]+)\(([\d\.]+)Hz\)\s+A65=([\d\.]+)\(([\d\.]+)Hz\)\s+\|\s+"
    r"P_RF=([\d\.]+)%\s+P_E2=([\d\.]+)%\s+\|\s+(\w+)\s+\|\s+SSR:([A-Za-z0-9\(\)]+)\s+\|\s+"
    r"U2V=([\d\.]+)%\s+U2I=([\d\.]+)%\s+E2=([\d\.]+)%\s+DOM=(\d)\s+\|\s+"
    r"HR:\s+L2sM=([-\d\.]+)\s+L2sP=([-\d\.]+)\s+LrM=([-\d\.]+)\s+LrP=([-\d\.]+)\s+"
    r"L3=([-\d\.]+)\s+L3rM=([-\d\.]+)\s+L3rP=([-\d\.]+)\s+SNR2s=([-\d\.]+)\s+"
    r"s=([-\d\.]+)\s+SOK=(\d)\s+f0=([-\d\.]+)\s+\|\s+"
    r"CUSUM:\s+S=([-\d\.]+)\s+Pcal=([-\d\.]+)%"
)

# Campos del residuo vectorial (firmware >= 2026-10-01); opcionales para compatibilidad
VEC_REGEX = re.compile(r"DE2=([-\d\.]+)%\s+dV2=([-\d\.]+)%\s+ANG=([-\d\.]+)")
# Fasores crudos (firmware >= 2026-10-06): permiten reetiquetar fases a posteriori
RAW_REGEX = re.compile(r"RAW:\s+R2=([-\d\.]+),([-\d\.]+)\s+I1=([-\d\.]+)\s+V2=([-\d\.]+),([-\d\.]+)\s+V1=([-\d\.]+)")

# Copia de todas las líneas seriales recibidas (se abre en main junto al CSV)
_raw_log = None

def leer_linea(ser) -> str:
    raw = ser.readline().decode('utf-8', errors='ignore').strip()
    if raw and _raw_log:
        _raw_log.write(f"{time.time():.3f} {raw}\n")
    return raw

def parse_line(line: str) -> Optional[Dict[str, Any]]:
    m = MCSA_REGEX.search(line)
    if not m:
        return None
    g = m.groups()
    mv = VEC_REGEX.search(line)
    vec = {
        "de2_fw": float(mv.group(1)) if mv else float('nan'),
        "dv2": float(mv.group(2)) if mv else float('nan'),
        "ang_de2": float(mv.group(3)) if mv else float('nan'),
    }
    mr = RAW_REGEX.search(line)
    nan = float('nan')
    vec.update(dict(zip(('r2_re', 'r2_im', 'i1', 'v2_re', 'v2_im', 'v1'),
                        [float(x) for x in mr.groups()] if mr else [nan] * 6)))
    return {**vec, 
        "t": time.time(),
        "motor": g[0],
        "falla_max": g[1].strip(),
        "va": float(g[2]), "vb": float(g[3]), "vc": float(g[4]),
        "ia": float(g[5]), "ib": float(g[6]), "ic": float(g[7]),
        "afund": float(g[8]),
        "a55": float(g[9]), "f55": float(g[10]),
        "a65": float(g[11]), "f65": float(g[12]),
        "p_rf": float(g[13]),
        "p_e2": float(g[14]),
        "pred": g[15],
        "ssr": g[16],
        "u2v": float(g[17]), "u2i": float(g[18]), "e2": float(g[19]), "dom": int(g[20]),
        "hr_l2sm": float(g[21]), "hr_l2sp": float(g[22]),
        "hr_lrm": float(g[23]), "hr_lrp": float(g[24]),
        "hr_l3": float(g[25]), "hr_l3rm": float(g[26]), "hr_l3rp": float(g[27]),
        "hr_snr2s": float(g[28]), "hr_s": float(g[29]), "hr_sok": int(g[30]), "hr_f0": float(g[31]),
        "cusum_s": float(g[32]), "p_cal": float(g[33])
    }

def conectar_serial(port: str, baud: int = BAUD, timeout_espera: float = 30.0) -> serial.Serial:
    t0 = time.time()
    while time.time() - t0 < timeout_espera:
        if os.path.exists(port):
            try:
                ser = serial.Serial(port, baud, timeout=1.0)
                ser.dtr = True
                ser.rts = True
                time.sleep(0.5)
                ser.reset_input_buffer()
                return ser
            except Exception:
                pass
        time.sleep(1.0)
    raise serial.SerialException(f"No se pudo conectar a {port} tras {timeout_espera}s de espera.")

def ssr_off(ser: serial.Serial):
    ser.write(b'0\n')
    ser.flush()
    time.sleep(0.1)

def ssr_on(ser: serial.Serial):
    # Activa el relevador físico 1 (GPIO 8)
    ser.write(b'1\n')
    ser.flush()
    time.sleep(0.1)

def ssr_on_confirmado(ser: serial.Serial, timeout: float = 3.0) -> Optional[float]:
    """Activa SSR 1 y devuelve el instante en que el firmware confirma GPIO en HIGH,
    o None si el firmware rechaza la solicitud (cooldown, motor apagado, sobrecorriente)."""
    ser.reset_input_buffer()
    ser.write(b'1\n')
    ser.flush()
    t0 = time.time()
    while time.time() - t0 < timeout:
        raw = leer_linea(ser)
        if '[DEBUG SSR] Exito' in raw:
            return time.time()
        if '[DEBUG SSR] Rechazado' in raw:
            print(f"  [SSR] {raw}")
            return None
    print("  [SSR] Sin confirmación del firmware tras ON.")
    return None

def fases_fuera(a: Dict[str, Any], b: Dict[str, Any], tol_abs: float, tol_rel: float = 0.012):
    """Fases cuya corriente difiere entre dos tramas más que max(tol_abs, tol_rel*I)."""
    malas = []
    for k in ('ia', 'ib', 'ic'):
        lim = max(tol_abs, tol_rel * max(a[k], b[k]))
        if abs(a[k] - b[k]) > lim:
            malas.append(f"{k.upper()} {a[k]:.2f}->{b[k]:.2f}")
    return malas

def registrar_fila(writer, d: Dict[str, Any], clase: int, carga: int, n_muestra: int,
                   t_desde_on: float, t_desde_off: float, delta_e2: float):
    # Canal Fase C es rms[CH_VC] y rms[CH_IC]
    row = [
        clase,
        CLASES[clase],
        carga,
        CARGAS_LABEL[carga],
        n_muestra,
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        d['vc'],
        d['ic'],
        d['a55'],
        d['a65'],
        0.0, # A_50
        0.0, # A_70
        d['afund'],
        d['u2i'] / 100.0, # Ineg relativo
        0.0, # THD
        d['e2'],
        d['u2v'],
        d['u2i'],
        d['dom'],
        d['hr_l2sm'],
        d['hr_l2sp'],
        d['hr_lrm'],
        d['hr_lrp'],
        d['hr_l3'],
        d['hr_l3rm'],
        d['hr_l3rp'],
        d['hr_snr2s'],
        d['hr_s'],
        d['hr_sok'],
        d['hr_f0'],
        d['cusum_s'],
        d['p_cal'],
        round(t_desde_on, 2),
        round(t_desde_off, 2),
        d['va'], d['vb'], d['ia'], d['ib'],
        round(delta_e2, 3),
        d['pred'],
        d['de2_fw'], d['dv2'], d['ang_de2'],
        d['falla_max'], d['r2_re'], d['r2_im'], d['i1'], d['v2_re'], d['v2_im'], d['v1']
    ]
    writer.writerow(row)

def main():
    parser = argparse.ArgumentParser(description="Capturador Robusto Multiclase de Datasets ITF (USB Serial)")
    parser.add_argument("--clase", type=int, choices=[1, 2, 3], required=True,
                        help="Nivel de Falla a capturar: 1=LEVE (F1), 2=INTER (F2), 3=SEVERA (F3)")
    parser.add_argument("--carga", choices=['0%', '25%', '50%', '75%'], default='50%',
                        help="Nivel de carga del motor (default: 50%%)")
    parser.add_argument("--pares", type=int, default=75,
                        help="Número de pares entrelazados (default: 75 = 150 muestras)")
    parser.add_argument("--port", type=str, default=DEFAULT_PORT,
                        help=f"Puerto serial (default: {DEFAULT_PORT})")
    parser.add_argument("--continuar", action='store_true',
                        help="Reanudar sobre el archivo más reciente para esta clase y carga")
    parser.add_argument("--duracion-pulso", type=float, default=7.0,
                        help="Duración del pulso de inyección en segundos (default: 7.0 s; asegura 2 tramas completas)")
    parser.add_argument("--t-min-on", type=float, default=3.0,
                        help="Edad mínima de la trama FALLA desde la confirmación de ON (default: 3.0 s)")
    parser.add_argument("--cooldown", type=float, default=8.0,
                        help="Tiempo mínimo desde OFF antes de aceptar trama SANO (default: 8.0 s)")
    parser.add_argument("--umbral-e2", type=float, default=0.0,
                        help="Salto mínimo (pp) de DE2 para aceptar el par (default: 0 = sin filtro; filtrar por DE2 sesga el dataset)")
    parser.add_argument("--nota", type=str, default="",
                        help="Condiciones del banco para el registro (p. ej. 'taps LEVE fase C, I_lazo=1.7 A pinza')")
    parser.add_argument("--tol-i", type=float, default=0.06,
                        help="Filtro de calidad: variación máxima por fase (A) entre SANO consecutivos y dentro del pulso (default: 0.06)")
    parser.add_argument("--tol-de2", type=float, default=0.35,
                        help="Filtro de calidad: variación máxima de DE2 (pp) entre tramas del mismo pulso (default: 0.35)")
    args = parser.parse_args()

    clase = args.clase
    label_falla = CLASES[clase]
    carga_str = args.carga
    carga = CARGAS_MAP[carga_str]
    n_pares = args.pares

    print("=" * 80)
    print("  MOTORGUARD-ITF: CAPTURADOR DE DATASETS MULTICLASE (USB SERIAL)")
    print(f"  Clase Seleccionada: {label_falla} (Clase {clase})")
    print(f"  Carga Mecánica:     {carga_str} (Nivel {carga})")
    print(f"  Hardware:           Mismo relevador físico (SSR 1 / GPIO 8, R=5 ohms)")
    print(f"  Objetivo:           {n_pares} pares entrelazados ({n_pares * 2} muestras totales)")
    print("=" * 80)

    # Determinar ruta del archivo CSV
    patron = os.path.join(DATASET_DIR, f"cap_ENTRELAZADA_{label_falla}_{carga_str}_*.csv")
    csv_path = None
    if args.continuar:
        coincidencias = sorted(f for f in glob.glob(patron) if not f.endswith("_descartes.csv"))
        if coincidencias:
            csv_path = coincidencias[-1]
            with open(csv_path, 'r', newline='') as fh:
                header = next(csv.reader(fh), [])
            if header != COLS:
                print(f"[AVISO] {os.path.basename(csv_path)} tiene el esquema anterior (v4.0); no se reanuda sobre él.")
                csv_path = None
            else:
                print(f"[REANUDAR] Archivo previo encontrado: {os.path.basename(csv_path)}")

    if not csv_path:
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        csv_path = os.path.join(DATASET_DIR, f"cap_ENTRELAZADA_{label_falla}_{carga_str}_{ts}.csv")
        print(f"[NUEVO] Creando archivo: {os.path.basename(csv_path)}")

    # Conectar al puerto serial
    print(f"\n[CONEXIÓN] Esperando puerto {args.port}...")
    try:
        ser = conectar_serial(args.port)
        print(f"[OK] Conectado exitosamente a {args.port} a {BAUD} baud.")
    except Exception as e:
        print(f"[ERROR CRÍTICO] {e}")
        sys.exit(1)

    # Inicializar CSV
    existe = os.path.exists(csv_path) and os.path.getsize(csv_path) > 0
    p = 0
    if existe:
        with open(csv_path, 'r', newline='') as fr:
            filas = [r for r in csv.reader(fr) if r]
            tiene_header = (len(filas) > 0 and filas[0][0] == 'clase')
            n_filas = len(filas) - 1 if tiene_header else len(filas)
            if n_filas % 2 != 0:
                print(f"  [CORRECCIÓN] Fila huérfana detectada ({n_filas} filas). Descartando última muestra...")
                with open(csv_path, 'w', newline='') as fw:
                    ww = csv.writer(fw)
                    for r in filas[:-1]:
                        ww.writerow(r)
                n_filas -= 1
            p = max(0, n_filas // 2)

    f_csv = open(csv_path, 'a', newline='')
    writer = csv.writer(f_csv)
    if not existe:
        writer.writerow(COLS)
        f_csv.flush()

    if p > 0:
        print(f"[REANUDANDO] Archivo con {p} pares ya registrados ({p * 2} muestras).")
        print(f"Continuando desde el par {p + 1} hasta {n_pares}...")
        if p >= n_pares:
            print("[INFO] El objetivo ya fue completado en este archivo.")
            f_csv.close()
            ser.close()
            return

    # Registro de pares descartados por el filtro de calidad (para reportar la tasa de rechazo)
    desc_path = csv_path.replace('.csv', '_descartes.csv')
    nuevo_desc = not os.path.exists(desc_path)
    f_desc = open(desc_path, 'a', newline='')
    w_desc = csv.writer(f_desc)
    if nuevo_desc:
        w_desc.writerow(['timestamp', 'clase', 'carga', 'motivo', 'detalle'])
    n_desc = 0

    global _raw_log
    _raw_log = open(csv_path.replace('.csv', '_serial.log'), 'a', buffering=1)

    meta_path = csv_path.replace('.csv', '_meta.json')
    try:
        fw_commit = subprocess.run(['git', '-C', os.path.expanduser('~/Arduino/PRUEBA_MODELO_1'), 'log', '-1', '--format=%h %s'],
                                   capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        fw_commit = ''
    meta = json.load(open(meta_path)) if os.path.exists(meta_path) else {'sesiones': []}
    sesion = {'inicio': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'clase': label_falla, 'carga': carga_str,
              'pares_previos': p, 'firmware': fw_commit, 'nota': args.nota, 'parametros': vars(args)}
    meta['sesiones'].append(sesion)

    def guardar_meta():
        with open(meta_path, 'w') as fm:
            json.dump(meta, fm, indent=2, ensure_ascii=False)
    guardar_meta()

    def descartar(motivo, detalle):
        nonlocal n_desc
        n_desc += 1
        w_desc.writerow([datetime.now().strftime('%Y-%m-%d %H:%M:%S'), clase, carga_str, motivo, detalle])
        f_desc.flush()
        print(f"[{p+1:3d}/{n_pares}] {label_falla:<5} -> [DESCARTADO] {motivo}: {detalle}")

    # Asegurar SSR apagado
    ssr_off(ser)
    t_off = time.time()

    # Comprobación previa: motor girando y corrientes plausibles antes del primer pulso
    ser.reset_input_buffer()
    d0, t_lim = None, time.time() + 30.0
    while time.time() < t_lim:
        raw = leer_linea(ser)
        d = parse_line(raw) if raw else None
        if d and d['motor'] == 'ON':
            d0 = d
            break
    if not d0:
        print("[ERROR] El firmware no reporta Motor:ON en 30 s. Arranca el motor y espera el warmup.")
        ssr_off(ser)
        ser.close()
        sys.exit(1)
    print(f"[PREVIO] I = {d0['ia']:.2f}/{d0['ib']:.2f}/{d0['ic']:.2f} A | V = {d0['va']:.1f}/{d0['vb']:.1f}/{d0['vc']:.1f} V | "
          f"U2V={d0['u2v']:.2f}% DE2={d0['de2_fw']:.2f}pp")
    sesion['previo'] = {k: d0[k] for k in ('ia', 'ib', 'ic', 'va', 'vb', 'vc', 'u2v', 'u2i', 'de2_fw')}
    guardar_meta()
    sanos_ref = []  # últimos SANO aceptados (referencia móvil del filtro de calidad)
    rechazos_sano = 0
    if args.duracion_pulso < args.t_min_on + 1.5:
        print(f"[ERROR] --duracion-pulso ({args.duracion_pulso}s) debe ser >= --t-min-on + 1.5 s")
        sys.exit(1)

    try:
        while p < n_pares:
            # 1. Fase SANO: esperar drenado completo tras el pulso previo
            espera = args.cooldown - (time.time() - t_off)
            if espera > 0:
                time.sleep(espera)
            ser.reset_input_buffer()

            d_sano = None
            t_lim = time.time() + 15.0
            while time.time() < t_lim:
                raw = leer_linea(ser)
                d = parse_line(raw) if raw else None
                if d and d['motor'] == 'ON' and d['ssr'] == 'OFF':
                    d_sano = d
                    break

            if not d_sano:
                print("  [ESPERA] Sin trama SANO válida (motor ON, SSR OFF) en 15 s...")
                continue
            t_sano_off = d_sano['t'] - t_off

            # Filtro 1: el SANO debe parecerse a los SANO recientes (detecta saltos de contacto)
            if len(sanos_ref) >= 3:
                ref = {k: sorted(x[k] for x in sanos_ref)[len(sanos_ref) // 2] for k in ('ia', 'ib', 'ic')}
                malas = fases_fuera(ref, d_sano, args.tol_i)
                if malas:
                    rechazos_sano += 1
                    if rechazos_sano >= 4:
                        # Cambio real y sostenido de carga o temperatura: se adopta el nivel nuevo
                        print(f"  [FILTRO] 4 SANO seguidos fuera de la referencia: se reinicia la referencia ({'; '.join(malas)})")
                        sanos_ref = [d_sano]
                        rechazos_sano = 0
                    else:
                        descartar('SANO inestable', '; '.join(malas))
                    t_off = time.time() - args.cooldown  # no hubo pulso: no esperar enfriamiento
                    continue
            rechazos_sano = 0

            # 2. Inyección de Falla (Activar SSR 1, fechar con confirmación del firmware)
            t_on = ssr_on_confirmado(ser)
            if t_on is None:
                ssr_off(ser)
                t_off = time.time()
                continue

            fallas = []
            while (time.time() - t_on) < args.duracion_pulso:
                raw = leer_linea(ser)
                d = parse_line(raw) if raw else None
                # Solo tramas cuya ventana de 1.70 s cae completa dentro del pulso
                if d and (d['t'] - t_on) >= args.t_min_on and d['ssr'] != 'OFF':
                    fallas.append(d)
            d_falla = fallas[-1] if fallas else None

            # 3. Desactivar
            ssr_off(ser)
            t_off = time.time()

            # Filtro 2: las tramas dentro del mismo pulso deben ser consistentes
            if len(fallas) < 2:
                descartar('Pulso con menos de 2 tramas completas', f'{len(fallas)} trama(s) con t_desde_on >= {args.t_min_on}s')
                continue
            a_, b_ = fallas[-2], fallas[-1]
            malas = fases_fuera(a_, b_, args.tol_i)
            if a_['de2_fw'] == a_['de2_fw'] and abs(a_['de2_fw'] - b_['de2_fw']) > args.tol_de2:
                malas.append(f"DE2 {a_['de2_fw']:.2f}->{b_['de2_fw']:.2f}pp")
            if malas:
                descartar('Salto dentro del pulso', '; '.join(malas))
                continue

            # 4. Validar si la inyección produjo evidencia física
            if d_falla:
                # Preferir el desplazamiento fasorial del firmware (independiente de la dirección);
                # con firmware antiguo se usa la diferencia escalar de e2
                if d_falla['de2_fw'] == d_falla['de2_fw']:  # no es NaN
                    salto_e2 = d_falla['de2_fw']
                else:
                    salto_e2 = d_falla['e2'] - d_sano['e2']
                if salto_e2 >= args.umbral_e2:
                    t_falla_on = d_falla['t'] - t_on
                    registrar_fila(writer, d_sano, 0, carga, (p * 2) + 1, -1.0, t_sano_off, 0.0)
                    registrar_fila(writer, d_falla, clase, carga, (p * 2) + 2, t_falla_on, -1.0, salto_e2)
                    f_csv.flush()

                    print(f"[{p+1:3d}/{n_pares}] SANO  -> e2={d_sano['e2']:4.2f}% | U2V={d_sano['u2v']:4.2f}% | I={d_sano['ic']:4.2f}A | t_off={t_sano_off:4.1f}s")
                    print(f"[{p+1:3d}/{n_pares}] {label_falla:<5} -> e2={d_falla['e2']:4.2f}% | U2V={d_falla['u2v']:4.2f}% | I={d_falla['ic']:4.2f}A | t_on={t_falla_on:4.1f}s (Δe2=+{salto_e2:.2f}pp)")
                    p += 1
                    sanos_ref = (sanos_ref + [d_sano])[-5:]
                else:
                    descartar('Salto insuficiente', f'DE2={salto_e2:+.2f}pp < {args.umbral_e2}')

        print("\n" + "=" * 80)
        print(f"  ¡CAMPAÑA COMPLETADA CON ÉXITO! Total: {p} pares ({p * 2} muestras)")
        print(f"  Pares descartados por el filtro de calidad: {n_desc} ({100 * n_desc / max(1, n_desc + p):.0f} %) -> {os.path.basename(desc_path)}")
        print(f"  Archivo guardado en: {csv_path}")
        print("=" * 80)

    except KeyboardInterrupt:
        print("\n\n[DETENIDO] Captura pausada por el usuario.")
    finally:
        sesion.update({'fin': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'pares_total': p, 'descartes': n_desc})
        guardar_meta()
        ssr_off(ser)
        f_csv.close()
        f_desc.close()
        _raw_log.close()
        ser.close()
        print("[SEGURIDAD] SSR apagado y puerto serial cerrado.")

if __name__ == "__main__":
    main()
