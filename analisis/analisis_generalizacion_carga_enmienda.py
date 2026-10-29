#!/usr/bin/env python3
"""
Enmienda al estudio 2: RF-MCSA con caracteristicas espectrales relativas (c').
Protocolo: ~/PROTOCOLO_GENERALIZACION_CARGA_ENMIENDA.md (commit dd93b67). Reutiliza, sin modificarlo,
~/analisis_generalizacion_carga.py. Solo lee el dataset; escribe en
~/tesis_itf/generalizacion_carga/enmienda_mcsa_relativo/.

Principal:  /usr/bin/python3 -I ~/analisis_generalizacion_carga_enmienda.py
Robustez:   ~/tesis_itf/venv/bin/python -I ~/analisis_generalizacion_carga_enmienda.py --sufijo venv
"""
import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np
import sklearn

sys.path.insert(0, os.path.expanduser('~'))
import analisis_generalizacion_carga as G  # noqa: E402

SALIDA = os.path.join(G.SALIDA, 'enmienda_mcsa_relativo')
F_MCSA_REL = ['r55', 'r65', 'hr_l2sm', 'hr_l2sp', 'hr_lrm', 'hr_lrp', 'hr_l3', 'hr_l3rm', 'hr_l3rp',
              'hr_snr2s', 'fc_A', 'fc_B', 'fc_C']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sufijo', default='')
    args = ap.parse_args()
    os.makedirs(SALIDA, exist_ok=True)
    filas, n_pares, _, _ = G.cargar()
    for f in filas:
        f['r55'] = f['A_55'] / f['A_fund']
        f['r65'] = f['A_65'] / f['A_fund']

    res = {'protocolo': 'PROTOCOLO_GENERALIZACION_CARGA_ENMIENDA.md (commit dd93b67)',
           'entorno': {'python': sys.version.split()[0], 'ejecutable': sys.executable, 'sklearn': sklearn.__version__},
           'fecha': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'caracteristicas': F_MCSA_REL,
           'n_pares': n_pares, 'resultados': {}, 'semillas': {}, 'importancias_semilla0': {}, 'mcnemar': {}}
    bolsa = {}
    for esquema, carga_te, itr, ite in G.particiones(filas):
        tr = [filas[i] for i in itr]
        te = [filas[i] for i in ite]
        clave = '75%' if esquema == 'E0' else carga_te
        b = bolsa.setdefault(esquema, {}).setdefault(clave, {'idx': [], 'a': [], 's': {}})
        b['idx'] += list(ite)
        b['a'] += list(map(int, G.regla(te)[0]))
        for sem in G.SEMILLAS:
            pr, sc, imp = G.rf(tr, te, F_MCSA_REL, sem)
            d = b['s'].setdefault(sem, {'pred': [], 'score': []})
            d['pred'] += list(map(int, pr))
            d['score'] += list(map(float, sc))
            if sem == 0:
                res['importancias_semilla0'].setdefault(esquema, {})[carga_te] = imp

    for esquema, porcarga in bolsa.items():
        for carga_te, b in porcarga.items():
            te = [filas[i] for i in b['idx']]
            for sem, d in b['s'].items():
                met = G.metricas(te, np.array(d['pred']), np.array(d['score']))
                res['semillas'].setdefault(esquema, {}).setdefault(carga_te, []).append(
                    {'semilla': sem, 'sens': met['sens'], 'fp': met['fp'], 'ba': met['ba']})
                if sem == 0:
                    res['resultados'].setdefault(esquema, {})[carga_te] = met
            pa, pc = np.array(b['a']), np.array(b['s'][0]['pred'])
            cl = np.array([f['clase'] for f in te])
            for grupo in G.SEVS + ['FALLA', 'SANO']:
                mk = (cl != 'SANO') if grupo == 'FALLA' else (cl == grupo)
                if mk.any():
                    n10, n01, p = G.mcnemar(pa[mk], pc[mk])
                    res['mcnemar'].setdefault(esquema, []).append(
                        {'carga': carga_te, 'grupo': grupo, 'n': int(mk.sum()), 'regla_si_rf_no': n10,
                         'regla_no_rf_si': n01, 'p': p})
    for lst in res['mcnemar'].values():
        for t, ph in zip(lst, G.holm([t['p'] for t in lst])):
            t['p_holm'] = ph

    suf = f'_{args.sufijo}' if args.sufijo else ''
    with open(os.path.join(SALIDA, f'resultado_enmienda_mcsa_relativo{suf}.json'), 'w') as fh:
        json.dump(res, fh, indent=1, ensure_ascii=False)

    print('Entorno:', res['entorno'], '| pares', n_pares)
    for esquema in ['E0', 'E1', 'E2']:
        print(f'== {esquema}')
        for c, m in res['resultados'][esquema].items():
            s = m['sens']
            rng = [x['sens']['LEVE'][0] for x in res['semillas'][esquema][c]]
            print(f"{c:5} c' LEVE {s['LEVE'][0]}/{s['LEVE'][1]} (semillas {min(rng)}-{max(rng)}) INTER {s['INTER'][0]}/"
                  f"{s['INTER'][1]} SEVERA {s['SEVERA'][0]}/{s['SEVERA'][1]} FP {m['fp'][0]}/{m['fp'][1]} BA {m['ba']:.3f}"
                  f" AUC_L {m['auc_leve']}")
    print('Importancias E1:', res['importancias_semilla0']['E1'].get('0%'))


if __name__ == '__main__':
    main()
