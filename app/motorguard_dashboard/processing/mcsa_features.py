"""
Módulo de cálculo matemático de alta velocidad para espectro MCSA y métricas de diagnóstico.
Alineado al 100% con la formulación matemática auditada en firmware C++ y scripts de tesis:
  - Ventana Hanning N=2400 con escala coherente física (Amperes pico).
  - Resolución espectral exacta Delta_f = 1.0 Hz (Fs = 2400 Hz).
  - Bandas espectrales auditadas para falla entre espiras (ITF): A_fund, A_55, A_65, A_50, A_70.
  - Ratios normalizados r_55, r_65, r_50, r_70, I_neg y THD.
  - Desbalance trifásico I_unb y factor de cresta por fase.
"""

import numpy as np
from typing import Tuple, Dict, Any, Optional
from motorguard_dashboard.core.config import (
    FS, WINDOW_SIZE, MAX_FREQ_HZ,
    BAND_FUNDAMENTAL, BAND_A55, BAND_A65, BAND_A50, BAND_A70
)
from motorguard_dashboard.core.data_types import WindowFeatures

# Precomputar ventana Hanning para N=2400 y factores de escala coherente
_HANN_WINDOW: np.ndarray = np.hanning(WINDOW_SIZE).astype(np.float32)
_HANN_COHERENT_GAIN: float = float(np.sum(_HANN_WINDOW))
_FFT_SCALE: float = 2.0 / _HANN_COHERENT_GAIN
_NUM_BINS_300HZ: int = int(MAX_FREQ_HZ) + 1  # 301 bins para 0 - 300 Hz a 1.0 Hz/bin
_FREQS_300HZ: np.ndarray = np.arange(_NUM_BINS_300HZ, dtype=np.float32)


def compute_peak_in_band(freqs: np.ndarray, mag: np.ndarray, f_min: float, f_max: float) -> Tuple[float, float]:
    """
    Obtiene la amplitud pico y la frecuencia correspondiente dentro de una banda [f_min, f_max].
    """
    idx_start = max(0, int(np.floor(f_min)))
    idx_end = min(len(mag), int(np.ceil(f_max)) + 1)
    
    if idx_start >= idx_end or idx_start >= len(mag):
        return 0.0, f_min
        
    band_slice = mag[idx_start:idx_end]
    if len(band_slice) == 0:
        return 0.0, f_min
        
    local_max_idx = int(np.argmax(band_slice))
    peak_amp = float(band_slice[local_max_idx])
    peak_freq = float(freqs[idx_start + local_max_idx])
    return peak_amp, peak_freq


def compute_spectrum(signal: np.ndarray) -> np.ndarray:
    """
    Calcula el espectro de amplitud pico (Amperes) con ventana Hanning de 0 a 300 Hz.
    signal: array 1D de longitud 2400
    Retorna: array 1D de longitud 301 (0 a 300 Hz con resolución 1.0 Hz)
    """
    assert len(signal) == WINDOW_SIZE, f"Señal debe tener {WINDOW_SIZE} muestras"
    # Remover componente de continua local antes del enventanado
    detrended = signal - np.mean(signal)
    windowed = detrended * _HANN_WINDOW
    
    # rfft entrega N/2 + 1 = 1201 bins con resolución 1.0 Hz
    fft_complex = np.fft.rfft(windowed)
    mag = np.abs(fft_complex[:_NUM_BINS_300HZ]) * _FFT_SCALE
    return mag.astype(np.float32)


