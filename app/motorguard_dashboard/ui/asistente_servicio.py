"""
Servicio del asistente para la interfaz: un hilo de trabajo que arranca el motor local (llama-server),
carga o construye el índice, descarga lo que falte ("Preparar asistente") y responde preguntas.

- Una sola tarea a la vez; las consultas automáticas por alarma pendientes se reemplazan por la más nueva.
- Todo lo pesado ocurre fuera del hilo de la interfaz; las señales Qt llegan a la interfaz en su hilo.
- Al cerrar, se cancela lo que esté en curso y se detienen los procesos llama-server.
"""

import os
import queue
import threading
import time
from typing import Callable, List, Optional

from PySide6.QtCore import QObject, Signal

from motorguard_dashboard.rag import biblioteca, catalogo
from motorguard_dashboard.rag.asistente import Asistente, ContextoAlarma, pregunta_alarma
from motorguard_dashboard.rag.indice import UMBRAL_ABSTENCION
from motorguard_dashboard.rag.descargas import ErrorDescarga, descargar, extraer_runtime
from motorguard_dashboard.rag.proveedores import ClienteOpenAI, ErrorProveedor
from motorguard_dashboard.rag.servicio import MotorLocal, buscar_llama_server
from motorguard_dashboard.sistema import bitacora

APAGADO, ARRANCANDO, INDEXANDO, LISTO, FALTA, ERROR, PREPARANDO = (
    "apagado", "arrancando", "indexando", "listo", "falta", "error", "preparando")


