#!/usr/bin/env python3
"""Analisis offline de una sesion larga (base + pulsos) con fasores crudos RAW."""
import re, sys, numpy as np
f = sys.argv[1]
RX = re.compile(r'RAW: R2=(-?[\d.]+),(-?[\d.]+) I1=([\d.]+) V2=(-?[\d.]+),(-?[\d.]+) V1=([\d.]+)')
B = []
for l in open(f):
    if '[MCSA] Motor:ON' not in l: continue
    m = RX.search(l); fase = re.search(r'\[(BASE|P\d+_ON|P\d+_OFF)\]', l)
    if not m or not fase: continue
    g = lambda k: float(re.search(rf'\b{k}=(-?[\d\.]+)', l)[1])
    i1 = float(m[3]); v1 = float(m[6])
    B.append(dict(t=float(l.split('s ', 1)[0]), fase=fase[1],
                  r=complex(float(m[1]), float(m[2])) / i1 * 100, v2=complex(float(m[4]), float(m[5])) / v1 * 100,
                  i1=i1, ia=g('IA'), ib=g('IB'), ic=g('IC'), va=g('VA'), e2=g('E2')))
t = np.array([b['t'] for b in B]); r = np.array([b['r'] for b in B]); v2 = np.array([b['v2'] for b in B])
fase = np.array([b['fase'] for b in B]); base = fase == 'BASE'
print(f'Bloques: {len(B)} (BASE {base.sum()}, {(t[base][-1]-t[base][0])/60:.1f} min)')
rb = r[base]
print('\n== 1. Ruido del residuo en BASE ==')
print(f'r = R2/|I1|: media {rb.mean():.2f} pp (|r|={abs(rb.mean()):.2f}, ang {np.degrees(np.angle(rb.mean())):.0f} deg)')
d1 = np.diff(rb)   # ruido rapido bloque a bloque
u = rb.mean() / abs(rb.mean())
rad = (d1 * np.conj(u)).real; tan = (d1 * np.conj(u)).imag
print(f'Cambio bloque a bloque: sd radial {rad.std():.3f}  sd tangencial {tan.std():.3f} pp  (rotacion de referencia => domina tangencial)')
for w in (1, 5, 35, 175):
    m = np.convolve(rb, np.ones(w)/w, 'valid'); print(f'  promedio {w:3d} bloques ({w*1.7:5.0f} s): sd |desv| = {np.std(abs(m-m.mean())):.3f}  sd comp re {m.real.std():.3f} im {m.imag.std():.3f}')
X = np.array([[b['ia'], b['ib'], b['ic'], b['va']] for b in B])[base]
for i, n in enumerate(['IA', 'IB', 'IC', 'VA']):
    print(f'  corr(re r, {n})={np.corrcoef(rb.real, X[:,i])[0,1]:+.2f}  corr(im r, {n})={np.corrcoef(rb.imag, X[:,i])[0,1]:+.2f}')
print(f'  corr(r, V2): re {np.corrcoef(rb.real, v2[base].real)[0,1]:+.2f} im {np.corrcoef(rb.imag, v2[base].imag)[0,1]:+.2f}')

print('\n== 2. Firma de los pulsos (media >=3 s tras ON menos media 10 s previos) ==')
sig = []
for k in range(1, 20):
    on = np.where(fase == f'P{k}_ON')[0]
    if len(on) == 0: break
    t_on = t[on[0]] - 0.5
    pre = (t < t_on) & (t > t_on - 12) & ~np.char.endswith(fase.astype(str), '_ON')
    dur = on[t[on] - t_on >= 3.0]
    if len(dur) == 0 or pre.sum() == 0: continue
    s = r[dur].mean() - r[pre].mean(); sig.append(s)
    print(f'P{k}: |dr|={abs(s):.2f} pp  ang={np.degrees(np.angle(s)):6.1f} deg  (n_dur={len(dur)}, n_pre={pre.sum()})')
sig = np.array(sig)
if len(sig):
    th = np.angle(sig.mean())
    print(f'Media: |dr|={abs(sig.mean()):.2f} pp ang={np.degrees(th):.1f} deg | dispersion ang ±{np.degrees(np.std(np.angle(sig*np.exp(-1j*th)))):.1f} deg | |dr| sd {abs(sig).std():.2f}')
np.savez('/tmp/claude-1000/-home-luna/b6437c26-0f05-4c91-8ee8-1400b33559a8/scratchpad/sesion.npz', t=t, r=r, v2=v2, fase=fase.astype(str), sig=sig)
