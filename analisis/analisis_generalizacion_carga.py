#!/usr/bin/env python3
"""
Estudio 2: generalizacion entre cargas de la regla de Fortescue frente al Random Forest.
Protocolo declarado antes de correr: ~/PROTOCOLO_GENERALIZACION_CARGA.md (commit 61c09f1).

Solo LEE el dataset multiclase (~/tesis_itf/dataset/cap_ENTRELAZADA_*_2026100[678]_*.csv) y escribe en
~/tesis_itf/generalizacion_carga/.

Corrida principal (entorno del estudio 1):  /usr/bin/python3 -I ~/analisis_generalizacion_carga.py
Robustez (venv, scikit-learn 1.9.0):       ~/tesis_itf/venv/bin/python -I ~/analisis_generalizacion_carga.py --sufijo venv
"""
import argparse
import csv
import glob
import json
import math
import os
import re
import sys
from datetime import datetime

import numpy as np
import scipy
import sklearn
from scipy.stats import binomtest
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold

DS = os.path.expanduser('~/tesis_itf/dataset')
SALIDA = os.path.expanduser('~/tesis_itf/generalizacion_carga')
ESTUDIO1 = os.path.expanduser('~/tesis_itf/comparacion_ml/resultado_comparacion_ml.json')

ANG_FALLA = -81.4          # grados, detector_dir.h
UMBRAL = 0.40              # pp, detector_dir.h
LAG_MAX_S = 60.0           # control nulo SANO: intervalo maximo con el SANO previo
UMBRAL_PROB = 0.5
SEMILLAS = list(range(10))
CARGAS = ['0%', '25%', '50%', '75%']
SEVS = ['LEVE', 'INTER', 'SEVERA']
GRID_A2 = [round(0.20 + 0.05 * i, 2) for i in range(17)]   # 0.20 ... 1.00

F_FORT = ['P', 'Q', 'mag', 'dI1', 'dV1', 'dV2']
F_FORT_SIN_I1 = ['P', 'Q', 'mag', 'dV1', 'dV2']
F_MCSA = ['I_rms', 'ia', 'ib', 'V_rms', 'va', 'vb', 'A_fund', 'A_55', 'A_65', 'hr_l2sm', 'hr_l2sp', 'hr_lrm',
          'hr_lrp', 'hr_l3', 'hr_l3rm', 'hr_l3rp', 'hr_snr2s', 'hr_s', 'hr_f0', 'fc_A', 'fc_B', 'fc_C']
METODOS_RF = {'b_rf_fortescue': F_FORT, 'b2_rf_sin_dI1': F_FORT_SIN_I1, 'c_rf_mcsa': F_MCSA}


# ----------------------------------------------------------------------------------------------- datos
def cargar():
    """Una fila por bloque evaluable: falla (ref = SANO del mismo par) o SANO (ref = SANO del par previo)."""
    rot = complex(math.cos(math.radians(-ANG_FALLA)), math.sin(math.radians(-ANG_FALLA)))
    filas, n_pares, n_sano_total = [], 0, 0
    archivos = sorted(f for f in glob.glob(f'{DS}/cap_ENTRELAZADA_*_2026100[678]_*.csv')
                      if not f.endswith('_descartes.csv'))
    for f in archivos:
        nom = os.path.basename(f)
        m = re.match(r'cap_ENTRELAZADA_(LEVE|INTER|SEVERA)_(\d+%)_(\d{8}_\d{4})\.csv$', nom)
        if not m:
            continue
        r = list(csv.DictReader(open(f)))
        assert len(r) % 2 == 0, nom
        prev = None
        for i in range(0, len(r), 2):
            s, fl = r[i], r[i + 1]
            assert s['label'] == 'SANO' and fl['label'] == m.group(1), nom
            n_pares += 1
            n_sano_total += 1
            # SANO contra el SANO del par anterior (control nulo)
            if prev is not None:
                lag = (datetime.strptime(s['timestamp'], '%Y-%m-%d %H:%M:%S')
                       - datetime.strptime(prev['timestamp'], '%Y-%m-%d %H:%M:%S')).total_seconds()
                if 0 < lag <= LAG_MAX_S:
                    filas.append(fila(s, prev, 'SANO', m.group(2), nom, rot, lag))
            filas.append(fila(fl, s, m.group(1), m.group(2), nom, rot, None))
            prev = s
    return filas, n_pares, n_sano_total, [os.path.basename(a) for a in archivos]


