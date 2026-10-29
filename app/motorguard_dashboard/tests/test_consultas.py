"""
Pruebas del lector de respuestas a petición ('W', 'f', 's').
'W': volcado REAL del log ~/estabilidad5min_20261006_144431.log (firmware 2dff915, mismo comando).
'f' y 's': no hay ejemplos en los logs; texto DERIVADO de los printf de PRUEBA_MODELO_1.ino
(printSpectrum y la rama 's'), con valores de ejemplo.
"""

import os

from motorguard_dashboard.telemetry.consultas import (
    AcumuladorRespuestas, FormaOnda, EspectroCritico, Indicadores, CONSULTAS_LECTURA,
)

LOG_WAVE = os.path.expanduser("~/estabilidad5min_20261006_144431.log")


def _sin_marca(linea):
    # este log usa marca relativa con espacios al inicio: "   5.10s [WAVE] ..." / "   5.10s 2255,1641,1853"
    partes = linea.strip().split(" ", 1)
    return partes[1] if len(partes) == 2 and partes[0].endswith("s") else linea.strip()


def lineas_wave_reales():
    with open(LOG_WAVE, encoding="utf-8", errors="ignore") as f:
        lineas = [_sin_marca(x) for x in f]
    i = next(k for k, x in enumerate(lineas) if x.startswith("[WAVE] begin"))
    j = next(k for k in range(i, len(lineas)) if lineas[k].startswith("[WAVE] end"))
    return lineas[i:j + 1]


# DERIVADO del printf de printSpectrum() (valores de ejemplo, no medidos)
TEXTO_F = """
================ BARRIDO FFT MULTIFASE (A, B, C) ================
  [FASE A (Pin A1)] Irms=5.40A | Afund=7593.5 | A55=33.2(57.5Hz)[r55=0.004] | A65=33.5(62.2Hz)[r65=0.004]
  [FASE B (Pin A0)] Irms=5.83A | Afund=8147.1 | A55=38.5(57.5Hz)[r55=0.005] | A65=31.3(62.2Hz)[r65=0.004]
  [FASE C (Pin A2)] Irms=5.26A | Afund=7348.0 | A55=35.4(57.5Hz)[r55=0.005] | A65=36.4(62.2Hz)[r65=0.005]  <-- FASE CRITICA
>>> Fase Critica: FASE C | P(LEVE)=45.2% | Diagnostico IA: SANO
-----------------------------------------------------------------
========== ESPECTRO DETALLADO FASE C (50 Hz - 70 Hz) ==========
Fundamental: A_fund = 7348.0 (f0 = 60.0 Hz)
Picos: f55p = 57.5 Hz (A55 = 35.4) | f65p = 62.2 Hz (A65 = 36.4)
 Freq (Hz) | Amplitud | Grafica
-----------+----------+-----------------------------------
""" + "\n".join(f"  {50 + k:4.1f} Hz | {10.0 + k:8.1f} | {'#' * 2}" for k in range(21)) + """
=================================================================
"""

TEXTO_S = ('{"vc":110.9,"ic":5.26,"f55":35.4,"f65":36.4,"f50":20.1,"f70":18.7,"ffund":7348.0,'
           '"ineg":0.0123,"thd":0.0310,"motor":1,"ssr":"OFF"}')


def test_volcado_real_w():
    acum = AcumuladorRespuestas()
    resp = None
    for x in lineas_wave_reales():
        consumida, r = acum.alimentar(x, 1.0)
        assert consumida
        resp = r or resp
    assert isinstance(resp, FormaOnda) and resp.completa and resp.n_declarado == 2048
    assert (resp.ia[0], resp.ib[0], resp.ic[0]) == (2255, 1641, 1853)   # primera muestra del log
    assert not acum.esperando


def test_w_interrumpido_no_se_completa():
    acum = AcumuladorRespuestas()
    lineas = lineas_wave_reales()
    for x in lineas[:100]:
        acum.alimentar(x)
    consumida, r = acum.alimentar("[MCSA] Motor:ON | ...")       # algo inesperado a mitad del volcado
    assert not consumida and r is None and not acum.esperando


def test_espectro_y_indicadores():
    acum = AcumuladorRespuestas()
    resp = None
    for x in TEXTO_F.splitlines():
        consumida, r = acum.alimentar(x)
        if x.strip():
            assert consumida, x
        resp = r or resp
    assert isinstance(resp, EspectroCritico) and resp.fase == "C" and resp.diagnostico == "SANO"
    assert len(resp.puntos) == 21 and resp.puntos[0] == (50.0, 10.0) and resp.puntos[-1] == (70.0, 30.0)
    assert [p["fase"] for p in resp.por_fase] == ["A", "B", "C"] and resp.por_fase[2]["f65"] == 62.2
    assert resp.a_fund == 7348.0 and (resp.f55p, resp.f65p) == (57.5, 62.2)

    consumida, ind = acum.alimentar(TEXTO_S)
    assert consumida and isinstance(ind, Indicadores) and ind.valores["thd"] == 0.031
    assert acum.alimentar('{"otro": 1}') == (False, None)            # JSON que no es la respuesta de 's'


def test_solo_consultas_de_lectura():
    assert set(CONSULTAS_LECTURA) == {"W", "f", "s"}
    for peligroso in ("t", "r", "k", "K", "n", "b", "p", "h", "l", "1", "0", "2", "3"):
        assert peligroso not in CONSULTAS_LECTURA


def run():
    test_volcado_real_w()
    test_w_interrumpido_no_se_completa()
    test_espectro_y_indicadores()
    test_solo_consultas_de_lectura()
    print("✓ Respuestas a petición (W real, f/s derivados): 4/4 pruebas")


if __name__ == "__main__":
    run()
