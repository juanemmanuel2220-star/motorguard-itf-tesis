"""
Pruebas de los bloqueos de seguridad de la inyección (ControlInyeccion) con reloj simulado.
Las tramas y mensajes del SSR parten de líneas reales (test_telemetry_parser); las variaciones
(motor OFF/WARMUP, SSR encendido, rechazos) se marcan como DERIVADAS.
"""

import csv
import dataclasses
import os
import tempfile

from motorguard_dashboard.inyeccion.control import (
    ControlInyeccion, Confirmacion, PlanSerie, validar_plan, COMANDOS_PERMITIDOS,
    ESPERA_FIRMWARE_S, VENTANA_FIRMA_S, VIGENCIA_CONFIRMACION_S,
)
from motorguard_dashboard.telemetry.parser import parsear_linea
from motorguard_dashboard.tests.test_telemetry_parser import (
    L_SANO, L_INTER, L_SSR_EXITO, L_SSR_APAGADO, L_SSR_FORZADO, L_SSR_RECHAZO_COOLDOWN,
)

T0 = 1_800_000_000.0
SANA = parsear_linea(L_SANO)
CON_ALARMA = parsear_linea(L_INTER)          # C=1 SEV=2 ML=2.251 P=2.224
EXITO = parsear_linea(L_SSR_EXITO)
APAGADO = parsear_linea(L_SSR_APAGADO)
FORZADO = parsear_linea(L_SSR_FORZADO)
RECHAZO = parsear_linea(L_SSR_RECHAZO_COOLDOWN)
PLAN = PlanSerie(taps="INTER", duracion_s=5.0, n_pulsos=2, pausa_s=15.0)


def trama(t, base=SANA, **cambios):
    return dataclasses.replace(base, t=t, **cambios)


def listo(ruta_csv=None, t=T0):
    """Controlador conectado con una trama sana reciente (motor ON, SSR OFF)."""
    c = ControlInyeccion(ruta_csv)
    c.conexion(True, t)
    c.procesar(trama(t), t)
    return c


def test_plan_y_comandos_permitidos():
    assert validar_plan(PLAN) is None
    assert validar_plan(PlanSerie("INTER", 11.0, 10, 15.0)) is None
    assert "duración" in validar_plan(PlanSerie("INTER", 11.5, 1, 15.0))
    assert "duración" in validar_plan(PlanSerie("INTER", 0.5, 1, 15.0))
    assert "pulsos" in validar_plan(PlanSerie("INTER", 5.0, 11, 15.0))
    assert "pausa" in validar_plan(PlanSerie("INTER", 5.0, 1, 14.9))
    assert "pausa" in validar_plan(PlanSerie("SEVERA", 5.0, 1, 19.9))
    assert validar_plan(PlanSerie("SEVERA", 5.0, 1, 20.0)) is None
    assert "taps" in validar_plan(PlanSerie("", 5.0, 1, 20.0))
    assert COMANDOS_PERMITIDOS == ("1", "0")
    for malo in ("h", "l", "p", "2", "3", "k", "K", "n", "R", "b", "t", "10", ""):
        try:
            ControlInyeccion._cmd(malo)
            raise AssertionError(f"aceptó el comando {malo!r}")
        except ValueError:
            pass


def test_sin_confirmacion_humana_no_hay_uno():
    c = listo()
    falsa = Confirmacion(1, PLAN, T0)                      # no emitida por el diálogo
    assert c.iniciar_serie(falsa, T0) == []
    conf = c.emitir_confirmacion(PLAN, T0)
    assert c.iniciar_serie(dataclasses.replace(conf, plan=PlanSerie("SEVERA", 5, 1, 20)), T0) == []  # alterada
    c2 = listo()
    conf2 = c2.emitir_confirmacion(PLAN, T0)
    c2.procesar(trama(T0 + VIGENCIA_CONFIRMACION_S), T0 + VIGENCIA_CONFIRMACION_S)
    assert c2.iniciar_serie(conf2, T0 + VIGENCIA_CONFIRMACION_S + 1) == []  # caducada
    c3 = listo()
    conf3 = c3.emitir_confirmacion(PLAN, T0)
    assert c3.iniciar_serie(conf3, T0) == ["1"]
    assert c3.iniciar_serie(conf3, T0) == []                                # un solo uso
    print("  sin confirmación válida no sale ningún '1'")


