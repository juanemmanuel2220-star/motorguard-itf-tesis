# Copia para la tesis de ~/Documents/TESIS/articulo_icit2027/figuras/fig_resultado_falsas_alarmas.py: solo cambian textos y formato.
#!/usr/bin/env python3
"""Fig.: falsas alarmas por hora (IC de Poisson al 95 %) en operacion sana continua.
Estudio 1 (~/tesis_itf/comparacion_ml/resultado_comparacion_ml.json) y validacion ciega 2
(~/tesis_itf/validacion_ciega2/resultado_validacion_ciega2_<fecha>.json, clave 'falsas_alarmas').
Uso: /usr/bin/python3 -I fig_resultado_falsas_alarmas.py [--fecha 20261015_20261016] [--json RUTA] [--salida DIR]"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import estilo_ieee as E  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--fecha', default='20261015_20261016')
ap.add_argument('--json', default=None)
ap.add_argument('--salida', default=E.DIR)
args = ap.parse_args()
E.DIR = args.salida
E.aplicar()
H = os.path.expanduser('~')
e1j = json.load(open(f'{H}/tesis_itf/comparacion_ml/resultado_comparacion_ml.json'))
ruta_vc = args.json or f'{H}/tesis_itf/validacion_ciega2/resultado_validacion_ciega2_{args.fecha}.json'
vc = json.load(open(ruta_vc)) if os.path.exists(ruta_vc) else {}
fa = vc.get('falsas_alarmas', {})

filas = [  # (etiqueta, fa_h, ic, estilo)
    ('Regla, estudio 1', e1j['A_firmware']['fa_h'], e1j['A_firmware']['fa_h_ic95'], ('o', 'white')),
    ('RF, estudio 1', e1j['C1_random_forest_mejor']['fa_h'], e1j['C1_random_forest_mejor']['fa_h_ic95'], ('s', '0.0')),
]
nombres = [('regla', 'Regla, validación ciega 2', ('o', 'white')), ('rf', 'RF congelado, validación ciega 2', ('s', '0.0')),
           ('regla_completa', 'Regla con enclavamiento, ciega 2', ('o', '0.6')),
           ('variante', 'Variante de ángulo, ciega 2', ('^', '0.6')),
           ('firmware', 'Firmware en vivo, ciega 2', ('v', 'white'))]
for k, et, st in nombres:
    if k in fa and fa[k].get('fa_h') is not None:
        filas.append((et, fa[k]['fa_h'], fa[k]['ic95'], st))
if not fa:
    print('AVISO: sin datos de la validacion ciega 2 en', ruta_vc)
fig, ax = plt.subplots(figsize=(E.ANCHO, 0.42 * len(filas) + 0.7))
for i, (et, v, ic, (mk, mfc)) in enumerate(filas[::-1]):
    ax.errorbar(v, i, xerr=[[v - ic[0]], [ic[1] - v]], marker=mk, mfc=mfc, color='0.0', ms=4, mew=0.6,
                capsize=1.5, elinewidth=0.6)
ax.set_yticks(range(len(filas)))
ax.set_yticklabels([f[0] for f in filas[::-1]])
ax.axvline(1.0, color='0.5', lw=0.6, ls=':')
ax.text(1.05, len(filas) - 0.6, '1 por hora', fontsize=6.5, color='0.3', va='center')
ax.set_xlabel('Falsas alarmas por hora (IC 95 %)')
ax.set_title(f"Validación ciega 2: {fa.get('regla', {}).get('horas', 0):.1f} h de operación sana; estudio 1: 2.76 h" if fa else 'Estudio 1: 2.76 h sanas', pad=2, fontsize=7)
ax.set_xlim(0, max(f[2][1] for f in filas) * 1.05)
ax.set_ylim(-0.6, len(filas) - 0.3)
ax.grid(axis='x')
fig.tight_layout()
E.guardar(fig, 'fig_resultado_falsas_alarmas')
