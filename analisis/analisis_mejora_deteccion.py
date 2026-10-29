#!/usr/bin/env python3
"""
Analisis fuera de linea del ruido de la firma y de variantes del detector direccional.
Protocolo: PROTOCOLO_MEJORA_DETECCION.md (declarado antes de correr, commit 0518dd4).
Solo lee logs; no modifica el firmware ni los datos.

Parte 1: desviacion de Allan de zP, zQ (y V2/|V1|) en los tramos sanos de la prueba larga; sigma y
         autocorrelacion de P para cada longitud de referencia.
Parte 2: rejilla de variantes (referencia D, racha/media/CUSUM, compuerta |Q|) con el detector completo
         (enclavamiento, severidad, liberacion), seleccion LOGO anidada, analisis complementarios
         (liberacion, persistencia extra para LEVE) y verificacion aproximada por carga con los pares.
"""
import csv
import json
import math
import os
import statistics
import sys
from collections import defaultdict

import numpy as np
from scipy.stats import chi2

sys.path.insert(0, os.path.expanduser('~'))
import analisis_compensacion_v2 as V  # noqa: E402  (port fiel del detector y lector con campos del firmware)
import comparacion_ml_deteccion as C  # noqa: E402  (grupos, lector, reloj, etiquetas)
import exploracion_rf_cargas_pares as E  # noqa: E402  (pares del dataset por carga)

ANG = math.radians(-81.4)
ROT = complex(math.cos(-ANG), math.sin(-ANG))
REF_HASTA = 6.0
U1, U2 = 1.626, 4.471
LIB_FRAC = 0.35
SALIDA = os.path.expanduser('~/tesis_itf/mejora_deteccion')
SEV_N = {'LEVE': 1, 'INTER': 2, 'SEVERA': 3}

DS = (11, 20, 30, 60)
GATES = (None, 0.6, 0.45, 0.3)
US = [round(0.30 + 0.05 * i, 2) for i in range(11)]
FAMILIAS = ([('F1', u, k) for u in US for k in (2, 3, 4, 5)]
            + [('F2', u, n) for u in US for n in (2, 3, 4)]
            + [('F3', ka, h) for ka in (0.10, 0.15, 0.20, 0.25, 0.30, 0.40) for h in (0.4, 0.6, 0.8, 1.0, 1.2, 1.5, 2.0)])
A_CFG = ('F1', 0.40, 3, 11, None)


def sev_de(m):
    return 3 if m >= U2 else 2 if m >= U1 else 1


# ----------------------------------------------------------------------------------------------
# Preparacion: por grupo y por D, P/Q/|dz|/referencia de cada bloque
# ----------------------------------------------------------------------------------------------
def preparar(bloques, D):
    ts = C.reloj(bloques)
    out, h = [], []
    for b, t in zip(bloques, ts):
        if b['motor'] != 'ON' or b['i1'] < 1e-6:
            h = []
            out.append(None)
            continue
        z = b['r2'] / b['i1'] * 100
        ref = [zz for tt, zz in h if REF_HASTA <= t - tt <= D]
        h = [(tt, zz) for tt, zz in h if t - tt <= D] + [(t, z)]
        if len(ref) < 2:
            out.append(dict(z=z, ok=False))
            continue
        rr = C.med_c(ref)
        d = (z - rr) * ROT
        out.append(dict(z=z, ok=True, ref=rr, P=d.real, Q=d.imag, M=abs(d)))
    return out


def simular(pre, cfg, L=0.20, extra_leve=0):
    """Detector completo con la variante cfg = (familia, a, b, D, gate). Devuelve C y SEV por bloque."""
    fam, a, b, _D, g = cfg
    conf, sev, racha, S, buf, mag3 = 0, 0, 0, 0.0, [], [0.0, 0.0, 0.0]
    trig_seguidos = 0
    res = []
    for x in pre:
        if x is None:
            conf, sev, racha, S, buf, mag3, trig_seguidos = 0, 0, 0, 0.0, [], [0.0, 0.0, 0.0], 0
            res.append((0, 0))
            continue
        if x['ok']:
            P = x['P']
            e = P if (g is None or abs(x['Q']) <= g) else min(P, 0.0)
            mag3 = mag3[1:] + [x['M']]
            if fam == 'F1':
                racha = racha + 1 if e >= a else 0
                trig = racha >= b
            elif fam == 'F2':
                buf = (buf + [e])[-b:]
                trig = len(buf) == b and sum(buf) / b >= a
            else:
                S = max(0.0, S + e - a)
                trig = S >= b
            trig_seguidos = trig_seguidos + 1 if trig else 0
        if not conf:
            if x['ok'] and trig_seguidos >= 1:
                s0 = sev_de(statistics.median(mag3))
                if s0 == 1 and trig_seguidos < 1 + extra_leve:
                    res.append((0, 0))
                    continue
                conf, sev, base, pconf = 1, s0, x['ref'], x['P']
                ml3, nlat, bajos = [0.0, 0.0, 0.0], 0, 0
            res.append((conf, sev))
            continue
        dl = (x['z'] - base) * ROT
        ml3 = ml3[1:] + [abs(dl)]
        nlat += 1
        if nlat >= 3:
            sev = max(sev, sev_de(statistics.median(ml3)))
        bajos = bajos + 1 if dl.real < max(LIB_FRAC * pconf, L) else 0
        if bajos >= 3:
            conf, sev, racha, S, buf, trig_seguidos, bajos = 0, 0, 0, 0.0, [], 0, 0
        res.append((conf, sev))
    return res