def compute_window_features(
    currents: np.ndarray,
    voltages: np.ndarray,
    window_id: int,
    timestamp: float,
    sample_index: int,
    fs: float = FS,
    prev_motor_on: bool = True
) -> WindowFeatures:
    """
    Procesa un bloque de 2400 muestras continuas de 3 fases de corriente y 2 de voltaje.
    currents: shape (3, 2400) -> [Ia, Ib, Ic]
    voltages: shape (2, 2400) -> [Vab, Vbc]
    """
    assert currents.shape == (3, WINDOW_SIZE), f"currents shape incorrecta: {currents.shape}"
    assert voltages.shape[1] == WINDOW_SIZE, f"voltages shape incorrecta: {voltages.shape}"
    
    # 1. Métricas temporales por fase
    i_mean = np.mean(currents, axis=1)
    i_std = np.std(currents, axis=1)
    # RMS libre de continua (AC RMS)
    i_rms = np.sqrt(np.mean((currents - i_mean[:, None]) ** 2, axis=1))
    i_peak = np.max(np.abs(currents - i_mean[:, None]), axis=1)
    crest_factor = i_peak / np.maximum(i_rms, 1e-6)
    
    # Voltaje RMS promedio
    v_mean = np.mean(voltages, axis=1)
    v_rms_channels = np.sqrt(np.mean((voltages - v_mean[:, None]) ** 2, axis=1))
    v_rms = float(np.mean(v_rms_channels))
    
    # 2. Magnitud promedio e Índice de Desbalance Trifásico (I_unb)
    i_prom = float(np.mean(i_rms))
    if i_prom > 0.05:
        max_i_rms = float(np.max(i_rms))
        i_unb = ((max_i_rms - i_prom) / i_prom) * 100.0
    else:
        i_unb = 0.0
        
    # 3. Detección de Estado del Motor con Histéresis (Validada en Firmware C++)
    max_i_val = float(np.max(i_rms))
    max_v_val = float(np.max(v_rms_channels)) if len(v_rms_channels) > 0 else 0.0
    
    if prev_motor_on:
        motor_on = max_i_val > 0.8
    else:
        motor_on = (max_v_val > 60.0 and max_i_val > 1.5) or (max_i_val > 1.8)
        
    # 4. Espectros FFT (0 a 300 Hz) para las 3 fases
    fft_a = compute_spectrum(currents[0])
    fft_b = compute_spectrum(currents[1])
    fft_c = compute_spectrum(currents[2])  # Fase C monitoreada para ITF
    
    # 5. Extracción de Bandas MCSA sobre Fase C
    if not motor_on:
        a_fund = 0.0
        a_55 = 0.0
        a_65 = 0.0
        a_50 = 0.0
        a_70 = 0.0
        r_55 = 0.0
        r_65 = 0.0
        r_50 = 0.0
        r_70 = 0.0
        thd = 0.0
        i_neg = 0.0
    else:
        # Fundamental (alrededor de 60 Hz)
        a_fund, f0 = compute_peak_in_band(_FREQS_300HZ, fft_c, BAND_FUNDAMENTAL[0], BAND_FUNDAMENTAL[1])
        if a_fund < 1e-4:
            f0 = 60.0
            
        # Bandas laterales MCSA dependientes del slip/fundamental detectada
        # inferior: f0 - 10 a f0 - 4.8 Hz; superior: f0 + 4.8 a f0 + 10 Hz
        f55_min, f55_max = max(0.0, f0 - 10.0), max(0.0, f0 - 4.8)
        f65_min, f65_max = f0 + 4.8, min(300.0, f0 + 10.0)
        
        a_55, _ = compute_peak_in_band(_FREQS_300HZ, fft_c, f55_min, f55_max)
        a_65, _ = compute_peak_in_band(_FREQS_300HZ, fft_c, f65_min, f65_max)
        a_50, _ = compute_peak_in_band(_FREQS_300HZ, fft_c, BAND_A50[0], BAND_A50[1])
        a_70, _ = compute_peak_in_band(_FREQS_300HZ, fft_c, BAND_A70[0], BAND_A70[1])
        
        # Ratios relativos a la fundamental
        ref_a = max(a_fund, 1e-4)
        r_55 = a_55 / ref_a
        r_65 = a_65 / ref_a
        r_50 = a_50 / ref_a
        r_70 = a_70 / ref_a
        
        # Corriente de secuencia negativa estimada
        sum_sidebands = a_55 + a_65
        i_neg = abs(a_55 - a_65) / max(sum_sidebands, 1e-6)
        
        # THD sobre armónicos en 120, 180, 240, 300 Hz
        harmonics = [120.0, 180.0, 240.0, 300.0]
        harm_sum_sq = 0.0
        for h in harmonics:
            a_h, _ = compute_peak_in_band(_FREQS_300HZ, fft_c, h - 2.0, h + 2.0)
            harm_sum_sq += a_h ** 2
        thd = np.sqrt(harm_sum_sq) / ref_a

    return WindowFeatures(
        window_id=window_id,
        timestamp=timestamp,
        sample_index=sample_index,
        I_rms=i_rms.astype(np.float32),
        I_mean=i_mean.astype(np.float32),
        I_std=i_std.astype(np.float32),
        I_peak=i_peak.astype(np.float32),
        crest_factor=crest_factor.astype(np.float32),
        I_prom=i_prom,
        I_unb=float(i_unb),
        V_rms=v_rms,
        freqs=_FREQS_300HZ.copy(),
        fft_mag_A=fft_a,
        fft_mag_B=fft_b,
        fft_mag_C=fft_c,
        A_fund=float(a_fund),
        A_55=float(a_55),
        A_65=float(a_65),
        A_50=float(a_50),
        A_70=float(a_70),
        r_55=float(r_55),
        r_65=float(r_65),
        r_50=float(r_50),
        r_70=float(r_70),
        THD=float(thd),
        I_neg=float(i_neg),
        motor_on=motor_on
    )
