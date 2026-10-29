"""
Pruebas para BaselineManager: Captura de referencia sana, Z-score y persistencia JSON.
"""

import os
import tempfile
import time
import numpy as np
from motorguard_dashboard.core.config import FS, WINDOW_SIZE
from motorguard_dashboard.core.data_types import WindowFeatures
from motorguard_dashboard.processing.mcsa_features import compute_window_features
from motorguard_dashboard.processing.baseline_manager import BaselineManager

def generate_synthetic_window(win_id: int, is_fault: bool = False, load_base: float = 4.45) -> WindowFeatures:
    """Genera una ventana sintética con o sin falla ITF."""
    t = np.arange(WINDOW_SIZE) / FS
    w0 = 2.0 * np.pi * 60.0
    
    i_pk = load_base * np.sqrt(2.0)
    ia = i_pk * np.sin(w0 * t) + np.random.normal(0, 0.02, WINDOW_SIZE)
    ib = i_pk * np.sin(w0 * t - 2.0 * np.pi / 3.0) + np.random.normal(0, 0.02, WINDOW_SIZE)
    
    if not is_fault:
        ic = i_pk * np.sin(w0 * t + 2.0 * np.pi / 3.0) + np.random.normal(0, 0.02, WINDOW_SIZE)
    else:
        # Falla ITF: elevación de Ic (+15%) y componentes laterales A55 y A65
        w55 = 2.0 * np.pi * 55.0
        w65 = 2.0 * np.pi * 65.0
        ic = (i_pk * 1.15) * np.sin(w0 * t + 2.0 * np.pi / 3.0) + \
             0.15 * np.sin(w55 * t) + 0.35 * np.sin(w65 * t) + \
             np.random.normal(0, 0.02, WINDOW_SIZE)
             
    curr = np.vstack((ia, ib, ic)).astype(np.float32)
    volt = np.ones((2, WINDOW_SIZE), dtype=np.float32) * 123.0
    return compute_window_features(curr, volt, win_id, time.time(), win_id * 1200)

def test_baseline_capture_and_zscore():
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = os.path.join(tmpdir, "test_baselines.json")
        bm = BaselineManager(persistence_path=json_path)
        bm.set_active_load(0)
        
        # 1. Iniciar captura de 10 ventanas sanas
        bm.start_capture(load_level=0, target_windows=10)
        assert bm.is_capturing
        
        captured_signals = []
        bm.sig_baseline_captured.connect(lambda lvl, prof: captured_signals.append((lvl, prof)))
        
        for i in range(10):
            w = generate_synthetic_window(i, is_fault=False)
            bm.process_window(w)
            
        assert not bm.is_capturing
        assert len(captured_signals) == 1
        assert 0 in bm.profiles
        
        prof = bm.profiles[0]
        assert prof.mean_spectrum_C.shape == (301,)
        assert prof.means["I_unb"] < 2.0
        print("Captura de Baseline (10 ventanas) exitosa.")
        
        # 2. Evaluar ventana SANA -> Z-scores deben ser pequeños (|Z| < 2.0)
        w_sano = generate_synthetic_window(11, is_fault=False)
        metrics_sano = bm.process_window(w_sano)
        assert metrics_sano is not None
        
        for m in metrics_sano:
            if m.feature_name.startswith("I_unb"):
                print(f"Sano I_unb Z-score: {m.z_score:.2f} (Alert: {m.alert_level})")
                assert abs(m.z_score) < 3.0
                
        # 3. Evaluar ventana CON FALLA ITF -> Z-score debe dispararse (|Z| > 5.0)
        w_falla = generate_synthetic_window(12, is_fault=True)
        metrics_falla = bm.process_window(w_falla)
        assert metrics_falla is not None
        
        fault_detected = False
        for m in metrics_falla:
            if "A_65" in m.feature_name or "I_unb" in m.feature_name:
                print(f"Falla {m.feature_name} -> Delta: {m.delta_pct:+.1f}%, Z: {m.z_score:+.2f}, Alerta: {m.alert_level}")
                if m.alert_level == "FAULT":
                    fault_detected = True
                    
        assert fault_detected, "La inyección de falla debe detonar alerta FAULT (|Z| >= 5.0)"
        print("test_baseline_capture_and_zscore PASSED")

if __name__ == "__main__":
    test_baseline_capture_and_zscore()
