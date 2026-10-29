"""
Integración de la etapa 2 sin hardware: ventana + panel + fuente serie sobre un pty, con el
SIMULADOR del firmware (tests/simulador_firmware.py; solo para pruebas).
Verifica: '0' al conectar, diálogo obligatorio, pulso completo con confirmación del firmware,
bloqueo por enfriamiento y por WARMUP, PARO, '0' al cerrar y que solo salgan '1' y '0'.
"""

import csv
import os
import tempfile
import time

from motorguard_dashboard.tests import qt_util
from motorguard_dashboard.tests.simulador_firmware import SimuladorFirmware
from motorguard_dashboard.tests.test_fuente_serie import PuertoVirtual, _esperar


def test_dialogo_exige_todas_las_casillas():
    qt_util.app()
    from motorguard_dashboard.inyeccion.control import PlanSerie
    from motorguard_dashboard.ui.panel_inyeccion import DialogoSeguridad
    from PySide6.QtWidgets import QDialog
    dlg = DialogoSeguridad(PlanSerie("INTER", 5, 1, 15))
    assert not dlg.btn_ok.isEnabled()
    dlg.casillas[0].setChecked(True)
    dlg.casillas[1].setChecked(True)
    assert not dlg.btn_ok.isEnabled()
    dlg.accept()
    assert dlg.result() != QDialog.Accepted
    dlg.casillas[2].setChecked(True)
    assert dlg.btn_ok.isEnabled()


def test_ventana_con_simulador():
    app = qt_util.app()
    from PySide6.QtWidgets import QDialog
    from motorguard_dashboard.inyeccion.control import ControlInyeccion
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

    original = panel_inyeccion.DialogoSeguridad.exec
    panel_inyeccion.DialogoSeguridad.exec = exec_simulado
    with tempfile.TemporaryDirectory() as d:
        pv = PuertoVirtual(d)
        pv.iniciar()
        sim = SimuladorFirmware(pv.maestro)
        sim.start()
        ruta_pulsos = os.path.join(d, "pulsos.csv")
        control = ControlInyeccion(ruta_pulsos)
        w = MonitorWindow(FuenteSerie(pv.a), RegistroAlarmas(os.path.join(d, "ev.csv")),
                          es_replay=False, descripcion="simulador", control=control)
        w.show()
        panel = w.panel_iny
        try:
            assert _esperar(lambda: sim.recibidos[:1] == ["0"]), "no se envió '0' al conectar"
            assert _esperar(lambda: control.ultima_trama is not None)
            assert not panel.btn_inyectar.isEnabled()                    # sin taps elegidos
            panel.elegir_taps("INTER")
            panel.spn_dur.setValue(1.0)
            panel.spn_n.setValue(1)
            assert _esperar(lambda: panel.btn_inyectar.isEnabled())

            # Diálogo cancelado: no sale ningún '1'
            panel.btn_inyectar.click()
            app.processEvents()
            assert respuesta["veces"] == 1 and "1" not in sim.recibidos

            # Diálogo aceptado: pulso de 1 s confirmado por el firmware
            respuesta["dialogo"] = QDialog.Accepted
            panel.btn_inyectar.click()
            assert _esperar(lambda: "1" in sim.recibidos and sim.ssr)
            assert _esperar(lambda: control.pulsos and control.pulsos[0].resultado == "completo", 6)
            assert not sim.ssr and sim.recibidos.count("0") >= 2
            p = control.pulsos[0]
            assert p.confirmacion_fw == "encendido" and 900 <= p.t_on_ms <= 1600

            # Enfriamiento: el botón queda bloqueado
            assert _esperar(lambda: "enfriamiento" in panel.lbl_bloqueo.text())
            assert not panel.btn_inyectar.isEnabled()

            # WARMUP: bloqueado (el firmware lo aceptaría; el bloqueo es de la app)
            control.t_ultimo_apagado -= 60
            sim.motor = "WARMUP"
            assert _esperar(lambda: "WARMUP" in panel.lbl_bloqueo.text())
            assert not panel.btn_inyectar.isEnabled()
            sim.motor = "ON"

            # Rechazo del firmware (su propio enfriamiento de 2 s): la app registra y envía '0'
            panel.spn_dur.setValue(11.0)
            assert _esperar(lambda: panel.btn_inyectar.isEnabled())
            sim.t_off = time.monotonic()
            n0 = sim.recibidos.count("0")
            panel.btn_inyectar.click()
            assert _esperar(lambda: len(control.pulsos) == 2 and control.pulsos[1].confirmacion_fw == "rechazado")
            assert _esperar(lambda: control.estado == control.LIBRE)
            assert not sim.ssr and _esperar(lambda: sim.recibidos.count("0") > n0)
            assert control.pulsos[1].motivo_rechazo.startswith("Cooldown activo")

            # PARO a mitad de un pulso largo
            sim.t_off -= 10
            control.t_ultimo_apagado -= 60
            assert _esperar(lambda: panel.btn_inyectar.isEnabled())
            panel.btn_inyectar.click()
            assert _esperar(lambda: sim.ssr), (control.mensaje, sim.recibidos)
            w.btn_paro.click()
            assert _esperar(lambda: not sim.ssr, 2)
            assert _esperar(lambda: control.pulsos[2].resultado == "PARO manual")
            assert _esperar(lambda: control.estado == control.LIBRE)  # apagado ya confirmado por el firmware

            # Cerrar la ventana con el SSR encendido envía '0'
            sim.t_off -= 10
            control.t_ultimo_apagado -= 60
            assert _esperar(lambda: panel.btn_inyectar.isEnabled()), (panel.lbl_bloqueo.text(), control.estado, control.mensaje)
            panel.btn_inyectar.click()
            assert _esperar(lambda: sim.ssr)
            w.close()
            assert _esperar(lambda: not sim.ssr, 2), "al cerrar no se apagó el SSR"
            assert set(sim.recibidos) <= {"0", "1"}, sim.recibidos
            assert sim.recibidos.count("1") == 4
        finally:
            panel_inyeccion.DialogoSeguridad.exec = original
            if w.isVisible():
                w.close()
            sim.detener()
            pv.desconectar()
        with open(ruta_pulsos, encoding="utf-8") as f:
            filas = sorted(csv.DictReader(f), key=lambda r: int(r["n"]))  # se escriben al cerrar su ventana
    assert [r["resultado"] for r in filas] == [
        "completo", "rechazado por el firmware", "PARO manual", "app cerrada durante el pulso"], \
        [(r["n"], r["resultado"]) for r in filas]
    print("  simulador: '0' al conectar, diálogo, pulso, enfriamiento, WARMUP, rechazo, PARO y cierre")


