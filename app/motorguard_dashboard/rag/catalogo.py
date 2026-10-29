"""
Catálogo fijo de lo que necesita el asistente: motor de inferencia, modelos y documentos.

Todo se descarga de su fuente oficial y se verifica por SHA-256:
- llama.cpp (MIT): binario CPU oficial de ggml-org, build fijada (publicada el 27-sep-2026).
- Modelos Qwen (Apache 2.0) en GGUF: Qwen3.5-4B Q4_K_M de unsloth (derivado de los pesos oficiales
  Qwen/Qwen3.5-4B; decisión del autor del 12-oct), Qwen3-Embedding-0.6B oficial de Qwen y Qwen3.5-2B de respaldo.
- Documentos de uso legal (FUENTES.md en ~/tesis_itf/rag_docs): dominio público de EE. UU. (NASA, DOE,
  USBR), dos artículos CC BY 4.0 (Sensors, copia de PubMed Central), el extracto de resultados de la tesis (viene con la app, rag/datos/) y el manual de ABB (© ABB: uso local; cada usuario lo descarga de ABB, no se
  redistribuye ni va al paquete). Si la fuente oficial cambia el archivo, se conserva pero se marca como
  "versión distinta a la evaluada" (el SHA-256 de la evaluación de la tesis queda en FUENTES.md).

Páginas indexadas: solo los capítulos sobre programas de mantenimiento, técnicas predictivas, aislamiento y
motores. El resto de las guías trata de calderas, trampas de vapor, enfriadores, alumbrado, contratos, etc.,
y solo agregaría ruido a la búsqueda y horas de indexado en esta CPU (≈3 s por fragmento).
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Recurso:
    clave: str
    archivo: str
    url: str
    sha256: Optional[str]
    tam: Optional[int]
    licencia: str
    titulo: str = ""
    detalle: str = ""
    redistribuible: bool = True
    idiomas: tuple = ("en", "es")      # páginas que se indexan (el manual ABB trae 9 idiomas: solo el español)
    en_paquete: bool = False           # viene con la app (rag/datos/), no se descarga
    paginas: Optional[tuple] = None    # rangos de páginas del PDF que se indexan ((ini, fin), ...); None = todas


LLAMA_BUILD = "b11223"
RUNTIME = Recurso(
    "llama.cpp", f"llama-{LLAMA_BUILD}-bin-ubuntu-x64.tar.gz",
    f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_BUILD}/llama-{LLAMA_BUILD}-bin-ubuntu-x64.tar.gz",
    "9ce07ebd35ccdbae598ef34d21607564c4a21956cf075409f82e4f4fe871ea5e", 17404321, "MIT",
    "llama.cpp", f"build {LLAMA_BUILD} (27-sep-2026), CPU")

_HF = "https://huggingface.co/{repo}/resolve/{rev}/{archivo}"

MODELO_LLM = Recurso(
    "qwen3.5-4b", "Qwen3.5-4B-Q4_K_M.gguf",
    _HF.format(repo="unsloth/Qwen3.5-4B-GGUF", rev="e87f176479d0855a907a41277aca2f8ee7a09523",
               archivo="Qwen3.5-4B-Q4_K_M.gguf"),
    "00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4", 2740937888, "Apache-2.0",
    "Qwen3.5-4B", "Q4_K_M · unsloth/Qwen3.5-4B-GGUF (de Qwen/Qwen3.5-4B)")
MODELO_LLM_RESPALDO = Recurso(
    "qwen3.5-2b", "Qwen3.5-2B-Q4_K_M.gguf",
    _HF.format(repo="unsloth/Qwen3.5-2B-GGUF", rev="f6d5376be1edb4d416d56da11e5397a961aca8ae",
               archivo="Qwen3.5-2B-Q4_K_M.gguf"),
    "aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223", 1280835840, "Apache-2.0",
    "Qwen3.5-2B", "Q4_K_M · unsloth/Qwen3.5-2B-GGUF (de Qwen/Qwen3.5-2B)")
MODELO_EMB = Recurso(
    "qwen3-embedding-0.6b", "Qwen3-Embedding-0.6B-Q8_0.gguf",
    _HF.format(repo="Qwen/Qwen3-Embedding-0.6B-GGUF", rev="370f27d7550e0def9b39c1f16d3fbaa13aa67728",
               archivo="Qwen3-Embedding-0.6B-Q8_0.gguf"),
    "06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439", 639150592, "Apache-2.0",
    "Qwen3-Embedding-0.6B", "Q8_0 · GGUF oficial de Qwen")

MODELOS_LLM = (MODELO_LLM, MODELO_LLM_RESPALDO)

_PD = "Dominio público (gobierno de EE. UU.)"
_USBR = "https://www.usbr.gov/power/data/fist/"
_PMC = "https://pmc-oa-opendata.s3.amazonaws.com/"
_CCBY = "CC BY 4.0"
DOCUMENTOS = (
    Recurso("abb", "ABB_3GZF500730-85_RevH.pdf",
            "https://search.abb.com/library/Download.aspx?DocumentID=3GZF500730-85&LanguageCode=en"
            "&DocumentPartId=&Action=Launch",
            "39807d7552ae98b16776600c0c3114b879158fd9a35dbe804ddcda2f1e655ce7", 5488716,
            "© ABB · solo uso local; no se redistribuye",
            "Manual de motores de baja tensión ABB", "3GZF500730-85 Rev H (05-2022) · sección en español",
            redistribuible=False, idiomas=("es",)),
    Recurso("nasa_rcm", "NASA_RCM_Guide_2008.pdf",
            "https://www.nasa.gov/wp-content/uploads/2023/06/nasa-rcmguide.pdf",
            "2d5752842bccfac479d8bd7e621db0c40701082a6cd4e042c53aabe9166da64b", 4443946, _PD,
            "NASA · Reliability-Centered Maintenance Guide", "septiembre de 2008 · caps. 5–7 (programa RCM, "
            "técnicas y criterios de pruebas predictivas)", paginas=((47, 136),)),
    Recurso("femp_om", "FEMP_OM_Best_Practices_R3.pdf",
            "https://www.energy.gov/sites/default/files/2020/04/f74/omguide_complete_w-eo-disclaimer.pdf",
            "9cf0adbc462c73b7ec20f97b21643ba709c2c7c4571ff6630a2d628d78e3147c", 8562032, _PD,
            "DOE/FEMP · O&M Best Practices Guide R3.0", "agosto de 2010 · caps. 5–6 (tipos de mantenimiento, "
            "técnicas predictivas) y 9.10 (motores)", paginas=((49, 94), (233, 243))),
    Recurso("usbr_3_1", "USBR_FIST_3-1.pdf", _USBR + "fist3_1/vol3-1.pdf",
            "40b3db57a6e30fc2be5772dcbc14a29a1bcec26fc31ca3ac2b36f3daca3c26ff", 2883753, _PD,
            "USBR · FIST 3-1", "Testing Solid Insulation of Electrical Equipment (1991)"),
    Recurso("usbr_3_4", "USBR_FIST_3-4.pdf", _USBR + "fist3_4/vol3-4.pdf",
            "9a8e23d4510faf88e3c1f0ad41c556459f9722bdf561ec11831d8281d73db741", 246362, _PD,
            "USBR · FIST 3-4", "Keeping Motor Windings Dry (1991)"),
    Recurso("usbr_4_1b", "USBR_FIST_4-1B.pdf", _USBR + "FIST_4-1B_%2801-2026%29.pdf",
            "94dfd4ec006b9856793cbfa0ccc2d2a0412587e9abad129f13e6603b7ec1fb13", 1221355, _PD,
            "USBR · FIST 4-1B", "Maintenance Scheduling for Electrical Equipment (enero de 2026) · "
            "secs. 1, 21 y 23 (motores)", paginas=((11, 14), (87, 93))),
    # MDPI rechaza descargas automáticas (HTTP 403): se usa la copia de PubMed Central (Open Access, PMC Cloud)
    Recurso("ruzimov2025", "Ruzimov2025_Sensors_25_4844.pdf", _PMC + "PMC12349302.1/PMC12349302.1.pdf",
            "811559a32066d1530953fe84690d497cd003f2dee3928fba92df6601af713308", 4053114, _CCBY,
            "Ruzimov et al. 2025 · Sensors 25(15) 4844", "detección de cortocircuito entre espiras por corriente "
            "de secuencia negativa (sin referencias)", paginas=((1, 20),)),
    Recurso("chen2023", "Chen2023_Sensors_23_8581.pdf", _PMC + "PMC10611028.1/PMC10611028.1.pdf",
            "95ecffb22cefe50b5dd8cfc32974f6e359caf1f47fe98bc8d170696234c5aa68", 5775211, _CCBY,
            "Chen et al. 2023 · Sensors 23(20) 8581", "detección de cortocircuito entre espiras por la energía de "
            "la envolvente de la corriente de arranque (sin referencias)", paginas=((1, 14),)),
    Recurso("tesis", "tesis_resultados.md", "", None, None, "Del autor de la tesis",
            "Resultados validados de la tesis", "detector, severidades, validación y limitaciones",
            idiomas=("es",), en_paquete=True),
    Recurso("banco", "banco_pruebas.md", "", None, None, "Del autor de la tesis",
            "Documento técnico del banco de pruebas", "equipo, instrumentación, teoría del detector, "
            "mediciones y comportamiento del banco", idiomas=("es",), en_paquete=True),
)
