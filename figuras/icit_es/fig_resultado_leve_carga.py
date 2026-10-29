# Copia para la tesis de ~/Documents/TESIS/articulo_icit2027/figuras/fig_resultado_leve_carga.py: solo cambian textos y formato.
#!/usr/bin/env python3
"""Fig. central: deteccion de la falla de 7.0 % (LEVE) por carga, regla de Fortescue frente al RF, con IC de Wilson.
(a) Estudio 2, pares de un bloque (~/tesis_itf/generalizacion_carga/resultado_generalizacion_carga.json):
    regla, RF de Fortescue E1 (entrenado al 75 %), RF de Fortescue E2 (deja la carga fuera), RF-MCSA E1.
(b) En vivo, registro continuo:
    - regla = decision del propio firmware (persistencia de 3 bloques), de los _resumen.json de
      ~/tesis_itf/validacion_vivo/: 0 y 25 % del 15-oct (validacion ciega 2) y 75 % de las sesiones validadas
      del 07-oct (14:04, decision en la PC; 15:29, firmware 81657f4), sumadas;
    - RF congelado = clave 'deteccion' de ~/tesis_itf/validacion_ciega2/resultado_validacion_ciega2_<fecha>.json
      (0 y 25 %; existira el 16-oct) y estudio 1 al 75 % (~/tesis_itf/comparacion_ml/resultado_comparacion_ml.json).
      Si el JSON no existe, la serie del RF solo muestra el 75 %.
Uso: /usr/bin/python3 -I fig_resultado_leve_carga.py [--fecha 20261015_20261016] [--json RUTA] [--salida DIR]"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import estilo_ieee as E  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--fecha', default='20261015_20261016')
ap.add_argument('--json', default=None, help='ruta alternativa del resultado de la validacion ciega 2')
ap.add_argument('--salida', default=E.DIR)
args = ap.parse_args()
E.DIR = args.salida
E.aplicar()
H = os.path.expanduser('~')
e2 = json.load(open(f'{H}/tesis_itf/generalizacion_carga/resultado_generalizacion_carga.json'))['resultados']
e1j = json.load(open(f'{H}/tesis_itf/comparacion_ml/resultado_comparacion_ml.json'))
ruta_vc = args.json or f'{H}/tesis_itf/validacion_ciega2/resultado_validacion_ciega2_{args.fecha}.json'
vc = json.load(open(ruta_vc)).get('deteccion', {}) if os.path.exists(ruta_vc) else {}
if not vc:
    print('AVISO: sin datos de la validacion ciega 2 en', ruta_vc, '-> la serie del RF solo muestra el 75 %')
VV = f'{H}/tesis_itf/validacion_vivo'
SES_REGLA = {'0%': ['vivo_LEVE_0%_20261015_1140'], '25%': ['vivo_LEVE_25%_20261015_1243'],
             '75%': ['vivo_LEVE_75%_20261007_1404', 'vivo_LEVE_75%_20261007_1529']}


def vivo(sesiones):
    tp = fn = 0
    for nom in sesiones:
        r = json.load(open(f'{VV}/{nom}_resumen.json'))
        tp += r['TP']
        fn += r['FN']
    return tp, tp + fn


def wilson(k, n, z=1.96):
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return 100 * p, 100 * (p - (c - h)), 100 * ((c + h) - p)


def serie(ax, xs, kn, desp, st, label):
    xs2, ys, lo, hi = [], [], [], []
    for x, (k, n) in zip(xs, kn):
        if n:
            p, a, b = wilson(k, n)
            xs2.append(x + desp); ys.append(p); lo.append(a); hi.append(b)
    ax.errorbar(xs2, ys, yerr=[lo, hi], ls='none', capsize=1.5, elinewidth=0.6, mew=0.6, label=label, **st)


fig, (axa, axb) = plt.subplots(1, 2, figsize=(E.ANCHO, (2.2) * E.ESCALA), sharey=True, gridspec_kw=dict(width_ratios=[4, 3]))
cargas = ['0%', '25%', '50%', '75%']
x = [0, 25, 50, 75]
# (a) pares
fuentes = [
    ('Regla', [e2['E2'][c]['a_regla']['sens']['LEVE'][:2] for c in cargas], -4.5,
     dict(marker='o', mfc='white', color='0.0', ms=3.5)),
    ('RF de Fortescue, entrenado al 75 %', [e2['E1'][c]['b_rf_fortescue']['sens']['LEVE'][:2] if c in e2['E1'] else (0, 0)
                             for c in cargas], -1.5, dict(marker='s', mfc='0.0', color='0.0', ms=3.2)),
    ('RF de Fortescue, dejando una carga fuera', [e2['E2'][c]['b_rf_fortescue']['sens']['LEVE'][:2] for c in cargas], 1.5,
     dict(marker='D', mfc='0.55', color='0.35', ms=3)),
    ('RF-MCSA, entrenado al 75 %', [e2['E1'][c]['c_rf_mcsa']['sens']['LEVE'][:2] if c in e2['E1'] else (0, 0)
                                  for c in cargas], 4.5, dict(marker='x', color='0.0', ms=3.5)),
]
for nom, kn, d, st in fuentes:
    serie(axa, x, kn, d, st, nom)
axa.set_title('(a) Pares de bloques (estudio 2)', pad=6)
axa.set_xticks(x)
axa.set_xlabel('Carga (%)')
axa.set_ylabel('Fallas LEVE detectadas (%)')
axa.set_ylim(-5, 105)
axa.grid(axis='y')
# (b) en vivo: regla (decision del firmware) y RF congelado
xb = [0, 25, 75]
reg = [vivo(SES_REGLA[c]) for c in ('0%', '25%', '75%')]
rfc = [(vc.get(f'LEVE_{c}', {}).get('rf', 0), vc.get(f'LEVE_{c}', {}).get('n', 0)) for c in ('0%', '25%')]
rfc.append((e1j['C1_random_forest_mejor']['det_n']['LEVE'], 60))
serie(axb, xb, reg, -3, dict(marker='o', mfc='white', color='0.0', ms=3.5), 'Regla')
serie(axb, xb, rfc, 3, dict(marker='s', mfc='0.0', color='0.0', ms=3.2), 'RF (congelado, entrenado al 75 %)')
axb.set_title('(b) En vivo, registro continuo', pad=6)
axb.set_xticks(xb)
axb.set_xlim(-12, 90)
axb.set_xlabel('Carga (%)')
axb.grid(axis='y')
h, l = axa.get_legend_handles_labels()
fig.legend(h, l, loc='lower center', ncol=2, bbox_to_anchor=(0.5, -0.12), handletextpad=0.3, columnspacing=1.0)
fig.tight_layout(w_pad=0.4)
E.guardar(fig, 'fig_resultado_leve_carga')
