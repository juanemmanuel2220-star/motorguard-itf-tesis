#!/usr/bin/env python3
"""Esquematicos y diagramas de funcionamiento del banco (cap. 3). Son dibujos de conexionado
y de logica, no datos medidos.
Fuentes: rag/datos/banco_pruebas.md §2-§22 y §31-§32 (cita: resultados_oct_2026.md y cap. 3),
firmware 299a943 (PRUEBA_MODELO_1.ino, detector_dir.h), pins_arduino.h de arduino_nano_nora
(core esp32 3.3.12), alimentacion de la TFT (VCC y LED a 3.3 V) de la Tabla 4 de
`IMAGENES COMPONENTES BANCO DE PRUEBAS/tabla_conexiones_banco_pruebas_ITF.png` y datos confirmados por el autor el 26-oct-2026: ZMPT101B fase-neutro,
ACS712 y entrada del SSR alimentados con 5 V del pin VBUS, sin snubber en el SSR.
Uso:  ~/venv_esquemas/bin/python esquematicos.py [potencia lazo driver acond nano bloque estados inyeccion]
      (schemdraw 0.19 + matplotlib del sistema; venv creado con --system-site-packages)
Genera fig_esq_*.png y fig_func_*.png en redaccion/figuras/."""
import os, sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle, Circle
import schemdraw
import schemdraw.elements as elm

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
AZUL, NARANJA, TINTA, TINTA2, GRIS = '#2a78d6', '#eb6834', '#0b0b0b', '#52514e', '#9a9893'
AZUL_F, NAR_F, GRIS_F = '#eef4fc', '#fdf0ea', '#f4f3ef'
FUENTE = 'Liberation Sans Narrow'
plt.rcParams.update({'font.family': FUENTE, 'font.size': 9, 'mathtext.fontset': 'custom',
                     'mathtext.rm': FUENTE, 'mathtext.it': FUENTE + ':italic', 'mathtext.bf': FUENTE + ':bold'})
schemdraw.config(font=FUENTE, fontsize=9, lw=1.0, color=TINTA, inches_per_unit=0.3)
DPI = 220


# ---------------------------------------------------------------------------
# utilidades para los esquematicos (schemdraw para componentes, matplotlib para texto)
# ---------------------------------------------------------------------------
class Esquema:
    def __init__(self, ipu=0.3):
        # schemdraw 0.19 dibuja en una figura de tamano fijo; la escala (pulgadas por unidad)
        # se impone en guardar() para que el texto conserve su tamano en puntos.
        self.ipu = ipu
        self.d = schemdraw.Drawing(show=False)
        self.textos, self.circulos, self.rects = [], [], []

    def add(self, e):
        self.d += e
        return e

    def linea(self, a, b, **kw):
        e = elm.Line().at(a).to(b)
        if 'color' in kw: e.color(kw['color'])
        if 'lw' in kw: e.linewidth(kw['lw'])
        if 'ls' in kw: e.linestyle(kw['ls'])
        return self.add(e)

    def poli(self, pts, **kw):
        for a, b in zip(pts[:-1], pts[1:]):
            self.linea(a, b, **kw)

    def punto(self, xy):
        self.add(elm.Dot(radius=0.07).at(xy))

    def borne(self, xy):
        self.add(elm.Dot(open=True, radius=0.1).at(xy))

    def t(self, x, y, s, ha='center', va='center', fs=9, color=TINTA, **kw):
        self.textos.append((x, y, s, ha, va, fs, color, kw))

    def caja(self, x, y, w, h, s='', color=AZUL, fill=None, fs=9, ls='-'):
        self.rects.append((x, y, w, h, color, fill, ls))
        if s:
            self.t(x + w / 2, y + h / 2, s, fs=fs)

    def circulo(self, xy, r, color=NARANJA):
        self.circulos.append((xy, r, color))

    def guardar(self, nombre):
        fig = self.d.draw(show=False)
        ax = fig.ax
        for (x, y, w, h, c, f, ls) in self.rects:
            ax.add_patch(Rectangle((x, y), w, h, fill=f is not None, fc=f or 'none', ec=c, lw=1.1, ls=ls, zorder=0.5))
        for (xy, r, c) in self.circulos:
            ax.add_patch(Circle(xy, r, fill=False, lw=1.3, ec=c))
        for (x, y, s, ha, va, fs, c, kw) in self.textos:
            ax.text(x, y, s, ha=ha, va=va, fontsize=fs, color=c, family=FUENTE, linespacing=1.2, zorder=5, **kw)
        bb, m = self.d.get_bbox(), 0.6
        ax.set_xlim(bb.xmin - m, bb.xmax + m); ax.set_ylim(bb.ymin - m, bb.ymax + m)
        ax.set_aspect('equal'); ax.set_position([0, 0, 1, 1])
        fig.fig.set_size_inches((bb.xmax - bb.xmin + 2 * m) * self.ipu, (bb.ymax - bb.ymin + 2 * m) * self.ipu)
        fig.fig.savefig(os.path.join(OUT, nombre), dpi=DPI, bbox_inches='tight', pad_inches=0.08)
        plt.close(fig.fig)
        print(nombre)


