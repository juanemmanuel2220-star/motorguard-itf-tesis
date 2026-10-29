"""
Evaluación del asistente (etapa 4): corre las preguntas de rag_eval/preguntas.json con el modelo local
(y, si se pide, con uno externo como comparación) y guarda todo para la tesis.

Métricas automáticas:
- recall@5: la página esperada (o una aceptable) está entre los fragmentos recuperados;
- cita de la página esperada: alguna cita válida de la respuesta apunta a esa página;
- abstención en las preguntas sin fuente: total (no se llamó al LLM, o todas las líneas dicen que no hay fuente) o
  parcial (algunas líneas). Es una regla de texto que solo orienta; la calificación a mano es la que vale.
Calificación a mano (hoja CSV): respuesta correcta, cita correcta (la página citada contiene lo afirmado) y
afirmaciones inventadas. Con --resumen se juntan las hojas calificadas en rag_eval/resultados.md.

    PYTHONPATH=. venv/bin/python -m motorguard_dashboard.herramientas.evaluar_rag [--preguntas ARCHIVO]
        [--modelo qwen3.5-4b] [--externo URL MODELO]      (clave: llavero o MOTORGUARD_API_KEY)
    PYTHONPATH=. venv/bin/python -m motorguard_dashboard.herramientas.evaluar_rag --resumen
"""

import argparse
import csv
import glob
import json
import os
import re
import sys
import time

from motorguard_dashboard.rag import biblioteca, catalogo
from motorguard_dashboard.rag.asistente import Asistente
from motorguard_dashboard.rag.proveedores import ClienteOpenAI
from motorguard_dashboard.rag.servicio import MotorLocal
from motorguard_dashboard.sistema import claves, rutas

DIR_EVAL = os.path.expanduser("~/tesis_itf/rag_eval")
# Línea que dice que los documentos no responden (la calificación a mano es la que vale: esto solo orienta)
NO_CUBREN = re.compile(r"no (cubren|encontr|tengo|hay|especific|mencion|incluy|contien|proporcion|indic|dan?|define)\w*"
                       r"\b.*(fuente|informaci|documento|fragmento|dato|valor)|(documento|fragmento)s?( disponibles)? no "
                       r"(cubren|especific|mencion|incluy|contien|proporcion|indic|define)|^\W*no se (mide|indica)", re.I)


def abstencion(texto: str) -> str:
    """'total' si todas las líneas dicen que no hay fuente, 'parcial' si alguna, '' si ninguna."""
    lineas = [l for l in texto.splitlines() if l.strip()]
    n = sum(1 for l in lineas if NO_CUBREN.search(l))
    return "total" if lineas and n == len(lineas) else ("parcial" if n else "")
COLUMNAS_MANO = ["correcta (1/0)", "cita_correcta (1/0)", "inventada (1/0)", "notas"]


def _pag(f):
    return f.fragmento.doc, f.fragmento.pag


def evaluar(asis: Asistente, preguntas: list, etiqueta: str) -> dict:
    filas = []
    for q in preguntas:
        r = asis.responder(q["pregunta"])
        esperadas = set()
        if not q.get("sin_fuente"):
            esperadas = {(q["doc"], q["pagina"])} | {tuple(x) for x in q.get("paginas_aceptables", [])}
        recuperadas = [_pag(f) for f in r.fuentes]
        citadas = sorted({_pag(r.fuentes[n - 1]) for l in r.lineas for n in l.citas})
        tipo = "total" if r.abstencion else abstencion(r.texto)
        abstuvo = tipo == "total"
        filas.append({
            "id": q["id"], "pregunta": q["pregunta"], "sin_fuente": bool(q.get("sin_fuente")),
            "respuesta_esperada": q["respuesta"], "esperadas": sorted(esperadas),
            "recall5": (bool(esperadas & set(recuperadas)) if esperadas else None),
            "cita_pagina_esperada": (bool(esperadas & set(citadas)) if esperadas else None),
            "abstencion": abstuvo, "abstencion_parcial": tipo == "parcial", "abstencion_sin_llm": r.abstencion, "max_coseno": round(r.max_coseno, 4),
            "recuperadas": recuperadas, "citadas": citadas, "fraccion_citada": r.fraccion_citada,
            "citas_inexistentes": sum(len(l.invalidas) for l in r.lineas), "modelo": r.modelo,
            "aviso": r.aviso, "error": r.error, "t_total_s": round(r.t_total, 1),
            "t_primer_token_s": r.t_primer_token and round(r.t_primer_token, 1),
            "respuesta": r.texto,
            "fragmentos": [{"doc": f.fragmento.doc, "pag": f.fragmento.pag, "texto": f.fragmento.texto}
                           for f in r.fuentes]})
        print(f"  [{q['id']:2d}] {r.t_total:5.0f} s  recall5={filas[-1]['recall5']}  "
              f"abst={abstuvo}  {q['pregunta'][:55]}", flush=True)
    con = [f for f in filas if not f["sin_fuente"]]
    sin = [f for f in filas if f["sin_fuente"]]
    auto = {
        "n_con_fuente": len(con), "n_sin_fuente": len(sin),
        "recall5": sum(f["recall5"] for f in con), "cita_pagina_esperada": sum(f["cita_pagina_esperada"] for f in con),
        "abstencion_correcta_sin_fuente": sum(f["abstencion"] for f in sin),
        "abstencion_indebida_con_fuente": sum(f["abstencion"] for f in con),
        "abstencion_parcial_sin_fuente": sum(f["abstencion_parcial"] for f in sin),
        "t_mediana_s": sorted(f["t_total_s"] for f in filas)[len(filas) // 2] if filas else None,
    }
    return {"etiqueta": etiqueta, "fecha": time.strftime("%Y-%m-%d %H:%M"), "automaticas": auto, "filas": filas}


def guardar(res: dict, nombre: str, carpeta: str = DIR_EVAL):
    os.makedirs(carpeta, exist_ok=True)
    ruta = os.path.join(carpeta, f"respuestas_{nombre}.json")
    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    hoja = os.path.join(carpeta, f"calificacion_{nombre}.csv")
    with open(hoja, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "sin_fuente", "pregunta", "respuesta_esperada", "pagina_esperada", "respuesta_del_modelo",
                    "paginas_citadas"] + COLUMNAS_MANO)
        for f in res["filas"]:
            w.writerow([f["id"], int(f["sin_fuente"]), f["pregunta"], f["respuesta_esperada"],
                        "; ".join(f"{d} p{p}" for d, p in f["esperadas"]), f["respuesta"],
                        "; ".join(f"{d} p{p}" for d, p in f["citadas"])] + [""] * len(COLUMNAS_MANO))
    print(f"-> {ruta}\n-> {hoja} (calificar a mano)")


