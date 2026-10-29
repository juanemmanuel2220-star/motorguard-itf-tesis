import sys, os, math, statistics
sys.path.insert(0, os.path.expanduser('~'))
import analisis_mejora_deteccion as M
import comparacion_ml_deteccion as C
ROT = M.ROT

def simular2(pre, u=0.40, k=3, extra_leve=0, congelar=False, ang=None, L=0.20):
    """Como M.simular (F1) con: congelar la referencia al primer bloque de la racha; compuerta por angulo."""
    conf, sev, racha, mag3, cand = 0, 0, 0, [0.0]*3, None
    res = []
    for x in pre:
        if x is None:
            conf, sev, racha, mag3, cand = 0, 0, 0, [0.0]*3, None
            res.append((0, 0)); continue
        if x['ok']:
            ref = cand if (congelar and cand is not None and not conf) else x['ref']
            d = (x['z'] - ref) * ROT
            P, Q = d.real, d.imag
            ok_dir = ang is None or abs(Q) <= math.tan(math.radians(ang)) * max(P, 0)
            e = P if ok_dir else min(P, 0.0)
            mag3 = mag3[1:] + [abs(d)]
            if e >= u:
                if racha == 0 and congelar and not conf:
                    cand = x['ref']
                racha += 1
            else:
                racha, cand = 0, None
        if not conf:
            if x['ok'] and racha >= k:
                s0 = M.sev_de(statistics.median(mag3))
                if s0 == 1 and racha < k + extra_leve:
                    res.append((0, 0)); continue
                conf, sev, pconf = 1, s0, P
                base = cand if (congelar and cand is not None) else x['ref']
                ml3, nlat, bajos = [0.0]*3, 0, 0
            res.append((conf, sev)); continue
        dl = (x['z'] - base) * ROT
        ml3 = ml3[1:] + [abs(dl)]; nlat += 1
        if nlat >= 3: sev = max(sev, M.sev_de(statistics.median(ml3)))
        bajos = bajos + 1 if dl.real < max(M.LIB_FRAC * pconf, L) else 0
        if bajos >= 3: conf, sev, racha, bajos, cand = 0, 0, 0, 0, None
        res.append((conf, sev))
    return res

grupos = {}
for nom, clase, log in C.GRUPOS:
    bl, pulsos = C.leer(log)
    lab = [C.etiquetar(b['t'], pulsos) for b in bl]
    g = dict(clase=clase, bloques=bl, pulsos=pulsos, lab=lab, pre={11: M.preparar(bl, 11), 20: M.preparar(bl, 20)})
    ts = [b['t'] for b in bl]; ok11 = g['pre'][11]
    g['expo'] = sum(t2 - t1 for i, (t1, t2) in enumerate(zip(ts, ts[1:])) if lab[i] == 0 and ok11[i] and ok11[i]['ok'] and t2 - t1 < 5.0)
    grupos[nom] = g
nombres = list(grupos)
# verificacion: sin opciones = A
pg = {n: M.puntuar_grupo(grupos[n], simular2(grupos[n]['pre'][11])) for n in nombres}
pgA = {n: M.puntuar_grupo(grupos[n], M.simular(grupos[n]['pre'][11], M.A_CFG)) for n in nombres}
print("simular2 sin opciones == A:", all(pg[n]['fa'] == pgA[n]['fa'] and pg[n]['det'] == pgA[n]['det'] for n in nombres))

def linea(etq, D=11, **kw):
    pg = {n: M.puntuar_grupo(grupos[n], simular2(grupos[n]['pre'][D], **kw)) for n in nombres}
    ag = M.agregar(pg, grupos, nombres)
    l1529 = sum(1 for d in pg['LEVE_1007_1529']['det'] if d)
    lc = sum(1 for n in nombres if grupos[n]['clase'] == 'LEVE' and n != 'LEVE_1007_1529' for d in pg[n]['det'] if d)
    print(f"{etq:44} FA={ag['fa']:2} ({ag['fa_h']:4}/h) INTER={ag['det']['INTER']}/22 SEV={ag['det']['SEVERA']}/12 sevOK={ag['sev_ok']} "
          f"LEVE 11s={l1529}/10 LEVE 7s={lc}/50 ret={ag['retardo_med_s']} durFA={sorted(round(x) for n in nombres for x in pg[n]['durs_fa'])}")

pass
pass
pass
pass
pass

print("\n== combinaciones angulo x LEVE+1 (post hoc)")
for a in (30, 35, 40):
    linea(f'A + angulo<={a}', ang=a)
    linea(f'A + angulo<={a} + LEVE +1', ang=a, extra_leve=1)
