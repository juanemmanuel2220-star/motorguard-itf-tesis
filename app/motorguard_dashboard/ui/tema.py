"""
Tema visual de la app (diseño "MotorGuard-ITF — Rediseño de la interfaz", estilo Material 3).

- Tokens de color claro/oscuro (los mismos de la hoja "Tokens y componentes" del diseño).
- Hoja de estilos (QSS) generada a partir de los tokens.
- GestorTema: modo 'sistema' (sigue el tema del escritorio y reacciona si cambia), 'claro' u 'oscuro'
  a petición del usuario; la preferencia se guarda con QSettings.
- Íconos SVG de trazo, coloreados con el token que se pida y redibujados al cambiar el tema.
- Fuentes Figtree y JetBrains Mono (SIL OFL 1.1, en ui/fuentes/ con sus licencias).
"""

import glob
import os
from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QByteArray, QObject, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFontDatabase, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

CLARO: Dict[str, str] = {
    "bg": "#F6F7FB", "rail": "#ECEFF6", "surface": "#FFFFFF", "surface2": "#F0F2F8", "plotBg": "#F8F9FD",
    "on": "#191C21", "muted": "#474B55", "outline": "#767A85", "outlineV": "#DADEE7", "grid": "#E8EBF2",
    "primary": "#2457A6", "onPrimary": "#FFFFFF", "primaryC": "#D8E2FF", "onPrimaryC": "#0B2A5C",
    "error": "#B3261E", "onError": "#FFFFFF", "disabledBg": "#E3E5EB", "disabledFg": "#5E626C",
    "overlay": "rgba(255,255,255,140)",
    "sanoFg": "#17663F", "sanoC": "#D2F1DE", "sanoOn": "#0B3A23",
    "leveFg": "#7A5300", "leveC": "#FFE6AE", "leveOn": "#3D2A00",
    "interFg": "#A3410C", "interC": "#FFDCC9", "interOn": "#3B1500",
    "severaFg": "#B3261E", "severaC": "#FFDAD6", "severaOn": "#410E0B",
    "apagadoC": "#E3E5EB", "apagadoOn": "#2E3138",
    "pa": "#2457A6", "pb": "#B85C00", "pc": "#7A4BB3",
}
OSCURO: Dict[str, str] = {
    "bg": "#101317", "rail": "#171A20", "surface": "#1B1F26", "surface2": "#252A32", "plotBg": "#161A20",
    "on": "#E2E4EA", "muted": "#C1C5CF", "outline": "#8D919B", "outlineV": "#363B44", "grid": "#2A2F38",
    "primary": "#AFC6FF", "onPrimary": "#0B2A5C", "primaryC": "#2A4A86", "onPrimaryC": "#D8E2FF",
    "error": "#FFB4AB", "onError": "#5F0B05", "disabledBg": "#2B2F37", "disabledFg": "#9CA0AA",
    "overlay": "rgba(0,0,0,56)",
    "sanoFg": "#8FD8AE", "sanoC": "#0F3B26", "sanoOn": "#C9F2D9",
    "leveFg": "#F2C35E", "leveC": "#3F2D00", "leveOn": "#FFE6AE",
    "interFg": "#FFB68D", "interC": "#55210A", "interOn": "#FFDCC9",
    "severaFg": "#FFB4AB", "severaC": "#67110D", "severaOn": "#FFDAD6",
    "apagadoC": "#2B2F37", "apagadoOn": "#D7DAE2",
    "pa": "#8FB2FF", "pb": "#FFB06B", "pc": "#CDAAFF",
}

# Severidad del firmware (0..3) -> prefijo de token
SEV_TOKEN = {0: "sano", 1: "leve", 2: "inter", 3: "severa"}

FUENTE = "Figtree"
FUENTE_MONO = "JetBrains Mono"
DIR_FUENTES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fuentes")
RUTA_LOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recursos", "logo.png")

