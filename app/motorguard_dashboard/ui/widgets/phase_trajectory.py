"""
Cuadrante 4: Espacio de Estado y Gráfico de Dispersión Carga vs Asimetría (I_prom vs I_unb).
Permite discriminar visualmente la física del fenómeno:
  - Cambio de carga (simétrico): Desplazamiento puramente horizontal (eje X).
  - Falla entre espiras ITF (asimétrica): Desplazamiento puramente vertical (eje Y).
Traza la trayectoria en tiempo real con una estela temporal de los últimos 30 puntos (15 segundos).
"""

from collections import deque
import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PySide6.QtCore import Qt, Slot

class PhaseTrajectoryWidget(QWidget):
    """
    Gráfico de fase 2D (I_prom vs I_unb) para análisis de trayectorias experimentales.
    """
    def __init__(self, max_points: int = 30, parent=None):
        super().__init__(parent)
        self.max_points = max_points
        self._history_x = deque(maxlen=max_points)
        self._history_y = deque(maxlen=max_points)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        
        # Cabecera
        hdr_layout = QHBoxLayout()
        title = QLabel("CUADRANTE 4: Espacio de Estado (Carga vs Desbalance ITF)")
        title.setStyleSheet("font-weight: 700; color: #38bdf8; font-size: 13px;")
        hdr_layout.addWidget(title)
        hdr_layout.addStretch()
        
        leg_desc = QLabel("X: Carga Simétrica (A) | Y: Asimetría ITF (%)")
        leg_desc.setStyleSheet("color: #94a3b8; font-size: 11px;")
        hdr_layout.addWidget(leg_desc)
        layout.addLayout(hdr_layout)
        
        # PlotWidget de PyQtGraph
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground("#090d16")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.25)
        self.plot_widget.setLabel("left", "Desbalance Trifásico I_unb", units="%", color="#94a3b8")
        self.plot_widget.setLabel("bottom", "Corriente RMS Promedio I_prom", units="A", color="#94a3b8")
        self.plot_widget.setXRange(3.8, 7.2, padding=0.02)
        self.plot_widget.setYRange(0.0, 20.0, padding=0.05)
        self.plot_widget.getPlotItem().hideButtons()

        # Línea de umbral de desbalance normal (2.0%)
        pen_thresh = pg.mkPen(color="#f59e0b", width=1, style=Qt.DashLine)
        self.thresh_line = pg.InfiniteLine(
            pos=2.0,
            angle=0,
            pen=pen_thresh,
            label=" Umbral Desbalance (2.0%)",
            labelOpts={"color": "#f59e0b", "position": 0.85}
        )
        self.plot_widget.addItem(self.thresh_line)

        # Rombos de referencia sana para los 4 niveles de carga auditados
        self._load_nominal_pts = [
            (4.45, 0.6, "L0 (0%)"),
            (4.95, 0.7, "L1 (25%)"),
            (5.60, 0.8, "L2 (50%)"),
            (6.40, 0.9, "L3 (75%)")
        ]
        
        ref_x = [p[0] for p in self._load_nominal_pts]
        ref_y = [p[1] for p in self._load_nominal_pts]
        self.scatter_refs = pg.ScatterPlotItem(
            x=ref_x,
            y=ref_y,
            pen=pg.mkPen(color="#10b981", width=2),
            brush=pg.mkBrush(color="#064e3b"),
            symbol="d",
            size=12,
            name="Referencias Sanas"
        )
        self.plot_widget.addItem(self.scatter_refs)
        
        for px, py, plabel in self._load_nominal_pts:
            text = pg.TextItem(plabel, color="#10b981", anchor=(0.5, 1.3))
            text.setPos(px, py)
            self.plot_widget.addItem(text)

        # Trazo de la trayectoria temporal (línea continua atenuada)
        pen_tail = pg.mkPen(color="#0284c7", width=1.5, style=Qt.SolidLine)
        self.curve_tail = self.plot_widget.plot(pen=pen_tail)
        
        # Puntos de la estela
        self.scatter_tail = pg.ScatterPlotItem(
            pen=pg.mkPen(color="#38bdf8", width=1),
            brush=pg.mkBrush(color="#0369a1"),
            symbol="o",
            size=6
        )
        self.plot_widget.addItem(self.scatter_tail)

        # Punto actual vivo (destacado)
        self.scatter_current = pg.ScatterPlotItem(
            symbol="o",
            size=14
        )
        self.plot_widget.addItem(self.scatter_current)

        layout.addWidget(self.plot_widget)

    @Slot(float, float)
    def update_point(self, i_prom: float, i_unb: float):
        """Añade un nuevo punto (I_prom, I_unb) a la trayectoria en vivo."""
        if i_prom < 0.5:
            return  # Motor apagado o corriente nula
            
        self._history_x.append(i_prom)
        self._history_y.append(i_unb)
        
        hx = list(self._history_x)
        hy = list(self._history_y)
        
        # Actualizar estela
        self.curve_tail.setData(hx, hy)
        self.scatter_tail.setData(hx, hy)
        
        # Color dinámico del punto actual según severidad de desbalance
        if i_unb < 2.0:
            brush_curr = pg.mkBrush(color="#10b981")
            pen_curr = pg.mkPen(color="#34d399", width=2)
        elif i_unb < 5.0:
            brush_curr = pg.mkBrush(color="#f59e0b")
            pen_curr = pg.mkPen(color="#fbbf24", width=2)
        else:
            brush_curr = pg.mkBrush(color="#ef4444")
            pen_curr = pg.mkPen(color="#f87171", width=2)
            
        self.scatter_current.setData(
            [i_prom], [i_unb],
            pen=pen_curr,
            brush=brush_curr
        )

    def clear(self):
        """Reinicia la trayectoria temporal."""
        self._history_x.clear()
        self._history_y.clear()
        self.curve_tail.clear()
        self.scatter_tail.clear()
        self.scatter_current.clear()
