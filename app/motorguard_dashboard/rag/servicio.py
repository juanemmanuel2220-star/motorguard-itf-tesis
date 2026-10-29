"""
Motor local del asistente: llama.cpp (llama-server) como procesos hijos de la app.

- Dos procesos en puertos libres de 127.0.0.1: uno con el LLM (Qwen3.5) y otro con los embeddings.
- Con prioridad baja (nice 10) y 4 hilos (los núcleos físicos del Ryzen 7 3700U rindieron mejor que 6 u 8),
  para que la interfaz y el hilo del puerto serie no se queden sin CPU.
- Nunca se usa un servidor ya existente ni un puerto fijo; los procesos se detienen al cerrar la app
  (terminate y, si no responde, kill) y también al salir el intérprete (atexit).
"""

import atexit
import os
import socket
import subprocess
import sys
import time
import urllib.request
from typing import List, Optional

from motorguard_dashboard.rag import catalogo
from motorguard_dashboard.rag.proveedores import ClienteOpenAI

HILOS = 4
CONTEXTO_LLM = 4096          # por slot
SLOTS_LLM = 2                # 0: preguntas libres; 1: alarmas (el prefijo de la consulta de alarma queda en caché)
SLOT_ALARMA = 1
NICE = 10
_VIVOS: List["ProcesoLlama"] = []


def dir_runtime_paquete() -> str:
    return "/usr/lib/motorguard-itf/llama"


def buscar_llama_server(dir_asistente: str) -> Optional[str]:
    for carpeta in (os.path.join(dir_asistente, "llama"), dir_runtime_paquete()):
        ruta = os.path.join(carpeta, "llama-server")
        if os.path.isfile(ruta) and os.access(ruta, os.X_OK):
            return ruta
    return None


def puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ProcesoLlama:
    def __init__(self, binario: str, modelo: str, args: List[str], nombre: str, log: Optional[str] = None,
                 paralelo: int = 1):
        self.binario = binario
        self.modelo = modelo
        self.args = args
        self.nombre = nombre
        self.log = log
        self.paralelo = paralelo
        self.puerto: Optional[int] = None
        self.proc: Optional[subprocess.Popen] = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.puerto}"

    def iniciar(self):
        self.puerto = puerto_libre()
        cmd = [self.binario, "-m", self.modelo, "--host", "127.0.0.1", "--port", str(self.puerto),
               "-t", str(HILOS), "--parallel", str(self.paralelo), "--no-webui"] + self.args
        entorno = dict(os.environ, LD_LIBRARY_PATH=os.path.dirname(self.binario))
        salida = open(self.log, "ab") if self.log else subprocess.DEVNULL
        extra = {}
        if sys.platform != "win32":
            extra["preexec_fn"] = lambda: os.nice(NICE)
        self.proc = subprocess.Popen(cmd, stdout=salida, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     env=entorno, cwd=os.path.dirname(self.binario), **extra)
        if self.log:
            salida.close()
        _VIVOS.append(self)

    def vivo(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def listo(self) -> bool:
        if not self.vivo():
            return False
        try:
            with urllib.request.urlopen(self.url + "/health", timeout=2) as r:
                return r.status == 200
        except Exception:                                        # noqa: BLE001 (todavía cargando)
            return False

    def esperar(self, limite_s: float = 120.0, cancelado=lambda: False) -> bool:
        t0 = time.monotonic()
        while time.monotonic() - t0 < limite_s and not cancelado():
            if self.listo():
                return True
            if not self.vivo():
                return False
            time.sleep(0.3)
        return False

    def detener(self):
        p, self.proc = self.proc, None
        if p is not None and p.poll() is None:
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(5)
        if self in _VIVOS:
            _VIVOS.remove(self)


@atexit.register
def _detener_todos():
    for p in list(_VIVOS):
        p.detener()


class MotorLocal:
    """Los dos llama-server del asistente y sus clientes."""

    def __init__(self, dir_asistente: str, modelo_llm: catalogo.Recurso = catalogo.MODELO_LLM):
        self.dir = dir_asistente
        self.rec_llm = modelo_llm
        self.llm: Optional[ProcesoLlama] = None
        self.emb: Optional[ProcesoLlama] = None

    def ruta_modelo(self, rec: catalogo.Recurso) -> str:
        return os.path.join(self.dir, "modelos", rec.archivo)

    def faltantes(self) -> List[str]:
        f = []
        if not buscar_llama_server(self.dir):
            f.append("motor llama.cpp")
        for rec in (self.rec_llm, catalogo.MODELO_EMB):
            if not os.path.isfile(self.ruta_modelo(rec)):
                f.append(rec.titulo)
        return f

    def iniciar(self, con_llm: bool = True, con_emb: bool = True):
        binario = buscar_llama_server(self.dir)
        if not binario:
            raise FileNotFoundError("no está el motor llama.cpp (Preparar asistente)")
        logs = os.path.join(self.dir, "logs")
        os.makedirs(logs, exist_ok=True)
        if con_emb and not (self.emb and self.emb.vivo()):
            self.emb = ProcesoLlama(binario, self.ruta_modelo(catalogo.MODELO_EMB),
                                    ["--embedding", "-c", "8192", "-b", "2048", "-ub", "2048"], "embeddings",
                                    os.path.join(logs, "llama_embeddings.log"))
            self.emb.iniciar()
        if con_llm and not (self.llm and self.llm.vivo()):
            self.llm = ProcesoLlama(binario, self.ruta_modelo(self.rec_llm),
                                    ["-c", str(CONTEXTO_LLM * SLOTS_LLM), "--jinja", "--reasoning", "off"], "llm",
                                    os.path.join(logs, "llama_llm.log"), paralelo=SLOTS_LLM)
            self.llm.iniciar()

    def esperar(self, limite_s: float = 180.0, cancelado=lambda: False) -> bool:
        return all(p.esperar(limite_s, cancelado) for p in (self.emb, self.llm) if p is not None)

    def detener(self):
        for p in (self.llm, self.emb):
            if p is not None:
                p.detener()

    def cliente_llm(self) -> ClienteOpenAI:
        return ClienteOpenAI(self.llm.url + "/v1", self.rec_llm.titulo, timeout=900,
                             extra_chat={"chat_template_kwargs": {"enable_thinking": False}, "cache_prompt": True},
                             nombre=f"{self.rec_llm.titulo} (local)", slot_alarma=SLOT_ALARMA)

    def cliente_emb(self) -> ClienteOpenAI:
        return ClienteOpenAI(self.emb.url + "/v1", catalogo.MODELO_EMB.titulo, timeout=300)
