"""
Gestor de perfiles de referencia sanos multi-carga (BaselineManager).
Permite capturar 5 s (10 ventanas consecutivas) en régimen sano estable para L0, L1, L2, L3,
y evalúa en vivo las desviaciones absolutas, porcentuales y puntuación normalizada Z-score.
"""

import os
import json
import numpy as np
from typing import Dict, List, Optional
from PySide6.QtCore import QObject, Signal, Slot

from motorguard_dashboard.core.config import (
    CARGAS, Z_SCORE_NORMAL, Z_SCORE_WARNING
)
from motorguard_dashboard.core.data_types import (
    WindowFeatures, BaselineProfile, DeviationMetrics
)

# Claves de features monitoreadas para cálculo de desviaciones
TRACKED_FEATURES = [
    ("I_unb", "I_unb (%)", lambda f: f.I_unb),
    ("A_65", "A_65 (A)", lambda f: f.A_65),
    ("A_55", "A_55 (A)", lambda f: f.A_55),
    ("r_65", "r_65 (A65/Afund)", lambda f: f.r_65),
    ("r_55", "r_55 (A55/Afund)", lambda f: f.r_55),
    ("I_neg", "I_neg (Sec. Neg.)", lambda f: f.I_neg),
    ("THD", "THD (%)", lambda f: f.THD * 100.0),
    ("I_rms_C", "I_rms Fase C (A)", lambda f: float(f.I_rms[2])),
    ("I_rms_A", "I_rms Fase A (A)", lambda f: float(f.I_rms[0])),
    ("I_rms_B", "I_rms Fase B (A)", lambda f: float(f.I_rms[1])),
    ("I_prom", "I_prom RMS (A)", lambda f: f.I_prom),
    ("A_fund", "A_fund (A)", lambda f: f.A_fund),
    ("V_rms", "V_rms (V)", lambda f: f.V_rms)
]


