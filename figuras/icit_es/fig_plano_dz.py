# Copia para la tesis de ~/Documents/TESIS/articulo_icit2027/figuras/fig_plano_dz.py: solo cambian textos y formato.
#!/usr/bin/env python3
"""Fig.: firma de secuencia negativa dz por clase en el plano complejo, una grafica por carga.
Datos: dataset multiclase (607 pares), dz por par con analisis_generalizacion_carga.cargar() (solo lee).
Uso: /usr/bin/python3 -I fig_plano_dz.py"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import estilo_ieee as E  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import analisis_generalizacion_carga as G  # noqa: E402

E.aplicar()
filas, *_ = G.cargar()
fig, axs = plt.subplots(1, 4, figsize=(E.ANCHO, (2.75) * E.ESCALA), sharex=True, sharey=True)
axs = axs.reshape(1, 4)
ang = math.radians(G.ANG_FALLA)
u = np.array([math.cos(ang), math.sin(ang)])           # direccion de falla
n = np.array([-u[1], u[0]])                             # perpendicular
for ax, carga in zip(axs.flat, G.CARGAS):
    ax.axhline(0, color='0.85', lw=0.4, zorder=0)
    ax.axvline(0, color='0.85', lw=0.4, zorder=0)
    # direccion -81.4 deg y frontera P = 0.40 pp
    ax.plot([0, 8.2 * u[0]], [0, 8.2 * u[1]], color='0.4', lw=0.6, ls='--', zorder=1)
    p0 = G.UMBRAL * u
    ax.plot([p0[0] - 3 * n[0], p0[0] + 3 * n[0]], [p0[1] - 3 * n[1], p0[1] + 3 * n[1]], color='0.0', lw=0.6,
            ls=':', zorder=1)
    for cl in ['SANO', 'LEVE', 'INTER', 'SEVERA']:
        dz = np.array([f['dz'] for f in filas if f['clase'] == cl and f['carga'] == carga])
        st = E.CLASE[cl]
        ax.plot(dz.real, dz.imag, ls='none', marker=st['marker'], color=st['color'], mfc=st['mfc'],
                ms=st['ms'] * 0.8, mew=0.4, alpha=0.8, label=st['label'], zorder=2)
    ax.set_title(f"Carga {E.CARGA_EN[carga]}", pad=6)
    ax.set_aspect('equal')
ax = axs[0, 0]
ax.set_xlim(-1.3, 2.2)
ax.set_ylim(-8.2, 1.0)
for a in axs[0]:
    a.set_xticks([-1, 0, 1, 2])
fig.supxlabel(r'Re$\{\Delta z\}$ (pp)', y=0.075, fontsize=8)
for a in axs[:, 0]:
    a.set_ylabel(r'Im$\{\Delta z\}$ (pp)')
axs[0, 3].text(2.1, -3.6, r'$-81.4^\circ$', fontsize=7, color='0.3', ha='right')
axs[0, 3].text(0.95, 0.1, r'$P=0.40$', fontsize=7)   # junto a la frontera, fuera de la nube del motor sano
h, l = axs[0, 0].get_legend_handles_labels()
fig.legend(h, l, loc='lower center', ncol=4, bbox_to_anchor=(0.5, -0.03), handletextpad=0.2, columnspacing=0.8,
           markerscale=1.4)
fig.tight_layout(rect=(0, 0.07, 1, 1), w_pad=0.2)
E.guardar(fig, 'fig_plano_dz')
