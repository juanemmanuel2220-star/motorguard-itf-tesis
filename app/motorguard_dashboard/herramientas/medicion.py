"""Medición de memoria y CPU del propio proceso (Linux, sin dependencias) y escritura de resultados."""

import csv
import json
import os
import time


def rss_mb() -> float:
    """Memoria residente del proceso en MB (VmRSS de /proc/self/status)."""
    with open("/proc/self/status") as f:
        for linea in f:
            if linea.startswith("VmRSS:"):
                return int(linea.split()[1]) / 1024.0
    return float("nan")


def cpu_s() -> float:
    return time.process_time()


def percentil(valores, p):
    if not valores:
        return float("nan")
    v = sorted(valores)
    k = min(len(v) - 1, max(0, int(round(p / 100.0 * (len(v) - 1)))))
    return v[k]


def guardar(dir_salida, muestras, resumen, titulo, eje_x, clave_x):
    os.makedirs(dir_salida, exist_ok=True)
    if muestras:
        with open(os.path.join(dir_salida, "muestras.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(muestras[0].keys()))
            w.writeheader()
            w.writerows(muestras)
    with open(os.path.join(dir_salida, "resumen.json"), "w", encoding="utf-8") as f:
        json.dump(resumen, f, indent=2, ensure_ascii=False)
    # La gráfica se dibuja en otro proceso: en el mismo que Qt, matplotlib y Qt cargan FreeType y chocan
    # ("raster overflow")
    import subprocess
    import sys
    subprocess.run([sys.executable, "-m", "motorguard_dashboard.herramientas.medicion", dir_salida, titulo, eje_x,
                    clave_x], check=False)


def graficar(dir_salida, titulo, eje_x, clave_x):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    with open(os.path.join(dir_salida, "muestras.csv"), encoding="utf-8") as f:
        muestras = [{k: float(v) for k, v in fila.items()} for fila in csv.DictReader(f)]
    if not muestras:
        return
    x = [m[clave_x] for m in muestras]
    clave_t = "ms_p99" if "ms_p99" in muestras[0] else "cpu_pct"
    fig, ax = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
    ax[0].plot(x, [m["rss_mb"] for m in muestras], color="#2457A6")
    ax[0].set_ylabel("Memoria residente (MB)")
    ax[0].ticklabel_format(useOffset=False, axis="y")
    ax[0].grid(alpha=0.3)
    ax[1].plot(x, [m[clave_t] for m in muestras], color="#B85C00")
    ax[1].set_ylabel("ms por trama (p99)" if clave_t == "ms_p99" else "CPU (%)")
    ax[1].set_xlabel(eje_x)
    ax[1].set_ylim(bottom=0)
    ax[1].grid(alpha=0.3)
    fig.suptitle(titulo)
    fig.tight_layout()
    fig.savefig(os.path.join(dir_salida, "grafica.png"), dpi=130)
    plt.close(fig)


if __name__ == "__main__":
    import sys
    graficar(*sys.argv[1:5])
