"""
Modo demo (app.py --demo, solo capturas): el simulador reproduce tramas REALES del banco, inyecta un episodio real
al recibir '1' y, en modo enclavado, la alarma solo se libera con 'r'.
"""

import os
import select
import time
import tty

from motorguard_dashboard.telemetry.parser import Trama, parsear_linea
from motorguard_dashboard.tests.simulador_demo import LOG_DEMO, SimuladorDemo, episodios_y_reposo


def _leer_tramas(fd, n, limite=10.0):
    buf, tramas, fin = "", [], time.monotonic() + limite
    while len(tramas) < n and time.monotonic() < fin:
        if select.select([fd], [], [], 0.05)[0]:
            buf += os.read(fd, 65536).decode(errors="ignore")
            *lineas, buf = buf.split("\n")
            tramas += [o for o in map(parsear_linea, lineas) if isinstance(o, Trama)]
    return tramas


def _sim(enclavada):
    maestro, esclavo = os.openpty()
    tty.setraw(esclavo)
    sim = SimuladorDemo(maestro, enclavada=enclavada, periodo=0.02)
    sim.start()
    return sim, esclavo


def test_episodios_del_log_real():
    episodios, reposo = episodios_y_reposo(LOG_DEMO)
    assert len(episodios) == 10 and len(reposo) > 200
    assert all(any("| INTER |" in x for x in ep) for ep in episodios)
    assert not any(x.startswith("[DEBUG SSR]") for ep in episodios for x in ep)


def test_inyeccion_y_liberacion():
    for enclavada in (False, True):
        sim, fd = _sim(enclavada)
        try:
            assert all(t.decision == "SANO" for t in _leer_tramas(fd, 5))
            os.write(fd, b"1")
            tramas = _leer_tramas(fd, 8)
            assert any(t.decision == "INTER" for t in tramas)
            os.write(fd, b"0")
            despues = _leer_tramas(fd, 30)
            if enclavada:
                assert despues[-1].decision == "INTER"             # no se libera sola
                os.write(fd, b"r")
                assert _leer_tramas(fd, 5)[-1].decision == "SANO"
            else:
                assert despues[-1].decision == "SANO"              # el episodio real termina liberado
        finally:
            sim.detener()
            os.close(fd)
    print("  demo: 10 episodios reales; inyección con alarma INTER; enclavada hasta 'r'")


def run():
    test_episodios_del_log_real()
    test_inyeccion_y_liberacion()
    print("✓ Modo demo: 2/2 pruebas")
