# MotorGuard-ITF: código, datos y protocolos de la tesis

Material de apoyo de la tesis de licenciatura en Ingeniería Mecatrónica:

> Luna Velázquez, J. E. (2026). *Detección de Fallas de Cortocircuito en Devanados de Motores de Inducción mediante Análisis de Firma de Corriente (MCSA) e Inteligencia Artificial* [Tesis de licenciatura]. Universidad Autónoma de San Luis Potosí, Unidad Académica Multidisciplinaria Región Altiplano.

El repositorio contiene:
- el firmware del detector embebido (Arduino Nano ESP32);
- la aplicación de escritorio MotorGuard-ITF con su asistente RAG local;
- los *scripts* de adquisición, entrenamiento, análisis y figuras;
- los protocolos declarados antes de cada análisis;
- los registros de ensayo del banco de pruebas que sustentan las tablas del capítulo 4.

Los archivos se publican **tal como se usaron en la tesis**. Los anexos citan números de línea, y esos números coinciden con los de este repositorio.

## El sistema en una línea
Un motor ABB de 1.5 kW con fallas entre espiras emuladas en la fase C (LEVE 7.0 %, INTER 14.3 % y SEVERA 21.6 % de las espiras).

| Etapa | Cómo funciona |
|---|---|
| Detección | Regla física sobre la corriente de secuencia negativa: proyección sobre −81.4°, umbral de 0.40 pp durante 3 bloques, con enclavamiento |
| Severidad | Umbrales aprendidos de 1.626 y 4.471 pp |
| Recomendación | Asistente RAG local con citas |

## Mapa anexo → archivo

| Anexo | En la tesis | En este repositorio |
|---|---|---|
| A | `~/Arduino/PRUEBA_MODELO_1/` (commit `299a943`) | `firmware/PRUEBA_MODELO_1/` |
| B | `~/sesion_larga_base_pulsos.py`, `~/prueba_provocacion.py` | `adquisicion/` |
| C | `~/tesis_itf/validacion_agrupada.py`, `~/tesis_itf/export_rf_flat.py`, `~/entrenar_severidad.py` | `modelos/` |
| D | `~/analisis_sesion_larga.py`, `.../figuras/scripts/detector_escalon_oct01.py` | `analisis/` |
| E | `~/tesis_itf/motorguard_dashboard/` (v1.0.0, commit `d265bc9`) | `app/motorguard_dashboard/` |

## Contenido

| Carpeta | Qué hay |
|---|---|
| `firmware/` | Firmware validado `299a943`, congelado para todas las pruebas en vivo |
| `app/` | Aplicación de escritorio (Python, PySide6) y scripts para construir sus paquetes `.deb` |
| `adquisicion/` | Scripts que hablan con el microcontrolador: sesiones de base y pulsos, prueba de provocación, captura del conjunto multiclase, validación en vivo y prueba larga |
| `modelos/` | Validación agrupada y exportación del RF de septiembre; entrenamiento del clasificador de severidad |
| `analisis/` | Scripts que regeneran las cifras del capítulo 4 (estudios 1 a 3, ruido del detector, compensación de V2) |
| `figuras/` | Scripts de las figuras de la tesis |
| `protocolos/` | Protocolos de análisis, cada uno con su commit anterior al análisis (ver `COMMITS.md`) |
| `registros/` | Registros de ensayo (ver abajo) |
| `tesis/` | La tesis en PDF |
| `COMMITS.md` | Fecha, mensaje y archivos de cada commit citado en la tesis, con los identificadores para comprobar los archivos |

### Registros (`registros/`)

| Carpeta | Contenido |
|---|---|
| `tesis_itf/dataset/` | Conjunto multiclase de pares SANO/FALLA del 6 al 8 de octubre (`cap_ENTRELAZADA_*`, cada uno con `_meta.json` y `_serial.log`), y las sesiones de julio a septiembre de la etapa anterior |
| `tesis_itf/validacion_vivo/` | Validaciones ciegas en vivo con el firmware final |
| `tesis_itf/prueba_larga/` | Operación continua sin falla (12-oct y 15–16-oct) |
| `tesis_itf/validacion_ciega2/` | Validación ciega 2, con los modelos congelados y sus SHA-256 |
| `tesis_itf/comparacion_ml/`, `generalizacion_carga/`, `mejora_deteccion/`, `modelo_severidad/` | Resultados tal como los escribieron los scripts |
| `tesis_itf/app_registros/`, `app_pruebas/` | Prueba en vivo de la app, registros del asistente, pruebas de resistencia y de los paquetes |
| Raíz de `registros/` | Campaña de inyecciones del 28 y 29 de septiembre y sesiones del 1 de octubre (antecedentes del capítulo 4) |

