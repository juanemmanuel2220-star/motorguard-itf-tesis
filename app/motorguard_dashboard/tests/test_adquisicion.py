"""
Pruebas de la sección Adquisición (lógica pura, reloj simulado):
- pares SANO/FALLA (adquisicion/pares.py) con el control de inyección real: ningún '1' sin confirmación,
  enfriamiento, bloques de 10 pulsos, filtros de calidad, pausas por pulso interrumpido, reanudación;
- prueba larga sin falla (adquisicion/base_larga.py): exposición, eventos, escalones y '0' periódico;
- protección de las carpetas de la tesis;
- equivalencia con el script: cada fila de los CSV reales de ~/tesis_itf/dataset se reproduce con el
  formato de la app a partir de su _serial.log (solo lectura; se omite si los archivos no están).
Las tramas parten de líneas reales (test_telemetry_parser); las variaciones se marcan como DERIVADAS.
"""

import csv
import glob
import io
import json
import os
import tempfile

from motorguard_dashboard.adquisicion import formato
from motorguard_dashboard.adquisicion.base_larga import PruebaLarga
from motorguard_dashboard.adquisicion.pares import CapturaPares, ParametrosPares, validar_parametros
from motorguard_dashboard.inyeccion.control import (
    ControlInyeccion, MAX_PULSOS_SERIE, VIGENCIA_ARMADA_S, validar_plan,
)
from motorguard_dashboard.telemetry.parser import parsear_linea
from motorguard_dashboard.tests.test_telemetry_parser import (
    L_INTER, L_SANO, L_SSR_APAGADO, L_SSR_EXITO, L_SSR_RECHAZO_COOLDOWN,
)

T0 = 1_800_000_000.0
BLOQUE = 1.7
EXITO = parsear_linea(L_SSR_EXITO)
APAGADO = parsear_linea(L_SSR_APAGADO)
RECHAZO = parsear_linea(L_SSR_RECHAZO_COOLDOWN)


def linea(base=L_SANO, **cambios):
    """Trama a partir de una línea real; los cambios de texto (DERIVADOS) se aplican sobre la línea."""
    texto = base[15:]
    for viejo, nuevo in cambios.get("reemplazos", ()):
        assert viejo in texto, viejo
        texto = texto.replace(viejo, nuevo)
    return parsear_linea(texto)


SANA = linea()
FALLA = linea(L_INTER)                                            # SSR:F1(LEVE), DE2=2.30 %
FALLA_SALTO = linea(L_INTER, reemplazos=[("IC=5.42A", "IC=5.60A")])   # DERIVADA: salto de corriente en el pulso


def con_t(obj, t):
    import dataclasses
    return dataclasses.replace(obj, t=t)


class Banco:
    """Control + captura alimentados con un reloj simulado, como los conecta la interfaz."""

    def __init__(self, carpeta, **prm):
        self.t = T0
        self.c = ControlInyeccion()
        self.c.conexion(True, self.t)
        self.enviados = []
        self.dar(SANA)
        prm.setdefault("clase", 2)
        prm.setdefault("carga", "50%")
        self.cap = CapturaPares(self.c, ParametrosPares(**prm), carpeta, self.t, origen="prueba")

    def dar(self, obj, dt=0.0):
        self.t += dt
        o = con_t(obj, self.t)
        self.enviados += self.c.procesar(o, self.t)
        if getattr(self, "cap", None):
            self.enviados += self.cap.procesar(o, self.t)

    def tic(self, dt=0.0):
        self.t += dt
        self.enviados += self.c.tic(self.t)
        self.enviados += self.cap.tic(self.t)

    def confirmar(self):
        plan = self.cap.plan_bloque()
        assert validar_plan(plan) is None, validar_plan(plan)
        conf = self.c.emitir_confirmacion(plan, self.t)
        self.enviados += self.cap.armar(conf, self.t)

    def esperar_sano(self):
        """Tramas sanas cada 1.7 s hasta que la captura pide el pulso."""
        for _ in range(40):
            antes = len(self.enviados)
            self.dar(SANA, BLOQUE)
            self.tic()
            if self.enviados[antes:] == ["1"]:
                return True
        return False

    def pulso(self, tramas=(FALLA, FALLA, FALLA), confirmar_off=True):
        """Pulso confirmado por el firmware con tramas cada 1.7 s; el control lo apaga a la duración pedida."""
        self.dar(EXITO, 0.05)
        t_on = self.t
        for tr in tramas:
            self.dar(tr, BLOQUE)
            self.tic()
        while self.c.pulso_actual is not None and self.c.estado == self.c.ENCENDIDO:
            self.tic(0.1)
        assert self.enviados[-1] == "0"
        if confirmar_off:
            self.dar(APAGADO, 0.05)
        self.tic(0.1)
        return t_on

    def par(self, **kw):
        assert self.esperar_sano(), self.cap.mensaje
        return self.pulso(**kw)


