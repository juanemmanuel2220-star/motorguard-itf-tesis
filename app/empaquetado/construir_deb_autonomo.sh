#!/usr/bin/env bash
# Construye motorguard-itf-autonomo_<versión>_amd64.deb: la app con Python 3.12, Qt 6 (PySide6 6.11.2),
# pyqtgraph, numpy, pyserial, pypdf y keyring incluidos (PyInstaller), para distribuciones sin PySide6 en sus repositorios.
#
# Se construye dentro de un contenedor Ubuntu 22.04 (glibc 2.35): un programa compilado contra una glibc
# vieja funciona en esa y en las más nuevas, así que el paquete corre en Ubuntu 22.04, 24.04 y 26.04 y en
# Debian 12 y 13. PySide6 >= 6.10 exige glibc >= 2.34, por eso no se usa una base más vieja.
#
# Uso: empaquetado/construir_deb_autonomo.sh      -> dist/motorguard-itf-autonomo_<versión>_amd64.deb
set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"          # ~/tesis_itf
APP="$RAIZ/motorguard_dashboard"
EMP="$RAIZ/empaquetado"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$APP/__init__.py")"
PAQ="motorguard-itf-autonomo"
OBRA="$EMP/obra/${PAQ}_${VERSION}_amd64"
PI="$EMP/obra/pyinstaller"
CACHE="$EMP/obra/cache"
DIST="$RAIZ/dist"
# Versiones fijas: las mismas con las que se probó la app
PYSIDE=6.11.2; PYQTGRAPH=0.14.0; NUMPY=2.5.2; PYSERIAL=3.5
# Asistente: pypdf (lee los PDF) y keyring con su backend Secret Service (clave de API opcional)
PYPDF=6.20.1; KEYRING=25.7.0; SECRETSTORAGE=3.5.0; JEEPNEY=0.9.0

echo "MotorGuard-ITF $VERSION (paquete autónomo) — construyendo en ubuntu:22.04"
rm -rf "$OBRA" "$PI"
mkdir -p "$PI" "$CACHE" "$DIST"

# Bibliotecas del sistema que Qt necesita también al construir (PyInstaller importa PySide6 para analizarlo)
LIBS_SISTEMA="$(grep -v '^#' "$EMP/autonomo/dependencias.txt" | sed 's/ (.*)//; s/.*| //' | grep -v '^libc6' | paste -sd' ')"
docker run --rm -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" -e LIBS_SISTEMA="$LIBS_SISTEMA" \
    -v "$RAIZ":/src:ro -v "$EMP/autonomo":/receta:ro -v "$PI":/salida -v "$CACHE":/cache \
    ubuntu:22.04 bash -c "
    set -e
    export DEBIAN_FRONTEND=noninteractive UV_CACHE_DIR=/cache/uv UV_PYTHON_INSTALL_DIR=/cache/python
    apt-get update -qq >/dev/null
    apt-get install -y -qq python3-pip binutils \$LIBS_SISTEMA >/dev/null
    pip3 install -q uv >/dev/null 2>&1
    uv python install 3.12 >/dev/null
    uv venv -q -p 3.12 /tmp/venv
    . /tmp/venv/bin/activate
    uv pip install -q PySide6-Essentials==$PYSIDE pyqtgraph==$PYQTGRAPH numpy==$NUMPY pyserial==$PYSERIAL pypdf==$PYPDF keyring==$KEYRING SecretStorage==$SECRETSTORAGE jeepney==$JEEPNEY pyinstaller
    python -c 'import PySide6, pyqtgraph, numpy, serial, pypdf, keyring; import PyInstaller; print(\"PySide6\", PySide6.__version__, \"· pyqtgraph\", pyqtgraph.__version__, \"· numpy\", numpy.__version__, \"· PyInstaller\", PyInstaller.__version__)'
    cd /tmp && pyinstaller --noconfirm --log-level WARN --workpath /tmp/obra --distpath /salida /receta/motorguard-itf.spec
    chown -R \$HOST_UID:\$HOST_GID /salida
"

