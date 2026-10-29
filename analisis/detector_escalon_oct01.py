#!/usr/bin/env python3
"""Detector direccional de escalon (fuera de linea) sobre los logs del 01-oct-2026.
Reproduce el analisis de la sesion de trabajo del 01-oct (22:05): proyeccion del
residuo R2/|I1| sobre la direccion de la firma LEVE (160.6 deg), referencia de
A..G bloques atras, media de N bloques, umbral T = maximo en la base de 10 min
(sesion SWAP, 0 falsas alarmas por construccion), retorno en T/2.
Uso: python3 detector_escalon_oct01.py
"""
import re
import numpy as np

BASE = '/home/luna/sesion_SWAP_AC_sensores_50carga_20261001_154157.log'
PULS = '/home/luna/sesion_LEVE_postconexion_50carga_20261001_155559.log'
RX = re.compile(r'RAW: R2=(-?[\d.]+),(-?[\d.]+) I1=([\d.]+)')
TH = np.radians(160.6)
A, G, N = 20, 8, 2


def load(f):
    t, r, fa = [], [], []
    for l in open(f):
        if '[MCSA] Motor:ON' not in l:
            continue
        m = RX.search(l); ph = re.search(r'\[(BASE|P\d+_ON|P\d+_OFF)\]', l)
        if not m or not ph:
            continue
        t.append(float(l.split('s ', 1)[0]))
        r.append(complex(float(m[1]), float(m[2])) / float(m[3]) * 100)
        fa.append(ph[1])
    return np.array(t), (np.array(r) * np.exp(-1j * TH)).real, np.array(fa)


def run(x, T, Toff):
    al, ref, out = False, None, []
    for i in range(len(x)):
        if i < A:
            out.append(False); continue
        cur = x[i - N + 1:i + 1].mean()
        if not al:
            ref_i = x[i - A:i - G].mean()
            if cur - ref_i > T:
                al, ref = True, ref_i
        elif cur - ref < Toff:
            al = False
        out.append(al)
    return np.array(out)


_, xb, fb = load(BASE)
xb = xb[fb == 'BASE']
T = max(xb[i - N + 1:i + 1].mean() - xb[i - A:i - G].mean() for i in range(A, len(xb)))
t, x, fa = load(PULS)
al = run(x, T, T / 2)
on = [i for i in range(1, len(al)) if al[i] and not al[i - 1]]
det = sorted({int(re.search(r'\d+', fa[i])[0]) for i in on if fa[i].endswith('_ON')})
extra = [fa[i] for i in on if not fa[i].endswith('_ON')]
lat = [t[i] - t[np.where(fa == fa[i])[0][0]] + 0.5 for i in on if fa[i].endswith('_ON')]
print(f'Base sana: {len(xb)} bloques ({len(xb)*1.7/60:.1f} min) -> umbral T = {T:.2f} pp, ruido sd = {xb.std():.3f} pp')
print(f'Pulsos detectados durante ON: {len(det)}/10 {det} | latencia media {np.mean(lat):.1f} s')
print(f'Alarmas fuera de pulso: {extra}')