class BaselineManager(QObject):
    """
    Gestiona la calibración y el cálculo estadístico de líneas base sanas multi-carga.
    """
    sig_baseline_captured = Signal(int, object)      # (load_level, BaselineProfile)
    sig_baseline_progress = Signal(int, int)         # (current_count, target_count)
    sig_deviations_computed = Signal(list)           # List[DeviationMetrics]

    def __init__(self, persistence_path: Optional[str] = None):
        super().__init__()
        self.profiles: Dict[int, BaselineProfile] = {}
        self.active_load_level: int = 0
        self.is_capturing: bool = False
        self.target_windows: int = 10               # 10 ventanas * 500 ms = 5.0 s
        self._capture_buffer: List[WindowFeatures] = []
        self._capture_load_level: int = 0
        
        self.persistence_path = persistence_path or os.path.expanduser("~/tesis_itf/dataset/baselines_multicarga.json")
        self.load_from_json()

    def set_active_load(self, load_level: int):
        """Define el nivel de carga activo para el cálculo de Z-scores en vivo."""
        self.active_load_level = max(0, min(3, load_level))

    def start_capture(self, load_level: int, target_windows: int = 10):
        """Inicia el proceso de captura de referencia sana promediando N ventanas."""
        self._capture_load_level = max(0, min(3, load_level))
        self.target_windows = target_windows
        self._capture_buffer.clear()
        self.is_capturing = True
        self.sig_baseline_progress.emit(0, self.target_windows)

    def cancel_capture(self):
        """Cancela la captura en progreso."""
        self.is_capturing = False
        self._capture_buffer.clear()
        self.sig_baseline_progress.emit(0, self.target_windows)

    @Slot(object)
    def process_window(self, features: WindowFeatures) -> Optional[List[DeviationMetrics]]:
        """
        Procesa una ventana entrante.
        Si la captura está activa, acumula la muestra.
        Si hay un baseline activo para la carga actual, calcula desviaciones y emite sig_deviations_computed.
        """
        # 1. Gestión de Captura
        if self.is_capturing:
            self._capture_buffer.append(features)
            count = len(self._capture_buffer)
            self.sig_baseline_progress.emit(count, self.target_windows)
            
            if count >= self.target_windows:
                self._finish_capture()

        # 2. Cálculo en vivo contra la referencia sana activa
        if self.active_load_level in self.profiles:
            profile = self.profiles[self.active_load_level]
            deviations: List[DeviationMetrics] = []
            
            for key, label, extractor in TRACKED_FEATURES:
                curr_val = float(extractor(features))
                ref_mean = float(profile.means.get(key, curr_val))
                ref_std = float(profile.stds.get(key, 1e-4))
                
                delta_abs = curr_val - ref_mean
                denom_pct = max(abs(ref_mean), 1e-4)
                delta_pct = (delta_abs / denom_pct) * 100.0
                
                # Puntuación Z-score normalizada con epsilon numérico
                z_score = delta_abs / (ref_std + 1e-6)
                
                abs_z = abs(z_score)
                if abs_z < Z_SCORE_NORMAL:
                    alert = "NORMAL"
                elif abs_z < Z_SCORE_WARNING:
                    alert = "WARNING"
                else:
                    alert = "FAULT"
                    
                deviations.append(DeviationMetrics(
                    feature_name=label,
                    current_value=curr_val,
                    ref_mean=ref_mean,
                    ref_std=ref_std,
                    delta_abs=delta_abs,
                    delta_pct=delta_pct,
                    z_score=z_score,
                    alert_level=alert
                ))
                
            self.sig_deviations_computed.emit(deviations)
            return deviations
            
        return None

    def _finish_capture(self):
        """Calcula medias, desviaciones estándar y espectro medio para finalizar la captura."""
        self.is_capturing = False
        load_lvl = self._capture_load_level
        num_win = len(self._capture_buffer)
        
        means: Dict[str, float] = {}
        stds: Dict[str, float] = {}
        
        for key, _, extractor in TRACKED_FEATURES:
            vals = np.array([extractor(f) for f in self._capture_buffer], dtype=np.float64)
            means[key] = float(np.mean(vals))
            stds[key] = float(np.std(vals, ddof=1) if len(vals) > 1 else 1e-4)
            
        # Espectro medio de fase C (301 bins)
        spec_matrix = np.vstack([f.fft_mag_C for f in self._capture_buffer])
        mean_spec = np.mean(spec_matrix, axis=0).astype(np.float32)
        
        profile = BaselineProfile(
            load_level=load_lvl,
            load_label=CARGAS.get(load_lvl, f"L{load_lvl}"),
            capture_timestamp=self._capture_buffer[-1].timestamp,
            num_windows=num_win,
            means=means,
            stds=stds,
            mean_spectrum_C=mean_spec
        )
        
        self.profiles[load_lvl] = profile
        self._capture_buffer.clear()
        self.sig_baseline_captured.emit(load_lvl, profile)
        self.save_to_json()

    def get_active_profile(self) -> Optional[BaselineProfile]:
        """Retorna el perfil sano activo para el nivel de carga actual."""
        return self.profiles.get(self.active_load_level, None)

    def save_to_json(self, path: Optional[str] = None):
        """Serializa los perfiles de referencia sanos a disco."""
        save_path = path or self.persistence_path
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        data = {}
        for lvl, prof in self.profiles.items():
            data[str(lvl)] = {
                "load_level": prof.load_level,
                "load_label": prof.load_label,
                "capture_timestamp": prof.capture_timestamp,
                "num_windows": prof.num_windows,
                "means": prof.means,
                "stds": prof.stds,
                "mean_spectrum_C": prof.mean_spectrum_C.tolist()
            }
        try:
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[WARN] Error al guardar baselines en {save_path}: {e}")

    def load_from_json(self, path: Optional[str] = None):
        """Carga perfiles de referencia sanos desde disco si existen."""
        load_path = path or self.persistence_path
        if not os.path.exists(load_path):
            return
        try:
            with open(load_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for lvl_str, p in data.items():
                lvl = int(lvl_str)
                self.profiles[lvl] = BaselineProfile(
                    load_level=p["load_level"],
                    load_label=p["load_label"],
                    capture_timestamp=p["capture_timestamp"],
                    num_windows=p["num_windows"],
                    means=p["means"],
                    stds=p["stds"],
                    mean_spectrum_C=np.array(p["mean_spectrum_C"], dtype=np.float32)
                )
        except Exception as e:
            print(f"[WARN] Error al cargar baselines desde {load_path}: {e}")