# --- árbol del paquete
mkdir -p "$OBRA/DEBIAN" "$OBRA/opt" "$OBRA/usr/bin"
cp -a "$PI/motorguard-itf" "$OBRA/opt/motorguard-itf"
ln -s /opt/motorguard-itf/motorguard-itf "$OBRA/usr/bin/motorguard-itf"
install -Dm0644 "$EMP/comun/motorguard-itf.desktop" "$OBRA/usr/share/applications/motorguard-itf.desktop"
for t in 64 128 256 512; do
    mkdir -p "$OBRA/usr/share/icons/hicolor/${t}x${t}/apps"
    python3 - "$APP/ui/recursos/logo.png" "$OBRA/usr/share/icons/hicolor/${t}x${t}/apps/motorguard-itf.png" "$t" <<'EOF'
import sys
from PIL import Image
Image.open(sys.argv[1]).resize((int(sys.argv[3]),) * 2, Image.LANCZOS).save(sys.argv[2], optimize=True)
EOF
done
mkdir -p "$OBRA/usr/share/man/man1" "$OBRA/usr/share/doc/$PAQ"
sed "s/@VERSION@/$VERSION/" "$EMP/comun/motorguard-itf.1" | gzip -9n > "$OBRA/usr/share/man/man1/motorguard-itf.1.gz"
# copyright: el común (con rutas en /opt) + los componentes incluidos
sed 's#usr/lib/motorguard-itf/motorguard_dashboard/ui/fuentes#opt/motorguard-itf/_internal/motorguard_dashboard/ui/fuentes#g' \
    "$EMP/comun/copyright" > "$OBRA/usr/share/doc/$PAQ/copyright"
cat "$EMP/autonomo/terceros.txt" >> "$OBRA/usr/share/doc/$PAQ/copyright"
FECHA="$(LC_ALL=C date -R)"
printf '%s (%s) unstable; urgency=medium\n\n  * Versión %s autónoma: incluye Python 3.12, PySide6 %s, pyqtgraph %s,\n    numpy %s y pyserial %s.\n\n -- Juan Emmanuel Luna Velázquez <lunabask13@gmail.com>  %s\n' \
    "$PAQ" "$VERSION" "$VERSION" "$PYSIDE" "$PYQTGRAPH" "$NUMPY" "$PYSERIAL" "$FECHA" | gzip -9n > "$OBRA/usr/share/doc/$PAQ/changelog.gz"

find "$OBRA/usr/share" -type d -exec chmod 0755 {} +
find "$OBRA/usr/share" -type f -exec chmod 0644 {} +
TAM_KB="$(du -sk --apparent-size "$OBRA/opt" "$OBRA/usr" | awk '{s+=$1} END {print s}')"
cat > "$OBRA/DEBIAN/control" <<EOF
Package: $PAQ
Version: $VERSION
Section: science
Priority: optional
Architecture: amd64
Installed-Size: $TAM_KB
Depends: $(cat "$EMP/autonomo/dependencias.txt" | grep -v '^#' | paste -sd, | sed 's/,/, /g')
Conflicts: motorguard-itf
Maintainer: Juan Emmanuel Luna Velázquez <lunabask13@gmail.com>
Description: monitoreo de fallas entre espiras (MCSA), versión autónoma
 Aplicación de escritorio para el detector embebido de fallas entre espiras
 (firmware PRUEBA_MODELO_1 en un Arduino Nano ESP32, por USB serie):
 monitoreo, alarmas con severidad, dashboard e inyección de fallas por SSR
 con bloqueos de seguridad. Incluye Python, Qt (PySide6) y las bibliotecas
 que usa, para distribuciones que no traen PySide6 (Ubuntu 22.04/24.04,
 Debian 12). En Ubuntu 26.04 o Debian 13 se recomienda el paquete
 motorguard-itf, que usa las bibliotecas del sistema.
 .
 Desarrollada como parte de una tesis de Ingeniería Mecatrónica (UASLP).
EOF

DEB="$DIST/${PAQ}_${VERSION}_amd64.deb"
dpkg-deb --root-owner-group -Zxz --build "$OBRA" "$DEB" >/dev/null
echo "Listo: $DEB ($(du -h "$DEB" | cut -f1); instalado ~$((TAM_KB / 1024)) MB)"
