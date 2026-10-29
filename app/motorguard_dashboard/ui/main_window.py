"""
Ventana Principal de la Estación de Diagnóstico Experimental MotorGuard-ITF.
100% enfocada en Adquisición de Hardware en Tiempo Real por cable USB con el ESP32-S3.
Orquesta el AcquisitionWorker, el SlidingWindowProcessor y los 4 cuadrantes interactivos.
"""

import time
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QGridLayout, QStatusBar, QLabel
)
from PySide6.QtCore import Qt, Slot

from motorguard_dashboard.core.config import (
    FS, WINDOW_SIZE, HOP_SIZE, RING_BUFFER_CAPACITY, CARGAS
)
from motorguard_dashboard.core.data_types import WindowFeatures, BaselineProfile
from motorguard_dashboard.core.ring_buffer import NumPyRingBuffer
from motorguard_dashboard.core.events import EventRecorder

from motorguard_dashboard.acquisition.worker import AcquisitionWorker
from motorguard_dashboard.processing.sliding_window import SlidingWindowProcessor
from motorguard_dashboard.processing.baseline_manager import BaselineManager

from motorguard_dashboard.ui.widgets.control_panel import ControlPanel
from motorguard_dashboard.ui.widgets.temporal_scope import TemporalScopeWidget
from motorguard_dashboard.ui.widgets.spectral_viewer import SpectralViewerWidget
from motorguard_dashboard.ui.widgets.deviation_table import DeviationTableWidget
from motorguard_dashboard.ui.widgets.phase_trajectory import PhaseTrajectoryWidget

