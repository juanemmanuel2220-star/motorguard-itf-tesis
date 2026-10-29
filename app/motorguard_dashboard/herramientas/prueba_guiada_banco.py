#!/usr/bin/env python3
"""
Prueba guiada en el banco (protocolo protocolos/prueba_en_vivo_app.md, pasos 5–8b): abre la app completa con el
Arduino real, igual que app.py (sin el asistente, para no cargar el CPU), y hace por código los clics que haría
el operador: consultas del Dashboard, configurar la inyección, PARO a los 3 s y cerrar la app a los 3 s.

Lo que NO automatiza: la confirmación de cada inyección. Antes de cada '1' se abre el mismo diálogo de
seguridad de la app y el operador tiene que marcar las tres casillas y pulsar Inyectar en la pantalla (regla
del autor: nunca enviar '1' sin una confirmación humana en la interfaz). Si el operador cancela, la prueba se
detiene. La pinza, el USB (paso 8c) y vigilar el lazo también son del operador.

    PYTHONPATH=. venv/bin/python -m motorguard_dashboard.herramientas.prueba_guiada_banco [--pasos 5,6,7,8a,8b]

Los registros quedan en la carpeta de registros de la app (sesion_<sello>_*), como en una sesión normal; el
avance se imprime con la hora para la hoja de la prueba.
"""

import argparse
import os
import signal
import sys
import time
from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from motorguard_dashboard import __version__
from motorguard_dashboard.inyeccion.control import ControlInyeccion
from motorguard_dashboard.sistema import bitacora, rutas
from motorguard_dashboard.sistema.instancia import InstanciaUnica
from motorguard_dashboard.telemetry.alarmas import RegistroAlarmas
from motorguard_dashboard.telemetry.fuente_serie import FuenteSerie
from motorguard_dashboard.ui.monitor_window import MonitorWindow
from motorguard_dashboard.ui.tema import RUTA_LOGO, GestorTema, cargar_fuentes, instalar_traducciones

# (paso, duración del pulso en s, número de pulsos, pausa en s, acción a los 3 s de encendido)
INYECCIONES = {"6": (5.0, 1, 20.0, None), "7": (5.0, 3, 20.0, None), "8a": (11.0, 1, 20.0, "paro"),
               "8b": (11.0, 1, 20.0, "cerrar")}


