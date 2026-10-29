#!/usr/bin/env python3
"""
Validacion ciega 2 (protocolo PROTOCOLO_VALIDACION_CIEGA_2.md): analisis fuera de linea de los registros
NUEVOS del banco con los modelos CONGELADOS el 14-oct-2026. Solo lee; no modifica firmware ni datos.

Detectores (todos sobre los mismos registros):
  - Regla de Fortescue, logica del estudio 1 (P >= 0.40 pp durante 3 bloques; C.eventos)    [H1, H2]
  - RF del estudio 1 congelado (s = 0.55, k = 3; misma logica de eventos)                      [H1, H2]
  - Regla con el detector completo (enclavamiento; replay fiel sin 'r')                         [secundario]
  - Variante congelada angulo <= 35 grados + LEVE en 4 bloques (detector completo)              [secundario]
  - Decision del propio firmware en vivo (campo DIR C y los _resumen.json del script en vivo)  [secundario]

H1: menos falsas alarmas del RF que de la regla (prueba condicional exacta, unilateral, alfa 0.05).
H2: deteccion LEVE a 0 % y 25 % del RF frente a la regla (McNemar exacto, bilateral), por carga.

Uso: /usr/bin/python3 analisis_validacion_ciega2.py [--fecha 20261015 20261016] [--salida DIR]
     (--fecha 20261012 = ensayo en seco con la prueba larga del 12-oct; sus cifras no se interpretan)
"""
import argparse
import glob
import hashlib
import json
import os
import re
import sys
from collections import defaultdict

import joblib
import numpy as np
from scipy.stats import binomtest, chi2

sys.path.insert(0, os.path.expanduser('~'))
sys.path.insert(0, os.path.expanduser('~/tesis_itf/validacion_ciega2/modelos'))
import analisis_mejora_deteccion as M  # noqa: E402
import comparacion_ml_deteccion as C  # noqa: E402
import variante_angulo35_leve4 as VAR  # noqa: E402

MODELOS = os.path.expanduser('~/tesis_itf/validacion_ciega2/modelos')
SHA_RF = '302d9d9ac071eef586f4e14ca5d6277c2aebdf8a3cbc8681edf50600f79db246'
SHA_VAR = 'a99f844878353725b5c1eb11d7b2b1eefdace4d6628b262ba2f23cf31b8dfd2f'
EXCLUSIONES = os.path.expanduser('~/tesis_itf/validacion_ciega2/exclusiones.json')
RE_C = re.compile(r"^([\d.]+) \[MCSA\] Motor:(\w+).*DIR: P=[-\d.]+ R=\d+ C=(\d)")
RE_VIVO = re.compile(r"vivo_(LEVE|INTER|SEVERA)_(\d+)%_")
RE_LARGA = re.compile(r"larga_")


def sha(ruta):
    return hashlib.sha256(open(ruta, 'rb').read()).hexdigest()


def ic_poisson(k, h):
    return [round(chi2.ppf(0.025, 2 * k) / 2 / h, 2) if k else 0.0, round(chi2.ppf(0.975, 2 * k + 2) / 2 / h, 2)]


def onsets_firmware(log):
    """Inicios de alarma del propio firmware (C de 0 a 1) con Motor:ON."""
    out, prev = [], 0
    for l in open(log, errors='ignore'):
        m = RE_C.search(l)
        if not m:
            continue
        c = int(m.group(3)) if m.group(2) == 'ON' else 0
        if c and not prev:
            out.append(float(m.group(1)))
        prev = c
    return out


def grupos_nuevos(fechas):
    vv = sorted(f for fecha in fechas for f in glob.glob(os.path.expanduser(f'~/tesis_itf/validacion_vivo/vivo_*_{fecha}_*_serial.log')))
    pl = sorted(f for fecha in fechas for f in glob.glob(os.path.expanduser(f'~/tesis_itf/prueba_larga/larga_{fecha}_*_serial.log')))
    excl = json.load(open(EXCLUSIONES)) if os.path.exists(EXCLUSIONES) else {}
    grupos, excluidas = [], []
    for log in vv + pl:
        nom = os.path.basename(log).replace('_serial.log', '')
        if nom in excl:
            excluidas.append(dict(sesion=nom, motivo=excl[nom]))
            continue
        m = RE_VIVO.search(nom)
        if m:
            grupos.append((nom, m.group(1), log, m.group(2)))
        elif RE_LARGA.search(nom):
            grupos.append((nom, 'SANO', log, None))
    return grupos, excluidas


def por_pulso(filas, score, umbral, k, pulsos):
    """Lista de booleanos (detectado o no) por pulso, con la logica de eventos del estudio 1."""
    ini = C.eventos(filas, score, umbral, k)
    return [any(a <= t <= b + C.T_COLA for t in ini) for a, b in pulsos]


