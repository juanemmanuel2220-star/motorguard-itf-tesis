#!/usr/bin/env python3
"""
Comparacion fuera de linea: regla del firmware vs regla reajustada vs aprendizaje automatico
(Random Forest, gradient boosting) para la etapa de deteccion. Protocolo: PROTOCOLO_COMPARACION_ML.md
(declarado antes de correr). Solo lee logs; no modifica el firmware ni los datos.
"""
import json
import math
import os
import re
import statistics
import sys
from collections import defaultdict

import numpy as np
from scipy.stats import chi2
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier

ANG = math.radians(-81.4)
REF_DESDE, REF_HASTA, HIST = 11.0, 6.0, 30.0
LAGS = 5
T_EXCL_INI, T_DRENADO, T_COLA = 1.0, 12.0, 2.0
PL = os.path.expanduser('~/tesis_itf/prueba_larga')
VV = os.path.expanduser('~/tesis_itf/validacion_vivo')
SALIDA = os.path.expanduser('~/tesis_itf/comparacion_ml')

GRUPOS = [
    ('larga_25', 'SANO', f'{PL}/larga_20261012_1319_serial.log'),
    ('larga_50', 'SANO', f'{PL}/larga_20261012_1350_serial.log'),
    ('larga_75', 'SANO', f'{PL}/larga_20261012_1422_serial.log'),
    ('larga_0', 'SANO', f'{PL}/larga_20261012_1457_serial.log'),
    ('LEVE_1006_1753', 'LEVE', f'{VV}/vivo_LEVE_75%_20261006_1753_serial.log'),
    ('LEVE_1007_1404', 'LEVE', f'{VV}/vivo_LEVE_75%_20261007_1404_serial.log'),
    ('LEVE_1007_1450', 'LEVE', f'{VV}/vivo_LEVE_75%_20261007_1450_serial.log'),
    ('LEVE_1007_1529', 'LEVE', f'{VV}/vivo_LEVE_75%_20261007_1529_serial.log'),
    ('INTER_1008_1628', 'INTER', f'{VV}/vivo_INTER_75%_20261008_1628_serial.log'),
    ('INTER_1009_1501', 'INTER', f'{VV}/vivo_INTER_75%_20261009_1501_serial.log'),
    ('INTER_1009_1513', 'INTER', f'{VV}/vivo_INTER_75%_20261009_1513_serial.log'),
    ('SEVERA_1008_1612', 'SEVERA', f'{VV}/vivo_SEVERA_75%_20261008_1612_serial.log'),
    ('SEVERA_1008_1637', 'SEVERA', f'{VV}/vivo_SEVERA_75%_20261008_1637_serial.log'),
]
EXCLUIDAS = [
    ('LEVE_1009_1526', 'LEVE', f'{VV}/vivo_LEVE_75%_20261009_1526_serial.log'),
    ('LEVE_1009_1546', 'LEVE', f'{VV}/vivo_LEVE_75%_20261009_1546_serial.log'),
]

RE_B = re.compile(r"^([\d.]+) \[MCSA\] Motor:(\w+).*RAW: R2=([-\d.]+),([-\d.]+) I1=([-\d.]+) V2=([-\d.]+),([-\d.]+) V1=([-\d.]+)")
RE_ON = re.compile(r"^([\d.]+) \[DEBUG SSR\] Exito")
RE_OFF = re.compile(r"^([\d.]+) \[DEBUG SSR\] Apagado")
NOMBRES_F = []


def leer(log):
    bloques, pulsos, t_on = [], [], None
    for l in open(log, errors='ignore'):
        m = RE_B.search(l)
        if m:
            g = m.groups()
            bloques.append(dict(t=float(g[0]), motor=g[1], r2=complex(float(g[2]), float(g[3])), i1=float(g[4]),
                                v2=complex(float(g[5]), float(g[6])), v1=float(g[7])))
            continue
        m = RE_ON.search(l)
        if m:
            t_on = float(m.group(1))
            continue
        m = RE_OFF.search(l)
        if m and t_on is not None:
            pulsos.append((t_on, float(m.group(1))))
            t_on = None
    return bloques, pulsos


def reloj(bloques):
    """Tiempo de bloque a paso constante dentro de cada racha continua (igual que el replay V2)."""
    ts, ini = [], 0
    for i in range(1, len(bloques) + 1):
        if i == len(bloques) or bloques[i]['t'] - bloques[i - 1]['t'] > 5.0:
            seg = bloques[ini:i]
            paso = (seg[-1]['t'] - seg[0]['t']) / (len(seg) - 1) if len(seg) > 1 else 1.7
            ts += [seg[0]['t'] + k * paso for k in range(len(seg))]
            ini = i
    return ts


def med_c(xs):
    return complex(statistics.median([x.real for x in xs]), statistics.median([x.imag for x in xs]))