def puntuar_grupo(g, res):
    """FA, detecciones por pulso, severidad, retardos, tiempo en FA y alarmas en drenado."""
    bl, pulsos, lab = g['bloques'], g['pulsos'], g['lab']
    eps, ini, smax = [], None, 0
    for i, (c, s) in enumerate(res):
        if c and ini is None:
            ini, smax = i, s
        elif c:
            smax = max(smax, s)
        elif ini is not None:
            eps.append((ini, i, smax))
            ini = None
    if ini is not None:
        eps.append((ini, len(res) - 1, smax))
    fa, t_fa, dren, durs_fa = 0, 0.0, 0, []
    det = [None] * len(pulsos)
    for i0, i1, s in eps:
        t0 = bl[i0]['t']
        k = next((j for j, (a, b) in enumerate(pulsos) if a <= t0 <= b + C.T_COLA), None)
        if k is not None:
            if det[k] is None:
                det[k] = (t0 - pulsos[k][0], s, bl[i1]['t'] < pulsos[k][1])
        elif lab[i0] == 0:
            fa += 1
            durs_fa.append(bl[i1]['t'] - t0)
        else:
            dren += 1
    t_fa = sum(durs_fa)
    return dict(fa=fa, t_fa=t_fa, durs_fa=durs_fa, dren=dren, det=det)


def agregar(pg, grupos, nombres):
    fa = sum(pg[n]['fa'] for n in nombres)
    expo = sum(grupos[n]['expo'] for n in nombres)
    det, tot, sevok, ret, prem = defaultdict(int), defaultdict(int), defaultdict(int), [], 0
    for n in nombres:
        cl = grupos[n]['clase']
        for d in pg[n]['det']:
            tot[cl] += 1
            if d:
                det[cl] += 1
                ret.append(d[0])
                sevok[cl] += d[1] == SEV_N[cl]
                prem += d[2]
    h = expo / 3600
    return dict(fa=fa, expo_h=round(h, 3), fa_h=round(fa / h, 2) if h else None,
                fa_h_ic95=[round(chi2.ppf(0.025, 2 * fa) / 2 / h, 2) if fa else 0.0,
                           round(chi2.ppf(0.975, 2 * fa + 2) / 2 / h, 2)] if h else None,
                t_fa_s_h=round(sum(pg[n]['t_fa'] for n in nombres) / h, 1) if h else None,
                dren=sum(pg[n]['dren'] for n in nombres),
                det={c: det[c] for c in ('LEVE', 'INTER', 'SEVERA')},
                tot={c: tot[c] for c in ('LEVE', 'INTER', 'SEVERA')},
                sev_ok={c: sevok[c] for c in ('LEVE', 'INTER', 'SEVERA')},
                retardo_med_s=round(statistics.median(ret), 1) if ret else None,
                liberadas_antes_de_toff=prem)


def clave_simple(cfg):
    fam, a, b, D, g = cfg
    return ({'F1': 0, 'F2': 1, 'F3': 2}[fam], D, GATES.index(g))


def elegir(cands, resultados, grupos, nombres, ref_det):
    best, bk = None, None
    for cfg in cands:
        ag = agregar(resultados[cfg], grupos, nombres)
        if any(ag['det'][c] < ref_det[c] for c in ref_det):
            continue
        k = (ag['fa'] / ag['expo_h'], -sum(ag['det'].values()), ag['retardo_med_s'] or 99, clave_simple(cfg))
        if bk is None or k < bk:
            best, bk = cfg, k
    return best


