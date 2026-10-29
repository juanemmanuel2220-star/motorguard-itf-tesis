"""
Pruebas del asistente RAG (rag/) sin red ni modelos:
- ingesta: fragmentos que no cruzan de página, secciones del extracto de la tesis, idioma, y con los PDF
  reales (si están en ~/tesis_itf/rag_docs) que del manual ABB solo entre la sección en español;
- índice: BM25 con glosario ES→EN, RRF, máximo por página, guardar/cargar y vigencia;
- asistente, con un servidor falso compatible con OpenAI: abstención sin llamar al LLM, citas válidas e
  inexistentes, prompt con solo los valores de la trama, respaldo local cuando el externo falla y que la
  clave nunca aparece en avisos ni errores;
- aislamiento: rag/ no importa el puerto serie ni el control de inyección;
- servicio: arranque, espera y paro de un llama-server falso;
- descargas: SHA-256 correcto, incorrecto y reanudación con Range.
"""

import ast
import glob
import hashlib
import json
import os
import stat
import sys
import tempfile
import threading
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

from motorguard_dashboard.rag import asistente as mod_asis
from motorguard_dashboard.rag import catalogo
from motorguard_dashboard.rag.asistente import Asistente, ContextoAlarma, analizar, construir_mensajes
from motorguard_dashboard.rag.indice import Indice, ampliar_consulta, tokens
from motorguard_dashboard.rag.ingesta import Fragmento, Pagina, fragmentar, idioma, paginas_documento, paginas_md
from motorguard_dashboard.rag.proveedores import ClienteOpenAI, ErrorProveedor

DIR_RAG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rag")
DOCS = os.path.expanduser("~/tesis_itf/rag_docs")
CLAVE = "sk-prueba-SECRETA-123"


def vec_hash(texto: str, dim: int = 256) -> np.ndarray:
    """Embedding falso: bolsa de palabras con hash (textos con palabras comunes quedan cerca). Las consultas
    ("Instruct: ... Query: ...") se amplían con el glosario ES→EN, como haría un modelo multilingüe."""
    v = np.zeros(dim, np.float32)
    palabras = ampliar_consulta(texto.split("Query: ", 1)[1]) if texto.startswith("Instruct:") else tokens(texto)
    for w in palabras:
        v[zlib.crc32(w.encode()) % dim] += 1.0
    return v