def fila(b, ref, clase, carga, archivo, rot, lag):
    z = complex(float(b['r2_re']), float(b['r2_im'])) / float(b['i1']) * 100.0
    zr = complex(float(ref['r2_re']), float(ref['r2_im'])) / float(ref['i1']) * 100.0
    dz = z - zr
    pr = dz * rot
    v2 = complex(float(b['v2_re']), float(b['v2_im']))
    v2r = complex(float(ref['v2_re']), float(ref['v2_im']))
    d = {
        'archivo': archivo, 'n_muestra': int(b['n_muestra']), 'clase': clase, 'carga': carga, 'lag_s': lag,
        'y': 0 if clase == 'SANO' else 1, 'dz': dz,
        'P': pr.real, 'Q': pr.imag, 'mag': abs(dz),
        'dI1': (float(b['i1']) - float(ref['i1'])) / float(ref['i1']) * 100.0,
        'dV1': (float(b['v1']) - float(ref['v1'])) / float(ref['v1']) * 100.0,
        'dV2': abs(v2 - v2r) / float(b['v1']) * 100.0,
    }
    for k in F_MCSA:
        if not k.startswith('fc_'):
            d[k] = float(b[k])
    fase = b['falla_max'].strip()[-1]
    for c in 'ABC':
        d['fc_' + c] = 1.0 if fase == c else 0.0
    return d


