# Copia para la tesis de ~/Documents/TESIS/articulo_icit2027/figuras/fig_delta_i1.py: solo cambian textos y formato.
#!/usr/bin/env python3
"""Fig.: cambio relativo de |I1| durante la falla por severidad y carga (por que dI1 no sirve en vacio).
Datos: dataset multiclase, dI1 por par con analisis_generalizacion_carga.cargar() (solo lee).
Mediana y rango intercuartil por celda. Uso: /usr/bin/python3 -I fig_delta_i1.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import estilo_ieee as E  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import analisis_generalizacion_carga as G  # noqa: E402

E.aplicar()
filas, *_ = G.cargar()
x = np.array([0, 25, 50, 75])
fig, ax = plt.subplots(figsize=(E.ANCHO, (2.1) * E.ESCALA))
ax.axhline(0, color='0.75', lw=0.5, zorder=0)
desp = {'SANO': -2.4, 'LEVE': -0.8, 'INTER': 0.8, 'SEVERA': 2.4}
for cl in ['SANO', 'LEVE', 'INTER', 'SEVERA']:
    med, lo, hi = [], [], []
    for c in G.CARGAS:
        v = np.array([f['dI1'] for f in filas if f['clase'] == cl and f['carga'] == c])
        q1, q2, q3 = np.percentile(v, [25, 50, 75])
        med.append(q2); lo.append(q2 - q1); hi.append(q3 - q2)
    st = E.CLASE[cl]
    ax.errorbar(x + desp[cl], med, yerr=[lo, hi], marker=st['marker'], color=st['color'], mfc=st['mfc'],
                ms=st['ms'] + 0.5, mew=0.6, lw=0.8, capsize=1.5, elinewidth=0.6, label=st['label'])
ax.set_xticks(x)
ax.set_xticklabels(['0', '25', '50', '75'])
ax.set_xlabel('Carga (% de la nominal)')
ax.set_ylabel(r'$\Delta|I_1|$ durante el bloque (%)')
ax.grid(axis='y')
ax.legend(loc='upper left', ncol=2, handletextpad=0.3, columnspacing=0.8)
ax.set_ylim(-0.8, 6.2)
fig.tight_layout()
E.guardar(fig, 'fig_delta_i1')