def cfg_str(cfg):
    fam, a, b, D, g = cfg
    est = {'F1': f'racha P>={a} x{b}', 'F2': f'media{b}(P)>={a}', 'F3': f'CUSUM k={a} h={b}'}[fam]
    return f"{est}, ref {D} s, compuerta {'no' if g is None else f'|Q|<={g}'}"


# ----------------------------------------------------------------------------------------------
# Parte 1: Allan
# ----------------------------------------------------------------------------------------------
def adev(x, m):
    x = np.asarray(x, float)
    cs = np.concatenate([[0.0], np.cumsum(x)])
    ybar = (cs[m:] - cs[:-m]) / m
    d = ybar[m:] - ybar[:-m]
    if len(d) < 5:
        return None
    return float(np.sqrt(0.5 * np.mean(d ** 2)))


def parte1(grupos):
    ms = [1, 2, 4, 8, 16, 32, 64, 128]
    out = {}
    for n in ('larga_25', 'larga_50', 'larga_75', 'larga_0'):
        bl = grupos[n]['bloques']
        z = [b['r2'] / b['i1'] * 100 * ROT for b in bl if b['motor'] == 'ON']
        v = [b['v2'] / b['v1'] * 100 * ROT for b in bl if b['motor'] == 'ON']
        series = {'zP': [c.real for c in z], 'zQ': [c.imag for c in z], 'v2P': [c.real for c in v], 'v2Q': [c.imag for c in v]}
        r = {}
        for s, xs in series.items():
            sig = [adev(xs, m) for m in ms]
            pend = [round(math.log(sig[i + 1] / sig[i]) / math.log(2), 2) if sig[i] and sig[i + 1] else None
                    for i in range(len(ms) - 1)]
            r[s] = dict(tau_s=[round(m * 1.70, 1) for m in ms], adev=[round(s_, 4) if s_ else None for s_ in sig],
                        pendiente=pend)
        out[n] = r
    # sigma y autocorrelacion lag-1 de P (sano) por D
    porD = {}
    for D in DS:
        Ps, ac = [], []
        for n in ('larga_25', 'larga_50', 'larga_75', 'larga_0'):
            p = [x['P'] for x in grupos[n]['pre'][D] if x and x['ok']]
            Ps += p
            pa = np.array(p)
            ac.append(float(np.corrcoef(pa[:-1], pa[1:])[0, 1]))
        Ps = np.array(Ps)
        porD[D] = dict(sigma_P=round(float(Ps.std()), 4), frac_P_ge_040=round(float((Ps >= 0.40).mean()), 4),
                       autocorr_lag1_med=round(statistics.median(ac), 3))
    return dict(allan=out, P_por_referencia=porD)


# ----------------------------------------------------------------------------------------------
# Verificacion aproximada por carga (pares del dataset)
# ----------------------------------------------------------------------------------------------
def pares_detectar(cfg):
    fam, a, b, _D, g = cfg
    filas = []
    for log in E.SESIONES:
        ps = E.pulsos_aprox(log)
        det = nb = 0
        for pre, fal in ps:
            zr = C.med_c([x['r2'] / x['i1'] * 100 for x in pre])
            racha, S, buf, hit = 0, 0.0, [], False
            nb = max(nb, len(fal))
            for x in fal:
                d = (x['r2'] / x['i1'] * 100 - zr) * ROT
                e = d.real if (g is None or abs(d.imag) <= g) else min(d.real, 0.0)
                if fam == 'F1':
                    racha = racha + 1 if e >= a else 0
                    hit |= racha >= b
                elif fam == 'F2':
                    buf = (buf + [e])[-b:]
                    hit |= len(buf) == b and sum(buf) / b >= a
                else:
                    S = max(0.0, S + e - a)
                    hit |= S >= b
            det += hit
        nom = os.path.basename(log).replace('cap_ENTRELAZADA_', '').split('_2026')[0]
        filas.append(dict(sesion=nom, det=det, n=len(ps)))
    return filas


def bloques_necesarios(cfg):
    fam, a, b, *_ = cfg
    if fam == 'F1':
        return b
    if fam == 'F2':
        return b
    return 1  # la CUSUM puede confirmar en 1 bloque si la firma es grande; se evalua igual


