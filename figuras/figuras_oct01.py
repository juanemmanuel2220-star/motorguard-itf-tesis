#!/usr/bin/env python3
"""Figuras del Cap. 4 a partir de los logs del 01-oct-2026 (datos reales del banco).
Genera en redaccion/figuras/:
  fig_firma_leve.png       firma de 10 pulsos LEVE en el plano del residuo (post-reconexion)
  fig_ruido_conexiones.png proyeccion del residuo en base sana: conexiones degradadas vs rehechas
  fig_detector_escalon.png detector direccional de escalon sobre la sesion de 10 pulsos LEVE
Uso: python3 figuras_oct01.py
"""
import re, os
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
H = '/home/luna/'
DEGR = H + 'sesion_LEVE_50carga_20261001_142637.log'
BASE = H + 'sesion_SWAP_AC_sensores_50carga_20261001_154157.log'
PULS = H + 'sesion_LEVE_postconexion_50carga_20261001_155559.log'
TH = np.radians(160.6)
AZUL, NARANJA, TINTA, TINTA2, GRID = '#2a78d6', '#eb6834', '#0b0b0b', '#52514e', '#e4e3df'
plt.rcParams.update({'font.family': 'Liberation Sans Narrow', 'font.size': 10, 'axes.edgecolor': TINTA2,
                     'axes.labelcolor': TINTA, 'xtick.color': TINTA2, 'ytick.color': TINTA2,
                     'axes.spines.top': False, 'axes.spines.right': False, 'axes.grid': True,
                     'grid.color': GRID, 'grid.linewidth': 0.6, 'savefig.dpi': 200})
RX = re.compile(r'RAW: R2=(-?[\d.]+),(-?[\d.]+) I1=([\d.]+)')


def load(f):
    t, r, fa = [], [], []
    for l in open(f):
        if '[MCSA] Motor:ON' not in l:
            continue
        m = RX.search(l); ph = re.search(r'\[(BASE|P\d+_ON|P\d+_OFF)\]', l)
        if not m or not ph:
            continue
        t.append(float(l.split('s ', 1)[0])); fa.append(ph[1])
        r.append(complex(float(m[1]), float(m[2])) / float(m[3]) * 100)
    return np.array(t), np.array(r), np.array(fa)


def proj(r):
    return (r * np.exp(-1j * TH)).real

# ---------- 1. firma LEVE (misma regla que analisis_sesion_larga.py) ----------
t, r, fa = load(PULS)
sig = []
for k in range(1, 11):
    on = np.where(fa == f'P{k}_ON')[0]
    t_on = t[on[0]] - 0.5
    pre = (t < t_on) & (t > t_on - 12) & ~np.char.endswith(fa.astype(str), '_ON')
    dur = on[t[on] - t_on >= 3.0]
    sig.append(r[dur].mean() - r[pre].mean())
sig = np.array(sig); mu = sig.mean()
fig, ax = plt.subplots(figsize=(4.6, 4.2))
ax.axhline(0, color=TINTA2, lw=0.8); ax.axvline(0, color=TINTA2, lw=0.8)
ax.annotate('', xy=(mu.real, mu.imag), xytext=(0, 0),
            arrowprops=dict(arrowstyle='-|>', color=TINTA, lw=1.6))
ax.scatter(sig.real, sig.imag, s=42, color=AZUL, edgecolor='white', linewidth=1.5, zorder=3)
ax.text(-0.42, -0.2, f'media de 10 pulsos:\n{abs(mu):.2f} pp a {np.degrees(np.angle(mu)):.1f}°', ha='center', va='center', fontsize=9, color=TINTA)
ax.set_xlabel(r'$\Delta\,\mathrm{Re}\{R_2/|I_1|\}$ (pp)'); ax.set_ylabel(r'$\Delta\,\mathrm{Im}\{R_2/|I_1|\}$ (pp)')
ax.set_aspect('equal'); lim = 1.15
ax.set_xlim(-lim, 0.25); ax.set_ylim(-0.35, 0.75)
fig.tight_layout(); fig.savefig(os.path.join(OUT, 'fig_firma_leve.png')); plt.close(fig)
print(f'firma: |media|={abs(mu):.2f} pp ang={np.degrees(np.angle(mu)):.1f} deg, sd|dr|={abs(sig).std():.2f}')

# ---------- 2. ruido de base: degradadas vs rehechas (mismos 10 min, misma escala) ----------
td, rd, fd = load(DEGR); tb, rb, fb = load(BASE)
xd = proj(rd[fd == 'BASE']); tdd = td[fd == 'BASE']
xb = proj(rb[fb == 'BASE']); tbb = tb[fb == 'BASE']
xd = xd[tdd - tdd[0] <= 600]; tdd = tdd[tdd - tdd[0] <= 600]
fig, axs = plt.subplots(2, 1, figsize=(6.3, 4.0), sharex=True, sharey=True)
for ax, tt, xx, tit in ((axs[0], tdd, xd, 'Conexiones degradadas (protoboard original)'),
                        (axs[1], tbb, xb, 'Conexiones rehechas')):
    ax.plot((tt - tt[0]) / 60, xx - xx.mean(), color=AZUL, lw=1.2)
    ax.set_title(f'{tit} · σ = {xx.std():.2f} pp', loc='left', fontsize=10, color=TINTA)
    ax.set_ylabel('pp')
axs[1].set_xlabel('Tiempo en base sana (min)')
fig.tight_layout(); fig.savefig(os.path.join(OUT, 'fig_ruido_conexiones.png')); plt.close(fig)
print(f'ruido: degradadas sd={xd.std():.3f} pp, rehechas sd={xb.std():.3f} pp')

# ---------- 3. detector de escalon ----------
A, G, N = 20, 8, 2
T = max(xb[i - N + 1:i + 1].mean() - xb[i - A:i - G].mean() for i in range(A, len(xb)))
x = proj(r)
stat = np.full(len(x), np.nan); al = np.zeros(len(x), bool); on_alarm = False; ref = None
for i in range(A, len(x)):
    cur = x[i - N + 1:i + 1].mean()
    if not on_alarm:
        stat[i] = cur - x[i - A:i - G].mean()
        if stat[i] > T:
            on_alarm, ref = True, x[i - A:i - G].mean()
    else:
        stat[i] = cur - ref
        if stat[i] < T / 2:
            on_alarm = False
    al[i] = on_alarm
tt = t - t[0]
fig, ax = plt.subplots(figsize=(6.3, 2.9))
for k in range(1, 11):
    idx = np.where(fa == f'P{k}_ON')[0]
    ax.axvspan(tt[idx[0]] - 0.5, tt[idx[-1]] + 0.5, color=NARANJA, alpha=0.18, lw=0)
    ax.text(tt[idx[0]], 1.58, f'P{k}', fontsize=7.5, color=TINTA2)
ax.plot(tt, stat, color=AZUL, lw=1.2)
ax.axhline(T, color=TINTA, lw=1.0, ls='--'); ax.text(tt[A], T + 0.04, f'umbral T = {T:.2f} pp', ha='left', fontsize=8.5, color=TINTA)
ys = np.where(al, -0.38, np.nan); ax.plot(tt, ys, color=TINTA, lw=3, solid_capstyle='butt')
ax.text(tt[A], -0.30, 'alarma activa', fontsize=8, color=TINTA2)
ax.set_ylim(-0.45, 1.7); ax.set_xlabel('Tiempo (s)'); ax.set_ylabel('Estadístico de escalón (pp)')
fig.tight_layout(); fig.savefig(os.path.join(OUT, 'fig_detector_escalon.png')); plt.close(fig)
print(f'detector: T={T:.2f}')