def caracteristicas(bloques):
    """Por bloque: P, Q, |dz|, dI1, dV1, |dV2| (contra la referencia del firmware) y la dispersion de z
    en 30 s. Devuelve una lista de dict o None si no hay referencia (o motor no ON)."""
    ts = reloj(bloques)
    out, h = [], []
    rot = complex(math.cos(-ANG), math.sin(-ANG))
    for b, t in zip(bloques, ts):
        if b['motor'] != 'ON' or b['i1'] < 1e-6:
            h = []
            out.append(None)
            continue
        z = b['r2'] / b['i1'] * 100
        ref = [x for x in h if REF_HASTA <= t - x['t'] <= REF_DESDE]
        h = [x for x in h if t - x['t'] <= HIST][-31:] + [dict(t=t, z=z, i1=b['i1'], v1=b['v1'], v2=b['v2'])]
        if len(ref) < 2:
            out.append(None)
            continue
        dz = (z - med_c([x['z'] for x in ref])) * rot
        i1r = statistics.median([x['i1'] for x in ref])
        v1r = statistics.median([x['v1'] for x in ref])
        v2r = med_c([x['v2'] for x in ref])
        zs = [x['z'] for x in h[:-1]]
        disp = math.sqrt(statistics.pvariance([x.real for x in zs]) + statistics.pvariance([x.imag for x in zs])) if len(zs) >= 3 else 0.0
        out.append(dict(P=dz.real, Q=dz.imag, M=abs(dz), dI1=(b['i1'] - i1r) / i1r * 100,
                        dV1=(b['v1'] - v1r) / v1r * 100, dV2=abs(b['v2'] - v2r) / b['v1'] * 100, disp=disp))
    return out


def vector(cs, i):
    """Bloque i y los LAGS-1 anteriores (si falta alguno, no hay vector)."""
    if i < LAGS - 1 or any(cs[i - k] is None for k in range(LAGS)):
        return None
    v = []
    for k in range(LAGS):
        c = cs[i - k]
        v += [c['P'], c['Q'], c['M'], c['dI1'], c['dV1'], c['dV2']]
    v.append(cs[i]['disp'])
    return v


def nombres():
    n = []
    for k in range(LAGS):
        n += [f'{x}_t-{k}' for x in ('P', 'Q', 'M', 'dI1', 'dV1', 'dV2')]
    return n + ['disp30s']


def etiquetar(t, pulsos):
    """1 falla, 0 sano, None excluido."""
    for a, b in pulsos:
        if a < t <= a + T_EXCL_INI:
            return None
        if a + T_EXCL_INI < t <= b:
            return 1
        if b < t <= b + T_DRENADO:
            return None
    return 0


def construir(grupos):
    datos = {}
    for nom, clase, log in grupos:
        bl, pulsos = leer(log)
        cs = caracteristicas(bl)
        filas = []
        for i, b in enumerate(bl):
            v = vector(cs, i)
            if v is None:
                continue
            filas.append(dict(t=b['t'], x=v, y=etiquetar(b['t'], pulsos), P=cs[i]['P']))
        datos[nom] = dict(clase=clase, filas=filas, pulsos=pulsos)
    return datos


def eventos(filas, score, umbral, k):
    """Inicios de alarma: k bloques seguidos con score >= umbral; una alarma nueva exige que la
    condicion haya estado apagada >= 3 bloques. Las filas son consecutivas en el tiempo; un hueco > 5 s
    reinicia la racha."""
    ini, racha, apagado, activo, t_prev = [], 0, 3, False, None
    for f, s in zip(filas, score):
        if t_prev is not None and f['t'] - t_prev > 5.0:
            racha, apagado, activo = 0, 3, False
        t_prev = f['t']
        if s >= umbral:
            racha += 1
            apagado = 0
        else:
            racha = 0
            apagado += 1
            if apagado >= 3:
                activo = False
        if racha >= k and not activo:
            ini.append(f['t'])
            activo = True
    return ini


def puntuar(datos, scores, umbral, k):
    """Falsas alarmas (inicios en bloques sanos) y detecciones por pulso."""
    fa, expo, det, tot, retardos = 0, 0.0, defaultdict(int), defaultdict(int), []
    for nom, d in datos.items():
        filas, sc = d['filas'], scores[nom]
        ini = eventos(filas, sc, umbral, k)
        etiqueta_t = {f['t']: f['y'] for f in filas}
        fa += sum(1 for t in ini if etiqueta_t.get(t) == 0)
        ts = [f['t'] for f in filas]
        expo += sum(b - a for (a, b), f in zip(zip(ts, ts[1:]), filas) if f['y'] == 0 and b - a < 5.0)
        for a, b in d['pulsos']:
            tot[d['clase']] += 1
            hit = [t for t in ini if a <= t <= b + T_COLA]
            if hit:
                det[d['clase']] += 1
                retardos.append(hit[0] - a)
    h = expo / 3600.0
    return dict(fa=fa, expo_h=round(h, 3), fa_h=round(fa / h, 2) if h else None,
                fa_h_ic95=[round(chi2.ppf(0.025, 2 * fa) / 2 / h, 2) if fa else 0.0,
                           round(chi2.ppf(0.975, 2 * fa + 2) / 2 / h, 2)],
                det={c: f"{det[c]}/{tot[c]}" for c in ('LEVE', 'INTER', 'SEVERA')},
                det_n={c: det[c] for c in ('LEVE', 'INTER', 'SEVERA')},
                retardo_med_s=round(statistics.median(retardos), 1) if retardos else None)


