"""
Integración de la sección Adquisición sin hardware: ventana + fuente serie sobre un pty con el SIMULADOR
del firmware (tests/simulador_firmware.py; solo para pruebas). Para que la prueba dure segundos se baja
el enfriamiento mínimo de la app a 1 s SOLO dentro de la prueba (en la app es de 15/20 s).
Verifica: diálogo obligatorio (cancelado = sin archivos), captura de 2 pares hasta el final, bloqueo de la
inyección manual mientras hay captura, prueba larga sin '1', cierre de la ventana con captura abierta y que
solo salgan '1' y '0'. La carpeta y los ajustes son temporales (no toca los QSettings del usuario).
"""

import csv
import glob
import json
import os
import tempfile

from motorguard_dashboard.tests import qt_util
from motorguard_dashboard.tests.simulador_firmware import SimuladorFirmware
from motorguard_dashboard.tests.test_fuente_serie import PuertoVirtual, _esperar


def test_adquisicion_con_simulador():
    app = qt_util.app()
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QDialog
    from motorguard_dashboard.adquisicion import formato
    from motorguard_dashboard.inyeccion import control as mod_control
    from motorguard_dashboard.telemetry.alarmas import RegistroAlarmas
    from motorguard_dashboard.telemetry.fuente_serie import FuenteSerie
    from motorguard_dashboard.ui import panel_inyeccion
    from motorguard_dashboard.ui.monitor_window import MonitorWindow

    respuesta = {"dialogo": QDialog.Rejected, "veces": 0}

    def exec_simulado(dlg):
        respuesta["veces"] += 1
        if respuesta["dialogo"] == QDialog.Accepted:
            for c in dlg.casillas:
                c.setChecked(True)
        return respuesta["dialogo"]

    original_exec = panel_inyeccion.DialogoSeguridad.exec
    original_enf = mod_control.ENFRIAMIENTO_MIN_S
    panel_inyeccion.DialogoSeguridad.exec = exec_simulado
    mod_control.ENFRIAMIENTO_MIN_S = 1.0
    with tempfile.TemporaryDirectory() as d:
        pv = PuertoVirtual(d)
        pv.iniciar()
        sim = SimuladorFirmware(pv.maestro)
        sim.start()
        control = mod_control.ControlInyeccion(os.path.join(d, "pulsos.csv"))
        w = MonitorWindow(FuenteSerie(pv.a), RegistroAlarmas(os.path.join(d, "ev.csv")),
                          es_replay=False, descripcion="simulador", control=control)
        tab = w.adquisicion
        tab._conf = QSettings(os.path.join(d, "ajustes.ini"), QSettings.IniFormat)
        datos = os.path.join(d, "datos")
        tab.poner_carpeta(datos)
        w.show()
        w.ir_a(2)
        try:
            assert _esperar(lambda: control.ultima_trama is not None)
            assert not tab.btn_iniciar.isEnabled()                 # falta elegir clase y carga
            tab.elegir_clase(2)
            tab.elegir_carga("50%")
            tab.spn_pares.setValue(2)
            tab.spn_dur.setValue(2.5)
            tab.spn_tmin.setValue(0.6)
            tab.spn_cool.setValue(2.5)                             # el simulador rechaza < 2 s desde el apagado
            assert _esperar(lambda: tab.btn_iniciar.isEnabled()), tab.lbl_bloqueo.text()

            # Carpeta de la tesis: bloqueado
            tab.poner_carpeta(os.path.expanduser("~/tesis_itf/dataset"))
            assert not tab.btn_iniciar.isEnabled() and "tesis" in tab.lbl_bloqueo.text()
            tab.poner_carpeta(datos)

            # Diálogo cancelado: ni '1' ni archivos
            tab.btn_iniciar.click()
            app.processEvents()
            assert respuesta["veces"] == 1 and "1" not in sim.recibidos and tab.captura is None
            assert not glob.glob(os.path.join(datos, "*"))

            respuesta["dialogo"] = QDialog.Accepted
            tab.btn_iniciar.click()
            assert tab.captura is not None and tab.activa
            # Mientras hay captura, la inyección manual queda bloqueada
            assert _esperar(lambda: "Adquisición" in w.panel_iny.lbl_bloqueo.text())
            assert not w.panel_iny.btn_inyectar.isEnabled()
            assert _esperar(lambda: tab.captura.estado == tab.captura.TERMINADA, 30), \
                (tab.captura.estado, tab.captura.mensaje, list(tab.captura.consola))
            cap = tab.captura
            assert cap.p == 2 and cap.n_desc == 0, list(cap.consola)
            with open(cap.ruta_csv, newline="") as fh:
                filas = list(csv.reader(fh))
            assert filas[0] == formato.COLS and len(filas) == 5
            assert [r[1] for r in filas[1:]] == ["SANO", "INTER", "SANO", "INTER"]
            meta = json.load(open(cap.ruta_meta))["sesiones"][-1]
            assert meta["parametros"]["port"] == pv.a and "MotorGuard-ITF" in meta["origen"]
            assert meta["pares_total"] == 2 and "fin" in meta
            assert sim.recibidos.count("1") == 2 and not sim.ssr
            assert "INTER" in tab.txt.toPlainText()
            assert _esperar(lambda: "Adquisición" not in w.panel_iny.lbl_bloqueo.text())

            # Prueba larga: nunca '1', '0' al iniciar
            tab.elegir_modo("larga")
            assert _esperar(lambda: tab.btn_iniciar.isEnabled()), tab.lbl_bloqueo.text()
            n0 = sim.recibidos.count("0")
            tab.btn_iniciar.click()
            assert tab.larga is not None and tab.larga.activa
            assert _esperar(lambda: sim.recibidos.count("0") > n0)
            assert _esperar(lambda: "prueba larga" in w.panel_iny.lbl_bloqueo.text())
            assert _esperar(lambda: len(tab.larga.prev or ()) > 0)
            tab.terminar()
            assert not tab.larga.activa and os.path.exists(tab.larga.base + "_resumen.json")
            assert sim.recibidos.count("1") == 2

            # Cerrar la ventana con una captura abierta: '0' y los archivos quedan cerrados
            tab.elegir_modo("pares")
            tab.spn_pares.setValue(5)
            assert _esperar(lambda: tab.btn_iniciar.isEnabled()), tab.lbl_bloqueo.text()
            tab.btn_iniciar.click()
            assert _esperar(lambda: sim.ssr, 10), tab.captura.mensaje
            cap2 = tab.captura
            w.close()
            assert _esperar(lambda: not sim.ssr, 2), "al cerrar no se apagó el SSR"
            assert not cap2.activa
            assert json.load(open(cap2.ruta_meta))["sesiones"][-1]["motivo_fin"] == "app cerrada"
            assert set(sim.recibidos) <= {"0", "1"}, sim.recibidos
        finally:
            panel_inyeccion.DialogoSeguridad.exec = original_exec
            mod_control.ENFRIAMIENTO_MIN_S = original_enf
            if w.isVisible():
                w.close()
            sim.detener()
            pv.desconectar()
    print("  simulador: diálogo, 2 pares completos, bloqueo manual, prueba larga sin '1' y cierre con captura abierta")


def run():
    test_adquisicion_con_simulador()
    print("✓ Sección Adquisición con simulador: 1/1 prueba")


if __name__ == "__main__":
    run()