# Íconos de trazo (viewBox 0 0 24 24), los mismos del diseño
ICONOS = {
    "logo": '<path d="M2 12h3l2.5-6 4 12 3-9 2 3H22"/>',
    "monitoreo": '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    "dashboard": '<rect x="3" y="3" width="7" height="9" rx="2"/><rect x="14" y="3" width="7" height="5" rx="2"/>'
                 '<rect x="14" y="12" width="7" height="9" rx="2"/><rect x="3" y="16" width="7" height="5" rx="2"/>',
    "asistente": '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/>'
                 '<path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
    "sistema": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    "claro": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2'
             'M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "oscuro": '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    "paro": '<path d="M8 2h8l6 6v8l-6 6H8l-6-6V8z"/><path d="M9 9h6v6H9z"/>',
    "enviar": '<path d="M12 19V5"/><path d="M5 12l7-7 7 7"/>',
    "detener": '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    "rayo": '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
    "reloj": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "candado": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "onda": '<path d="M2 12c2-6 4-6 6 0s4 6 6 0 4-6 6 0"/>',
    "barras": '<path d="M4 20V14M9 20V8M14 20V4M19 20v-9"/>',
    "documento": '<path d="M6 3h9l4 4v14H6z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
    "check": '<path d="M5 12l5 5L20 7"/>',
    "ajustes": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 '
               '1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1'
               'a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1'
               'a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 '
               '1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    "adquisicion": '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/>'
                   '<path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    "carpeta": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
}


def instalar_traducciones(app) -> bool:
    """Textos propios de Qt (menú del clic derecho, botones de diálogos estándar) en español. Busca qtbase_es en la
    instalación de Qt y en la del sistema; si no está, quedan en inglés."""
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
    tr = QTranslator(app)
    for carpeta in (QLibraryInfo.path(QLibraryInfo.TranslationsPath), "/usr/share/qt6/translations"):
        if tr.load(QLocale(QLocale.Spanish, QLocale.Mexico), "qtbase", "_", carpeta):
            app.installTranslator(tr)
            app._traductor_qt = tr                     # que no lo recoja el recolector de basura
            return True
    return False


def cargar_fuentes():
    for ruta in sorted(glob.glob(os.path.join(DIR_FUENTES, "*.ttf"))):
        QFontDatabase.addApplicationFont(ruta)


def logo_pixmap(tam: int) -> QPixmap:
    """Logotipo de la app (ui/recursos/logo.png) nítido en pantallas de alta densidad."""
    escala = 3
    pm = QPixmap(RUTA_LOGO).scaled(tam * escala, tam * escala, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    pm.setDevicePixelRatio(escala)
    return pm


def icono(nombre: str, color: str, tam: int = 20, grosor: float = 2.0) -> QIcon:
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="{grosor}" stroke-linecap="round" stroke-linejoin="round">{ICONOS[nombre]}</svg>')
    ren = QSvgRenderer(QByteArray(svg.encode()))
    escala = 3
    pm = QPixmap(tam * escala, tam * escala)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    ren.render(p)
    p.end()
    pm.setDevicePixelRatio(escala)
    return QIcon(pm)


def repulir(w):
    """Vuelve a aplicar la hoja de estilos tras cambiar una propiedad dinámica."""
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


_TRAZOS_QSS = {"palomita": "M5 12.5l4.5 4.5L19 7.5", "flecha": "M6 9l6 6 6-6"}


def _svg_qss(nombre: str, color: str) -> str:
    """Ícono de un trazo (palomita de las casillas, flecha de las listas) del color dado, como archivo: QSS solo
    acepta imágenes por ruta."""
    import tempfile
    ruta = os.path.join(tempfile.gettempdir(), f"motorguard-itf-{nombre}-{color.lstrip('#').lower()}.svg")
    if not os.path.exists(ruta):
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="{_TRAZOS_QSS[nombre]}" '
               f'fill="none" stroke="{color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>')
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write(svg)
    return ruta.replace(os.sep, "/")


