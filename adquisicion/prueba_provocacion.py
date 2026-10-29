#!/usr/bin/env python3
"""
MotorGuard-ITF: prueba de provocación de conexiones (protoboard).

Mide la estabilidad de los 6 canales con el motor girando y el SSR apagado:
  1) REFERENCIA: 40 s sin tocar nada.
  2) Por cada módulo y por los rieles de la protoboard: 15 s moviendo con suavidad
     y dando golpecitos a sus cables, seguidos de 6 s de reposo.
Al final compara cada tramo contra la referencia y emite un veredicto.

Uso (en una terminal junto al banco, motor ya girando y fuera del warmup):
  python3 ~/prueba_provocacion.py
  python3 ~/prueba_provocacion.py --analizar ~/provocacion_YYYYMMDD_HHMMSS.log   # re-analizar un log
"""
import argparse
import os
import re
import sys
import time
from datetime import datetime
from statistics import median

PORT = "/dev/ttyACM0"
BAUD = 115200
T_REF = 40.0
T_PROV = 15.0
T_REPOSO = 6.0
TRAMOS = [
    ("IA", "Cables del sensor de corriente fase A (VCC, GND, OUT)"),
    ("IB", "Cables del sensor de corriente fase B"),
    ("IC", "Cables del sensor de corriente fase C"),
    ("VA", "Cables del sensor de voltaje fase A"),
    ("VB", "Cables del sensor de voltaje fase B"),
    ("VC", "Cables del sensor de voltaje fase C"),
    ("RIELES", "Rieles de 5 V, 3.3 V y GND de la protoboard y cables al Arduino"),
    ("GOLPES", "Golpecitos suaves sobre la mesa y la protoboard, sin tocar cables"),
]
CANALES = ["IA", "IB", "IC", "VA", "VB", "VC"]
# Umbral mínimo de desviación por tipo de canal (además de 5 veces la dispersión de la referencia)
PISO = {"I": 0.04, "V": 1.0, "R2": 0.50}

RX_RAW = re.compile(r"RAW: R2=(-?[\d.]+),(-?[\d.]+) I1=([\d.]+)")


def parse(line):
    if "[MCSA] Motor:ON" not in line:
        return None
    d = {}
    for k in CANALES:
        m = re.search(rf"\b{k}=([\d.]+)", line)
        if not m:
            return None
        d[k] = float(m.group(1))
    m = RX_RAW.search(line)
    if m and float(m.group(3)) > 0:
        i1 = float(m.group(3))
        d["R2"] = complex(float(m.group(1)), float(m.group(2))) / i1 * 100.0
    d["alarma"] = "| LEVE |" in line
    return d


def mad(xs):
    m = median(xs)
    return median([abs(x - m) for x in xs]) * 1.4826


def analizar(path):
    orden = []  # (tramo, datos) en el orden del log
    for l in open(path, encoding="utf-8", errors="replace"):
        m = re.match(r"\s*[\d.]+s \[(\w+)\] (.*)", l)
        if not m:
            continue
        d = parse(m.group(2))
        if d:
            orden.append((m.group(1), d))
    # Señal diferencial: cada canal menos el promedio de sus dos compañeros del mismo tipo.
    # Un cambio de red o de carga mueve las tres fases juntas y se cancela; un mal contacto no.
    for _, d in orden:
        for grupo in (CANALES[:3], CANALES[3:]):
            for k in grupo:
                otros = [d[j] for j in grupo if j != k]
                d["d" + k] = d[k] - sum(otros) / len(otros)
    ref = [d for t, d in orden if t == "REF"]
    if len(ref) < 10:
        print(f"[ERROR] Solo hay {len(ref)} tramas de referencia (se necesitan >= 10). ¿Motor girando y fuera del warmup?")
        return 2
    # Ruido de referencia: dispersión robusta de los cambios bloque a bloque
    ruido = {}
    for k in CANALES:
        xs = [d["d" + k] for d in ref]
        ruido[k] = mad([b - a for a, b in zip(xs, xs[1:])])
    r2ref = [d["R2"] for d in ref if "R2" in d]
    ruido["R2"] = mad([abs(b - a) for a, b in zip(r2ref, r2ref[1:])]) if len(r2ref) > 2 else 0.0

    def umbral(k):
        tipo = "R2" if k == "R2" else ("I" if k.startswith("I") else "V")
        piso = {"I": 0.04, "V": 3.5, "R2": 0.6}[tipo]  # calibrados con logs reales del 01-oct-2026
        return max(5 * ruido[k], piso)

    print("\n" + "=" * 88)
    print("  PRUEBA DE PROVOCACIÓN")
    print("  Cada tramo se compara con los 6 bloques previos. Los canales se miden contra el promedio")
    print("  de sus dos compañeros, así que los cambios de red o de carga no cuentan como saltos.")
    print("=" * 88)
    print(f"  {'Tramo':<8} {'n':>3}  " + "  ".join(f"{k:>7}" for k in CANALES) + f"  {'R2(pp)':>7}  Veredicto")
    fallas = []
    for nombre, _ in TRAMOS:
        idx = [i for i, (t, _) in enumerate(orden) if t in (nombre, nombre + "_R")]
        if not idx:
            print(f"  {nombre:<8} sin datos")
            continue
        previos = [orden[i][1] for i in range(max(0, idx[0] - 6), idx[0])]
        if len(previos) < 3:
            print(f"  {nombre:<8} sin bloques previos suficientes")
            continue
        ds = [orden[i][1] for i in idx]
        cols, malos = [], []
        for k in CANALES:
            base = median([d["d" + k] for d in previos])
            dev = max(abs(d["d" + k] - base) for d in ds)
            cols.append(dev)
            if dev > umbral(k) + 1e-9:
                malos.append(k)
        r2p = [d["R2"] for d in previos if "R2" in d]
        r2dev = float("nan")
        if r2p:
            c0 = complex(median([z.real for z in r2p]), median([z.imag for z in r2p]))
            r2dev = max(abs(d["R2"] - c0) for d in ds if "R2" in d)
            if r2dev > umbral("R2") + 1e-9:
                malos.append("R2")
        if malos:
            fallas.append((nombre, malos))
        ver = "OK" if not malos else "SALTO en " + ", ".join(malos)
        print(f"  {nombre:<8} {len(ds):>3}  " + "  ".join(f"{c:>7.3f}" for c in cols) + f"  {r2dev:>7.2f}  {ver}")
    alarmas = sum(d["alarma"] for _, d in orden if _ != "ESPERA")
    print("-" * 88)
    print("  Columnas: mayor cambio diferencial del canal en el tramo (A para corrientes, V para voltajes).")
    print(f"  Umbrales: corrientes {max(umbral(k) for k in CANALES[:3]):.3f} A · voltajes {max(umbral(k) for k in CANALES[3:]):.2f} V · residuo {umbral('R2'):.2f} pp")
    print(f"  Tramas en alarma del firmware durante la prueba: {alarmas}")
    print("=" * 88)
    if fallas:
        print("  RESULTADO: NO APROBADA. Revisa y fija estas conexiones antes de la sesión:")
        for n, ks in fallas:
            print(f"    · Al mover {n}: saltó {', '.join(ks)}")
        return 1
    print("  RESULTADO: APROBADA. Las conexiones son estables; puedes iniciar la sesión.")
    return 0


