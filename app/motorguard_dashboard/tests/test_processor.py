"""
Pruebas matemáticas y de rendimiento para mcsa_features.py.
"""

import time
import numpy as np
from motorguard_dashboard.core.config import FS, WINDOW_SIZE
from motorguard_dashboard.processing.mcsa_features import (
    compute_window_features, compute_spectrum, compute_peak_in_band
)

def test_pure_sinusoid_fft_accuracy():
    """Valida la resolución espectral de 1.0 Hz y la escala coherente en amplitud física."""
    t = np.arange(WINDOW_SIZE) / FS
    amp_peak = 5.0
    f0 = 60.0
    signal = amp_peak * np.sin(2.0 * np.pi * f0 * t)
    
    spec = compute_spectrum(signal)
    freqs = np.arange(len(spec))
    
    peak_val, peak_freq = compute_peak_in_band(freqs, spec, 58.0, 62.0)
    assert peak_freq == 60.0, f"Frecuencia fundamental errónea: {peak_freq}"
    assert abs(peak_val - amp_peak) < 0.15, f"Error de amplitud: {peak_val} vs {amp_peak}"
    print(f"test_pure_sinusoid_fft_accuracy PASSED (f={peak_freq} Hz, amp={peak_val:.3f} A)")

def test_three_phase_unbalance():
    """Valida el cálculo del índice de desbalance trifásico I_unb."""
    t = np.arange(WINDOW_SIZE) / FS
    w0 = 2.0 * np.pi * 60.0
    
    # Tres fases equilibradas a 4.45 A RMS (pico = 4.45 * sqrt(2))
    base_rms = 4.45
    i_pk = base_rms * np.sqrt(2.0)
    ia = i_pk * np.sin(w0 * t)
    ib = i_pk * np.sin(w0 * t - 2.0 * np.pi / 3.0)
    ic = i_pk * np.sin(w0 * t + 2.0 * np.pi / 3.0)
    curr_balanced = np.vstack((ia, ib, ic))
    volt = np.zeros((2, WINDOW_SIZE), dtype=np.float32)
    
    feat_bal = compute_window_features(curr_balanced, volt, 0, time.time(), 0)
    assert feat_bal.I_unb < 0.1, f"Desbalance en sano balanceado debe ser ~0, dio {feat_bal.I_unb}"
    assert abs(feat_bal.I_prom - base_rms) < 0.05
    
    # Fase C con 20% más corriente (simulación de asimetría)
    ic_fault = (i_pk * 1.25) * np.sin(w0 * t + 2.0 * np.pi / 3.0)
    curr_unbal = np.vstack((ia, ib, ic_fault))
    feat_unbal = compute_window_features(curr_unbal, volt, 1, time.time(), 0)
    
    # Esperado: Ia=4.45, Ib=4.45, Ic=5.56 -> I_prom=4.82 -> I_unb = (5.56 - 4.82)/4.82 * 100 = 15.3%
    assert feat_unbal.I_unb > 10.0, f"Desbalance esperado > 10%, dio {feat_unbal.I_unb:.2f}%"
    print(f"test_three_phase_unbalance PASSED (I_unb sano: {feat_bal.I_unb:.2f}%, desbalanceado: {feat_unbal.I_unb:.2f}%)")

def test_mcsa_sidebands_detection():
    """Valida la extracción de los armónicos laterales de falla A55 y A65."""
    t = np.arange(WINDOW_SIZE) / FS
    w0 = 2.0 * np.pi * 60.0
    w55 = 2.0 * np.pi * 55.0
    w65 = 2.0 * np.pi * 65.0
    
    ia = 5.0 * np.sin(w0 * t)
    ib = 5.0 * np.sin(w0 * t - 2.0 * np.pi / 3.0)
    # Ic contiene fundamental + componentes MCSA
    ic = 5.0 * np.sin(w0 * t + 2.0 * np.pi / 3.0) + 0.25 * np.sin(w55 * t) + 0.40 * np.sin(w65 * t)
    curr = np.vstack((ia, ib, ic))
    volt = np.ones((2, WINDOW_SIZE), dtype=np.float32) * 123.0
    
    feat = compute_window_features(curr, volt, 0, time.time(), 0)
    assert abs(feat.A_55 - 0.25) < 0.05, f"A_55 esperado ~0.25, dio {feat.A_55:.3f}"
    assert abs(feat.A_65 - 0.40) < 0.05, f"A_65 esperado ~0.40, dio {feat.A_65:.3f}"
    assert feat.r_65 > feat.r_55
    assert feat.I_neg > 0.15
    print(f"test_mcsa_sidebands_detection PASSED (A55={feat.A_55:.3f}A, A65={feat.A_65:.3f}A, r65={feat.r_65:.4f})")

def test_computation_latency():
    """Verifica que el procesamiento de ventana completa N=2400 tome menos de 3.0 ms."""
    curr = np.random.randn(3, WINDOW_SIZE).astype(np.float32)
    volt = np.random.randn(2, WINDOW_SIZE).astype(np.float32)
    
    # Warmup
    _ = compute_window_features(curr, volt, 0, time.time(), 0)
    
    iterations = 50
    t0 = time.perf_counter()
    for i in range(iterations):
        _ = compute_window_features(curr, volt, i, time.time(), i * 1200)
    elapsed = time.perf_counter() - t0
    avg_ms = (elapsed / iterations) * 1000.0
    print(f"test_computation_latency PASSED: Promedio {avg_ms:.2f} ms por ventana (Límite: 3.0 ms)")
    assert avg_ms < 3.0, f"Demasiado lento: {avg_ms:.2f} ms"

if __name__ == "__main__":
    test_pure_sinusoid_fft_accuracy()
    test_three_phase_unbalance()
    test_mcsa_sidebands_detection()
    test_computation_latency()
