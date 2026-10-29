#!/usr/bin/env python3
"""
Prueba larga sin falla: reinicio de alarmas atascadas (enmienda del 12-oct-2026).

Sigue el _serial.log que escribe prueba_larga_sin_falla.py (no lee el puerto, para no quitarle tramas)
y, si la alarma del detector (C=1) sigue enclavada mas de --max-s segundos, abre el puerto solo para
escribir 'r' (reinicio del detector; no toca el SSR) y lo registra en <log>_reinicios.csv.
Termina cuando el log deja de crecer durante --fin-s segundos (el script de la prueba termino).

Uso: python3 reinicio_alarma_atascada.py ~/tesis_itf/prueba_larga/larga_AAAAMMDD_HHMM_serial.log
"""
import argparse
import re
import time

import serial

RE_DIR = re.compile(r"DIR:\s+P=([-\d.]+)\s+R=(\d+)\s+C=(\d)\s+REF=(\d)\s+CUSUM=(\d)\s+SEV=(\d)\s+ML=([-\d.]+)\s+PL=([-\d.]+)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('log')
    ap.add_argument('--port', default='/dev/ttyACM0')
    ap.add_argument('--max-s', type=float, default=60.0)
    ap.add_argument('--fin-s', type=float, default=30.0)
    args = ap.parse_args()

    reg = open(args.log.replace('_serial.log', '_reinicios.csv'), 'a', buffering=1)
    reg.write('t_envio,t_inicio_alarma,duracion_s,sev,ml,pl\n')
    f = open(args.log, 'r', errors='ignore')
    t_c1 = None
    ult_dato = time.time()
    espera_c0 = False
    while True:
        linea = f.readline()
        if not linea:
            if time.time() - ult_dato > args.fin_s:
                break
            time.sleep(0.2)
            continue
        ult_dato = time.time()
        partes = linea.split(' ', 1)
        d = RE_DIR.search(linea)
        if not d or len(partes) < 2:
            continue
        t = float(partes[0])
        c = d.group(3)
        if c == '0':
            t_c1 = None
            espera_c0 = False
            continue
        if espera_c0:
            continue
        if t_c1 is None:
            t_c1 = t
        elif t - t_c1 > args.max_s:
            with serial.Serial(args.port, 115200, timeout=1) as s:
                s.write(b'r\n')
                s.flush()
            ahora = time.time()
            reg.write(f"{ahora:.3f},{t_c1:.3f},{t - t_c1:.1f},{d.group(6)},{d.group(7)},{d.group(8)}\n")
            print(time.strftime('%H:%M:%S'), f"alarma atascada {t - t_c1:.0f} s (SEV={d.group(6)} ML={d.group(7)}) -> enviado 'r'", flush=True)
            espera_c0 = True
    reg.close()
    print(time.strftime('%H:%M:%S'), 'fin: el log dejo de crecer', flush=True)


if __name__ == '__main__':
    main()
