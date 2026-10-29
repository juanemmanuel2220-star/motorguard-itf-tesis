"""
Pruebas de la fuente serie con un puerto virtual (pty), sin Arduino:
lectura, registro crudo, exclusividad, desconexión/reconexión y puerto ocupado por otro programa.
Las líneas que se escriben son reales (ver test_telemetry_parser).
"""

import os
import select
import subprocess
import sys
import tempfile
import time
import tty

import serial

from motorguard_dashboard.telemetry.fuente_serie import FuenteSerie, procesos_con_puerto
from motorguard_dashboard.telemetry.parser import Trama, EventoSSR, parsear_linea
from motorguard_dashboard.tests import qt_util
from motorguard_dashboard.tests.test_telemetry_parser import L_SANO, L_INTER, L_SSR_EXITO


def _esperar(cond, timeout=8.0):
    app = qt_util.app()
    fin = time.monotonic() + timeout
    while time.monotonic() < fin:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.05)
    app.processEvents()
    return cond()


class PuertoVirtual:
    """Pty creado por la prueba: la app abre el esclavo (vía el enlace `a`) y la prueba escribe en el
    maestro como si fuera el Arduino. Cerrar el maestro equivale a desconectar el cable."""

    def __init__(self, d):
        self.a = os.path.join(d, "ttyV0")
        self.maestro = None

    def iniciar(self):
        self.maestro, esclavo = os.openpty()
        tty.setraw(esclavo)  # sin eco, como el CDC del Arduino (si no, lo escrito vuelve al maestro)
        ruta = os.ttyname(esclavo)
        os.close(esclavo)  # nadie más lo tiene abierto, como el Arduino recién conectado
        if os.path.lexists(self.a):
            os.remove(self.a)
        os.symlink(ruta, self.a)

    def leer(self, timeout=2.0) -> bytes:
        """Lo que la app envió al 'Arduino' (comandos)."""
        datos, fin = b"", time.monotonic() + timeout
        while time.monotonic() < fin:
            listo, _, _ = select.select([self.maestro], [], [], 0.05)
            if listo:
                datos += os.read(self.maestro, 1024)
            elif datos:
                break
        return datos

    def escribir(self, *lineas):
        for l in lineas:
            os.write(self.maestro, (l + "\n").encode())

    def desconectar(self):
        if self.maestro is not None:
            os.close(self.maestro)
            self.maestro = None
        if os.path.lexists(self.a):
            os.remove(self.a)


def test_lectura_exclusividad_y_reconexion():
    with tempfile.TemporaryDirectory() as d:
        pv = PuertoVirtual(d)
        pv.iniciar()
        datos, descartadas, estados = [], [], []
        crudo = os.path.join(d, "reg", "sesion_serial.log")
        fuente = FuenteSerie(puerto=pv.a, ruta_crudo=crudo)
        fuente.sig_dato.connect(datos.append)
        fuente.sig_descartada.connect(descartadas.append)
        fuente.sig_estado.connect(lambda ok, m: estados.append((ok, m)))
        fuente.start()
        try:
            assert _esperar(lambda: any(ok for ok, _ in estados)), estados
            assert pv.leer() == b"0\n", "al conectar debe enviarse '0'"
            assert fuente.enviar("1") and pv.leer() == b"1\n"
            for malo in ("h", "2", "k", "n", "R"):
                try:
                    fuente.enviar(malo)
                    raise AssertionError(f"la fuente envió {malo!r}")
                except ValueError:
                    pass
            assert pv.leer(0.3) == b"", "salió algo distinto de '1'/'0'"
            # Líneas como llegan del Arduino (sin la marca de tiempo del archivo)
            t0 = time.time()
            pv.escribir(L_SANO[15:], L_SSR_EXITO[15:], L_INTER[15:], L_INTER[15:200])
            assert _esperar(lambda: len(datos) >= 3 and len(descartadas) >= 1)
            tramas = [x for x in datos if isinstance(x, Trama)]
            assert [t.dir.sev for t in tramas] == [0, 2]
            assert all(t0 - 1 <= x.t <= time.time() + 1 for x in datos)  # hora de recepción
            assert sum(isinstance(x, EventoSSR) for x in datos) == 1
            assert descartadas == [L_INTER[15:200]]

            # El registro crudo es reproducible con el mismo parser
            with open(crudo, encoding="utf-8") as f:
                reg = [parsear_linea(x) for x in f]
            assert sum(isinstance(x, Trama) for x in reg) == 2 and all(x is None or x.t for x in reg)
            with open(crudo, encoding="utf-8") as f:
                assert [x.split(" ", 1)[1].strip() for x in f if ">> TX" in x] == [">> TX 0", ">> TX 1"]

            # Mientras la app tiene el puerto, otro programa no puede abrirlo (TIOCEXCL)
            try:
                serial.Serial(pv.a, 115200, timeout=0.2).close()
                raise AssertionError("otro programa pudo abrir el puerto de la app")
            except serial.SerialException as e:
                assert "Errno 16" in str(e), e  # EBUSY por TIOCEXCL, no otro error

            # Desconexión: se informa y se reintenta; al volver el puerto, reconecta sola
            n_estados = len(estados)
            pv.desconectar()
            assert _esperar(lambda: any(not ok and "perdida" in m for ok, m in estados[n_estados:]))
            assert fuente.enviar("0") is False
            pv.iniciar()
            n_estados = len(estados)
            assert _esperar(lambda: any(ok for ok, _ in estados[n_estados:]), 10), estados[n_estados:]
            assert pv.leer() == b"0\n", "al reconectar debe enviarse '0'"
            n = len(datos)
            pv.escribir(L_SANO[15:])
            assert _esperar(lambda: len(datos) > n)
        finally:
            fuente.detener()
            pv.desconectar()


