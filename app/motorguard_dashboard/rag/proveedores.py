"""
Cliente de API de chat (sin dependencias: urllib). Lo usan el modelo local (llama-server) y los proveedores
externos opcionales que elija el usuario. Dos protocolos cubren cualquier proveedor:

- "openai": /chat/completions compatible con OpenAI (OpenAI, DeepSeek, Gemini, Mistral, OpenRouter, Qwen,
  Azure OpenAI v1, Ollama, LM Studio, vLLM, llama-server…).
- "anthropic": /messages nativo de Anthropic. Su capa compatible con OpenAI es, según Anthropic, para pruebas y
  no para producción, así que la app usa la API nativa.

- chat(): con streaming (SSE); se puede cancelar entre trozos.
- modelos(): /models (para elegir el modelo del proveedor; las dos API devuelven data[].id).
- embeddings(): /embeddings (solo el servidor local de embeddings).
- Clave: "Authorization: Bearer"; en Azure (*.azure.com), la cabecera "api-key"; en Anthropic, "x-api-key".

La clave de API nunca se escribe en registros ni se devuelve en mensajes de error (_sin_clave).
"""

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import numpy as np

# Presets de proveedores externos (el usuario puede editar la URL y elegir cualquier modelo)
PRESETS = {
    "DeepSeek": "https://api.deepseek.com/v1",
    "Qwen (Alibaba Cloud)": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "OpenRouter": "https://openrouter.ai/api/v1",
    "Google Gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "Mistral": "https://api.mistral.ai/v1",
    "OpenAI": "https://api.openai.com/v1",
    "Anthropic": "https://api.anthropic.com/v1",
    "URL personalizada": "",
}
MAX_TOKENS_ANTHROPIC = 4096      # incluye el razonamiento interno (adaptive thinking) de los modelos actuales
# Esfuerzo de razonamiento de Claude: la respuesta del asistente es corta y se apoya en fragmentos ya dados, así que
# "low" (recomendado para chat) responde más rápido y gasta menos que el predeterminado ("high" en Sonnet 5.5)
ESFUERZO_ANTHROPIC = "low"
PROTOCOLOS = {"openai": "Compatible con OpenAI (/chat/completions)", "anthropic": "Anthropic nativo (/messages)"}


def protocolo_de_url(url: str) -> str:
    """Protocolo por omisión según el proveedor (el usuario puede cambiarlo en la URL personalizada)."""
    return "anthropic" if "anthropic.com" in url else "openai"


class ErrorProveedor(Exception):
    pass


@dataclass
class ResultadoChat:
    texto: str
    modelo: str
    t_primer_token: Optional[float]
    t_total: float
    tokens_prompt: Optional[int] = None
    tokens_respuesta: Optional[int] = None
    cancelado: bool = False
    extra: dict = field(default_factory=dict)


