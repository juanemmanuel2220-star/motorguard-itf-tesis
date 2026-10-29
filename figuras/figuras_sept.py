#!/usr/bin/env python3
"""Figuras de la campana de inyecciones del 28-29 sep 2026 y del ensayo de puente manual.
Datos: ~/ensayo_10_inyecciones_*.csv y ~/ensayo_puente_manual_vivo_20260929_135303.csv
Genera en redaccion/figuras/: fig_campana_sept.png, fig_cusum_75.png, fig_puente_manual.png
Criterio de deteccion (el del script de ensayo): pred == LEVE o cusum_s >= 5 durante FALLA_F1.
"""
import glob, os
from datetime import datetime
import numpy as np, pandas as pd, matplotlib
matplotlib.use('Agg'); import matplotlib.pyplot as plt
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
AZUL, NARANJA, TINTA, TINTA2, GRID = '#2a78d6', '#eb6834', '#0b0b0b', '#52514e', '#e4e3df'
plt.rcParams.update({'font.family': 'Liberation Sans Narrow', 'font.size': 10, 'axes.edgecolor': TINTA2,
                     'axes.labelcolor': TINTA, 'xtick.color': TINTA2, 'ytick.color': TINTA2,
                     'axes.spines.top': False, 'axes.spines.right': False, 'savefig.dpi': 200})

# ---------- 1. deteccion por corrida, separando ciclos con alarma previa ----------
MESES = {9: 'sep', 10: 'oct'}
filas = []
for f in glob.glob('/home/luna/ensayo_10_inyecciones_*.csv'):
    d = pd.read_csv(f)
    ts = datetime.strptime(f[-19:-4], '%Y%m%d_%H%M%S')
    carga = d['carga'].iloc[0] if 'carga' in d.columns else 's/r'
    n = nueva = previa = 0
    for _, x in d[d.fase == 'FALLA_F1'].groupby('ciclo'):
        n += 1
        ya = (x.pred.iloc[0] == 'LEVE') or (x.cusum_s.iloc[0] >= 5)       # alarma activa al iniciar el pulso
        hit = ((x.pred == 'LEVE') | (x.cusum_s >= 5)).any()
        previa += ya; nueva += (hit and not ya)
    filas.append((ts, carga, n, nueva, previa))
filas.sort()
fig, ax = plt.subplots(figsize=(6.3, 4.4))
y = np.arange(len(filas))[::-1]
for yi, (ts, carga, n, nueva, previa) in zip(y, filas):
    ax.barh(yi, nueva, height=0.62, color=AZUL, label='Detección nueva' if yi == y[0] else None)
    ax.barh(yi, previa, left=nueva + 0.08 if nueva else 0, height=0.62, color=NARANJA,
            label='Alarma ya activa al iniciar el pulso' if yi == y[0] else None)
    ax.text(max(r[2] for r in filas) + 0.25, yi, f'{nueva} de {n - previa}', va='center', fontsize=8.5, color=TINTA)   # columna comun
etq = [f"{ts.day:02d}-{MESES[ts.month]} {ts:%H:%M} · {('carga ' + c) if c != 's/r' else 'sin registro de carga'}" for ts, c, *_ in filas]
ax.set_yticks(y, etq, fontsize=9)
ax.set_xlim(0, 11.8); ax.set_xticks(range(0, 11, 2)); ax.set_xlabel('Ciclos de inyección')
ax.grid(axis='x', color=GRID, lw=0.6); ax.set_axisbelow(True)
ax.legend(loc='lower center', bbox_to_anchor=(0.45, 1.0), ncol=2, frameon=False, fontsize=9)
fig.tight_layout(); fig.savefig(os.path.join(OUT, 'fig_campana_sept.png')); plt.close(fig)
tn = sum(r[2] for r in filas); tp = sum(r[4] for r in filas); tnu = sum(r[3] for r in filas)
print(f'campana: {tn} ciclos, {tp} con alarma previa, {tnu} detecciones nuevas de {tn - tp}')

# ---------- 2. trazas CUSUM de dos corridas al 75 % ----------
pares = [('/home/luna/ensayo_10_inyecciones_75carga_20260929_112750.csv', '29-sep 11:27 · alarma activa al iniciar 8 de los 10 pulsos'),
         ('/home/luna/ensayo_10_inyecciones_75carga_20260929_114830.csv', '29-sep 11:48 · ninguno de los 10 pulsos detectado')]
fig, axs = plt.subplots(2, 1, figsize=(6.3, 4.2), sharey=True)
for ax, (f, tit) in zip(axs, pares):
    d = pd.read_csv(f); t = d.t - d.t.iloc[0]
    for _, x in d[d.fase == 'FALLA_F1'].groupby('ciclo'):
        tt = x.t - d.t.iloc[0]; ax.axvspan(tt.min() - 0.8, tt.max() + 0.8, color=NARANJA, alpha=0.18, lw=0)
    ax.plot(t, d.cusum_s, color=AZUL, lw=1.2)
    ax.axhline(5, color=TINTA, lw=1, ls='--'); ax.text(t.iloc[-1], 5.25, 'H = 5', ha='right', fontsize=8.5, color=TINTA)
    ax.set_title(tit, loc='left', fontsize=10, color=TINTA); ax.set_ylabel('$S_t$'); ax.set_ylim(-0.5, 16)
    ax.grid(axis='y', color=GRID, lw=0.6)
axs[1].set_xlabel('Tiempo desde el inicio de la corrida (s)')
fig.tight_layout(); fig.savefig(os.path.join(OUT, 'fig_cusum_75.png')); plt.close(fig)

# ---------- 3. puente manual ----------
d = pd.read_csv('/home/luna/ensayo_puente_manual_vivo_20260929_135303.csv')
fig, axs = plt.subplots(2, 1, figsize=(6.3, 3.9), sharex=True)
leve = (d.pred == 'LEVE').values
for ax in axs:
    i = 0
    while i < len(d):
        if leve[i]:
            j = i
            while j + 1 < len(d) and leve[j + 1]:
                j += 1
            ax.axvspan(d.t_rel.iloc[i] - 0.6, d.t_rel.iloc[j] + 0.6, color=NARANJA, alpha=0.18, lw=0)
            i = j + 1
        else:
            i += 1
    ax.grid(axis='y', color=GRID, lw=0.6)
axs[0].plot(d.t_rel, d.e2, color=AZUL, lw=1.2); axs[0].set_ylabel('$e_2$ (%)')
axs[1].plot(d.t_rel, d.cusum_s, color=AZUL, lw=1.2); axs[1].axhline(5, color=TINTA, lw=1, ls='--')
axs[1].text(d.t_rel.iloc[-1], 5.25, 'H = 5', ha='right', fontsize=8.5, color=TINTA)
axs[1].set_ylabel('$S_t$'); axs[1].set_xlabel('Tiempo (s)')
axs[0].set_title('Franjas: intervalos en que el detector indicó LEVE', loc='left', fontsize=9.5, color=TINTA2)
fig.tight_layout(); fig.savefig(os.path.join(OUT, 'fig_puente_manual.png')); plt.close(fig)
print('ok')