class ServidorFalso:
    """Servidor compatible con OpenAI: /embeddings, /chat/completions (SSE) y /models; puede fallar a propósito."""

    def __init__(self, respuesta="- Mida la resistencia de aislamiento antes de arrancar [1].\n- Seque el devanado [2]."):
        self.respuesta = respuesta
        self.fallar = False
        self.chats = []
        self.cabeceras = []
        self.rutas = []
        self.rechazar_temperatura = False    # 400 si llega "temperature" (modelos que ya no la aceptan)
        self.rechazo = False                 # Anthropic: stop_reason "refusal"
        srv = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, obj):
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                srv.cabeceras.append(dict(self.headers))
                srv.rutas.append(self.path)
                self._json(200, {"data": [{"id": "modelo-b"}, {"id": "modelo-a"}]})

            def do_POST(self):
                srv.cabeceras.append(dict(self.headers))
                cuerpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if srv.fallar:
                    return self._json(500, {"error": f"fallo con clave {CLAVE}"})
                if srv.rechazar_temperatura and "temperature" in cuerpo:
                    srv.chats.append(cuerpo)
                    return self._json(400, {"type": "error", "error": {"type": "invalid_request_error",
                                      "message": "`temperature` is deprecated for this model."}})
                if self.path.endswith("/embeddings"):
                    textos = cuerpo["input"]
                    return self._json(200, {"data": [{"index": i, "embedding": vec_hash(t).tolist()}
                                                     for i, t in enumerate(textos)]})
                srv.chats.append(cuerpo)
                srv.rutas.append(self.path)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                if self.path.endswith("/messages"):         # API nativa de Anthropic
                    eventos = [{"type": "message_start", "message": {"usage": {"input_tokens": 61}}},
                               {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}}]
                    eventos += [{"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "text_delta", "text": srv.respuesta[i:i + 7]}}
                                for i in range(0, len(srv.respuesta), 7)]
                    fin = {"type": "message_delta", "usage": {"output_tokens": 23}}
                    if srv.rechazo:
                        eventos = eventos[:2]
                        fin["delta"] = {"stop_reason": "refusal", "stop_details": {"category": "cyber"}}
                    eventos += [fin, {"type": "message_stop"}]
                    for e in eventos:
                        self.wfile.write(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode())
                    return
                try:
                    for trozo in [srv.respuesta[i:i + 7] for i in range(0, len(srv.respuesta), 7)]:
                        d = {"choices": [{"delta": {"content": trozo}}]}
                        self.wfile.write(f"data: {json.dumps(d)}\n\n".encode())
                    self.wfile.write(b'data: {"choices":[],"usage":{"prompt_tokens":50,"completion_tokens":20}}\n\n')
                    self.wfile.write(b"data: [DONE]\n\n")
                except (BrokenPipeError, ConnectionResetError):
                    pass                                       # el cliente canceló

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"

    def cerrar(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _indice_chico():
    frags = [
        Fragmento("usbr_3_1", 10, "10", "Insulation resistance of the stator winding is measured with a megohmmeter; "
                  "the polarization index is the ratio of the 10-minute to the 1-minute reading."),
        Fragmento("usbr_3_1", 10, "10", "Insulation resistance readings should be corrected to 40 C for trending."),
        Fragmento("usbr_3_1", 10, "10", "Megohmmeter insulation resistance test voltage depends on the winding rating."),
        Fragmento("usbr_3_4", 5, "5", "Space heaters keep motor windings dry and above the dew point when idle."),
        Fragmento("femp_om", 120, "", "Steam traps should be checked annually for leaks and blockages."),
        Fragmento("tesis", 6, "§6", "Falsas alarmas: 7.3 por hora en operación continua sin falla; una alarma LEVE "
                  "breve puede ser una falsa alarma del motor sano."),
        Fragmento("tesis", 6, "§6", "Consecuencia práctica: la condición del aislamiento debe confirmarse con las pruebas "
                  "que indican los documentos de mantenimiento."),
        Fragmento("tesis", 7, "§7", "Limitaciones: el sistema no sustituye las pruebas eléctricas fuera de línea."),
        Fragmento("tesis", 1, "§1", "Banco de pruebas: severidad INTER con 14.3 % de las espiras de la fase C; "
                  "inspección y pruebas del aislamiento del devanado del estator."),
        Fragmento("banco", 20, "§20", "Alarma enclavada del detector del banco: se libera cuando la firma cae; "
                  "inspección del aislamiento del devanado del estator tras una alarma."),
    ]
    emb = np.vstack([vec_hash(f.texto) for f in frags])
    return Indice(frags, emb, {"documentos": {"x": "1"}})


def test_fragmentos_no_cruzan_pagina():
    texto = " ".join(f"Oración número {i} sobre el aislamiento del devanado." for i in range(200))
    p = Pagina("doc", 7, "5", texto)
    fr = fragmentar(p)
    assert len(fr) > 5 and all(f.pag == 7 and f.etiqueta == "5" for f in fr)
    assert all(len(f.texto) <= 900 * 1.3 for f in fr), max(len(f.texto) for f in fr)
    assert fr[0].texto.startswith("Oración número 0") and fr[-1].texto.endswith("199 sobre el aislamiento del devanado.")
    juntos = " ".join(f.texto for f in fr)
    assert all(f"número {i} " in juntos for i in range(200))          # no se pierde texto entre fragmentos
    assert fragmentar(Pagina("doc", 1, "", "Texto corto."))[0].texto == "Texto corto."


def test_extracto_tesis_y_idioma():
    ruta = os.path.join(DIR_RAG, "datos", "tesis_resultados.md")
    secs = paginas_md(ruta, "tesis")
    assert [s.etiqueta for s in secs] == [f"§{k}" for k in range(1, 8)]
    assert "7.3 por hora" in secs[5].texto and "1.626" in secs[2].texto
    assert idioma("The insulation resistance of the winding should be measured with the motor disconnected from "
                  "the supply and it is recommended that the reading is corrected to 40 C for the trend.") == "en"
    assert idioma("La resistencia de aislamiento del devanado debe medirse con el motor desconectado de la red y se "
                  "recomienda que la lectura se corrija a 40 C para la tendencia del motor.") == "es"
    assert idioma("Der Isolationswiderstand der Wicklung ist mit einem Messgerät zu prüfen, das nicht mit der "
                  "Versorgung verbunden ist und für die Messung und den Vergleich mit den Werten.") == "de"


def test_documento_banco():
    rec = next(r for r in catalogo.DOCUMENTOS if r.clave == "banco")
    assert rec.en_paquete and rec.idiomas == ("es",)
    secs = paginas_documento(os.path.join(DIR_RAG, "datos", rec.archivo), "banco", rec.idiomas)
    assert len(secs) >= 30 and [s.etiqueta for s in secs] == [f"§{k}" for k in range(1, len(secs) + 1)]
    assert "NO describe el motor que vigila" in secs[0].texto and all(len(s.texto) > 200 for s in secs)
    frs = [f for s in secs for f in fragmentar(s)]
    assert all(len(f.texto) <= 900 * 1.3 for f in frs)
    assert "banco" in mod_asis.DOCS_BANCO and "banco" not in mod_asis.SECCIONES_TESIS_ALARMA


def test_pdf_reales():
    ruta = os.path.join(DOCS, "ABB_3GZF500730-85_RevH.pdf")
    if not os.path.exists(ruta):
        print("    (se omite: no están los PDF en ~/tesis_itf/rag_docs)")
        return
    abb = paginas_documento(ruta, "abb", ("es",))
    assert abb and all(idioma(p.texto) == "es" for p in abb)
    assert 90 <= min(p.pag for p in abb) and max(p.pag for p in abb) <= 125, (min(p.pag for p in abb), max(p.pag for p in abb))
    assert any("resistencia de aislamiento" in p.texto.lower() for p in abb)
    nasa = paginas_documento(os.path.join(DOCS, "NASA_RCM_Guide_2008.pdf"), "nasa_rcm")
    assert len(nasa) > 300
    # el encabezado que se repite en todas las páginas se quita
    assert sum("RELIABILITY-CENTERED MAINTENANCE GUIDE FOR FACILITIES" in p.texto for p in nasa) < len(nasa) * 0.1


def test_indice_busqueda_y_disco():
    ind = _indice_chico()
    assert "insulation" in ampliar_consulta("¿Cómo pruebo el aislamiento?")
    assert "energized" in ampliar_consulta("¿Qué pruebas requieren desenergizar?")
    assert "condensation" in ampliar_consulta("¿Cómo evitar la condensación en un motor parado?")
    q = "¿Cómo se mide la resistencia de aislamiento del devanado con megóhmetro?"
    res = ind.buscar(q, vec_hash(" ".join(ampliar_consulta(q))), k=5)
    assert res[0].fragmento.doc == "usbr_3_1"
    assert sum(1 for r in res if (r.fragmento.doc, r.fragmento.pag) == ("usbr_3_1", 10)) <= 2   # máximo por página
    solo = ind.buscar(q, vec_hash(q), k=3, docs=["tesis"])
    assert solo and all(r.fragmento.doc == "tesis" for r in solo)
    with tempfile.TemporaryDirectory() as d:
        ruta = os.path.join(d, "indice")
        ind.manifiesto = {"documentos": {"x": "1"}, "version": 1}
        ind.guardar(ruta)
        otro = Indice.cargar(ruta)
        assert len(otro) == len(ind) and otro.vigente({"documentos": {"x": "1"}})
        assert not otro.vigente({"documentos": {"x": "2"}})
        # con rangos de páginas (tuplas) el índice guardado sigue vigente al recargarlo
        ind.manifiesto = {"documentos": {"x": ["1", [(3, 9)], ["es"]]}, "version": 1}
        ind.guardar(ruta)
        assert Indice.cargar(ruta).vigente({"documentos": {"x": ["1", [(3, 9)], ["es"]]}})
        assert np.allclose(otro.emb, ind.emb)
        assert Indice.cargar(os.path.join(d, "no_existe")) is None
    # Reconstrucción incremental: solo se calculan los fragmentos nuevos (mismo modelo de embeddings)
    vistos = []

    def embed(textos):
        vistos.extend(textos)
        return np.vstack([vec_hash(t) for t in textos])
    man = {"documentos": {"x": "1"}, "modelo_embeddings": "m1"}
    base = Indice.construir(ind.fragmentos[:3], embed, man)
    vistos.clear()
    nuevo = Indice.construir(ind.fragmentos, embed, man, previo=base)
    assert vistos == [f.texto for f in ind.fragmentos[3:]] and np.allclose(nuevo.emb, ind.emb)
    vistos.clear()
    Indice.construir(ind.fragmentos, embed, dict(man, modelo_embeddings="m2"), previo=base)
    assert len(vistos) == len(ind.fragmentos)                # otro modelo: se recalcula todo


def test_citas_y_prompt():
    lineas = analizar("Recomendaciones:\n- Desenergice y bloquee el motor antes de inspeccionar [2].\n"
                      "- Mida el índice de polarización [1][3] y compare con la tendencia.\n"
                      "- Revise los rodamientos del lado acoplado [9].\n- Limpie el devanado con aire seco.", 3)
    assert [l.citas for l in lineas] == [[], [2], [1, 3], [], []]
    assert lineas[3].invalidas == [9] and not lineas[0].es_afirmacion
    r = mod_asis.Respuesta("p", "", [], lineas=lineas)
    assert abs(r.fraccion_citada - 2 / 4) < 1e-9
    # Verificación de cifras decimales contra los fragmentos citados y el contexto
    from motorguard_dashboard.rag.indice import Resultado
    fu_citas = [Resultado(Fragmento("tesis", 6, "§6", "Tasa de 7.3 por hora y umbral 1.626 pp."), 0, 0.8, 1)]
    lin_ok = analizar("- En operación continua hubo 7.3 falsas alarmas y umbral 1.63 pp [1].", 1, fuentes=fu_citas)
    assert not lin_ok[0].cifras_sin_soporte
    lin_mal = analizar("- La resistencia debe ser al menos 99.5 MΩ con corriente 2.35 A [1].", 1,
                       fuentes=fu_citas, contexto="Corriente: 2.35 A")
    assert lin_mal[0].cifras_sin_soporte == ["99.5"]

    from motorguard_dashboard.telemetry.parser import Trama  # noqa: F401
    from motorguard_dashboard.tests.test_plano_firma import trama

    class Ev:
        t_inicio = 100.0

        def duracion(self, t):
            return t - self.t_inicio
    tr = trama(130.0, complex(0.1, 0.8), p_fw=0.1, c=1, sev=2, ml=2.345, pl=2.1)
    ctx = ContextoAlarma.de_trama(tr, Ev())
    assert ctx.severidad == "INTER" and ctx.ml_pp == 2.345 and ctx.segundos_alarma == 30.0
    texto = ctx.texto()
    assert "INTER" in texto and "2.35 pp" in texto and "30 s" in texto and f"{tr.i1:.3f} A pico" in texto
    assert f"A {tr.ia:.2f} A, B {tr.ib:.2f} A, C {tr.ic:.2f} A" in texto
    sin = ContextoAlarma.de_trama(trama(131.0, complex(0.1, 0.8)), None)
    assert sin.severidad is None and sin.ml_pp is None and "Sin alarma" in sin.texto()
    ind = _indice_chico()
    msgs = construir_mensajes("¿Qué reviso?", ind.buscar("aislamiento", vec_hash("insulation"), 2), ctx)
    assert msgs[0]["role"] == "system" and "SOLO" in msgs[0]["content"]
    assert "[1] USBR · FIST 3-1, pág. 10 del PDF" in msgs[1]["content"] and "Valores medidos" in msgs[1]["content"]


def test_asistente_con_servidor_falso():
    srv = ServidorFalso()
    externo = ServidorFalso()
    try:
        ind = _indice_chico()
        emb = ClienteOpenAI(srv.url)
        local = ClienteOpenAI(srv.url, "qwen", nombre="Qwen3.5 (local)")
        a = Asistente(ind, emb, local, umbral=0.30)
        tokens_vistos = []
        r = a.responder("¿Cómo mido la resistencia de aislamiento del devanado con megohmmeter?",
                        al_token=tokens_vistos.append)
        assert not r.abstencion and len(srv.chats) == 1 and "".join(tokens_vistos) == srv.respuesta
        assert r.fraccion_citada == 1.0 and r.tokens_prompt == 50 and r.modelo == "Qwen3.5 (local)"
        # Abstención: nada parecido en los documentos -> no se llama al LLM
        r2 = a.responder("¿Quién ganó el campeonato de fútbol de 1986?")
        assert r2.abstencion and r2.texto == mod_asis.SIN_FUENTE and len(srv.chats) == 1 and not r2.fuentes
        # Alarma: siempre incluye la tesis (§6 y §7, SECCIONES_TESIS_ALARMA) y los valores medidos
        r3 = a.responder("alarma", ctx=ContextoAlarma("SEVERA", 5.0, 7.7, 5.5, 5.6, 5.9, 12, "FALLA"), alarma=True)
        assert "SEVERA" in srv.chats[-1]["messages"][1]["content"]
        assert [f.fragmento.etiqueta for f in r3.fuentes if f.fragmento.doc == "tesis"] == ["§6", "§7"]
        assert r3.fuentes[-2].fragmento.texto.startswith("Consecuencia práctica")
        assert not any(f.fragmento.doc == "banco" for f in r3.fuentes)      # el banco no compite al alarmar
        # Externo que falla: responde el local, con aviso y sin la clave
        externo.fallar = True
        ext = ClienteOpenAI(externo.url, "deepseek-x", clave=CLAVE, nombre="deepseek-x (externo)")
        b = Asistente(ind, emb, ext, respaldo_llm=local, umbral=0.30)
        r4 = b.responder("¿Cómo mido la resistencia de aislamiento del devanado con megohmmeter?")
        assert r4.modelo == "Qwen3.5 (local)" and "externo falló" in r4.aviso and CLAVE not in r4.aviso
        assert any(c.get("Authorization") == f"Bearer {CLAVE}" for c in externo.cabeceras)
        # Sin respaldo: error informado sin la clave
        c = Asistente(ind, emb, ext, umbral=0.30).responder("¿Cómo mido la resistencia de aislamiento con megohmmeter?")
        assert c.error and CLAVE not in c.error and not c.texto
        assert ClienteOpenAI(srv.url).modelos() == ["modelo-a", "modelo-b"]
        # Cancelar a mitad de la respuesta
        r5 = a.responder("¿Cómo mido la resistencia de aislamiento del devanado con megohmmeter?",
                         cancelado=lambda: True)
        assert r5.cancelada
    finally:
        srv.cerrar()
        externo.cerrar()


def test_protocolos_de_proveedor():
    """Anthropic usa su API nativa (/messages, sistema aparte, x-api-key); Azure, la cabecera api-key."""
    from motorguard_dashboard.rag.proveedores import protocolo_de_url
    assert protocolo_de_url("https://api.anthropic.com/v1") == "anthropic"
    assert protocolo_de_url("https://api.deepseek.com/v1") == "openai"
    srv = ServidorFalso()
    try:
        cli = ClienteOpenAI(srv.url, "claude-x", clave=CLAVE, protocolo="anthropic")
        vistos = []
        r = cli.chat([{"role": "system", "content": "reglas"}, {"role": "user", "content": "hola"}],
                     al_token=vistos.append)
        assert r.texto == srv.respuesta == "".join(vistos)
        assert (r.tokens_prompt, r.tokens_respuesta) == (61, 23)
        cuerpo, cab = srv.chats[-1], {k.lower(): v for k, v in srv.cabeceras[-1].items()}
        assert srv.rutas[-1] == "/v1/messages" and cuerpo["system"] == "reglas"
        assert cuerpo["messages"] == [{"role": "user", "content": "hola"}]
        assert cab.get("x-api-key") == CLAVE and "authorization" not in cab and cab.get("anthropic-version")
        assert cli.modelos() == ["modelo-a", "modelo-b"] and srv.rutas[-1] == "/v1/models?limit=1000"
        # Claude actual rechaza temperature y su razonamiento cuenta contra max_tokens (banco, 13-oct)
        assert "temperature" not in cuerpo and cuerpo["max_tokens"] >= 4096
        assert cuerpo["output_config"] == {"effort": "low"}          # chat: esfuerzo bajo, más rápido
        srv.rechazo = True
        try:
            cli.chat([{"role": "user", "content": "x"}])
            assert False, "un rechazo debe informarse como falla"
        except ErrorProveedor as e:
            assert "refusal" in str(e) and "cyber" in str(e)
        srv.rechazo = False
        # Compatible con OpenAI: si el proveedor rechaza temperature, se reintenta sin ella
        srv.rechazar_temperatura = True
        oa = ClienteOpenAI(srv.url, "modelo-razonador", clave=CLAVE)
        r = oa.chat([{"role": "user", "content": "hola"}])
        assert r.texto == srv.respuesta and "temperature" in srv.chats[-2] and "temperature" not in srv.chats[-1]
        srv.rechazar_temperatura = False
        # Azure OpenAI: misma API compatible, la clave va en "api-key"
        az = ClienteOpenAI("https://recurso.openai.azure.com/openai/v1", "gpt-x", clave=CLAVE)._cabeceras()
        assert az.get("api-key") == CLAVE and "Authorization" not in az
        assert ClienteOpenAI(srv.url, clave=CLAVE)._cabeceras()["Authorization"] == f"Bearer {CLAVE}"
        try:
            ClienteOpenAI(srv.url, protocolo="otro")
            assert False, "debió rechazar el protocolo"
        except ValueError:
            pass
    finally:
        srv.cerrar()
    print("  proveedores: OpenAI compatible, Anthropic nativo y cabecera de Azure")


def test_aislamiento_del_puerto_serie():
    prohibidos = ("fuente_serie", "inyeccion", "serial", "panel_inyeccion", "adquisicion")
    for ruta in glob.glob(os.path.join(DIR_RAG, "*.py")):
        arbol = ast.parse(open(ruta, encoding="utf-8").read())
        for nodo in ast.walk(arbol):
            nombres = []
            if isinstance(nodo, ast.Import):
                nombres = [a.name for a in nodo.names]
            elif isinstance(nodo, ast.ImportFrom):
                nombres = [nodo.module or ""]
            for n in nombres:
                assert not any(p in n for p in prohibidos), (ruta, n)
            if isinstance(nodo, ast.Attribute):
                assert nodo.attr != "enviar", ruta          # FuenteSerie.enviar es la única vía al Arduino


_LLAMA_FALSO = r'''#!{py}
import sys, http.server
puerto = int(sys.argv[sys.argv.index("--port") + 1])
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'{{"status":"ok"}}')
http.server.HTTPServer(("127.0.0.1", puerto), H).serve_forever()
'''


def test_servicio_arranca_y_detiene():
    from motorguard_dashboard.rag import servicio
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "llama"))
        os.makedirs(os.path.join(d, "modelos"))
        binario = os.path.join(d, "llama", "llama-server")
        with open(binario, "w") as fh:
            fh.write(_LLAMA_FALSO.format(py=sys.executable))
        os.chmod(binario, os.stat(binario).st_mode | stat.S_IEXEC)
        motor = servicio.MotorLocal(d)
        assert set(motor.faltantes()) == {"Qwen3.5-4B", "Qwen3-Embedding-0.6B"}
        for rec in (catalogo.MODELO_LLM, catalogo.MODELO_EMB):
            open(motor.ruta_modelo(rec), "w").close()
        assert motor.faltantes() == []
        motor.iniciar()
        try:
            assert motor.esperar(20)
            assert motor.llm.puerto != motor.emb.puerto and motor.llm.listo()
            pid = motor.llm.proc.pid
            assert os.getpriority(os.PRIO_PROCESS, pid) >= servicio.NICE
            assert len(servicio._VIVOS) == 2
        finally:
            motor.detener()
        assert not servicio._VIVOS and motor.llm.proc is None