# ---------------------------------------------------------------------------
# Figura: circuito de potencia y puntos de medicion
# ---------------------------------------------------------------------------
def fig_potencia():
    E = Esquema()
    yL = {'L1': 8.4, 'L2': 7.2, 'L3': 6.0}
    yN = 2.6
    fases = [('L1', 'A'), ('L2', 'B'), ('L3', 'C')]
    for nom, y in list(yL.items()) + [('N', yN)]:
        E.borne((0, y))
        E.t(-0.25, y, nom, ha='right')
        E.linea((0.1, y), (0.9, y))
    E.t(0, 9.4, 'Red trifásica, 60 Hz\n≈123 V por fase', ha='left', va='bottom')
    E.caja(0.9, 2.0, 1.9, 7.0, 'Variac\ntrifásico\n3.5 kVA', NARANJA)
    E.t(4.4, 8.95, '3 × ACS712-30A\nen serie', va='bottom', color=AZUL, fs=8.5)
    for (nom, f) in fases:
        y = yL[nom]
        E.linea((2.8, y), (3.6, y))
        E.caja(3.6, y - 0.36, 1.6, 0.72, f'I{f}', AZUL, fs=9.5)
    for i, (nom, f) in enumerate(fases):
        x = 6.4 + i * 1.25
        y = yL[nom]
        E.linea((5.2, y), (x, y))
        E.punto((x, y))
        E.linea((x, y), (11.3, y))
        E.linea((x, y), (x, 4.2))
        E.caja(x - 0.45, 3.4, 0.9, 0.8, f'V{f}', AZUL, fs=9.5)
        E.linea((x, 3.4), (x, yN))
        E.punto((x, yN))
    E.t(5.75, 3.8, '3 × ZMPT101B\nfase–neutro', ha='right', color=AZUL, fs=8.5)
    E.linea((2.8, yN), (8.9, yN))
    E.t(9.2, yN, 'neutro: solo referencia de los ZMPT101B', ha='left', va='center', color=TINTA2, fs=8.5)
    cx, cy, r = 12.6, 7.2, 1.35
    for nom in ('L1', 'L2', 'L3'):
        y = yL[nom]
        xe = cx - (r ** 2 - (y - cy) ** 2) ** 0.5
        E.linea((11.3, y), (xe, y))
    E.circulo((cx, cy), r)
    E.t(cx, cy, 'M\n3~', fs=12)
    E.t(cx, cy - r - 0.15, 'Motor ABB M1AA 145T-D4\n1.5 kW · 220 V · 220-YY\n(sin neutro)', va='top', fs=8.5)
    E.t(cx, 4.05, 'derivaciones 1–4 de la fase C\n→ lazo de inyección', va='top', color=NARANJA, fs=8.5)
    gx = 16.6
    for dy in (0.1, -0.1):
        E.linea((cx + r, cy + dy), (gx - r, cy + dy), lw=1.8)
    E.t((cx + gx) / 2, cy + 0.3, 'eje', va='bottom', color=TINTA2, fs=8.5)
    E.circulo((gx, cy), r)
    E.t(gx, cy, 'G\n=', fs=12)
    E.t(gx, cy - r - 0.15, 'Generador de CD\nBaldor CDP3585\n2 HP · 180 V · 9.6 A\nimán permanente\n(tipo PM3548P)', va='top', fs=8.5)
    xa = gx + (r ** 2 - 0.9 ** 2) ** 0.5
    xr = 19.4
    E.linea((xa, cy + 0.9), (xr, cy + 0.9))
    E.linea((xa, cy - 0.9), (xr, cy - 0.9))
    E.add(elm.ResistorIEC().at((xr, cy + 0.9)).to((xr, cy - 0.9)))
    E.t(xr + 0.45, cy, '$R_L$', ha='left', fs=10)
    E.t(15.0, cy + 1.75, '$R_L$ según la carga: 0 %, abierta (vacío);\n25 %, 75 Ω; 50 %, 33 Ω; 75 %, 2 × 50 Ω en paralelo', ha='left', va='bottom', fs=8.5)
    E.guardar('fig_esq_potencia.png')


