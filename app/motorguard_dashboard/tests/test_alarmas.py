"""
Pruebas del registro de alarmas con los logs reales de la validación en vivo (firmware 299a943).
El resultado se compara con un conteo independiente hecho sobre el texto del log (sin el parser).
"""

import csv
import glob
import os
import re
import tempfile

from motorguard_dashboard.telemetry.alarmas import RegistroAlarmas
from motorguard_dashboard.telemetry.parser import parsear_linea, NOMBRES_SEV
from motorguard_dashboard.tests.test_telemetry_parser import DIR_VIVO, L_SANO, L_INTER, L_SEVERA

_RE_TXT = re.compile(r"^([\d.]+) \[MCSA\] Motor:(\w+) .* C=([01]) REF=\d CUSUM=-?\d+ SEV=(\d) ML=(-?[\d.]+)")


def _alarmas_por_texto(ruta):
    """Lista de (t_inicio, t_fin, sev_max, ml_max) a partir del texto: flancos de C."""
    out, abierta = [], None
    with open(ruta, encoding="utf-8", errors="ignore") as f:
        for linea in f:
            m = _RE_TXT.match(linea)
            if not m:
                continue
            t, motor, c, sev, ml = float(m[1]), m[2], m[3] == "1", int(m[4]), float(m[5])
            if abierta and (not c or motor == "OFF"):
                out.append((abierta[0], t, abierta[1], abierta[2]))
                abierta = None
            elif not abierta and c and motor != "OFF":
                abierta = [t, sev, ml]
            if abierta:
                abierta[1] = max(abierta[1], sev)
                abierta[2] = max(abierta[2], ml)
    if abierta:
        out.append((abierta[0], None, abierta[1], abierta[2]))
    return out


def _procesar_log(ruta, ruta_csv=None):
    reg = RegistroAlarmas(ruta_csv)
    with open(ruta, encoding="utf-8", errors="ignore") as f:
        for linea in f:
            reg.procesar(parsear_linea(linea))
    return reg


def test_logs_reales_contra_texto():
    resumen = []
    for ruta in sorted(glob.glob(os.path.join(DIR_VIVO, "*_serial.log"))):
        esperado = _alarmas_por_texto(ruta)
        reg = _procesar_log(ruta)
        obtenido = [(e.t_inicio, e.t_fin, e.sev_max, e.ml_max) for e in reg.eventos]
        assert obtenido == esperado, os.path.basename(ruta)
        resumen.append((os.path.basename(ruta), len(obtenido)))
    # Bloques validados: una alarma por prueba real (10 pruebas reales cada uno)
    d = dict(resumen)
    assert d["vivo_INTER_75%_20261009_1513_serial.log"] == 10
    assert d["vivo_SEVERA_75%_20261008_1612_serial.log"] == 10
    print("  alarmas por log:", ", ".join(f"{n.split('_serial')[0][5:]}={k}" for n, k in resumen))


def test_severidad_y_csv_bloque_inter():
    ruta = os.path.join(DIR_VIVO, "vivo_INTER_75%_20261009_1513_serial.log")
    with tempfile.TemporaryDirectory() as d:
        ruta_csv = os.path.join(d, "eventos.csv")
        reg = _procesar_log(ruta, ruta_csv)
        reg.cerrar_sesion(0.0)
        assert all(NOMBRES_SEV[e.sev_max] == "INTER" for e in reg.eventos)
        assert all(e.motivo_fin == "liberada por el firmware" for e in reg.eventos)
        with open(ruta_csv, encoding="utf-8") as f:
            filas = list(csv.DictReader(f))
    alarmas = [r for r in filas if r["tipo"] == "ALARMA"]
    ssr = [r for r in filas if r["tipo"] == "SSR"]
    assert len(alarmas) == 10 and all(r["sev_max"] == "INTER" for r in alarmas)
    assert len(ssr) == 20  # 10 encendidos + 10 apagados (las solicitudes no se anotan)
    for r, e in zip(alarmas, reg.eventos):
        assert abs(float(r["duracion_s"]) - (e.t_fin - e.t_inicio)) < 0.05


def test_conexion_perdida_y_cierre():
    reg = RegistroAlarmas()
    reg.procesar(parsear_linea(L_SANO))
    ev = reg.procesar(parsear_linea(L_INTER))
    assert ev.abierta and not ev.ya_activa and ev.sev_inicial == 2
    reg.procesar(parsear_linea(L_SEVERA))  # la severidad máxima se conserva
    cerrada = reg.conexion_perdida(1791600000.0, "cable desconectado")
    assert cerrada is ev and not ev.abierta and ev.sev_max == 3
    assert ev.t_fin == parsear_linea(L_SEVERA).t  # última trama vista, no la hora de la pérdida
    assert ev.motivo_fin.startswith("conexión perdida")

    # Sesión que empieza con la alarma ya enclavada
    reg2 = RegistroAlarmas()
    ev2 = reg2.procesar(parsear_linea(L_INTER))
    assert ev2.ya_activa
    assert reg2.cerrar_sesion(0.0).motivo_fin == "sesión cerrada con la alarma activa"

    # Motor apagado con alarma abierta
    reg3 = RegistroAlarmas()
    reg3.procesar(parsear_linea(L_SANO))
    reg3.procesar(parsear_linea(L_INTER))
    off = parsear_linea(L_SANO.replace("Motor:ON", "Motor:OFF"))  # DERIVADA
    assert reg3.procesar(off).motivo_fin == "motor apagado"


def test_liberacion_manual():
    """'r' desde la app: la alarma se cierra como liberada manualmente y las tramas enclavadas que el firmware envió
    antes de procesar la 'r' no abren otra; después de una trama sin enclavamiento, una alarma nueva sí se abre."""
    import dataclasses
    reg = RegistroAlarmas()
    inter = parsear_linea(L_INTER)
    reg.procesar(parsear_linea(L_SANO))
    ev = reg.procesar(inter)
    cerrada = reg.liberacion_manual(inter.t + 1.0)
    assert cerrada is ev and ev.motivo_fin == "liberada manualmente (r)" and reg.abierta is None
    assert reg.procesar(dataclasses.replace(inter, t=inter.t + 2.0)) is None and reg.abierta is None
    reg.procesar(dataclasses.replace(parsear_linea(L_SANO), t=inter.t + 3.0))
    nueva = reg.procesar(dataclasses.replace(inter, t=inter.t + 20.0))
    assert nueva is not None and nueva is not ev and nueva.abierta
    # Sin alarma abierta, solo queda la anotación
    assert RegistroAlarmas().liberacion_manual(0.0) is None


def run():
    test_logs_reales_contra_texto()
    test_severidad_y_csv_bloque_inter()
    test_conexion_perdida_y_cierre()
    test_liberacion_manual()
    print("✓ Registro de alarmas: 4/4 pruebas")


if __name__ == "__main__":
    run()
