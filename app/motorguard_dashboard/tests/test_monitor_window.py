"""
Prueba de integración de la ventana de monitoreo (sin pantalla): reproduce el bloque SEVERA validado
y verifica tabla, CSV, cierre y que la ventana no tenga controles que envíen comandos.
"""

import csv
import os
import tempfile
import time

from motorguard_dashboard.tests import qt_util
from motorguard_dashboard.tests.test_telemetry_parser import DIR_VIVO


def test_ventana_con_bloque_severa():
    app = qt_util.app()
    from motorguard_dashboard.telemetry.alarmas import RegistroAlarmas
    from motorguard_dashboard.telemetry.fuente_replay import FuenteReplay
    from motorguard_dashboard.ui.monitor_window import MonitorWindow

    log = os.path.join(DIR_VIVO, "vivo_SEVERA_75%_20261008_1612_serial.log")
    with tempfile.TemporaryDirectory() as d:
        ruta_csv = os.path.join(d, "eventos.csv")
        fuente = FuenteReplay(log, velocidad=1e6)
        w = MonitorWindow(fuente, RegistroAlarmas(ruta_csv), es_replay=True, descripcion="prueba")
        w.show()
        fin = time.monotonic() + 30
        while fuente.isRunning() or not w.lbl_fuente.text().startswith("○"):
            app.processEvents()
            assert time.monotonic() < fin, "la reproducción no terminó"
            time.sleep(0.01)
        app.processEvents()

        assert w.tabla.rowCount() == 10
        assert all(w.tabla.item(r, 5).text() == "SEVERA" for r in range(10))
        assert w._n_descartadas == 0
        # En reproducción no hay ningún control que envíe comandos (solo navegación y tema)
        assert w.btn_paro is None and w.panel_iny is None and not w.dashboard.botones
        assert not w.btn_liberar.isVisible()                    # tampoco "Liberar alarma"
        # Cada columna se desplaza sola (17-oct)
        w.scroll_izq.verticalScrollBar().setValue(w.scroll_izq.verticalScrollBar().maximum())
        assert w.scroll_der.verticalScrollBar().value() == 0
        w.close()
        with open(ruta_csv, encoding="utf-8") as f:
            alarmas = [r for r in csv.DictReader(f) if r["tipo"] == "ALARMA"]
        assert len(alarmas) == 10 and all(r["sev_max"] == "SEVERA" for r in alarmas)
    print("  ventana: 10 alarmas SEVERA en tabla y CSV; sin controles que envíen comandos")


def test_liberar_alarma_atascada():
    """Botón "Liberar alarma" (aprobado por el autor el 16-oct) con el SIMULADOR: solo aparece con una alarma
    enclavada, pide la confirmación con casilla, envía 'r' y la alarma queda cerrada como liberada manualmente;
    el reinicio del firmware no abre una alarma nueva."""
    app = qt_util.app()
    from PySide6.QtWidgets import QDialog
    from motorguard_dashboard.inyeccion.control import ControlInyeccion
    from motorguard_dashboard.telemetry.alarmas import RegistroAlarmas
    from motorguard_dashboard.telemetry.fuente_serie import FuenteSerie
    from motorguard_dashboard.tests.simulador_firmware import SimuladorFirmware
    from motorguard_dashboard.tests.test_fuente_serie import PuertoVirtual, _esperar
    from motorguard_dashboard.ui import monitor_window as mw

    respuesta = {"aceptar": False, "veces": 0}

    def exec_simulado(dlg):
        respuesta["veces"] += 1
        assert not dlg.btn_ok.isEnabled()                       # sin la casilla no se puede aceptar
        if respuesta["aceptar"]:
            dlg.casilla.setChecked(True)
            assert dlg.btn_ok.isEnabled()
            return QDialog.Accepted
        return QDialog.Rejected

    original = mw.DialogoLiberar.exec
    mw.DialogoLiberar.exec = exec_simulado
    with tempfile.TemporaryDirectory() as d:
        pv = PuertoVirtual(d)
        pv.iniciar()
        sim = SimuladorFirmware(pv.maestro)
        sim.start()
        reg = RegistroAlarmas(os.path.join(d, "ev.csv"))
        w = mw.MonitorWindow(FuenteSerie(pv.a), reg, es_replay=False, descripcion="simulador",
                             control=ControlInyeccion(os.path.join(d, "pulsos.csv")))
        w.show()
        try:
            assert _esperar(lambda: w._ultima is not None, 5)
            assert not w.btn_liberar.isVisible()                 # sin alarma no aparece
            sim.atascada = True
            assert _esperar(lambda: reg.abierta is not None and w.btn_liberar.isVisible(), 5)
            assert w.btn_liberar.isEnabled()
            w.btn_liberar.click()                                 # cancelado: no sale 'r'
            app.processEvents()
            assert respuesta["veces"] == 1 and "r" not in sim.recibidos and reg.abierta is not None
            respuesta["aceptar"] = True
            ev = reg.abierta
            w.btn_liberar.click()
            assert _esperar(lambda: "r" in sim.recibidos, 3)
            assert ev.motivo_fin == "liberada manualmente (r)" and reg.abierta is None
            time.sleep(1.5)                                       # varias tramas después del reinicio
            app.processEvents()
            assert reg.abierta is None and not w.btn_liberar.isVisible()
            assert set(sim.recibidos) <= {"0", "1", "W", "f", "s", "r"}
        finally:
            mw.DialogoLiberar.exec = original
            w.close()
            sim.detener()
            pv.desconectar()
    print("  liberar alarma: botón solo con alarma enclavada, casilla obligatoria, 'r' y cierre registrado")


def run():
    test_ventana_con_bloque_severa()
    test_liberar_alarma_atascada()
    print("✓ Ventana de monitoreo: 2/2 pruebas")


if __name__ == "__main__":
    run()
