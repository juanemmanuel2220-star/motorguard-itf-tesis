#!/usr/bin/env python3
"""
Resumen de una sesión de la app con el Arduino, a partir de lo que la app grabó:
  <base>_serial.log (y sus partes _pNNN), <base>_eventos.csv, <base>_pulsos.csv y app.log.

Reporta tramas, huecos, estados del motor, comandos enviados, respuesta del firmware a cada '1', duración
real de cada pulso (T_ON del firmware), alarmas, reconexiones, consultas a petición y su efecto en la trama
siguiente, y errores en app.log. Hace comprobaciones automáticas (declaradas en el protocolo de la prueba en
vivo) y escribe <base>_resumen.md y <base>_resumen.json junto al log.

Uso: python -m motorguard_dashboard.herramientas.resumen_sesion RUTA/sesion_<sello>_serial.log [--app-log RUTA]
     python -m motorguard_dashboard.herramientas.resumen_sesion CARPETA      (toma la sesión más reciente)
"""

import argparse
import csv
import glob
import json
import os
import re
import statistics
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from motorguard_dashboard.telemetry.parser import EventoSSR, Trama, parsear_linea  # noqa: E402

RESPUESTA_FW_MAX_S = 1.0     # el firmware confirma o rechaza un '1' en menos de 1 s
T_ON_MAX_MS = 12_000         # corte del firmware
HUECO_S = 5.0                # hueco entre tramas que se reporta (normal: ~1.7 s)
_RE_LINEA = re.compile(r"^(\d+\.\d+) (.*)$")


def _hora(t):
    return datetime.fromtimestamp(t).strftime("%H:%M:%S") if t else "—"


def _archivos(ruta):
    """(base, [partes del log crudo en orden], eventos.csv, pulsos.csv)"""
    if os.path.isdir(ruta):
        logs = sorted(glob.glob(os.path.join(ruta, "sesion_*_serial.log")), key=os.path.getmtime)
        logs = [x for x in logs if not re.search(r"_p\d{3}_serial\.log$", x)] or logs
        if not logs:
            raise SystemExit(f"no hay sesiones (sesion_*_serial.log) en {ruta}")
        ruta = logs[-1]
    base = ruta[:-len("_serial.log")] if ruta.endswith("_serial.log") else os.path.splitext(ruta)[0]
    partes = [ruta] + sorted(glob.glob(f"{base}_p[0-9][0-9][0-9]_serial.log"))
    carpeta = os.path.dirname(ruta)

    def hermano(sufijo, generico):
        for c in (f"{base}_{sufijo}", os.path.join(carpeta, generico)):
            if os.path.isfile(c):
                return c
        return None
    return base, partes, hermano("eventos.csv", "eventos.csv"), hermano("pulsos.csv", "pulsos.csv")


def _leer_crudo(partes):
    lineas = []
    for p in partes:
        with open(p, encoding="utf-8", errors="ignore") as f:
            for x in f:
                m = _RE_LINEA.match(x.rstrip("\n"))
                if m:
                    lineas.append((float(m.group(1)), m.group(2)))
    return lineas


