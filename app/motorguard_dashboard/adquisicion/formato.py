"""
Formato de los archivos de adquisición, copiado de ~/captura_dataset_multiclase.py (v4.2) para que los
CSV de la app sean intercambiables con los del script (entrenar_severidad.py los lee igual):
COLS, las regex de la trama, parse_line, registrar_fila, fases_fuera y la reanudación con --continuar.
Lo copiado conserva la lógica del script; solo cambia que la hora de cada trama es la de recepción que
da la fuente serie (el script usaba time.time() al leerla, que es lo mismo).

Además: protección de las carpetas de la tesis y el commit del firmware para el _meta.json.
"""

import csv
import glob
import os
import re
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

CLASES = {0: 'SANO', 1: 'LEVE', 2: 'INTER', 3: 'SEVERA'}
CARGAS_LABEL = {0: '0%', 1: '25%', 2: '50%', 3: '75%'}
CARGAS_MAP = {'0%': 0, '25%': 1, '50%': 2, '75%': 3}

COLS = [
    'clase', 'label', 'carga', 'carga_label', 'n_muestra', 'timestamp',
    'V_rms', 'I_rms', 'A_55', 'A_65', 'A_50', 'A_70', 'A_fund', 'I_neg', 'THD',
    'e2', 'u2v', 'u2i', 'dom',
    'hr_l2sm', 'hr_l2sp', 'hr_lrm', 'hr_lrp', 'hr_l3', 'hr_l3rm', 'hr_l3rp',
    'hr_snr2s', 'hr_s', 'hr_sok', 'hr_f0', 'cusum_s', 'p_cal',
    't_desde_on', 't_desde_off', 'va', 'vb', 'ia', 'ib', 'delta_e2', 'pred_fw',
    'de2_fw', 'dv2', 'ang_de2',
    'falla_max', 'r2_re', 'r2_im', 'i1', 'v2_re', 'v2_im', 'v1'
]

MCSA_REGEX = re.compile(
    r"\[MCSA\]\s+Motor:(\w+)\s+\|\s+FallaMax:([A-Za-z0-9 ]+)\s+\|\s+"
    r"VA=([\d\.]+)V\s+VB=([\d\.]+)V\s+VC=([\d\.]+)V\s+\|\s+"
    r"IA=([\d\.]+)A\s+IB=([\d\.]+)A\s+IC=([\d\.]+)A\s+\|\s+"
    r"Afund=([\d\.]+)\s+A55=([\d\.]+)\(([\d\.]+)Hz\)\s+A65=([\d\.]+)\(([\d\.]+)Hz\)\s+\|\s+"
    r"P_RF=([\d\.]+)%\s+P_E2=([\d\.]+)%\s+\|\s+(\w+)\s+\|\s+SSR:([A-Za-z0-9\(\)]+)\s+\|\s+"
    r"U2V=([\d\.]+)%\s+U2I=([\d\.]+)%\s+E2=([\d\.]+)%\s+DOM=(\d)\s+\|\s+"
    r"HR:\s+L2sM=([-\d\.]+)\s+L2sP=([-\d\.]+)\s+LrM=([-\d\.]+)\s+LrP=([-\d\.]+)\s+"
    r"L3=([-\d\.]+)\s+L3rM=([-\d\.]+)\s+L3rP=([-\d\.]+)\s+SNR2s=([-\d\.]+)\s+"
    r"s=([-\d\.]+)\s+SOK=(\d)\s+f0=([-\d\.]+)\s+\|\s+"
    r"CUSUM:\s+S=([-\d\.]+)\s+Pcal=([-\d\.]+)%"
)
VEC_REGEX = re.compile(r"DE2=([-\d\.]+)%\s+dV2=([-\d\.]+)%\s+ANG=([-\d\.]+)")
RAW_REGEX = re.compile(r"RAW:\s+R2=([-\d\.]+),([-\d\.]+)\s+I1=([-\d\.]+)\s+V2=([-\d\.]+),([-\d\.]+)\s+V1=([-\d\.]+)")

