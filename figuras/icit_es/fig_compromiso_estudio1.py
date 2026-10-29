# Copia para la tesis de ~/Documents/TESIS/articulo_icit2027/figuras/fig_compromiso_estudio1.py: solo cambian textos y formato.
#!/usr/bin/env python3
"""Fig.: compromiso falsas alarmas / deteccion LEVE en operacion continua al 75 % (estudio 1).
Datos: ~/tesis_itf/comparacion_ml/resultado_comparacion_ml.json (B_curva: regla u x k; C1 curva: RF s x k).
Se dibuja la frontera de Pareto de cada detector y sus puntos de operacion declarados.
Uso: /usr/bin/python3 -I fig_compromiso_estudio1.py"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import estilo_ieee as E  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

E.aplicar()
d = json.load(open(os.path.expanduser('~/tesis_itf/comparacion_ml/resultado_comparacion_ml.json')))


def pareto(pts):
    """Puntos no dominados: menos FA/h y mas LEVE."""
    pts = sorted(pts, key=lambda p: (p[0], -p[1]))
    fr, mejor = [], -1
    for fa, lev in pts:
        if lev > mejor:
            fr.append((fa, lev))
            mejor = lev
    return fr


fig, ax = plt.subplots(figsize=(E.ANCHO, (2.2) * E.ESCALA))
series = [('Regla de Fortescue (umbral, persistencia)', d['B_curva'], 'o', 'none', '-'),
          ('Random Forest (probabilidad, persistencia)', d['C1_random_forest_curva'], 's', '0.0', '--')]
for nom, curva, mk, mfc, ls in series:
    pts = [(c['fa_h'], c['det_n']['LEVE']) for c in curva]
    ax.plot([p[0] for p in pts], [p[1] for p in pts], ls='none', marker=mk, mfc='none', color='0.75', ms=2.5,
            mew=0.4, zorder=1)
    fr = pareto(pts)
    ax.step([p[0] for p in fr], [p[1] for p in fr], where='post', color='0.0', ls=ls, lw=0.9, zorder=2)
    ax.plot([p[0] for p in fr], [p[1] for p in fr], ls='none', marker=mk, mfc=mfc, color='0.0', ms=3.5, mew=0.6,
            label=nom, zorder=3)
for clave, txt, tx, ty in (('A_firmware', 'Regla: 0.40 pp, 3 bloques', 6.2, 38), ('C1_random_forest_mejor', 'RF: s = 0.55, 3 bloques', 0.25, 56.5)):
    p = d[clave]
    ax.plot(p['fa_h'], p['det_n']['LEVE'], marker='*', color='0.0', ms=7, mew=0.3, mfc='white', zorder=4)
    ax.annotate(txt, (p['fa_h'], p['det_n']['LEVE']), xytext=(tx, ty), fontsize=7,
                arrowprops=dict(arrowstyle='-', lw=0.4, color='0.3'))
ax.set_xlim(0, 12)
ax.set_ylim(0, 63)
ax.set_xlabel('Falsas alarmas por hora (operación sana, 2.76 h)')
ax.set_ylabel('Fallas LEVE detectadas (de 60)')
ax.grid(True)
ax.legend(loc='lower right', handletextpad=0.3)
fig.tight_layout()
E.guardar(fig, 'fig_compromiso_estudio1')
