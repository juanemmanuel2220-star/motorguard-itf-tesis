#!/usr/bin/env bash
# Construye motorguard-itf_<versión>_all.deb: la app en Python usando PySide6, pyqtgraph, pyserial y numpy
# de la distribución (Ubuntu 26.04, Debian 13 o más nuevos). Solo empaqueta los módulos de la app nueva:
# sin pruebas, sin herramientas de desarrollo y sin el código anterior.
#
# Uso: empaquetado/construir_deb_ligero.sh            -> dist/motorguard-itf_<versión>_all.deb
set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"          # ~/tesis_itf
APP="$RAIZ/motorguard_dashboard"
EMP="$RAIZ/empaquetado"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$APP/__init__.py")"
PAQ="motorguard-itf"
OBRA="$EMP/obra/${PAQ}_${VERSION}_all"
DIST="$RAIZ/dist"

echo "MotorGuard-ITF $VERSION (paquete ligero)"
rm -rf "$OBRA"
mkdir -p "$OBRA/DEBIAN" "$DIST"

# --- la app (solo lo que usa la versión nueva)
DEST="$OBRA/usr/lib/$PAQ/motorguard_dashboard"
mkdir -p "$DEST/ui"
cp "$APP/__init__.py" "$APP/app.py" "$DEST/"
for d in adquisicion inyeccion sistema telemetry rag; do
    mkdir -p "$DEST/$d"
    cp "$APP/$d"/*.py "$DEST/$d/"
done
# documentos del banco de la tesis que vienen con la app (los PDF y los modelos se descargan con
# «Preparar asistente» desde sus fuentes oficiales: el manual ABB no se puede redistribuir)
mkdir -p "$DEST/rag/datos"
cp "$APP/rag/datos"/*.md "$DEST/rag/datos/"
for f in __init__ tema componentes monitor_window plano_firma dashboard_tab panel_inyeccion adquisicion_tab asistente_tab asistente_servicio conversacion marcas dialogos; do
    cp "$APP/ui/$f.py" "$DEST/ui/"
done
cp -r "$APP/ui/fuentes" "$APP/ui/recursos" "$DEST/ui/"
# JetBrains Mono viene de la distribución (fonts-jetbrains-mono); Qt la encuentra por fontconfig.
# Figtree no está empaquetada en Debian/Ubuntu: se incluye.
rm -f "$DEST/ui/fuentes"/JetBrainsMono-*.ttf "$DEST/ui/fuentes/OFL_JetBrainsMono.txt"

# --- comando, lanzador, íconos, manual y documentación
mkdir -p "$OBRA/usr/bin"
cat > "$OBRA/usr/bin/$PAQ" <<'EOF'
#!/bin/sh
exec /usr/bin/python3 /usr/lib/motorguard-itf/motorguard_dashboard/app.py "$@"
EOF
chmod 0755 "$OBRA/usr/bin/$PAQ"
install -Dm0644 "$EMP/comun/$PAQ.desktop" "$OBRA/usr/share/applications/$PAQ.desktop"
for t in 64 128 256 512; do
    mkdir -p "$OBRA/usr/share/icons/hicolor/${t}x${t}/apps"
    python3 - "$APP/ui/recursos/logo.png" "$OBRA/usr/share/icons/hicolor/${t}x${t}/apps/$PAQ.png" "$t" <<'EOF'
import sys
from PIL import Image
Image.open(sys.argv[1]).resize((int(sys.argv[3]),) * 2, Image.LANCZOS).save(sys.argv[2], optimize=True)
EOF
done
mkdir -p "$OBRA/usr/share/man/man1" "$OBRA/usr/share/doc/$PAQ"
sed "s/@VERSION@/$VERSION/" "$EMP/comun/$PAQ.1" | gzip -9n > "$OBRA/usr/share/man/man1/$PAQ.1.gz"
# copyright sin el bloque de JetBrains Mono (no se incluye en este paquete)
awk 'BEGIN{RS="";ORS="\n\n"} !/JetBrainsMono-\*\.ttf/' "$EMP/comun/copyright" | sed -e :a -e '/^\n*$/{$d;N;ba' -e '}' \
    > "$OBRA/usr/share/doc/$PAQ/copyright"
FECHA="$(LC_ALL=C date -R)"
printf '%s (%s) unstable; urgency=medium\n\n  * Versión %s: monitoreo, inyección segura, dashboard, tema claro/oscuro,\n    estabilidad para sesiones largas y asistente de mantenimiento con citas.\n\n -- Juan Emmanuel Luna Velázquez <lunabask13@gmail.com>  %s\n' \
    "$PAQ" "$VERSION" "$VERSION" "$FECHA" | gzip -9n > "$OBRA/usr/share/doc/$PAQ/changelog.gz"

# --- permisos normalizados y metadatos del paquete
find "$OBRA/usr" -type d -exec chmod 0755 {} +
find "$OBRA/usr" -type f ! -path "*/usr/bin/*" -exec chmod 0644 {} +
TAM_KB="$(du -sk "$OBRA/usr" | cut -f1)"
cat > "$OBRA/DEBIAN/control" <<EOF
Package: $PAQ
Version: $VERSION
Section: science
Priority: optional
Architecture: all
Installed-Size: $TAM_KB
Depends: python3 (>= 3.11), python3-pyside6.qtcore, python3-pyside6.qtgui, python3-pyside6.qtwidgets, python3-pyside6.qtsvg, python3-pyside6.qtdbus, python3-pyside6.qtopengl, python3-pyside6.qtopenglwidgets, python3-pyqtgraph (>= 0.13), python3-serial, python3-numpy, python3-pypdf, fonts-jetbrains-mono
Recommends: python3-keyring, poppler-utils
Conflicts: motorguard-itf-autonomo
Maintainer: Juan Emmanuel Luna Velázquez <lunabask13@gmail.com>
Description: monitoreo de fallas entre espiras en motores de inducción (MCSA)
 Aplicación de escritorio para el detector embebido de fallas entre espiras
 (firmware PRUEBA_MODELO_1 en un Arduino Nano ESP32, por USB serie):
 estado del motor, corrientes y voltajes por fase, proyección de la firma,
 alarmas con severidad, dashboard de cada trama y, con el Arduino,
 inyección de fallas por SSR con bloqueos de seguridad. Sin Arduino
 reproduce registros seriales grabados. Tema claro y oscuro.
 .
 Incluye un asistente de mantenimiento (RAG local con llama.cpp y modelos
 Qwen) que recomienda inspecciones citando documento y página; el motor,
 los modelos y los documentos se descargan desde la app.
 .
 Desarrollada como parte de una tesis de Ingeniería Mecatrónica (UASLP).
EOF
cat > "$OBRA/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "configure" ] && command -v py3compile >/dev/null 2>&1; then
    py3compile -p motorguard-itf /usr/lib/motorguard-itf
fi
EOF
cat > "$OBRA/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
if command -v py3clean >/dev/null 2>&1; then
    py3clean -p motorguard-itf
else
    find /usr/lib/motorguard-itf -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
fi
EOF
chmod 0755 "$OBRA/DEBIAN/postinst" "$OBRA/DEBIAN/prerm"

DEB="$DIST/${PAQ}_${VERSION}_all.deb"
dpkg-deb --root-owner-group -Zxz --build "$OBRA" "$DEB" >/dev/null
echo "Listo: $DEB ($(du -h "$DEB" | cut -f1))"
