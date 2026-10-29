"""
Buffer circular multicanal de alto rendimiento optimizado con NumPy.
Diseñado para retener las últimas N muestras continuas sin reubicaciones costosas de memoria.
"""

import threading
import numpy as np
from typing import Tuple, Optional

class NumPyRingBuffer:
    """
    Buffer circular seguro para subprocesos (thread-safe) para señales continuas multicanal.
    Almacena 3 canales de corriente [Ia, Ib, Ic] y 2 canales de voltaje [Vab, Vbc].
    """
    def __init__(self, capacity: int = 24000, num_current_channels: int = 3, num_voltage_channels: int = 2):
        self.capacity = capacity
        self.num_i = num_current_channels
        self.num_v = num_voltage_channels
        
        # Buffers circulares contiguos en memoria
        self._current_buffer = np.zeros((self.num_i, capacity), dtype=np.float32)
        self._voltage_buffer = np.zeros((self.num_v, capacity), dtype=np.float32)
        self._timestamps = np.zeros(capacity, dtype=np.float64)
        
        self._write_pos = 0
        self._total_samples = 0
        self._lock = threading.Lock()

    def push(self, currents: np.ndarray, voltages: np.ndarray, timestamps: Optional[np.ndarray] = None) -> int:
        """
        Inserta un bloque de muestras en el buffer circular.
        currents: np.ndarray shape (3, M)
        voltages: np.ndarray shape (2, M)
        timestamps: np.ndarray shape (M,) opcional
        Retorna el número total de muestras acumuladas hasta el momento.
        """
        assert currents.shape[0] == self.num_i, f"Corrientes deben tener forma ({self.num_i}, M)"
        assert voltages.shape[0] == self.num_v, f"Voltajes deben tener forma ({self.num_v}, M)"
        
        m = currents.shape[1]
        if m == 0:
            return self._total_samples

        with self._lock:
            if m >= self.capacity:
                # Si el bloque entrante excede la capacidad, solo guardamos las últimas 'capacity' muestras
                currents = currents[:, -self.capacity:]
                voltages = voltages[:, -self.capacity:]
                if timestamps is not None:
                    timestamps = timestamps[-self.capacity:]
                m = self.capacity
                self._current_buffer[:, :] = currents
                self._voltage_buffer[:, :] = voltages
                if timestamps is not None:
                    self._timestamps[:] = timestamps
                self._write_pos = 0
            else:
                end_pos = self._write_pos + m
                if end_pos <= self.capacity:
                    # Sin envoltura (wrap-around)
                    self._current_buffer[:, self._write_pos:end_pos] = currents
                    self._voltage_buffer[:, self._write_pos:end_pos] = voltages
                    if timestamps is not None:
                        self._timestamps[self._write_pos:end_pos] = timestamps
                    self._write_pos = end_pos % self.capacity
                else:
                    # Envoltura en el límite circular
                    first_part = self.capacity - self._write_pos
                    second_part = m - first_part
                    
                    self._current_buffer[:, self._write_pos:] = currents[:, :first_part]
                    self._current_buffer[:, :second_part] = currents[:, first_part:]
                    
                    self._voltage_buffer[:, self._write_pos:] = voltages[:, :first_part]
                    self._voltage_buffer[:, :second_part] = voltages[:, first_part:]
                    
                    if timestamps is not None:
                        self._timestamps[self._write_pos:] = timestamps[:first_part]
                        self._timestamps[:second_part] = timestamps[first_part:]
                    
                    self._write_pos = second_part

            self._total_samples += m
            return self._total_samples

    def is_ready(self, window_size: int) -> bool:
        """Verifica si se han acumulado suficientes muestras para una ventana completa."""
        return self._total_samples >= window_size

    def get_latest_window(self, window_size: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray, int]:
        """
        Extrae las últimas 'window_size' muestras ordenadas cronológicamente.
        Retorna:
          currents: (3, window_size)
          voltages: (2, window_size)
          timestamps: (window_size,)
          end_sample_index: int (índice absoluto de la última muestra)
        """
        assert window_size <= self.capacity, f"Tamaño de ventana ({window_size}) supera capacidad ({self.capacity})"
        
        with self._lock:
            if self._total_samples < window_size:
                raise ValueError(f"Muestras insuficientes ({self._total_samples} < {window_size})")

            end_idx = self._total_samples
            w_pos = self._write_pos
            start_pos = (w_pos - window_size) % self.capacity
            
            if start_pos < w_pos:
                # Contiguo sin split
                curr = self._current_buffer[:, start_pos:w_pos].copy()
                volt = self._voltage_buffer[:, start_pos:w_pos].copy()
                t = self._timestamps[start_pos:w_pos].copy()
            else:
                # Split a través del límite del buffer
                curr = np.hstack((self._current_buffer[:, start_pos:], self._current_buffer[:, :w_pos]))
                volt = np.hstack((self._voltage_buffer[:, start_pos:], self._voltage_buffer[:, :w_pos]))
                t = np.concatenate((self._timestamps[start_pos:], self._timestamps[:w_pos]))
                
            return curr, volt, t, end_idx

    def clear(self):
        """Reinicia el buffer circular a ceros."""
        with self._lock:
            self._current_buffer.fill(0)
            self._voltage_buffer.fill(0)
            self._timestamps.fill(0)
            self._write_pos = 0
            self._total_samples = 0
