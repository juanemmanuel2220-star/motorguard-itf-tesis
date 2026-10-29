"""
Procesador de ventana rodante N=2400 (1.0 s) con solapamiento del 50% (actualización cada 500 ms).
Opera en un hilo QThread independiente para desacoplar el procesamiento intensivo de la UI.
"""

import time
import threading
import numpy as np
from PySide6.QtCore import QThread, Signal, Slot
from typing import Optional

from motorguard_dashboard.core.config import WINDOW_SIZE, HOP_SIZE, FS
from motorguard_dashboard.core.data_types import WindowFeatures
from motorguard_dashboard.core.ring_buffer import NumPyRingBuffer
from motorguard_dashboard.processing.mcsa_features import compute_window_features

class SlidingWindowProcessor(QThread):
    """
    Hilo consumidor del RingBuffer.
    Genera un objeto WindowFeatures cada HOP_SIZE = 1200 muestras (500 ms a 2400 Hz).
    """
    sig_window_processed = Signal(object)      # Emite WindowFeatures
    sig_motor_state_changed = Signal(bool)    # Emite estado del motor ON/OFF

    def __init__(
        self,
        ring_buffer: NumPyRingBuffer,
        window_size: int = WINDOW_SIZE,
        hop_size: int = HOP_SIZE
    ):
        super().__init__()
        self.ring_buffer = ring_buffer
        self.window_size = window_size
        self.hop_size = hop_size
        
        self._running = False
        self._last_processed_idx = 0
        self._window_counter = 0
        self._motor_on = False
        self._wake_event = threading.Event()

    def stop(self):
        """Detiene de forma segura el bucle de procesamiento."""
        self._running = False
        self._wake_event.set()
        self.wait(1000)

    @Slot(int)
    def on_samples_accumulated(self, total_samples: int):
        """Slot llamado cuando AcquisitionWorker inserta nuevas muestras."""
        if total_samples - self._last_processed_idx >= self.hop_size:
            self._wake_event.set()

    def run(self):
        """Bucle principal de procesamiento de ventanas."""
        self._running = True
        
        while self._running:
            # Esperar a que lleguen suficientes muestras (con timeout de seguridad de 50 ms)
            self._wake_event.wait(timeout=0.05)
            self._wake_event.clear()
            
            if not self._running:
                break
                
            # Verificar si hay una ventana completa y ha transcurrido un salto de hop_size
            current_total = self.ring_buffer._total_samples
            if not self.ring_buffer.is_ready(self.window_size):
                continue
                
            if current_total - self._last_processed_idx < self.hop_size:
                continue

            try:
                # 1. Extraer ventana más reciente
                curr, volt, t_stamps, end_idx = self.ring_buffer.get_latest_window(self.window_size)
                now_t = float(t_stamps[-1]) if len(t_stamps) > 0 and t_stamps[-1] > 0 else time.time()
                
                # 2. Calcular features y espectro
                feat = compute_window_features(
                    currents=curr,
                    voltages=volt,
                    window_id=self._window_counter,
                    timestamp=now_t,
                    sample_index=end_idx,
                    prev_motor_on=self._motor_on
                )
                
                # 3. Notificar cambios de estado del motor
                if feat.motor_on != self._motor_on:
                    self._motor_on = feat.motor_on
                    self.sig_motor_state_changed.emit(self._motor_on)
                    
                # 4. Emitir features calculadas
                self.sig_window_processed.emit(feat)
                
                self._last_processed_idx = end_idx
                self._window_counter += 1
                
            except Exception as e:
                # Evitar que una excepción mate el hilo del procesador
                print(f"[ERROR] SlidingWindowProcessor: {e}")
