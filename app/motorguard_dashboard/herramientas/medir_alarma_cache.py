"""
Medición de la consulta de alarma con el slot de alarma precalentado (como la usa la app).

Sin caché, Qwen3.5-4B tardó 169.9 s en la alarma (rag_eval/medicion_modelos.json). La app precalienta, al
arrancar, el prefijo de la consulta de alarma (sistema + fragmentos), así que al alarmar solo se procesan los
valores medidos y la pregunta. Aquí se mide eso: calentamiento, alarma, una pregunta libre de desarrollo (en el otro
slot, como si el usuario preguntara entre alarmas) y dos alarmas más. Criterio declarado: alarma en <= 90 s.

Contexto: solo tramas reales. Cada alarma usa la primera trama de un evento distinto (flanco de C) del log INTER del
09-oct (la primera es medir_modelos_rag.CTX_EJEMPLO). Repetir la misma trama no sirve: el prompt sería idéntico y se
reutilizaría casi completo.

    PYTHONPATH=. venv/bin/python -m motorguard_dashboard.herramientas.medir_alarma_cache [--modelo qwen3.5-4b]
"""

import argparse
import glob
import json
import os
import sys
import threading
import time

from motorguard_dashboard.herramientas.medir_modelos_rag import CTX_EJEMPLO, LIMITE_ALARMA_S
from motorguard_dashboard.rag import biblioteca, catalogo
from motorguard_dashboard.rag.asistente import (CONSULTA_ALARMA, MAX_TOKENS, Asistente, ContextoAlarma, _slot,
                                                analizar, construir_mensajes, pregunta_alarma)
from motorguard_dashboard.rag.servicio import MotorLocal
from motorguard_dashboard.sistema import rutas
from motorguard_dashboard.telemetry.parser import Trama, parsear_linea

LOG_INTER = os.path.expanduser("~/tesis_itf/validacion_vivo/vivo_INTER_75%_20261009_1513_serial.log")


def _leer(ruta):
    try:
        with open(ruta) as fh:
            return fh.read().strip()
    except OSError:
        return None


class EstadoCPU:
    """Muestrea cada segundo la frecuencia media de los núcleos, la temperatura del CPU (k10temp) y si hay
    corriente alterna. La velocidad de generación cambia con el estado térmico y de energía del equipo
    (13-oct: 4.5 t/s a las 03:48 y 2.9–4.7 t/s a las 11:16 con el mismo modelo)."""

    def __init__(self):
        self.temp = next((os.path.join(os.path.dirname(n), "temp1_input")
                          for n in glob.glob("/sys/class/hwmon/hwmon*/name") if _leer(n) == "k10temp"), None)
        self.freqs = glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq")
        self.ac = glob.glob("/sys/class/power_supply/A*/online")
        self._muestras, self._fin = [], threading.Event()

    def _muestrear(self):
        while not self._fin.wait(1.0):
            f = [int(v) for v in map(_leer, self.freqs) if v]
            t = _leer(self.temp) if self.temp else None
            self._muestras.append((sum(f) / len(f) / 1000 if f else None, int(t) / 1000 if t else None))

    def __enter__(self):
        self._muestras, self._fin = [], threading.Event()
        self._hilo = threading.Thread(target=self._muestrear, daemon=True)
        self._hilo.start()
        return self

    def __exit__(self, *a):
        self._fin.set()
        self._hilo.join()

    def resumen(self) -> dict:
        mhz = [m for m, _ in self._muestras if m is not None]
        tc = [t for _, t in self._muestras if t is not None]
        ac = _leer(self.ac[0]) if self.ac else None
        return {"cpu_mhz_media": round(sum(mhz) / len(mhz)) if mhz else None,
                "temp_c_max": max(tc) if tc else None, "corriente_alterna": None if ac is None else ac == "1"}