def qss(t: Dict[str, str]) -> str:
    palomita = _svg_qss("palomita", t["onPrimary"])
    flecha = _svg_qss("flecha", t["muted"])
    sev = ""
    for nombre in ("sano", "leve", "inter", "severa", "apagado"):
        c, on = t[nombre + "C"], t[nombre + "On"]
        sev += (f'QFrame[sev="{nombre}"] {{ background: {c}; border: 1px solid {c}; border-radius: 28px; }}\n'
                f'QFrame[sev="{nombre}"] QLabel {{ color: {on}; }}\n'
                f'QLabel[chipSev="{nombre}"] {{ background: {c}; color: {on}; border-radius: 9px; '
                f'padding: 3px 10px; font-weight: 700; }}\n')
    for nombre in ("sano", "leve", "inter", "severa"):
        # Píldora "ENCLAVADA" de la tarjeta de estado: un chip con estado propio (dos atributos ganan a
        # QFrame[sev] QLabel, que daría el color de la tarjeta)
        sev += (f'QLabel[rol="chip"][estado="enclave_{nombre}"] {{ background: {t[nombre + "Fg"]}; color: {t[nombre + "C"]}; '
                f'border-color: {t[nombre + "Fg"]}; font-size: 12px; font-weight: 800; }}\n')
    return f"""
* {{ font-family: "{FUENTE}"; font-size: 14px; }}
QMainWindow, QWidget#raiz, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {t['bg']}; color: {t['on']}; }}
QWidget {{ color: {t['on']}; }}
QToolTip {{ background: {t['surface2']}; color: {t['on']}; border: 1px solid {t['outlineV']}; padding: 6px; }}

QFrame#riel {{ background: {t['rail']}; }}
QLabel#logo {{ background: transparent; }}
QPushButton[variante="navPill"] {{ background: transparent; border-radius: 16px; min-height: 32px; max-height: 32px;
    min-width: 56px; max-width: 56px; padding: 0; }}
QPushButton[variante="navPill"]:checked {{ background: {t['primaryC']}; }}
QPushButton[variante="navPill"]:hover:!checked {{ background: {t['surface2']}; }}
QLabel[rol="navEtiqueta"] {{ color: {t['muted']}; font-size: 12px; font-weight: 600; }}
QLabel[rol="navEtiqueta"][activo="true"] {{ color: {t['on']}; font-weight: 700; }}
QLabel[rol="sobreChip"] {{ background: {t['overlay']}; border: 1px solid transparent; border-radius: 10px; padding: 4px 10px; font-size: 12px; font-weight: 600; }}
QLabel[rol="cifraGrande"] {{ font-size: 60px; font-weight: 800; }}
QLabel[rol="encabezado"] {{ font-size: 13px; font-weight: 700; }}

QLabel[rol="titulo"] {{ font-size: 28px; font-weight: 700; }}
QLabel[rol="subtitulo"], QLabel[rol="secundario"] {{ color: {t['muted']}; font-size: 13px; }}
QLabel[rol="tituloTarjeta"] {{ font-size: 17px; font-weight: 700; }}
QLabel[rol="tituloGrupo"] {{ font-size: 15px; font-weight: 700; }}
QLabel[rol="etiqueta"] {{ color: {t['muted']}; font-size: 12px; font-weight: 600; }}
QLabel[rol="cifra"] {{ font-family: "{FUENTE_MONO}"; font-size: 20px; font-weight: 600; }}
QLabel[rol="cifraChica"] {{ font-family: "{FUENTE_MONO}"; font-size: 13px; color: {t['muted']}; }}
QLabel[rol="mono"] {{ font-family: "{FUENTE_MONO}"; font-size: 13px; font-weight: 600; }}
QLabel[rol="aviso"] {{ color: {t['leveFg']}; font-weight: 600; font-size: 13px; }}
QLabel[rol="vacio"] {{ color: {t['muted']}; border: 2px dashed {t['outlineV']}; border-radius: 14px; padding: 16px; }}

QFrame[rol="tarjeta"] {{ background: {t['surface']}; border-radius: 24px; }}
QFrame[rol="contenedor"] {{ background: {t['surface2']}; border-radius: 16px; }}
QFrame[rol="nota"] {{ background: {t['primaryC']}; border-radius: 20px; }}
QFrame[rol="nota"] QLabel {{ color: {t['onPrimaryC']}; }}
QFrame[rol="separador"] {{ background: {t['outlineV']}; max-height: 1px; min-height: 1px; border: none; }}
QFrame[rol="sobre"] {{ background: {t['overlay']}; border-radius: 14px; }}
{sev}
QLabel[rol="chip"] {{ background: {t['surface']}; border: 1px solid {t['outlineV']}; border-radius: 18px;
    padding: 0 14px; min-height: 34px; font-size: 13px; font-weight: 600; }}
QLabel[rol="chip"][estado="bien"] {{ background: {t['sanoC']}; color: {t['sanoOn']}; border-color: {t['sanoC']}; font-weight: 700; }}
QLabel[rol="chip"][estado="mal"] {{ background: {t['severaC']}; color: {t['severaOn']}; border-color: {t['severaC']}; font-weight: 700; }}
QLabel[rol="chip"][estado="aviso"] {{ background: {t['leveC']}; color: {t['leveOn']}; border-color: {t['leveC']}; font-weight: 700; }}
QLabel[rol="chip"][estado="neutro"] {{ background: {t['apagadoC']}; color: {t['apagadoOn']}; border-color: {t['apagadoC']}; }}
QLabel[rol="chip"][estado="tenue"] {{ color: {t['muted']}; font-weight: 500; }}
QLabel[rol="etiquetaMsg"] {{ border-radius: 6px; padding: 1px 8px; font-size: 11px; font-weight: 700;
    background: {t['surface2']}; color: {t['muted']}; }}
QLabel[rol="etiquetaMsg"][tipo="SSR"] {{ background: {t['primaryC']}; color: {t['onPrimaryC']}; }}
QLabel[rol="etiquetaMsg"][tipo="IA"] {{ background: {t['interC']}; color: {t['interOn']}; }}

QPushButton {{ border-radius: 22px; min-height: 44px; padding: 0 22px; font-weight: 700; border: none;
    background: {t['primary']}; color: {t['onPrimary']}; }}
QPushButton:disabled {{ background: {t['disabledBg']}; color: {t['disabledFg']}; }}
QPushButton[variante="tonal"] {{ background: {t['primaryC']}; color: {t['onPrimaryC']}; min-height: 40px; border-radius: 20px; padding: 0 16px; }}
QPushButton[variante="tonal"]:disabled {{ background: {t['disabledBg']}; color: {t['disabledFg']}; }}
QPushButton[variante="contorno"] {{ background: transparent; color: {t['primary']}; border: 1px solid {t['outline']};
    min-height: 40px; border-radius: 20px; padding: 0 16px; }}
QPushButton[variante="contorno"]:disabled {{ color: {t['disabledFg']}; border-color: {t['outlineV']}; }}
QPushButton[variante="paro"] {{ background: {t['error']}; color: {t['onError']}; font-weight: 800; font-size: 15px; }}
QPushButton[variante="filtro"] {{ background: transparent; color: {t['on']}; border: 1px solid {t['outline']};
    min-height: 36px; border-radius: 10px; padding: 0 16px; font-weight: 600; }}
QPushButton[variante="filtro"]:checked {{ background: {t['primaryC']}; color: {t['onPrimaryC']}; border-color: {t['primaryC']}; font-weight: 700; }}
QPushButton[variante="zoom"] {{ background: transparent; color: {t['on']}; border: 1px solid {t['outline']};
    min-height: 30px; border-radius: 10px; padding: 0 10px; font-weight: 700; font-size: 16px; }}
QPushButton[variante="zoom"]:hover {{ border-color: {t['primary']}; }}
QPushButton[variante="seg"] {{ background: transparent; color: {t['on']}; border: 1px solid {t['outline']};
    border-radius: 0; min-height: 38px; padding: 0 14px; font-size: 13px; font-weight: 600; }}
QPushButton[variante="seg"][pos="ini"] {{ border-top-left-radius: 20px; border-bottom-left-radius: 20px; }}
QPushButton[variante="seg"][pos="fin"] {{ border-top-right-radius: 20px; border-bottom-right-radius: 20px; }}
QPushButton[variante="seg"][pos="medio"], QPushButton[variante="seg"][pos="fin"] {{ border-left: none; }}
QPushButton[variante="seg"]:checked {{ background: {t['primaryC']}; color: {t['onPrimaryC']}; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {{ background: transparent; color: {t['on']};
    border: 1px solid {t['outline']}; border-radius: 12px; padding: 8px 12px; selection-background-color: {t['primaryC']}; }}
QSpinBox, QDoubleSpinBox {{ font-family: "{FUENTE_MONO}"; font-size: 16px; min-height: 26px; }}
QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{ border: 2px solid {t['primary']}; }}
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}
QPlainTextEdit[rol="log"] {{ font-family: "{FUENTE_MONO}"; font-size: 12px; border: none; padding: 0; }}
QCheckBox {{ spacing: 10px; min-height: 30px; }}
/* Casilla dibujada explícitamente: sin esto, con la hoja de estilos Qt la pintaba como un cuadro negro relleno,
   igual marcada que sin marcar (lo reportó el autor en el diálogo de confirmación de inyección, 13-oct) */
QCheckBox::indicator {{ width: 18px; height: 18px; border: 2px solid {t['outline']}; border-radius: 5px;
    background: {t['surface']}; }}
QCheckBox::indicator:hover {{ border-color: {t['primary']}; }}
QCheckBox::indicator:checked {{ background: {t['primary']}; border-color: {t['primary']}; image: url("{palomita}"); }}
QCheckBox::indicator:disabled {{ border-color: {t['outlineV']}; background: {t['disabledBg']}; }}
QCheckBox::indicator:checked:disabled {{ background: {t['disabledFg']}; border-color: {t['disabledFg']}; }}
/* Listas desplegables: sin reglas propias Qt las pintaba negras con texto oscuro (sección Asistente y diálogo
   del modelo externo, 13-oct) */
QComboBox {{ background: {t['surface']}; color: {t['on']}; border: 1px solid {t['outline']}; border-radius: 12px;
    padding: 6px 12px; min-height: 26px; }}
QComboBox:hover {{ border-color: {t['primary']}; }}
QComboBox:focus, QComboBox:on {{ border: 2px solid {t['primary']}; }}
QComboBox:disabled {{ background: {t['disabledBg']}; color: {t['disabledFg']}; border-color: {t['outlineV']}; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 28px; border: none;
    background: transparent; }}
QComboBox::down-arrow {{ image: url("{flecha}"); width: 14px; height: 14px; }}
QComboBox QLineEdit {{ background: transparent; border: none; padding: 0; color: {t['on']}; }}
QComboBox QAbstractItemView {{ background: {t['surface']}; color: {t['on']}; border: 1px solid {t['outlineV']};
    selection-background-color: {t['primaryC']}; selection-color: {t['onPrimaryC']}; outline: none; padding: 4px; }}

QProgressBar {{ background: {t['outlineV']}; border: none; border-radius: 4px; max-height: 8px; min-height: 8px; }}
QProgressBar::chunk {{ background: {t['primary']}; border-radius: 4px; }}

/* Vistas de árbol y de lista (p. ej. el diálogo de archivos de Qt cuando no hay portal del escritorio): sin reglas
   salían con fondo blanco en el tema oscuro (revisión visual, 16-oct) */
QTreeView, QListView {{ background: {t['surface']}; color: {t['on']}; border: 1px solid {t['outlineV']};
    border-radius: 8px; selection-background-color: {t['primaryC']}; selection-color: {t['onPrimaryC']};
    alternate-background-color: {t['surface2']}; }}
QComboBox QAbstractItemView {{ border-radius: 0; }}

QTableWidget {{ background: transparent; border: none; gridline-color: transparent; font-size: 13px;
    selection-background-color: {t['primaryC']}; selection-color: {t['onPrimaryC']}; }}
QTableWidget::item {{ border-top: 1px solid {t['outlineV']}; padding: 6px 8px; }}
QHeaderView {{ background: transparent; border: none; }}
QHeaderView::section {{ background: transparent; color: {t['muted']}; border: none; padding: 6px 8px;
    font-size: 12px; font-weight: 600; }}
QTableCornerButton::section {{ background: transparent; border: none; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t['outlineV']}; border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t['outlineV']}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* Menús (clic derecho en los campos de texto: Copiar, Pegar…). Sin reglas salían negros y sin texto legible
   (autor, 13-oct, al pegar la clave de API) */
QMenu {{ background: {t['surface']}; color: {t['on']}; border: 1px solid {t['outlineV']}; border-radius: 10px;
    padding: 6px; }}
QMenu::item {{ padding: 6px 28px 6px 12px; border-radius: 6px; background: transparent; color: {t['on']}; }}
QMenu::item:selected {{ background: {t['primaryC']}; color: {t['onPrimaryC']}; }}
QMenu::item:disabled {{ color: {t['disabledFg']}; }}
QMenu::separator {{ height: 1px; background: {t['outlineV']}; margin: 4px 8px; }}

/* Conversación del asistente (estilo chat) */
QScrollArea#conversacion, QScrollArea#conversacion > QWidget > QWidget {{ background: {t['surface']}; border: none; }}
QFrame[rol="burbuja"] {{ background: {t['surface2']}; border-radius: 18px; }}
QFrame[rol="burbuja"] QLabel {{ color: {t['on']}; }}
QFrame[rol="cajaEntrada"] {{ background: {t['surface']}; border: 1px solid {t['outline']}; border-radius: 20px;
    min-height: 44px; }}
QFrame[rol="cajaEntrada"] QLineEdit {{ border: none; background: transparent; padding: 10px 6px; font-size: 15px; }}
QPushButton[variante="enviar"] {{ min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px;
    border-radius: 20px; padding: 0; }}
QPushButton[variante="detener"] {{ min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px;
    border-radius: 20px; padding: 0; background: {t['on']}; }}
QLabel[rol="pieRespuesta"] {{ color: {t['muted']}; font-size: 12px; }}

QDialog {{ background: {t['surface']}; }}
QDialog QLabel, QDialog QCheckBox {{ color: {t['on']}; }}
"""


