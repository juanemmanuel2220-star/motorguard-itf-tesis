"""
Cuadrante 3: Tabla de Diagnóstico Cuantitativo en Vivo y Alertas Z-Score.
Muestra en tiempo real las diferencias absolutas, porcentuales y puntuaciones normalizadas Z,
con semáforos de color basados en los umbrales auditados (|Z|<2 normal, 2<=|Z|<5 transición, |Z|>=5 anomalía).
"""

from typing import List
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView, QLabel, QHBoxLayout
)
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor, QFont

from motorguard_dashboard.core.data_types import DeviationMetrics

COLUMNS = ["Variable", "Valor Actual", "Ref. Sana (μ ± σ)", "Δ Absoluto", "Δ %", "Z-Score", "Diagnóstico"]

class DeviationTableWidget(QWidget):
    """
    Tabla interactiva de diagnóstico estadístico en tiempo real.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        
        # Cabecera
        hdr_layout = QHBoxLayout()
        title = QLabel("CUADRANTE 3: Diagnóstico Cuantitativo vs Referencia Sana (Z-Score)")
        title.setStyleSheet("font-weight: 700; color: #38bdf8; font-size: 13px;")
        hdr_layout.addWidget(title)
        hdr_layout.addStretch()
        
        self.lbl_status = QLabel("● Estado: Esperando Baseline")
        self.lbl_status.setStyleSheet("color: #94a3b8; font-size: 11px;")
        hdr_layout.addWidget(self.lbl_status)
        layout.addLayout(hdr_layout)
        
        # Tabla QTableWidget
        self.table = QTableWidget()
        self.table.setColumnCount(len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setAlternatingRowColors(True)
        
        layout.addWidget(self.table)

    @Slot(list)
    def update_metrics(self, deviations: List[DeviationMetrics]):
        """Actualiza todas las filas de la tabla con los residuos calculados."""
        if not deviations:
            return

        self.lbl_status.setText("● Monitoreo Activo vs Baseline")
        self.lbl_status.setStyleSheet("color: #10b981; font-weight: 600; font-size: 11px;")
        
        self.table.setRowCount(len(deviations))
        
        for row, d in enumerate(deviations):
            # 1. Variable
            item_var = QTableWidgetItem(d.feature_name)
            item_var.setFont(QFont("sans-serif", 9, QFont.Bold))
            item_var.setForeground(QColor("#f8fafc"))
            
            # 2. Actual
            item_act = QTableWidgetItem(f"{d.current_value:.4f}" if abs(d.current_value) < 1.0 else f"{d.current_value:.2f}")
            item_act.setTextAlignment(Qt.AlignCenter)
            item_act.setForeground(QColor("#e2e8f0"))
            
            # 3. Ref Sana
            ref_str = f"{d.ref_mean:.4f} ± {d.ref_std:.4f}" if abs(d.ref_mean) < 1.0 else f"{d.ref_mean:.2f} ± {d.ref_std:.2f}"
            item_ref = QTableWidgetItem(ref_str)
            item_ref.setTextAlignment(Qt.AlignCenter)
            item_ref.setForeground(QColor("#94a3b8"))
            
            # 4. Delta Abs
            sign_abs = "+" if d.delta_abs >= 0 else ""
            item_dabs = QTableWidgetItem(f"{sign_abs}{d.delta_abs:.4f}" if abs(d.delta_abs) < 1.0 else f"{sign_abs}{d.delta_abs:.2f}")
            item_dabs.setTextAlignment(Qt.AlignCenter)
            
            # 5. Delta Pct
            sign_pct = "+" if d.delta_pct >= 0 else ""
            item_dpct = QTableWidgetItem(f"{sign_pct}{d.delta_pct:.1f}%")
            item_dpct.setTextAlignment(Qt.AlignCenter)
            
            # 6. Z-Score
            sign_z = "+" if d.z_score >= 0 else ""
            item_z = QTableWidgetItem(f"{sign_z}{d.z_score:.2f}")
            item_z.setTextAlignment(Qt.AlignCenter)
            item_z.setFont(QFont("sans-serif", 9, QFont.Bold))
            
            # 7. Diagnóstico Badge
            item_diag = QTableWidgetItem()
            item_diag.setTextAlignment(Qt.AlignCenter)
            item_diag.setFont(QFont("sans-serif", 9, QFont.Bold))
            
            # Formato de semáforo según severidad
            if d.alert_level == "NORMAL":
                item_diag.setText(" NORMAL ")
                item_diag.setBackground(QColor("#064e3b"))
                item_diag.setForeground(QColor("#34d399"))
                item_z.setForeground(QColor("#34d399"))
                item_dpct.setForeground(QColor("#94a3b8"))
                item_dabs.setForeground(QColor("#94a3b8"))
            elif d.alert_level == "WARNING":
                item_diag.setText(" ATENCIÓN ")
                item_diag.setBackground(QColor("#78350f"))
                item_diag.setForeground(QColor("#fbbf24"))
                item_z.setForeground(QColor("#fbbf24"))
                item_dpct.setForeground(QColor("#fbbf24"))
                item_dabs.setForeground(QColor("#fbbf24"))
            else:  # FAULT
                item_diag.setText(" FALLA ITF ")
                item_diag.setBackground(QColor("#7f1d1d"))
                item_diag.setForeground(QColor("#f87171"))
                item_z.setForeground(QColor("#f87171"))
                item_dpct.setForeground(QColor("#f87171"))
                item_dabs.setForeground(QColor("#f87171"))
                
            self.table.setItem(row, 0, item_var)
            self.table.setItem(row, 1, item_act)
            self.table.setItem(row, 2, item_ref)
            self.table.setItem(row, 3, item_dabs)
            self.table.setItem(row, 4, item_dpct)
            self.table.setItem(row, 5, item_z)
            self.table.setItem(row, 6, item_diag)