class MainWindow(QMainWindow):
    """
    Ventana principal de diagnóstico experimental en tiempo real con hardware ESP32-S3.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MotorGuard-ITF — Diagnóstico Experimental en Tiempo Real (ESP32-S3 MCSA)")
        self.resize(1500, 950)
        self.setMinimumSize(1100, 750)

        # 1. Instanciar núcleo de datos y gestores
        self.ring_buffer = NumPyRingBuffer(capacity=RING_BUFFER_CAPACITY)
        self.baseline_manager = BaselineManager()
        self.event_recorder = EventRecorder()

        # 2. Instanciar workers multihilo exclusivos para hardware real
        self.acq_worker = AcquisitionWorker(ring_buffer=self.ring_buffer)
        self.proc_worker = SlidingWindowProcessor(
            ring_buffer=self.ring_buffer,
            window_size=WINDOW_SIZE,
            hop_size=HOP_SIZE
        )

        # 3. Construir Interfaz Gráfica
        self._init_ui()

        # 4. Conectar señales y slots
        self._connect_signals()

        # 5. Cargar perfiles base existentes si los hay
        active_prof = self.baseline_manager.get_active_profile()
        if active_prof:
            self.spectral_viewer.set_reference_spectrum(active_prof)

        # 6. Iniciar hilos de adquisición y procesamiento en tiempo real
        self.acq_worker.start()
        self.proc_worker.start()

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # Panel Superior de Control de Hardware y Eventos
        self.control_panel = ControlPanel()
        main_layout.addWidget(self.control_panel)

        # Grid de los 4 Cuadrantes interactivos (2x2)
        grid_layout = QGridLayout()
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setSpacing(8)

        # Cuadrante 1: Osciloscopio Temporal (Ia, Ib, Ic en tiempo real)
        self.temporal_scope = TemporalScopeWidget(buffer_seconds=1.5, fs=FS)
        grid_layout.addWidget(self.temporal_scope, 0, 0)

        # Cuadrante 2: Espectro MCSA Superpuesto (Fase C vs Ref. Sana)
        self.spectral_viewer = SpectralViewerWidget()
        grid_layout.addWidget(self.spectral_viewer, 0, 1)

        # Cuadrante 3: Tabla de Diagnóstico y Z-Scores en vivo
        self.deviation_table = DeviationTableWidget()
        grid_layout.addWidget(self.deviation_table, 1, 0)

        # Cuadrante 4: Espacio de Estado Carga vs Asimetría ITF (I_prom vs I_unb)
        self.phase_trajectory = PhaseTrajectoryWidget(max_points=30)
        grid_layout.addWidget(self.phase_trajectory, 1, 1)

        # Proporciones equilibradas 50% / 50%
        grid_layout.setRowStretch(0, 1)
        grid_layout.setRowStretch(1, 1)
        grid_layout.setColumnStretch(0, 1)
        grid_layout.setColumnStretch(1, 1)

        main_layout.addLayout(grid_layout)

        # Barra de Estado (Status Bar)
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.lbl_status_hw = QLabel("Hardware: Auto-detectando...")
        self.lbl_status_samples = QLabel("Muestras: 0")
        self.lbl_status_session = QLabel("Sesión: Inactiva")
        self.lbl_status_fps = QLabel("Fs: 2400 Hz | Ventana: 500 ms")

        self.status_bar.addWidget(self.lbl_status_hw, 1)
        self.status_bar.addWidget(self.lbl_status_samples, 1)
        self.status_bar.addWidget(self.lbl_status_fps, 1)
        self.status_bar.addPermanentWidget(self.lbl_status_session)

    def _connect_signals(self):
        """Conecta todas las señales y slots del sistema en tiempo real."""
        # 1. Adquisición continua hacia Cuadrante 1 y Procesador de Ventana
        self.acq_worker.sig_raw_chunk.connect(self.temporal_scope.update_chunk)
        self.acq_worker.sig_data_ready.connect(self.proc_worker.on_samples_accumulated)
        self.acq_worker.sig_hardware_connected.connect(self._on_hardware_status_changed)
        self.acq_worker.sig_error.connect(self._on_acq_error)

        # 2. Ventana procesada hacia Cuadrantes 2, 3, 4, Baseline y Grabador CSV
        self.proc_worker.sig_window_processed.connect(self._on_window_processed)
        self.proc_worker.sig_motor_state_changed.connect(self.control_panel.update_motor_state)

        # 3. Gestor de Baseline hacia Cuadrantes y Panel de Control
        self.baseline_manager.sig_baseline_captured.connect(self._on_baseline_captured)
        self.baseline_manager.sig_baseline_progress.connect(self.control_panel.update_baseline_progress)
        self.baseline_manager.sig_deviations_computed.connect(self.deviation_table.update_metrics)

        # 4. Panel de Control hacia Workers, Hardware y Event Recorder
        self.control_panel.sig_reconnect_requested.connect(lambda: self.acq_worker.set_port(None))
        self.control_panel.sig_load_changed.connect(self._on_load_changed)
        self.control_panel.sig_baseline_requested.connect(self.baseline_manager.start_capture)
        self.control_panel.sig_record_toggled.connect(self._on_record_toggled)
        self.control_panel.sig_event_button_clicked.connect(self._on_event_button_clicked)
        # Despachar comandos hacia los relevadores SSR en el ESP32 real
        self.control_panel.sig_command_requested.connect(self.acq_worker.send_command)

    @Slot(bool, str)
    def _on_hardware_status_changed(self, connected: bool, message: str):
        """Actualiza el badge de hardware en el panel y en la barra de estado."""
        self.control_panel.update_hardware_status(connected, message)
        self.lbl_status_hw.setText(f"Hardware: {message}")
        if connected:
            self.status_bar.showMessage(f"✓ Conexión establecida con microcontrolador: {message}", 5000)
        else:
            self.status_bar.showMessage(f"⚠️ {message}", 4000)

    @Slot(object)
    def _on_window_processed(self, feat: WindowFeatures):
        """Distribuye la ventana de features calculadas a los 4 cuadrantes y al logger."""
        # Cuadrante 2: Actualizar Espectro
        self.spectral_viewer.update_spectrum(feat)

        # Cuadrante 4: Actualizar Plano de Fase
        self.phase_trajectory.update_point(feat.I_prom, feat.I_unb)

        # Cuadrante 3: Calcular y emitir residuos contra el baseline activo
        deviations = self.baseline_manager.process_window(feat)

        # Grabación a CSV si la sesión está activa
        if self.event_recorder.is_recording:
            self.event_recorder.record_features(feat, deviations)

        # Actualizar Status Bar
        self.lbl_status_samples.setText(f"Muestras: {feat.sample_index:,}")

    @Slot(int, object)
    def _on_baseline_captured(self, load_level: int, profile: BaselineProfile):
        """Maneja el fin de captura de baseline."""
        self.spectral_viewer.set_reference_spectrum(profile)
        load_name = CARGAS.get(load_level, f"L{load_level}")
        self.status_bar.showMessage(f"✓ Referencia sana para {load_name} capturada exitosamente", 4000)

    @Slot(int)
    def _on_load_changed(self, load_level: int):
        """Conmuta la referencia sana activa para el nivel de carga actual."""
        self.baseline_manager.set_active_load(load_level)
        prof = self.baseline_manager.get_active_profile()
        if prof:
            self.spectral_viewer.set_reference_spectrum(prof)
        else:
            self.spectral_viewer.curve_ref.clear()

    @Slot(str, str)
    def _on_event_button_clicked(self, event_type: str, description: str):
        """Añade marca visual en el osciloscopio y registra evento sincronizado en CSV."""
        self.temporal_scope.add_event_marker(event_type)
        current_sample = self.ring_buffer._total_samples
        self.event_recorder.record_event(
            event_type=event_type,
            description=description,
            sample_index=current_sample
        )
        self.status_bar.showMessage(f"Marca de evento: [{event_type}] - {description}", 3000)

    @Slot(bool)
    def _on_record_toggled(self, is_recording: bool):
        """Inicia o detiene la sesión de grabación a CSV."""
        if is_recording:
            csv_path = self.event_recorder.start_session()
            self.lbl_status_session.setText(f"REC: {csv_path.split('/')[-1]}")
            self.lbl_status_session.setStyleSheet("color: #ef4444; font-weight: 700;")
        else:
            saved_path = self.event_recorder.stop_session()
            self.lbl_status_session.setText("Sesión: Detenida")
            self.lbl_status_session.setStyleSheet("color: #94a3b8;")
            if saved_path:
                self.status_bar.showMessage(f"Sesión guardada en: {saved_path}", 5000)

    @Slot(str)
    def _on_acq_error(self, err_msg: str):
        self.status_bar.showMessage(f"⚠️ {err_msg}", 6000)

    def closeEvent(self, event):
        """Cierre ordenado de hilos y archivos."""
        print("[INFO] Cerrando hilos de adquisición y procesamiento...")
        self.acq_worker.stop()
        self.proc_worker.stop()
        if self.event_recorder.is_recording:
            self.event_recorder.stop_session()
        event.accept()
