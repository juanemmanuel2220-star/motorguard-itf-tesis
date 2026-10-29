#!/usr/bin/env python3
"""
Prueba de resistencia en TIEMPO REAL contra el SIMULADOR del firmware (solo pruebas; no es evidencia
experimental del banco). La app completa (puerto serie, ventana, inyección) corre N horas como en uso real:

  - una trama cada 1.7 s (como el firmware), por un puerto virtual (pty);
  - un pulso INTER de 5 s cada 30 s por la lógica de seguridad (sin el diálogo, que es para personas);
  - una desconexión del puerto de 10 s cada 20 min.

Criterios (declarados antes de correr):
  - crecimiento de memoria entre la hora 1 y el final <= 30 MB
  - 0 errores en app.log
  - >= 95 % de las tramas esperadas recibidas (descontando el tiempo desconectado)
  - todos los pulsos terminan (ninguno queda en curso) y el SSR simulado queda apagado al final

Uso: python -m motorguard_dashboard.herramientas.resistencia_tiempo_real [--horas 4] [--salida DIR]
"""

import argparse
import os
import sys
import tempfile
import time
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from motorguard_dashboard.herramientas.medicion import cpu_s, guardar, rss_mb  # noqa: E402

CRECIMIENTO_MAX_MB = 30.0
TRAMAS_MIN = 0.95


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--horas", type=float, default=4.0)
    ap.add_argument("--periodo", type=float, default=1.7, help="segundos entre tramas del simulador")
    ap.add_argument("--pulso-cada", type=float, default=30.0)
    ap.add_argument("--desconectar-cada", type=float, default=1200.0)
    ap.add_argument("--salida", default=os.path.expanduser(
        f"~/tesis_itf/app_pruebas/resistencia_tiempo_real_{datetime.now():%Y%m%d_%H%M%S}"))
    args = ap.parse_args()
    os.makedirs(args.salida, exist_ok=True)

    app = QApplication([])
    from motorguard_dashboard.inyeccion.control import ControlInyeccion, PlanSerie
    from motorguard_dashboard.sistema import bitacora
    from motorguard_dashboard.telemetry.alarmas import RegistroAlarmas
    from motorguard_dashboard.telemetry.fuente_serie import FuenteSerie
    from motorguard_dashboard.tests.simulador_firmware import SimuladorFirmware
    from motorguard_dashboard.tests.test_fuente_serie import PuertoVirtual
    from motorguard_dashboard.ui.monitor_window import MonitorWindow
    from motorguard_dashboard.ui.tema import GestorTema, cargar_fuentes

    ruta_log = bitacora.configurar(args.salida, a_consola=False)
    cargar_fuentes()
    tema = GestorTema(app, persistir=False, modo="claro")
    dir_pty = tempfile.mkdtemp()
    pv = PuertoVirtual(dir_pty)
    pv.iniciar()
    sim = SimuladorFirmware(pv.maestro, periodo=args.periodo)
    sim.start()
    control = ControlInyeccion(os.path.join(args.salida, "pulsos.csv"))
    fuente = FuenteSerie(pv.a, ruta_crudo=os.path.join(args.salida, "sesion_serial.log"))
    w = MonitorWindow(fuente, RegistroAlarmas(os.path.join(args.salida, "eventos.csv")), False,
                      "resistencia en tiempo real (simulador)", control, tema=tema)
    w.resize(1440, 920)
    w.show()

    estado = {"intentos": 0, "iniciados": 0, "desconexiones": 0, "s_desconectado": 0.0,
              "t_desc": None, "reconexiones": 0, "cpu_prev": cpu_s(), "t_prev": time.monotonic()}
    fuente.sig_estado.connect(lambda ok, m: estado.__setitem__("reconexiones", estado["reconexiones"] + int(ok)))
    muestras = []
    t_ini = time.monotonic()
    rss0 = rss_mb()
    rss_hora1 = [None]

    def pulso():
        estado["intentos"] += 1
        ahora = time.time()
        if control.bloqueo(ahora, "INTER") is None and not control.en_curso:
            conf = control.emitir_confirmacion(PlanSerie("INTER", 5.0, 1, 20.0), ahora)
            cmds = control.iniciar_serie(conf, ahora)
            if cmds:
                estado["iniciados"] += 1
            w.panel_iny._enviar(cmds)

    def desconectar():
        estado["desconexiones"] += 1
        estado["t_desc"] = time.monotonic()
        pv.desconectar()
        QTimer.singleShot(10_000, reconectar)

    def reconectar():
        pv.iniciar()
        sim.cambiar_puerto(pv.maestro)
        estado["s_desconectado"] += time.monotonic() - estado["t_desc"]

    def muestrear():
        ahora = time.monotonic()
        horas = (ahora - t_ini) / 3600.0
        r = rss_mb()
        if rss_hora1[0] is None and horas >= 1.0:
            rss_hora1[0] = r
        cpu = 100.0 * (cpu_s() - estado["cpu_prev"]) / max(1e-6, ahora - estado["t_prev"])
        estado["cpu_prev"], estado["t_prev"] = cpu_s(), ahora
        muestras.append({"horas": round(horas, 3), "rss_mb": round(r, 1), "cpu_pct": round(cpu, 2),
                         "tramas": w._n_tramas, "pulsos": control._n_pulsos, "alarmas": w.registro._n_eventos,
                         "desconexiones": estado["desconexiones"], "reconexiones": estado["reconexiones"]})
        print(f"  {horas:5.2f} h  RSS {r:6.1f} MB  CPU {cpu:5.2f} %  tramas {w._n_tramas:6d}  "
              f"pulsos {control._n_pulsos:4d}  alarmas {w.registro._n_eventos:4d}", flush=True)

    def terminar():
        for t in temporizadores:
            t.stop()
        # Dejar terminar el pulso en curso antes de cerrar
        fin = time.monotonic() + 15
        while control.en_curso and time.monotonic() < fin:
            app.processEvents()
            time.sleep(0.05)
        muestrear()
        duracion = time.monotonic() - t_ini
        esperadas = (duracion - estado["s_desconectado"]) / args.periodo
        w.close()
        fin = time.monotonic() + 3
        while sim.ssr and time.monotonic() < fin:
            time.sleep(0.05)
        crecimiento = muestras[-1]["rss_mb"] - (rss_hora1[0] if rss_hora1[0] is not None else rss0)
        n_err = open(ruta_log, encoding="utf-8").read().count(" ERROR ")
        pendientes = sum(1 for p in control.pulsos if not p.resultado)
        resumen = {
            "fecha": datetime.now().isoformat(timespec="seconds"), "horas": round(duracion / 3600, 3),
            "simulador": "tests/simulador_firmware.py (solo pruebas)", "periodo_s": args.periodo,
            "tramas_recibidas": w._n_tramas, "tramas_esperadas": int(esperadas),
            "fraccion_tramas": round(w._n_tramas / max(1, esperadas), 4),
            "pulsos_intentados": estado["intentos"], "pulsos_iniciados": estado["iniciados"],
            "pulsos_registrados": control._n_pulsos, "pulsos_sin_terminar": pendientes,
            "alarmas": w.registro._n_eventos, "desconexiones": estado["desconexiones"],
            "segundos_desconectado": round(estado["s_desconectado"], 1), "ssr_apagado_al_final": not sim.ssr,
            "rss_inicio_mb": round(rss0, 1), "rss_hora1_mb": round(rss_hora1[0] or rss0, 1),
            "rss_final_mb": muestras[-1]["rss_mb"], "crecimiento_mb": round(crecimiento, 1),
            "cpu_medio_pct": round(sum(m["cpu_pct"] for m in muestras) / len(muestras), 2),
            "errores_app_log": n_err,
            "criterios": {"crecimiento_max_mb": CRECIMIENTO_MAX_MB, "errores": 0, "fraccion_tramas_min": TRAMAS_MIN},
        }
        resumen["aprobada"] = bool(crecimiento <= CRECIMIENTO_MAX_MB and n_err == 0
                                   and resumen["fraccion_tramas"] >= TRAMAS_MIN and pendientes == 0
                                   and resumen["ssr_apagado_al_final"])
        sim.detener()
        pv.desconectar()
        guardar(args.salida, muestras, resumen,
                f"Resistencia en tiempo real (simulador): {duracion / 3600:.1f} h", "horas", "horas")
        print(("APROBADA" if resumen["aprobada"] else "NO APROBADA") +
              f": crecimiento {crecimiento:.1f} MB, errores {n_err}, tramas {resumen['fraccion_tramas']:.1%}, "
              f"pulsos {control._n_pulsos} (sin terminar {pendientes}) · {args.salida}", flush=True)
        bitacora.restablecer()
        app.exit(0 if resumen["aprobada"] else 1)

    temporizadores = []
    for cada_s, accion in ((args.pulso_cada, pulso), (args.desconectar_cada, desconectar), (60.0, muestrear)):
        tm = QTimer()
        tm.timeout.connect(accion)
        tm.start(int(cada_s * 1000))
        temporizadores.append(tm)
    QTimer.singleShot(int(args.horas * 3600 * 1000), terminar)
    print(f"Resistencia en tiempo real: {args.horas:g} h contra el simulador · {args.salida}", flush=True)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
