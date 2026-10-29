#!/usr/bin/env python3
"""
MotorGuard-ITF — monitoreo del firmware congelado (commit 299a943).

Uso (con el venv de ~/tesis_itf):
  python -m motorguard_dashboard.app                         # Arduino por USB (detecta /dev/ttyACM*)
  python -m motorguard_dashboard.app --puerto /dev/ttyACM0
  python -m motorguard_dashboard.app --replay ~/tesis_itf/validacion_vivo/vivo_INTER_75%_20261009_1513_serial.log [--velocidad 10]
  python -m motorguard_dashboard.app --elegir-log           # elegir el log con un diálogo
  python -m motorguard_dashboard.app --demo [--demo-enclavada]  # SOLO capturas: simulador con tramas reales
También desde el menú de aplicaciones (lanzador ~/.local/share/applications/motorguard-itf.desktop).

Registros en la carpeta de Ajustes (por defecto Documentos/MotorGuard-ITF/registros): eventos de alarma (CSV) y, con el Arduino, las líneas crudas
recibidas (reproducibles con --replay) y los pulsos de inyección (CSV). No usar al mismo tiempo que los
scripts de validación. La inyección solo existe con el Arduino y siempre pide confirmación.
La sección Adquisición (solo con el Arduino) escribe en su propia carpeta (por defecto
Documentos/MotorGuard-ITF/adquisicion), nunca en las carpetas de datos de la tesis.
"""

import argparse
import os
import signal
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from motorguard_dashboard.inyeccion.control import ControlInyeccion
from motorguard_dashboard import __version__
from motorguard_dashboard.sistema import bitacora, rutas
from motorguard_dashboard.sistema.instancia import InstanciaUnica
from motorguard_dashboard.telemetry.alarmas import RegistroAlarmas
from motorguard_dashboard.telemetry.fuente_replay import FuenteReplay
from motorguard_dashboard.telemetry.fuente_serie import FuenteSerie
from motorguard_dashboard.ui.monitor_window import MonitorWindow
from motorguard_dashboard.ui.tema import RUTA_LOGO, GestorTema, cargar_fuentes, instalar_traducciones


