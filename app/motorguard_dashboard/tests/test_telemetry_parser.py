"""
Pruebas del parser de telemetría con líneas reales de ~/tesis_itf/validacion_vivo/*_serial.log
(firmware 299a943). Las líneas sin equivalente en los logs se marcan como DERIVADAS.
"""

import glob
import os

from motorguard_dashboard.telemetry.parser import (
    parsear_linea, separar_marca_tiempo, Trama, EventoSSR, MensajeFirmware
)

DIR_VIVO = os.path.expanduser("~/tesis_itf/validacion_vivo")

# vivo_INTER_75%_20261009_1513_serial.log, línea 1 (SANO, sin alarma)
L_SANO = "1791580418.950 [MCSA] Motor:ON | FallaMax:Fase A | VA=118.1V VB=121.4V VC=110.9V | IA=5.40A IB=5.83A IC=5.26A | Afund=7593.5 A55=33.2(57.5Hz) A65=33.5(62.2Hz) | P_RF=45.2% P_E2=54.2% | SANO | SSR:OFF | U2V=4.84% U2I=2.95% E2=0.64% DOM=1 | HR: L2sM=-35.82 L2sP=-34.48 LrM=-28.40 LrP=-9.64 L3=8.78 L3rM=-22.82 L3rP=-15.84 SNR2s=39.47 s=0.0203 SOK=0 f0=59.982 | CUSUM: S=0.00 Pcal=58.3% | DE2=0.61% dV2=0.48% ANG=-133.1 | RAW: R2=-0.02469,0.04309 I1=7.7520 V2=3.5789,6.7989 V1=158.761 | DIR: P=0.219 R=0 C=0 REF=1 CUSUM=0 SEV=0 ML=0.354 PL=0.178"
# mismo log, primera trama con alarma enclavada INTER
L_INTER = "1791580464.971 [MCSA] Motor:ON | FallaMax:Fase C | VA=115.8V VB=121.5V VC=113.0V | IA=5.60A IB=5.82A IC=5.42A | Afund=7619.9 A55=37.5(56.9Hz) A65=42.3(62.2Hz) | P_RF=46.1% P_E2=100.0% | INTER | SSR:F1(LEVE) | U2V=4.85% U2I=2.55% E2=1.46% DOM=1 | HR: L2sM=-45.44 L2sP=-32.04 LrM=-25.99 LrP=-24.41 L3=2.41 L3rM=-22.77 L3rP=-14.50 SNR2s=40.96 s=0.0202 SOK=0 f0=59.983 | CUSUM: S=8.00 Pcal=97.3% | DE2=2.30% dV2=0.12% ANG=-72.3 | RAW: R2=0.05851,-0.09930 I1=7.9102 V2=4.1836,6.4398 V1=158.176 | DIR: P=2.224 R=3 C=1 REF=1 CUSUM=1 SEV=2 ML=2.251 PL=2.224"
# vivo_SEVERA_75%_20261008_1612_serial.log, primera trama SEV=3
L_SEVERA = "1791497577.582 [MCSA] Motor:ON | FallaMax:Fase B | VA=114.6V VB=127.4V VC=125.6V | IA=5.52A IB=5.95A IC=5.76A | Afund=8214.1 A55=36.7(57.5Hz) A65=41.7(62.2Hz) | P_RF=46.6% P_E2=100.0% | SEVERA | SSR:F1(LEVE) | U2V=3.55% U2I=5.85% E2=4.12% DOM=1 | HR: L2sM=-33.92 L2sP=-32.12 LrM=-32.95 LrP=-8.99 L3=7.77 L3rM=-18.81 L3rP=-33.03 SNR2s=50.00 s=0.0270 SOK=1 f0=60.017 | CUSUM: S=8.00 Pcal=97.3% | DE2=5.63% dV2=0.08% ANG=-82.0 | RAW: R2=-0.10802,-0.31481 I1=8.0807 V2=4.5391,3.8401 V1=167.563 | DIR: P=5.917 R=3 C=1 REF=1 CUSUM=1 SEV=3 ML=5.917 PL=5.917"
# vivo_LEVE_75%_20261009_1546_serial.log, primera trama SEV=1
L_LEVE = "1791582471.905 [MCSA] Motor:ON | FallaMax:Fase C | VA=112.4V VB=124.8V VC=118.6V | IA=5.39A IB=5.76A IC=5.21A | Afund=7205.1 A55=35.8(56.9Hz) A65=42.3(62.2Hz) | P_RF=43.2% P_E2=4.1% | LEVE | SSR:F1(LEVE) | U2V=4.45% U2I=2.39% E2=0.56% DOM=1 | HR: L2sM=-28.55 L2sP=-33.75 LrM=-25.60 LrP=-6.49 L3=10.30 L3rM=-21.60 L3rP=-16.28 SNR2s=51.40 s=0.0333 SOK=0 f0=60.017 | CUSUM: S=0.00 Pcal=3.9% | DE2=0.44% dV2=0.12% ANG=-83.1 | RAW: R2=0.02062,0.03762 I1=7.6905 V2=3.8206,6.0662 V1=161.232 | DIR: P=0.492 R=3 C=1 REF=1 CUSUM=0 SEV=1 ML=0.581 PL=0.492"
# vivo_SEVERA_75%_20261008_1637_serial.log (motor apagado)
L_OFF = "1791499288.104 [MCSA] Motor:OFF | FallaMax:Fase A | VA=0.0V VB=0.0V VC=0.0V | IA=0.00A IB=0.00A IC=0.00A | Afund=0.0 A55=0.0(60.0Hz) A65=0.0(60.0Hz) | P_RF=0.0% P_E2=0.0% | SANO | SSR:OFF | U2V=0.00% U2I=0.00% E2=0.00% DOM=1 | HR: L2sM=0.00 L2sP=0.00 LrM=0.00 LrP=0.00 L3=0.00 L3rM=0.00 L3rP=0.00 SNR2s=0.00 s=0.0120 SOK=0 f0=60.000 | CUSUM: S=0.00 Pcal=0.0% | DE2=0.00% dV2=0.00% ANG=0.0 | RAW: R2=0.00000,0.00000 I1=0.0000 V2=0.0000,0.0000 V1=0.000 | DIR: P=0.000 R=0 C=0 REF=0 CUSUM=0 SEV=0 ML=0.000 PL=0.000"
# DERIVADA: los logs con DIR no tienen tramas en WARMUP; se toma L_SANO con Motor:WARMUP y decisión WARMUP,
# que es lo que imprime el firmware en ese estado (PRUEBA_MODELO_1.ino l. 1420 y namePred(-1)).
L_WARMUP = L_SANO.replace("Motor:ON", "Motor:WARMUP").replace("| SANO |", "| WARMUP |")

