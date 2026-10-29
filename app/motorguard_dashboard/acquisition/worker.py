"""
Worker de adquisición de hardware en tiempo real basado en PySide6.QThread.
Conexión automática y continua con el microcontrolador ESP32-S3 por cable USB.
Alimenta el NumPyRingBuffer de forma ininterrumpida a 2400 Hz (sin congelamientos)
y despacha comandos bidireccionales hacia los relevadores SSR.
"""

import time
import numpy as np
from PySide6.QtCore import QThread, Signal, Slot
from typing import Optional

from motorguard_dashboard.core.config import FS
from motorguard_dashboard.core.data_types import RawSampleChunk
from motorguard_dashboard.core.ring_buffer import NumPyRingBuffer
from motorguard_dashboard.acquisition.serial_source import SerialStreamReader
from motorguard_dashboard.acquisition.synthetic_emulator import SyntheticMotorEmulator

class AcquisitionWorker(QThread):
    """
    Hilo de adquisición continua desde hardware real ESP32-S3 o emulador sintético.
    """
    sig_hardware_connected = Signal(bool, str)  # (conectado, mensaje)
    sig_error = Signal(str)
    sig_data_ready = Signal(int)                # Total de muestras acumuladas
    sig_raw_chunk = Signal(object)              # RawSampleChunk para osciloscopio
    sig_telemetry_updated = Signal(dict)        # Diccionario de telemetría parseada

    def __init__(self, ring_buffer: NumPyRingBuffer, serial_port: Optional[str] = None, mode: str = "HARDWARE"):
        super().__init__()
        self.ring_buffer = ring_buffer
        self.mode = mode.upper()
        self._running = False
        
        self.reader = SerialStreamReader(port=serial_port, baudrate=115200)
        self.emulator = SyntheticMotorEmulator(fs=FS) if self.mode == "EMULATOR" else None
        self.chunk_size = 120                   # 120 muestras = 50 ms a 2400 Hz
        self.target_interval = self.chunk_size / FS  # 0.050 s
        self._was_connected = False

    def set_load(self, load_level: int):
        """Ajusta nivel de carga en modo emulador."""
        if self.emulator:
            self.emulator.set_load(load_level)

    def set_fault(self, fault_class: int):
        """Ajusta clase de severidad de falla en modo emulador."""
        if self.emulator:
            self.emulator.set_fault(fault_class)

    def send_command(self, cmd: str) -> bool:
        """Envía un comando al microcontrolador ESP32-S3 (ej: '1', '2', '3', '0')."""
        return self.reader.send_command(cmd)

    def set_port(self, port: str):
        """Asigna un puerto serie preferido."""
        self.reader.preferred_port = port
        if self.reader.is_connected() and self.reader.current_port != port:
            self.reader.disconnect()

    def stop(self):
        """Detiene de forma segura el bucle de adquisición."""
        self._running = False
        self.wait(1000)

    def run(self):
        """Bucle principal de adquisición en tiempo real a 2400 Hz."""
        self._running = True
        next_time = time.perf_counter()

        if self.mode == "EMULATOR":
            self.sig_hardware_connected.emit(True, "EMULADOR SINTÉTICO ACTIVO (ABB 145T-D4)")
            while self._running:
                chunk = self.emulator.generate_chunk(self.chunk_size)
                timestamps = np.linspace(
                    chunk.timestamp_start,
                    chunk.timestamp_start + self.target_interval,
                    self.chunk_size,
                    endpoint=False
                )
                total_samples = self.ring_buffer.push(chunk.currents, chunk.voltages, timestamps)
                self.sig_raw_chunk.emit(chunk)
                self.sig_data_ready.emit(total_samples)

                next_time += self.target_interval
                sleep_time = next_time - time.perf_counter()
                if sleep_time > 0.001:
                    time.sleep(sleep_time)
                elif sleep_time < -0.2:
                    next_time = time.perf_counter()
            self.sig_hardware_connected.emit(False, "Emulador detenido")
            return
        
        while self._running:
            # 1. Comprobar / auto-conectar con el hardware por cable USB
            is_conn = self.reader.is_connected()
            if not is_conn:
                is_conn = self.reader.connect()
                
            if is_conn != self._was_connected:
                self._was_connected = is_conn
                if is_conn:
                    self.sig_hardware_connected.emit(True, f"ESP32-S3 CONECTADO ({self.reader.current_port})")
                else:
                    self.sig_hardware_connected.emit(False, "Esperando cable USB ESP32-S3 (/dev/ttyACM*)...")

            # 2. Si está conectado, leer telemetría o muestras crudas
            if is_conn:
                has_data, tel = self.reader.read_telemetry_or_samples()
                if has_data and tel and "motor_on" in tel:
                    self.sig_telemetry_updated.emit(tel)

            # 3. Generar bloque continuo para el buffer circular (2400 Hz constantes)
            chunk = self.reader.generate_realtime_chunk(self.chunk_size)
            timestamps = np.linspace(
                chunk.timestamp_start,
                chunk.timestamp_start + self.target_interval,
                self.chunk_size,
                endpoint=False
            )

            # 4. Insertar en el RingBuffer
            total_samples = self.ring_buffer.push(chunk.currents, chunk.voltages, timestamps)

            # 5. Notificar a la interfaz y al procesador de ventana
            self.sig_raw_chunk.emit(chunk)
            self.sig_data_ready.emit(total_samples)

            # 6. Temporización isócrona para mantener exactamente 2400 Hz
            next_time += self.target_interval
            sleep_time = next_time - time.perf_counter()
            if sleep_time > 0.001:
                time.sleep(sleep_time)
            elif sleep_time < -0.2:
                next_time = time.perf_counter()

        self.reader.disconnect()
        self.sig_hardware_connected.emit(False, "Adquisición detenida")
