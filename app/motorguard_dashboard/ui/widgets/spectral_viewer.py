"""
Cuadrante 2: Analizador Espectral MCSA Superpuesto (0 - 300 Hz).
Muestra el espectro en tiempo real de la Fase C superpuesto con la firma sana de referencia en verde.
Incluye marcadores en 60 Hz (fundamental), 55 Hz (A55) y 65 Hz (A65), y modo de zoom en la banda MCSA.
"""

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, Slot

from motorguard_dashboard.core.config import MAX_FREQ_HZ
from motorguard_dashboard.core.data_types import WindowFeatures, BaselineProfile

class SpectralViewerWidget(QWidget):
    """
    Visualizador de espectro FFT con superposición de referencia sana.
    Permite comparar visualmente el surgimiento de armónicos de falla entre espiras.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_zoomed = False
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        
        # Cabecera con controles de zoom y leyenda
        hdr_layout = QHBoxLayout()
        title = QLabel("CUADRANTE 2: Espectro MCSA (Fase C vs Ref. Sana)")
        title.setStyleSheet("font-weight: 700; color: #38bdf8; font-size: 13px;")
        hdr_layout.addWidget(title)
        hdr_layout.addStretch()
        
        leg_actual = QLabel("● Actual")
        leg_actual.setStyleSheet("color: #facc15; font-weight: 700; font-size: 12px; margin-right: 8px;")
        leg_ref = QLabel("● Ref Sana")
        leg_ref.setStyleSheet("color: #10b981; font-weight: 700; font-size: 12px; margin-right: 12px;")
        
        self.btn_zoom = QPushButton("🔍 Zoom MCSA (45-75 Hz)")
        self.btn_zoom.setFixedHeight(26)
        self.btn_zoom.setStyleSheet("font-size: 11px; padding: 2px 8px;")
        self.btn_zoom.clicked.connect(self._toggle_zoom)
        
        hdr_layout.addWidget(leg_actual)
        hdr_layout.addWidget(leg_ref)
        hdr_layout.addWidget(self.btn_zoom)
        layout.addLayout(hdr_layout)
        
        # Gráfica PyQtGraph
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground("#090d16")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.25)
        self.plot_widget.setLabel("left", "Amplitud Pico", units="A", color="#94a3b8")
        self.plot_widget.setLabel("bottom", "Frecuencia", units="Hz", color="#94a3b8")
        self.plot_widget.setXRange(0.0, 300.0, padding=0.01)
        self.plot_widget.setYRange(0.0, 6.5, padding=0.05)
        self.plot_widget.getPlotItem().hideButtons()
        
        # Líneas verticales indicadoras fijas
        pen_fund = pg.mkPen(color="#94a3b8", width=1, style=Qt.DashLine)
        pen_55 = pg.mkPen(color="#f97316", width=1.5, style=Qt.DashLine)
        pen_65 = pg.mkPen(color="#ef4444", width=1.5, style=Qt.DashLine)
        
        self.line_fund = pg.InfiniteLine(pos=60.0, angle=90, pen=pen_fund, label=" 60 Hz", labelOpts={"color": "#94a3b8", "position": 0.9})
        self.line_55 = pg.InfiniteLine(pos=55.0, angle=90, pen=pen_55, label=" A55 (55 Hz)", labelOpts={"color": "#f97316", "position": 0.75})
        self.line_65 = pg.InfiniteLine(pos=65.0, angle=90, pen=pen_65, label=" A65 (65 Hz)", labelOpts={"color": "#ef4444", "position": 0.60})
        
        self.plot_widget.addItem(self.line_fund)
        self.plot_widget.addItem(self.line_55)
        self.plot_widget.addItem(self.line_65)
        
        # Curva de referencia sana (Verde esmeralda con relleno tenue)
        pen_ref = pg.mkPen(color="#10b981", width=1.5)
        self.curve_ref = self.plot_widget.plot(pen=pen_ref, name="Ref Sana")
        
        # Curva en vivo (Amarillo brillante)
        pen_actual = pg.mkPen(color="#facc15", width=2.0)
        self.curve_actual = self.plot_widget.plot(pen=pen_actual, name="Fase C")
        
        layout.addWidget(self.plot_widget)

    def _toggle_zoom(self):
        """Alterna entre vista completa 0-300 Hz y zoom en la banda MCSA 45-75 Hz."""
        self._is_zoomed = not self._is_zoomed
        if self._is_zoomed:
            self.plot_widget.setXRange(45.0, 75.0, padding=0.02)
            self.btn_zoom.setText("🌐 Espectro Completo (0-300 Hz)")
        else:
            self.plot_widget.setXRange(0.0, 300.0, padding=0.01)
            self.btn_zoom.setText("🔍 Zoom MCSA (45-75 Hz)")

    @Slot(object)
    def update_spectrum(self, features: WindowFeatures):
        """Actualiza la curva de espectro actual en vivo."""
        self.curve_actual.setData(features.freqs, features.fft_mag_C)
        # Ajustar dinámicamente posición de fundamentales si hubo variación de slip
        if features.A_fund > 0.5:
            # Buscar fundamental exacta
            idx_fund = int(np.argmax(features.fft_mag_C[55:65])) + 55
            f0 = features.freqs[idx_fund]
            self.line_fund.setPos(f0)
            self.line_55.setPos(f0 - 5.0)
            self.line_65.setPos(f0 + 5.0)

    @Slot(object)
    def set_reference_spectrum(self, profile: BaselineProfile):
        """Actualiza la curva de referencia sana (verde)."""
        freqs = np.arange(len(profile.mean_spectrum_C), dtype=np.float32)
        self.curve_ref.setData(freqs, profile.mean_spectrum_C)

    def clear(self):
        """Limpia las curvas del espectro."""
        self.curve_actual.clear()
        self.curve_ref.clear()
