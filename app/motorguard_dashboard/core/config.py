"""
Constantes y configuraciones globales para la estación experimental MotorGuard-ITF.
Basado en las especificaciones validadas en auditoria_completa.md y el hardware del banco:
  - Motor ABB M1AA 145T-D4
  - Fs = 2400 Hz (ESP32-S3 Hardware Timer)
  - 3x ACS712-30A (Ia, Ib, Ic)
  - 2x ZMPT101B (Vab, Vbc)
  - SSR-25DA (Taps de falla 0.193 Ohm)
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple
import numpy as np

# ==================== PARÁMETROS DE MUESTREO Y FFT ====================
FS: float = 2400.0                   # Frecuencia de muestreo (Hz)
WINDOW_SIZE: int = 2400              # N = 2400 muestras (exactamente 1.0 s)
HOP_SIZE: int = 1200                 # Salto de 1200 muestras (overlap 50% -> 500 ms)
UPDATE_INTERVAL_MS: int = 500        # Período de actualización del procesador
DELTA_F: float = FS / WINDOW_SIZE    # Resolución espectral: 1.0 Hz exacto
MAX_FREQ_HZ: float = 300.0           # Rango visualizado de FFT: 0 - 300 Hz
RING_BUFFER_CAPACITY: int = 24000    # Capacidad del buffer circular: 10 segundos

# ==================== CANALES Y MAPEO DE HARDWARE ====================
CH_VA: int = 0
CH_VB: int = 1
CH_VC: int = 2
CH_IA: int = 3
CH_IB: int = 4
CH_IC: int = 5

NUM_CHANNELS: int = 6
NUM_CURRENT_CHANNELS: int = 3
NUM_VOLTAGE_CHANNELS: int = 2        # Vab, Vbc

# Factores de calibración validados en banco (auditoria_completa.md)
# Nota: CAL_V[1] = 0.5400 es correcto debido a la ganancia del potenciómetro de la Fase B
CAL_V: Tuple[float, float, float] = (1.8150, 0.5400, 2.2140)
CAL_I: Tuple[float, float, float] = (0.0166, 0.0174, 0.0195)

# Tensión y Corriente nominal del motor ABB M1AA 145T-D4
V_NOMINAL_RMS: float = 123.0         # Tensión monofásica fase-neutro o línea ajustada (V)
I_NOMINAL_RMS_NO_LOAD: float = 4.45  # Corriente en vacío nominal (A)
GRID_FREQ_HZ: float = 60.0           # Frecuencia de red fundamental

# ==================== BANDAS ESPECTRALES MCSA ====================
# Bandas auditadas para detección de falla entre espiras (ITF)
BAND_FUNDAMENTAL: Tuple[float, float] = (58.0, 62.0)
BAND_A55: Tuple[float, float] = (50.0, 55.2)    # Armónico lateral izquierdo
BAND_A65: Tuple[float, float] = (64.8, 70.0)    # Armónico lateral derecho
BAND_A50: Tuple[float, float] = (48.0, 52.0)    # Subarmónico
BAND_A70: Tuple[float, float] = (68.0, 72.0)    # Interarmónico superior

# ==================== NIVELES DE CARGA Y SEVERIDAD ====================
CARGAS: Dict[int, str] = {
    0: "L0 (0% - Vacío)",
    1: "L1 (25% - Baja)",
    2: "L2 (50% - Media)",
    3: "L3 (75% - Nominal)"
}

CLASES_FALLA: Dict[int, str] = {
    0: "SANO",
    1: "LEVE (Tap 1-2, ~5%)",
    2: "INTERMEDIA (Tap 2-4, ~10%)",
    3: "SEVERA (Tap 1-4, ~15%)"
}

# Columnas estándar auditadas para compatibilidad con datasets históricos
COLS_AUDITADAS: List[str] = [
    'clase', 'label', 'carga', 'carga_label', 'n_muestra', 'timestamp',
    'V_rms', 'I_rms', 'A_55', 'A_65', 'A_50', 'A_70', 'A_fund', 'I_neg', 'THD'
]

# Umbrales Z-score
Z_SCORE_NORMAL: float = 2.0
Z_SCORE_WARNING: float = 5.0