def filas(ruta):
    with open(ruta, newline="") as fh:
        return list(csv.reader(fh))


def test_control_disparo_externo():
    """Serie armada: ningún '1' sin disparar(); disparar() exige la pausa y los bloqueos de siempre."""
    from motorguard_dashboard.inyeccion.control import PlanSerie
    c = ControlInyeccion()
    c.conexion(True, T0)
    c.procesar(con_t(SANA, T0), T0)
    assert c.disparar(T0) == [] and "armada" in c.mensaje
    plan = PlanSerie("INTER", 5.0, 2, 15.0, externo=True)
    assert c.iniciar_serie(c.emitir_confirmacion(plan, T0), T0) == [] and c.armada and c.restantes == 2
    assert c.tic(T0 + 30) == []                                   # el temporizador no dispara solo
    c.procesar(con_t(SANA, T0 + 30), T0 + 30)
    assert c.disparar(T0 + 30) == ["1"] and not c.armada
    c.procesar(con_t(EXITO, T0 + 30.1), T0 + 30.1)
    assert c.tic(T0 + 35.2) == ["0"]
    c.procesar(con_t(APAGADO, T0 + 35.3), T0 + 35.3)
    assert c.armada and c.restantes == 1
    c.procesar(con_t(SANA, T0 + 40), T0 + 40)
    assert c.disparar(T0 + 40) == [] and "pausa" in c.mensaje      # 15 s desde el apagado
    c.procesar(con_t(SANA, T0 + 51), T0 + 51)
    assert c.disparar(T0 + 51) == ["1"]
    # Armar durante el enfriamiento se permite; el disparo no
    c2 = ControlInyeccion()
    c2.conexion(True, T0)
    c2.procesar(con_t(SANA, T0), T0)
    c2.t_ultimo_apagado = T0 - 5
    assert c2.bloqueo(T0, "INTER") is not None
    c2.iniciar_serie(c2.emitir_confirmacion(plan, T0), T0)
    assert c2.armada and c2.disparar(T0) == [] and "pausa" in c2.mensaje
    c2.cancelar_armada()
    assert not c2.en_curso
    # Una serie normal (no externa) sigue igual: el primer '1' sale al confirmar
    c3 = ControlInyeccion()
    c3.conexion(True, T0)
    c3.procesar(con_t(SANA, T0), T0)
    assert c3.iniciar_serie(c3.emitir_confirmacion(PlanSerie("INTER", 5.0, 1, 15.0), T0), T0) == ["1"]


def test_parametros():
    ok = ParametrosPares(2, "50%")
    assert validar_parametros(ok) is None
    assert validar_parametros(ParametrosPares(3, "50%", cooldown=20.0)) is None
    assert "15" in validar_parametros(ParametrosPares(2, "50%", cooldown=8.0))      # el script permitía 8 s
    assert "20" in validar_parametros(ParametrosPares(3, "50%", cooldown=15.0))
    assert "t_min_on" in validar_parametros(ParametrosPares(2, "50%", duracion_pulso=4.0, t_min_on=3.0))
    assert validar_parametros(ParametrosPares(2, "50%", duracion_pulso=11.5)) is not None
    assert validar_parametros(ParametrosPares(2, "60%")) is not None
    assert validar_parametros(ParametrosPares(0, "50%")) is not None


def test_carpetas_protegidas():
    for ruta in ("~/tesis_itf/dataset", "~/tesis_itf/dataset/piloto", "~/tesis_itf/validacion_vivo",
                 "~/tesis_itf/prueba_larga/x"):
        assert formato.carpeta_protegida(ruta), ruta
        for crear in (lambda r: CapturaPares(ControlInyeccion(), ParametrosPares(2, "50%"), os.path.expanduser(r), T0),
                      lambda r: PruebaLarga(os.path.expanduser(r), T0)):
            try:
                crear(ruta)
                raise AssertionError(f"escribió en {ruta}")
            except ValueError as e:
                assert "tesis" in str(e)
    assert formato.carpeta_protegida("~/tesis_itf/app_datasets") is None
    assert formato.carpeta_protegida("~/tesis_itf/dataset_nuevo") is None


