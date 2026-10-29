#!/usr/bin/env python3
"""
Analisis fuera de linea (POST HOC, exploratorio): compensacion del desbalance de la red con V2.

Pregunta: las falsas alarmas de la prueba larga sin falla (12-oct-2026, 11 eventos en 90 min) se
deben a cambios del desbalance de voltaje de la red? Si se resta la corriente de secuencia negativa
que el motor sano toma por el desbalance de voltaje, I2_red = Y2 * V2, desaparecen sin perder la
deteccion de fallas reales?

Metodo (no modifica el firmware ni los datos; solo lee los _serial.log):
  1. Port exacto de detector_dir.cpp (firmware 299a943). Se verifica reproduciendo la decision del
     firmware (P, C, SEV) bloque a bloque sobre los mismos logs.
  2. Variante compensada: R2c = R2 - Y2 * V2 (mismos fasores RAW, referidos a arg(V1)), con el
     mismo detector, mismos umbrales, misma direccion -81.4 y mismos umbrales de severidad.
  3. Y2 (admitancia de secuencia negativa del motor, compleja) se estima por minimos cuadrados con
     los CAMBIOS (dR2 frente a dV2, contra la misma referencia movil del detector) en datos SIN
     falla de la prueba larga. Validacion cruzada: se estima con 3 tramos y se evalua en el cuarto
     (dejando una carga fuera). Para las validaciones con falla se usa Y2 estimado con los 4 tramos
     (esas validaciones no participan en la estimacion).
  4. Se evaluan: (a) falsas alarmas en los 4 tramos de la prueba larga; (b) TP/FN/FP/TN y severidad
     en las validaciones ciegas en vivo con falla real (misma ventana de puntuacion: de inicio de la
     prueba a fin + 2 s).
Limitaciones: post hoc y con los mismos datos que motivaron la idea; las validaciones con falla son
todas al 75 %. Un resultado positivo justifica una validacion nueva, no sustituye a la validacion.
"""
import cmath
import csv
import glob
import json
import math
import os
import re
import statistics
import sys

ANG = math.radians(-81.4)
UMBRAL, PERS, LIB_FRAC = 0.40, 3, 0.35
REF_DESDE, REF_HASTA, HIST = 11.0, 6.0, 30.0
HIST_N = 32
U1, U2 = 1.626, 4.471
PL_DIR = os.path.expanduser('~/tesis_itf/prueba_larga')
VV_DIR = os.path.expanduser('~/tesis_itf/validacion_vivo')
SALIDA = os.path.expanduser('~/tesis_itf/prueba_larga/analisis_v2')

RE_LINEA = re.compile(r"^([\d.]+) \[MCSA\] Motor:(\w+).*U2V=([\d.]+)%.*RAW: R2=([-\d.]+),([-\d.]+) I1=([-\d.]+) "
                      r"V2=([-\d.]+),([-\d.]+) V1=([-\d.]+) \| DIR: P=([-\d.]+) R=(\d+) C=(\d) REF=(\d) CUSUM=\d SEV=(\d)")


def leer(log):
    """Bloques del firmware: t (host), motor, u2v, R2, I1, V2, V1 y la decision del firmware."""
    out = []
    for l in open(log, errors='ignore'):
        m = RE_LINEA.search(l)
        if not m:
            continue
        g = m.groups()
        out.append(dict(t=float(g[0]), motor=g[1], u2v=float(g[2]), r2=complex(float(g[3]), float(g[4])),
                        i1=float(g[5]), v2=complex(float(g[6]), float(g[7])), v1=float(g[8]),
                        fw_p=float(g[9]), fw_r=int(g[10]), fw_c=int(g[11]), fw_ref=int(g[12]), fw_sev=int(g[13])))
    return out


def proyectar(z):
    return z.real * math.cos(ANG) + z.imag * math.sin(ANG)


def sev_de(mag):
    return 3 if mag >= U2 else 2 if mag >= U1 else 1