# ---------------------------------------------------------------------------
# Figura: derivaciones de la fase C y lazo de inyeccion
# ---------------------------------------------------------------------------
def fig_lazo():
    E = Esquema()
    xw = 3.0
    ytap = {1: 10.0, 2: 8.3, 3: 6.6, 4: 4.9}
    E.linea((xw, 11.6), (xw, ytap[1]), ls='--', color=TINTA2)
    E.linea((xw, ytap[4]), (xw, 3.3), ls='--', color=TINTA2)
    E.t(xw, 11.75, 'resto del devanado\nde la fase C', va='bottom', color=TINTA2, fs=8.5)
    E.t(xw, 3.15, 'resto del devanado\nde la fase C', va='top', color=TINTA2, fs=8.5)
    for a, b in ((1, 2), (2, 3), (3, 4)):
        E.add(elm.Inductor2(loops=3).at((xw, ytap[a])).to((xw, ytap[b])))
        E.t(xw + 0.55, (ytap[a] + ytap[b]) / 2, '7.0 %', ha='left', color=TINTA2, fs=8.5)
    xb = 5.6
    for k, y in ytap.items():
        E.punto((xw, y))
        E.linea((xw, y), (xb, y))
        E.borne((xb + 0.1, y))
        E.t(xb + 0.35, y + 0.05, str(k), ha='left', fs=10)
    E.t(xb + 0.1, 11.0, 'caja de\nbornes', va='bottom', fs=8.5)

    def corchete(x, y1, y2, txt, color):
        E.poli([(x + 0.25, y1), (x, y1), (x, y2), (x + 0.25, y2)], color=color, lw=1.4)
        E.t(x - 0.15, (y1 + y2) / 2, txt, ha='right', color=color, fs=8.5)
    corchete(2.0, ytap[1], ytap[2], 'LEVE\n1–2', AZUL)
    corchete(0.6, ytap[2], ytap[4], 'INTER\n2–4', NARANJA)
    corchete(-0.8, ytap[1], ytap[4], 'SEVERA\n1–4', TINTA)
    # lazo
    ya, yb = 9.4, 5.5
    xa = 8.6
    E.borne((xa, ya)); E.borne((xa, yb))
    E.t(xa - 0.25, ya, 'a', ha='right', fs=10); E.t(xa - 0.25, yb, 'b', ha='right', fs=10)
    E.add(elm.Fuse().at((xa + 0.1, ya)).to((11.2, ya)))
    E.t(9.9, ya + 0.45, 'fusible\n5 A o 10 A rápido', va='bottom', fs=8.5)
    E.add(elm.ResistorIEC().at((11.2, ya)).to((14.0, ya)))
    E.t(12.6, ya + 0.45, 'resistencia limitadora\n5 Ω, ≈150 W', va='bottom', fs=8.5)
    E.poli([(14.0, ya), (15.2, ya), (15.2, 8.3)])
    E.caja(14.2, 6.6, 2.0, 1.7, 'SSR-25DA\nlado de carga\n(1–2)', NARANJA, fs=8.5)
    E.poli([(15.2, 6.6), (15.2, yb), (xa + 0.1, yb)])
    E.linea((16.2, 7.45), (17.4, 7.45), ls='--', color=AZUL)
    E.t(17.5, 7.45, 'control: GPIO 8\n(driver 2N2222)', ha='left', color=AZUL, fs=8.5)
    E.t(12.0, 4.95, 'La clase se elige uniendo a y b con las derivaciones de la tabla\n(cambio manual, con el motor apagado y la alimentación cortada).', va='top', color=TINTA2, fs=8.5)
    cols = [8.4, 10.6, 12.3, 14.3, 17.0]
    filas = [('Clase', 'a – b', 'Espiras', 'Lazo (pinza)', 'Fusible'),
             ('LEVE', '1 – 2', '7.0 %', '1.7 A', '5 A'),
             ('INTER', '2 – 4', '14.3 %', '3.3–3.7 A', '5 A'),
             ('SEVERA', '1 – 4', '21.6 %', '4.8–5.2 A', '10 A rápido')]
    y0 = 3.5
    for i, fila in enumerate(filas):
        for x, s in zip(cols, fila):
            E.t(x, y0 - i * 0.62, s, ha='left', fs=8.5, weight='bold' if i == 0 else 'normal')
    E.linea((8.3, y0 - 0.31), (18.6, y0 - 0.31), lw=0.6, color=TINTA2)
    E.guardar('fig_esq_lazo.png')


# ---------------------------------------------------------------------------
# Figura: driver del SSR
# ---------------------------------------------------------------------------
def fig_driver():
    E = Esquema()
    E.borne((0, 3.0))
    E.t(-0.25, 3.0, 'D5\n(GPIO 8)', ha='right', fs=9)
    E.add(elm.ResistorIEC().at((0.1, 3.0)).to((3.0, 3.0)))
    E.t(1.55, 3.45, '$R_B$ = 1 kΩ', va='bottom', fs=9)
    q = E.add(elm.BjtNpn(circle=True).anchor('base').at((3.0, 3.0)))
    E.t(q.center[0] + 0.85, q.center[1], '2N2222', ha='left', fs=9)
    E.add(elm.Ground().at(q.emitter))
    E.t(q.emitter[0] + 0.7, q.emitter[1] - 0.45, 'GND común', ha='left', fs=8.5, color=TINTA2)
    xc = q.collector[0]
    sx, sy, sw, sh = xc - 0.7, 4.9, 4.8, 1.9
    E.caja(sx, sy, sw, sh, color=NARANJA)
    E.t(sx + sw / 2, sy + sh / 2 + 0.3, 'Fotek SSR-25DA', fs=9.5, weight='bold')
    E.t(sx + sw / 2, sy + sh / 2 - 0.35, 'entrada CD → salida CA', fs=8.5, color=TINTA2)
    p3, p4 = (xc, sy + sh), (xc, sy)
    E.linea(q.collector, p4)
    E.t(xc - 0.15, sy - 0.3, '4 (−)', ha='right', fs=8.5)
    E.t(xc - 0.15, sy + sh + 0.3, '3 (+)', ha='right', fs=8.5)
    E.linea(p3, (xc, sy + sh + 0.9))
    E.borne((xc, sy + sh + 1.0))
    E.t(xc, sy + sh + 1.25, 'VBUS (+5 V)\nArduino Nano ESP32', va='bottom', fs=9)
    x1 = sx + sw
    for y, nom in ((sy + sh * 0.72, '1'), (sy + sh * 0.28, '2')):
        E.linea((x1, y), (x1 + 1.4, y), color=NARANJA)
        E.borne((x1 + 1.5, y))
        E.t(x1 + 0.15, y + 0.22, nom, ha='left', fs=8.5)
    E.t(x1 + 1.8, sy + sh / 2, 'al lazo de inyección\n(fusible, 5 Ω y derivaciones\nde la fase C)', ha='left', fs=8.5, color=NARANJA)
    E.guardar('fig_esq_driver_ssr.png')