def test_par_completo_y_archivos():
    with tempfile.TemporaryDirectory() as d:
        b = Banco(d, pares=2, nota="prueba")
        # Sin confirmación no sale nada, aunque haya tramas sanas
        for _ in range(15):
            b.dar(SANA, BLOQUE)
            b.tic()
        assert b.enviados == [] and b.cap.estado == b.cap.ESPERA_CONFIRMACION
        b.confirmar()
        t_armado = b.t
        assert b.cap.estado == b.cap.ESPERA_SANO and b.enviados == []
        assert b.esperar_sano()
        # La trama SANO usada llegó >= cooldown después del inicio (t_off inicial = armado)
        assert b.t - t_armado >= 15.0
        t_on = b.pulso()
        assert b.cap.p == 1 and b.cap.estado == b.cap.ESPERA_SANO
        rows = filas(b.cap.ruta_csv)
        assert rows[0] == formato.COLS and len(rows) == 3
        sano, falla = (dict(zip(formato.COLS, r)) for r in rows[1:])
        assert (sano["clase"], sano["label"], falla["clase"], falla["label"]) == ("0", "SANO", "2", "INTER")
        assert sano["carga"] == "2" and sano["carga_label"] == "50%"
        assert (sano["n_muestra"], falla["n_muestra"]) == ("1", "2")
        assert sano["t_desde_on"] == "-1.0" and falla["t_desde_off"] == "-1.0"
        assert float(sano["t_desde_off"]) >= 15.0
        assert 3.0 <= float(falla["t_desde_on"]) < 7.0
        assert float(falla["delta_e2"]) == 2.3 and falla["de2_fw"] == "2.3"
        assert sano["I_rms"] == "5.26" and falla["I_rms"] == "5.42" and falla["r2_re"] == "0.05851"
        # Segundo par: la captura termina sola y cancela lo que quedara armado
        b.par()
        assert b.cap.estado == b.cap.TERMINADA and b.cap.p == 2 and not b.c.armada
        assert len(filas(b.cap.ruta_csv)) == 5
        meta = json.load(open(b.cap.ruta_meta))
        s = meta["sesiones"][-1]
        assert s["pares_total"] == 2 and s["descartes"] == 0 and s["parametros"]["cooldown"] == 15.0
        assert s["clase"] == "INTER" and s["nota"] == "prueba" and "previo" in s and s["bloques"] == 1
        assert os.path.getsize(b.cap.ruta_csv.replace(".csv", "_serial.log")) > 0
        assert filas(b.cap.ruta_descartes) == [["timestamp", "clase", "carga", "motivo", "detalle"]]
        assert set(b.enviados) <= {"0", "1"} and b.enviados.count("1") == 2
        assert t_on > t_armado


def test_filtros_de_calidad():
    with tempfile.TemporaryDirectory() as d:
        b = Banco(d, pares=5)
        b.confirmar()
        b.par(tramas=(FALLA,))                         # una sola trama completa en el pulso
        b.par(tramas=(FALLA, FALLA, FALLA_SALTO))      # salto de corriente dentro del pulso
        assert b.cap.p == 0 and b.cap.n_desc == 2
        motivos = [r[3] for r in filas(b.cap.ruta_descartes)[1:]]
        assert motivos == ["Pulso con menos de 2 tramas completas", "Salto dentro del pulso"]
        # Umbral de DE2 (solo si el usuario lo pide; por defecto 0)
        b2 = Banco(os.path.join(d, "u"), pares=5, umbral_e2=3.0)
        b2.confirmar()
        b2.par()
        assert b2.cap.p == 0 and filas(b2.cap.ruta_descartes)[1][3] == "Salto insuficiente"


def test_sano_inestable_y_reinicio_de_referencia():
    with tempfile.TemporaryDirectory() as d:
        b = Banco(d, pares=9)
        b.confirmar()
        for _ in range(3):
            b.par()
        assert b.cap.p == 3
        otra = linea(reemplazos=[("IA=5.40A", "IA=5.60A")])   # DERIVADA: cambio de carga en fase A
        b.tic(15.0)
        n = len(b.enviados)
        for _ in range(3):
            b.dar(otra, BLOQUE)
            b.tic()
        assert b.enviados[n:] == [] and b.cap.n_desc == 3
        b.dar(otra, BLOQUE)                                   # 4.º seguido: se reinicia la referencia
        b.dar(otra, BLOQUE)
        assert b.enviados[n:] == ["1"]