class ClienteOpenAI:
    def __init__(self, base_url: str, modelo: str = "", clave: Optional[str] = None,
                 extra_chat: Optional[dict] = None, timeout: float = 60.0, nombre: str = "",
                 slot_alarma: Optional[int] = None, protocolo: Optional[str] = None,
                 esfuerzo: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.protocolo = protocolo or protocolo_de_url(self.base_url)
        self.esfuerzo = esfuerzo                     # Claude: output_config.effort (None = ESFUERZO_ANTHROPIC)
        if self.protocolo not in PROTOCOLOS:
            raise ValueError(f"protocolo desconocido: {self.protocolo}")
        self.modelo = modelo
        self._clave = clave
        self.extra_chat = extra_chat or {}
        self.timeout = timeout
        self.nombre = nombre or modelo
        # llama-server local: slot reservado para las consultas de alarma (su prefijo queda en caché)
        self.slot_alarma = slot_alarma

    def _sin_clave(self, texto: str) -> str:
        return texto.replace(self._clave, "***") if self._clave else texto

    def _cabeceras(self) -> dict:
        cab = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.protocolo == "anthropic":
            cab["anthropic-version"] = "2023-06-01"
            if self._clave:
                cab["x-api-key"] = self._clave
        elif self._clave:
            if ".azure.com" in self.base_url:
                cab["api-key"] = self._clave
            else:
                cab["Authorization"] = f"Bearer {self._clave}"
        return cab

    def _peticion(self, ruta: str, cuerpo: Optional[dict] = None):
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        req = urllib.request.Request(self.base_url + ruta, data=datos, headers=self._cabeceras(),
                                     method="POST" if datos is not None else "GET")
        try:
            return urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            try:
                detalle = e.read().decode("utf-8", "replace")[:300]
            except Exception:                                    # noqa: BLE001
                detalle = ""
            raise ErrorProveedor(self._sin_clave(f"HTTP {e.code}: {detalle}")) from None
        except Exception as e:                                   # noqa: BLE001 (red, DNS, tiempo agotado)
            raise ErrorProveedor(self._sin_clave(str(e))) from None

    def modelos(self) -> List[str]:
        # Anthropic pagina la lista (20 por omisión)
        with self._peticion("/models?limit=1000" if self.protocolo == "anthropic" else "/models") as r:
            d = json.load(r)
        return sorted(m.get("id", "") for m in d.get("data", []) if m.get("id"))

    def chat(self, mensajes: List[dict], max_tokens: int = 700, temperatura: Optional[float] = 0.2,
             al_token: Optional[Callable[[str], None]] = None,
             cancelado: Callable[[], bool] = lambda: False, extra: Optional[dict] = None) -> ResultadoChat:
        esfuerzo = (self.esfuerzo or ESFUERZO_ANTHROPIC) if self.protocolo == "anthropic" else None
        for _ in range(3):
            try:
                return self._chat(mensajes, max_tokens, temperatura, al_token, cancelado, extra, esfuerzo)
            except ErrorProveedor as e:
                # Parámetros opcionales que algunos modelos no aceptan: se reintenta sin el que se rechazó
                m = str(e)
                if "HTTP 400" in m and temperatura is not None and "temperature" in m:
                    temperatura = None
                elif "HTTP 400" in m and esfuerzo is not None and ("effort" in m or "output_config" in m):
                    esfuerzo = None
                else:
                    raise
        return self._chat(mensajes, max_tokens, temperatura, al_token, cancelado, extra, esfuerzo)

    def _chat(self, mensajes, max_tokens, temperatura, al_token, cancelado, extra, esfuerzo=None) -> ResultadoChat:
        anthropic = self.protocolo == "anthropic"
        cuerpo = {"model": self.modelo or "local", "max_tokens": max_tokens, "stream": True}
        if anthropic:
            # Los modelos actuales de Claude rechazan temperature/top_p/top_k (400 en Sonnet 5.5, Opus 5.5, Fable…;
            # banco, 13-oct) y su razonamiento interno cuenta contra max_tokens: se deja espacio para la respuesta
            temperatura = None
            cuerpo["max_tokens"] = max(max_tokens, MAX_TOKENS_ANTHROPIC)
            if esfuerzo:
                cuerpo["output_config"] = {"effort": esfuerzo}
        if temperatura is not None:
            cuerpo["temperature"] = temperatura
        if anthropic:
            # La API nativa lleva el mensaje de sistema aparte
            cuerpo["system"] = "\n".join(m["content"] for m in mensajes if m["role"] == "system")
            cuerpo["messages"] = [m for m in mensajes if m["role"] != "system"]
        else:
            cuerpo["messages"] = mensajes
        cuerpo.update(self.extra_chat)
        cuerpo.update(extra or {})
        t0 = time.monotonic()
        t1 = None
        partes: List[str] = []
        uso: dict = {}
        tiempos: dict = {}
        cancel = False
        with self._peticion("/messages" if anthropic else "/chat/completions", cuerpo) as r:
            for linea in r:
                if cancelado():
                    cancel = True
                    break
                linea = linea.decode("utf-8", "replace").strip()
                if not linea.startswith("data:"):
                    continue
                dato = linea[5:].strip()
                if dato == "[DONE]":
                    break
                try:
                    d = json.loads(dato)
                except ValueError:
                    continue
                if anthropic:
                    trozos = self._anthropic_evento(d, uso)
                else:
                    if d.get("usage"):
                        uso = d["usage"]
                    if d.get("timings"):
                        tiempos = d["timings"]
                    trozos = [(c.get("delta") or {}).get("content") or "" for c in d.get("choices") or []]
                for trozo in trozos:
                    if trozo:
                        if t1 is None:
                            t1 = time.monotonic() - t0
                        partes.append(trozo)
                        if al_token:
                            al_token(trozo)
        return ResultadoChat("".join(partes), self.nombre, t1, time.monotonic() - t0,
                             uso.get("prompt_tokens") or uso.get("input_tokens") or tiempos.get("prompt_n"),
                             uso.get("completion_tokens") or uso.get("output_tokens") or tiempos.get("predicted_n"),
                             cancel, {"timings": tiempos} if tiempos else {})

    def _anthropic_evento(self, d: dict, uso: dict) -> List[str]:
        """Un evento SSE de /messages: devuelve el texto nuevo y acumula el uso de tokens en `uso`."""
        tipo = d.get("type")
        if tipo == "error":
            raise ErrorProveedor(self._sin_clave(str(d.get("error", d))[:300]))
        if tipo == "message_start":
            uso.update((d.get("message") or {}).get("usage") or {})
        elif tipo == "message_delta":
            uso.update(d.get("usage") or {})
            if (d.get("delta") or {}).get("stop_reason") == "refusal":
                # El modelo declinó la petición: se informa como falla para que responda el modelo local
                det = (d.get("delta") or {}).get("stop_details") or d.get("stop_details") or {}
                raise ErrorProveedor(f"el modelo rechazó la petición (refusal{', ' + str(det.get('category')) if det.get('category') else ''})")
        elif tipo == "content_block_delta" and (d.get("delta") or {}).get("type") == "text_delta":
            return [d["delta"].get("text") or ""]
        return []

    def llama(self, ruta: str, cuerpo: dict) -> dict:
        """Endpoints propios de llama-server en la raíz (/apply-template, /tokenize, /completion); solo local."""
        raiz = self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url
        cab = {"Content-Type": "application/json"}
        req = urllib.request.Request(raiz + ruta, data=json.dumps(cuerpo).encode(), headers=cab, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.load(r)
        except Exception as e:                                   # noqa: BLE001
            raise ErrorProveedor(self._sin_clave(str(e))) from None

    def embeddings(self, textos: List[str]) -> np.ndarray:
        with self._peticion("/embeddings", {"input": textos, "model": self.modelo or "local"}) as r:
            d = json.load(r)
        datos = sorted(d["data"], key=lambda x: x.get("index", 0))
        return np.array([x["embedding"] for x in datos], dtype=np.float32)