# ---------------------------------------------------------------------------
# Figura: acondicionamiento de los sensores
# ---------------------------------------------------------------------------
def fig_acond():
    E = Esquema()
    bx, bw = 1.4, 3.8
    xr = bx + bw
    # (a) corriente
    E.t(0, 9.6, '(a) Canal de corriente (×3)', ha='left', va='bottom', fs=9.5, weight='bold')
    E.borne((0, 7.9)); E.t(-0.2, 7.9, 'Lx (variac)', ha='right', fs=8.5)
    E.linea((0.1, 7.9), (bx, 7.9), color=NARANJA)
    E.caja(bx, 6.0, bw, 2.8, color=AZUL)
    E.t(bx + 1.5, 8.35, 'ACS712-30A', fs=9, weight='bold')
    E.t(bx + 1.5, 7.2, '66 mV/A\nreposo 2.5 V', fs=8.5, color=TINTA2)
    E.t(bx + 0.1, 7.9, 'IP+', ha='left', fs=7.5); E.t(bx + 0.1, 6.4, 'IP−', ha='left', fs=7.5)
    E.poli([(bx, 6.4), (0.8, 6.4), (0.8, 5.2)], color=NARANJA)
    E.borne((0.8, 5.1)); E.t(0.8, 4.85, 'al motor', va='top', fs=8.5)
    E.t(xr - 0.1, 8.4, 'VCC', ha='right', fs=7.5)
    E.t(xr - 0.1, 7.3, 'OUT', ha='right', fs=7.5)
    E.t(xr - 0.1, 6.35, 'GND', ha='right', fs=7.5)
    E.poli([(xr, 8.4), (xr + 0.6, 8.4), (xr + 0.6, 9.2)]); E.borne((xr + 0.6, 9.3)); E.t(xr + 0.85, 9.3, 'VBUS (+5 V)', ha='left', fs=8.5)
    E.linea((xr, 6.35), (xr + 0.5, 6.35)); E.add(elm.Ground().at((xr + 0.5, 6.35)))
    E.linea((xr, 7.3), (xr + 1.4, 7.3))
    E.add(elm.ResistorIEC().at((xr + 1.4, 7.3)).to((xr + 4.0, 7.3)))
    E.t(xr + 2.7, 7.75, '$R_1$ = 10 kΩ', va='bottom', fs=8.5)
    xn = xr + 4.0
    E.punto((xn, 7.3))
    E.add(elm.ResistorIEC().at((xn, 7.3)).to((xn, 4.8)))
    E.t(xn + 0.45, 6.05, '$R_2$ = 20 kΩ', ha='left', fs=8.5)
    E.add(elm.Ground().at((xn, 4.8)))
    E.linea((xn, 7.3), (xn + 1.8, 7.3)); E.borne((xn + 1.9, 7.3))
    E.t(xn + 2.15, 7.3, 'ADC: A1 (IA)\nA0 (IB), A2 (IC)', ha='left', fs=8.5)
    E.t(0, 3.9, '$V_{ADC} = \\frac{R_2}{R_1+R_2}\\,V_{OUT} = \\frac{2}{3}\\,V_{OUT}$:  reposo 2.5 V → 1.67 V;  66 mV/A → 44 mV/A',
        ha='left', va='top', fs=9)
    # (b) voltaje
    E.t(0, 2.3, '(b) Canal de voltaje (×3)', ha='left', va='bottom', fs=9.5, weight='bold')
    E.borne((0, 1.2)); E.t(-0.2, 1.2, 'Lx', ha='right', fs=8.5)
    E.borne((0, -0.6)); E.t(-0.2, -0.6, 'N', ha='right', fs=8.5)
    E.linea((0.1, 1.2), (bx, 1.2), color=NARANJA)
    E.linea((0.1, -0.6), (bx, -0.6), color=NARANJA)
    E.caja(bx, -1.1, bw, 2.8, color=AZUL)
    E.t(bx + 1.5, 1.25, 'ZMPT101B', fs=9, weight='bold')
    E.t(bx + 1.5, 0.0, 'transformador\n+ amplificador;\nganancia por\npotenciómetro', fs=8, color=TINTA2)
    E.t(xr - 0.1, 1.3, 'VCC', ha='right', fs=7.5)
    E.t(xr - 0.1, 0.3, 'OUT', ha='right', fs=7.5)
    E.t(xr - 0.1, -0.75, 'GND', ha='right', fs=7.5)
    E.poli([(xr, 1.3), (xr + 0.6, 1.3), (xr + 0.6, 2.0)]); E.borne((xr + 0.6, 2.1)); E.t(xr + 0.85, 2.1, '+3V3', ha='left', fs=8.5)
    E.linea((xr, -0.75), (xr + 0.5, -0.75)); E.add(elm.Ground().at((xr + 0.5, -0.75)))
    E.linea((xr, 0.3), (xn + 1.8, 0.3)); E.borne((xn + 1.9, 0.3))
    E.t(xn + 2.15, 0.3, 'ADC: A4 (VA)\nA3 (VB), A5 (VC)', ha='left', fs=8.5)
    E.t((xr + xn) / 2 + 0.6, 0.55, 'directo, sin divisor', va='bottom', fs=8.5, color=TINTA2)
    # tabla de canales
    xt = 16.4
    filas = [('Canal', 'Pin', 'GPIO', 'ADC'), ('VA', 'A4', '11', 'ADC2'), ('VB', 'A3', '4', 'ADC1'),
             ('VC', 'A5', '12', 'ADC2'), ('IA', 'A1', '2', 'ADC1'), ('IB', 'A0', '1', 'ADC1'), ('IC', 'A2', '3', 'ADC1')]
    for i, f in enumerate(filas):
        for j, c in enumerate(f):
            E.t(xt + j * 1.25, 8.9 - i * 0.62, c, ha='left', fs=8.5, weight='bold' if i == 0 else 'normal')
    E.linea((xt - 0.1, 8.9 - 0.31), (xt + 4.9, 8.9 - 0.31), lw=0.6, color=TINTA2)
    E.t(xt - 0.1, 4.3, 'ADC de 12 bits, atenuación de 11 dB.\nVA y VC están en el ADC2, que no\nfunciona con el radio encendido:\nel Wi-Fi está deshabilitado.', ha='left', va='top', fs=8.5, color=TINTA2)
    E.guardar('fig_esq_acondicionamiento.png')