def _leer_csv(ruta):
    if not ruta:
        return []
    with open(ruta, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _errores_app_log(ruta_log, t0, t1):
    if not ruta_log or not os.path.isfile(ruta_log):
        return None, []
    errores = []
    for ruta in [ruta_log] + sorted(glob.glob(ruta_log + ".*")):
        with open(ruta, encoding="utf-8", errors="ignore") as f:
            for x in f:
                m = re.match(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ (ERROR|CRITICAL)", x)
                if m:
                    t = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
                    if t0 - 1 <= t <= t1 + 1:
                        errores.append(x.strip())
    return len(errores), errores


def analizar(partes, eventos_csv, pulsos_csv, ruta_app_log):
    lineas = _leer_crudo(partes)
    if not lineas:
        raise SystemExit("el log crudo está vacío")
    t0, t1 = lineas[0][0], lineas[-1][0]
    tramas, ssr, tx = [], [], []
    for t, texto in lineas:
        if texto.startswith(">> TX "):
            tx.append((t, texto[6:].strip()))
            continue
        o = parsear_linea(texto)
        if isinstance(o, Trama):
            tramas.append((t, o))
        elif isinstance(o, EventoSSR):
            ssr.append((t, o))

    # Tramas y huecos
    intervalos = [b[0] - a[0] for a, b in zip(tramas, tramas[1:])]
    huecos = [(a[0], b[0] - a[0]) for a, b in zip(tramas, tramas[1:]) if b[0] - a[0] > HUECO_S]

    # Estados del motor
    motor = []
    for t, o in tramas:
        if not motor or motor[-1][1] != o.motor:
            motor.append((t, o.motor))

    # Cada '1': respuesta del firmware y apagado
    pulsos_fw = []
    for t_cmd, c in tx:
        if c != "1":
            continue
        resp = next(((t, e) for t, e in ssr if t >= t_cmd and e.tipo in ("encendido", "rechazado")), None)
        p = {"t_cmd": t_cmd, "respuesta": None, "latencia_s": None, "t_on_ms": None, "forzado": None}
        if resp:
            p["respuesta"] = resp[1].tipo if resp[1].tipo == "rechazado" else "encendido"
            p["latencia_s"] = round(resp[0] - t_cmd, 3)
            if resp[1].tipo == "encendido":
                apag = next(((t, e) for t, e in ssr if t >= resp[0] and e.tipo == "apagado"), None)
                if apag:
                    p["t_on_ms"], p["forzado"] = apag[1].t_on_ms, apag[1].forzado
        pulsos_fw.append(p)

    # Consultas a petición: retraso de la trama siguiente
    consultas = []
    for t_cmd, c in tx:
        if c in ("W", "f", "s"):
            antes = [t for t, _ in tramas if t <= t_cmd]
            despues = [t for t, _ in tramas if t > t_cmd]
            if antes and despues:
                consultas.append({"cmd": c, "t": t_cmd, "intervalo_tramas_s": round(despues[0] - antes[-1], 2)})

    eventos = _leer_csv(eventos_csv)
    alarmas = [e for e in eventos if e.get("tipo") == "ALARMA"]
    conexion = [e for e in eventos if e.get("tipo") == "CONEXION"]
    pulsos_app = _leer_csv(pulsos_csv)
    n_err, errores = _errores_app_log(ruta_app_log, t0, t1)

    confirmados = [p for p in pulsos_fw if p["respuesta"] == "encendido"]
    comprobaciones = [
        ("Cada '1' tuvo respuesta del firmware en ≤ 1 s",
         all(p["latencia_s"] is not None and p["latencia_s"] <= RESPUESTA_FW_MAX_S for p in pulsos_fw)),
        ("Todo pulso confirmado se apagó (mensaje 'Apagado' del firmware)",
         all(p["t_on_ms"] is not None for p in confirmados)),
        ("Ningún pulso pasó de 12 s encendido (T_ON del firmware)",
         all((p["t_on_ms"] or 0) <= T_ON_MAX_MS for p in confirmados)),
        ("Al conectar se envió '0' (primer comando de la sesión)", bool(tx) and tx[0][1] == "0"),
        ("Solo salieron comandos permitidos ('1', '0', 'W', 'f', 's' y 'r' para liberar una alarma)",
         all(c in ("1", "0", "W", "f", "s", "r") for _, c in tx)),
        ("Sin errores en app.log durante la sesión", n_err == 0 if n_err is not None else None),
    ]
    return {
        "inicio": _hora(t0), "fin": _hora(t1), "duracion_min": round((t1 - t0) / 60, 1),
        "partes_log": [os.path.basename(p) for p in partes],
        "tramas": len(tramas),
        "intervalo_mediano_s": round(statistics.median(intervalos), 3) if intervalos else None,
        "intervalo_max_s": round(max(intervalos), 2) if intervalos else None,
        "huecos": [{"desde": _hora(t), "s": round(d, 1)} for t, d in huecos],
        "motor": [{"hora": _hora(t), "estado": e} for t, e in motor],
        "comandos": {c: sum(1 for _, x in tx if x == c) for c in sorted({x for _, x in tx})},
        "pulsos_firmware": [{**p, "t_cmd": _hora(p["t_cmd"])} for p in pulsos_fw],
        "pulsos_app": pulsos_app,
        "alarmas": alarmas,
        "conexion": conexion,
        "consultas": consultas,
        "errores_app_log": n_err, "errores_detalle": errores[:20],
        "comprobaciones": [{"descripcion": d, "ok": ok} for d, ok in comprobaciones],
    }


def a_markdown(r, nombre):
    def marca(ok):
        return "✅" if ok else ("—" if ok is None else "❌")
    L = [f"# Resumen de la sesión `{nombre}`", "",
         f"- {r['inicio']} – {r['fin']} ({r['duracion_min']} min), log: {', '.join(r['partes_log'])}",
         f"- Tramas: {r['tramas']} · intervalo mediano {r['intervalo_mediano_s']} s · máximo {r['intervalo_max_s']} s",
         f"- Comandos enviados: {r['comandos']}",
         f"- Errores en app.log durante la sesión: {r['errores_app_log'] if r['errores_app_log'] is not None else 'sin app.log'}",
         "", "## Comprobaciones", "", "| | Comprobación |", "|---|---|"]
    L += [f"| {marca(c['ok'])} | {c['descripcion']} |" for c in r["comprobaciones"]]
    L += ["", "## Estados del motor", "", " → ".join(f"{m['estado']} ({m['hora']})" for m in r["motor"]) or "—"]
    if r["huecos"]:
        L += ["", f"## Huecos entre tramas > {HUECO_S:g} s", ""] + [f"- {h['desde']}: {h['s']} s" for h in r["huecos"]]
    L += ["", "## Pulsos (según el firmware)", "", "| # | Pedido | Respuesta | Latencia (s) | T_ON (ms) | Forzado |",
          "|---|---|---|---|---|---|"]
    for k, p in enumerate(r["pulsos_firmware"], 1):
        L.append(f"| {k} | {p['t_cmd']} | {p['respuesta'] or 'sin respuesta'} | {p['latencia_s'] if p['latencia_s'] is not None else '—'} "
                 f"| {p['t_on_ms'] if p['t_on_ms'] is not None else '—'} | {'' if p['forzado'] is None else int(p['forzado'])} |")
    if r["pulsos_app"]:
        L += ["", "## Pulsos (registro de la app)", "",
              "| # | Taps | Duración pedida (s) | Firmware | Resultado | Alarma | Latencia alarma (s) | Severidad | ML máx (pp) |",
              "|---|---|---|---|---|---|---|---|---|"]
        for p in r["pulsos_app"]:
            L.append(f"| {p['n']} | {p['taps_declarados']} | {p['duracion_pedida_s']} | {p['confirmacion_fw']} | {p['resultado']} "
                     f"| {'sí' if p['alarma_confirmada'] == '1' else 'no'} | {p['latencia_alarma_s']} | {p['sev_max']} | {p['ml_max_pp']} |")
    L += ["", "## Alarmas", "", "| Inicio | Fin | Duración (s) | Sev. máx. | ML máx (pp) | Motivo de fin |", "|---|---|---|---|---|---|"]
    L += [f"| {a['inicio']} | {a['fin']} | {a['duracion_s']} | {a['sev_max']} | {a['ml_max']} | {a['motivo_fin']} |" for a in r["alarmas"]]
    if r["conexion"]:
        L += ["", "## Conexión", ""] + [f"- {c['inicio']}: {c['detalle']}" for c in r["conexion"]]
    if r["consultas"]:
        L += ["", "## Consultas a petición", "", "| Consulta | Intervalo entre la trama anterior y la siguiente (s) |", "|---|---|"]
        L += [f"| {c['cmd']} | {c['intervalo_tramas_s']} |" for c in r["consultas"]]
    if r["errores_detalle"]:
        L += ["", "## Errores en app.log", "", "```"] + r["errores_detalle"] + ["```"]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Resumen de una sesión de MotorGuard-ITF con el Arduino")
    ap.add_argument("ruta", help="sesion_<sello>_serial.log o la carpeta de registros")
    ap.add_argument("--app-log", default=None, help="app.log (por defecto, el de la carpeta de datos de la app)")
    args = ap.parse_args()
    base, partes, ev, pu = _archivos(args.ruta)
    ruta_app_log = args.app_log
    if ruta_app_log is None:
        from motorguard_dashboard.sistema import rutas
        ruta_app_log = os.path.join(rutas.dir_logs_app(), "app.log")
    r = analizar(partes, ev, pu, ruta_app_log)
    nombre = os.path.basename(base)
    with open(f"{base}_resumen.json", "w", encoding="utf-8") as f:
        json.dump(r, f, indent=2, ensure_ascii=False)
    with open(f"{base}_resumen.md", "w", encoding="utf-8") as f:
        f.write(a_markdown(r, nombre))
    malas = [c["descripcion"] for c in r["comprobaciones"] if c["ok"] is False]
    print(f"{nombre}: {r['tramas']} tramas, {len(r['pulsos_firmware'])} pulsos, {len(r['alarmas'])} alarmas · "
          + ("todas las comprobaciones OK" if not malas else "FALLAN: " + "; ".join(malas)))
    print(f"Resumen: {base}_resumen.md")
    return 1 if malas else 0


if __name__ == "__main__":
    sys.exit(main())
