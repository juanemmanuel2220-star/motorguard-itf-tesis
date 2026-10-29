#!/usr/bin/env python3
"""
MotorGuard-ITF: clasificador de severidad (etapa 2) - entrenamiento y validacion
--------------------------------------------------------------------------------
Diseno declarado ANTES de ver resultados (08-oct-2026):

Datos: pares SANO/FALLA de ~/tesis_itf/dataset (sin piloto/), capturados el 06-08 oct con
la calibracion del 06-oct. Clases LEVE (taps 1.7 A), INTER (3.3-3.7 A), SEVERA (4.8-5.2 A);
cargas 0/25/50/75 %. La etapa 2 solo clasifica pares con falla (la deteccion es la etapa 1).

Variables (las que el firmware ya calcula en cada bloque):
  mag  = |dR2| / |I1| (pp), dR2 = R2_falla - R2_sano
  proy = Re{dR2 * exp(-j*(-81.4 deg))} (pp), componente sobre la direccion de falla
  i1   = |I1| del SANO del par (A pico), indicador de carga

Modelos:
  M1 (PRIMARIO): dos umbrales sobre mag (LEVE < u1 <= INTER < u2 <= SEVERA). Cada umbral es el
     punto medio entre las clases vecinas en entrenamiento (o el de maxima exactitud si se
     traslapan). Es el modelo mas simple de embeber y de explicar. Nota: los rangos por archivo
     se vieron durante la captura, por eso se declara el modelo simple como primario.
  M2: regresion logistica multinomial sobre [mag, i1] (estandarizadas).
  M3: arbol de decision (profundidad <= 3) sobre [mag, proy, i1].

Validacion:
  V1 (principal): dejar una carga fuera - se entrena con 3 cargas y se prueba con la 4a,
     rotando las 4. Reporta matriz de confusion global, exactitud con IC95 (Wilson) y F1 macro.
  V2 (sesion): se entrena con todo el bloque principal y se prueba con la repeticion LEVE 75 %
     del 07-oct (otra sesion), para descartar que el modelo aprenda el dia de captura.
  Limitacion conocida: cada severidad se capturo en un dia distinto (clase confundida con
  sesion); V2 solo lo prueba para LEVE.
"""

import csv
import glob
import json
import math
import os
import re
import sys

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.tree import DecisionTreeClassifier, export_text

DATASET = os.path.expanduser('~/tesis_itf/dataset')
SALIDA = os.path.expanduser('~/tesis_itf/modelo_severidad')
ANG_FALLA = -81.4
CLASES = ['LEVE', 'INTER', 'SEVERA']
CARGAS = ['0%', '25%', '50%', '75%']
REPETICION = 'cap_ENTRELAZADA_LEVE_75%_20261007_1544.csv'


def cargar():
    filas = []
    for f in sorted(glob.glob(os.path.join(DATASET, 'cap_ENTRELAZADA_*_2026100[678]_*.csv'))):
        if f.endswith('_descartes.csv'):
            continue
        m = re.match(r'cap_ENTRELAZADA_(LEVE|INTER|SEVERA)_(\d+%)_(\d{8}_\d{4})\.csv', os.path.basename(f))
        if not m:
            continue
        r = list(csv.DictReader(open(f)))
        u = complex(math.cos(math.radians(ANG_FALLA)), -math.sin(math.radians(ANG_FALLA)))
        for i in range(0, len(r) - 1, 2):
            s, l = r[i], r[i + 1]
            assert s['label'] == 'SANO' and l['label'] == m.group(1), f
            d = complex(float(l['r2_re']) - float(s['r2_re']), float(l['r2_im']) - float(s['r2_im']))
            d = d / float(l['i1']) * 100.0
            filas.append({
                'clase': m.group(1), 'carga': m.group(2), 'archivo': os.path.basename(f),
                'repeticion': os.path.basename(f) == REPETICION,
                'mag': abs(d), 'proy': (d * u).real, 'i1': float(s['i1']),
                'ang': math.degrees(math.atan2(d.imag, d.real)),
            })
    return filas


class Umbrales:
    """M1: dos umbrales sobre mag."""

    def fit(self, X, y):
        mag = X[:, 0]
        self.u = []
        for a, b in [(0, 1), (1, 2)]:
            lo, hi = mag[y == a], mag[y == b]
            if lo.max() < hi.min():
                self.u.append(0.5 * (lo.max() + hi.min()))
            else:
                cand = np.sort(np.concatenate([lo, hi]))
                acc = [((lo < t).sum() + (hi >= t).sum()) for t in cand]
                self.u.append(float(cand[int(np.argmax(acc))]))
        return self

    def predict(self, X):
        mag = X[:, 0]
        return (mag >= self.u[0]).astype(int) + (mag >= self.u[1]).astype(int)


def wilson(k, n, z=1.96):
    if n == 0:
        return (float('nan'), float('nan'))
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (c - h, c + h)