def resumen(carpeta: str = DIR_EVAL):
    filas_md = ["# Evaluación del asistente RAG", "",
                f"Generado el {time.strftime('%Y-%m-%d %H:%M')} con `herramientas/evaluar_rag.py --resumen` a partir de "
                "`respuestas_*.json` (métricas automáticas) y `calificacion_*.csv` (calificación a mano).", ""]
    for ruta in sorted(glob.glob(os.path.join(carpeta, "respuestas_*.json"))):
        res = json.load(open(ruta, encoding="utf-8"))
        a = res["automaticas"]
        nombre = os.path.basename(ruta)[len("respuestas_"):-5]
        filas_md += [f"## {res['etiqueta']} ({res['fecha']})", "",
                     f"- Recall@5 (página esperada entre los fragmentos recuperados): {a['recall5']}/{a['n_con_fuente']}",
                     f"- La respuesta cita la página esperada: {a['cita_pagina_esperada']}/{a['n_con_fuente']}",
                     f"- Abstención correcta en preguntas sin fuente: {a['abstencion_correcta_sin_fuente']}/{a['n_sin_fuente']}",
                     f"- Abstención indebida en preguntas con fuente: {a['abstencion_indebida_con_fuente']}/{a['n_con_fuente']}",
                     f"- Abstención parcial en preguntas sin fuente (alguna línea dice que no hay fuente, otras "
                     f"responden): {a.get('abstencion_parcial_sin_fuente', '—')}/{a['n_sin_fuente']}",
                     f"- Tiempo mediano por respuesta: {a['t_mediana_s']} s", ""]
        hoja = os.path.join(carpeta, f"calificacion_{nombre}.csv")
        if os.path.exists(hoja):
            filas = list(csv.DictReader(open(hoja, encoding="utf-8")))
            for col in COLUMNAS_MANO[:3]:
                vals = [f[col].strip() for f in filas if f[col].strip() in ("0", "1")]
                if vals:
                    filas_md.append(f"- {col.split(' ')[0]} (a mano): {sum(v == '1' for v in vals)}/{len(vals)}")
            filas_md.append(f"- Fuente: `{os.path.basename(hoja)}`")
        filas_md.append("")
    with open(os.path.join(carpeta, "resultados.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(filas_md))
    print("\n".join(filas_md))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--preguntas", default=os.path.join(DIR_EVAL, "preguntas.json"))
    ap.add_argument("--modelo", choices=[r.clave for r in catalogo.MODELOS_LLM], default=catalogo.MODELO_LLM.clave)
    ap.add_argument("--externo", nargs=2, metavar=("URL", "MODELO"))
    ap.add_argument("--protocolo", choices=["openai", "anthropic"],
                    help="API del proveedor externo (por omisión, según la URL: anthropic.com -> anthropic)")
    ap.add_argument("--resumen", action="store_true")
    ap.add_argument("--dir", default=DIR_EVAL, help="carpeta de salida (p. ej. rag_eval/preliminar)")
    a = ap.parse_args(argv)
    if a.resumen:
        resumen(a.dir)
        return 0
    preguntas = json.load(open(a.preguntas, encoding="utf-8"))["preguntas"]
    rec = next(r for r in catalogo.MODELOS_LLM if r.clave == a.modelo)
    base, docs = rutas.dir_asistente(), rutas.dir_documentos()
    motor = MotorLocal(base, rec)
    motor.iniciar()
    try:
        assert motor.esperar(300), "el motor local no arrancó"
        ind = biblioteca.cargar_o_construir(base, docs)
        assert ind is not None, "no hay índice vigente"
        local = motor.cliente_llm()
        sello = time.strftime("%Y%m%d_%H%M")
        if a.externo:
            url, modelo = a.externo
            clave = os.environ.get("MOTORGUARD_API_KEY") or claves.leer(url)
            llm = ClienteOpenAI(url, modelo, clave=clave, timeout=120, nombre=f"{modelo} (externo)",
                                protocolo=a.protocolo)
            res = evaluar(Asistente(ind, motor.cliente_emb(), llm), preguntas, f"{modelo} (externo)")
            guardar(res, f"externo_{re.sub(r'[^A-Za-z0-9.-]+', '_', modelo)}_{sello}", a.dir)
        else:
            res = evaluar(Asistente(ind, motor.cliente_emb(), local), preguntas, f"{rec.titulo} (local)")
            guardar(res, f"local_{rec.clave}_{sello}", a.dir)
    finally:
        motor.detener()
    return 0


if __name__ == "__main__":
    sys.exit(main())