class PortalApariencia:
    """Preferencia claro/oscuro del escritorio según el portal freedesktop (GNOME, KDE...).

    Es lo que el usuario elige en Configuración → Apariencia. Qt, cuando el portal dice "sin preferencia",
    adivina por los colores del tema GTK, y con un tema GTK oscuro reporta oscuro aunque el usuario haya
    elegido claro (caso real: tema "Space-transparency" con estilo Claro en Ubuntu 26.04).
    consultar() devuelve True (oscuro), False (claro o sin preferencia) o None si no hay portal.
    """
    SERVICIO, RUTA, INTERFAZ = "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop", \
        "org.freedesktop.portal.Settings"

    def __init__(self):
        self._iface = None
        try:
            from PySide6.QtDBus import QDBusConnection, QDBusInterface
            bus = QDBusConnection.sessionBus()
            if bus.isConnected():
                iface = QDBusInterface(self.SERVICIO, self.RUTA, self.INTERFAZ, bus)
                if iface.isValid():
                    self._iface = iface
        except Exception:  # sin QtDBus o sin bus de sesión (Windows, contenedores)
            self._iface = None

    def consultar(self) -> Optional[bool]:
        if self._iface is None:
            return None
        try:
            from PySide6.QtDBus import QDBusMessage, QDBusVariant
            r = self._iface.call("ReadOne", "org.freedesktop.appearance", "color-scheme")
            if r.type() != QDBusMessage.ReplyMessage:          # portales viejos solo tienen Read
                r = self._iface.call("Read", "org.freedesktop.appearance", "color-scheme")
            if r.type() != QDBusMessage.ReplyMessage or not r.arguments():
                return None
            v = r.arguments()[0]
            while isinstance(v, QDBusVariant):
                v = v.variant()
            return int(v) == 1                                  # 1 oscuro; 0 sin preferencia y 2 claro -> claro
        except Exception:
            return None


