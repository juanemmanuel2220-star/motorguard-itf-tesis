"""
Panel de Control y Barra de Eventos Experimentales en Tiempo Real.
100% enfocado en hardware real ESP32-S3 (sin simulación).
Muestra el estado de la conexión física por cable USB y despacha comandos hacia los relevadores SSR.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QProgressBar, QFrame
)
from PySide6.QtCore import Qt, Signal, Slot

from motorguard_dashboard.core.config import CARGAS

class ControlPanel(QWidget):
    """
    Panel de control para la estación de adquisición en tiempo real.
    """
    sig_reconnect_requested = Signal()           # Solicita re-escanear puerto USB
    sig_load_changed = Signal(int)               # load_level (0 a 3)
    sig_fault_changed = Signal(int)              # fault_class (0 a 3)
    sig_baseline_requested = Signal(int)         # load_level
    sig_record_toggled = Signal(bool)            # is_recording
    sig_event_button_clicked = Signal(str, str)  # (event_type, description)
    sig_command_requested = Signal(str)          # Comando serie al ESP32: '1', '2', '3', '0'

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_recording = False
        self._is_connected = False
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 4, 6, 4)
        main_layout.setSpacing(6)

        # ==================== FILA 1: HARDWARE REAL, CARGA Y BASELINE ====================
        row1 = QHBoxLayout()
        row1.setSpacing(10)

        # 1. Badge de Estado de Hardware Real
        lbl_hw_title = QLabel("Hardware:")
        lbl_hw_title.setStyleSheet("font-weight: 700; color: #38bdf8; font-size: 12px;")
        row1.addWidget(lbl_hw_title)

        self.lbl_hw_badge = QLabel("○ ESPERANDO CABLE USB (/dev/ttyACM*)")
        self.lbl_hw_badge.setObjectName("lbl_hw_disconnected")
        row1.addWidget(self.lbl_hw_badge)

        self.btn_reconnect = QPushButton("🔄 Re-escanear")
        self.btn_reconnect.setFixedHeight(26)
        self.btn_reconnect.setStyleSheet("font-size: 11px; padding: 2px 8px;")
        self.btn_reconnect.clicked.connect(self._on_reconnect_clicked)
        row1.addWidget(self.btn_reconnect)

        # Separador vertical
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.VLine)
        sep1.setStyleSheet("color: #283556;")
        row1.addWidget(sep1)

        # 2. Selector de Nivel de Carga
        lbl_carga = QLabel("Nivel de Carga:")
        lbl_carga.setStyleSheet("font-weight: 600; color: #94a3b8;")
        self.combo_carga = QComboBox()
        for lvl, name in CARGAS.items():
            self.combo_carga.addItem(f"{name}", lvl)
        self.combo_carga.currentIndexChanged.connect(self._on_load_selected)
        row1.addWidget(lbl_carga)
        row1.addWidget(self.combo_carga)

        # 3. Botón y Progreso de Baseline (5s)
        self.btn_baseline = QPushButton("📸 Capturar Baseline Sana (5s)")
        self.btn_baseline.setObjectName("btn_baseline")
        self.btn_baseline.clicked.connect(self._on_baseline_clicked)
        row1.addWidget(self.btn_baseline)

        self.progress_baseline = QProgressBar()
        self.progress_baseline.setRange(0, 10)
        self.progress_baseline.setValue(0)
        self.progress_baseline.setFixedWidth(90)
        self.progress_baseline.setFormat("%v/10 win")
        row1.addWidget(self.progress_baseline)

        # Separador vertical
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        sep2.setStyleSheet("color: #283556;")
        row1.addWidget(sep2)

        # 4. Grabación de Sesión CSV
        self.btn_record = QPushButton("● Iniciar Grabación")
        self.btn_record.setObjectName("btn_record")
        self.btn_record.clicked.connect(self._toggle_recording)
        row1.addWidget(self.btn_record)

        self.lbl_record_status = QLabel("REC: Inactivo")
        self.lbl_record_status.setStyleSheet("color: #64748b; font-size: 11px;")
        row1.addWidget(self.lbl_record_status)

        row1.addStretch()

        # 5. Indicador de Motor ON/OFF
        self.lbl_motor_state = QLabel("● MOTOR OFF")
        self.lbl_motor_state.setObjectName("lbl_motor_off")
        row1.addWidget(self.lbl_motor_state)

        main_layout.addLayout(row1)

        # ==================== FILA 2: BOTONES DE INYECCIÓN DE EVENTOS ====================
        row2 = QHBoxLayout()
        row2.setSpacing(10)

        lbl_ev = QLabel("Secuencia Experimental:")
        lbl_ev.setStyleSheet("font-weight: 700; color: #38bdf8; font-size: 12px;")
        row2.addWidget(lbl_ev)

        # Selector de Severidad de Falla ITF
        lbl_sev = QLabel("Severidad ITF:")
        lbl_sev.setStyleSheet("font-weight: 600; color: #94a3b8;")
        self.combo_severidad = QComboBox()
        self.combo_severidad.addItem("LEVE (Tap 1-2, ~5%)", 1)
        self.combo_severidad.addItem("INTERMEDIA (Tap 2-4, ~10%)", 2)
        self.combo_severidad.addItem("SEVERA (Tap 1-4, ~15%)", 3)
        row2.addWidget(lbl_sev)
        row2.addWidget(self.combo_severidad)

        # Botones Rápidos de Evento y Control de Hardware
        self.btn_ev_carga = QPushButton("⚡ Cambio de Carga")
        self.btn_ev_carga.setObjectName("btn_carga")
        self.btn_ev_carga.clicked.connect(self._on_ev_carga_clicked)
        row2.addWidget(self.btn_ev_carga)

        self.btn_ev_falla = QPushButton("⚠️ Inyectar Falla ITF")
        self.btn_ev_falla.setObjectName("btn_falla")
        self.btn_ev_falla.clicked.connect(self._on_ev_falla_clicked)
        row2.addWidget(self.btn_ev_falla)

        self.btn_ev_severidad = QPushButton("🔥 Aumentar Severidad")
        self.btn_ev_severidad.setObjectName("btn_severidad")
        self.btn_ev_severidad.clicked.connect(self._on_ev_severidad_clicked)
        row2.addWidget(self.btn_ev_severidad)

        self.btn_ev_sano = QPushButton("✅ Falla OFF / Sano")
        self.btn_ev_sano.setObjectName("btn_sano")
        self.btn_ev_sano.clicked.connect(self._on_ev_sano_clicked)
        row2.addWidget(self.btn_ev_sano)

        row2.addStretch()
        main_layout.addLayout(row2)

    def _on_reconnect_clicked(self):
        """Solicita re-escanear puertos USB."""
        self.sig_reconnect_requested.emit()

    def update_hardware_status(self, connected: bool, message: str):
        """Actualiza el badge de conexión USB de hardware real."""
        self._is_connected = connected
        if connected:
            self.lbl_hw_badge.setText(f"● {message}")
            self.lbl_hw_badge.setObjectName("lbl_hw_connected")
        else:
            self.lbl_hw_badge.setText(f"○ {message}")
            self.lbl_hw_badge.setObjectName("lbl_hw_disconnected")
        self.lbl_hw_badge.style().unpolish(self.lbl_hw_badge)
        self.lbl_hw_badge.style().polish(self.lbl_hw_badge)

    def _on_load_selected(self, index: int):
        load_lvl = self.combo_carga.currentData()
        self.sig_load_changed.emit(load_lvl)

    def _on_baseline_clicked(self):
        load_lvl = self.combo_carga.currentData()
        self.sig_baseline_requested.emit(load_lvl)

    def _toggle_recording(self):
        self._is_recording = not self._is_recording
        if self._is_recording:
            self.btn_record.setText("■ Detener Grabación")
            self.btn_record.setObjectName("btn_stop_record")
            self.lbl_record_status.setText("REC: Grabando...")
            self.lbl_record_status.setStyleSheet("color: #ef4444; font-weight: 700; font-size: 11px;")
        else:
            self.btn_record.setText("● Iniciar Grabación")
            self.btn_record.setObjectName("btn_record")
            self.lbl_record_status.setText("REC: Detenido")
            self.lbl_record_status.setStyleSheet("color: #64748b; font-size: 11px;")

        self.style().unpolish(self.btn_record)
        self.style().polish(self.btn_record)
        self.sig_record_toggled.emit(self._is_recording)

    def _on_ev_carga_clicked(self):
        load_name = self.combo_carga.currentText()
        load_lvl = self.combo_carga.currentData()
        self.sig_load_changed.emit(load_lvl)
        self.sig_event_button_clicked.emit("CAMBIO_CARGA", f"Carga cambiada a {load_name}")

    def _on_ev_falla_clicked(self):
        sev_class = self.combo_severidad.currentData()
        sev_name = self.combo_severidad.currentText()
        self.sig_fault_changed.emit(sev_class)
        self.sig_event_button_clicked.emit("INYECCION_FALLA", f"Falla ITF Inyectada: {sev_name}")
        # Enviar comando físico por serial al ESP32 para activar el SSR real
        cmd = str(sev_class)  # '1', '2' o '3'
        self.sig_command_requested.emit(cmd)

    def _on_ev_severidad_clicked(self):
        curr_idx = self.combo_severidad.currentIndex()
        next_idx = min(self.combo_severidad.count() - 1, curr_idx + 1)
        self.combo_severidad.setCurrentIndex(next_idx)
        sev_class = self.combo_severidad.currentData()
        sev_name = self.combo_severidad.currentText()
        self.sig_fault_changed.emit(sev_class)
        self.sig_event_button_clicked.emit("AUMENTO_SEVERIDAD", f"Severidad elevada a: {sev_name}")
        cmd = str(sev_class)
        self.sig_command_requested.emit(cmd)

    def _on_ev_sano_clicked(self):
        self.sig_fault_changed.emit(0)
        self.sig_event_button_clicked.emit("FALLA_OFF", "Falla ITF Retirada - Retorno a Sano")
        # Enviar '0' al ESP32 para abrir el SSR y retirar la falla
        self.sig_command_requested.emit("0")

    @Slot(int, int)
    def update_baseline_progress(self, current: int, total: int):
        self.progress_baseline.setMaximum(total)
        self.progress_baseline.setValue(current)
        if current >= total:
            self.btn_baseline.setText("✓ Baseline Capturado")
            self.btn_baseline.setEnabled(True)
        else:
            self.btn_baseline.setText(f"Capturando ({current}/{total})...")
            self.btn_baseline.setEnabled(False)

    @Slot(bool)
    def update_motor_state(self, is_on: bool):
        if is_on:
            self.lbl_motor_state.setText("● MOTOR ON")
            self.lbl_motor_state.setObjectName("lbl_motor_on")
        else:
            self.lbl_motor_state.setText("● MOTOR OFF")
            self.lbl_motor_state.setObjectName("lbl_motor_off")
        self.lbl_motor_state.style().unpolish(self.lbl_motor_state)
        self.lbl_motor_state.style().polish(self.lbl_motor_state)