Glosario de nombres: *SANO* es motor sano; *LEVE*, *INTER* y *SEVERA* son las tres severidades; *carga* es el porcentaje de carga del generador.

## Cómo reproducir las cifras

Los scripts no se modificaron, así que leen y escriben rutas de la forma `~/tesis_itf/...`. Para correrlos, apunta `HOME` a `registros/`:

```bash
python3 -m venv venv && . venv/bin/activate && pip install -r requirements.txt
cd registros
HOME=$(pwd) python3 ../analisis/comparacion_ml_deteccion.py          # estudio 1
HOME=$(pwd) python3 ../analisis/analisis_generalizacion_carga.py     # estudio 2
HOME=$(pwd) python3 ../analisis/analisis_validacion_ciega2.py        # validación ciega 2
HOME=$(pwd) python3 ../modelos/entrenar_severidad.py                 # clasificador de severidad
python3 ../analisis/analisis_sesion_larga.py sesion_LEVE_postconexion_50carga_20261001_155559.log
```

- Al correr un script se sobrescriben sus archivos de resultados en `registros/tesis_itf/`.
- Algunos scripts de figuras y de la etapa de septiembre usan la ruta absoluta `/home/luna/`. Para correrlos hay que ajustar esa ruta o crear un enlace.
- **Versiones:** todos los resultados se obtuvieron con scikit-learn 1.7.2 (`requirements.txt`). Con otra versión, el bosque aleatorio puede dar cifras distintas por unos cuantos bloques.

## Firmware
1. Arduino IDE 2 con el núcleo `esp32` 3.3.12 y la placa **Arduino Nano ESP32**.
2. **Opción obligatoria: `PinNumbers=byGPIONumber`** (viene en `sketch.yaml`). Con la opción por defecto, los pines no corresponden.
3. Bibliotecas del gestor de Arduino: Adafruit GFX 1.12.6, Adafruit ILI9341 1.6.4 y Adafruit BusIO 1.17.4.

En la línea 1365 la contraseña del punto de acceso Wi-Fi se reemplazó por `"CAMBIAR_CLAVE"`; el resto del archivo es idéntico al commit `299a943` (ver `COMMITS.md`). El Wi-Fi está desactivado por defecto (`HABILITAR_WIFI 0`), porque dos canales de voltaje usan el ADC2.

## Aplicación
```bash
pip install PySide6 pyqtgraph numpy scipy pandas scikit-learn pyserial pypdf keyring
cd app && python3 -m motorguard_dashboard.app --replay ../registros/tesis_itf/validacion_vivo/<sesión>_serial.log
```

- **Con el microcontrolador:** sin `--replay`, la app usa el primer `/dev/ttyACM*`.
- **Paquetes `.deb`:** `app/empaquetado/README.md` explica cómo construirlos.
- **Modelos del asistente:** Qwen3.5-4B, Qwen3-Embedding-0.6B y el runtime llama.cpp no vienen en el repositorio. Se descargan desde la app con **Preparar asistente**, que verifica su SHA-256.
- **Documentos del asistente:** los PDF públicos (NASA, DOE/FEMP, USBR y dos artículos CC BY) no se redistribuyen. La app los descarga de su fuente oficial (`app/motorguard_dashboard/rag/catalogo.py`). El manual del motor es © ABB y no se incluye: cada usuario debe obtenerlo del fabricante.

## Lo que no está aquí
- **El historial de git:** el repositorio de trabajo contiene archivos personales. Los commits citados están documentados en `COMMITS.md`.
- **Los modelos de lenguaje, el manual ABB y los PDF de las fuentes del asistente:** ver la sección «Aplicación».
- **Las fotos del banco:** los scripts que las anotan dependen de fotos personales.

## Licencia

| Parte | Licencia |
|---|---|
| Código (firmware, app y scripts) | GPL-3.0-or-later (`LICENSE`) |
| Registros, protocolos y el PDF de la tesis | CC BY 4.0 (`LICENSE-DATA`) |
| Fuentes tipográficas de la app | OFL-1.1 |
| Íconos de marcas | CC0, con las marcas propiedad de sus dueños (ver `app/empaquetado/comun/copyright`) |

## Cómo citar
Cita la tesis (arriba). Los datos de cita también están en `CITATION.cff`.