# Mensajes del SSR reales (vivo_INTER_75%_20261009_1513_serial.log, líneas 25, 26 y 37)
L_SSR_SOLICITUD = "1791580458.860 [DEBUG SSR] Solicitud F1 | I_rms=5.83A | Cooldown=372168 ms"
L_SSR_EXITO = "1791580458.862 [DEBUG SSR] Exito: GPIO 8 puesto en HIGH (3V)"
L_SSR_APAGADO = "1791580470.098 [DEBUG SSR] Apagado. Forzado: 0 | T_ON: 11215 ms"
# DERIVADAS del formato del firmware (ssrOn/ssrOff, l. 780-806): no aparecen en los logs
L_SSR_FORZADO = "[DEBUG SSR] Apagado. Forzado: 1 | T_ON: 12001 ms"
L_SSR_RECHAZO_MOTOR = "[DEBUG SSR] Rechazado: Motor apagado. Peligro de Inrush."
L_SSR_RECHAZO_COOLDOWN = "[DEBUG SSR] Rechazado: Cooldown activo (1500/2000 ms)."


def test_marca_de_tiempo():
    assert separar_marca_tiempo(L_SSR_EXITO) == (1791580458.862, L_SSR_EXITO[15:])
    assert separar_marca_tiempo("   6.78s [MCSA] x".strip())[0] == 6.78
    assert separar_marca_tiempo("[MCSA] x") == (None, "[MCSA] x")


def test_tramas_reales():
    s = parsear_linea(L_SANO)
    assert isinstance(s, Trama)
    assert s.t == 1791580418.950 and s.motor == "ON" and s.decision == "SANO" and s.ssr == "OFF"
    assert (s.va, s.vb, s.vc) == (118.1, 121.4, 110.9)
    assert (s.ia, s.ib, s.ic) == (5.40, 5.83, 5.26)
    assert s.i1 == 7.7520
    d = s.dir
    assert (d.p, d.racha, d.enclavada, d.ref, d.cusum, d.sev, d.ml, d.pl) == (0.219, 0, False, True, 0, 0, 0.354, 0.178)

    i = parsear_linea(L_INTER)
    assert i.decision == "INTER" and i.ssr == "F1(LEVE)"
    assert i.dir.enclavada and i.dir.sev == 2 and i.dir.nombre_sev == "INTER" and i.dir.p == 2.224 and i.dir.ml == 2.251

    v = parsear_linea(L_SEVERA)
    assert v.dir.enclavada and v.dir.sev == 3 and v.dir.nombre_sev == "SEVERA" and v.dir.ml == 5.917

    l = parsear_linea(L_LEVE)
    assert l.dir.enclavada and l.dir.sev == 1 and l.dir.ml == 0.581 and l.dir.cusum == 0

    o = parsear_linea(L_OFF)
    assert o.motor == "OFF" and not o.dir.ref and o.i1 == 0.0

    w = parsear_linea(L_WARMUP)
    assert w.motor == "WARMUP" and w.decision == "WARMUP"

    # Sin marca de tiempo (como llega directo del puerto)
    assert parsear_linea(L_INTER[15:]).t is None