def test_bloques_de_10_con_nueva_confirmacion():
    with tempfile.TemporaryDirectory() as d:
        b = Banco(d, pares=12)
        b.confirmar()
        assert b.c.restantes == MAX_PULSOS_SERIE
        for _ in range(10):
            b.par()
        assert b.cap.p == 10 and b.cap.estado == b.cap.ESPERA_CONFIRMACION and not b.c.en_curso
        # Sin la nueva confirmación no hay pulso 11
        n = len(b.enviados)
        for _ in range(20):
            b.dar(SANA, BLOQUE)
            b.tic()
        assert "1" not in b.enviados[n:]
        assert b.cap.plan_bloque().n_pulsos == 2
        b.confirmar()
        b.par()
        b.par()
        assert b.cap.estado == b.cap.TERMINADA and b.cap.p == 12
        assert json.load(open(b.cap.ruta_meta))["sesiones"][-1]["bloques"] == 2


def test_pulso_interrumpido_pausa_la_captura():
    with tempfile.TemporaryDirectory() as d:
        b = Banco(d, pares=5)
        b.confirmar()
        assert b.esperar_sano()
        b.dar(EXITO, 0.05)
        b.dar(FALLA, BLOQUE)
        b.enviados += b.c.paro(b.t)                     # PARO de la barra superior
        assert b.enviados[-1] == "0"
        b.dar(APAGADO, 0.1)
        b.tic(0.1)
        assert b.cap.estado == b.cap.PAUSADA and b.cap.p == 0 and "PARO" in b.cap.mensaje
        assert len(filas(b.cap.ruta_csv)) == 1
        n = len(b.enviados)
        for _ in range(20):
            b.dar(SANA, BLOQUE)
            b.tic()
        assert "1" not in b.enviados[n:]
        # Reanudar exige confirmar otra vez y respeta el enfriamiento desde el último apagado
        b.confirmar()
        t_conf = b.t
        assert b.esperar_sano() and b.t >= b.c.t_ultimo_apagado + 15.0 and b.t > t_conf
        b.pulso()
        assert b.cap.p == 1
        # Rechazo del firmware: pausa con el motivo
        assert b.esperar_sano()
        b.dar(RECHAZO, 0.05)
        b.tic(0.1)
        assert b.cap.estado == b.cap.PAUSADA and "Cooldown" in b.cap.mensaje
        pausas = json.load(open(b.cap.ruta_meta))["sesiones"][-1]["pausas"]
        assert len(pausas) == 2


def test_serie_armada_caduca_y_conexion_perdida():
    with tempfile.TemporaryDirectory() as d:
        b = Banco(d, pares=5)
        b.confirmar()
        # Motor en WARMUP (DERIVADA): no hay SANO válido y la serie armada caduca
        warm = linea(reemplazos=[("Motor:ON", "Motor:WARMUP"), ("| SANO |", "| WARMUP |")])
        for _ in range(int(VIGENCIA_ARMADA_S / BLOQUE) + 2):
            b.dar(warm, BLOQUE)
            b.tic()
        assert b.cap.estado == b.cap.PAUSADA and not b.c.armada and "1" not in b.enviados
        b.confirmar()                                 # con el motor en WARMUP no se arma
        assert not b.c.armada and b.cap.estado == b.cap.PAUSADA and "WARMUP" in b.cap.mensaje
        b.dar(SANA, BLOQUE)
        b.confirmar()
        assert b.c.armada
        b.c.conexion(False, b.t)
        b.tic(0.1)
        assert b.cap.estado == b.cap.PAUSADA


def test_pausar_y_terminar_envian_cero_si_hay_pulso():
    with tempfile.TemporaryDirectory() as d:
        b = Banco(d, pares=5)
        b.confirmar()
        assert b.esperar_sano()
        b.dar(EXITO, 0.05)
        assert b.cap.pausar(b.t) == ["0"] and b.cap.estado == b.cap.PAUSADA
        b.dar(APAGADO, 0.1)
        b.tic()
        b.confirmar()
        assert b.cap.terminar(b.t) == [] and not b.c.armada and b.cap.estado == b.cap.TERMINADA
        assert b.cap.procesar(con_t(SANA, b.t + 50), b.t + 50) == []