def test_bloqueos():
    c = ControlInyeccion()
    assert "conexión" in c.bloqueo(T0)
    c.conexion(True, T0)
    assert "telemetría" in c.bloqueo(T0)
    c.procesar(trama(T0), T0)
    assert c.bloqueo(T0) is None
    assert "telemetría" in c.bloqueo(T0 + 5.1)                              # trama vieja
    for motor in ("OFF", "WARMUP"):
        c.procesar(trama(T0, motor=motor), T0)
        assert motor in c.bloqueo(T0)
        conf = c.emitir_confirmacion(PLAN, T0)
        assert c.iniciar_serie(conf, T0) == [], motor
    c.procesar(trama(T0, ssr="F1(LEVE)"), T0)
    assert "SSR encendido" in c.bloqueo(T0)
    c.procesar(trama(T0), T0)
    c.t_ultimo_apagado, c.taps_ultimo = T0 - 10, "INTER"
    assert "enfriamiento" in c.bloqueo(T0, "INTER")
    c.procesar(trama(T0 + 5), T0 + 5)
    assert c.bloqueo(T0 + 5, "INTER") is None                                # 15 s cumplidos
    assert "enfriamiento" in c.bloqueo(T0 + 5, "SEVERA")                     # SEVERA pide 20 s
    c.taps_ultimo = "SEVERA"
    assert "enfriamiento" in c.bloqueo(T0 + 5, "LEVE")                       # el último fue SEVERA


def test_serie_completa_y_csv():
    with tempfile.TemporaryDirectory() as d:
        ruta = os.path.join(d, "pulsos.csv")
        c = listo(ruta)
        assert c.iniciar_serie(c.emitir_confirmacion(PLAN, T0), T0) == ["1"]
        assert c.tic(T0 + 0.5) == []
        c.procesar(EXITO, T0 + 0.1)
        assert c.estado == c.ENCENDIDO
        c.procesar(trama(T0 + 1.8, CON_ALARMA, ssr="F1(LEVE)"), T0 + 1.8)
        assert c.tic(T0 + 4.9) == []
        assert c.tic(T0 + 5.1) == ["0"]                                      # duración cumplida
        c.procesar(APAGADO, T0 + 5.2)
        assert c.estado == c.PAUSA
        c.procesar(trama(T0 + 6), T0 + 6)
        assert c.tic(T0 + 5.2 + 14.9) == []                                   # pausa de 15 s
        c.procesar(trama(T0 + 20.1), T0 + 20.1)
        assert c.tic(T0 + 20.3) == ["1"]                                      # segundo pulso
        c.procesar(EXITO, T0 + 20.4)
        assert c.tic(T0 + 25.5) == ["0"]
        c.procesar(APAGADO, T0 + 25.6)
        assert c.estado == c.LIBRE and "serie terminada" in c.mensaje
        c.tic(T0 + 25.6 + VENTANA_FIRMA_S + 0.1)
        c.cerrar(T0 + 40)
        with open(ruta, encoding="utf-8") as f:
            filas = list(csv.DictReader(f))
    assert [r["pulso_en_serie"] for r in filas] == ["1", "2"]
    p1 = filas[0]
    assert p1["confirmacion_fw"] == "encendido" and p1["resultado"] == "completo"
    assert p1["t_on_ms_fw"] == "11215" and p1["forzado_fw"] == "0"        # del mensaje real del firmware
    assert p1["alarma_confirmada"] == "1" and p1["sev_max"] == "INTER" and p1["ml_max_pp"] == "2.251"
    assert p1["latencia_alarma_s"] == "1.7" and p1["taps_declarados"] == "INTER"
    assert filas[1]["alarma_confirmada"] == "0"


