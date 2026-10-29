"""
Pestaña Dashboard: datos de la trama en reproducción y capturas a petición con el SIMULADOR del
firmware (solo pruebas): respuestas, bloqueo durante un pulso, intervalo mínimo y PARO global.
"""

import os
import tempfile
import time

from motorguard_dashboard.tests import qt_util
from motorguard_dashboard.tests.simulador_firmware import SimuladorFirmware
from motorguard_dashboard.tests.test_consultas import LOG_WAVE
from motorguard_dashboard.tests.test_fuente_serie import PuertoVirtual, _esperar
from motorguard_dashboard.tests.test_telemetry_parser import DIR_VIVO


def test_replay_llena_el_dashboard():
    app = qt_util.app()
    from motorguard_dashboard.telemetry.alarmas import RegistroAlarmas
    from motorguard_dashboard.telemetry.fuente_replay import FuenteReplay
    from motorguard_dashboard.ui.monitor_window import MonitorWindow
    fuente = FuenteReplay(os.path.join(DIR_VIVO, "vivo_INTER_75%_20261009_1513_serial.log"), velocidad=1e6)
    w = MonitorWindow(fuente, RegistroAlarmas(), es_replay=True, descripcion="prueba")
    assert w.secciones == ["Monitoreo", "Dashboard", "Adquisición", "Asistente"]
    assert w.btn_paro is None and not w.dashboard.botones
    fin = time.monotonic() + 30
    while fuente.isRunning() or not w.lbl_fuente.text().startswith("○"):
        app.processEvents()
        assert time.monotonic() < fin
        time.sleep(0.01)
    app.processEvents()
    d = w.dashboard
    # Última trama del log (1791581073.268): IA=5.39 U2I=2.56% f0=59.973
    assert d.tarjetas["ia"].text() == "5.39" and d.valores["U2I"][0].text() == "2.56 %"
    assert d.valores["f0"][0].text() == "59.973 Hz" and d.tarjetas["act"].text() == "10"
    w.close()


def test_botones_zoom():
    """Zoom (17-oct): + muestra la mitad del tiempo siguiendo el último dato, − el doble y Ajustar vuelve a todo."""
    app = qt_util.app()
    from motorguard_dashboard.telemetry.parser import Trama, parsear_linea
    from motorguard_dashboard.ui.dashboard_tab import DashboardTab
    w = DashboardTab(consultar=lambda c: True)
    w.resize(1300, 1100)
    w.show()
    for linea in open(os.path.join(DIR_VIVO, "vivo_INTER_75%_20261009_1513_serial.log"), errors="replace"):
        o = parsear_linea(linea)
        if isinstance(o, Trama):
            w.procesar(o)
    app.processEvents()
    vb = w.plot_i.getViewBox()
    (x0, x1), _ = vb.viewRange()
    fin = vb.childrenBounds()[0][1]
    w.zoom_i.botones["mas"].click()
    app.processEvents()
    (a0, a1), _ = vb.viewRange()
    assert abs(w.zoom_i.ventana - (x1 - x0) / 2) < 1e-6 and abs(a1 - fin) < 1e-6 and abs((a1 - a0) - w.zoom_i.ventana) < 1e-6
    w.zoom_i.botones["menos"].click()
    assert abs(w.zoom_i.ventana - (x1 - x0)) < 1e-6
    w.zoom_i.botones["ajustar"].click()
    app.processEvents()
    assert w.zoom_i.ventana is None and vb.autoRangeEnabled()[0]
    w.close()
    print("  zoom: + mitad del tiempo pegado al último dato, − el doble, Ajustar vuelve al autoajuste")


def test_replay_con_volcados_grabados():
    """Un log con volcados 'W' (06-oct) entrega las formas de onda también al reproducirlo."""
    qt_util.app()
    from motorguard_dashboard.telemetry.fuente_replay import FuenteReplay
    respuestas = []
    f = FuenteReplay(LOG_WAVE, velocidad=1e6)
    f.sig_respuesta.connect(respuestas.append)
    f.start()
    assert f.wait(30000)
    qt_util.app().processEvents()
    assert len(respuestas) == 3 and all(r.completa for r in respuestas)


def test_capturas_con_simulador():
    app = qt_util.app()
    from PySide6.QtWidgets import QDialog
    from motorguard_dashboard.inyeccion.control import ControlInyeccion, PlanSerie
    from motorguard_dashboard.telemetry.alarmas import RegistroAlarmas
    from motorguard_dashboard.telemetry.fuente_serie import FuenteSerie
    from motorguard_dashboard.ui import dashboard_tab
    from motorguard_dashboard.ui.monitor_window import MonitorWindow
    with tempfile.TemporaryDirectory() as d:
        pv = PuertoVirtual(d)
        pv.iniciar()
        sim = SimuladorFirmware(pv.maestro)
        sim.start()
        control = ControlInyeccion()
        w = MonitorWindow(FuenteSerie(pv.a), RegistroAlarmas(), False, "simulador", control)
        w.show()
        w.ir_a(1)
        db = w.dashboard
        try:
            assert _esperar(lambda: db.botones["W"].isEnabled())
            db.botones["W"].click()
            assert _esperar(lambda: db.curvas_onda[2].getData()[0] is not None), (db.lbl_consulta.text(), sim.recibidos[-5:])
            assert len(db.curvas_onda[2].getData()[0]) == 2048
            assert "2048 muestras" in db.lbl_consulta.text()
            assert not db.botones["f"].isEnabled()                          # intervalo mínimo de 5 s
            db._t_ultima_consulta -= 10
            assert _esperar(lambda: db.botones["f"].isEnabled())
            db.botones["f"].click()
            assert _esperar(lambda: "Fase crítica C" in db.lbl_espectro.text())
            db._t_ultima_consulta -= 10
            assert _esperar(lambda: db.botones["s"].isEnabled())
            db.botones["s"].click()
            assert _esperar(lambda: "THD = 0.031" in db.lbl_indicadores.text())

            # Durante un pulso no se puede consultar; el PARO de la barra funciona desde esta pestaña
            db._t_ultima_consulta -= 10
            conf = control.emitir_confirmacion(PlanSerie("INTER", 11, 1, 15), time.time())
            w.panel_iny._enviar(control.iniciar_serie(conf, time.time()))
            assert _esperar(lambda: sim.ssr)
            # (el refresco de los botones es cada 250 ms: se espera el motivo correcto, no el anterior)
            assert _esperar(lambda: not db.botones["W"].isEnabled() and "inyección" in db.botones["W"].toolTip())
            w.btn_paro.click()
            assert _esperar(lambda: not sim.ssr, 2)
            assert set(sim.recibidos) <= {"0", "1", "W", "f", "s"}
        finally:
            w.close()
            sim.detener()
            pv.desconectar()


def run():
    test_replay_llena_el_dashboard()
    test_replay_con_volcados_grabados()
    test_capturas_con_simulador()
    print("✓ Dashboard: 3/3 pruebas")


if __name__ == "__main__":
    run()
