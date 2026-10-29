#!/usr/bin/env bash
# Prueba un .deb de MotorGuard-ITF instalándolo en contenedores limpios (Docker):
#   apt instala el paquete y sus dependencias, se revisan el comando y el manual, la app se abre sin pantalla
#   reproduciendo un log real durante unos segundos y se comprueba que app.log no tenga errores.
#   Con --lintian también revisa el paquete con lintian (en el primer contenedor).
#
# Uso: empaquetado/probar_deb.sh dist/motorguard-itf_1.0.0_all.deb ubuntu:26.04 debian:13 [--lintian]
set -uo pipefail

DEB="$(realpath "$1")"; shift
LINTIAN=0
IMAGENES=()
for a in "$@"; do
    if [ "$a" = "--lintian" ]; then LINTIAN=1; else IMAGENES+=("$a"); fi
done
LOG="$HOME/tesis_itf/validacion_vivo/vivo_INTER_75%_20261009_1513_serial.log"
FALLAS=0

for img in "${IMAGENES[@]}"; do
    echo "=================== $img"
    docker run --rm -e DEBIAN_FRONTEND=noninteractive -e LINTIAN="$LINTIAN" \
        -v "$(dirname "$DEB")":/paquete:ro -v "$LOG":/datos/sesion_serial.log:ro "$img" bash -c '
        set -e
        apt-get update -qq >/dev/null
        apt-get install -y -qq /paquete/'"$(basename "$DEB")"' >/tmp/apt.log 2>&1 || { tail -20 /tmp/apt.log; exit 10; }
        . /etc/os-release; echo "instalado en $PRETTY_NAME"
        PQ=$(dpkg-query -W -f="\${Package}\n" "motorguard-itf*" 2>/dev/null | head -1)
        dpkg -s "$PQ" | grep -E "^(Package|Version|Status):" | tr "\n" " "; echo
        command -v motorguard-itf
        motorguard-itf --help | head -2
        dpkg -c /paquete/'"$(basename "$DEB")"' | grep -q "man1/motorguard-itf.1.gz" && echo "manual: incluido en el paquete"
        export QT_QPA_PLATFORM=offscreen
        set +e
        timeout -s TERM 12 motorguard-itf --replay /datos/sesion_serial.log --velocidad 100 >/tmp/app.out 2>&1
        rc=$?
        set -e
        echo "la app corrió (código $rc; 124 = cerrada por el tiempo de prueba)"
        L=$HOME/.local/share/MotorGuard-ITF/logs/app.log
        test -s "$L" || { echo "FALTA app.log"; cat /tmp/app.out; exit 11; }
        grep -c " ERROR " "$L" >/tmp/n_err || true
        echo "errores en app.log: $(cat /tmp/n_err)"
        grep -E "Inicio MotorGuard-ITF" "$L" | sed "s/^.*Inicio/Inicio/"
        test "$(cat /tmp/n_err)" = "0" || { grep -A5 " ERROR " "$L" | head -30; exit 12; }
        ls "$HOME"/Documents/MotorGuard-ITF/registros/ 2>/dev/null | head -2 || true
        # Bibliotecas que les faltan a los complementos de pantalla de Qt (solo en el paquete autónomo)
        if [ -d /opt/motorguard-itf ]; then
            F=$(find /opt/motorguard-itf -path "*platforms/libq*.so" | xargs ldd 2>/dev/null | grep "not found" | sort -u)
            [ -z "$F" ] && echo "complementos de pantalla (xcb, wayland, offscreen): sin bibliotecas faltantes" \
                        || { echo "FALTAN BIBLIOTECAS:"; echo "$F"; exit 13; }
        fi
        # Arranque con una pantalla X11 virtual: prueba las bibliotecas gráficas de un escritorio real
        apt-get install -y -qq xvfb xauth >/dev/null 2>&1
        rm -f "$L"
        set +e
        QT_QPA_PLATFORM=xcb xvfb-run -a timeout -s TERM 12 motorguard-itf --replay /datos/sesion_serial.log --velocidad 100 >/tmp/x11.out 2>&1
        rc=$?
        set -e
        test -s "$L" || { echo "X11: la app no arrancó"; tail -15 /tmp/x11.out; exit 14; }
        n=$(grep -c " ERROR " "$L" || true)
        echo "X11 (Xvfb): la app corrió (código $rc), errores en app.log: $n"
        test "$n" = "0" || { grep -A5 " ERROR " "$L" | head -20; exit 15; }
        if [ "$LINTIAN" = "1" ]; then
            apt-get install -y -qq lintian >/dev/null 2>&1
            echo "--- lintian"
            lintian --no-tag-display-limit /paquete/'"$(basename "$DEB")"' || true
        fi
        apt-get remove -y -qq "motorguard-itf*" >/dev/null 2>&1 && echo "desinstalación: ok"
        test ! -e /usr/lib/motorguard-itf/motorguard_dashboard/__pycache__ && echo "sin residuos de __pycache__"
    ' || { echo "*** FALLÓ en $img (código $?)"; FALLAS=$((FALLAS + 1)); }
    LINTIAN=0
done
echo "==================="
[ "$FALLAS" -eq 0 ] && echo "TODAS LAS PRUEBAS DEL PAQUETE PASARON" || echo "$FALLAS imagen(es) con fallas"
exit "$FALLAS"
