"""
Medición del modelo local del asistente (sección F del plan; criterio declarado antes de medir):
  - consulta de alarma respondida en <= 90 s;
  - >= 90 % de las líneas con cita válida.
Se mide Qwen3.5-4B y, solo si no cumple, Qwen3.5-2B (--modelo para forzar uno).

Usa las preguntas de DESARROLLO (rag_eval/desarrollo.json), no las de la evaluación. Además informa el
coseno máximo de cada pregunta (con y sin fuente) para fijar el umbral de abstención.

    PYTHONPATH=. venv/bin/python -m motorguard_dashboard.herramientas.medir_modelos_rag [--modelo qwen3.5-2b]
"""

import argparse
import json
import os
import sys
import time

from motorguard_dashboard.rag import biblioteca, catalogo
from motorguard_dashboard.rag.asistente import Asistente, ContextoAlarma, pregunta_alarma
from motorguard_dashboard.rag.indice import INSTRUCCION_CONSULTA
from motorguard_dashboard.rag.servicio import MotorLocal
from motorguard_dashboard.sistema import rutas

LIMITE_ALARMA_S = 90.0
MIN_CITADAS = 0.90
# Contexto de alarma de ejemplo: primera trama con la alarma confirmada del log real
# validacion_vivo/vivo_INTER_75%_20261009_1513_serial.log (hora 1791580464.971); tiempo con alarma = 0 s
CTX_EJEMPLO = ContextoAlarma("INTER", 2.251, 7.9102, 5.60, 5.82, 5.42, 0.0, "INTER")


def rss_mb(pid: int) -> float:
    try:
        for linea in open(f"/proc/{pid}/status"):
            if linea.startswith("VmRSS:"):
                return int(linea.split()[1]) / 1024
    except OSError:
        pass
    return float("nan")


def medir(rec: catalogo.Recurso, base: str, docs: str, dev: dict) -> dict:
    motor = MotorLocal(base, rec)
    motor.iniciar()
    try:
        t0 = time.monotonic()
        assert motor.esperar(300), "el motor no arrancó"
        t_carga = time.monotonic() - t0
        ind = biblioteca.cargar_o_construir(base, docs)
        assert ind is not None, "no hay índice vigente (preparar_asistente --indexar)"
        emb = motor.cliente_emb()
        cosenos = {"con_fuente": [], "sin_fuente": []}
        for clase in cosenos:
            for q in dev[clase]:
                v = emb.embeddings([INSTRUCCION_CONSULTA + q])[0]
                cosenos[clase].append({"pregunta": q, "max_coseno": round(ind.max_coseno(v), 4)})
        a = Asistente(ind, emb, motor.cliente_llm(), umbral=0.0)        # sin abstención: se mide el LLM
        filas = []
        casos = [(pregunta_alarma(CTX_EJEMPLO), CTX_EJEMPLO, True)] + [(q, None, False) for q in dev["con_fuente"]]
        for q, ctx, alarma in casos:
            r = a.responder(q, ctx, alarma)
            filas.append({"pregunta": q, "alarma": alarma, "t_busqueda_s": round(r.t_busqueda, 2),
                          "t_primer_token_s": r.t_primer_token and round(r.t_primer_token, 1),
                          "t_total_s": round(r.t_total, 1), "tokens_prompt": r.tokens_prompt,
                          "tokens_respuesta": r.tokens_respuesta, "fraccion_citada": r.fraccion_citada,
                          "citas_inexistentes": sum(len(l.invalidas) for l in r.lineas),
                          "fuentes": [f"{f.fragmento.doc} p{f.fragmento.pag}" for f in r.fuentes],
                          "respuesta": r.texto})
            print(f"  {r.t_total:6.1f} s  citadas {r.fraccion_citada}  {q[:60]}", flush=True)
        ram = {"llm_mb": round(rss_mb(motor.llm.proc.pid)), "emb_mb": round(rss_mb(motor.emb.proc.pid))}
    finally:
        motor.detener()
    alarma = filas[0]
    fr = [f["fraccion_citada"] for f in filas if f["fraccion_citada"] is not None]
    citadas = sum(fr) / len(fr) if fr else 0.0
    return {"modelo": rec.titulo, "archivo": rec.archivo, "sha256": rec.sha256, "t_carga_s": round(t_carga, 1),
            "ram": ram, "cosenos": cosenos, "casos": filas,
            "alarma_t_total_s": alarma["t_total_s"], "fraccion_citada_media": round(citadas, 3),
            "cumple": alarma["t_total_s"] <= LIMITE_ALARMA_S and citadas >= MIN_CITADAS}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--modelo", choices=[r.clave for r in catalogo.MODELOS_LLM])
    ap.add_argument("--docs", default=None)
    ap.add_argument("--salida", default=os.path.expanduser("~/tesis_itf/rag_eval/medicion_modelos.json"))
    a = ap.parse_args(argv)
    dev = json.load(open(os.path.expanduser("~/tesis_itf/rag_eval/desarrollo.json"), encoding="utf-8"))
    base, docs = rutas.dir_asistente(), a.docs or rutas.dir_documentos()
    orden = [r for r in catalogo.MODELOS_LLM if a.modelo in (None, r.clave)]
    resultados = []
    for rec in orden:
        print(f"== {rec.titulo}", flush=True)
        res = medir(rec, base, docs, dev)
        resultados.append(res)
        print(f"  alarma: {res['alarma_t_total_s']} s · citadas {res['fraccion_citada_media']} · "
              f"RAM {res['ram']} · cumple={res['cumple']}", flush=True)
        if res["cumple"] and a.modelo is None:
            break                                   # el 2B solo se mide si el 4B no cumple
    salida = {"fecha": time.strftime("%Y-%m-%d %H:%M"), "criterio": {"alarma_max_s": LIMITE_ALARMA_S,
              "min_fraccion_citada": MIN_CITADAS}, "cpu": "AMD Ryzen 7 3700U, 4 hilos, nice 10",
              "llama_cpp": catalogo.LLAMA_BUILD, "resultados": resultados}
    os.makedirs(os.path.dirname(a.salida), exist_ok=True)
    with open(a.salida, "w", encoding="utf-8") as fh:
        json.dump(salida, fh, ensure_ascii=False, indent=1)
    print(f"-> {a.salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