def metricas(y, p):
    cm = np.zeros((3, 3), int)
    for a, b in zip(y, p):
        cm[a, b] += 1
    f1 = []
    for k in range(3):
        tp = cm[k, k]
        prec = tp / max(1, cm[:, k].sum())
        rec = tp / max(1, cm[k, :].sum())
        f1.append(0 if prec + rec == 0 else 2 * prec * rec / (prec + rec))
    acc = np.trace(cm) / cm.sum()
    return cm, acc, float(np.mean(f1)), wilson(int(np.trace(cm)), int(cm.sum()))


MODELOS = {
    'M1_umbrales_mag': (lambda: Umbrales(), ['mag']),
    'M2_logistica_mag_i1': (lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)), ['mag', 'i1']),
    'M3_arbol_mag_proy_i1': (lambda: DecisionTreeClassifier(max_depth=3, random_state=0), ['mag', 'proy', 'i1']),
}


def matriz(filas, cols):
    X = np.array([[f[c] for c in cols] for f in filas])
    y = np.array([CLASES.index(f['clase']) for f in filas])
    return X, y


def main():
    os.makedirs(SALIDA, exist_ok=True)
    filas = cargar()
    princ = [f for f in filas if not f['repeticion']]
    rep = [f for f in filas if f['repeticion']]
    print(f"Pares de falla: {len(princ)} en el bloque principal + {len(rep)} de repeticion LEVE")
    for c in CLASES:
        print('  ' + c + ': ' + ', '.join(f"{g}={sum(1 for f in princ if f['clase'] == c and f['carga'] == g)}" for g in CARGAS))

    reporte = {'diseno': __doc__.strip().splitlines()[3:], 'modelos': {}}
    for nombre, (fab, cols) in MODELOS.items():
        y_all, p_all, por_carga = [], [], {}
        for g in CARGAS:
            tr = [f for f in princ if f['carga'] != g]
            te = [f for f in princ if f['carga'] == g]
            Xtr, ytr = matriz(tr, cols)
            Xte, yte = matriz(te, cols)
            mdl = fab().fit(Xtr, ytr)
            p = mdl.predict(Xte)
            y_all += list(yte)
            p_all += list(p)
            por_carga[g] = {'exactitud': float((p == yte).mean()), 'n': int(len(yte)),
                            'errores': [(CLASES[a], CLASES[b], round(f['mag'], 2)) for a, b, f in zip(yte, p, te) if a != b]}
            if nombre.startswith('M1'):
                por_carga[g]['umbrales'] = [round(float(u), 3) for u in mdl.u]
        cm, acc, f1, ic = metricas(y_all, p_all)
        # V2: todo el bloque principal -> repeticion
        Xa, ya = matriz(princ, cols)
        Xr, yr = matriz(rep, cols)
        mdl = fab().fit(Xa, ya)
        pr = mdl.predict(Xr)
        reporte['modelos'][nombre] = {
            'variables': cols, 'V1_exactitud': acc, 'V1_IC95': ic, 'V1_F1_macro': f1,
            'V1_matriz': cm.tolist(), 'V1_por_carga': por_carga,
            'V2_repeticion_aciertos': int((pr == yr).sum()), 'V2_n': int(len(yr)),
        }
        if nombre.startswith('M1'):
            reporte['modelos'][nombre]['umbrales_finales'] = [round(float(u), 3) for u in mdl.u]
        if nombre.startswith('M3'):
            reporte['modelos'][nombre]['arbol'] = export_text(mdl, feature_names=cols)

        print(f"\n=== {nombre} ({', '.join(cols)}) ===")
        print(f"V1 dejar-una-carga-fuera: exactitud {acc:.3f} (IC95 {ic[0]:.3f}-{ic[1]:.3f}), F1 macro {f1:.3f}")
        print("  matriz (filas real, columnas predicho) LEVE/INTER/SEVERA:")
        for k in range(3):
            print(f"    {CLASES[k]:7s} {cm[k]}")
        for g in CARGAS:
            e = por_carga[g]
            extra = f" umbrales {e['umbrales']}" if 'umbrales' in e else ''
            print(f"  carga {g:4s}: {e['exactitud']:.3f} ({e['n']} pares){extra}" + (f" errores {e['errores']}" if e['errores'] else ''))
        print(f"V2 repeticion LEVE 07-oct: {int((pr == yr).sum())}/{len(yr)} clasificados como LEVE")
        if nombre.startswith('M1'):
            print(f"  umbrales finales (todo el bloque): {[round(float(u), 3) for u in mdl.u]} pp")

    with open(os.path.join(SALIDA, 'reporte_validacion.json'), 'w') as fh:
        json.dump(reporte, fh, indent=2, ensure_ascii=False, default=float)
    print(f"\nReporte: {os.path.join(SALIDA, 'reporte_validacion.json')}")


if __name__ == '__main__':
    main()