# Carpetas con los datos de la tesis: la app nunca escribe en ellas (encargo: no modificar el dataset ni
# las validaciones). Se comparan rutas reales, así que tampoco se cuela un enlace simbólico.
CARPETAS_PROTEGIDAS = ("~/tesis_itf/dataset", "~/tesis_itf/validacion_vivo", "~/tesis_itf/prueba_larga")
DIR_FIRMWARE = "~/Arduino/PRUEBA_MODELO_1"


def parse_line(line: str, t: float) -> Optional[Dict[str, Any]]:
    """Igual que parse_line del script; t es la hora de recepción de la línea."""
    m = MCSA_REGEX.search(line)
    if not m:
        return None
    g = m.groups()
    mv = VEC_REGEX.search(line)
    vec = {
        "de2_fw": float(mv.group(1)) if mv else float('nan'),
        "dv2": float(mv.group(2)) if mv else float('nan'),
        "ang_de2": float(mv.group(3)) if mv else float('nan'),
    }
    mr = RAW_REGEX.search(line)
    nan = float('nan')
    vec.update(dict(zip(('r2_re', 'r2_im', 'i1', 'v2_re', 'v2_im', 'v1'),
                        [float(x) for x in mr.groups()] if mr else [nan] * 6)))
    return {**vec,
            "t": t,
            "motor": g[0],
            "falla_max": g[1].strip(),
            "va": float(g[2]), "vb": float(g[3]), "vc": float(g[4]),
            "ia": float(g[5]), "ib": float(g[6]), "ic": float(g[7]),
            "afund": float(g[8]),
            "a55": float(g[9]), "f55": float(g[10]),
            "a65": float(g[11]), "f65": float(g[12]),
            "p_rf": float(g[13]),
            "p_e2": float(g[14]),
            "pred": g[15],
            "ssr": g[16],
            "u2v": float(g[17]), "u2i": float(g[18]), "e2": float(g[19]), "dom": int(g[20]),
            "hr_l2sm": float(g[21]), "hr_l2sp": float(g[22]),
            "hr_lrm": float(g[23]), "hr_lrp": float(g[24]),
            "hr_l3": float(g[25]), "hr_l3rm": float(g[26]), "hr_l3rp": float(g[27]),
            "hr_snr2s": float(g[28]), "hr_s": float(g[29]), "hr_sok": int(g[30]), "hr_f0": float(g[31]),
            "cusum_s": float(g[32]), "p_cal": float(g[33])}


def fases_fuera(a: Dict[str, Any], b: Dict[str, Any], tol_abs: float, tol_rel: float = 0.012) -> List[str]:
    """Fases cuya corriente difiere entre dos tramas más que max(tol_abs, tol_rel*I)."""
    malas = []
    for k in ('ia', 'ib', 'ic'):
        lim = max(tol_abs, tol_rel * max(a[k], b[k]))
        if abs(a[k] - b[k]) > lim:
            malas.append(f"{k.upper()} {a[k]:.2f}->{b[k]:.2f}")
    return malas


