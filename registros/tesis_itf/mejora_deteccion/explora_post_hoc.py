import sys, os, math, statistics, json
sys.path.insert(0, os.path.expanduser('~'))
import analisis_mejora_deteccion as M
import comparacion_ml_deteccion as C
import exploracion_rf_cargas_pares as E

# 1) Angulo de dz en los pares por sesion (por que falla la compuerta absoluta)
print("== angulo y |dz| de la firma en los pares (mediana por sesion), respecto a -81.4")
pares = {}
for log in E.SESIONES:
    nom = os.path.basename(log).replace('cap_ENTRELAZADA_', '').split('_2026')[0]
    ps = E.pulsos_aprox(log)
    pares[nom] = []
    angs, mags, qs = [], [], []
    for pre, fal in ps:
        zr = C.med_c([x['r2'] / x['i1'] * 100 for x in pre])
        ds = [(x['r2'] / x['i1'] * 100 - zr) * M.ROT for x in fal]
        pares[nom].append(ds)
        d = complex(statistics.median([q.real for q in ds]), statistics.median([q.imag for q in ds]))
        angs.append(math.degrees(math.atan2(d.imag, d.real))); mags.append(abs(d)); qs.append(abs(d.imag))
    print(f"  {nom:11} ang_med={statistics.median(angs):+6.1f}  |dz|_med={statistics.median(mags):5.2f}  |Q|_med={statistics.median(qs):5.2f}  nfal_min={min(len(x) for x in pares[nom])}")

def det_pares(fam, a, b, gate, minbloques):
    out = {}
    for nom, lst in pares.items():
        det = n = 0
        for ds in lst:
            if len(ds) < minbloques: continue
            n += 1
            racha, S, buf, hit = 0, 0.0, [], False
            for d in ds:
                ok = gate(d)
                e = d.real if ok else min(d.real, 0.0)
                if fam == 'F1': racha = racha + 1 if e >= a else 0; hit |= racha >= b
                elif fam == 'F2': buf = (buf + [e])[-b:]; hit |= len(buf) == b and sum(buf) / b >= a
            det += hit
        out[nom] = f"{det}/{n}"
    return out

sin = lambda d: True
abs03 = lambda d: abs(d.imag) <= 0.3
rel = lambda th: (lambda d: abs(d.imag) <= math.tan(math.radians(th)) * max(d.real, 0))
print("\n== pares con >= 4 bloques de falla (verificacion realizable para configuraciones de 4 bloques)")
for etq, args in [('A racha0.40x3', ('F1', .40, 3, sin)), ('media4>=0.5 sin compuerta', ('F2', .5, 4, sin)),
                  ('media4>=0.5 |Q|<=0.3', ('F2', .5, 4, abs03)), ('A + |Q|<=0.3', ('F1', .40, 3, abs03)),
                  ('A + angulo<=30', ('F1', .40, 3, rel(30))), ('A + angulo<=45', ('F1', .40, 3, rel(45)))]:
    print(f"  {etq:28}", det_pares(*args, minbloques=4))

# 2) LOGO / en muestra con variantes no declaradas, sobre los 13 grupos en vivo
grupos = {}
for nom, clase, log in C.GRUPOS:
    bl, pulsos = C.leer(log)
    lab = [C.etiquetar(b['t'], pulsos) for b in bl]
    g = dict(clase=clase, bloques=bl, pulsos=pulsos, lab=lab, pre={D: M.preparar(bl, D) for D in (11, 20, 30)})
    ts = [b['t'] for b in bl]; ok11 = g['pre'][11]
    g['expo'] = sum(t2 - t1 for i, (t1, t2) in enumerate(zip(ts, ts[1:])) if lab[i] == 0 and ok11[i] and ok11[i]['ok'] and t2 - t1 < 5.0)
    grupos[nom] = g
nombres = list(grupos)
def corre(cfg, **kw):
    pg = {n: M.puntuar_grupo(grupos[n], M.simular(grupos[n]['pre'][cfg[3]], cfg, **kw)) for n in nombres}
    return M.agregar(pg, grupos, nombres), pg
print("\n== en vivo (13 grupos, en muestra), variantes no declaradas")
for etq, cfg in [('A', ('F1', .40, 3, 11, None)), ('media4>=0.5 ref20 sin compuerta', ('F2', .5, 4, 20, None)),
                 ('media3>=0.5 ref20 sin compuerta', ('F2', .5, 3, 20, None)),
                 ('A ref20', ('F1', .40, 3, 20, None))]:
    ag, _ = corre(cfg)
    print(f"  {etq:34} FA={ag['fa']:2} ({ag['fa_h']}/h) det={ag['det']} ret={ag['retardo_med_s']}")
for e in (1, 2, 3, 4):
    ag, pg = corre(('F1', .40, 3, 11, None), extra_leve=e)
    print(f"  A + LEVE {e} bloques extra           FA={ag['fa']:2} ({ag['fa_h']}/h) INTER={ag['det']['INTER']} SEV={ag['det']['SEVERA']} LEVE(no medible)={ag['det']['LEVE']}  durFA={sorted(round(x,1) for n in nombres for x in pg[n]['durs_fa'])}")
# cuantos pulsos LEVE en vivo tienen bloques suficientes: duracion de los pulsos LEVE de 15:29 (11.2 s)
ag, pg = corre(('F1', .40, 3, 11, None), extra_leve=2)
print("  LEVE_1007_1529 (pulsos 11.2 s) con +2:", sum(1 for d in pg['LEVE_1007_1529']['det'] if d), "/", len(pg['LEVE_1007_1529']['det']),
      " A:", sum(1 for d in corre(('F1', .40, 3, 11, None))[1]['LEVE_1007_1529']['det'] if d))