class GestorTema(QObject):
    """Modo 'sistema' | 'claro' | 'oscuro'. Emite `cambiado(tokens)` cada vez que cambian los colores."""
    cambiado = Signal(dict)
    MODOS = ("sistema", "claro", "oscuro")

    REVISION_PORTAL_MS = 2000

    def __init__(self, app: QGuiApplication, persistir: bool = True, modo: Optional[str] = None,
                 portal: Optional[Callable[[], Optional[bool]]] = None):
        """portal: función que devuelve la preferencia del escritorio (True oscuro, False claro, None sin
        portal); por defecto se consulta el portal freedesktop. Se puede sustituir en las pruebas."""
        super().__init__()
        self.app = app
        self._portal = portal if portal is not None else PortalApariencia().consultar
        self._oscuro_aplicado: Optional[bool] = None
        self._ajustes = QSettings("Tesis-ITF", "MotorGuard-ITF") if persistir else None
        guardado = self._ajustes.value("tema", "sistema") if self._ajustes else "sistema"
        self.modo = modo or (guardado if guardado in self.MODOS else "sistema")
        self.t: Dict[str, str] = CLARO
        self._iconos: List[Tuple[object, str, str, int]] = []
        self._hints = app.styleHints()
        self._hints.colorSchemeChanged.connect(lambda *_: self._revisar_sistema())
        # El portal no avisa por esta vía: en modo sistema se revisa cada 2 s (una llamada D-Bus barata)
        self._revision = QTimer(self)
        self._revision.timeout.connect(self._revisar_sistema)
        self._revision.start(self.REVISION_PORTAL_MS)
        self._aplicar()

    def preferencia_sistema(self) -> bool:
        """True si el escritorio pide oscuro: primero el portal; sin portal, lo que diga Qt."""
        p = self._portal()
        if p is not None:
            return p
        return self._hints.colorScheme() == Qt.ColorScheme.Dark

    @property
    def oscuro(self) -> bool:
        if self.modo == "oscuro":
            return True
        if self.modo == "claro":
            return False
        return self.preferencia_sistema()

    def _revisar_sistema(self):
        if self.modo == "sistema" and self.oscuro != self._oscuro_aplicado:
            self._aplicar()

    def poner_modo(self, modo: str):
        if modo not in self.MODOS:
            raise ValueError(modo)
        self.modo = modo
        if self._ajustes:
            self._ajustes.setValue("tema", modo)
        self._aplicar()

    def registrar_icono(self, widget, nombre: str, token: str, tam: int = 20):
        """El widget (botón, etiqueta) lleva el ícono `nombre` en el color del token; se redibuja al cambiar."""
        self._iconos.append((widget, nombre, token, tam))
        self._pintar_icono(widget, nombre, token, tam)

    def _pintar_icono(self, widget, nombre, token, tam):
        ic = icono(nombre, self.t[token], tam)
        if hasattr(widget, "setIcon"):
            widget.setIcon(ic)
            widget.setIconSize(QSize(tam, tam))
        else:
            widget.setPixmap(ic.pixmap(QSize(tam, tam)))

    def _aplicar(self):
        self._oscuro_aplicado = self.oscuro
        self.t = OSCURO if self._oscuro_aplicado else CLARO
        self.app.setStyleSheet(qss(self.t))
        vivos = []
        for w, nombre, token, tam in self._iconos:
            try:
                self._pintar_icono(w, nombre, token, tam)
                vivos.append((w, nombre, token, tam))
            except RuntimeError:
                pass  # widget ya destruido
        self._iconos = vivos
        self.cambiado.emit(self.t)


