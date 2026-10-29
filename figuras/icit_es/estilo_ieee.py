"""Estilo de las figuras del articulo ICIT 2027 adaptado a la tesis: mismo nombre de modulo para que los
scripts copiados no cambien su logica de datos. Ancho de pagina, Liberation Sans Narrow (Arial Narrow), espanol."""
import os
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

ANCHO = 6.0            # in, ancho de texto de la tesis
ESCALA = 1.55          # factor de alto respecto al formato de columna del articulo
DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))   # redaccion/figuras
sys.path.insert(0, os.path.expanduser('~'))
CLASE = {
    'SANO':   dict(marker='.', color='0.65', mfc='0.65', ms=4, label='Sano'),
    'LEVE':   dict(marker='o', color='0.0', mfc='none', ms=4.5, label='LEVE (7.0 % de espiras)'),
    'INTER':  dict(marker='^', color='0.35', mfc='0.35', ms=4.5, label='INTERMEDIA (14.3 %)'),
    'SEVERA': dict(marker='s', color='0.0', mfc='0.0', ms=4.2, label='SEVERA (21.6 %)'),
}
CARGA_EN = {'0%': '0 %', '25%': '25 %', '50%': '50 %', '75%': '75 %'}


def aplicar():
    plt.rcParams.update({
        'font.family': 'Liberation Sans Narrow', 'mathtext.fontset': 'dejavusans',
        'font.size': 10, 'axes.labelsize': 10, 'axes.titlesize': 10, 'xtick.labelsize': 9.5, 'ytick.labelsize': 9.5,
        'legend.fontsize': 9.5, 'axes.linewidth': 0.7, 'lines.linewidth': 1.2, 'grid.linewidth': 0.5,
        'grid.color': '0.85', 'axes.grid': False, 'legend.frameon': False, 'savefig.dpi': 300,
    })


def guardar(fig, nombre):
    fig.savefig(os.path.join(DIR, f'{nombre}.png'), bbox_inches='tight', pad_inches=0.03)
    print('guardada', os.path.join(DIR, nombre + '.png'))
