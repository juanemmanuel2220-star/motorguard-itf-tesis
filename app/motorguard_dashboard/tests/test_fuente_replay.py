"""
Pruebas de la reproducción de logs reales: ritmo, orden, detención y el hilo Qt.
"""

import os
import tempfile

from motorguard_dashboard.telemetry.fuente_replay import lineas_con_ritmo, FuenteReplay
from motorguard_dashboard.telemetry.parser import Trama, EventoSSR
from motorguard_dashboard.tests import qt_util
from motorguard_dashboard.tests.test_telemetry_parser import DIR_VIVO

LOG_INTER = os.path.join(DIR_VIVO, "vivo_INTER_75%_20261009_1513_serial.log")


def _marcas(ruta):
    with open(ruta, encoding="utf-8") as f:
        return [float(x.split(" ", 1)[0]) for x in f if x[:1].isdigit()]


def test_ritmo_y_orden():
    dormido = []
    salida = list(lineas_con_ritmo(LOG_INTER, velocidad=10.0, dormir=dormido.append))
    with open(LOG_INTER, encoding="utf-8") as f:
        originales = f.read().splitlines()
    assert [l for l, _ in salida] == originales
    tramas = [o for _, o in salida if isinstance(o, Trama)]
    assert len(tramas) == 385
    assert all(a.t <= b.t for a, b in zip(tramas, tramas[1:]))
    marcas = _marcas(LOG_INTER)
    esperado = (marcas[-1] - marcas[0]) / 10.0
    assert abs(sum(dormido) - esperado) < 1e-6, (sum(dormido), esperado)
    assert max(dormido) <= 0.1 + 1e-9


def test_detener_a_mitad():
    n = {"lineas": 0}

    def detener():
        return n["lineas"] >= 20

    for _ in lineas_con_ritmo(LOG_INTER, velocidad=1000.0, dormir=lambda s: None, detener=detener):
        n["lineas"] += 1
    assert n["lineas"] == 20


def test_marca_que_retrocede_no_espera():
    with tempfile.TemporaryDirectory() as d:
        ruta = os.path.join(d, "x.log")
        with open(ruta, "w") as f:
            f.write("10.0 [RED] a\n9.0 [RED] b\n9.5 [RED] c\n")
        dormido = []
        list(lineas_con_ritmo(ruta, dormir=dormido.append))
        assert abs(sum(dormido) - 0.5) < 1e-9


def test_hilo_qt():
    app = qt_util.app()
    datos, descartadas, estados = [], [], []
    fuente = FuenteReplay(LOG_INTER, velocidad=1e6)
    fuente.sig_dato.connect(datos.append)
    fuente.sig_descartada.connect(descartadas.append)
    fuente.sig_estado.connect(lambda a, m: estados.append(a))
    fuente.start()
    assert fuente.wait(30000)
    app.processEvents()
    assert sum(isinstance(d, Trama) for d in datos) == 385
    assert sum(isinstance(d, EventoSSR) for d in datos) == 30  # 10 pulsos x 3 mensajes (grep)
    assert descartadas == []
    assert estados == [True, False]


def run():
    test_ritmo_y_orden()
    test_detener_a_mitad()
    test_marca_que_retrocede_no_espera()
    test_hilo_qt()
    print("✓ Reproducción de logs: 4/4 pruebas")


if __name__ == "__main__":
    run()
