"""
Logotipo y nombre legible del modelo de lenguaje que responde (sección Asistente).

Los logotipos son los SVG de Simple Icons (CC0) en ui/recursos/marcas/ (ver LEEME.md: las marcas son de sus
dueños y solo identifican al proveedor). Se dibujan en el color de la marca; si ese color casi no contrasta con el
fondo del tema (Ollama es negro), en el color del texto.
"""

import os
import re
import tempfile
from typing import Optional

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

DIR_MARCAS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recursos", "marcas")

# clave: (proveedor, color de marca)
MARCAS = {
    "claude": ("Anthropic", "#D97757"),
    "qwen": ("Qwen", "#6950EF"),
    "googlegemini": ("Google", "#8E75B2"),
    "mistralai": ("Mistral AI", "#FA520F"),
    "deepseek": ("DeepSeek", "#5786FE"),
    "openrouter": ("OpenRouter", "#94A3B8"),
    "ollama": ("Ollama", "#000000"),
}
_POR_URL = (("anthropic.com", "claude"), ("generativelanguage.googleapis", "googlegemini"), ("mistral.ai", "mistralai"),
            ("deepseek.com", "deepseek"), ("openrouter.ai", "openrouter"), ("dashscope", "qwen"), ("aliyuncs", "qwen"),
            (":11434", "ollama"))
_POR_MODELO = (("claude", "claude"), ("qwen", "qwen"), ("qwq", "qwen"), ("gemini", "googlegemini"),
               ("mistral", "mistralai"), ("magistral", "mistralai"), ("codestral", "mistralai"),
               ("deepseek", "deepseek"))
_SIGLAS = {"gpt": "GPT", "ai": "AI", "llm": "LLM", "deepseek": "DeepSeek", "qwen": "Qwen", "chatgpt": "ChatGPT"}


def marca(modelo: str = "", url: str = "") -> Optional[str]:
    """Logotipo por el nombre del modelo (lo que responde) y, si no, por el proveedor de la URL."""
    m = (modelo or "").lower()
    for clave, slug in _POR_MODELO:
        if clave in m:
            return slug
    u = (url or "").lower()
    for clave, slug in _POR_URL:
        if clave in u:
            return slug
    return None


def proveedor(url: str) -> str:
    slug = next((s for c, s in _POR_URL if c in (url or "").lower()), None)
    if slug:
        return MARCAS[slug][0]
    from urllib.parse import urlparse
    return urlparse(url).netloc or "API externa"


def nombre_modelo(ident: str) -> str:
    """'claude-sonnet-5-5' -> 'Claude Sonnet 5.5'; 'claude-opus-4-5-20251101' -> 'Claude Opus 4.5'. Lo que no
    reconoce lo deja igual (p. ej. 'Qwen3.5-4B')."""
    base = ident.split("/")[-1]                                   # OpenRouter: 'anthropic/claude-…'
    if not re.fullmatch(r"[a-z0-9.\-]+", base):
        return ident
    base = re.sub(r"-\d{8}$", "", base)                           # sin la fecha de la versión
    partes, salida = base.split("-"), []
    for p in partes:
        if p.isdigit() and salida and re.fullmatch(r"\d+(\.\d+)*", salida[-1]):
            salida[-1] += "." + p                                 # 5-5 -> 5.5
        elif salida and salida[-1] == "GPT" and p[:1].isdigit():
            salida[-1] += "-" + p                                 # gpt-6 -> GPT-6
        else:
            salida.append(_SIGLAS.get(p, p if p[:1].isdigit() else p.capitalize()))
    return " ".join(salida)


def _contraste_bajo(hexa: str, fondo: str) -> bool:
    def lum(h):
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
        f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
    a, b = sorted((lum(hexa), lum(fondo)), reverse=True)
    return (a + 0.05) / (b + 0.05) < 2.0


def color(slug: str, t: dict) -> str:
    c = MARCAS[slug][1]
    return t.get("on", "#191C21") if _contraste_bajo(c, t.get("surface2", "#F0F2F8")) else c


def pixmap(slug: str, col: str, tam: int = 24) -> QPixmap:
    with open(os.path.join(DIR_MARCAS, f"{slug}.svg"), encoding="utf-8") as fh:
        svg = fh.read().replace("<svg ", f'<svg fill="{col}" ', 1)
    ren = QSvgRenderer(QByteArray(svg.encode()))
    escala = 3
    pm = QPixmap(tam * escala, tam * escala)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    ren.render(p)
    p.end()
    pm.setDevicePixelRatio(escala)
    return pm


def ruta_png(slug: str, col: str, tam: int = 16) -> str:
    """El logotipo como PNG temporal, para el texto enriquecido (<img>) del pie de cada respuesta."""
    ruta = os.path.join(tempfile.gettempdir(), f"motorguard-itf-marca-{slug}-{col.lstrip('#').lower()}-{tam}.png")
    if not os.path.exists(ruta):
        pm = pixmap(slug, col, tam)
        pm.setDevicePixelRatio(1)
        pm.save(ruta)
    return ruta
