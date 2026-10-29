#!/usr/bin/env python3
"""
EXPLORACION APROXIMADA (no declarada; orientativa): como se comportaria el Random Forest de
comparacion_ml_deteccion.py ante fallas a cargas que no vio al entrenarse (0/25/50 %).

Problema: los logs del dataset multiclase no son continuos (captura_dataset_multiclase.py vacia el bufer
entre pulsos), asi que no existe la referencia movil de 6-11 s ni los 5 bloques previos.
Aproximacion: en cada pulso se usa como referencia el (los) bloque(s) sano(s) que el script tomo justo
antes de encender el SSR; los rezagos anteriores al pulso se llenan con 0 (valor tipico del sano) y la
dispersion de 30 s con la mediana del entrenamiento. La regla del firmware (P >= 0.40, 3 bloques) se
evalua sobre EXACTAMENTE las mismas caracteristicas aproximadas, para que la comparacion sea justa.
Control de la aproximacion: las sesiones al 75 % deben dar resultados parecidos a los de la validacion
en vivo (LEVE 48/60, INTER 22/22 con el RF).
"""
import glob
import math
import os
import re
import statistics
import sys

import numpy as np
from sklearn.ensemble import RandomForestClassifier

sys.path.insert(0, os.path.expanduser('~'))
import comparacion_ml_deteccion as C  # noqa: E402

DS = os.path.expanduser('~/tesis_itf/dataset')
SESIONES = sorted(glob.glob(f'{DS}/cap_ENTRELAZADA_LEVE_*_20261006_*_serial.log')
                  + glob.glob(f'{DS}/cap_ENTRELAZADA_INTER_*_20261007_*_serial.log')
                  + glob.glob(f'{DS}/cap_ENTRELAZADA_SEVERA_*_20261008_*_serial.log'))
ROT = complex(math.cos(-C.ANG), math.sin(-C.ANG))


def pulsos_aprox(log):
    """Por cada pulso: (bloques previos sanos, bloques con falla) dentro del mismo tramo continuo."""
    bloques, t_ons = [], []
    for l in open(log, errors='ignore'):
        m = C.RE_B.search(l)
        if m:
            g = m.groups()
            bloques.append(dict(t=float(g[0]), motor=g[1], r2=complex(float(g[2]), float(g[3])), i1=float(g[4]),
                                v2=complex(float(g[5]), float(g[6])), v1=float(g[7])))
        elif C.RE_ON.search(l):
            t_ons.append(float(C.RE_ON.search(l).group(1)))
    segs, ini = [], 0
    for i in range(1, len(bloques) + 1):
        if i == len(bloques) or bloques[i]['t'] - bloques[i - 1]['t'] > 5.0:
            segs.append(bloques[ini:i])
            ini = i
    out = []
    for t_on in t_ons:
        seg = next((s for s in segs if s[0]['t'] <= t_on + 0.5 and s[-1]['t'] > t_on + C.T_EXCL_INI), None)
        if not seg:
            continue
        pre = [b for b in seg if b['t'] <= t_on and b['motor'] == 'ON']
        fal = [b for b in seg if b['t'] > t_on + C.T_EXCL_INI and b['motor'] == 'ON']
        if pre and len(fal) >= 3:
            out.append((pre, fal))
    return out


def feats(pre, fal, disp_med):
    zr = C.med_c([b['r2'] / b['i1'] * 100 for b in pre])
    i1r = statistics.median([b['i1'] for b in pre])
    v1r = statistics.median([b['v1'] for b in pre])
    v2r = C.med_c([b['v2'] for b in pre])
    cs = []
    for b in fal:
        dz = (b['r2'] / b['i1'] * 100 - zr) * ROT
        cs.append([dz.real, dz.imag, abs(dz), (b['i1'] - i1r) / i1r * 100, (b['v1'] - v1r) / v1r * 100,
                   abs(b['v2'] - v2r) / b['v1'] * 100])
    filas = []
    for i in range(len(cs)):
        v = []
        for k in range(C.LAGS):
            v += cs[i - k] if i - k >= 0 else [0.0] * 6
        filas.append(v + [disp_med])
    return filas


def main():
    datos = C.construir(C.GRUPOS)
    X = np.array([f['x'] for d in datos.values() for f in d['filas'] if f['y'] is not None])
    y = np.array([f['y'] for d in datos.values() for f in d['filas'] if f['y'] is not None])
    disp_med = float(np.median(X[y == 0, -1]))
    rf = RandomForestClassifier(n_estimators=300, max_depth=6, class_weight='balanced', min_samples_leaf=5,
                                n_jobs=-1, random_state=0).fit(X, y)
    print("EXPLORACION APROXIMADA (referencia = bloque sano previo al pulso). RF entrenado con los 13 grupos.")
    print(f"{'sesion':32} {'pulsos':>6} {'regla P>=0.40 x3':>17} {'RF p>=0.55 x3':>14} {'P med':>6} {'dI1 med':>8} {'p_RF med':>8}")
    for log in SESIONES:
        ps = pulsos_aprox(log)
        det_r = det_rf = 0
        pm, dm, prm = [], [], []
        for pre, fal in ps:
            F = feats(pre, fal, disp_med)
            prob = rf.predict_proba(np.array(F))[:, 1]
            P = [f[0] for f in F]
            det_r += any(all(p >= 0.40 for p in P[i:i + 3]) for i in range(len(P) - 2))
            det_rf += any(all(p >= 0.55 for p in prob[i:i + 3]) for i in range(len(prob) - 2))
            pm += P
            dm += [f[3] for f in F]
            prm += list(prob)
        nom = os.path.basename(log).replace('cap_ENTRELAZADA_', '').replace('_serial.log', '')
        n = len(ps)
        print(f"{nom:32} {n:6} {det_r:>8}/{n:<3} ({100 * det_r / n:3.0f}%) {det_rf:>5}/{n:<3} ({100 * det_rf / n:3.0f}%) "
              f"{statistics.median(pm):6.2f} {statistics.median(dm):+8.2f} {statistics.median(prm):8.2f}")


if __name__ == '__main__':
    main()