# ---------------------------------------------------------------------------
# utilidades para los diagramas (matplotlib puro)
# ---------------------------------------------------------------------------
def lienzo(w, h, xmax, ymax):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, xmax); ax.set_ylim(0, ymax); ax.axis('off')
    return fig, ax


def bloque(ax, x, y, w, h, txt, fill=AZUL_F, edge=AZUL, fs=8.8, ls='-', bold_first=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.25,rounding_size=0.6', fc=fill, ec=edge, lw=1.1, ls=ls))
    if bold_first and '\n' in txt:
        cab, resto = txt.split('\n', 1)
        lineas = [cab] + resto.split('\n')
        ax.text(x + w / 2, y + h / 2, '\n'.join(lineas), ha='center', va='center', fontsize=fs, color=TINTA, linespacing=1.2, alpha=0)
        tt = ax.text(x + w / 2, y + h / 2, cab + '\n' + ' ' * 0, ha='center', va='center', fontsize=fs, alpha=0)
        # cabecera en negrita arriba y cuerpo debajo, centrados como bloque
        n = len(lineas)
        paso = fs * 1.2 / 72 * 1.0
        fig = ax.figure
        # alto de una linea en unidades de datos
        inv = ax.transData.inverted()
        y0 = inv.transform((0, 0))[1]
        y1 = inv.transform((0, fs * 1.25 / 72 * fig.dpi))[1]
        lh = y1 - y0
        ytop = y + h / 2 + (n - 1) * lh / 2
        ax.text(x + w / 2, ytop, cab, ha='center', va='center', fontsize=fs, weight='bold', color=TINTA)
        for i, l in enumerate(lineas[1:], start=1):
            ax.text(x + w / 2, ytop - i * lh, l, ha='center', va='center', fontsize=fs - 0.3, color=TINTA)
    else:
        ax.text(x + w / 2, y + h / 2, txt, ha='center', va='center', fontsize=fs, color=TINTA, linespacing=1.2)


def flecha(ax, a, b, txt=None, color=TINTA2, ls='-', off=(0, 0.3), ha='center', fs=8, rad=0.0):
    ax.annotate('', xy=b, xytext=a, arrowprops=dict(arrowstyle='-|>', color=color, lw=1.1, ls=ls,
                                                    shrinkA=0, shrinkB=0, connectionstyle=f'arc3,rad={rad}'))
    if txt:
        ax.text((a[0] + b[0]) / 2 + off[0], (a[1] + b[1]) / 2 + off[1], txt, ha=ha, va='center', fontsize=fs, color=color, linespacing=1.15)


def guardar_fig(fig, nombre):
    fig.savefig(os.path.join(OUT, nombre), dpi=DPI, bbox_inches='tight', pad_inches=0.06)
    plt.close(fig)
    print(nombre)


# ---------------------------------------------------------------------------
# Figura: conexiones del Arduino Nano ESP32
# ---------------------------------------------------------------------------
def fig_nano():
    fig, ax = lienzo(6.3, 4.6, 100, 74)
    bx, by, bw, bh = 38, 8, 24, 60
    ax.add_patch(Rectangle((bx, by), bw, bh, fc='#e8eef7', ec=AZUL, lw=1.4))
    ax.text(bx + bw / 2, by + bh - 4, 'Arduino Nano ESP32', ha='center', fontsize=9.5, weight='bold')
    ax.text(bx + bw / 2, by + bh - 8.5, 'ESP32-S3', ha='center', fontsize=8.5, color=TINTA2)
    ax.text(bx + bw / 2, by + 4, 'USB-C', ha='center', fontsize=8.5, weight='bold')
    izq = [('VBUS', '+5 V (USB)'), ('+3V3', '3.3 V'), ('GND', ''), ('A4', 'GPIO 11 · VA'), ('A3', 'GPIO 4 · VB'),
           ('A5', 'GPIO 12 · VC'), ('A1', 'GPIO 2 · IA'), ('A0', 'GPIO 1 · IB'), ('A2', 'GPIO 3 · IC')]
    der = [('D5', 'GPIO 8 · SSR'), ('D10', 'GPIO 21 · CS'), ('D8', 'GPIO 17 · DC'), ('D9', 'GPIO 18 · RST'),
           ('D11', 'GPIO 38 · MOSI'), ('D12', 'GPIO 47 · MISO'), ('D13', 'GPIO 48 · SCK')]
    yi = {}
    for i, (p, s) in enumerate(izq):
        y = by + bh - 15 - i * 5.0
        yi[p] = y
        ax.plot([bx - 3, bx], [y, y], color=TINTA, lw=1)
        ax.text(bx + 1.2, y, p, ha='left', va='center', fontsize=8.5, weight='bold')
        if s: ax.text(bx - 3.6, y, s, ha='right', va='center', fontsize=8, color=TINTA2)
    yd = {}
    for i, (p, s) in enumerate(der):
        y = by + bh - 15 - i * 5.0 - (0 if i == 0 else 4)
        yd[p] = y
        ax.plot([bx + bw, bx + bw + 3], [y, y], color=TINTA, lw=1)
        ax.text(bx + bw - 1.2, y, p, ha='right', va='center', fontsize=8.5, weight='bold')
        ax.text(bx + bw + 3.6, y, s, ha='left', va='center', fontsize=8, color=TINTA2)

    def llave_izq(y1, y2, txt, color, x=17):
        ax.plot([x + 2, x, x, x + 2], [y1 + 1.2, y1 + 1.2, y2 - 1.2, y2 - 1.2], color=color, lw=1.2)
        ax.text(x - 1, (y1 + y2) / 2, txt, ha='right', va='center', fontsize=8.5, color=color, linespacing=1.2)
    llave_izq(yi['A4'], yi['A5'], 'ZMPT101B\n(3.3 V)', AZUL)
    llave_izq(yi['A1'], yi['A2'], 'ACS712-30A\n+ divisor 2/3\n(5 V)', AZUL)
    llave_izq(yi['VBUS'], yi['GND'], 'alimentación de\nsensores, SSR y TFT', TINTA2)

    def llave_der(y1, y2, txt, color, x=83):
        ax.plot([x - 2, x, x, x - 2], [y1 + 1.2, y1 + 1.2, y2 - 1.2, y2 - 1.2], color=color, lw=1.2)
        ax.text(x + 1, (y1 + y2) / 2, txt, ha='left', va='center', fontsize=8.5, color=color, linespacing=1.2)
    ax.plot([bx + bw + 16, 82], [yd['D5'], yd['D5']], color=NARANJA, lw=1.2)
    ax.text(83, yd['D5'], 'driver 2N2222\n→ SSR-25DA', ha='left', va='center', fontsize=8.5, color=NARANJA, linespacing=1.2)
    llave_der(yd['D10'], yd['D13'], 'pantalla TFT\nILI9341 2.8 in\n(SPI; VCC y LED\na 3.3 V)', AZUL)
    ax.annotate('', xy=(bx + bw / 2, 1.5), xytext=(bx + bw / 2, by), arrowprops=dict(arrowstyle='<|-|>', color=TINTA2, lw=1.1))
    ax.text(bx + bw / 2 + 2, 2.5, 'PC: aplicación MotorGuard-ITF\n(USB serie, 115 200 baud; telemetría y comandos)', ha='left', va='center', fontsize=8.2, color=TINTA2)
    guardar_fig(fig, 'fig_esq_nano.png')


# ---------------------------------------------------------------------------
# Figura: procesamiento de un bloque en el firmware
# ---------------------------------------------------------------------------
def fig_bloque():
    fig, ax = lienzo(6.3, 7.4, 100, 120)
    w, x = 70, 13
    pasos = [
        ('Muestreo', 'temporizador de hardware cada 416 µs (2403.846 Hz por canal);\nuna tarea de FreeRTOS lee VA, VB, VC, IA, IB e IC en secuencia'),
        ('Doble búfer', '4096 muestras por canal = 1.70 s;\nuno se llena mientras el otro se procesa'),
        ('Frecuencia fundamental', 'f0 en 58.5–61.5 Hz con ventana de Hann e interpolación de Grandke'),
        ('Fasores', 'DFT de una sola frecuencia en f0 (Hann, amplitud pico);\ncompensación del retardo de cada canal (0–150 µs) y calibración'),
        ('Componentes simétricas', 'rotación para que arg(V1) = 0;  Fortescue: I1, I2, V1, V2'),
        ('Firma de secuencia negativa', 'R2 = I2 − Y2·V2 − I2,0;   z = 100·R2 / |I1|  (pp)'),
        ('Detector direccional y severidad', 'proyección de dz sobre −81.4°, 0.40 pp × 3 bloques, enclavamiento;\nseveridad con los umbrales de 1.626 y 4.471 pp'),
    ]
    y = 114
    gap = 3.6
    cajas = []
    for i, (cab, txt) in enumerate(pasos):
        n = 1 + txt.count('\n') + 1
        h = 2.6 + 3.1 * n
        col = (NAR_F, NARANJA) if i == len(pasos) - 1 else (AZUL_F, AZUL)
        bloque(ax, x, y - h, w, h, cab + '\n' + txt, col[0], col[1], fs=8.4, bold_first=True)
        cajas.append((y - h, y))
        if i:
            flecha(ax, (x + w / 2, y + gap - 0.3), (x + w / 2, y + 0.3))
        y -= h + gap
    ybot = cajas[-1][0]
    yb = ybot - 15
    outs = [(13, 'Telemetría [MCSA], RAW y DIR\npor USB serie, cada 1.70 s'), (53, 'Pantalla TFT\n(estado, corrientes, alarma)')]
    for xo, t in outs:
        bloque(ax, xo, yb, 30, 8, t, GRIS_F, TINTA2, fs=8.2)
        flecha(ax, (x + w / 2, ybot - 0.3), (xo + 15, yb + 8.3))
    yf = (cajas[5][0] + cajas[5][1]) / 2
    bloque(ax, 86.5, yf - 8, 13, 16, 'Heredados,\nno deciden:\nCUSUM y\nRandom\nForest', '#ffffff', GRIS, fs=7.8, ls='--')
    flecha(ax, (x + w + 0.3, yf), (86.2, yf), color=GRIS, ls='--')
    ax.text(x, 118, 'Procesamiento de cada bloque (cada 1.70 s)', fontsize=9, color=TINTA2, ha='left')
    guardar_fig(fig, 'fig_func_bloque.png')


# ---------------------------------------------------------------------------
# Figura: estados del motor y del detector
# ---------------------------------------------------------------------------
def fig_estados():
    fig, ax = lienzo(6.4, 5.6, 100, 88)
    B = {
        'OFF': (2, 64, 22, 13, 'OFF\nmotor apagado;\nno se decide'),
        'WARM': (38, 64, 22, 13, 'WARMUP\n60 s sin decidir'),
        'VIG': (70, 54, 29, 28, 'ON: VIGILANCIA\nreferencia: mediana de z\nde 6 a 11 s atrás\n$dz = z - ref$\n$P = \\mathrm{Re}\\{dz\\,e^{\\,j81.4°}\\}$\nracha de bloques con P ≥ 0.40 pp'),
        'ALM': (62, 4, 37, 30, 'ALARMA ENCLAVADA\nse congela la base previa;\nseveridad = mediana de |dz|\nen los 3 bloques de confirmación:\n< 1.626 pp LEVE; < 4.471 pp INTER;\n≥ 4.471 pp SEVERA\n(mientras dura, solo puede subir)'),
        'LIB': (4, 8, 36, 20, 'LIBERACIÓN\nPL contra la base congelada\n< máx(0.20 pp; 0.35 · P de confirmación)\ndurante 3 bloques'),
    }
    for k, (x, y, w, h, t) in B.items():
        col = (NAR_F, NARANJA) if k == 'ALM' else ((GRIS_F, TINTA2) if k in ('OFF', 'WARM') else (AZUL_F, AZUL))
        bloque(ax, x, y, w, h, t, col[0], col[1], fs=8.3, bold_first=True)
    flecha(ax, (24.3, 70.5), (37.7, 70.5), '3 fases con\nI de 60 Hz > 1 A\ny V > 60 V\n(3 bloques)', off=(0, 9.0), fs=7.5)
    flecha(ax, (60.3, 70.5), (69.7, 70.5), '60 s', off=(0, 2.0), fs=7.8)
    flecha(ax, (90, 53.7), (90, 34.3), 'racha = 3\nbloques (~5 s):\nconfirma', off=(1.5, 0), ha='left', fs=7.8)
    flecha(ax, (61.7, 18), (40.3, 18), 'la firma cae\ncontra la base', off=(0, 4.0), fs=7.8)
    flecha(ax, (22, 28.3), (69.7, 58), color=TINTA2, rad=-0.18)
    ax.text(44.5, 40, 'se reinicia\nla racha', ha='center', va='center', fontsize=7.8, color=TINTA2)
    flecha(ax, (70, 34.3), (76, 53.7), color=AZUL, ls='--')
    ax.text(70.5, 44, "'r' («Liberar alarma»):\nreinicia el detector", ha='right', va='center', fontsize=7.8, color=AZUL)
    ax.text(2, 61.5, 'a OFF desde cualquier estado si menos de 2 fases\ntienen I de 60 Hz > 0.5 A durante 3 bloques', ha='left', va='top', fontsize=7.8, color=TINTA2)
    guardar_fig(fig, 'fig_func_estados.png')


def fig_inyeccion():
    fig, ax = lienzo(6.4, 7.6, 100, 120)
    for x, t in [(1, 'Aplicación MotorGuard-ITF'), (35, 'Firmware 299a943'), (69, 'Banco')]:
        ax.add_patch(Rectangle((x, 1), 30, 118, fc='#fafaf8', ec='#d8d6d0', lw=0.8))
        ax.text(x + 15, 116, t, ha='center', va='center', fontsize=9, weight='bold')
    H = lambda n: 2.6 + 2.5 * n
    def caja(carril, y, t, **k):
        n = t.count('\n') + 1
        x = {0: 2.5, 1: 36.5, 2: 70.5}[carril]
        bloque(ax, x, y, 27, H(n), t, fs=7.8, bold_first=True, **k)
        return (x, y, 27, H(n))
    c1 = caja(0, 99, 'Bloqueos de la app\nmotor ON y fuera de WARMUP;\npulso ≤ 11 s; enfriamiento ≥ 15 s\n(≥ 20 s SEVERA); máx. por serie')
    c2 = caja(0, 85, 'Confirmación humana\ncasillas: derivaciones conectadas\ny nadie toca el lazo')
    f1 = caja(1, 74, "Recibe '1'\nrechaza si: motor apagado,\notro SSR activo, < 2 s desde\nel último apagado o I > 8 A")
    f2 = caja(1, 62, 'GPIO 8 en alto\n2N2222 → entrada del SSR')
    b1 = caja(2, 62, 'SSR cierra el lazo\ncorriente por 5 Ω y las espiras', fill=NAR_F, edge=NARANJA)
    b2 = caja(2, 47, 'Falla emulada\nfirma de secuencia negativa\nen las corrientes del motor')
    f3 = caja(1, 44.5, 'Vigila durante el pulso\napaga si T_ON llega a 12 s o si\nIC > 8 A en 3 lecturas (cada\n100 ms, tras 600 ms de cegado)')
    f4 = caja(1, 32, 'Detector\nalarma en ~5 s con su severidad')
    a3 = caja(0, 32, 'Muestra la alarma\ny registra la latencia')
    a4 = caja(0, 16.5, "Envía '0'\nal terminar el pulso, con PARO,\nal cerrar o al perder la conexión")
    f5 = caja(1, 17.75, "Recibe '0'\nGPIO 8 en bajo")
    b3 = caja(2, 16.5, 'SSR abre el lazo\nla alarma se libera\nen 5.1–6.1 s')
    a5 = caja(0, 3.5, 'Registro del pulso\nsesion_*_pulsos.csv', fill=GRIS_F, edge=TINTA2)
    top = lambda c: (c[0] + c[2] / 2, c[1] + c[3] + 0.35)
    bot = lambda c: (c[0] + c[2] / 2, c[1] - 0.35)
    der = lambda c, y=None: (c[0] + c[2] + 0.35, y if y is not None else c[1] + c[3] / 2)
    izq = lambda c, y=None: (c[0] - 0.35, y if y is not None else c[1] + c[3] / 2)
    flecha(ax, bot(c1), top(c2))
    flecha(ax, der(c2), izq(f1, 81), "'1'", off=(0, 2.4))
    flecha(ax, bot(f1), top(f2))
    flecha(ax, der(f2), izq(b1))
    flecha(ax, bot(b1), top(b2))
    flecha(ax, bot(f2), top(f3))
    flecha(ax, izq(b2, 49), der(f4, 38))
    ax.text(72, 44, 'corrientes', ha='left', va='center', fontsize=7.8, color=TINTA2)
    flecha(ax, bot(f3), top(f4))
    flecha(ax, izq(f4), der(a3))
    flecha(ax, bot(a3), top(a4))
    yz = f5[1] + f5[3] / 2
    flecha(ax, der(a4, yz), izq(f5), "'0'", off=(0, 2.4))
    flecha(ax, der(f5), izq(b3, yz))
    flecha(ax, bot(a4), top(a5))
    guardar_fig(fig, 'fig_func_inyeccion.png')


TODAS = ['potencia', 'lazo', 'driver', 'acond', 'nano', 'bloque', 'estados', 'inyeccion']
if __name__ == '__main__':
    for q in (sys.argv[1:] or TODAS):
        globals()['fig_' + q]()
