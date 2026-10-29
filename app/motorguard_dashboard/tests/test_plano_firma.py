"""
Pruebas del "Plano de la firma" (telemetry/firma.py y ui/plano_firma.py):
- el cálculo reproduce detector_dir.cpp en casos armados a mano (líneas DERIVADAS de una trama real);
- la base congelada se despeja exactamente de PL y ML;
- contra los logs reales de ~/tesis_itf/validacion_vivo (firmware 299a943): la P recalculada coincide con
  la del firmware en >= 99 % de las tramas y la ML con la base despejada en >= 99 % (se omite sin los logs);
- la tarjeta dibuja un log real completo en claro y oscuro, y la ventana la alimenta en una reproducción.
"""

import cmath
import dataclasses
import glob
import os

from motorguard_dashboard.telemetry.firma import (
    DIR_FALLA, PlanoFirma, TOL_COINCIDE_PP, UMBRAL_PP, proyectar,
)
from motorguard_dashboard.telemetry.parser import Trama, parsear_linea
from motorguard_dashboard.tests import qt_util
from motorguard_dashboard.tests.test_telemetry_parser import L_SANO

LOGS = sorted(glob.glob(os.path.expanduser("~/tesis_itf/validacion_vivo/vivo_*_serial.log")))


def trama(t, z: complex, p_fw: float = 0.0, c=0, ref=1, sev=0, ml=0.0, pl=0.0, motor="ON"):
    """Trama DERIVADA de L_SANO con R2 tal que R2/|I1|*100 = z (|I1| = 7.7520 A) y el campo DIR indicado."""
    r2 = z * 7.7520 / 100.0
    texto = L_SANO[15:].replace("R2=-0.02469,0.04309", f"R2={r2.real:.5f},{r2.imag:.5f}")
    texto = texto.replace("DIR: P=0.219 R=0 C=0 REF=1 CUSUM=0 SEV=0 ML=0.354 PL=0.178",
                          f"DIR: P={p_fw:.3f} R=0 C={c} REF={ref} CUSUM=0 SEV={sev} ML={ml:.3f} PL={pl:.3f}")
    texto = texto.replace("Motor:ON", f"Motor:{motor}")
    tr = parsear_linea(texto)
    assert isinstance(tr, Trama), texto
    return dataclasses.replace(tr, t=t)


def test_referencia_y_proyeccion():
    pf = PlanoFirma()
    zs = [complex(0.1, 0.8), complex(0.2, 0.9), complex(0.0, 0.7), complex(0.15, 0.85)]
    for k, z in enumerate(zs):
        e = pf.procesar(trama(100.0 + 1.7 * k, z, ref=0))
        assert e.ref is None and e.p_app is None            # REF=0 en el firmware: no se dibuja referencia
    # t = 110.2: edades 10.2, 8.5, 6.8 y 5.1 -> la referencia usa los 3 primeros (mediana por componente)
    ref = complex(0.1, 0.8)
    z = ref + 0.9 * DIR_FALLA + 0.3 * DIR_FALLA * 1j       # 0.9 pp en la dirección de falla y 0.3 de lado
    e = pf.procesar(trama(110.2, z, p_fw=0.9))
    assert abs(e.ref - ref) < 1e-3, e.ref                  # R2 se imprime con 5 decimales
    assert abs(e.p_app - 0.9) < 2e-3 and e.coincide and e.p_app >= UMBRAL_PP
    assert abs(abs(e.dz) - abs(complex(0.9, 0.3))) < 2e-3
    # P del firmware distinta: se marca como aproximada
    e2 = pf.procesar(trama(111.9, z, p_fw=0.5))
    assert not e2.coincide


def test_base_desde_firmware():
    base = complex(0.12, 0.85)
    for d in (2.2 * DIR_FALLA + 0.4j * DIR_FALLA, 0.3 * DIR_FALLA - 0.25j * DIR_FALLA, 5.0 * DIR_FALLA):
        z = base + d
        pl, ml = proyectar(z - base), abs(z - base)
        sol = PlanoFirma.base_desde_firmware(z, pl, ml, base + 0.05)
        assert abs(sol - base) < 1e-9, (d, sol)