def test_tabla_solo_revisa_pulsos_abiertos():
    """La tabla sigue los cambios de un pulso abierto (también el último, al cerrarse su ventana) y no vuelve a
    revisar las filas de pulsos terminados: revisarlas todas en cada tic subía el CPU con 200 pulsos."""
    qt_util.app()
    from motorguard_dashboard.inyeccion.control import ControlInyeccion, Pulso
    from motorguard_dashboard.ui.panel_inyeccion import PanelInyeccion
    c = ControlInyeccion()
    for n in range(1, 201):
        c.pulsos.append(Pulso(n=n, serie=n, pulso_en_serie=1, taps="INTER", t_solicitud=0, duracion=5,
                              confirmacion_fw="encendido", resultado="completo"))
    p = PanelInyeccion(c, lambda s: True)
    p._timer.stop()
    p._refrescar()
    assert p.tabla.rowCount() == 200
    assert p.tabla.item(199, 4).text() == "no"
    # El último pulso sigue en su ventana de firma: su fila se actualiza
    ultimo = c.pulsos[-1]
    c._en_ventana.append(ultimo)
    p._refrescar()
    ultimo.alarma, ultimo.sev_max = True, 2
    p._refrescar()
    assert p.tabla.item(199, 4).text() == "sí" and p.tabla.item(199, 5).text() == "INTER"
    # Se cierra la ventana con un último cambio: se ve en el refresco siguiente
    c._en_ventana.clear()
    ultimo.sev_max = 3
    p._refrescar()
    assert p.tabla.item(199, 5).text() == "SEVERA"
    # Un pulso terminado ya no se revisa (su objeto no cambia en la app; aquí se fuerza para comprobarlo)
    c.pulsos[0].resultado = "cambiado"
    p._refrescar()
    assert p.tabla.item(0, 3).text() == "completo"
    print("  tabla de pulsos: solo se revisan los abiertos y el que acaba de cerrarse")


def run():
    test_dialogo_exige_todas_las_casillas()
    test_ventana_con_simulador()
    test_tabla_solo_revisa_pulsos_abiertos()
    print("✓ Panel de inyección con simulador: 3/3 pruebas")


if __name__ == "__main__":
    run()