# ----------------------------------------------------------------------------------------------
def main():
    os.makedirs(SALIDA, exist_ok=True)
    rep = {'protocolo': 'PROTOCOLO_MEJORA_DETECCION.md (commit 0518dd4)'}

    # --- datos ---
    grupos = {}
    for nom, clase, log in C.GRUPOS:
        bl, pulsos = C.leer(log)
        lab = [C.etiquetar(b['t'], pulsos) for b in bl]
        g = dict(clase=clase, bloques=bl, pulsos=pulsos, lab=lab, pre={D: preparar(bl, D) for D in DS})
        ts = [b['t'] for b in bl]
        ok11 = g['pre'][11]
        g['expo'] = sum(t2 - t1 for i, (t1, t2) in enumerate(zip(ts, ts[1:]))
                        if lab[i] == 0 and ok11[i] and ok11[i]['ok'] and t2 - t1 < 5.0)
        grupos[nom] = g
    nombres = list(grupos)

    # --- fidelidad: el simulador con A y los 'r' reales debe dar los eventos del firmware ---
    fid = {}
    for nom, base in (('larga_25', 'larga_20261012_1319'), ('larga_50', 'larga_20261012_1350'),
                      ('larga_75', 'larga_20261012_1422'), ('larga_0', 'larga_20261012_1457')):
        blv = V.leer(os.path.join(V.PL_DIR, base + '_serial.log'))
        fr = os.path.join(V.PL_DIR, base + '_reinicios.csv')
        rein = [float(r['t_envio']) for r in csv.DictReader(open(fr)) if r.get('t_envio', '').strip()] if os.path.exists(fr) else []
        port = V.correr(blv, 0j, rein)
        fid[nom] = dict(eventos_port_con_r=len(V.eventos(blv, port)),
                        c_port_vs_fw=round(sum(b['fw_c'] == r[0] for b, r in zip(blv, port) if b['motor'] == 'ON' and b['fw_ref']) /
                                           sum(1 for b in blv if b['motor'] == 'ON' and b['fw_ref']), 4))
        res_sin_r_port = V.correr(blv, 0j, ())
        mio = simular(preparar(blv, 11), A_CFG)
        fid[nom]['c_simulador_vs_port_sin_r'] = round(sum(a[0] == b[0] for a, b in zip(mio, res_sin_r_port)) / len(mio), 4)
        fid[nom]['sev_simulador_vs_port_sin_r'] = round(sum(a[1] == b[3] for a, b in zip(mio, res_sin_r_port)) / len(mio), 4)
    rep['fidelidad'] = fid
    print('fidelidad', json.dumps(fid))

    # --- Parte 1 ---
    rep['parte1_ruido'] = parte1(grupos)
    print('parte1', json.dumps(rep['parte1_ruido']['P_por_referencia']))

    # --- Parte 2: rejilla ---
    cfgs = [(f, a, b, D, g) for (f, a, b) in FAMILIAS for D in DS for g in GATES]
    resultados = {}
    for i, cfg in enumerate(cfgs):
        resultados[cfg] = {n: puntuar_grupo(grupos[n], simular(grupos[n]['pre'][cfg[3]], cfg)) for n in nombres}
        if i % 200 == 0:
            print(f'  rejilla {i}/{len(cfgs)}', flush=True)
    A = agregar(resultados[A_CFG], grupos, nombres)
    rep['A_firmware_sin_r'] = A
    print('A', json.dumps(A))

    restr = {
        'a_umbral_persistencia': lambda c: c[0] == 'F1' and c[3] == 11 and c[4] is None,
        'b_mas_referencia': lambda c: c[0] == 'F1' and c[4] is None,
        'c_mas_compuerta': lambda c: c[0] == 'F1',
        'd_media_movil': lambda c: c[0] == 'F2',
        'e_cusum': lambda c: c[0] == 'F3',
        'f_todo': lambda c: True,
    }
    logo = {}
    for etq, filtro in restr.items():
        cands = [c for c in cfgs if filtro(c)]
        pg_out, elegidas = {}, {}
        for n in nombres:
            otros = [m for m in nombres if m != n]
            ref_det = agregar(resultados[A_CFG], grupos, otros)['det']
            cfg = elegir(cands, resultados, grupos, otros, ref_det) or A_CFG
            elegidas[n] = cfg_str(cfg)
            pg_out[n] = resultados[cfg][n]
        ag = agregar(pg_out, grupos, nombres)
        final = elegir(cands, resultados, grupos, nombres, A['det'])
        logo[etq] = dict(fuera_de_muestra=ag, elegidas_por_pliegue=elegidas, config_final=cfg_str(final),
                         final_en_muestra=agregar(resultados[final], grupos, nombres), _final=final)
        print(etq, json.dumps(ag['fa']), ag['fa_h'], ag['det'], '| final:', cfg_str(final), flush=True)
    final = logo['f_todo']['_final']

    # --- curva de compromiso (en muestra, descriptiva): menor FA por numero de LEVE detectadas ---
    curva = {}
    for cfg in cfgs:
        ag = agregar(resultados[cfg], grupos, nombres)
        if ag['det']['INTER'] < A['det']['INTER'] or ag['det']['SEVERA'] < A['det']['SEVERA']:
            continue
        lv = ag['det']['LEVE']
        if lv not in curva or ag['fa'] < curva[lv][0]:
            curva[lv] = (ag['fa'], cfg_str(cfg), ag['fa_h'])
    rep['curva_compromiso_en_muestra'] = {lv: dict(fa=v[0], fa_h=v[2], cfg=v[1]) for lv, v in sorted(curva.items(), reverse=True)}
    # la de mayor reduccion: menos FA conservando INTER y SEVERA (LEVE puede perder)
    mayor = min((c for c in cfgs if all(agregar(resultados[c], grupos, nombres)['det'][k] >= A['det'][k] for k in ('INTER', 'SEVERA'))),
                key=lambda c: (agregar(resultados[c], grupos, nombres)['fa'], -agregar(resultados[c], grupos, nombres)['det']['LEVE']))

    # --- complementarios ---
    comp = {}
    for etq, cfg in (('A', A_CFG), ('final', final), ('mayor_reduccion', mayor)):
        d = {'config': cfg_str(cfg)}
        for L in (0.20, 0.30, 0.40):
            pg = {n: puntuar_grupo(grupos[n], simular(grupos[n]['pre'][cfg[3]], cfg, L=L)) for n in nombres}
            ag = agregar(pg, grupos, nombres)
            durs = sorted(round(x, 1) for n in nombres for x in pg[n]['durs_fa'])
            d[f'liberacion_L{L}'] = dict(fa=ag['fa'], t_fa_s_h=ag['t_fa_s_h'], det=ag['det'], sev_ok=ag['sev_ok'],
                                         liberadas_antes_de_toff=ag['liberadas_antes_de_toff'], durs_fa_s=durs)
        for e in (2, 4, 6):
            pg = {n: puntuar_grupo(grupos[n], simular(grupos[n]['pre'][cfg[3]], cfg, extra_leve=e)) for n in nombres}
            ag = agregar(pg, grupos, nombres)
            d[f'extra_leve_{e}'] = dict(fa=ag['fa'], fa_h=ag['fa_h'], det_INTER=ag['det']['INTER'], det_SEVERA=ag['det']['SEVERA'],
                                        det_LEVE_no_medible_con_pulsos_de_7_11s=ag['det']['LEVE'])
        comp[etq] = d
    rep['complementarios'] = comp

    # --- verificacion aproximada por carga ---
    ver = {}
    for etq, cfg in (('A', A_CFG), ('final', final), ('mayor_reduccion', mayor)):
        ver[etq] = dict(config=cfg_str(cfg), bloques_necesarios=bloques_necesarios(cfg),
                        realizable=bloques_necesarios(cfg) <= 3, sesiones=pares_detectar(cfg))
    rep['verificacion_por_carga'] = ver

    # --- criterio ---
    fo = logo['f_todo']['fuera_de_muestra']
    c1 = fo['fa'] / fo['expo_h'] <= 0.5 * A['fa'] / A['expo_h']
    c2 = all(fo['det'][k] >= A['det'][k] for k in A['det'])
    perdidas = {}
    for sa, sf in zip(ver['A']['sesiones'], ver['final']['sesiones']):
        if sa['sesion'].startswith('LEVE'):
            perdidas[sa['sesion']] = sa['det'] - sf['det']
    c3 = (not ver['final']['realizable']) or all(v <= 2 for v in perdidas.values())
    rep['criterio'] = dict(c1_fa_fuera_muestra_le_50pct_de_A=c1, c2_detecciones_ge_A=c2,
                           c3_por_carga=c3, perdidas_LEVE_por_carga=perdidas,
                           verificacion_realizable=ver['final']['realizable'],
                           recomendar_validacion_banco=bool(c1 and c2 and c3))
    for v in logo.values():
        v.pop('_final')
    rep['logo'] = logo
    rep['config_final'] = cfg_str(final)
    rep['config_mayor_reduccion'] = cfg_str(mayor)

    with open(os.path.join(SALIDA, 'resultado_mejora_deteccion.json'), 'w') as fh:
        json.dump(rep, fh, indent=1, ensure_ascii=False, default=str)
    print('criterio', json.dumps(rep['criterio'], ensure_ascii=False))
    print('verificacion', json.dumps(ver, ensure_ascii=False))
    print('complementarios', json.dumps(comp, ensure_ascii=False))


if __name__ == '__main__':
    main()