class ServicioAsistente(QObject):
    sig_estado = Signal(str, str)              # (estado, texto)
    sig_progreso = Signal(str, int, int)       # (etapa, n, total)
    sig_token = Signal(str)
    sig_inicio_respuesta = Signal(str, bool)   # (pregunta, alarma)
    sig_respuesta = Signal(object)             # rag.asistente.Respuesta
    sig_documentos = Signal(object)            # List[biblioteca.EstadoDoc]

    def __init__(self, dir_asistente: str, carpeta_docs: Callable[[], str],
                 modelo_llm: catalogo.Recurso = catalogo.MODELO_LLM, parent=None):
        super().__init__(parent)
        self.dir = dir_asistente
        self._carpeta_docs = carpeta_docs
        self.motor = MotorLocal(dir_asistente, modelo_llm)
        self.indice = None
        self.externo: Optional[ClienteOpenAI] = None
        self.umbral = UMBRAL_ABSTENCION
        self.estado = APAGADO
        self._cola: "queue.Queue" = queue.Queue()
        self._cancelar = threading.Event()
        self._cerrado = False
        self._ocupados = 0
        self._candado = threading.Lock()
        self._ext_ocupado = False
        self.precargando = False
        self.precargada = False
        self.precargar = True                    # el usuario puede desactivarla (demostraciones rápidas)
        self._precarga_encolada = False
        self._listo = ""
        # Dos colas: la del modelo local (precarga, preguntas y alarmas locales; una cosa a la vez) y la del modelo
        # externo, que no usa el CPU y no debe esperar a la precarga local (13-oct: la pregunta a Claude quedaba
        # en cola 2–3 min detrás de la precarga de alarma del modelo local)
        self._cola_ext: "queue.Queue" = queue.Queue()
        self._hilo = threading.Thread(target=self._bucle, args=(self._cola,), name="asistente", daemon=True)
        self._hilo.start()
        self._hilo_ext = threading.Thread(target=self._bucle, args=(self._cola_ext,), name="asistente-externo",
                                          daemon=True)
        self._hilo_ext.start()

    # ---------------------------------------------------------------- API (hilo de la interfaz)
    @property
    def listo(self) -> bool:
        return self.estado == LISTO

    @property
    def ocupado(self) -> bool:
        return self._ocupados > 0

    def motivo_espera(self) -> Optional[str]:
        """Por qué una pregunta nueva no empezaría de inmediato (None si empieza ya)."""
        if self.externo is not None:
            return "se responde al terminar la respuesta en curso." if self._cola_ext.qsize() or self._ext_ocupado \
                else None
        if self.precargando:
            return "el asistente termina de precargar la consulta de alarma (unos 2–3 min) y luego responde."
        return "se responde al terminar la respuesta en curso." if self.ocupado else None

    def faltantes(self) -> List[str]:
        f = self.motor.faltantes()
        if not any(e.estado != "falta" for e in biblioteca.estado_documentos(self._carpeta_docs())):
            f.append("documentos")
        return f

    def documentos(self):
        return biblioteca.estado_documentos(self._carpeta_docs())

    def iniciar(self):
        self._poner(self._iniciar)

    def preparar(self):
        self._poner(self._preparar)

    def cambiar_modelo(self, rec: catalogo.Recurso):
        def tarea():
            self.motor.detener()
            self.motor = MotorLocal(self.dir, rec)
            self._iniciar()
        self._poner(tarea)

    def preguntar(self, pregunta: str, ctx: Optional[ContextoAlarma] = None, alarma: bool = False):
        if alarma:
            # solo la alarma más reciente queda pendiente
            pendientes = []
            while True:
                try:
                    t = self._cola.get_nowait()
                except queue.Empty:
                    break
                if not getattr(t, "es_alarma", False):
                    pendientes.append(t)
            for t in pendientes:
                self._cola.put(t)

        def tarea():
            self._responder(pregunta, ctx, alarma)
        tarea.es_alarma = alarma
        if self.externo is not None:                     # el modelo externo no espera a la cola local
            if not self._cerrado:
                self._cola_ext.put(tarea)
            return
        # Antes de una precarga que todavía no empieza (el modelo procesa una cosa a la vez)
        pendientes = []
        while True:
            try:
                pendientes.append(self._cola.get_nowait())
            except queue.Empty:
                break
        precargas = [t for t in pendientes if getattr(t, "es_precarga", False)]
        for t in [t for t in pendientes if t is not None and not getattr(t, "es_precarga", False)] + [tarea] + precargas:
            self._poner(t)
        if None in pendientes:
            self._cola.put(None)                         # cierre en curso

    def cancelar(self):
        self._cancelar.set()

    def cerrar(self):
        self._cerrado = True
        self._cancelar.set()
        self._cola.put(None)
        self._cola_ext.put(None)
        self._hilo.join(timeout=3)
        self._hilo_ext.join(timeout=3)
        self.motor.detener()

    # ---------------------------------------------------------------- hilo de trabajo
    def _poner(self, tarea):
        if not self._cerrado:
            self._cola.put(tarea)

    def _bucle(self, cola):
        externo = cola is self._cola_ext
        while True:
            tarea = cola.get()
            if tarea is None or self._cerrado:
                return
            if not getattr(tarea, "es_precarga", False):
                self._cancelar.clear()
            with self._candado:
                self._ocupados += 1
            if externo:
                self._ext_ocupado = True
            try:
                tarea()
            except Exception as e:                               # noqa: BLE001 (se informa en la interfaz)
                bitacora.LOG.exception("Asistente: error en tarea")
                self._estado(ERROR, f"Error del asistente: {e}")
            finally:
                with self._candado:
                    self._ocupados -= 1
                if externo:
                    self._ext_ocupado = False

    def _estado(self, estado: str, texto: str):
        self.estado = estado
        if not self._cerrado:
            self.sig_estado.emit(estado, texto)

    def _iniciar(self):
        self.sig_documentos.emit(self.documentos())
        falta = self.faltantes()
        if falta:
            self._estado(FALTA, "Falta: " + ", ".join(falta) + ". Use «Preparar asistente».")
            return
        self._estado(ARRANCANDO, f"Arrancando el modelo local ({self.motor.rec_llm.titulo})…")
        self.motor.iniciar()
        if not self.motor.esperar(240, cancelado=lambda: self._cerrado):
            self._estado(ERROR, "El motor local no arrancó (ver asistente/logs/).")
            return
        self.indice = biblioteca.cargar_o_construir(self.dir, self._carpeta_docs())
        if self.indice is None:
            self._estado(INDEXANDO, "Indexando los documentos (una sola vez; puede tardar más de una hora)…")
            self.indice = biblioteca.cargar_o_construir(
                self.dir, self._carpeta_docs(), self.motor.cliente_emb().embeddings,
                lambda etapa, n, total: self.sig_progreso.emit(etapa, n, total),
                cancelado=lambda: self._cerrado)
        self.sig_documentos.emit(self.documentos())
        # Se puede preguntar en cuanto el modelo está cargado, pero el modelo procesa una cosa a la vez: la precarga
        # de la consulta de alarma (~2.5 min) es una tarea más de la cola, y las preguntas y alarmas que lleguen antes
        # de que empiece van primero (preguntar()). En el banco (13-oct) la precarga en un hilo aparte, a la vez que una
        # pregunta, bajó el procesamiento de ~14 a 3.4 y 1.5 tokens/s: la pregunta tardó 792 s.
        self.precargada = False
        self._listo = f"Listo · {self.motor.rec_llm.titulo} local · {len(self.indice)} fragmentos"
        self._estado(LISTO, self._listo)
        self.precargar_si_conviene()

    def precargar_si_conviene(self):
        """Encola la precarga de la consulta de alarma si hace falta: el modelo local está listo, no se hizo ya, el
        usuario no la desactivó (demostraciones rápidas) y responde el modelo local (con el externo, las alarmas las
        responde la API y precargar solo gastaría CPU). Se puede llamar desde la interfaz al cambiar esos ajustes."""
        if (self.estado != LISTO or self.indice is None or self.precargada or self.precargando
                or self._precarga_encolada or not self.precargar or self.externo is not None or self._cerrado):
            if self.estado == LISTO and not self.precargada and not self.precargando and not self._precarga_encolada:
                motivo = ("modelo externo activo" if self.externo is not None else
                          "precarga desactivada" if not self.precargar else None)
                if motivo:
                    self._estado(LISTO, self._listo + f" · sin precarga de alarma ({motivo})")
            return
        listo, motor = self._listo, self.motor
        self._precarga_encolada = True
        self._estado(LISTO, listo + " · precarga de la consulta de alarma pendiente")

        def precarga():
            self._precarga_encolada = False
            if self.motor is not motor or self._cerrado or not self.precargar or self.externo is not None:
                if self.motor is motor and self.estado == LISTO:
                    self._estado(LISTO, listo + " · sin precarga de alarma")
                return
            self.precargando = True
            self._estado(LISTO, listo + " · precargando la consulta de alarma (~2–3 min)…")
            t0 = time.monotonic()
            try:
                ok = self._precalentar()
            except Exception:                            # noqa: BLE001 (sin precarga, la alarma tarda más; no falla)
                bitacora.LOG.warning("Asistente: no se pudo precargar la consulta de alarma", exc_info=True)
                ok = False
            finally:
                self.precargando = False
            self.precargada = ok
            if ok:
                bitacora.LOG.info("Asistente: consulta de alarma precargada en %.0f s", time.monotonic() - t0)
            if self.motor is motor and self.estado == LISTO and not self._cerrado:
                self._estado(LISTO, listo if ok else listo + " · sin precarga de alarma")
        precarga.es_precarga = True
        self._poner(precarga)

    def _precalentar(self):
        """Carga en la caché del modelo el prompt de sistema (slot 0) y el prefijo de la consulta de alarma (slot 1),
        para que la respuesta a una alarma solo tenga que procesar los valores medidos y la pregunta."""
        from motorguard_dashboard.rag.asistente import SISTEMA
        try:
            llm = self.motor.cliente_llm()
            llm.chat([{"role": "system", "content": SISTEMA}, {"role": "user", "content": "Responde solo: listo"}],
                     max_tokens=2, cancelado=lambda: self._cerrado, extra={"id_slot": 0})
            return Asistente(self.indice, self.motor.cliente_emb(), llm).precalentar_alarma(lambda: self._cerrado) is not None
        except ErrorProveedor:
            bitacora.LOG.warning("Asistente: la precarga falló (el modelo no respondió)")
            return False

    def _preparar(self):
        self._estado(PREPARANDO, "Preparando el asistente…")

        def prog(nombre):
            return lambda n, total: self.sig_progreso.emit(f"Descargando {nombre}", n // 1_000_000,
                                                           (total or 0) // 1_000_000)
        cancel = self._cancelar.is_set
        try:
            if not buscar_llama_server(self.dir):
                carpeta = os.path.join(self.dir, "descargas")
                descargar(catalogo.RUNTIME, carpeta, prog("llama.cpp (MB)"), cancel)
                extraer_runtime(os.path.join(carpeta, catalogo.RUNTIME.archivo), os.path.join(self.dir, "llama"))
            for rec in (catalogo.MODELO_EMB, self.motor.rec_llm):
                if not os.path.isfile(self.motor.ruta_modelo(rec)):
                    descargar(rec, os.path.join(self.dir, "modelos"), prog(f"{rec.titulo} (MB)"), cancel)
            docs = self._carpeta_docs()
            for e in biblioteca.estado_documentos(docs):
                if e.estado == "falta" and e.rec.url:
                    try:
                        descargar(e.rec, docs, prog(f"{e.rec.titulo} (MB)"), cancel, estricto=False)
                    except ErrorDescarga as err:
                        bitacora.LOG.warning("Asistente: no se pudo descargar %s: %s", e.rec.titulo, err)
        except ErrorDescarga as e:
            self._estado(ERROR, f"No se pudo preparar: {e}")
            return
        self._iniciar()

    def _responder(self, pregunta: str, ctx: Optional[ContextoAlarma], alarma: bool):
        if self.estado != LISTO or self.indice is None:
            return
        local = self.motor.cliente_llm()
        llm = self.externo or local
        a = Asistente(self.indice, self.motor.cliente_emb(), llm, respaldo_llm=local if self.externo else None,
                      umbral=self.umbral)
        texto = pregunta_alarma(ctx) if alarma and ctx is not None else pregunta
        self.sig_inicio_respuesta.emit(texto, alarma)
        t0 = time.monotonic()
        r = a.responder(texto, ctx, alarma, al_token=self.sig_token.emit, cancelado=self._cancelar.is_set)
        bitacora.LOG.info("Asistente: respuesta en %.1f s (%s, alarma=%s, abstención=%s)",
                          time.monotonic() - t0, r.modelo or "-", alarma, r.abstencion)
        if not self._cerrado:
            self.sig_respuesta.emit(r)
