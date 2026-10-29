"""
Prepara el asistente desde la terminal (lo mismo que el botón "Preparar asistente" de la app):
descarga y verifica el runtime de llama.cpp y los modelos Qwen del catálogo y, con --indexar, construye
el índice de los documentos (los que falten se informan; no se descargan aquí).

    PYTHONPATH=. venv/bin/python -m motorguard_dashboard.herramientas.preparar_asistente [--respaldo]
        [--indexar] [--docs CARPETA]
"""

import argparse
import os
import sys
import time

from motorguard_dashboard.rag import catalogo
from motorguard_dashboard.rag.descargas import descargar, extraer_runtime
from motorguard_dashboard.sistema import rutas


def _barra(nombre):
    t0 = [time.monotonic(), 0.0]

    def f(n, total):
        if time.monotonic() - t0[1] < 5 and n != total:
            return
        t0[1] = time.monotonic()
        pct = f"{100 * n / total:5.1f} %" if total else ""
        vel = n / max(1e-3, time.monotonic() - t0[0]) / 1e6
        print(f"  {nombre}: {n / 1e6:8.1f} MB {pct}  ({vel:.1f} MB/s)", flush=True)
    return f


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--respaldo", action="store_true", help="descargar también Qwen3.5-2B")
    ap.add_argument("--indexar", action="store_true", help="construir el índice de los documentos")
    ap.add_argument("--docs", help="carpeta de documentos (por defecto, la de los ajustes de la app)")
    a = ap.parse_args(argv)
    base = rutas.dir_asistente()
    modelos = os.path.join(base, "modelos")
    print(f"Carpeta del asistente: {base}")
    tar = os.path.join(base, "descargas")
    descargar(catalogo.RUNTIME, tar, _barra("llama.cpp"))
    srv = extraer_runtime(os.path.join(tar, catalogo.RUNTIME.archivo), os.path.join(base, "llama"))
    print(f"  runtime: {srv}")
    recs = [catalogo.MODELO_EMB, catalogo.MODELO_LLM] + ([catalogo.MODELO_LLM_RESPALDO] if a.respaldo else [])
    for r in recs:
        descargar(r, modelos, _barra(r.titulo))
        print(f"  ✓ {r.archivo} (SHA-256 verificado)")
    if a.indexar:
        indexar(base, a.docs or rutas.dir_documentos())
    return 0


def indexar(base: str, docs: str):
    from motorguard_dashboard.rag import biblioteca
    from motorguard_dashboard.rag.servicio import MotorLocal
    print(f"Documentos: {docs}")
    for e in biblioteca.estado_documentos(docs):
        print(f"  {e.estado:8s} {e.rec.titulo}")
    motor = MotorLocal(base)
    motor.iniciar(con_llm=False)
    try:
        if not motor.esperar(120):
            raise SystemExit("el servidor de embeddings no arrancó (ver asistente/logs/llama_embeddings.log)")
        t0 = time.monotonic()
        marca = [0.0]

        def prog(etapa, n, total):
            if time.monotonic() - marca[0] > 10 or n == total:
                marca[0] = time.monotonic()
                print(f"  {etapa}: {n}/{total}  ({time.monotonic() - t0:.0f} s)", flush=True)
        ind = biblioteca.cargar_o_construir(base, docs, motor.cliente_emb().embeddings, prog)
        print(f"  índice: {len(ind)} fragmentos en {time.monotonic() - t0:.0f} s -> {biblioteca.dir_indice(base)}")
    finally:
        motor.detener()


if __name__ == "__main__":
    sys.exit(main())