def decir(texto: str):
    print(f"{datetime.now():%H:%M:%S}  {texto}", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--pasos", default="5,6,7,8a,8b")
    ap.add_argument("--puerto")
    ap.add_argument("--esperar-min", type=float, default=5.0,
                    help="minutos con el motor en ON antes del primer paso (protocolo: >= 5 min)")
    a = ap.parse_args()
    pasos = [p.strip() for p in a.pasos.split(",") if p.strip()]
    if any(p not in INYECCIONES and p != "5" for p in pasos):
        ap.error(f"pasos válidos: 5, {', '.join(INYECCIONES)}")
    if "8b" in pasos and pasos[-1] != "8b":
        ap.error("8b cierra la app: tiene que ser el último paso")

    app = QApplication(sys.argv)
    app.setApplicationName("MotorGuard-ITF")
    app.setOrganizationName(rutas.ORG)
    app.setApplicationVersion(__version__)
    bitacora.configurar(rutas.dir_logs_app())
    app.setDesktopFileName("motorguard-itf")
    app.setWindowIcon(QIcon(RUTA_LOGO))
    cargar_fuentes()
    instalar_traducciones(app)
    tema = GestorTema(app, persistir=True)

    instancia = InstanciaUnica(os.path.join(rutas.dir_datos_app(), "arduino.lock"))
    tomada, pid = instancia.tomar()
    if not tomada:
        decir(f"ya hay una ventana con el Arduino (PID {pid}): ciérrala y vuelve a correr la prueba")
        return 2
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    dir_reg = rutas.dir_registros()
    fuente = FuenteSerie(a.puerto, ruta_crudo=os.path.join(dir_reg, f"sesion_{sello}_serial.log"))
    control = ControlInyeccion(os.path.join(dir_reg, f"sesion_{sello}_pulsos.csv"))
    bitacora.registrar_arranque(__version__, "Arduino por USB (prueba guiada en el banco)")
    w = MonitorWindow(fuente, RegistroAlarmas(os.path.join(dir_reg, f"sesion_{sello}_eventos.csv")),
                      es_replay=False, descripcion="Arduino por USB · prueba guiada", control=control, tema=tema)
    w.show()
    decir(f"app abierta; sesión sesion_{sello} en {dir_reg}; pasos {', '.join(pasos)}")

    cola = list(pasos)
    estado = {"paso": None, "consultas": [], "t_limite": 0.0}

    def despues(seg, f):
        QTimer.singleShot(int(seg * 1000), f)

    def siguiente():
        if not cola:
            decir("FIN: todos los pasos pedidos terminaron; la app queda abierta (ciérrala tú)")
            return
        paso = cola.pop(0)
        estado["paso"] = paso
        decir(f"--- paso {paso}")
        if paso == "5":
            estado["consultas"] = ["W", "f", "s"]
            esperar_dashboard()
        else:
            esperar_inyeccion(paso, time.monotonic() + 600)

    # ---------------------------------------------------------------- paso 5: consultas del Dashboard
    def esperar_dashboard():
        if not estado["consultas"]:
            decir("paso 5: tres consultas pedidas; espero 8 s a la última respuesta")
            despues(8, siguiente)
            return
        cmd = estado["consultas"][0]
        b = w.dashboard.botones.get(cmd)
        if b is None or not b.isEnabled():
            despues(1, esperar_dashboard)              # bloqueado (WARMUP, pulso en curso, intervalo mínimo…)
            return
        estado["consultas"].pop(0)
        w.ir_a(1)                                       # sección Dashboard, como si el operador la abriera
        decir(f"paso 5: clic en «{b.text()}» (envía '{cmd}')")
        b.click()
        despues(6, esperar_dashboard)

    # ---------------------------------------------------------------- pasos 6–8b: inyección
    def esperar_inyeccion(paso, limite):
        p = w.panel_iny
        dur, n, pausa, accion = INYECCIONES[paso]
        p.elegir_taps("INTER")
        p.spn_dur.setValue(dur)
        p.spn_n.setValue(n)
        p.spn_pausa.setValue(pausa)
        if not p.btn_inyectar.isEnabled():
            if time.monotonic() > limite:
                decir(f"paso {paso}: Inyectar sigue bloqueado después de 10 min ({p.lbl_bloqueo.text()}); se detiene")
                return
            despues(1, lambda: esperar_inyeccion(paso, limite))
            return
        decir(f"paso {paso}: INTER, {n} pulso(s) de {dur:g} s, pausa {pausa:g} s. Se abre el diálogo: "
              "CONFIRMA TÚ en la pantalla (o Cancelar para detener la prueba)")
        n_antes = control._n_pulsos
        p.btn_inyectar.click()                          # abre DialogoSeguridad.exec(): espera al operador
        if not control.en_curso and control._n_pulsos == n_antes:
            decir(f"paso {paso}: el operador canceló el diálogo; la prueba se detiene aquí")
            return
        w.ir_a(0)                                       # Monitoreo, para ver la alarma
        decir(f"paso {paso}: confirmado por el operador; serie en curso")
        if accion:
            esperar_encendido(paso, accion, time.monotonic() + 5)
        else:
            esperar_fin(paso)

    def esperar_encendido(paso, accion, limite):
        pa = control.pulso_actual
        if pa is not None and pa.t_encendido is not None:
            decir(f"paso {paso}: SSR encendido (confirmado por el firmware); {accion} en 3 s")
            despues(3, lambda: ejecutar(paso, accion))
            return
        if time.monotonic() > limite:
            decir(f"paso {paso}: el firmware no confirmó el encendido en 5 s; la app ya gestiona el '0'")
            despues(15, siguiente)
            return
        despues(0.1, lambda: esperar_encendido(paso, accion, limite))

    def ejecutar(paso, accion):
        if accion == "paro":
            decir(f"paso {paso}: clic en PARO")
            w.btn_paro.click()
            esperar_fin(paso)
        else:
            decir(f"paso {paso}: se cierra la app con el SSR encendido")
            w.close()

    def esperar_fin(paso):
        if control.en_curso:
            despues(0.5, lambda: esperar_fin(paso))
            return
        ultimo = control.pulsos[-1] if control.pulsos else None
        decir(f"paso {paso}: terminado; último pulso: {ultimo.resultado if ultimo else '—'}"
              f"{f' (T_ON {ultimo.t_on_ms} ms)' if ultimo and ultimo.t_on_ms else ''}")
        despues(2, siguiente)

    def esperar_motor():
        t = control.ultima_trama
        minutos = control.minutos_encendido(time.time())
        # --esperar-min 0: el operador declara que el motor ya lleva el tiempo pedido (arranque no visto por la app)
        if t is not None and t.motor == "ON" and (a.esperar_min == 0 or (minutos is not None and minutos >= a.esperar_min)):
            decir("motor en ON" + (f" desde hace {minutos:.1f} min" if minutos is not None else
                                   " (arranque declarado por el operador)") + ": empiezan los pasos")
            siguiente()
            return
        ahora = time.monotonic()
        if ahora - estado.get("t_aviso", 0) > 60:
            estado["t_aviso"] = ahora
            decir(f"esperando: motor {t.motor if t else '—'}"
                  + (f", {minutos:.1f} de {a.esperar_min:g} min en ON" if minutos is not None else ""))
        despues(2, esperar_motor)

    # Como app.py: Ctrl+C o SIGTERM cierran la ventana de forma ordenada (el cierre envía '0')
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: w.close())
    latido = QTimer()
    latido.timeout.connect(lambda: None)
    latido.start(200)
    despues(3, esperar_motor)
    codigo = app.exec()
    bitacora.LOG.info("Cierre normal (código %s)", codigo)
    instancia.soltar()
    decir(f"app cerrada (código {codigo})")
    return codigo


if __name__ == "__main__":
    sys.exit(main())
