"""
Integración de la sección Asistente sin modelos reales: un llama-server FALSO (script de Python con /health,
/v1/embeddings y /v1/chat/completions) recorre la cadena completa ServicioAsistente → MotorLocal → índice
(construido con el extracto de la tesis) → respuesta → interfaz.

Verifica: arranque y paro de los procesos, índice construido y reutilizado, pregunta con respuesta y citas
enlazadas, clic en una cita (fragmento visible), registro JSONL sin claves, consulta automática una sola vez
por alarma y nunca si la alarma la provocó el usuario, proveedor externo que falla (responde el local) y que
la clave no queda en QSettings. Los ajustes y carpetas son temporales.
"""

import glob
import json
import os
import stat
import sys
import tempfile

from motorguard_dashboard.tests import qt_util
from motorguard_dashboard.tests.test_fuente_serie import _esperar

LLAMA_FALSO = r'''#!{py}
import sys, json, zlib, re, unicodedata, http.server
puerto = int(sys.argv[sys.argv.index("--port") + 1])
emb = "--embedding" in sys.argv
def vec(t):
    if t.startswith("Instruct:"):
        t = t.split("Query: ", 1)[1]
    t = "".join(c for c in unicodedata.normalize("NFKD", t.lower()) if not unicodedata.combining(c))
    v = [0.0] * 128
    for w in re.findall(r"[a-z0-9]+", t):
        if len(w) > 3:
            v[zlib.crc32(w.encode()) % 128] += 1.0
    return v
RESP = "- Desenergice el motor antes de inspeccionar [1].\n- Revise el historial de falsas alarmas [2].\n- Cambie el aceite [7]."
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _j(self, o):
        b = json.dumps(o).encode(); self.send_response(200); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        self._j({{"status": "ok"}})
    def do_POST(self):
        c = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.endswith("/embeddings"):
            return self._j({{"data": [{{"index": i, "embedding": vec(x)}} for i, x in enumerate(c["input"])]}})
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        try:
            for i in range(0, len(RESP), 9):
                self.wfile.write(("data: " + json.dumps({{"choices": [{{"delta": {{"content": RESP[i:i+9]}}}}]}}) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
        except BrokenPipeError:
            pass
http.server.ThreadingHTTPServer(("127.0.0.1", puerto), H).serve_forever()
'''


def _preparar_dir(d):
    os.makedirs(os.path.join(d, "asistente", "llama"))
    os.makedirs(os.path.join(d, "asistente", "modelos"))
    binario = os.path.join(d, "asistente", "llama", "llama-server")
    with open(binario, "w") as fh:
        fh.write(LLAMA_FALSO.format(py=sys.executable))
    os.chmod(binario, os.stat(binario).st_mode | stat.S_IEXEC)
    from motorguard_dashboard.rag import catalogo
    for rec in (catalogo.MODELO_LLM, catalogo.MODELO_EMB):
        open(os.path.join(d, "asistente", "modelos", rec.archivo), "w").close()
    os.makedirs(os.path.join(d, "docs"))          # sin PDF: solo el extracto de la tesis (viene con la app)


class Ev:
    def __init__(self, t0):
        self.t_inicio = t0

    def duracion(self, t):
        return t - self.t_inicio


