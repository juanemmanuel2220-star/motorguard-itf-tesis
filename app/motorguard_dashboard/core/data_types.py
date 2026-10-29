"""
Definición de estructuras de datos y contratos de tipado para la estación MotorGuard-ITF.
"""

from dataclasses import dataclass, field
import numpy as np
from typing import Dict, Optional, List

@dataclass(frozen=True)
class RawSampleChunk:
    """Lote de muestras continuas entregadas por el AcquisitionWorker."""
    timestamp_start: float      # Timestamp Unix de inicio del bloque
    sample_indices: np.ndarray  # Índices continuos enteros uint64
    currents: np.ndarray        # Forma (3, M) -> [Ia, Ib, Ic] en Amperes calibrados
    voltages: np.ndarray        # Forma (2, M) -> [Vab, Vbc] en Volts calibrados

@dataclass
class WindowFeatures:
    """Métricas y espectro calculados sobre una ventana de N=2400 muestras."""
    window_id: int
    timestamp: float
    sample_index: int
    
    # Temporales por fase (A, B, C)
    I_rms: np.ndarray           # np.ndarray shape (3,) -> [Ia, Ib, Ic]
    I_mean: np.ndarray          # np.ndarray shape (3,) -> componentes de continua / deriva
    I_std: np.ndarray           # np.ndarray shape (3,)
    I_peak: np.ndarray          # np.ndarray shape (3,)
    crest_factor: np.ndarray    # np.ndarray shape (3,) -> I_peak / I_rms
    
    # Imbalance y Magnitudes Globales
    I_prom: float               # Promedio RMS de las 3 fases
    I_unb: float                # ((max(I_rms) - I_prom) / I_prom) * 100.0
    V_rms: float                # Tensión RMS estimada
    
    # Espectro MCSA (Resolución 1.0 Hz, rango 0 a 300 Hz)
    freqs: np.ndarray           # Array [0, 1, 2, ..., 300] Hz
    fft_mag_A: np.ndarray       # Magnitud pico de fase A (shape 301,)
    fft_mag_B: np.ndarray       # Magnitud pico de fase B (shape 301,)
    fft_mag_C: np.ndarray       # Magnitud pico de fase C (shape 301,) - monitoreada ITF
    
    # Features MCSA Auditadas
    A_fund: float               # Amplitud fundamental (alrededor de 60 Hz)
    A_55: float                 # Armónico lateral izquierdo [50.0, 55.2] Hz
    A_65: float                 # Armónico lateral derecho [64.8, 70.0] Hz
    A_50: float                 # Interarmónico 50 Hz
    A_70: float                 # Interarmónico 70 Hz
    r_55: float                 # A_55 / A_fund
    r_65: float                 # A_65 / A_fund
    r_50: float                 # A_50 / A_fund
    r_70: float                 # A_70 / A_fund
    THD: float                  # Distorsión armónica total (%)
    I_neg: float                # Estimación de corriente de secuencia negativa
    motor_on: bool = True       # Estado del motor (histéresis de corriente/voltaje)

@dataclass
class DeviationMetrics:
    """Métrica de desviación estadística respecto a la referencia sana activa."""
    feature_name: str
    current_value: float
    ref_mean: float
    ref_std: float
    delta_abs: float
    delta_pct: float
    z_score: float
    alert_level: str            # 'NORMAL', 'WARNING', 'FAULT'

@dataclass
class BaselineProfile:
    """Perfil estadístico de referencia sana capturado durante 5 segundos."""
    load_level: int             # 0 (L0), 1 (L1), 2 (L2), 3 (L3)
    load_label: str
    capture_timestamp: float
    num_windows: int
    means: Dict[str, float]     # Media de cada feature en las 10 ventanas
    stds: Dict[str, float]      # Desviación estándar de cada feature
    mean_spectrum_C: np.ndarray # Espectro medio de fase C (0 a 300 Hz) para superposición

@dataclass
class ExperimentalEvent:
    """Marca de evento en la secuencia experimental."""
    event_id: int
    timestamp: float
    sample_index: int
    event_type: str             # 'CAMBIO_CARGA', 'INYECCION_FALLA', 'MODIF_SEVERIDAD', 'FALLA_OFF'
    description: str
    load_level: int
    fault_class: int