def estilizar_plot(plot, t: Dict[str, str]):
    """Colores de una gráfica de pyqtgraph según el tema."""
    import pyqtgraph as pg
    plot.setBackground(t["plotBg"])
    for eje in ("left", "bottom"):
        ax = plot.getAxis(eje)
        ax.setPen(pg.mkPen(t["outlineV"]))
        ax.setTextPen(pg.mkPen(t["muted"]))
    plot.showGrid(x=True, y=True, alpha=0.18 if t is CLARO else 0.25)
    # Leyenda con fondo: sin él, quedaba encima de las curvas con el texto gris ilegible (revisión visual, 16-oct)
    item = plot.getPlotItem() if hasattr(plot, "getPlotItem") else plot
    leyenda = getattr(item, "legend", None)
    if leyenda is not None:
        fondo = pg.mkColor(t["surface"])
        fondo.setAlpha(225)
        leyenda.setBrush(pg.mkBrush(fondo))
        leyenda.setPen(pg.mkPen(t["outlineV"]))
        leyenda.setLabelTextColor(pg.mkColor(t["on"]))
        for muestra, etiqueta_ley in leyenda.items:      # setLabelTextColor no vuelve a dibujar el texto existente
            etiqueta_ley.setText(etiqueta_ley.text, color=t["on"])
            muestra.update()