def test_rechazo_y_falta_de_respuesta():
    c = listo()
    c.iniciar_serie(c.emitir_confirmacion(PLAN, T0), T0)
    assert c.procesar(RECHAZO, T0 + 0.1) == ["0"]
    assert c.estado == c.LIBRE and c.pulsos[0].confirmacion_fw == "rechazado"
    assert c.pulsos[0].motivo_rechazo.startswith("Cooldown activo")

    c = listo()
    c.iniciar_serie(c.emitir_confirmacion(PLAN, T0), T0)
    assert c.tic(T0 + ESPERA_FIRMWARE_S - 0.1) == []
    assert c.tic(T0 + ESPERA_FIRMWARE_S + 0.1) == ["0"]
    assert c.estado == c.LIBRE and c.pulsos[0].confirmacion_fw == "sin respuesta"


def test_apagado_sin_confirmar():
    c = listo()
    c.iniciar_serie(c.emitir_confirmacion(PlanSerie("LEVE", 2, 1, 15), T0), T0)
    c.procesar(EXITO, T0 + 0.1)
    assert c.tic(T0 + 2.2) == ["0"]
    assert c.tic(T0 + 2.2 + ESPERA_FIRMWARE_S + 0.1) == ["0"]                  # reenvío
    c.tic(T0 + 2.2 + 2 * ESPERA_FIRMWARE_S + 0.3)
    assert c.estado == c.LIBRE and "⚠" in c.mensaje

    # La telemetría con SSR:OFF también confirma el apagado
    c = listo()
    c.iniciar_serie(c.emitir_confirmacion(PlanSerie("LEVE", 2, 1, 15), T0), T0)
    c.procesar(EXITO, T0 + 0.1)
    c.tic(T0 + 2.2)
    c.procesar(trama(T0 + 2.4), T0 + 2.4)                                      # 0.2 s: muy pronto
    assert c.estado == c.ESPERA_APAGADO
    c.procesar(trama(T0 + 3.0), T0 + 3.0)
    assert c.estado == c.LIBRE and c.pulsos[0].resultado == "completo"


def test_motor_se_apaga_durante_el_pulso():
    c = listo()
    c.iniciar_serie(c.emitir_confirmacion(PLAN, T0), T0)
    c.procesar(EXITO, T0 + 0.1)
    assert c.procesar(trama(T0 + 1.5, motor="OFF", ssr="F1(LEVE)"), T0 + 1.5) == ["0"]
    c.procesar(APAGADO, T0 + 1.6)
    assert c.estado == c.LIBRE and "motor en OFF" in c.pulsos[0].resultado


def test_paro_en_cada_estado():
    c = ControlInyeccion()
    assert c.paro(T0) == ["0"]                                                 # aun sin conexión
    c = listo()
    c.iniciar_serie(c.emitir_confirmacion(PLAN, T0), T0)
    assert c.paro(T0 + 0.05) == ["0"]                                          # esperando al firmware
    c = listo()
    c.iniciar_serie(c.emitir_confirmacion(PLAN, T0), T0)
    c.procesar(EXITO, T0 + 0.1)
    assert c.paro(T0 + 1) == ["0"]
    c.procesar(APAGADO, T0 + 1.1)
    assert c.estado == c.LIBRE and c.pulsos[0].resultado == "PARO manual"
    assert c.tic(T0 + 30) == []                                                # no sigue la serie
    c = listo()
    c.iniciar_serie(c.emitir_confirmacion(PLAN, T0), T0)
    c.procesar(EXITO, T0 + 0.1)
    c.tic(T0 + 5.1)
    c.procesar(APAGADO, T0 + 5.2)
    assert c.estado == c.PAUSA
    assert c.paro(T0 + 6) == ["0"] and c.estado == c.LIBRE
    c.procesar(trama(T0 + 21), T0 + 21)
    assert c.tic(T0 + 21) == []


