#!/usr/bin/env python3
"""
DIAGNOSTICO POST HOC (no declarado, 14-oct-2026): de donde sale el LEVE 0 % = 17/50 de
exploracion_rf_cargas_pares.py? El estudio 2 declarado (commit 61c09f1) no lo reprodujo con pares.
Variantes del RF (mismos hiperparametros, entrenado con los 13 grupos continuos, aplicado a los pares
del dataset con la misma aproximacion de exploracion_rf_cargas_pares.py):
  (a) igual que el 12-oct (5 rezagos rellenados con 0 + dispersion imputada);
  (b) sin las columnas dI1;
  (c) solo el bloque actual (P, Q, |dz|, dI1, dV1, |dV2|), sin rezagos ni dispersion;
  (d) solo el bloque actual y sin dI1.
10 semillas. Solo lee logs. Orienta la redaccion; no es un resultado.
"""
import os, sys, statistics
import numpy as np
import sklearn
from sklearn.ensemble import RandomForestClassifier
sys.path.insert(0, os.path.expanduser('~'))
import comparacion_ml_deteccion as C
import exploracion_rf_cargas_pares as E

NF = 6
def cols(variante):
    todas = list(range(NF * C.LAGS + 1))
    if variante == 'a': return todas
    if variante == 'b': return [i for i in todas if i == NF * C.LAGS or i % NF != 3]
    if variante == 'c': return list(range(NF))
    if variante == 'd': return [0, 1, 2, 4, 5]

datos = C.construir(C.GRUPOS)
X = np.array([f['x'] for d in datos.values() for f in d['filas'] if f['y'] is not None])
y = np.array([f['y'] for d in datos.values() for f in d['filas'] if f['y'] is not None])
disp_med = float(np.median(X[y == 0, -1]))
pares = {}
for log in E.SESIONES:
    nom = os.path.basename(log).replace('cap_ENTRELAZADA_', '').split('_2026')[0]
    pares[nom] = [np.array(E.feats(pre, fal, disp_med)) for pre, fal in E.pulsos_aprox(log)]

print(f"sklearn {sklearn.__version__}", flush=True)
TODO, CORTES, n0 = [], {}, 0
for nom, ps in pares.items():
    CORTES[nom] = []
    for F in ps:
        TODO.append(F); CORTES[nom].append((n0, n0 + len(F))); n0 += len(F)
TODO = np.vstack(TODO)
res = {v: {nom: [] for nom in pares} for v in 'abcd'}
for v in 'abcd':
    cs = cols(v)
    for sem in range(10):
        rf = RandomForestClassifier(n_estimators=300, max_depth=6, class_weight='balanced', min_samples_leaf=5,
                                    n_jobs=-1, random_state=sem).fit(X[:, cs], y)
        prob = rf.predict_proba(TODO[:, cs])[:, 1]
        for nom, ps in pares.items():
            det = 0
            for F, (a, b) in zip(ps, CORTES[nom]):
                p = prob[a:b]
                det += any(all(q >= 0.55 for q in p[i:i + 3]) for i in range(len(p) - 2))
            res[v][nom].append(det)
print(f"{'sesion':11}" + "".join(f"{v:>16}" for v in ('a 12-oct', 'b sin dI1', 'c bloque', 'd bloque-dI1')) + f"{'regla':>8}")
for nom, ps in pares.items():
    fila = f"{nom:11}"
    for v in 'abcd':
        d = res[v][nom]
        fila += f"{min(d):>6}-{max(d):<3}/{len(ps):<4}"
    reg = sum(any(all(q >= 0.40 for q in F[i:i + 3, 0]) for i in range(len(F) - 2)) for F in ps)
    print(fila + f"{reg:>5}/{len(ps)}", flush=True)
