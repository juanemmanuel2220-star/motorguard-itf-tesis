"""
Mecanismos de estabilidad a largo plazo:
app.log con captura de excepciones, rotación del log crudo, hilo de lectura que sobrevive a un error y se
reinicia si muere, aviso de permiso (dialout), instancia única, rutas configurables y topes de memoria.
"""

import glob
import os
import stat
import sys
import tempfile
import threading
import time

from motorguard_dashboard.tests import qt_util
from motorguard_dashboard.tests.test_fuente_serie import PuertoVirtual, _esperar
from motorguard_dashboard.tests.test_telemetry_parser import L_INTER, L_SANO


def test_bitacora_captura_excepciones():
    qt_util.app()
    from motorguard_dashboard.sistema import bitacora
    with tempfile.TemporaryDirectory() as d:
        avisos = []
        bitacora.notificador.error.connect(avisos.append)
        previo_py, previo_hilo = sys.excepthook, threading.excepthook
        try:
            ruta = bitacora.configurar(d, a_consola=False)
            try:
                raise ValueError("falla de prueba en el hilo principal")
            except ValueError:
                sys.excepthook(*sys.exc_info())

            def falla():
                raise RuntimeError("falla de prueba en un hilo")
            h = threading.Thread(target=falla, name="hilo-prueba")
            h.start()
            h.join()
            qt_util.app().processEvents()
            texto = open(ruta, encoding="utf-8").read()
            assert "falla de prueba en el hilo principal" in texto and "Traceback" in texto
            assert "hilo-prueba" in texto and "falla de prueba en un hilo" in texto
            assert len(avisos) == 2
        finally:
            bitacora.notificador.error.disconnect(avisos.append)
            bitacora.restablecer()
            sys.excepthook, threading.excepthook = previo_py, previo_hilo


def test_rotacion_del_log_crudo():
    from motorguard_dashboard.telemetry.parser import Trama, parsear_linea
    from motorguard_dashboard.telemetry.registro_crudo import RegistroCrudo
    with tempfile.TemporaryDirectory() as d:
        base = os.path.join(d, "sesion_20261011_120000_serial.log")
        reloj = {"t": 0.0}
        reg = RegistroCrudo(base, max_bytes=5000, max_s=60, reloj=lambda: reloj["t"])
        for k in range(30):                       # ~560 B por línea (16 KB) -> rota por tamaño
            reg.escribir(1000.0 + k, L_SANO[15:])
        partes_tam = reg.parte
        reloj["t"] = 61                            # rota por tiempo aunque el archivo sea chico
        reg.escribir(2000.0, L_INTER[15:])
        reg.cerrar()
        # Orden por parte: el archivo base es la 1 y luego _p002, _p003, ...
        archivos = [base] + sorted(f for f in glob.glob(os.path.join(d, "*_serial.log")) if f != base)
        assert partes_tam == 3 and len(archivos) == partes_tam + 1
        assert os.path.basename(archivos[1]) == "sesion_20261011_120000_p002_serial.log"
        tramas = [x for f in archivos for x in map(parsear_linea, open(f, encoding="utf-8")) if isinstance(x, Trama)]
        assert len(tramas) == 31, "se perdió alguna línea al rotar"
        assert all(os.path.getsize(f) <= 5000 + 600 for f in archivos)


def test_lectura_sobrevive_a_un_error_y_se_reinicia():
    app = qt_util.app()
    from motorguard_dashboard.telemetry import fuente_serie
    from motorguard_dashboard.telemetry.fuente_serie import FuenteSerie
    with tempfile.TemporaryDirectory() as d:
        pv = PuertoVirtual(d)
        pv.iniciar()
        datos, estados = [], []
        f = FuenteSerie(pv.a)
        f.sig_dato.connect(datos.append)
        f.sig_estado.connect(lambda ok, m: estados.append((ok, m)))
        original = fuente_serie.parsear_linea
        veces = {"n": 0}

        def parser_que_falla(linea):
            veces["n"] += 1
            if veces["n"] == 1:
                raise RuntimeError("error inesperado de prueba")
            return original(linea)

        fuente_serie.parsear_linea = parser_que_falla
        try:
            f.start()
            assert _esperar(lambda: any(ok for ok, _ in estados))
            pv.escribir(L_SANO[15:])                       # esta provoca el error
            assert _esperar(lambda: any("Error interno" in m for _, m in estados))
            assert f.isRunning(), "el hilo murió por un error inesperado"
            assert _esperar(lambda: sum(ok for ok, _ in estados) >= 2, 8), estados    # reconectó
            pv.escribir(L_SANO[15:])
            assert _esperar(lambda: len(datos) == 1)

            # Muerte inesperada del hilo (no pedida con detener()): reiniciar() lo levanta
            f._detener = True
            assert _esperar(lambda: not f.isRunning(), 5)
            assert not f.detenida and f.reiniciar() and f.reinicios == 1
            assert _esperar(lambda: f.isRunning())
            f.detener()
            assert not f.reiniciar(), "no debe reiniciarse si se pidió detener"
        finally:
            fuente_serie.parsear_linea = original
            f.detener()
            pv.desconectar()


