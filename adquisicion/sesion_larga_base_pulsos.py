#!/usr/bin/env python3
"""
MotorGuard-ITF: sesion larga de adquisicion (base sana + tren de pulsos).

Registra TODAS las lineas seriales con marca de tiempo y etiqueta de fase
(WAIT / WARMUP / BASE / Pk_ON / Pk_OFF), para diseñar el detector offline
con los fasores crudos (campo RAW de la trama [MCSA]).

Uso:
  python3 sesion_larga_base_pulsos.py --falla LEVE --carga 50% --base-min 30 --pulsos 10
"""
import argparse
import sys
import time
from datetime import datetime

import serial

ap = argparse.ArgumentParser()
ap.add_argument("--falla", required=True, help="Etiqueta de los taps conectados (LEVE/INTER/SEVERA)")
ap.add_argument("--carga", required=True, help="Carga mecanica (p.ej. 50%%)")
ap.add_argument("--base-min", type=float, default=30.0, help="Minutos de base sana tras el warmup")
ap.add_argument("--pulsos", type=int, default=10)
ap.add_argument("--t-on", type=float, default=6.0, help="Duracion de cada pulso (s)")
ap.add_argument("--t-off", type=float, default=30.0, help="Reposo tras cada pulso (s)")
ap.add_argument("--port", default="/dev/ttyACM0")
ap.add_argument("--espera-min", type=float, default=15.0, help="Minutos maximos esperando el encendido del motor")
args = ap.parse_args()

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
carga_tag = args.carga.replace("%", "")
out_path = f"/home/luna/sesion_{args.falla}_{carga_tag}carga_{ts}.log"
out = open(out_path, "w")
out.write(f"# Sesion larga: falla={args.falla} carga={args.carga} base={args.base_min} min "
          f"pulsos={args.pulsos}x{args.t_on}s reposo={args.t_off}s inicio={ts}\n")
print(f"LOG: {out_path}", flush=True)

import os
print(f"Esperando puerto {args.port}...", flush=True)
_tp = time.time()
while True:
    if os.path.exists(args.port):
        try:
            s = serial.Serial(args.port, 115200, timeout=1)
            break
        except serial.SerialException:
            pass
    if time.time() - _tp > args.espera_min * 60:
        print("TIMEOUT: el puerto serial no aparecio", flush=True)
        sys.exit(1)
    time.sleep(1)
print("Puerto conectado", flush=True)
t0 = time.time()
fase = "WAIT"
EVENTOS = ("IA ->", "[RED]", "Motor ON", "Motor apagado", "Motor:OFF", "[DEBUG SSR]", "Zero SSR")
ultimo_off = [0.0]


def log_linea(l):
    out.write(f"{time.time() - t0:8.2f}s [{fase}] {l}\n")
    out.flush()


def leer(dur, eco=True):
    t = time.time()
    while time.time() - t < dur:
        l = s.readline().decode(errors="replace").rstrip()
        if not l:
            continue
        log_linea(l)
        if "Motor:OFF" in l and fase not in ("WAIT",):
            # Un corte de alimentacion invalida la sesion: avisar una vez cada 30 s
            if time.time() - ultimo_off[0] > 30:
                ultimo_off[0] = time.time()
                print(f"{time.time() - t0:7.1f}s [{fase}] ALERTA: Motor:OFF detectado", flush=True)
        elif eco and any(k in l for k in EVENTOS) and "MOTOR_DET" not in l:
            print(f"{time.time() - t0:7.1f}s [{fase}] {l[:120]}", flush=True)


def esperar(token, timeout):
    t = time.time()
    while time.time() - t < timeout:
        l = s.readline().decode(errors="replace").rstrip()
        if not l:
            continue
        log_linea(l)
        if any(tok in l for tok in (token if isinstance(token, tuple) else (token,))):
            return l
    return None


try:
    s.write(b"0\n")
    s.flush()
    print("Esperando motor encendido...", flush=True)
    l_on = esperar(("Motor ON", "Motor:WARMUP", "Motor:ON"), args.espera_min * 60)
    if not l_on:
        print(f"TIMEOUT: el motor no encendio en {args.espera_min} min", flush=True)
        sys.exit(1)
    if "Motor:ON" in l_on:
        print(f"{time.time() - t0:7.1f}s Motor ya en marcha (warmup completado)", flush=True)
    else:
        fase = "WARMUP"
        print(f"{time.time() - t0:7.1f}s Motor ON, warmup 60 s", flush=True)
        if not esperar("IA -> SANO", 120):
            print("AVISO: no se observo fin de warmup en 120 s; se continua", flush=True)

    fase = "BASE"
    print(f"{time.time() - t0:7.1f}s BASE {args.base_min} min (SSR OFF)", flush=True)
    t_base = time.time()
    while time.time() - t_base < args.base_min * 60:
        leer(min(300, args.base_min * 60 - (time.time() - t_base)))
        print(f"{time.time() - t0:7.1f}s [BASE] progreso {(time.time() - t_base) / 60:.1f}/{args.base_min} min", flush=True)

    for k in range(1, args.pulsos + 1):
        fase = f"P{k}_ON"
        s.reset_input_buffer()
        s.write(b"1\n")
        s.flush()
        leer(args.t_on, eco=False)
        s.write(b"0\n")
        s.flush()
        fase = f"P{k}_OFF"
        leer(args.t_off, eco=False)
        print(f"{time.time() - t0:7.1f}s pulso {k}/{args.pulsos} completado", flush=True)
    print("FIN SESION", flush=True)
finally:
    s.write(b"0\n")
    s.flush()
    time.sleep(0.2)
    s.close()
    out.close()