# ------------------------------------------------------------------------------------------ metricas
def wilson(k, n, z=1.96):
    if n == 0:
        return [k, n, float('nan'), float('nan')]
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [k, n, round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def metricas(filas, pred, score):
    y = np.array([f['y'] for f in filas])
    cl = np.array([f['clase'] for f in filas])
    out = {'sens': {}, 'n_filas': len(filas)}
    for s in SEVS:
        mk = cl == s
        if mk.any():
            out['sens'][s] = wilson(int(pred[mk].sum()), int(mk.sum()))
    out['sens']['FALLA'] = wilson(int(pred[y == 1].sum()), int((y == 1).sum()))
    out['fp'] = wilson(int(pred[y == 0].sum()), int((y == 0).sum()))
    sen = pred[y == 1].mean() if (y == 1).any() else float('nan')
    esp = 1 - pred[y == 0].mean() if (y == 0).any() else float('nan')
    out['ba'] = round(float((sen + esp) / 2), 4)
    for nom, mk in (('auc_leve', (cl == 'SANO') | (cl == 'LEVE')), ('auc_falla', np.ones(len(y), bool))):
        yy = y[mk]
        out[nom] = round(float(roc_auc_score(yy, score[mk])), 4) if 0 < yy.sum() < len(yy) else None
    return out


def mcnemar(pa, pb):
    """Exacto: binomial sobre los discordantes. Devuelve (a1b0, a0b1, p)."""
    n10 = int(((pa == 1) & (pb == 0)).sum())
    n01 = int(((pa == 0) & (pb == 1)).sum())
    p = binomtest(n10, n10 + n01, 0.5).pvalue if n10 + n01 > 0 else 1.0
    return n10, n01, float(p)


def holm(ps):
    orden = sorted(range(len(ps)), key=lambda i: ps[i])
    adj, m, mx = [0.0] * len(ps), len(ps), 0.0
    for r, i in enumerate(orden):
        mx = max(mx, min(1.0, (m - r) * ps[i]))
        adj[i] = mx
    return adj


# ------------------------------------------------------------------------------------------- metodos
def regla(filas):
    P = np.array([f['P'] for f in filas])
    return (P >= UMBRAL).astype(int), P


def regla_entrenada(tr, te):
    """(a'): direccion = media circular de arg(dz) de las fallas de entrenamiento; umbral por exactitud balanceada."""
    u = sum(f['dz'] / abs(f['dz']) for f in tr if f['y'] == 1 and abs(f['dz']) > 0)
    th = math.atan2(u.imag, u.real)
    rot = complex(math.cos(-th), math.sin(-th))
    ptr = np.array([(f['dz'] * rot).real for f in tr])
    ytr = np.array([f['y'] for f in tr])
    mejor = None
    for t in GRID_A2:
        pr = ptr >= t
        ba = (pr[ytr == 1].mean() + 1 - pr[ytr == 0].mean()) / 2
        clave = (round(ba, 10), -abs(t - UMBRAL))
        if mejor is None or clave > mejor[0]:
            mejor = (clave, t)
    t = mejor[1]
    pte = np.array([(f['dz'] * rot).real for f in te])
    return (pte >= t).astype(int), pte, {'angulo_deg': round(math.degrees(th), 2), 'umbral_pp': t}


def rf(tr, te, feats, semilla):
    X = np.array([[f[k] for k in feats] for f in tr])
    y = np.array([f['y'] for f in tr])
    m = RandomForestClassifier(n_estimators=300, max_depth=6, class_weight='balanced', min_samples_leaf=5,
                               n_jobs=-1, random_state=semilla).fit(X, y)
    p = m.predict_proba(np.array([[f[k] for k in feats] for f in te]))[:, 1]
    imp = dict(zip(feats, [round(float(v), 4) for v in m.feature_importances_]))
    return (p >= UMBRAL_PROB).astype(int), p, imp


# ------------------------------------------------------------------------------------------ esquemas
def particiones(filas):
    """Lista de (esquema, carga_prueba, idx_train, idx_test)."""
    carga = np.array([f['carga'] for f in filas])
    idx = np.arange(len(filas))
    out = []
    i75 = idx[carga == '75%']
    strat = np.array([f['clase'] for f in filas])[i75]
    for k, (a, b) in enumerate(StratifiedKFold(5, shuffle=True, random_state=0).split(i75, strat)):
        out.append(('E0', f'75%_pliegue{k}', i75[a], i75[b]))
    for c in ['0%', '25%', '50%']:
        out.append(('E1', c, i75, idx[carga == c]))
    for c in CARGAS:
        out.append(('E2', c, idx[carga != c], idx[carga == c]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sufijo', default='', help="'venv' para la corrida de robustez")
    args = ap.parse_args()
    os.makedirs(SALIDA, exist_ok=True)
    entorno = {'python': sys.version.split()[0], 'ejecutable': sys.executable, 'sklearn': sklearn.__version__,
               'numpy': np.__version__, 'scipy': scipy.__version__}

    filas, n_pares, n_sano_total, archivos = cargar()
    sano = [f for f in filas if f['y'] == 0]
    controles = {
        'archivos': archivos, 'pares': n_pares, 'filas_falla': len(filas) - len(sano),
        'filas_sano_utilizables': len(sano), 'filas_sano_total': n_sano_total,
        'lag_sano_s_mediana_por_archivo': {},
        'mediana_mag_por_celda': {}, 'mediana_dI1_por_celda': {}, 'mediana_ang_por_celda': {},
    }
    for a in archivos:
        lg = [f['lag_s'] for f in sano if f['archivo'] == a]
        controles['lag_sano_s_mediana_por_archivo'][a] = float(np.median(lg)) if lg else None
    for s in ['SANO'] + SEVS:
        for c in CARGAS:
            sel = [f for f in filas if f['clase'] == s and f['carga'] == c]
            if sel:
                k = f'{s}_{c}'
                controles['mediana_mag_por_celda'][k] = round(float(np.median([f['mag'] for f in sel])), 3)
                controles['mediana_dI1_por_celda'][k] = round(float(np.median([f['dI1'] for f in sel])), 3)
                controles['mediana_ang_por_celda'][k] = round(float(np.degrees(np.median(np.angle([f['dz'] for f in sel])))), 1)

    res = {'protocolo': 'PROTOCOLO_GENERALIZACION_CARGA.md (commit 61c09f1)', 'entorno': entorno,
           'fecha': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'controles': controles,
           'resultados': {}, 'semillas': {}, 'parametros_a2': {}, 'importancias_semilla0': {}, 'mcnemar': {}}
    pred_filas = []

    parts = particiones(filas)
    # E0 se agrega sobre sus 5 pliegues (predicciones fuera de pliegue)
    for esquema, carga_te, itr, ite in parts:
        tr = [filas[i] for i in itr]
        te = [filas[i] for i in ite]
        clave_carga = '75%' if esquema == 'E0' else carga_te
        bolsa = res.setdefault('_bolsa', {}).setdefault(esquema, {}).setdefault(clave_carga, {'idx': [], 'm': {}})
        bolsa['idx'] += list(ite)
        pa, sa = regla(te)
        p2, s2, prm = regla_entrenada(tr, te)
        res['parametros_a2'].setdefault(esquema, {})[carga_te] = prm
        salida = {'a_regla': (pa, sa), 'a2_regla_entrenada': (p2, s2)}
        for nom, feats in METODOS_RF.items():
            for sem in SEMILLAS:
                pr, sc, imp = rf(tr, te, feats, sem)
                salida[f'{nom}#s{sem}'] = (pr, sc)
                if sem == 0:
                    res['importancias_semilla0'].setdefault(esquema, {}).setdefault(nom, {})[carga_te] = imp
        for nom, (pr, sc) in salida.items():
            d = bolsa['m'].setdefault(nom, {'pred': [], 'score': []})
            d['pred'] += list(map(int, pr))
            d['score'] += list(map(float, sc))

    for esquema, porcarga in res.pop('_bolsa').items():
        for carga_te, b in porcarga.items():
            te = [filas[i] for i in b['idx']]
            for nom, d in b['m'].items():
                pr, sc = np.array(d['pred']), np.array(d['score'])
                if '#s' in nom:
                    base, sem = nom.split('#s')
                    sem = int(sem)
                    met = metricas(te, pr, sc)
                    res['semillas'].setdefault(esquema, {}).setdefault(carga_te, {}).setdefault(base, []).append(
                        {'semilla': sem, 'LEVE': met['sens'].get('LEVE'), 'fp': met['fp'], 'ba': met['ba'],
                         'auc_leve': met['auc_leve']})
                    if sem != 0:
                        continue
                    nom = base
                res['resultados'].setdefault(esquema, {}).setdefault(carga_te, {})[nom] = metricas(te, pr, sc)
                for f, p_, s_ in zip(te, pr, sc):
                    pred_filas.append({'esquema': esquema, 'carga_prueba': carga_te, 'metodo': nom,
                                       'archivo': f['archivo'], 'n_muestra': f['n_muestra'], 'clase': f['clase'],
                                       'pred': int(p_), 'score': round(float(s_), 5)})
            # McNemar (a) frente a (b), semilla 0, en las mismas filas
            pa = np.array(b['m']['a_regla']['pred'])
            pb = np.array(b['m']['b_rf_fortescue#s0']['pred'])
            cl = np.array([f['clase'] for f in te])
            for grupo in SEVS + ['FALLA', 'SANO']:
                mk = (cl != 'SANO') if grupo == 'FALLA' else (cl == grupo)
                if mk.any():
                    n10, n01, p = mcnemar(pa[mk], pb[mk])
                    res['mcnemar'].setdefault(esquema, []).append(
                        {'carga': carga_te, 'grupo': grupo, 'n': int(mk.sum()), 'regla_si_rf_no': n10,
                         'regla_no_rf_si': n01, 'p': p})
    for esquema, lst in res['mcnemar'].items():
        for t, ph in zip(lst, holm([t['p'] for t in lst])):
            t['p_holm'] = ph

    # Hipotesis primaria (E1, LEVE 0 %)
    e1 = res['resultados']['E1']['0%']
    prim = next(t for t in res['mcnemar']['E1'] if t['carga'] == '0%' and t['grupo'] == 'LEVE')
    sens_a = e1['a_regla']['sens']['LEVE'][0]
    sens_b_sem = [s['LEVE'][0] for s in res['semillas']['E1']['0%']['b_rf_fortescue']]
    res['hipotesis_primaria'] = {
        'regla_LEVE0': e1['a_regla']['sens']['LEVE'], 'rf_LEVE0_semilla0': e1['b_rf_fortescue']['sens']['LEVE'],
        'mcnemar': prim, 'rf_LEVE0_por_semilla': sens_b_sem,
        'cond1_p_menor_0.05_y_rf_menor': bool(prim['p'] < 0.05 and e1['b_rf_fortescue']['sens']['LEVE'][0] < sens_a),
        'cond2_rf_menor_en_10_semillas': bool(all(k < sens_a for k in sens_b_sem)),
    }
    res['hipotesis_primaria']['confirmada'] = (res['hipotesis_primaria']['cond1_p_menor_0.05_y_rf_menor']
                                               and res['hipotesis_primaria']['cond2_rf_menor_en_10_semillas'])

    # Indicadores del articulo (menor es mejor)
    e1j = json.load(open(ESTUDIO1))
    e2 = res['resultados']['E2']
    ind = {}
    for nom, fuente in (('a_regla', 'A_firmware'), ('b_rf_fortescue', 'C1_random_forest_mejor')):
        ind[nom] = {
            'e_FA': e1j[fuente]['fa_h'],
            'e_L75': round(1 - e1j[fuente]['det_n']['LEVE'] / 60, 4),
            'e_L0': round(1 - res['resultados']['E1']['0%'][nom]['sens']['LEVE'][0]
                          / res['resultados']['E1']['0%'][nom]['sens']['LEVE'][1], 4),
            'e_FP': round(float(np.mean([e2[c][nom]['fp'][0] / e2[c][nom]['fp'][1] for c in CARGAS])), 4),
            'e_BA': round(float(np.mean([1 - e2[c][nom]['ba'] for c in CARGAS])), 4),
        }
    ejes = ['e_FA', 'e_L75', 'e_L0', 'e_FP', 'e_BA']
    norm = {}
    for nom in ind:
        norm[nom] = [ind[nom][e] / max(ind[m][e] for m in ind) if max(ind[m][e] for m in ind) > 0 else 0.0
                     for e in ejes]
    area = {nom: round(0.5 * math.sin(2 * math.pi / len(ejes))
                       * sum(v[i] * v[(i + 1) % len(v)] for i in range(len(v))), 4) for nom, v in norm.items()}
    res['indicadores'] = {'ejes': ejes, 'valores': ind, 'normalizados': norm, 'area_radar': area,
                          'fuente_e_FA_e_L75': 'resultado_comparacion_ml.json (estudio 1, Python del sistema)'}

    suf = f'_{args.sufijo}' if args.sufijo else ''
    with open(os.path.join(SALIDA, f'resultado_generalizacion_carga{suf}.json'), 'w') as fh:
        json.dump(res, fh, indent=1, ensure_ascii=False)
    with open(os.path.join(SALIDA, f'predicciones_por_fila{suf}.csv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(pred_filas[0].keys()))
        w.writeheader()
        w.writerows(pred_filas)

    # Resumen en consola
    print('Entorno:', entorno)
    print('Controles: pares', n_pares, '| falla', controles['filas_falla'], '| SANO utilizables', len(sano),
          '/', n_sano_total)
    print('Mediana |dz| por celda:', controles['mediana_mag_por_celda'])
    for esquema in ['E0', 'E1', 'E2']:
        print(f'\n== {esquema}')
        for c, mets in res['resultados'][esquema].items():
            for nom, m in mets.items():
                s = m['sens']
                print(f"{c:5} {nom:22} LEVE {s.get('LEVE', ['-', '-'])[0]}/{s.get('LEVE', ['-', '-'])[1]}"
                      f" INTER {s['INTER'][0]}/{s['INTER'][1]} SEVERA {s['SEVERA'][0]}/{s['SEVERA'][1]}"
                      f" FP {m['fp'][0]}/{m['fp'][1]} BA {m['ba']:.3f} AUC_L {m['auc_leve']}")
    print('\nHipotesis primaria:', json.dumps(res['hipotesis_primaria'], ensure_ascii=False))
    print('Indicadores:', json.dumps(res['indicadores']['valores'], ensure_ascii=False))
    print('Area radar:', area)
    print('Parametros (a\'):', json.dumps(res['parametros_a2'], ensure_ascii=False))


if __name__ == '__main__':
    main()