def test_asistente_con_llama_falso():
    app = qt_util.app()
    from PySide6.QtCore import QSettings, QUrl
    from motorguard_dashboard.rag import servicio as mod_servicio
    from motorguard_dashboard.sistema import claves, rutas
    from motorguard_dashboard.tests.test_plano_firma import trama
    from motorguard_dashboard.ui import asistente_tab as mod_tab
    from motorguard_dashboard.ui.asistente_servicio import ServicioAsistente
    from motorguard_dashboard.ui.tema import GestorTema

    original_llavero = claves._llavero
    claves._llavero = lambda: None                 # nunca el llavero real del usuario
    with tempfile.TemporaryDirectory() as d:
        _preparar_dir(d)
        conf = QSettings(os.path.join(d, "ajustes.ini"), QSettings.IniFormat)
        conf.setValue(rutas.CLAVE_DOCUMENTOS, os.path.join(d, "docs"))
        conf.setValue(rutas.CLAVE_REGISTROS, os.path.join(d, "registros"))
        provocada = {"v": False}
        tema = GestorTema(app, persistir=False, modo="claro")
        w = mod_tab.AsistenteTab(tema=tema, provocada=lambda: provocada["v"], conf=conf)
        w.aplicar_tema(tema.t)
        w.show()
        # Precarga lenta (en la PC real tarda ~2.5 min): se debe poder preguntar mientras corre (banco, 13-oct)
        import time as _t
        from motorguard_dashboard.ui import asistente_servicio as mod_as
        precarga_real = mod_as.ServicioAsistente._precalentar
        fin_precarga = {"t": None}

        def precarga_lenta(self):
            _t.sleep(6)
            precarga_real(self)
            fin_precarga["t"] = _t.monotonic()
        mod_as.ServicioAsistente._precalentar = precarga_lenta
        srv = ServicioAsistente(os.path.join(d, "asistente"), lambda: os.path.join(d, "docs"))
        srv.umbral = 0.15                          # el embedding falso (bolsa de palabras) da cosenos bajos
        w.iniciar_servicio(srv)
        try:
            # la etiqueta se actualiza con la señal de estado, un instante después de que el servicio queda listo
            assert _esperar(lambda: srv.listo and "fragmentos" in w.lbl_servicio.text(), 60), w.lbl_servicio.text()
            assert len(mod_servicio._VIVOS) == 2
            assert "precarga" in w.lbl_servicio.text() and fin_precarga["t"] is None
            assert os.path.exists(os.path.join(d, "asistente", "indice", "manifiesto.json"))
            assert w._filas_fuentes["tesis"].text() == "Disponible" and w._filas_fuentes["banco"].text() == "Disponible"
            assert w._filas_fuentes["abb"].text() == "Falta"
            assert w.btn_preguntar.isEnabled()

            # Pregunta libre
            # El modelo procesa una cosa a la vez: la pregunta hecha antes de que empiece la precarga va primero (si
            # ya empezó, espera en cola y se avisa); nunca corren a la vez (en el banco eso bajó todo a ~2 tokens/s)
            w._preguntar("¿Qué dice la tesis sobre las falsas alarmas en operación continua?")
            assert _esperar(lambda: w._entradas and w._entradas[-1]["r"] is not None, 40)
            t_resp = _t.monotonic()
            assert _esperar(lambda: fin_precarga["t"] is not None and "precargando" not in w.lbl_servicio.text(), 40)
            assert fin_precarga["t"] > t_resp or w.lbl_cola.text(), "pregunta y precarga corrieron a la vez"
            # Durante la precarga, una pregunta queda en cola con aviso
            mod_as.ServicioAsistente._precalentar = precarga_real
            r = w._entradas[-1]["r"]
            assert not r.abstencion and r.fuentes and all(f.fragmento.doc in ("tesis", "banco") for f in r.fuentes)
            html = w.conversacion.html()
            assert "cita:0-1" in html and "Fuentes:" in html
            assert [l.invalidas for l in r.lineas][-1] == [7]                 # [7] no existe: se marca
            w._cita(QUrl("cita:0-1"))
            assert w.caja_frag.isVisible() and any(
                t in w.lbl_frag.text() for t in ("Resultados validados de la tesis", "Documento técnico del banco de pruebas")
            )
            registro = glob.glob(os.path.join(d, "registros", "asistente_*.jsonl"))
            assert registro and json.loads(open(registro[0]).readline())["modelo"].endswith("(local)")

            # Alarma: consulta automática UNA vez por evento
            ev = Ev(1000.0)
            n0 = len(w._entradas)
            tr = trama(1005.0, complex(0.1, 0.8), p_fw=0.1, c=1, sev=2, ml=2.3, pl=2.0)
            for k in range(5):
                w.contexto(tr, ev)
            # La alarma se libera mientras el modelo responde: el registro debe guardar el contexto que recibió el
            # modelo (INTER), no el de la trama actual (banco, 13-oct: quedaba "Sin alarma confirmada")
            w.contexto(trama(1007.0, complex(0.1, 0.1), p_fw=0.0, c=0, sev=0, ml=0.0, pl=0.0), None)
            assert _esperar(lambda: len(w._entradas) == n0 + 1 and w._entradas[-1]["r"] is not None, 30)
            assert w._entradas[-1]["alarma"] and "INTER" in w._entradas[-1]["pregunta"]
            ultima = json.loads(open(registro[0], encoding="utf-8").readlines()[-1])
            assert ultima["alarma"] and "severidad INTER" in ultima["contexto"], ultima["contexto"]
            assert any(f.fragmento.doc == "tesis" for f in w._entradas[-1]["r"].fuentes)
            app.processEvents()
            assert len(w._entradas) == n0 + 1
            # Alarma provocada por el usuario: no se consulta
            provocada["v"] = True
            w.contexto(tr, Ev(2000.0))
            app.processEvents()
            assert len(w._entradas) == n0 + 1
            provocada["v"] = False
            # Consulta automática desactivada
            w.chk_auto.setChecked(False)
            w.contexto(tr, Ev(3000.0))
            app.processEvents()
            assert len(w._entradas) == n0 + 1 and conf.value(mod_tab.CLAVE_AUTO) in (False, "false")

            # Proveedor externo que falla: responde el local; la clave no queda en QSettings
            conf.setValue(mod_tab.CLAVE_EXT_URL, "http://127.0.0.1:9/v1")       # puerto cerrado
            conf.setValue(mod_tab.CLAVE_EXT_MODELO, "modelo-externo")
            conf.setValue(mod_tab.CLAVE_EXT_ACEPTADO + "/127.0.0.1:9", True)
            claves.guardar("http://127.0.0.1:9/v1", "sk-NO-DEBE-QUEDAR")
            w._elegir_proveedor("externo")
            assert srv.externo is not None and srv.externo.modelo == "modelo-externo"
            n1 = len(w._entradas)
            w._preguntar("¿Qué dice la tesis sobre las falsas alarmas en operación continua?")
            assert _esperar(lambda: len(w._entradas) == n1 + 1 and w._entradas[-1]["r"] is not None, 30)
            r = w._entradas[-1]["r"]
            assert r.modelo.endswith("(local)") and "externo falló" in r.aviso and "sk-NO" not in r.aviso
            conf.sync()
            assert "sk-NO-DEBE-QUEDAR" not in open(os.path.join(d, "ajustes.ini")).read()
            assert all("sk-NO-DEBE-QUEDAR" not in open(f).read() for f in registro)
            w._elegir_proveedor("local")
            assert srv.externo is None
            # Diálogo: el preset de Anthropic elige su API nativa; una URL personalizada puede usar cualquiera
            dlg = mod_tab.DialogoExterno(conf)
            dlg.cmb_preset.setCurrentText("Anthropic")
            assert dlg.cmb_protocolo.currentData() == "anthropic"
            dlg.cmb_preset.setCurrentText("DeepSeek")
            assert dlg.cmb_protocolo.currentData() == "openai"
            dlg.cmb_preset.setCurrentText("URL personalizada")
            dlg.txt_url.setText("https://proxy.ejemplo.org/v1")
            dlg.cmb_protocolo.setCurrentIndex(dlg.cmb_protocolo.findData("anthropic"))
            dlg.cmb_modelo.setCurrentText("claude-x")
            dlg.chk_aviso.setChecked(True)
            dlg._guardar()
            assert conf.value(mod_tab.CLAVE_EXT_PROTOCOLO) == "anthropic"
            assert w._cliente_externo().protocolo == "anthropic"
            conf.setValue(mod_tab.CLAVE_EXT_URL, "")

            # Abstención en la interfaz: nada parecido -> sin llamar al LLM
            n2 = len(w._entradas)
            w._preguntar("zzz qqq xxx")
            assert _esperar(lambda: len(w._entradas) == n2 + 1 and w._entradas[-1]["r"] is not None, 30)
            assert w._entradas[-1]["r"].abstencion

            # Al reiniciar se reutiliza el índice (no se reconstruye)
            mtime = os.path.getmtime(os.path.join(d, "asistente", "indice", "embeddings.npy"))
            srv2 = ServicioAsistente(os.path.join(d, "asistente"), lambda: os.path.join(d, "docs"))
            srv2.iniciar()
            assert _esperar(lambda: srv2.listo, 60)
            assert os.path.getmtime(os.path.join(d, "asistente", "indice", "embeddings.npy")) == mtime
            srv2.cerrar()
        finally:
            w.cerrar()
            claves._llavero = original_llavero
            claves._memoria.clear()
        assert not mod_servicio._VIVOS, "quedaron llama-server vivos"
    print("  llama-server falso: arranque, índice, pregunta con citas, alarma automática única, externo con "
          "respaldo local, abstención y paro")