def fuera_de_muestra(datos, fabrica):
    """Probabilidades dejando cada grupo fuera (el modelo nunca ve el grupo evaluado)."""
    scores = {}
    for nom in datos:
        Xtr = [f['x'] for g, d in datos.items() if g != nom for f in d['filas'] if f['y'] is not None]
        ytr = [f['y'] for g, d in datos.items() if g != nom for f in d['filas'] if f['y'] is not None]
        m = fabrica()
        m.fit(np.array(Xtr), np.array(ytr))
        scores[nom] = m.predict_proba(np.array([f['x'] for f in datos[nom]['filas']]))[:, 1]
    return scores


def mejor_punto(res, ref_det):
    """Menos FA/h conservando en cada severidad al menos las detecciones de la regla A."""
    ok = [r for r in res if all(r['det_n'][c] >= ref_det[c] for c in ref_det)]
    return min(ok, key=lambda r: (r['fa_h'], -sum(r['det_n'].values()))) if ok else None


def main():
    os.makedirs(SALIDA, exist_ok=True)
    datos = construir(GRUPOS)
    resumen = {'protocolo': 'PROTOCOLO_COMPARACION_ML.md', 'grupos': {
        n: dict(clase=d['clase'], bloques=len(d['filas']), falla=sum(f['y'] == 1 for f in d['filas']),
                sano=sum(f['y'] == 0 for f in d['filas']), pulsos=len(d['pulsos'])) for n, d in datos.items()}}

    p_scores = {n: [f['P'] for f in d['filas']] for n, d in datos.items()}
    A = puntuar(datos, p_scores, 0.40, 3)
    resumen['A_firmware'] = A
    ref_det = A['det_n']

    B = []
    for u in [round(0.40 + 0.05 * i, 2) for i in range(13)]:
        for k in (3, 4, 5, 6):
            B.append(dict(u=u, k=k, **puntuar(datos, p_scores, u, k)))
    resumen['B_mejor'] = mejor_punto(B, ref_det)
    resumen['B_curva'] = B

    modelos = {
        'C1_random_forest': lambda: RandomForestClassifier(n_estimators=300, max_depth=6, class_weight='balanced',
                                                           min_samples_leaf=5, n_jobs=-1, random_state=0),
        'C2_gradient_boosting': lambda: HistGradientBoostingClassifier(max_depth=4, learning_rate=0.05, max_iter=300,
                                                                       class_weight='balanced', random_state=0),
    }
    for nom_m, fab in modelos.items():
        sc = fuera_de_muestra(datos, fab)
        curva = []
        for s in [round(0.05 * i, 2) for i in range(2, 20)] + [0.97, 0.99]:
            for k in (1, 2, 3):
                curva.append(dict(s=s, k=k, **puntuar(datos, sc, s, k)))
        resumen[nom_m + '_mejor'] = mejor_punto(curva, ref_det)
        resumen[nom_m + '_curva'] = curva
        if nom_m == 'C1_random_forest':
            Xall = np.array([f['x'] for d in datos.values() for f in d['filas'] if f['y'] is not None])
            yall = np.array([f['y'] for d in datos.values() for f in d['filas'] if f['y'] is not None])
            rf = fab().fit(Xall, yall)
            imp = sorted(zip(nombres(), rf.feature_importances_), key=lambda x: -x[1])[:12]
            resumen['C1_importancias_top12'] = [(n, round(float(v), 3)) for n, v in imp]

    with open(os.path.join(SALIDA, 'resultado_comparacion_ml.json'), 'w') as fh:
        json.dump(resumen, fh, indent=1, ensure_ascii=False)
    for clave in ('grupos', 'A_firmware', 'B_mejor', 'C1_random_forest_mejor', 'C2_gradient_boosting_mejor',
                  'C1_importancias_top12'):
        print(clave, json.dumps(resumen.get(clave), ensure_ascii=False))


if __name__ == '__main__':
    if '--solo-datos' in sys.argv:
        d = construir(GRUPOS)
        for n, x in d.items():
            print(n, x['clase'], 'bloques', len(x['filas']), 'falla', sum(f['y'] == 1 for f in x['filas']),
                  'sano', sum(f['y'] == 0 for f in x['filas']), 'pulsos', len(x['pulsos']))
    else:
        main()