def conectar():
    import serial
    t0 = time.time()
    while time.time() - t0 < 60:
        if os.path.exists(PORT):
            try:
                return serial.Serial(PORT, BAUD, timeout=1)
            except Exception:
                pass
        time.sleep(1)
    print(f"[ERROR] No encuentro {PORT}. ¿Está conectado el Arduino?")
    sys.exit(2)


def correr():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.expanduser(f"~/provocacion_{ts}.log")
    s = conectar()
    s.write(b"0\n")
    s.flush()
    out = open(path, "w", encoding="utf-8")
    out.write(f"# Prueba de provocación {ts}\n")
    t0 = time.time()
    tag = ["ESPERA"]

    def leer(dur, cuenta=None):
        t = time.time()
        ultimo = -1
        while time.time() - t < dur:
            l = s.readline().decode(errors="replace").rstrip()
            if l:
                out.write(f"{time.time() - t0:8.2f}s [{tag[0]}] {l}\n")
                out.flush()
            if cuenta:
                rest = int(dur - (time.time() - t)) + 1
                if rest != ultimo and rest > 0:
                    ultimo = rest
                    print(f"\r    {cuenta}: {rest:2d} s ", end="", flush=True)
        if cuenta:
            print("\r" + " " * 60 + "\r", end="")

    print("Esperando telemetría con el motor girando (fuera del warmup)...")
    t_w = time.time()
    while True:
        l = s.readline().decode(errors="replace").rstrip()
        if l:
            out.write(f"{time.time() - t0:8.2f}s [ESPERA] {l}\n")
        if "[MCSA] Motor:ON" in l:
            break
        if time.time() - t_w > 180:
            print("[ERROR] En 3 min no llegó ninguna trama 'Motor:ON'. Enciende el motor y espera a que termine el warmup.")
            sys.exit(2)
    print("\nMotor detectado. NO TOQUES NADA durante la referencia.\a")
    tag[0] = "REF"
    leer(T_REF, "Referencia, sin tocar")
    for i, (nombre, desc) in enumerate(TRAMOS, 1):
        print(f"\n[{i}/{len(TRAMOS)}] {nombre}: {desc}\a")
        print("    Mueve con suavidad y da golpecitos a esos cables (sin desconectarlos).")
        tag[0] = nombre
        leer(T_PROV, "Moviendo")
        print("    Suelta y no toques nada.")
        tag[0] = nombre + "_R"
        leer(T_REPOSO, "Reposo")
    s.write(b"0\n")
    s.close()
    out.close()
    print(f"\nLog guardado en {path}")
    return analizar(path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Prueba de provocación de conexiones MotorGuard-ITF")
    ap.add_argument("--analizar", metavar="LOG", help="Re-analizar un log existente sin correr la prueba")
    a = ap.parse_args()
    sys.exit(analizar(a.analizar) if a.analizar else correr())