def test_eventos_ssr():
    e = parsear_linea(L_SSR_SOLICITUD)
    assert isinstance(e, EventoSSR) and e.tipo == "solicitud"
    assert parsear_linea(L_SSR_EXITO).tipo == "encendido"
    a = parsear_linea(L_SSR_APAGADO)
    assert a.tipo == "apagado" and a.forzado is False and a.t_on_ms == 11215
    f = parsear_linea(L_SSR_FORZADO)
    assert f.tipo == "apagado" and f.forzado is True and f.t_on_ms == 12001
    r = parsear_linea(L_SSR_RECHAZO_MOTOR)
    assert r.tipo == "rechazado" and r.motivo == "Motor apagado. Peligro de Inrush"
    assert parsear_linea(L_SSR_RECHAZO_COOLDOWN).motivo.startswith("Cooldown activo")


def test_otras_lineas():
    z = parsear_linea("1791581050.797 [Zero SSR] Retorno a SANO confirmado. Base fasorial resincronizada (|R2|/|I1| = 0.921%)")
    assert isinstance(z, MensajeFirmware) and z.texto.startswith("[Zero SSR]")
    assert parsear_linea("") is None
    assert parsear_linea("basura sin corchete") is None
    assert parsear_linea("12,34,56") is None


def test_lineas_cortadas_se_rechazan():
    """Ningún corte de la trama (pérdida en el puerto serie) puede producir una Trama parcial."""
    for linea in (L_SANO, L_INTER, L_SEVERA):
        for corte in range(len(linea) - 1, 15, -7):
            assert not isinstance(parsear_linea(linea[:corte]), Trama), f"aceptó una trama cortada en {corte}"
        assert parsear_linea(linea[:-1]) is None  # corte en el último dígito de PL


def test_logs_reales_completos():
    """Recorre todos los logs y compara contra un conteo independiente de texto.

    Solo el firmware congelado 299a943 imprime SEV/ML/PL; las tramas de firmwares anteriores
    (logs del 06 y 07-oct) no deben aceptarse, ni completas ni a medias.
    """
    logs = sorted(glob.glob(os.path.join(DIR_VIVO, "*_serial.log")))
    assert logs, f"no hay logs en {DIR_VIVO}"
    total = 0
    for ruta in logs:
        with open(ruta, encoding="utf-8", errors="ignore") as f:
            lineas = f.read().splitlines()
        esperadas = [x for x in lineas if "[MCSA]" in x and "| DIR: P=" in x and " SEV=" in x]
        tramas = [t for t in map(parsear_linea, lineas) if isinstance(t, Trama)]
        assert len(tramas) == len(esperadas), f"{os.path.basename(ruta)}: {len(tramas)} != {len(esperadas)}"
        assert sum(t.dir.enclavada for t in tramas) == sum(" C=1 REF=" in x for x in esperadas)
        for k in range(4):
            assert sum(t.dir.sev == k for t in tramas) == sum(f" SEV={k} " in x for x in esperadas)
        assert sum(isinstance(e, EventoSSR) for e in map(parsear_linea, lineas)) == \
            sum("[DEBUG SSR]" in x for x in lineas)
        total += len(tramas)

    # Cifras fijas del bloque INTER validado (09-oct 15:13), verificadas con grep
    with open(os.path.join(DIR_VIVO, "vivo_INTER_75%_20261009_1513_serial.log"), encoding="utf-8") as f:
        inter = [t for t in map(parsear_linea, f) if isinstance(t, Trama)]
    assert len(inter) == 385
    assert sum(t.dir.enclavada for t in inter) == 65
    assert sum(t.dir.sev == 2 for t in inter) == 65

    # Firmware anterior (81657f4, sin SEV): ninguna trama aceptada
    with open(os.path.join(DIR_VIVO, "vivo_LEVE_75%_20261007_1450_serial.log"), encoding="utf-8") as f:
        assert not any(isinstance(t, Trama) for t in map(parsear_linea, f))
    print(f"✓ {len(logs)} logs, {total} tramas del firmware 299a943 leídas sin discrepancias")


def run():
    test_marca_de_tiempo()
    test_tramas_reales()
    test_eventos_ssr()
    test_otras_lineas()
    test_lineas_cortadas_se_rechazan()
    test_logs_reales_completos()
    print("✓ Parser de telemetría: 6/6 pruebas")


if __name__ == "__main__":
    run()