class Detector:
    """Port de detector_dir.cpp (299a943). Mediana por componente como statistics.median."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.h = []          # (t, z)
        self.racha = 0
        self.mag3 = [0.0] * PERS
        self.conf = 0
        self.sev = 0
        self.p = 0.0
        self.ref_ok = 0

    def step(self, t, r2, i1):
        if i1 < 1e-6:
            return self.sev
        z = r2 / i1 * 100.0
        ref = [zz for tt, zz in self.h if REF_HASTA <= t - tt <= REF_DESDE]
        self.h = [(tt, zz) for tt, zz in self.h if t - tt <= HIST]
        if len(self.h) == HIST_N:
            self.h.pop(0)
        self.h.append((t, z))
        self.ref_ok = len(ref) >= 2
        rr = 0j
        if self.ref_ok:
            rr = complex(statistics.median([x.real for x in ref]), statistics.median([x.imag for x in ref]))
            d = z - rr
            self.p = proyectar(d)
            self.racha = self.racha + 1 if self.p >= UMBRAL else 0
            self.mag3 = self.mag3[1:] + [abs(d)]
        if not self.conf:
            if self.ref_ok and self.racha >= PERS:
                self.conf, self.base, self.pconf = 1, rr, self.p
                self.sev = sev_de(statistics.median(self.mag3))
                self.ml3, self.nlat, self.bajos = [0.0] * PERS, 0, 0
            return self.sev
        dl = z - self.base
        pl = proyectar(dl)
        self.ml3 = self.ml3[1:] + [abs(dl)]
        self.nlat += 1
        if self.nlat >= PERS:
            self.sev = max(self.sev, sev_de(statistics.median(self.ml3)))
        nivel = max(LIB_FRAC * self.pconf, 0.5 * UMBRAL)
        self.bajos = self.bajos + 1 if pl < nivel else 0
        if self.bajos >= PERS:
            self.conf = self.sev = self.racha = self.bajos = 0
        return self.sev


def reloj_firmware(bloques):
    """Tiempo de bloque reconstruido: el host recibe las tramas con retraso irregular (lecturas por
    rafagas), el firmware las produce a paso casi constante. Dentro de cada racha continua de
    bloques se usa t0 + i * paso medio de la racha."""
    ts, ini = [], 0
    for i in range(1, len(bloques) + 1):
        if i == len(bloques) or bloques[i]['t'] - bloques[i - 1]['t'] > 5.0:
            seg = bloques[ini:i]
            paso = (seg[-1]['t'] - seg[0]['t']) / (len(seg) - 1) if len(seg) > 1 else 1.7
            ts += [seg[0]['t'] + k * paso for k in range(len(seg))]
            ini = i
    return ts


def correr(bloques, y2=0j, reinicios=()):
    """Corre el detector; y2=0 reproduce el firmware. reinicios: tiempos host en los que se envio 'r'."""
    det = Detector()
    ts = reloj_firmware(bloques)
    res, pend = [], sorted(reinicios)
    for b, t in zip(bloques, ts):
        while pend and b['t'] >= pend[0]:
            det.reset()
            pend.pop(0)
        if b['motor'] != 'ON':
            det.reset()
            res.append((0, 0.0, 0, 0))
            continue
        sev = det.step(t, b['r2'] - y2 * b['v2'], b['i1'])
        res.append((det.conf, det.p, det.racha, sev))
    return res


def eventos(bloques, res):
    ev, ini, smax = [], None, 0
    for b, (c, p, r, s) in zip(bloques, res):
        if c and ini is None:
            ini, smax = b['t'], s
        elif c:
            smax = max(smax, s)
        elif not c and ini is not None:
            ev.append((ini, b['t'] - ini, smax))
            ini = None
    if ini is not None:
        ev.append((ini, bloques[-1]['t'] - ini, smax))
    return ev


def deltas(bloques):
    """Pares (dR2/|I1|, dV2/|I1|) contra la mediana de [t-11, t-6] s, solo con el motor en ON."""
    ts = reloj_firmware(bloques)
    xs, ys, h = [], [], []
    for b, t in zip(bloques, ts):
        if b['motor'] != 'ON' or b['i1'] < 1e-6:
            h = []
            continue
        r = b['r2'] / b['i1'] * 100
        v = b['v2'] / b['i1'] * 100
        ref = [(rr, vv) for tt, rr, vv in h if REF_HASTA <= t - tt <= REF_DESDE]
        h = [x for x in h if t - x[0] <= HIST] + [(t, r, v)]
        if len(ref) >= 2:
            rm = complex(statistics.median([x[0].real for x in ref]), statistics.median([x[0].imag for x in ref]))
            vm = complex(statistics.median([x[1].real for x in ref]), statistics.median([x[1].imag for x in ref]))
            ys.append(r - rm)
            xs.append(v - vm)
    return xs, ys


def ajustar_y2(pares):
    """Minimos cuadrados complejos sin termino independiente: dR = Y2 * dV."""
    num = sum(y * x.conjugate() for x, y in pares)
    den = sum(abs(x) ** 2 for x, _ in pares)
    return num / den


def r2_ajuste(pares, y2):
    sr = sum(abs(y - y2 * x) ** 2 for x, y in pares)
    st = sum(abs(y) ** 2 for _, y in pares)
    return 1 - sr / st


def puntuar_vivo(base, bloques, res):
    """TP/FN/FP/TN con la ventana de validacion_vivo_direccional.py: [inicio de la prueba, fin + 2 s]."""
    plan = json.load(open(base + '_plan.json'))['plan']
    filas = list(csv.DictReader(open(base + '_tramas.csv')))
    vent = {}
    for f in filas:
        k = int(f['prueba'])
        if f['fase'] == 'PRUEBA' and k > 0:
            a, b = vent.get(k, (float(f['t']), float(f['t'])))
            vent[k] = (min(a, float(f['t'])), max(b, float(f['t'])))
    tp = fn = fp = tn = 0
    sevs = []
    for k, (a, b) in sorted(vent.items()):
        alarma = [(c, s) for bl, (c, p, r, s) in zip(bloques, res) if a <= bl['t'] <= b + 2.0 and c]
        real = plan[k - 1] == 'REAL'
        if real and alarma:
            tp += 1
            sevs.append(max(s for _, s in alarma))
        elif real:
            fn += 1
        elif alarma:
            fp += 1
        else:
            tn += 1
    return dict(TP=tp, FN=fn, FP=fp, TN=tn, sev=[['-', 'LEVE', 'INTER', 'SEVERA'][s] for s in sevs])


def main():
    os.makedirs(SALIDA, exist_ok=True)
    rep = {'nota': 'POST HOC / exploratorio. Firmware 299a943 sin cambios; solo lectura de logs.'}

    # --- 1. Prueba larga: datos, fidelidad del port, estimacion de Y2 ---
    tramos = [('25 %', 'larga_20261012_1319'), ('50 %', 'larga_20261012_1350'),
              ('75 %', 'larga_20261012_1422'), ('0 %', 'larga_20261012_1457')]
    datos = {}
    for nom, b in tramos:
        bl = leer(os.path.join(PL_DIR, b + '_serial.log'))
        rein = []
        fr = os.path.join(PL_DIR, b + '_reinicios.csv')
        if os.path.exists(fr):
            rein = [float(r['t_envio']) for r in csv.DictReader(open(fr)) if r.get('t_envio', '').strip()]
        datos[nom] = (bl, rein)

    fid = {}
    for nom, (bl, rein) in datos.items():
        res = correr(bl, 0j, rein)
        on = [(b, r) for b, r in zip(bl, res) if b['motor'] == 'ON' and b['fw_ref'] == 1]
        fid[nom] = dict(bloques=len(on),
                        p_dif_med=round(statistics.median(abs(b['fw_p'] - r[1]) for b, r in on), 4),
                        c_concuerda=round(sum(b['fw_c'] == r[0] for b, r in on) / len(on), 4))
    rep['fidelidad_port'] = fid

    pares = {nom: list(zip(*deltas(bl))) for nom, (bl, _) in datos.items()}
    y2_todos = ajustar_y2([p for v in pares.values() for p in v])
    rep['y2_todos'] = dict(re=y2_todos.real, im=y2_todos.imag, mod=abs(y2_todos),
                           ang_grados=math.degrees(cmath.phase(y2_todos)),
                           r2=r2_ajuste([p for v in pares.values() for p in v], y2_todos))

    # --- 2. Falsas alarmas: firmware (replay) vs compensado, dejando el tramo evaluado fuera del ajuste ---
    filas = []
    for nom, (bl, rein) in datos.items():
        y2_cv = ajustar_y2([p for k, v in pares.items() if k != nom for p in v])
        expo = sum(b2['t'] - b1['t'] for b1, b2 in zip(bl, bl[1:]) if b1['motor'] == 'ON' and b2['t'] - b1['t'] < 5) / 60
        fila = {'tramo': nom, 'exposicion_min': round(expo, 1),
                'y2_cv': [round(y2_cv.real, 4), round(y2_cv.imag, 4)], 'r2_cv': round(r2_ajuste(pares[nom], y2_cv), 3)}
        for etq, y2 in (('firmware', 0j), ('compensado', y2_cv)):
            # en el replay del firmware se aplican los 'r' reales; en el compensado no hacen falta
            res = correr(bl, y2, rein if etq == 'firmware' else ())
            ev = eventos(bl, res)
            on = [r for b, r in zip(bl, res) if b['motor'] == 'ON']
            fila[etq] = dict(eventos=len(ev), duraciones_s=[round(d, 1) for _, d, _ in ev],
                             sev_max=[['-', 'LEVE', 'INTER', 'SEVERA'][s] for *_, s in ev],
                             bloques_p_sobre_umbral=sum(r[1] >= UMBRAL for r in on), bloques=len(on),
                             p_desv_std=round(statistics.pstdev([r[1] for r in on]), 3))
        filas.append(fila)
    rep['prueba_larga'] = filas
    tot = {etq: sum(f[etq]['eventos'] for f in filas) for etq in ('firmware', 'compensado')}
    expo_h = sum(f['exposicion_min'] for f in filas) / 60
    rep['prueba_larga_total'] = {etq: dict(eventos=k, tasa_h=round(k / expo_h, 2)) for etq, k in tot.items()}

    # --- 3. Validaciones en vivo con falla real (Y2 de los 4 tramos; estos datos no participan) ---
    vivos = []
    for base in sorted(glob.glob(os.path.join(VV_DIR, 'vivo_*_plan.json'))):
        base = base[:-len('_plan.json')]
        bl = leer(base + '_serial.log')
        if len(bl) < 50:
            continue
        r_fw = correr(bl, 0j)
        r_c = correr(bl, y2_todos)
        fila = {'sesion': os.path.basename(base), 'firmware_replay': puntuar_vivo(base, bl, r_fw),
                'compensado': puntuar_vivo(base, bl, r_c)}
        try:
            d = json.load(open(base + '_resumen.json'))
            fila['reportado_en_su_dia'] = {k: d.get(k) for k in ('TP', 'FN', 'FP', 'TN', 'decision')}
        except FileNotFoundError:
            pass
        vivos.append(fila)
    rep['validaciones_vivo'] = vivos

    with open(os.path.join(SALIDA, 'resultado_compensacion_v2.json'), 'w') as fh:
        json.dump(rep, fh, indent=2, ensure_ascii=False, default=str)
    print(json.dumps(rep, indent=1, ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