def confirmaciones(ruta: str, n: int):
    """Contexto de la primera trama de cada alarma confirmada (flanco 0 -> 1 de C) del log, con 0 s de alarma."""
    salida, antes = [], False
    for linea in open(ruta, errors="replace"):
        t = parsear_linea(linea)
        if not isinstance(t, Trama) or t.dir is None:
            continue
        if t.dir.enclavada and not antes:
            salida.append((t.t, ContextoAlarma(t.dir.nombre_sev, t.dir.ml, t.i1, t.ia, t.ib, t.ic, 0.0, t.decision)))
            if len(salida) == n:
                break
        antes = t.dir.enclavada
    return salida


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--modelo", choices=[r.clave for r in catalogo.MODELOS_LLM], default=catalogo.MODELO_LLM.clave)
    ap.add_argument("--alarmas", type=int, default=3)
    ap.add_argument("--salida", default=os.path.expanduser(
        f"~/tesis_itf/rag_eval/medicion_alarma_cache_{time.strftime('%Y%m%d_%H%M')}.json"))
    a = ap.parse_args(argv)
    rec = next(r for r in catalogo.MODELOS_LLM if r.clave == a.modelo)
    dev = json.load(open(os.path.expanduser("~/tesis_itf/rag_eval/desarrollo.json"), encoding="utf-8"))
    base, docs = rutas.dir_asistente(), rutas.dir_documentos()
    motor = MotorLocal(base, rec)
    motor.iniciar()
    pasos = []
    try:
        assert motor.esperar(300), "el motor no arrancó"
        ind = biblioteca.cargar_o_construir(base, docs)
        assert ind is not None, "no hay índice vigente"
        llm = motor.cliente_llm()
        asis = Asistente(ind, motor.cliente_emb(), llm)
        t0 = time.monotonic()
        prefijo = asis.precalentar_alarma()
        t_cal = time.monotonic() - t0
        print(f"calentamiento: {t_cal:.1f} s, prefijo {prefijo} tokens", flush=True)
        ctxs = confirmaciones(LOG_INTER, a.alarmas)
        assert ctxs[0][1] == CTX_EJEMPLO, "la primera confirmación del log debe ser CTX_EJEMPLO"
        for n, (marca, ctx) in enumerate(ctxs):
            if n == 1:
                t0 = time.monotonic()
                asis.responder(dev["con_fuente"][0])
                print(f"pregunta libre intermedia: {time.monotonic() - t0:.1f} s", flush=True)
            with EstadoCPU() as cpu:
                t0 = time.monotonic()
                fuentes, _ = asis.recuperar(CONSULTA_ALARMA, alarma=True)
                res = llm.chat(construir_mensajes(pregunta_alarma(ctx), fuentes, ctx), MAX_TOKENS,
                               extra=_slot(llm, True))
                total = time.monotonic() - t0
            af = [l for l in analizar(res.texto, len(fuentes)) if l.es_afirmacion]
            t = res.extra.get("timings", {})
            pasos.append({"alarma": n + 1, "trama": marca, "contexto": ctx.texto(), "t_total_s": round(total, 1),
                          "t_primer_token_s": res.t_primer_token and round(res.t_primer_token, 1),
                          "tokens_reutilizados": t.get("cache_n"), "tokens_procesados": t.get("prompt_n"),
                          "tokens_respuesta": t.get("predicted_n"),
                          "tokens_por_s_generacion": t.get("predicted_per_second") and round(t["predicted_per_second"], 2),
                          **cpu.resumen(),
                          "fraccion_citada": round(sum(1 for l in af if l.citas and not l.invalidas) / len(af), 3)
                          if af else None,
                          "fuentes": [f"{f.fragmento.doc} p{f.fragmento.pag}" for f in fuentes],
                          "respuesta": res.texto})
            print(f"alarma {n + 1}: {total:.1f} s (primer token {res.t_primer_token:.1f} s; "
                  f"{t.get('cache_n')} tokens reutilizados, {t.get('prompt_n')} procesados)", flush=True)
    finally:
        motor.detener()
    salida = {"fecha": time.strftime("%Y-%m-%d %H:%M"), "modelo": rec.titulo, "archivo": rec.archivo,
              "llama_cpp": catalogo.LLAMA_BUILD, "cpu": "AMD Ryzen 7 3700U, 4 hilos, nice 10",
              "criterio_alarma_max_s": LIMITE_ALARMA_S, "log": LOG_INTER,
              "calentamiento_s": round(t_cal, 1), "prefijo_tokens": prefijo, "alarmas": pasos,
              "cumple_todas": all(p["t_total_s"] <= LIMITE_ALARMA_S for p in pasos)}
    os.makedirs(os.path.dirname(a.salida), exist_ok=True)
    with open(a.salida, "w", encoding="utf-8") as fh:
        json.dump(salida, fh, ensure_ascii=False, indent=1)
    print(f"-> {a.salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