def fila_dataset(d: Dict[str, Any], clase: int, carga: int, n_muestra: int, t_desde_on: float,
                 t_desde_off: float, delta_e2: float, timestamp: str) -> list:
    """Fila del CSV, en el orden de COLS (registrar_fila del script). Fase C: rms[CH_VC] y rms[CH_IC]."""
    return [
        clase, CLASES[clase], carga, CARGAS_LABEL[carga], n_muestra, timestamp,
        d['vc'], d['ic'], d['a55'], d['a65'],
        0.0,  # A_50
        0.0,  # A_70
        d['afund'],
        d['u2i'] / 100.0,  # Ineg relativo
        0.0,  # THD
        d['e2'], d['u2v'], d['u2i'], d['dom'],
        d['hr_l2sm'], d['hr_l2sp'], d['hr_lrm'], d['hr_lrp'], d['hr_l3'], d['hr_l3rm'], d['hr_l3rp'],
        d['hr_snr2s'], d['hr_s'], d['hr_sok'], d['hr_f0'], d['cusum_s'], d['p_cal'],
        round(t_desde_on, 2), round(t_desde_off, 2),
        d['va'], d['vb'], d['ia'], d['ib'],
        round(delta_e2, 3),
        d['pred'],
        d['de2_fw'], d['dv2'], d['ang_de2'],
        d['falla_max'], d['r2_re'], d['r2_im'], d['i1'], d['v2_re'], d['v2_im'], d['v1'],
    ]


def carpeta_protegida(ruta: str) -> Optional[str]:
    """La carpeta protegida que contiene a 'ruta' (o es ella), o None si se puede escribir ahí."""
    real = os.path.realpath(os.path.expanduser(ruta))
    for p in CARPETAS_PROTEGIDAS:
        prot = os.path.realpath(os.path.expanduser(p))
        if real == prot or real.startswith(prot + os.sep):
            return p
    return None


def nombre_base(label: str, carga_str: str, ahora: Optional[datetime] = None) -> str:
    """Mismo nombre que el script (entrenar_severidad.py lo reconoce por este patrón)."""
    return f"cap_ENTRELAZADA_{label}_{carga_str}_{(ahora or datetime.now()).strftime('%Y%m%d_%H%M')}.csv"


def buscar_para_continuar(carpeta: str, label: str, carga_str: str) -> Tuple[Optional[str], str]:
    """Archivo más reciente de esta clase y carga con el esquema actual (como --continuar), y un mensaje."""
    patron = os.path.join(glob.escape(carpeta), f"cap_ENTRELAZADA_{label}_{carga_str}_*.csv")
    coincidencias = sorted(f for f in glob.glob(patron) if not f.endswith("_descartes.csv"))
    if not coincidencias:
        return None, f"no hay capturas previas de {label} {carga_str} en esta carpeta: se crea un archivo nuevo"
    ruta = coincidencias[-1]
    with open(ruta, 'r', newline='') as fh:
        header = next(csv.reader(fh), [])
    if header != COLS:
        return None, f"{os.path.basename(ruta)} tiene otro esquema: no se reanuda sobre él (se crea uno nuevo)"
    return ruta, f"se reanuda {os.path.basename(ruta)}"


def pares_existentes(ruta: str, corregir: bool = True) -> Tuple[int, bool]:
    """Pares completos ya escritos en el CSV. Si hay una fila huérfana (par a medias) la quita, como el
    script (con corregir=False solo cuenta, sin tocar el archivo). Devuelve (pares, hay_huerfana)."""
    if not os.path.exists(ruta) or os.path.getsize(ruta) == 0:
        return 0, False
    with open(ruta, 'r', newline='') as fr:
        filas = [r for r in csv.reader(fr) if r]
    tiene_header = len(filas) > 0 and filas[0][0] == 'clase'
    n_filas = len(filas) - 1 if tiene_header else len(filas)
    corregido = False
    if n_filas % 2 != 0 and not corregir:
        return max(0, (n_filas - 1) // 2), True
    if n_filas % 2 != 0:
        with open(ruta, 'w', newline='') as fw:
            ww = csv.writer(fw)
            for r in filas[:-1]:
                ww.writerow(r)
        n_filas -= 1
        corregido = True
    return max(0, n_filas // 2), corregido


def commit_firmware() -> str:
    """Último commit que tocó la carpeta del firmware ('' si no hay git o no existe la carpeta)."""
    try:
        return subprocess.run(['git', '-C', os.path.expanduser(DIR_FIRMWARE), 'log', '-1', '--format=%h %s', '--', '.'],
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ''