def test_puerto_ocupado_no_se_interrumpe():
    with tempfile.TemporaryDirectory() as d:
        pv = PuertoVirtual(d)
        pv.iniciar()
        # Otro programa (como un script de validación) tiene el puerto abierto
        otro = subprocess.Popen([sys.executable, "-c",
                                 f"import time; f=open({pv.a!r},'rb'); time.sleep(60)"])
        try:
            assert _esperar(lambda: any(p == otro.pid for p, _ in procesos_con_puerto(pv.a)), 5)
            estados = []
            fuente = FuenteSerie(puerto=pv.a)
            fuente.sig_estado.connect(lambda ok, m: estados.append((ok, m)))
            fuente.start()
            assert _esperar(lambda: any("ocupado" in m for _, m in estados))
            assert f"PID {otro.pid}" in estados[-1][1]
            time.sleep(2.5)  # al menos un reintento
            assert otro.poll() is None, "la app terminó el proceso que tenía el puerto"
            assert not any(ok for ok, _ in estados)
            # Al cerrarse el otro programa, la app se conecta
            otro.terminate()
            otro.wait(5)
            assert _esperar(lambda: any(ok for ok, _ in estados), 6), estados
        finally:
            if otro.poll() is None:
                otro.terminate()
            fuente.detener()
            pv.desconectar()


def test_reconexion_con_puerto_aun_enumerandose():
    """Al reconectar el USB, tcflush (reset_input_buffer) puede fallar con termios.error mientras el Arduino se
    enumera. Es un reintento normal: no debe quedar como "Error inesperado" (ERROR con traza) en app.log."""
    import logging
    import termios
    from motorguard_dashboard.sistema import bitacora
    with tempfile.TemporaryDirectory() as d:
        pv = PuertoVirtual(d)
        pv.iniciar()
        original = serial.Serial.reset_input_buffer
        fallos = {"n": 1}

        def reset_que_falla(self):
            if fallos["n"]:
                fallos["n"] -= 1
                raise termios.error(5, "Input/output error")
            return original(self)

        errores = []

        class Captura(logging.Handler):
            def emit(self, rec):
                if rec.levelno >= logging.ERROR:
                    errores.append(rec.getMessage())
        h = Captura()
        bitacora.LOG.addHandler(h)
        serial.Serial.reset_input_buffer = reset_que_falla
        estados = []
        fuente = FuenteSerie(puerto=pv.a)
        fuente.sig_estado.connect(lambda ok, m: estados.append((ok, m)))
        try:
            fuente.start()
            assert _esperar(lambda: any(ok for ok, _ in estados), 8), estados
            assert any((not ok) and "No se pudo abrir" in m and "Input/output" in m for ok, m in estados), estados
            assert not errores, errores
        finally:
            serial.Serial.reset_input_buffer = original
            bitacora.LOG.removeHandler(h)
            fuente.detener()
            pv.desconectar()
    print("  reconexión: termios.error al abrir es un reintento (aviso), no un ERROR")


def run():
    test_lectura_exclusividad_y_reconexion()
    test_puerto_ocupado_no_se_interrumpe()
    test_reconexion_con_puerto_aun_enumerandose()
    print("✓ Fuente serie (puerto virtual): 3/3 pruebas")


if __name__ == "__main__":
    run()