def fa_y_expo(filas, score, umbral, k):
    ini = C.eventos(filas, score, umbral, k)
    lab = {f['t']: f['y'] for f in filas}
    fa = sum(1 for t in ini if lab.get(t) == 0)
    ts = [f['t'] for f in filas]
    expo = sum(b - a for (a, b), f in zip(zip(ts, ts[1:]), filas) if f['y'] == 0 and b - a < 5.0)
    return fa, expo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fecha', nargs='+', default=['20261015', '20261016'])
    ap.add_argument('--salida', default=os.path.expanduser('~/tesis_itf/validacion_ciega2'))
    args = ap.parse_args()
    os.makedirs(args.salida, exist_ok=True)

    # --- modelos congelados ---
    ruta_rf = os.path.join(MODELOS, 'rf_estudio1_13grupos.joblib')
    assert sha(ruta_rf) == SHA_RF, 'el RF congelado cambio'
    assert sha(os.path.join(MODELOS, 'variante_angulo35_leve4.py')) == SHA_VAR, 'la variante congelada cambio'
    rf = joblib.load(ruta_rf)
    meta = json.load(open(os.path.join(MODELOS, 'rf_estudio1_13grupos.json')))
    import sklearn
    if sklearn.__version__ != meta['sklearn']:
        print(f"AVISO: scikit-learn {sklearn.__version__} != {meta['sklearn']} del modelo congelado; usar /usr/bin/python3")

    grupos, excluidas = grupos_nuevos(args.fecha)
    if not grupos:
        sys.exit(f'No hay registros con fecha {args.fecha}')
    datos = C.construir([(n, c, l) for n, c, l, _ in grupos])
    carga = {n: cg for n, _, _, cg in grupos}

    res = dict(protocolo='PROTOCOLO_VALIDACION_CIEGA_2.md', fecha_datos=args.fecha, sklearn=sklearn.__version__,
               excluidas=excluidas, grupos={})
    tot = defaultdict(lambda: dict(fa=0, expo=0.0))
    pulsos_det = defaultdict(lambda: defaultdict(list))   # (clase, carga) -> detector -> [bool]
    for nom, cl, log, cg in grupos:
        d = datos[nom]
        filas = d['filas']
        if not filas:
            continue
        P = [f['P'] for f in filas]
        prob = rf.predict_proba(np.array([f['x'] for f in filas]))[:, 1]
        bl, pulsos = C.leer(log)
        lab = [C.etiquetar(b['t'], pulsos) for b in bl]
        g = dict(bloques=bl, pulsos=pulsos, lab=lab)
        pre = M.preparar(bl, 11)
        comp = M.puntuar_grupo(g, M.simular(pre, M.A_CFG))
        var = M.puntuar_grupo(g, VAR.simular(pre))
        fw_on = onsets_firmware(log)
        fw_fa = sum(1 for t in fw_on if C.etiquetar(t, pulsos) == 0)
        fila = dict(clase=cl, carga=cg, pulsos=len(pulsos))
        for etq, sc, u, k in (('regla', P, 0.40, 3), ('rf', prob, 0.55, 3)):
            fa, expo = fa_y_expo(filas, sc, u, k)
            tot[etq]['fa'] += fa
            tot[etq]['expo'] += expo
            fila[etq] = dict(fa=fa, det=por_pulso(filas, sc, u, k, pulsos))
            pulsos_det[(cl, cg)][etq] += fila[etq]['det']
        expo_ref = fa_y_expo(filas, P, 0.40, 3)[1]
        for etq, pg in (('regla_completa', comp), ('variante', var)):
            tot[etq]['fa'] += pg['fa']
            tot[etq]['expo'] += expo_ref
            fila[etq] = dict(fa=pg['fa'], det=[bool(x) for x in pg['det']], durs_fa=[round(x, 1) for x in pg['durs_fa']])
            pulsos_det[(cl, cg)][etq] += fila[etq]['det']
        tot['firmware']['fa'] += fw_fa
        tot['firmware']['expo'] += expo_ref
        fila['firmware'] = dict(fa=fw_fa)
        rs = log.replace('_serial.log', '_resumen.json')
        if os.path.exists(rs):
            r = json.load(open(rs))
            fila['firmware']['resumen_en_vivo'] = {k: r.get(k) for k in ('TP', 'FN', 'FP', 'TN', 'decision', 'severidad', 'sev_ok')}
        res['grupos'][nom] = fila

    # --- H1: falsas alarmas ---
    h = {k: v['expo'] / 3600 for k, v in tot.items()}
    res['falsas_alarmas'] = {k: dict(fa=v['fa'], horas=round(h[k], 3), fa_h=round(v['fa'] / h[k], 2) if h[k] else None,
                                     ic95=ic_poisson(v['fa'], h[k]) if h[k] else None) for k, v in tot.items()}
    a, b = tot['regla']['fa'], tot['rf']['fa']
    res['H1'] = dict(regla=a, rf=b, p_unilateral=binomtest(b, a + b, 0.5, alternative='less').pvalue if a + b else None,
                     confirmada=bool(a + b and binomtest(b, a + b, 0.5, alternative='less').pvalue < 0.05))

    # --- H2 y secundarias: deteccion por clase y carga ---
    det = {}
    for (cl, cg), dd in sorted(pulsos_det.items(), key=lambda x: (str(x[0][0]), str(x[0][1]))):
        if cl == 'SANO':
            continue
        r_, f_ = dd['regla'], dd['rf']
        solo_regla = sum(x and not y for x, y in zip(r_, f_))
        solo_rf = sum(y and not x for x, y in zip(r_, f_))
        det[f'{cl}_{cg}%'] = dict(n=len(r_), **{k: sum(v) for k, v in dd.items()}, solo_regla=solo_regla, solo_rf=solo_rf,
                                  mcnemar_p=binomtest(min(solo_regla, solo_rf), solo_regla + solo_rf, 0.5).pvalue
                                  if solo_regla + solo_rf else 1.0)
    res['deteccion'] = det
    res['H2'] = {k: v for k, v in det.items() if k.startswith('LEVE_0') or k.startswith('LEVE_25')}

    sal = os.path.join(args.salida, f"resultado_validacion_ciega2_{'_'.join(args.fecha)}.json")
    json.dump(res, open(sal, 'w'), indent=1, ensure_ascii=False, default=str)
    print(json.dumps({k: res[k] for k in ('falsas_alarmas', 'H1', 'deteccion', 'excluidas')}, indent=1, ensure_ascii=False, default=str))
    print('->', sal)


if __name__ == '__main__':
    main()