def test_servicio_sin_preparar():
    app = qt_util.app()
    from PySide6.QtCore import QSettings
    from motorguard_dashboard.ui import asistente_tab as mod_tab
    from motorguard_dashboard.ui.asistente_servicio import ServicioAsistente
    with tempfile.TemporaryDirectory() as d:
        conf = QSettings(os.path.join(d, "ajustes.ini"), QSettings.IniFormat)
        w = mod_tab.AsistenteTab(conf=conf)
        srv = ServicioAsistente(os.path.join(d, "vacio"), lambda: os.path.join(d, "docs"))
        w.iniciar_servicio(srv)
        try:
            assert _esperar(lambda: "Preparar asistente" in w.lbl_servicio.text(), 10), w.lbl_servicio.text()
            assert w.btn_preparar.isEnabled()
            assert not w.btn_preguntar.isEnabled()
        finally:
            w.cerrar()
    app.processEvents()


def test_conversacion_estilo_chat():
    """Pregunta en burbuja a la derecha, citas con documento y página, tarjeta de alarma con severidad y ML,
    sugerencias solo con la conversación vacía (diseño aprobado por el autor el 13-oct)."""
    app = qt_util.app()
    import tempfile as tf
    from PySide6.QtCore import QPoint, QSettings
    from motorguard_dashboard.rag.asistente import Respuesta, analizar
    from motorguard_dashboard.rag.indice import Resultado
    from motorguard_dashboard.rag.ingesta import Fragmento
    from motorguard_dashboard.ui import asistente_tab as mod_tab
    from motorguard_dashboard.ui.tema import GestorTema
    tema = GestorTema(app, persistir=False, modo="claro")
    w = mod_tab.AsistenteTab(tema=tema, conf=QSettings(os.path.join(tf.mkdtemp(), "a.ini"), QSettings.IniFormat))
    w.resize(1400, 1000)
    w.show()
    app.processEvents()
    assert w.conversacion.vacio.isVisible() and all(b.isVisible() for b in w._botones_sug)
    fu = [Resultado(Fragmento("usbr_3_1", 11, "5", "Polarization index = R10/R1"), 0, 0.8, 1),
          Resultado(Fragmento("tesis", 6, "§6", "Consecuencia práctica"), 0, 0.6, 1)]
    txt = "- El IP es R10/R1 [1].\n- Confirme con pruebas fuera de línea [2][7]."
    r = Respuesta("¿Cómo se mide el IP?", txt, fu, lineas=analizar(txt, 2), modelo="Qwen3.5-4B (local)", t_total=90,
                  contexto="- Alarma confirmada por el firmware, severidad INTER\n- Magnitud de la firma (ML): 2.25 pp de |I1|")
    w._entradas = [{"pregunta": "¿Cómo se mide el IP?", "alarma": False, "texto": "", "r": r, "hora": "14:20:01"},
                   {"pregunta": "El detector confirmó una alarma INTER (posible…)", "alarma": True, "texto": "", "r": r,
                    "hora": "14:11:22"},
                   {"pregunta": "¿Y la humedad?", "alarma": False, "texto": "- Use resistencias", "r": None, "hora": "x"}]
    w._render()
    app.processEvents()
    assert not w.conversacion.vacio.isVisible()
    m0, m1, m2 = w.conversacion._mensajes
    centro = m0.burbuja.mapTo(w.conversacion, QPoint(m0.burbuja.width() // 2, 0)).x()
    assert centro > w.conversacion.viewport().width() // 2, "la burbuja del usuario va a la derecha"
    html = w.conversacion.html()
    assert "USBR 3-1 p.11" in html and "Tesis §6" in html and "cita:0-1" in html and "<s>[7]</s>" in html
    assert "INTER" in m1.cabeza.text() and "ML 2.25 pp" in m1.cabeza.text() and "14:11:22" in m1.cabeza.text()
    assert "▍" in m2.texto.text() and not m2.pie.isVisible() and "Qwen3.5-4B" in m0.pie.text()
    # Clic en una cita: muestra el fragmento citado
    w._cita(mod_tab.QUrl("cita:0-2"))
    assert w.caja_frag.isVisible() and "§6" in w.lbl_frag.text()
    w.close()
    print("  conversación: burbuja a la derecha, citas con documento y página, tarjeta de alarma, texto en vivo")


def test_cola_pregunta_antes_de_la_precarga():
    """Una pregunta o alarma que llega antes de que empiece la precarga de alarma se atiende primero; las tareas
    nunca corren a la vez (el modelo procesa una cosa a la vez)."""
    qt_util.app()
    import threading
    import time as _t
    from motorguard_dashboard.ui.asistente_servicio import ServicioAsistente
    with tempfile.TemporaryDirectory() as d:
        srv = ServicioAsistente(os.path.join(d, "a"), lambda: os.path.join(d, "docs"))
        orden, activos, maximo = [], [0], [0]
        candado = threading.Lock()
        soltar = threading.Event()

        def registrar(nombre, esperar=None):
            def f():
                with candado:
                    activos[0] += 1
                    maximo[0] = max(maximo[0], activos[0])
                if esperar:
                    esperar.wait(5)
                orden.append(nombre)
                with candado:
                    activos[0] -= 1
            return f
        srv._poner(registrar("en curso", soltar))          # ocupa el hilo de trabajo
        _t.sleep(0.2)
        pre = registrar("precarga")
        pre.es_precarga = True
        srv._poner(pre)
        srv._responder = lambda pregunta, ctx, alarma: registrar(f"pregunta {pregunta}")()
        srv.preguntar("A")
        srv.preguntar("B", alarma=True)
        soltar.set()
        assert _esperar(lambda: len(orden) == 4, 5), orden
        assert orden == ["en curso", "pregunta A", "pregunta B", "precarga"], orden
        assert maximo[0] == 1, "dos tareas corrieron a la vez"
        # Con el modelo externo, la pregunta no espera a la cola local (que puede estar precargando)
        soltar2 = threading.Event()
        srv._poner(registrar("precarga larga", soltar2))
        _t.sleep(0.2)
        srv.externo = object()
        assert srv.motivo_espera() is None
        srv.preguntar("C")
        assert _esperar(lambda: "pregunta C" in orden, 3), orden
        assert "precarga larga" not in orden
        srv.externo = None
        soltar2.set()
        srv._cerrado = True
        srv._cola_ext.put(None)
        srv._cola.put(None)
    print("  cola: las preguntas y alarmas van antes de la precarga pendiente; nunca dos tareas a la vez")


def test_tarjeta_modelo_logo_y_esfuerzo():
    """Tarjeta Modelo: logotipo y nombre del modelo que responde; esfuerzo de Claude elegible y enviado a la API;
    el pie de cada respuesta lleva el logotipo y el nombre legible."""
    app = qt_util.app()
    import tempfile as tf
    from PySide6.QtCore import QSettings
    from motorguard_dashboard.rag.asistente import Respuesta
    from motorguard_dashboard.sistema import claves
    from motorguard_dashboard.ui import asistente_tab as mod_tab
    from motorguard_dashboard.ui.conversacion import pie_respuesta
    from motorguard_dashboard.ui.tema import GestorTema
    original = claves._llavero
    claves._llavero = lambda: None
    try:
        conf = QSettings(os.path.join(tf.mkdtemp(), "a.ini"), QSettings.IniFormat)
        conf.setValue(mod_tab.CLAVE_EXT_URL, "https://api.anthropic.com/v1")
        conf.setValue(mod_tab.CLAVE_EXT_MODELO, "claude-sonnet-5-5")
        conf.setValue(mod_tab.CLAVE_EXT_ACEPTADO + "/api.anthropic.com", True)
        tema = GestorTema(app, persistir=False, modo="oscuro")
        w = mod_tab.AsistenteTab(tema=tema, conf=conf)
        w.aplicar_tema(tema.t)
        w.show()
        app.processEvents()
        assert w.lbl_nombre_modelo.text().startswith("Qwen3.5") and "Local" in w.lbl_externo.text()
        assert not w.caja_esfuerzo.isVisible() and not w.lbl_logo.pixmap().isNull()
        w._elegir_proveedor("externo")
        app.processEvents()
        assert w.lbl_nombre_modelo.text() == "Claude Sonnet 5.5" and "Anthropic" in w.lbl_externo.text()
        assert w.caja_esfuerzo.isVisible() and w._cliente_externo().esfuerzo == "low"
        w.sel_esfuerzo.botones["high"].click()
        assert conf.value(mod_tab.CLAVE_EXT_ESFUERZO) == "high" and w._cliente_externo().esfuerzo == "high"
        r = Respuesta("p", "x", [], modelo="claude-sonnet-5-5 (externo)", t_total=12)
        assert pie_respuesta(r).startswith("Claude Sonnet 5.5 (externo)")
        w._entradas = [{"pregunta": "p", "alarma": False, "texto": "", "r": r, "hora": "x"}]
        w._render()
        assert "<img" in w.conversacion._mensajes[0].pie.text()
        w.close()
    finally:
        claves._llavero = original
    print("  tarjeta Modelo: logotipo y nombre (Qwen local / Claude externo), esfuerzo elegible, logo en el pie")


def test_precarga_opcional():
    """La precarga de alarma se omite si el usuario la desactiva (demostraciones) o si responde el modelo externo, y
    se hace al reactivarla o al volver al modelo local."""
    qt_util.app()
    from motorguard_dashboard.ui import asistente_servicio as mod_as
    with tempfile.TemporaryDirectory() as d:
        srv = mod_as.ServicioAsistente(os.path.join(d, "a"), lambda: os.path.join(d, "docs"))
        hechas = []
        srv._precalentar = lambda: hechas.append(1) or True
        estados = []
        srv.sig_estado.connect(lambda e, t: estados.append(t))
        srv.estado, srv.indice, srv._listo = mod_as.LISTO, object(), "Listo · prueba"
        srv.precargar = False
        srv.precargar_si_conviene()
        assert not srv._precarga_encolada and "precarga desactivada" in estados[-1]
        srv.precargar, srv.externo = True, object()
        srv.precargar_si_conviene()
        assert not srv._precarga_encolada and "modelo externo" in estados[-1]
        srv.externo = None                                  # vuelve el modelo local: ahora sí
        srv.precargar_si_conviene()
        assert _esperar(lambda: srv.precargada, 3) and hechas == [1]
        srv.precargar_si_conviene()                         # ya hecha: no se repite
        assert hechas == [1]
        srv._cerrado = True
        srv._cola.put(None)
        srv._cola_ext.put(None)
    print("  precarga de alarma: se omite si está desactivada o con el modelo externo; se hace al reactivarla")


def run():
    test_asistente_con_llama_falso()
    test_servicio_sin_preparar()
    test_conversacion_estilo_chat()
    test_cola_pregunta_antes_de_la_precarga()
    test_tarjeta_modelo_logo_y_esfuerzo()
    test_precarga_opcional()
    print("✓ Sección Asistente con llama-server falso: 6/6 pruebas")


if __name__ == "__main__":
    run()