def test_continuar_y_fila_huerfana():
    with tempfile.TemporaryDirectory() as d:
        b = Banco(d, pares=2)
        b.confirmar()
        b.par()
        b.cap.terminar(b.t)
        with open(b.cap.ruta_csv, "a", newline="") as fh:          # par a medias (corte de luz)
            csv.writer(fh).writerow(filas(b.cap.ruta_csv)[1])
        b2 = Banco(d, pares=2, continuar=True)
        assert b2.cap.ruta_csv == b.cap.ruta_csv and b2.cap.p == 1
        assert any("huérfana" in x for x in b2.cap.consola)
        b2.confirmar()
        assert b2.cap.plan_bloque().n_pulsos == 1
        b2.par()
        assert b2.cap.estado == b2.cap.TERMINADA and len(filas(b.cap.ruta_csv)) == 5
        sesiones = json.load(open(b.cap.ruta_meta))["sesiones"]
        assert [s["pares_previos"] for s in sesiones] == [0, 1]
        # Otra clase: no reanuda el archivo de INTER
        b3 = Banco(d, pares=1, clase=1, continuar=True)
        assert "LEVE" in os.path.basename(b3.cap.ruta_csv)
        b3.cap.terminar(b3.t)


def test_prueba_larga():
    with tempfile.TemporaryDirectory() as d:
        pl = PruebaLarga(d, T0, minutos=2.0, max_horas=1.0, nota="banco")
        t = T0
        assert pl.tic(t) == ["0"] and pl.tic(t + 1) == []
        enviados = []
        alarma = linea(L_INTER, reemplazos=[("SSR:F1(LEVE)", "SSR:OFF")])   # DERIVADA: alarma sin pulso
        escalon = linea(reemplazos=[("I1=7.7520", "I1=8.1000")])            # DERIVADA: +4.5 % de |I1|
        secuencia = [SANA] * 20 + [escalon] * 3 + [alarma] * 4 + [escalon] * 10 + [SANA] * 40
        for tr in secuencia:
            t += BLOQUE
            enviados += pl.procesar(con_t(tr, t), t) + pl.tic(t)
            if not pl.activa:
                break
        assert not pl.activa and "exposición objetivo" in pl.motivo_fin
        assert enviados.count("0") >= 2 and "1" not in enviados
        r = json.load(open(pl.base + "_resumen.json"))
        assert r["eventos_falsa_alarma"] == 1 and r["eventos"][0]["sev_max"] == "INTER"
        assert r["eventos"][0]["tras_escalon"] is True and r["alarmas_tras_escalon"] == 1
        assert r["escalones_de_carga"] >= 2 and r["escalones_con_alarma_30s"] >= 1
        assert r["exposicion_min"] >= 2.0 and r["firmware"] == "299a943" and r["nota"] == "banco"
        assert r["tasa_sup95_por_hora"] > r["tasa_por_hora"]
        assert len(filas(pl.base + "_tramas.csv")) == 1 + len([1 for _ in open(pl.base + "_serial.log")])


def test_equivalencia_con_csv_reales():
    """Cada fila de los CSV reales del dataset se obtiene con el formato de la app desde su _serial.log."""
    rutas = sorted(f for f in glob.glob(os.path.expanduser("~/tesis_itf/dataset/cap_ENTRELAZADA_*.csv"))
                   if not f.endswith("_descartes.csv") and os.path.exists(f.replace(".csv", "_serial.log")))
    if not rutas:
        print("    (se omite: no está ~/tesis_itf/dataset)")
        return
    fijas = {"clase", "label", "carga", "carga_label", "n_muestra", "timestamp", "t_desde_on", "t_desde_off",
             "delta_e2"}
    idx = [i for i, c in enumerate(formato.COLS) if c not in fijas]

    def texto(valores):
        buf = io.StringIO()
        csv.writer(buf).writerow(valores)
        return next(csv.reader(io.StringIO(buf.getvalue())))

    total = 0
    for ruta in rutas:
        rows = filas(ruta)
        if rows[0] != formato.COLS:
            continue                                  # esquema anterior (v4.0)
        claves = set()
        for lin in open(ruta.replace(".csv", "_serial.log"), errors="ignore"):
            partes = lin.rstrip("\n").split(" ", 1)
            if len(partes) == 2 and "[MCSA]" in partes[1]:
                dd = formato.parse_line(partes[1], float(partes[0]))
                if dd:
                    fila = texto(formato.fila_dataset(dd, 0, 0, 0, 0.0, 0.0, 0.0, ""))
                    claves.add(tuple(fila[i] for i in idx))
        for r in rows[1:]:
            assert tuple(r[i] for i in idx) in claves, f"{os.path.basename(ruta)}: fila {r[4]} sin trama equivalente"
            total += 1
    assert total > 0
    print(f"    {total} filas reales de {len(rutas)} archivos reproducidas con el formato de la app")


def run():
    for nombre, f in sorted(globals().items()):
        if nombre.startswith("test_") and callable(f):
            f()
            print(f"  ✅ adquisición: {nombre}")


if __name__ == "__main__":
    run()