def test_confirmacion_base_y_reinicios():
    pf = PlanoFirma()
    t = 200.0
    for k in range(8):
        pf.procesar(trama(t, complex(0.1, 0.8)))
        t += 1.7
    base = complex(0.1, 0.8)
    zf = base + 2.25 * DIR_FALLA + 0.6j * DIR_FALLA       # con ML ~ PL el despeje amplifica el redondeo
    e = pf.procesar(trama(t, zf, p_fw=proyectar(zf - base), c=1, sev=2, ml=2.25, pl=proyectar(zf - base)))
    assert e.enclavada and abs(e.base - base) < 1e-3          # R2 se imprime con 5 decimales
    t += 1.7
    e = pf.procesar(trama(t, zf, p_fw=0.3, c=1, sev=2, ml=abs(zf - base), pl=proyectar(zf - base)))
    assert abs(e.base - base) < 2e-3 and abs(e.ml_app - e.ml_fw) <= TOL_COINCIDE_PP
    # Motor apagado: se reinicia todo
    assert pf.procesar(trama(t + 1.7, 0j, motor="OFF")) is None and pf.base is None and not pf.hist
    # La hora retrocede (otra corrida en el mismo log): se reinicia el historial
    pf.procesar(trama(500.0, base))
    pf.procesar(trama(501.7, base))
    pf.procesar(trama(300.0, base))
    assert len(pf.hist) == 1
    # Alarma ya enclavada al empezar: se despeja la base desde el primer bloque y se avisa
    pf2 = PlanoFirma()
    e = pf2.procesar(trama(10.0, zf, p_fw=0.2, c=1, sev=2, ml=abs(zf - base), pl=proyectar(zf - base)))
    assert e.base is not None and abs(e.ml_app - e.ml_fw) <= TOL_COINCIDE_PP and e.notas


def test_coincide_con_logs_reales():
    if not LOGS:
        print("    (se omite: no está ~/tesis_itf/validacion_vivo)")
        return
    tot = ok = n_ml = ok_ml = 0
    for ruta in LOGS:
        pf = PlanoFirma()
        for linea in open(ruta, errors="ignore"):
            o = parsear_linea(linea)
            if not isinstance(o, Trama):
                continue
            e = pf.procesar(o)
            if e is None or e.p_app is None:
                continue
            tot += 1
            ok += e.coincide
            if e.base is not None and pf._base_del_fw and abs(e.ml_fw) < 50:   # sin el bloque anómalo de 284 pp
                n_ml += 1
                ok_ml += abs(e.ml_app - e.ml_fw) <= TOL_COINCIDE_PP
    assert tot > 1000 and ok / tot >= 0.99, (ok, tot)
    assert n_ml > 100 and ok_ml / n_ml >= 0.99, (ok_ml, n_ml)
    print(f"    P recalculada = P del firmware en {ok}/{tot} tramas reales; ML con la base despejada en {ok_ml}/{n_ml}")


def test_tarjeta_dibuja_log_real():
    app = qt_util.app()
    from motorguard_dashboard.ui.plano_firma import PlanoFirmaTarjeta
    from motorguard_dashboard.ui.tema import GestorTema
    ruta = os.path.expanduser("~/tesis_itf/validacion_vivo/vivo_INTER_75%_20261009_1513_serial.log")
    if not os.path.exists(ruta):
        print("    (se omite: falta el log INTER del 09-oct)")
        return
    tramas = [o for o in (parsear_linea(l) for l in open(ruta, errors="ignore")) if isinstance(o, Trama)]
    tema = GestorTema(app, persistir=False, modo="claro")
    w = PlanoFirmaTarjeta(tema=tema)
    w.aplicar_tema(tema.t)
    w.show()
    vio_base = vio_ref = False
    for k, tr in enumerate(tramas):
        w.procesar(tr)
        w.mostrar_pendiente()                           # en la app se redibuja como mucho cada 150 ms
        if w.estado is not None:
            vio_ref |= w.estado.ref is not None
            vio_base |= w.estado.base is not None and w.base.data.size > 0
            assert w.valores.valores["p"].text().startswith(f"{tr.dir.p:+.3f}")
        if k == len(tramas) // 2:
            tema.poner_modo("oscuro")
            w.aplicar_tema(tema.t)
    app.processEvents()
    assert vio_ref and vio_base
    w.close()


def test_ventana_alimenta_el_plano():
    app = qt_util.app()
    from motorguard_dashboard.telemetry.alarmas import RegistroAlarmas
    from motorguard_dashboard.telemetry.fuente_replay import FuenteReplay
    from motorguard_dashboard.tests.test_fuente_serie import _esperar
    from motorguard_dashboard.ui.monitor_window import MonitorWindow
    if not LOGS:
        return
    ruta = os.path.expanduser("~/tesis_itf/validacion_vivo/vivo_INTER_75%_20261009_1513_serial.log")
    w = MonitorWindow(FuenteReplay(ruta, 30), RegistroAlarmas(None), es_replay=True, descripcion="prueba")
    w.show()
    try:
        assert _esperar(lambda: w.plano.estado is not None and w.plano.estado.ref is not None, 20)
        w.ir_a(1)                                       # fuera de Monitoreo no se dibuja, pero se sigue calculando
        n = w._n_tramas
        assert _esperar(lambda: w._n_tramas > n + 5, 10)
        w.ir_a(0)                                       # al volver se dibuja lo pendiente
        assert _esperar(lambda: not w.plano._pendiente, 3)
    finally:
        w.close()


def run():
    for nombre, f in sorted(globals().items()):
        if nombre.startswith("test_") and callable(f):
            f()
            print(f"  ✅ plano de la firma: {nombre}")


if __name__ == "__main__":
    run()
