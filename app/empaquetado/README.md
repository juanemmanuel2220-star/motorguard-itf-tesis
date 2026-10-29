# Empaquetado de MotorGuard-ITF

| Paquete | Para | Cómo se construye |
|---|---|---|
| `motorguard-itf_<v>_all.deb` (ligero, ~1 MB) | Ubuntu 26.04, Debian 13 o más nuevos (traen PySide6 ≥ 6.8 y pyqtgraph) | `empaquetado/construir_deb_ligero.sh` |
| `motorguard-itf-autonomo_<v>_amd64.deb` (incluye Python y Qt) | Ubuntu 22.04/24.04, Debian 12 y los anteriores | `empaquetado/construir_deb_autonomo.sh` |

Los dos se excluyen entre sí (`Conflicts`). La versión sale de `motorguard_dashboard/__init__.py`.

**Autónomo:** se construye en un contenedor `ubuntu:22.04` (glibc 2.35) con Python 3.12 (uv), PySide6 6.11.2,
pyqtgraph 0.14.0, numpy 2.5.2, pypdf 6.20.1 y keyring 25.7.0 (con SecretStorage/jeepney) y PyInstaller; un binario hecho contra una glibc vieja corre en esa y en las
nuevas. No se usa una base más vieja porque PySide6 ≥ 6.10 exige glibc ≥ 2.34. Se instala en `/opt/motorguard-itf`
(convención para software de terceros con todo incluido; por eso `lintian` marca `dir-or-file-in-opt`, regla
pensada para los paquetes oficiales de Debian). Las bibliotecas del sistema que pide Qt están en
`autonomo/dependencias.txt`.

**Verificado (12-oct-2026; repetido el 13-oct con el asistente incluido)** con `probar_deb.sh` (instalar con apt, arrancar sin pantalla y con X11/Xvfb
reproduciendo un log real, revisar `app.log`, buscar bibliotecas faltantes, desinstalar):
- ligero: Ubuntu 26.04 y Debian 13 — sin errores; lintian sin observaciones;
- autónomo: Ubuntu 22.04, 24.04 y 26.04, Debian 12 y 13 — sin errores ni bibliotecas faltantes. Con `--lintian`
  (13-oct) aparecen, además de `dir-or-file-in-opt`, las observaciones propias de un paquete de PyInstaller
  (`embedded-library`, `unstripped-binary-or-object`, `shared-library-is-executable`, entre otras); no se
  corrigieron porque las bibliotecas van tal como las publica cada proyecto.
- Ninguno de los dos lleva el runtime de llama.cpp, los modelos ni los documentos: los descarga "Preparar
  asistente" en la sección Asistente (`~/.local/share/MotorGuard-ITF/asistente/`).

**Probar en contenedores limpios** (instala con apt, arranca la app sin pantalla con un log real, revisa
`app.log` y desinstala):

    empaquetado/probar_deb.sh dist/motorguard-itf_1.0.0_all.deb ubuntu:26.04 debian:13 --lintian
    empaquetado/probar_deb.sh dist/motorguard-itf-autonomo_1.0.0_amd64.deb ubuntu:22.04 ubuntu:24.04 ubuntu:26.04 debian:12 debian:13

**Instalar en tu PC:** `sudo apt install ./dist/motorguard-itf_1.0.0_all.deb`
Para leer el Arduino, el usuario debe estar en el grupo `dialout`: `sudo usermod -aG dialout $USER`.
