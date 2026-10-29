#!/usr/bin/env python3
"""
Prueba de resistencia ACELERADA: el equivalente a N horas (24 por defecto) de telemetría pasando por la
ventana completa, lo más rápido posible, para ver si la memoria crece sin límite o la interfaz se vuelve
lenta con el tiempo.

Datos: las líneas REALES de los logs del firmware 299a943 (validacion_vivo, con SEV), repetidas en ciclo
con sus marcas de tiempo desplazadas para que el tiempo avance de forma continua. No se inventan valores.
Cada trama entra por el mismo slot que usa la fuente real (MonitorWindow._on_dato), en el hilo principal.

Criterios (declarados antes de correr):
  - crecimiento de memoria entre la hora 1 y el final <= 30 MB
  - tiempo por trama en el percentil 99 <= 20 ms (el firmware manda una cada 1.7 s)
  - 0 errores en app.log

Uso: python -m motorguard_dashboard.herramientas.resistencia_acelerada [--horas 24] [--salida DIR]
"""

import argparse
import glob
import os
import sys
import time
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from motorguard_dashboard.herramientas.medicion import cpu_s, guardar, percentil, rss_mb  # noqa: E402
from motorguard_dashboard.telemetry.parser import Trama, parsear_linea  # noqa: E402

LOGS = os.path.expanduser("~/tesis_itf/validacion_vivo/*_serial.log")
CRECIMIENTO_MAX_MB = 30.0
P99_MAX_MS = 20.0


class FuenteNula(QObject):
    """La ventana necesita una fuente con estas señales; aquí los datos se entregan a mano."""
    sig_dato = Signal(object)
    sig_descartada = Signal(str)
    sig_estado = Signal(bool, str)
    sig_respuesta = Signal(object)

    def start(self):
        self.sig_estado.emit(True, "PRUEBA DE RESISTENCIA (acelerada)")

    def detener(self):
        pass

    def isRunning(self):
        return True


def cargar_sesiones():
    """Listas de objetos parseados por log del firmware 299a943, con su duración."""
    sesiones = []
    for ruta in sorted(glob.glob(LOGS)):
        objs = [o for o in map(parsear_linea, open(ruta, encoding="utf-8", errors="ignore")) if o is not None and o.t]
        if any(isinstance(o, Trama) for o in objs):
            sesiones.append(objs)
    return sesiones


