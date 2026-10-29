"""
Variante congelada (14-oct-2026) para la validacion ciega 2: regla del firmware + compuerta por angulo
(|Q| <= tan(35 grados) * P) + confirmacion de LEVE con 4 bloques (INTER/SEVERA con 3).
Elegida POST HOC en ~/tesis_itf/mejora_deteccion/explora_post_hoc2.py (simular2 con ang=35, extra_leve=1);
copiada aqui sin cambios de logica. Entrada: lista de analisis_mejora_deteccion.preparar(bloques, 11).
"""
import math
import os
import statistics
import sys

sys.path.insert(0, os.path.expanduser('~'))
import analisis_mejora_deteccion as M  # noqa: E402

ROT = M.ROT
U, K, EXTRA_LEVE, ANG, L = 0.40, 3, 1, 35.0, 0.20


def simular(pre, u=U, k=K, extra_leve=EXTRA_LEVE, ang=ANG, L=L):
    conf, sev, racha, mag3 = 0, 0, 0, [0.0] * 3
    res = []
    for x in pre:
        if x is None:
            conf, sev, racha, mag3 = 0, 0, 0, [0.0] * 3
            res.append((0, 0))
            continue
        if x['ok']:
            d = (x['z'] - x['ref']) * ROT
            P, Q = d.real, d.imag
            ok_dir = abs(Q) <= math.tan(math.radians(ang)) * max(P, 0)
            e = P if ok_dir else min(P, 0.0)
            mag3 = mag3[1:] + [abs(d)]
            racha = racha + 1 if e >= u else 0
        if not conf:
            if x['ok'] and racha >= k:
                s0 = M.sev_de(statistics.median(mag3))
                if s0 == 1 and racha < k + extra_leve:
                    res.append((0, 0))
                    continue
                conf, sev, pconf, base = 1, s0, P, x['ref']
                ml3, nlat, bajos = [0.0] * 3, 0, 0
            res.append((conf, sev))
            continue
        dl = (x['z'] - base) * ROT
        ml3 = ml3[1:] + [abs(dl)]
        nlat += 1
        if nlat >= 3:
            sev = max(sev, M.sev_de(statistics.median(ml3)))
        bajos = bajos + 1 if dl.real < max(M.LIB_FRAC * pconf, L) else 0
        if bajos >= 3:
            conf, sev, racha, bajos = 0, 0, 0, 0
        res.append((conf, sev))
    return res
