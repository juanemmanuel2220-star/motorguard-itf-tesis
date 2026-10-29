"""
Cuadrante 1: Osciloscopio Temporal de Corrientes Trifásicas (Ia, Ib, Ic) y Marcadores de Eventos.
Optimizado con pyqtgraph a 60 FPS con downsampling de picos para preservar transitorios sin sobrecarga.
"""

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout
from PySide6.QtCore import Qt, Slot

from motorguard_dashboard.core.config import FS
from motorguard_dashboard.core.data_types import RawSampleChunk

class TemporalScopeWidget(QWidget):
    """
    Osciloscopio en tiempo real que muestra las 3 fases de corriente
    y traza líneas verticales con etiquetas cada vez que ocurre un evento experimental.
    """
    def __init__(self, buffer_seconds: float = 1.5, fs: float = FS, parent=None):
        super().__init__(parent)
        self.fs = fs
        self.buffer_len = int(buffer_seconds * fs)  # 3600 muestras = 1.5 s
        
        # Buffer rodante local para display
        self._currents_buffer = np.zeros((3, self.buffer_len), dtype=np.float32)
        self._time_axis = np.linspace(-buffer_seconds, 0, self.buffer_len, endpoint=False)
        self._samples_received = 0
        
        # Lista de marcadores de eventos (máximo 8 activos para mantener la gráfica despejada)
        self._event_lines = []
        
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        
        # Cabecera del cuadrante con leyenda integrada
        hdr_layout = QHBoxLayout()
        title = QLabel("CUADRANTE 1: Osciloscopio Temporal de Corrientes (Ia, Ib, Ic)")
        title.setStyleSheet("font-weight: 700; color: #38bdf8; font-size: 13px;")
        hdr_layout.addWidget(title)
        hdr_layout.addStretch()
        
        leg_ia = QLabel("● Ia")
        leg_ia.setStyleSheet("color: #eab308; font-weight: 700; font-size: 12px; margin-right: 8px;")
        leg_ib = QLabel("● Ib")
        leg_ib.setStyleSheet("color: #06b6d4; font-weight: 700; font-size: 12px; margin-right: 8px;")
        leg_ic = QLabel("● Ic (ITF)")
        leg_ic.setStyleSheet("color: #ec4899; font-weight: 700; font-size: 12px;")
        
        hdr_layout.addWidget(leg_ia)
        hdr_layout.addWidget(leg_ib)
        hdr_layout.addWidget(leg_ic)
        layout.addLayout(hdr_layout)
        
        # Widget de PyQtGraph
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground("#090d16")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.25)
        self.plot_widget.setLabel("left", "Corriente", units="A", color="#94a3b8")
        self.plot_widget.setLabel("bottom", "Tiempo Relativo", units="s", color="#94a3b8")
        self.plot_widget.setYRange(-12.0, 12.0, padding=0.05)
        self.plot_widget.setXRange(self._time_axis[0], self._time_axis[-1], padding=0.01)
        self.plot_widget.enableAutoRange(axis=pg.ViewBox.YAxis, enable=False)
        self.plot_widget.getPlotItem().hideButtons()  # Desactivar botón 'A' de auto-zoom

        # Curvas para cada fase
        pen_ia = pg.mkPen(color="#eab308", width=1.5)
        pen_ib = pg.mkPen(color="#06b6d4", width=1.5)
        pen_ic = pg.mkPen(color="#ec4899", width=1.5)
        
        self.curve_ia = self.plot_widget.plot(pen=pen_ia, name="Ia")
        self.curve_ib = self.plot_widget.plot(pen=pen_ib, name="Ib")
        self.curve_ic = self.plot_widget.plot(pen=pen_ic, name="Ic")
        
        # Activar optimizaciones de pyqtgraph
        for c in (self.curve_ia, self.curve_ib, self.curve_ic):
            c.setDownsampling(auto=True, method='peak')
            c.setClipToView(True)
            
        layout.addWidget(self.plot_widget)

    @Slot(object)
    def update_chunk(self, chunk: RawSampleChunk):
        """Actualiza el buffer circular y redibuja las formas de onda."""
        m = chunk.currents.shape[1]
        if m == 0:
            return
            
        if m >= self.buffer_len:
            self._currents_buffer[:, :] = chunk.currents[:, -self.buffer_len:]
        else:
            # Desplazar hacia la izquierda e insertar al final
            self._currents_buffer[:, :-m] = self._currents_buffer[:, m:]
            self._currents_buffer[:, -m:] = chunk.currents
            
        self._samples_received += m
        
        # Actualizar curvas
        self.curve_ia.setData(self._time_axis, self._currents_buffer[0])
        self.curve_ib.setData(self._time_axis, self._currents_buffer[1])
        self.curve_ic.setData(self._time_axis, self._currents_buffer[2])

    def add_event_marker(self, label: str):
        """Inserta una línea vertical en el extremo derecho (t = 0 s) marcando un evento."""
        pen_event = pg.mkPen(color="#ef4444", width=2, style=Qt.DashLine)
        line = pg.InfiniteLine(
            pos=0.0,
            angle=90,
            pen=pen_event,
            label=f" {label}",
            labelOpts={"position": 0.85, "color": "#f8fafc", "fill": (239, 68, 68, 180), "movable": False}
        )
        self.plot_widget.addItem(line)
        self._event_lines.append(line)
        
        # Mantener un máximo de 8 líneas para no saturar el osciloscopio
        if len(self._event_lines) > 8:
            oldest = self._event_lines.pop(0)
            self.plot_widget.removeItem(oldest)

    def clear(self):
        """Reinicia el buffer a ceros y limpia marcadores."""
        self._currents_buffer.fill(0)
        for line in self._event_lines:
            self.plot_widget.removeItem(line)
        self._event_lines.clear()
        self.curve_ia.clear()
        self.curve_ib.clear()
        self.curve_ic.clear()
