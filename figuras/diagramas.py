#!/usr/bin/env python3
"""Diagramas conceptuales (no son datos): bloques del sistema actual y componentes simetricas.
Genera fig_bloques_sistema.png y fig_fortescue.png en redaccion/figuras/."""
import os, numpy as np, matplotlib
matplotlib.use('Agg'); import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
AZUL, NARANJA, TINTA, TINTA2 = '#2a78d6', '#eb6834', '#0b0b0b', '#52514e'
plt.rcParams.update({'font.family': 'Liberation Sans Narrow', 'font.size': 9.5, 'savefig.dpi': 220})

# ---------- diagrama de bloques (sistema final, firmware 299a943 + app + asistente) ----------
fig, ax = plt.subplots(figsize=(7.6, 5.2)); ax.set_xlim(0, 101); ax.set_ylim(0, 70); ax.axis('off')
def box(x, y, w, h, txt, fill='#eef4fc', edge=AZUL, fs=9.2):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.4,rounding_size=1.2', fc=fill, ec=edge, lw=1.1))
    ax.text(x + w / 2, y + h / 2, txt, ha='center', va='center', color=TINTA, linespacing=1.25, fontsize=fs)
def arrow(x1, y1, x2, y2, txt=None, dx=0, dy=1.2, color=TINTA2):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1), arrowprops=dict(arrowstyle='-|>', color=color, lw=1.1))
    if txt: ax.text((x1 + x2) / 2 + dx, (y1 + y2) / 2 + dy, txt, ha='center', va='bottom', fontsize=8, color=TINTA2)
pot = '#fdf0ea'
# fila 1: potencia (separacion de 5.5 entre cajas)
box(1, 56, 14, 10, 'Red trifásica\n≈123 V por fase\n60 Hz', pot, NARANJA)
box(20.5, 56, 13, 10, 'Variac\ntrifásico\n3.5 kVA', pot, NARANJA)
box(39, 56, 17, 10, 'Sensores\n3× ACS712-30A\n3× ZMPT101B')
box(61.5, 56, 16, 10, 'Motor ABB\nM1AA 145T-D4\n1.5 kW', pot, NARANJA)
box(84, 56, 16, 10, 'Generador Baldor\n+ resistencias\n0/25/50/75 %', pot, NARANJA)
# fila 2: instrumentacion y decision
box(1, 33, 15, 10, 'Pantalla TFT\nILI9341')
box(21.5, 28, 34, 20, 'Arduino Nano ESP32 (firmware 299a943)\n6 canales · bloques de 1.70 s\nFortescue → firma z = 100·R2/|I1|\n(1) detección: regla direccional\n(2) severidad: umbrales aprendidos', fs=8.8)
box(61.5, 38, 16, 10, 'Lazo de falla\nSSR-25DA + 5 Ω\ntaps fase C', pot, NARANJA)
box(84, 38, 16, 10, 'Driver\n2N2222', fs=9)
# fila 3: supervision
box(23.5, 3, 30, 16, 'Aplicación MotorGuard-ITF (PC)\nmonitoreo · registro · adquisición\ninyección con bloqueos\n(3) asistente RAG local', fs=8.8)
box(66, 5, 34, 12, 'Documentos de mantenimiento\n(ABB, NASA, DOE/FEMP, USBR,\nartículos y extracto de la tesis)', '#f4f3ef', TINTA2, fs=8.5)
# flechas
arrow(15.6, 61, 19.9, 61); arrow(34.1, 61, 38.4, 61); arrow(56.6, 61, 60.9, 61)
arrow(78.1, 61, 83.4, 61, 'eje', dy=0.8)
arrow(47.5, 55.4, 47.5, 48.6, 'I, V', dx=-3.5, dy=-1)
arrow(69.5, 48.6, 69.5, 55.4)
arrow(20.9, 38, 16.6, 38, 'SPI', dy=0.6)
arrow(38.5, 27.4, 38.5, 19.6, 'USB serie', dx=5.5, dy=-1)
arrow(56.1, 31, 91.5, 37.4, 'GPIO 8', dx=2, dy=-4.2)
arrow(83.4, 43, 78.1, 43)
arrow(65.4, 11, 54.1, 11, 'fragmentos', dy=0.8)
ax.text(1, 50, 'Potencia', color=NARANJA, fontsize=8.5)
ax.text(1, 22, 'Instrumentación,\ndecisión y\nsupervisión', color=AZUL, fontsize=8.5, va='top')
fig.savefig(os.path.join(OUT, 'fig_bloques_sistema.png'), bbox_inches='tight'); plt.close(fig)

# ---------- componentes simetricas ----------
a = np.exp(2j * np.pi / 3)
fig, axs = plt.subplots(1, 3, figsize=(7.0, 2.6))
def fasores(ax, vs, labs, tit, color):
    for v, l in zip(vs, labs):
        ax.annotate('', xy=(v.real, v.imag), xytext=(0, 0), arrowprops=dict(arrowstyle='-|>', color=color, lw=1.6))
        ax.text(v.real * 1.22, v.imag * 1.22, l, ha='center', va='center', fontsize=9.5, color=TINTA)
    ax.set_xlim(-1.4, 1.4); ax.set_ylim(-1.4, 1.4); ax.set_aspect('equal'); ax.axis('off')
    ax.set_title(tit, fontsize=9.5, color=TINTA)
fasores(axs[0], [1, a**2, a], ['$I_{a1}$', '$I_{b1}$', '$I_{c1}$'], 'Secuencia positiva\n(a → b → c)', AZUL)
fasores(axs[1], [0.6, 0.6 * a, 0.6 * a**2], ['$I_{a2}$', '$I_{b2}$', '$I_{c2}$'], 'Secuencia negativa\n(a → c → b)', NARANJA)
fasores(axs[2], [0.7 + 0.0j] * 3, ['', '', ''], 'Secuencia cero\n(en fase)', TINTA2)
axs[2].text(0.35, -0.35, '$I_{a0}=I_{b0}=I_{c0}$', ha='center', fontsize=9.5, color=TINTA)
fig.tight_layout(); fig.savefig(os.path.join(OUT, 'fig_fortescue.png'), bbox_inches='tight', pad_inches=0.1); plt.close(fig)
print('ok')