def secuencia(sesiones, horas):
    """Genera los objetos en ciclo, desplazando el tiempo para que avance sin saltos hacia atrás."""
    import dataclasses
    fin = horas * 3600.0
    desplazado = 0.0
    t0 = None
    while True:
        for objs in sesiones:
            base = objs[0].t
            for o in objs:
                t = desplazado + (o.t - base)
                if t > fin:
                    return
                if t0 is None:
                    t0 = time.time()
                yield dataclasses.replace(o, t=t0 + t), t / 3600.0
            desplazado += (objs[-1].t - base) + 5.0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--horas", type=float, default=24.0)
    ap.add_argument("--salida", default=os.path.expanduser(
        f"~/tesis_itf/app_pruebas/resistencia_acelerada_{datetime.now():%Y%m%d_%H%M%S}"))
    args = ap.parse_args()
    os.makedirs(args.salida, exist_ok=True)

    app = QApplication([])
    from motorguard_dashboard.sistema import bitacora
    ruta_log = bitacora.configurar(args.salida, a_consola=False)
    errores = []
    bitacora.notificador.error.connect(errores.append)
    from motorguard_dashboard.telemetry.alarmas import RegistroAlarmas
    from motorguard_dashboard.ui.monitor_window import MonitorWindow
    from motorguard_dashboard.ui.tema import GestorTema, cargar_fuentes
    cargar_fuentes()
    tema = GestorTema(app, persistir=False, modo="claro")
    w = MonitorWindow(FuenteNula(), RegistroAlarmas(os.path.join(args.salida, "eventos.csv")), True,
                      "resistencia", tema=tema)
    w.resize(1440, 920)
    w.show()
    app.processEvents()

    sesiones = cargar_sesiones()
    print(f"{len(sesiones)} sesiones reales del firmware 299a943; simulando {args.horas:g} h")
    muestras, tiempos_ventana, todos = [], [], []
    n_tramas, n_obj = 0, 0
    rss0 = rss_mb()
    rss_hora1 = None
    t_ini, cpu_ini = time.perf_counter(), cpu_s()
    siguiente_cambio = 6.0
    for obj, horas in secuencia(sesiones, args.horas):
        t = time.perf_counter()
        w._on_dato(obj)
        dt = (time.perf_counter() - t) * 1000.0
        n_obj += 1
        if isinstance(obj, Trama):
            n_tramas += 1
            tiempos_ventana.append(dt)
            todos.append(dt)
        if n_obj % 200 == 0:
            app.processEvents()
        if horas >= siguiente_cambio:            # ejercitar tema y navegación durante la prueba
            tema.poner_modo("oscuro" if tema.modo == "claro" else "claro")
            w.ir_a(int(siguiente_cambio // 6) % 3)
            siguiente_cambio += 6.0
        if n_tramas and n_tramas % 1000 == 0 and tiempos_ventana:
            app.processEvents()
            r = rss_mb()
            if rss_hora1 is None and horas >= 1.0:
                rss_hora1 = r
            muestras.append({"horas_simuladas": round(horas, 3), "tramas": n_tramas, "rss_mb": round(r, 1),
                             "ms_p50": round(percentil(tiempos_ventana, 50), 3),
                             "ms_p99": round(percentil(tiempos_ventana, 99), 3),
                             "filas_tabla": w.tabla.rowCount(), "widgets": len(app.allWidgets())})
            print(f"  {horas:6.2f} h  {n_tramas:6d} tramas  RSS {r:7.1f} MB  p99 {muestras[-1]['ms_p99']:6.2f} ms")
            tiempos_ventana = []
    app.processEvents()
    rss_fin = rss_mb()
    crecimiento = rss_fin - (rss_hora1 if rss_hora1 is not None else rss0)
    p99 = percentil(todos, 99)
    texto_log = open(ruta_log, encoding="utf-8").read()
    n_err = texto_log.count(" ERROR ")
    resumen = {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "horas_simuladas": args.horas, "tramas": n_tramas, "objetos": n_obj,
        "sesiones_reales": len(sesiones), "alarmas_registradas": w.registro._n_eventos,
        "rss_inicio_mb": round(rss0, 1), "rss_hora1_mb": round(rss_hora1 or rss0, 1), "rss_final_mb": round(rss_fin, 1),
        "crecimiento_mb": round(crecimiento, 1), "ms_por_trama_p50": round(percentil(todos, 50), 3),
        "ms_por_trama_p99": round(p99, 3), "ms_por_trama_max": round(max(todos), 3),
        "errores_app_log": n_err, "errores_notificados": len(errores),
        "duracion_real_s": round(time.perf_counter() - t_ini, 1), "cpu_s": round(cpu_s() - cpu_ini, 1),
        "criterios": {"crecimiento_max_mb": CRECIMIENTO_MAX_MB, "p99_max_ms": P99_MAX_MS, "errores": 0},
    }
    resumen["aprobada"] = bool(crecimiento <= CRECIMIENTO_MAX_MB and p99 <= P99_MAX_MS and n_err == 0)
    w.close()
    guardar(args.salida, muestras, resumen, f"Resistencia acelerada: {args.horas:g} h de telemetría real",
            "horas simuladas", "horas_simuladas")
    print(("APROBADA" if resumen["aprobada"] else "NO APROBADA") +
          f": crecimiento {crecimiento:.1f} MB, p99 {p99:.2f} ms, errores {n_err} · {args.salida}")
    bitacora.restablecer()
    return 0 if resumen["aprobada"] else 1


if __name__ == "__main__":
    sys.exit(main())