def test_conexion_perdida_y_corte_del_firmware():
    c = listo()
    c.iniciar_serie(c.emitir_confirmacion(PLAN, T0), T0)
    c.procesar(EXITO, T0 + 0.1)
    c.conexion(False, T0 + 2)
    assert c.estado == c.LIBRE and "conexión perdida" in c.pulsos[0].resultado
    c.conexion(True, T0 + 4)
    c.procesar(trama(T0 + 4), T0 + 4)
    assert c.tic(T0 + 30) == []                                                # no reanuda sola
    assert "enfriamiento" in c.bloqueo(T0 + 4, "INTER")                         # cuenta desde la pérdida

    c = listo()
    c.iniciar_serie(c.emitir_confirmacion(PlanSerie("SEVERA", 11, 3, 20), T0), T0)
    c.procesar(EXITO, T0 + 0.1)
    c.procesar(FORZADO, T0 + 10)                                               # protección del firmware
    assert c.estado == c.LIBRE and c.pulsos[0].resultado == "cortado por el firmware (protección)"
    assert c.pulsos[0].forzado is True and c.pulsos[0].t_on_ms == 12001


def test_cerrar_envia_cero():
    with tempfile.TemporaryDirectory() as d:
        ruta = os.path.join(d, "p.csv")
        c = listo(ruta)
        c.iniciar_serie(c.emitir_confirmacion(PLAN, T0), T0)
        c.procesar(EXITO, T0 + 0.1)
        assert c.cerrar(T0 + 1) == ["0"]
        with open(ruta, encoding="utf-8") as f:
            filas = list(csv.DictReader(f))
        assert len(filas) == 1 and filas[0]["resultado"] == "app cerrada durante el pulso"


def test_aviso_de_arranque():
    """Aviso (no bloqueo) los primeros ~5 min tras encender el motor (falsa alarma del 09-oct 15:01)."""
    c = ControlInyeccion()
    c.conexion(True, T0)
    c.procesar(trama(T0, motor="OFF"), T0)
    assert c.aviso_arranque(T0) is None                                          # apagado: nada que avisar
    c.procesar(trama(T0 + 2, motor="WARMUP"), T0 + 2)                            # arranca: cuenta desde aquí
    c.procesar(trama(T0 + 62, motor="ON"), T0 + 62)
    assert "hace 1.0 min" in c.aviso_arranque(T0 + 62)
    assert c.bloqueo(T0 + 62, "INTER") is None, "el aviso no debe bloquear"
    assert c.minutos_encendido(T0 + 62) == 1.0
    c.procesar(trama(T0 + 303), T0 + 303)
    assert c.aviso_arranque(T0 + 303) is None                                    # pasaron 5 min
    c.procesar(trama(T0 + 304, motor="OFF"), T0 + 304)
    c.procesar(trama(T0 + 310), T0 + 310)
    assert "hace 0.0 min" in c.aviso_arranque(T0 + 310)                          # se reinicia al reencender
    c2 = listo()                                                                 # ya encendido al abrir la app
    assert "ya estaba encendido" in c2.aviso_arranque(T0) and c2.minutos_encendido(T0) is None


def run():
    test_plan_y_comandos_permitidos()
    test_sin_confirmacion_humana_no_hay_uno()
    test_bloqueos()
    test_serie_completa_y_csv()
    test_rechazo_y_falta_de_respuesta()
    test_apagado_sin_confirmar()
    test_motor_se_apaga_durante_el_pulso()
    test_paro_en_cada_estado()
    test_conexion_perdida_y_corte_del_firmware()
    test_cerrar_envia_cero()
    test_aviso_de_arranque()
    print("✓ Bloqueos de inyección: 11/11 pruebas")


if __name__ == "__main__":
    run()
