"""
MotorGuard ITF - Detector Secuencial CUSUM sobre Log-Odds Calibradas (Mejora 3B)
Implementación en Python con compatibilidad estricta C++.
"""

import numpy as np
from dataclasses import dataclass

CAL_A = -6.8515
CAL_B = 3.5614
CUSUM_K = 0.50
CUSUM_H = 5.00
CUSUM_HOFF = 1.25
CUSUM_M = 3

@dataclass
class DetectorStatePy:
    S: float = 0.0
    p_cal: float = 0.0
    z: float = 0.0
    consecutive_low: int = 0
    current_decision: int = 0  # 0: SANO, 1: ALARMA
    is_warmup: bool = False

def detector_init_py() -> DetectorStatePy:
    return DetectorStatePy()

def detector_step_py(p_raw: float, st: DetectorStatePy) -> int:
    if st.is_warmup:
        st.S = 0.0
        st.consecutive_low = 0
        st.current_decision = 0
        return -1

    # 1. Calibración de Platt
    exponente = CAL_A * p_raw + CAL_B
    exponente = float(np.clip(exponente, -20.0, 20.0))
    p_cal = 1.0 / (1.0 + np.exp(exponente))
    st.p_cal = float(p_cal)

    # 2. Log-odds z_t
    z_t = -exponente
    st.z = float(z_t)

    # 3. Acumulador CUSUM
    s_next = max(0.0, st.S + z_t - CUSUM_K)
    st.S = float(s_next)

    # 4. Regla de decisión secuencial con histéresis
    if st.current_decision == 1:
        if st.S < CUSUM_HOFF:
            st.consecutive_low += 1
            if st.consecutive_low >= CUSUM_M:
                st.current_decision = 0
                st.consecutive_low = 0
        else:
            st.consecutive_low = 0
    else:
        if st.S >= CUSUM_H:
            st.current_decision = 1
            st.consecutive_low = 0

    return st.current_decision