def main():
    ap = argparse.ArgumentParser(description="MotorGuard-ITF: monitoreo del detector embebido")
    origen = ap.add_mutually_exclusive_group()
    origen.add_argument("--puerto", help="puerto serie (por defecto, el primer /dev/ttyACM*)")
    origen.add_argument("--replay", metavar="LOG", help="reproducir un *_serial.log real en lugar del Arduino")
    origen.add_argument("--elegir-log", action="store_true", help="elegir con un diálogo el log a reproducir")
    origen.add_argument("--demo", action="store_true",
                        help="SOLO capturas (desde el repositorio): simulador del firmware con tramas reales del banco")
    ap.add_argument("--demo-enclavada", action="store_true",
                    help="con --demo, la alarma queda enclavada hasta «Liberar alarma»")
    ap.add_argument("--velocidad", type=float, default=1.0, help="factor de velocidad de la reproducción")
    ap.add_argument("--tema", choices=GestorTema.MODOS, help="forzar el tema (por defecto, el último elegido)")
    ap.add_argument("--sin-asistente", action="store_true", help="no arrancar el modelo local del asistente")
    args = ap.parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName("MotorGuard-ITF")
    app.setOrganizationName(rutas.ORG)
    app.setApplicationVersion(__version__)
    bitacora.configurar(rutas.dir_logs_app())
    app.setDesktopFileName("motorguard-itf")   # en Wayland/GNOME el ícono del dock sale del .desktop con este nombre
    app.setWindowIcon(QIcon(RUTA_LOGO))
    cargar_fuentes()
    instalar_traducciones(app)
    # Tema: sigue al del sistema o el que elija el usuario (Sistema/Claro/Oscuro); se recuerda entre sesiones
    tema = GestorTema(app, persistir=True, modo=args.tema)

    if args.elegir_log:
        ruta, _ = QFileDialog.getOpenFileName(None, "Elegir un log para reproducir", rutas.dir_reproduccion(),
                                              "Logs seriales (*_serial.log *.log);;Todos los archivos (*)")
        if not ruta:
            return
        rutas.recordar_dir_reproduccion(ruta)
        args.replay = ruta

    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    dir_reg = rutas.dir_registros()
    instancia = None
    simulador = None
    if args.demo:
        # Modo demo: nada sale a hardware. El simulador vive en tests/ (no va en los .deb).
        import tty
        from motorguard_dashboard.tests.simulador_demo import SimuladorDemo
        dir_reg = os.path.join(dir_reg, "demo")
        dir_adq = os.path.join(dir_reg, "adquisicion")
        rutas.dir_registros = lambda conf=None: dir_reg        # que nada de la demo caiga en las carpetas reales
        rutas.dir_adquisicion = lambda conf=None: dir_adq
        os.makedirs(dir_reg, exist_ok=True)
        maestro, esclavo = os.openpty()
        tty.setraw(esclavo)
        puerto = os.ttyname(esclavo)
        simulador = SimuladorDemo(maestro, enclavada=args.demo_enclavada)
        simulador.start()
        fuente = FuenteSerie(puerto, ruta_crudo=os.path.join(dir_reg, f"demo_{sello}_serial.log"))
        ruta_csv = os.path.join(dir_reg, f"demo_{sello}_eventos.csv")
        descripcion = "DEMO: simulador del firmware"
        control = ControlInyeccion(os.path.join(dir_reg, f"demo_{sello}_pulsos.csv"))
    elif args.replay:
        if not os.path.isfile(args.replay):
            ap.error(f"no existe {args.replay}")
        nombre = os.path.basename(args.replay).replace("_serial.log", "")
        fuente = FuenteReplay(args.replay, args.velocidad)
        ruta_csv = os.path.join(dir_reg, f"replay_{nombre}_{sello}_eventos.csv")
        descripcion = f"reproducción de {nombre}"
        control = None
    else:
        # Una sola ventana con el Arduino: dos se pelearían el puerto y el SSR
        instancia = InstanciaUnica(os.path.join(rutas.dir_datos_app(), "arduino.lock"))
        tomada, pid = instancia.tomar()
        if not tomada:
            bitacora.LOG.warning("Ya hay una ventana con el Arduino (PID %s); no se abre otra", pid)
            QMessageBox.warning(None, "MotorGuard-ITF",
                                "Ya hay una ventana de MotorGuard-ITF usando el Arduino"
                                + (f" (proceso {pid})" if pid else "") + ".\nCiérrala antes de abrir otra. "
                                "Las reproducciones de logs sí pueden abrirse varias.")
            return
        fuente = FuenteSerie(args.puerto, ruta_crudo=os.path.join(dir_reg, f"sesion_{sello}_serial.log"))
        ruta_csv = os.path.join(dir_reg, f"sesion_{sello}_eventos.csv")
        descripcion = "Arduino por USB"
        control = ControlInyeccion(os.path.join(dir_reg, f"sesion_{sello}_pulsos.csv"))

    bitacora.registrar_arranque(__version__, descripcion)
    bitacora.LOG.info("Registros de esta sesión en %s", dir_reg)
    ventana = MonitorWindow(fuente, RegistroAlarmas(ruta_csv), es_replay=bool(args.replay),
                            descripcion=descripcion, control=control, tema=tema, demo=args.demo)
    ventana.show()
    if not args.sin_asistente:
        ventana.asistente.iniciar_servicio()   # llama-server en segundo plano (si está preparado)

    # Ctrl+C o SIGTERM cierran la ventana de forma ordenada: el cierre envía '0' antes de soltar el puerto.
    # (Si el proceso muere de golpe, el firmware apaga el SSR a los 12 s.)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: ventana.close())
    latido = QTimer()
    latido.timeout.connect(lambda: None)   # deja que Python atienda las señales del sistema
    latido.start(200)
    codigo = app.exec()
    bitacora.LOG.info("Cierre normal (código %s)", codigo)
    if instancia is not None:
        instancia.soltar()
    if simulador is not None:
        simulador.detener()
    sys.exit(codigo)


if __name__ == "__main__":
    main()