def test_descargas():
    from motorguard_dashboard.rag.descargas import ErrorDescarga, descargar
    contenido = os.urandom(300_000)
    sha = hashlib.sha256(contenido).hexdigest()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            ini = 0
            rng = self.headers.get("Range")
            if rng:
                ini = int(rng.split("=")[1].split("-")[0])
                self.send_response(206)
            else:
                self.send_response(200)
            self.send_header("Content-Length", str(len(contenido) - ini))
            self.end_headers()
            self.wfile.write(contenido[ini:])

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/archivo.bin"
    try:
        with tempfile.TemporaryDirectory() as d:
            bueno = catalogo.Recurso("x", "x.bin", url, sha, len(contenido), "MIT")
            with open(os.path.join(d, "x.bin.part"), "wb") as fh:          # descarga interrumpida
                fh.write(contenido[:100_000])
            assert descargar(bueno, d) == sha
            assert open(os.path.join(d, "x.bin"), "rb").read() == contenido
            malo = catalogo.Recurso("y", "y.bin", url, "0" * 64, None, "MIT")
            try:
                descargar(malo, d)
                assert False, "debió fallar"
            except ErrorDescarga as e:
                assert "SHA-256" in str(e)
            assert not glob.glob(os.path.join(d, "y.bin*"))
            # documento con versión distinta: se conserva si no es estricto
            assert descargar(malo, d, estricto=False) == sha and os.path.exists(os.path.join(d, "y.bin"))
    finally:
        httpd.shutdown()
        httpd.server_close()


def run():
    for nombre, f in sorted(globals().items()):
        if nombre.startswith("test_") and callable(f):
            f()
            print(f"  ✅ asistente RAG: {nombre}")


if __name__ == "__main__":
    run()
