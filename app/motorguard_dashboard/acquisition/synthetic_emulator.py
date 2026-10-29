"""
Emulador sintético de alta fidelidad para el motor de inducción ABB M1AA 145T-D4.
Modela fielmente la física de corriente trifásica balanceada, variación de carga y
la aparición de asimetrías y componentes armónicas MCSA ante fallas entre espiras (ITF).
Calibrado según los datos experimentales validados en auditoria_completa.md.
"""

import time
import numpy as np
from typing import Tuple, Optional
from motorguard_dashboard.core.config import (
    FS, GRID_FREQ_HZ, V_NOMINAL_RMS, I_NOMINAL_RMS_NO_LOAD
)
from motorguard_dashboard.core.data_types import RawSampleChunk

class SyntheticMotorEmulator:
    """
    Generador de señales sintéticas a 2400 Hz que reproduce la física del banco:
      - Carga pura: incremento simétrico en las 3 fases (Ia, Ib, Ic suben por igual).
      - Falla ITF en Fase C: asimetría en Ic, aumento drástico de bandas laterales (55 Hz y 65 Hz)
        y elevación del índice de desbalance I_unb.
    """
    def __init__(self, fs: float = FS):
        self.fs = fs
        self.current_sample_idx = 0
        self.load_level = 0    # 0: L0 (0%), 1: L1 (25%), 2: L2 (50%), 3: L3 (75%)
        self.fault_class = 0   # 0: SANO, 1: LEVE, 2: INTER, 3: SEVERA
        
        # Corrientes RMS según nivel de carga para motor ABB M1AA 145T-D4
        self._load_currents = {
            0: 4.45,   # 0% (Vacío)
            1: 4.95,   # 25% (Baja)
            2: 5.60,   # 50% (Media)
            3: 6.40    # 75% (Nominal)
        }
        
        # Desfase angular trifásico estándar (-120° y +120°)
        self._phi_a = 0.0
        self._phi_b = -2.0 * np.pi / 3.0
        self._phi_c = 2.0 * np.pi / 3.0
        
        # Factor de potencia (desfase corriente-voltaje)
        self._pf_angle = -0.55  # ~cos(phi)=0.85 inductivo

    def set_load(self, load_level: int):
        """Modifica el nivel de carga (0 a 3)."""
        self.load_level = max(0, min(3, load_level))

    def set_fault(self, fault_class: int):
        """Modifica la severidad de falla ITF en la Fase C (0 a 3)."""
        self.fault_class = max(0, min(3, fault_class))

    def generate_chunk(self, num_samples: int) -> RawSampleChunk:
        """
        Genera un bloque de muestras continuas manteniendo coherencia de fase temporal.
        Retorna un objeto RawSampleChunk.
        """
        t_start = time.time()
        n = np.arange(self.current_sample_idx, self.current_sample_idx + num_samples, dtype=np.float64)
        t = n / self.fs
        w0 = 2.0 * np.pi * GRID_FREQ_HZ
        
        # 1. Tensión de red trifásica (Vab, Vbc)
        v_peak = np.sqrt(2.0) * V_NOMINAL_RMS
        v_ab = v_peak * np.sin(w0 * t)
        v_bc = v_peak * np.sin(w0 * t - 2.0 * np.pi / 3.0)
        voltages = np.vstack((v_ab, v_bc)).astype(np.float32)
        
        # 2. Corrientes base según nivel de carga
        base_rms = self._load_currents[self.load_level]
        i_peak = np.sqrt(2.0) * base_rms
        
        ia = i_peak * np.sin(w0 * t + self._phi_a + self._pf_angle)
        ib = i_peak * np.sin(w0 * t + self._phi_b + self._pf_angle)
        ic = i_peak * np.sin(w0 * t + self._phi_c + self._pf_angle)
        
        # 3. Modelado de Falla entre Espiras (ITF) en Fase C
        # Auditado: en SANO A55=47.0, A65=55.6 (en cuentas/mV); en LEVE A55=+116%, A65=+243%
        # Modelamos en Amperes físicos equivalentes
        noise_level = 0.04  # Ruido blanco gaussiano de 40 mA
        
        if self.fault_class == 0:
            # SANO: pequeñas componentes naturales de ranura y ruido equilibrado
            w_55 = 2.0 * np.pi * 55.0
            w_65 = 2.0 * np.pi * 65.0
            # Nivel base natural de armónicos laterales (muy bajo)
            a55_base = 0.035
            a65_base = 0.040
            ic += a55_base * np.sin(w_55 * t) + a65_base * np.sin(w_65 * t)
        else:
            # Escalado de severidad: 1=LEVE, 2=INTER, 3=SEVERA
            mult = 1.0 if self.fault_class == 1 else (2.2 if self.fault_class == 2 else 4.0)
            
            # Asimetría en amplitud en la fase con falla (Fase C)
            ic_boost = (0.08 * mult) * i_peak
            ic += ic_boost * np.sin(w0 * t + self._phi_c + self._pf_angle)
            
            # Armónicos laterales de falla MCSA (55 Hz y 65 Hz)
            # En auditoría: A65 crece +243% y A55 crece +116%
            w_55 = 2.0 * np.pi * 55.0
            w_65 = 2.0 * np.pi * 65.0
            w_50 = 2.0 * np.pi * 50.0
            w_70 = 2.0 * np.pi * 70.0
            
            a55_fault = (0.035 + 0.045 * mult)
            a65_fault = (0.040 + 0.100 * mult)
            a50_fault = (0.020 + 0.025 * mult)
            a70_fault = (0.020 + 0.030 * mult)
            
            ic += a55_fault * np.sin(w_55 * t + 0.3)
            ic += a65_fault * np.sin(w_65 * t - 0.5)
            ic += a50_fault * np.sin(w_50 * t + 0.1)
            ic += a70_fault * np.sin(w_70 * t - 0.2)
            
            # Ligera inducción cruzada en fases A y B por desbalance de estator
            ia += 0.02 * mult * np.sin(w_55 * t)
            ib += 0.02 * mult * np.sin(w_65 * t)
            
        # 4. Inyección de ruido de medición gaussiano
        ia += np.random.normal(0, noise_level, num_samples)
        ib += np.random.normal(0, noise_level, num_samples)
        ic += np.random.normal(0, noise_level, num_samples)
        
        currents = np.vstack((ia, ib, ic)).astype(np.float32)
        sample_indices = n.astype(np.uint64)
        
        self.current_sample_idx += num_samples
        
        return RawSampleChunk(
            timestamp_start=t_start,
            sample_indices=sample_indices,
            currents=currents,
            voltages=voltages
        )
