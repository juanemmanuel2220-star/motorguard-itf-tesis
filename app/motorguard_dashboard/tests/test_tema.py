"""
Tema claro/oscuro: modos, seguimiento del tema del sistema y contraste de los pares de texto (WCAG 4.5:1).
"""

from motorguard_dashboard.tests import qt_util
from motorguard_dashboard.ui.tema import CLARO, OSCURO, GestorTema, qss

PARES_TEXTO = [  # (texto, fondo)
    ("on", "bg"), ("on", "surface"), ("on", "surface2"), ("muted", "surface"), ("muted", "bg"),
    ("muted", "surface2"), ("onPrimary", "primary"), ("onPrimaryC", "primaryC"), ("onError", "error"),
    ("disabledFg", "disabledBg"), ("sanoOn", "sanoC"), ("leveOn", "leveC"), ("interOn", "interC"),
    ("severaOn", "severaC"), ("apagadoOn", "apagadoC"), ("leveFg", "surface"), ("interFg", "surface"),
    ("primary", "surface"),
]


def _lum(hexa):
    r, g, b = (int(hexa[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contraste(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_contraste():
    peores = []
    for nombre, t in (("claro", CLARO), ("oscuro", OSCURO)):
        for texto, fondo in PARES_TEXTO:
            c = contraste(t[texto], t[fondo])
            assert c >= 4.5, f"{nombre}: {texto} sobre {fondo} = {c:.2f}:1"
            peores.append(c)
    print(f"  contraste mínimo de los pares de texto: {min(peores):.2f}:1")


def test_modos_y_sistema():
    from PySide6.QtCore import Qt
    app = qt_util.app()
    recibidos = []
    portal = {"valor": None}                           # None = sin portal: decide Qt
    g = GestorTema(app, persistir=False, modo="claro", portal=lambda: portal["valor"])
    g.cambiado.connect(recibidos.append)
    try:
        assert g.t is CLARO and app.styleSheet() == qss(CLARO)
        g.poner_modo("oscuro")
        assert g.t is OSCURO and recibidos[-1] == OSCURO and app.styleSheet() == qss(OSCURO)
        # 'sistema' sigue al tema del escritorio. La plataforma sin pantalla de las pruebas no simula el
        # tema del sistema (colorScheme() siempre es Unknown), así que se sustituye por uno falso y se llama
        # al mismo método que dispara la señal colorSchemeChanged de Qt.
        class Sistema:
            esquema = Qt.ColorScheme.Dark

            def colorScheme(self):
                return self.esquema

        sistema = Sistema()
        g._hints = sistema
        g.poner_modo("sistema")
        assert g.oscuro and g.t is OSCURO
        sistema.esquema = Qt.ColorScheme.Light
        g._aplicar()                      # lo que hace la señal colorSchemeChanged
        assert not g.oscuro and g.t is CLARO
        # Elegido a mano, ya no lo sigue
        g.poner_modo("oscuro")
        sistema.esquema = Qt.ColorScheme.Light
        g._aplicar()
        assert g.t is OSCURO

        # Con portal, el portal manda (caso real: estilo Claro en Ubuntu con un tema GTK oscuro, Qt dice Dark)
        g.poner_modo("sistema")
        sistema.esquema = Qt.ColorScheme.Dark
        portal["valor"] = False
        g._revisar_sistema()
        assert g.t is CLARO, "con el portal en claro, el modo sistema debe quedar claro aunque Qt diga oscuro"
        n = len(recibidos)
        g._revisar_sistema()
        assert len(recibidos) == n, "sin cambios no se vuelve a aplicar el tema"
        portal["valor"] = True                         # el usuario cambia a oscuro en Configuración
        g._revisar_sistema()
        assert g.t is OSCURO and recibidos[-1] == OSCURO
        try:
            g.poner_modo("azul")
            raise AssertionError("aceptó un modo inválido")
        except ValueError:
            pass
    finally:
        g.poner_modo("claro")


def test_casillas_se_distinguen():
    """La casilla sin marcar se ve vacía (color de la superficie) y la marcada, rellena del color primario. Antes
    de definir QCheckBox::indicator, Qt pintaba ambas como un cuadro negro (diálogo de inyección, 13-oct)."""
    app = qt_util.app()
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QCheckBox
    for modo, t in (("claro", CLARO), ("oscuro", OSCURO)):
        estilo = qss(t)
        assert "QCheckBox::indicator:checked" in estilo and "palomita" in estilo
        GestorTema(app, persistir=False, modo=modo)
        colores = {}
        for marcada in (False, True):
            c = QCheckBox("casilla")
            c.setStyleSheet(estilo)
            c.setChecked(marcada)
            c.resize(160, 34)
            c.show()
            app.processEvents()
            img = c.grab().toImage()
            # Interior del indicador (18 px + borde de 2 px), a media altura y junto al borde derecho, donde no
            # cae el trazo de la palomita
            colores[marcada] = QColor(img.pixel(18, img.height() // 2)).name()
            c.close()
        assert colores[False] != colores[True], (modo, colores)
        assert colores[False] == t["surface"].lower(), (modo, colores)
        assert colores[True] == t["primary"].lower(), (modo, colores)
    print("  casillas: vacía con el color de la superficie y marcada con el primario (claro y oscuro)")


def test_listas_desplegables_legibles():
    """El cuadro de una lista desplegable usa el color de la superficie (antes salía negro con texto oscuro en la
    sección Asistente y el diálogo del modelo externo, 13-oct), también la editable."""
    app = qt_util.app()
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QComboBox
    for modo, t in (("claro", CLARO), ("oscuro", OSCURO)):
        estilo = qss(t)
        assert "QComboBox QAbstractItemView" in estilo and "QComboBox::down-arrow" in estilo
        assert "QMenu::item:selected" in estilo           # menú del clic derecho (antes negro, 13-oct)
        GestorTema(app, persistir=False, modo=modo)
        for editable in (False, True):
            c = QComboBox()
            c.setStyleSheet(estilo)
            c.setEditable(editable)
            c.addItems(["Qwen3.5-4B (local, 2.7 GB)"])
            c.resize(320, 44)
            c.show()
            app.processEvents()
            img = c.grab().toImage()
            fondo = QColor(img.pixel(img.width() // 2, 6)).name()   # franja superior, sin texto
            c.close()
            assert fondo == t["surface"].lower(), (modo, editable, fondo)
    print("  listas desplegables: fondo de superficie en claro y oscuro (normal y editable)")


def test_leyendas_y_vistas():
    """Las leyendas de las gráficas llevan fondo y texto del tema (setLabelTextColor de pyqtgraph no redibujaba las
    etiquetas existentes) y las vistas de árbol/lista tienen estilo (revisión visual, 16-oct)."""
    app = qt_util.app()
    import pyqtgraph as pg
    from motorguard_dashboard.ui.tema import estilizar_plot
    for t in (CLARO, OSCURO):
        assert "QTreeView, QListView" in qss(t)
        p = pg.PlotWidget()
        p.addLegend()
        p.plot([0, 1], [0, 1], name="I_A")
        estilizar_plot(p, t)
        ley = p.getPlotItem().legend
        assert ley.brush().color().name() == t["surface"].lower()
        assert all(et.opts["color"] == t["on"] and t["on"].lower() in et.item.toHtml().lower()
                   for _, et in ley.items), [et.item.toHtml() for _, et in ley.items]
    print("  leyendas con fondo y texto del tema; vistas de árbol y lista con estilo")


def run():
    test_contraste()
    test_modos_y_sistema()
    test_casillas_se_distinguen()
    test_listas_desplegables_legibles()
    test_leyendas_y_vistas()
    print("✓ Tema claro/oscuro: 5/5 pruebas")


if __name__ == "__main__":
    run()