def test_aviso_de_permiso_dialout():
    if os.geteuid() == 0:
        return  # root ignora los permisos
    from motorguard_dashboard.telemetry.fuente_serie import FuenteSerie
    with tempfile.TemporaryDirectory() as d:
        pv = PuertoVirtual(d)
        pv.iniciar()
        real = os.path.realpath(pv.a)
        modo = os.stat(real).st_mode
        os.chmod(real, 0)
        try:
            ok, msg = FuenteSerie(pv.a)._abrir()
            assert not ok and "dialout" in msg, msg
        finally:
            os.chmod(real, stat.S_IMODE(modo))
            pv.desconectar()


def test_instancia_unica():
    qt_util.app()
    from motorguard_dashboard.sistema.instancia import InstanciaUnica
    with tempfile.TemporaryDirectory() as d:
        ruta = os.path.join(d, "arduino.lock")
        a, b = InstanciaUnica(ruta), InstanciaUnica(ruta)
        assert a.tomar() == (True, None)
        tomada, pid = b.tomar()
        assert not tomada and pid == os.getpid()
        a.soltar()
        assert b.tomar()[0]
        b.soltar()
        del a, b                                    # antes de borrar la carpeta temporal


def test_rutas_configurables():
    from PySide6.QtCore import QSettings
    from motorguard_dashboard.sistema import rutas
    with tempfile.TemporaryDirectory() as d:
        conf = QSettings(os.path.join(d, "ajustes.ini"), QSettings.IniFormat)
        assert rutas.dir_registros(conf) == rutas.dir_registros_defecto()
        assert rutas.dir_registros_defecto().endswith(os.path.join("MotorGuard-ITF", "registros"))
        rutas.poner_dir_registros(os.path.join(d, "regs"), conf)
        assert rutas.dir_registros(conf) == os.path.join(d, "regs")
        rutas.recordar_dir_reproduccion(os.path.join(d, "x_serial.log"), conf)
        assert rutas.dir_reproduccion(conf) == d


def test_topes_de_memoria():
    from motorguard_dashboard.inyeccion import control as mod_control
    from motorguard_dashboard.telemetry import alarmas as mod_alarmas
    from motorguard_dashboard.telemetry.parser import parsear_linea
    import dataclasses
    sana, alarma = parsear_linea(L_SANO), parsear_linea(L_INTER)
    reg = mod_alarmas.RegistroAlarmas()
    tope = mod_alarmas.MAX_EVENTOS_MEMORIA
    for k in range(tope + 7):
        reg.procesar(dataclasses.replace(alarma, t=10.0 * k))
        reg.procesar(dataclasses.replace(sana, t=10.0 * k + 5))
    assert len(reg.eventos) == tope and reg.eventos[-1].id == tope + 7

    qt_util.app()
    from motorguard_dashboard.telemetry.alarmas import EventoAlarma, RegistroAlarmas
    from motorguard_dashboard.ui import monitor_window as mw
    from motorguard_dashboard.telemetry.fuente_replay import FuenteReplay
    from motorguard_dashboard.tests.test_telemetry_parser import DIR_VIVO
    w = mw.MonitorWindow(FuenteReplay(os.path.join(DIR_VIVO, "vivo_INTER_75%_20261009_1513_serial.log"), 1e6),
                         RegistroAlarmas(), True, "prueba")
    try:
        while w.fuente.isRunning():
            qt_util.app().processEvents()
        qt_util.app().processEvents()               # señales que quedaron en cola al terminar el hilo
        n0 = w.tabla.rowCount()
        for k in range(mw.MAX_FILAS_ALARMAS + 25):
            ev = EventoAlarma(id=1000 + k, t_inicio=float(k), sev_inicial=2, ml_inicial=2.0, p_inicial=2.0,
                              i1=7.8, ia=5.5, ib=5.8, ic=5.4, ya_activa=False, sev_max=2, ml_max=2.3, t_ultima=float(k))
            w._actualizar_fila(ev)
        assert w.tabla.rowCount() == mw.MAX_FILAS_ALARMAS
        assert w.tabla.item(w.tabla.rowCount() - 1, 0).text() == str(1000 + mw.MAX_FILAS_ALARMAS + 24)
        ultimo = EventoAlarma(id=1000 + mw.MAX_FILAS_ALARMAS + 24, t_inicio=0.0, sev_inicial=2, ml_inicial=2.0,
                              p_inicial=2.0, i1=7.8, ia=5.5, ib=5.8, ic=5.4, ya_activa=False, sev_max=3,
                              ml_max=5.0, t_ultima=1.0)
        w._actualizar_fila(ultimo)                 # actualizar la última no agrega filas
        assert w.tabla.rowCount() == mw.MAX_FILAS_ALARMAS
        assert w.tabla.item(w.tabla.rowCount() - 1, 5).text() == "SEVERA"
        assert n0 == 10
    finally:
        w.close()
    assert mod_control.MAX_PULSOS_MEMORIA >= 200


def run():
    test_bitacora_captura_excepciones()
    test_rotacion_del_log_crudo()
    test_lectura_sobrevive_a_un_error_y_se_reinicia()
    test_aviso_de_permiso_dialout()
    test_instancia_unica()
    test_rutas_configurables()
    test_topes_de_memoria()
    print("✓ Estabilidad: 7/7 pruebas")


if __name__ == "__main__":
    run()
