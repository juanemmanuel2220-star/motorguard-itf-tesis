"""
MotorGuard ITF - Extractor MCSA de Alta Resolución (Referencia NumPy)
Implementación matemática de referencia para la Mejora 2 de la auditoría técnica.

Características clave:
1. Interpolación de Grandke para estimación de fundamental f0 y corrección de scalloping loss.
2. Cancelación de la fundamental en el dominio del tiempo por mínimos cuadrados.
3. Estimación y seguimiento del deslizamiento (slip ŝ) a partir de componentes rotóricas f0 ± f_r.
4. DFT Goertzel generalizado de un solo bin con ventana Hann para frecuencias exactas.
5. Cálculo de piso de ruido espectral local (mediana en ventana con exclusión de armónicos).
6. Relación señal a ruido (SNR) respecto al piso local y niveles relativos en dB.
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict, Any

MCSA_FS = 2400.0
MCSA_N = 4096
MCSA_DF = MCSA_FS / float(MCSA_N)  # 0.5859375 Hz
MCSA_P_PARES = 2
MCSA_S_MIN = 0.002
MCSA_S_MAX = 0.06

@dataclass
class McsaHrResultados:
    f0: float = 60.0
    A0: float = 1.0
    s: float = 0.012
    slip_ok: int = 0
    fr: float = 29.64
    
    # Amplitudes en dB relativas a Â0: Lx = 20*log10(Ax / Â0)
    L_2sm: float = -60.0
    L_2sp: float = -60.0
    L_rm: float = -55.0
    L_rp: float = -55.0
    L_3: float = -30.0
    L_3rm: float = -90.0
    L_3rp: float = -90.0
    
    # SNR respecto al piso local (dB)
    SNR_2sm: float = 20.0
    SNR_2sp: float = 20.0
    SNR_2s: float = 20.0
    SNR_rm: float = 20.0
    SNR_rp: float = 20.0
    SNR_3: float = 30.0
    SNR_3rm: float = 10.0
    SNR_3rp: float = 10.0
    
    # Pisos locales (unidades físicas)
    floor_2sm: float = 1e-4
    floor_2sp: float = 1e-4
    floor_rm: float = 1e-4
    floor_rp: float = 1e-4
    floor_3: float = 1e-4
    floor_3rm: float = 1e-4
    floor_3rp: float = 1e-4
    
    # Amplitudes físicas
    A_2sm: float = 1e-3
    A_2sp: float = 1e-3
    A_rm: float = 1e-3
    A_rp: float = 1e-3
    A_3: float = 1e-2
    A_3rm: float = 1e-4
    A_3rp: float = 1e-4

@dataclass
class McsaHrState:
    last_valid_s: float = 0.012
    has_valid_s: bool = False
    enable_ema: bool = False
    alpha_ema: float = 0.3
    P_2sm: float = 0.0
    P_2sp: float = 0.0
    P_rm: float = 0.0
    P_rp: float = 0.0
    P_3: float = 0.0
    P_3rm: float = 0.0
    P_3rp: float = 0.0

def grandke_f0(mag_X: np.ndarray, df: float = MCSA_DF, k_min: int = 100, k_max: int = 105) -> Tuple[float, int, float]:
    """Estima la frecuencia fundamental f0 mediante interpolación de Grandke para ventana Hann."""
    best_k = k_min + int(np.argmax(mag_X[k_min:k_max + 1]))
    
    if mag_X[best_k + 1] >= mag_X[best_k - 1]:
        sign = 1
        neighbor = mag_X[best_k + 1]
    else:
        sign = -1
        neighbor = mag_X[best_k - 1]
        
    denom = mag_X[best_k] if mag_X[best_k] > 1e-12 else 1e-12
    alpha = float(np.clip(neighbor / denom, 0.0, 1.0))
    delta = float(np.clip((2.0 * alpha - 1.0) / (1.0 + alpha), 0.0, 0.5))
    
    f0 = (float(best_k) + float(sign) * delta) * df
    return f0, best_k, float(sign) * delta

def grandke_amp(mag_k: float, delta: float, sum_w: float = 2048.0) -> float:
    """Calcula la amplitud corregida por scalloping loss."""
    abs_d = abs(delta)
    if abs_d > 1e-6:
        sinc_d = float(np.sin(np.pi * abs_d) / (np.pi * abs_d))
    else:
        sinc_d = 1.0
    denom = max(1.0 - abs_d * abs_d, 1e-6)
    W_delta = sinc_d / denom
    return (2.0 * mag_k) / (sum_w * W_delta)

def cancelar_fundamental(x: np.ndarray, f0: float, fs: float = MCSA_FS) -> Tuple[np.ndarray, float, float]:
    """Cancela la fundamental en el tiempo mediante ajuste por mínimos cuadrados de senos y cosenos."""
    n = len(x)
    omega = 2.0 * np.pi * f0 / fs
    t = np.arange(n)
    c = np.cos(omega * t)
    s = np.sin(omega * t)
    
    Ccc = np.sum(c * c)
    Css = np.sum(s * s)
    Ccs = np.sum(c * s)
    Cxc = np.sum(x * c)
    Cxs = np.sum(x * s)
    
    D = Ccc * Css - Ccs * Ccs
    if abs(D) > 1e-9:
        a = (Css * Cxc - Ccs * Cxs) / D
        b = (Ccc * Cxs - Ccs * Cxc) / D
    else:
        a, b = 0.0, 0.0
        
    residuo = x - (a * c + b * s)
    return residuo, float(a), float(b)

def dft_single(y: np.ndarray, freq: float, fs: float = MCSA_FS, w: Optional[np.ndarray] = None) -> float:
    """Calcula la amplitud física en una frecuencia exacta mediante DFT de un solo bin con ventana Hann."""
    n = len(y)
    if w is None:
        w = 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(n) / n)
    sum_w = np.sum(w)
    theta = 2.0 * np.pi * freq * np.arange(n) / fs
    re = np.sum(w * y * np.cos(theta))
    im = -np.sum(w * y * np.sin(theta))
    return float((2.0 / sum_w) * np.hypot(re, im))

def piso_local(
    mag_R: np.ndarray,
    f_target: float,
    target_freqs: list,
    df: float = MCSA_DF,
    sum_w: float = 2048.0
) -> float:
    """Calcula la mediana de magnitudes de bins vecinos excluyendo picos objetivo."""
    spans = [3.0, 5.0]
    valid_mags = []
    
    for span in spans:
        valid_mags.clear()
        k_start = max(1, int(round((f_target - span) / df)))
        k_end = min(len(mag_R) - 1, int(round((f_target + span) / df)))
        
        for k in range(k_start, k_end + 1):
            fk = k * df
            if abs(fk - f_target) > span:
                continue
            if abs(fk - f_target) <= 3.0 * df:
                continue
            
            clash = False
            for ft in target_freqs:
                if abs(fk - ft) <= 3.0 * df:
                    clash = True
                    break
            if not clash:
                valid_mags.append(mag_R[k])
                
        if len(valid_mags) >= 5:
            break
            
    if not valid_mags:
        return 1e-7
        
    valid_mags.sort()
    med_mag = float(valid_mags[len(valid_mags) // 2])
    floor_amp = (2.0 / sum_w) * med_mag
    return max(floor_amp, 1e-7)

def procesar_mcsa_hr(
    x_in: np.ndarray,
    state: Optional[McsaHrState] = None,
    cal_i: float = 1.0
) -> McsaHrResultados:
    """
    Ejecuta el pipeline completo de MCSA de alta resolución sobre un bloque de 4096 muestras.
    """
    if state is None:
        state = McsaHrState()
        
    # Preprocesamiento: remoción de nivel DC y escalado
    x = cal_i * (x_in - np.mean(x_in))
    n = len(x)
    assert n == MCSA_N, f"Se requieren {MCSA_N} muestras, recibidas {n}"
    
    # 1. Ventana de Hann y primera FFT
    w = 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(n) / n)
    sum_w = np.sum(w)
    X = np.fft.rfft(x * w)
    mag_X = np.abs(X)
    
    # 2. Estimación de Fundamental en [58.5, 61.5] Hz con Grandke
    df = MCSA_DF
    k_min = int(round(58.5 / df))
    k_max = int(round(61.5 / df))
    f0, best_k, delta = grandke_f0(mag_X, df, k_min, k_max)
    A0 = grandke_amp(mag_X[best_k], delta, sum_w)
    A0 = max(A0, 1e-6)
    
    # 3. Cancelación de Fundamental en tiempo
    residuo, a_ls, b_ls = cancelar_fundamental(x, f0, MCSA_FS)
    
    # 4. Segunda FFT (residuo)
    R = np.fft.rfft(residuo * w)
    mag_R = np.abs(R)
    
    # 5. Búsqueda de deslizamiento fr
    fr_min = f0 * (1.0 - MCSA_S_MAX) / float(MCSA_P_PARES)
    fr_max = f0 * (1.0 - MCSA_S_MIN) / float(MCSA_P_PARES)
    k_up_min = int(round((f0 + fr_min) / df))
    k_up_max = int(round((f0 + fr_max) / df))
    
    best_k_up = k_up_min
    max_metric = -1.0
    for k_up in range(k_up_min, k_up_max + 1):
        f_up = k_up * df
        cand_fr = f_up - f0
        f_low = abs(f0 - cand_fr)
        k_low = max(1, int(round(f_low / df)))
        metric = mag_R[k_up]**2 + mag_R[k_low]**2
        if metric > max_metric:
            max_metric = metric
            best_k_up = k_up
            
    # Interpolación dual de Grandke
    f_up_bin = best_k_up * df
    cand_fr = f_up_bin - f0
    best_k_low = max(1, int(round(abs(f0 - cand_fr) / df)))
    
    # Grandke upper
    sign_u = 1 if mag_R[best_k_up + 1] >= mag_R[best_k_up - 1] else -1
    alpha_u = np.clip(mag_R[best_k_up + sign_u] / max(mag_R[best_k_up], 1e-12), 0.0, 1.0)
    delta_u = np.clip((2.0 * alpha_u - 1.0) / (1.0 + alpha_u), 0.0, 0.5)
    f_up_est = (best_k_up + sign_u * delta_u) * df
    fr_up = f_up_est - f0
    
    # Grandke lower
    sign_l = 1 if mag_R[best_k_low + 1] >= mag_R[best_k_low - 1] else -1
    alpha_l = np.clip(mag_R[best_k_low + sign_l] / max(mag_R[best_k_low], 1e-12), 0.0, 1.0)
    delta_l = np.clip((2.0 * alpha_l - 1.0) / (1.0 + alpha_l), 0.0, 0.5)
    f_low_est = (best_k_low + sign_l * delta_l) * df
    fr_low = f0 - f_low_est
    
    fr_est = 0.5 * (fr_up + fr_low)
    s_est = 1.0 - float(MCSA_P_PARES) * fr_est / f0
    
    # Prominencia >= 6 dB
    floor_up = piso_local(mag_R, f_up_est, [f0, f_up_est], df, sum_w)
    amp_up = (2.0 / sum_w) * mag_R[best_k_up]
    prom_dB = 20.0 * np.log10(amp_up / max(floor_up, 1e-7))
    
    if prom_dB >= 6.0 and (MCSA_S_MIN <= s_est <= MCSA_S_MAX):
        slip_ok = 1
        s_final = s_est
        fr_final = fr_est
        state.last_valid_s = s_final
        state.has_valid_s = True
    else:
        slip_ok = 0
        if state.has_valid_s:
            s_final = state.last_valid_s
        else:
            s_final = 0.012
        fr_final = f0 * (1.0 - s_final) / float(MCSA_P_PARES)
        
    # 6. Frecuencias exactas
    f_2sm = f0 * (1.0 - 2.0 * s_final)
    f_2sp = f0 * (1.0 + 2.0 * s_final)
    f_rm = f0 - fr_final
    f_rp = f0 + fr_final
    f_3 = 3.0 * f0
    f_3rm = 3.0 * f0 - fr_final
    f_3rp = 3.0 * f0 + fr_final
    
    all_targets = [f0, f_2sm, f_2sp, f_rm, f_rp, f_3, f_3rm, f_3rp]
    
    # 7. Pisos locales
    fl_2sm = piso_local(mag_R, f_2sm, all_targets, df, sum_w)
    fl_2sp = piso_local(mag_R, f_2sp, all_targets, df, sum_w)
    fl_rm  = piso_local(mag_R, f_rm,  all_targets, df, sum_w)
    fl_rp  = piso_local(mag_R, f_rp,  all_targets, df, sum_w)
    fl_3   = piso_local(mag_R, f_3,   all_targets, df, sum_w)
    fl_3rm = piso_local(mag_R, f_3rm, all_targets, df, sum_w)
    fl_3rp = piso_local(mag_R, f_3rp, all_targets, df, sum_w)
    
    # 8. DFTs Goertzel exactas
    A_2sm = dft_single(residuo, f_2sm, MCSA_FS, w)
    A_2sp = dft_single(residuo, f_2sp, MCSA_FS, w)
    A_rm  = dft_single(residuo, f_rm,  MCSA_FS, w)
    A_rp  = dft_single(residuo, f_rp,  MCSA_FS, w)
    A_3   = dft_single(x,       f_3,   MCSA_FS, w)
    A_3rm = dft_single(residuo, f_3rm, MCSA_FS, w)
    A_3rp = dft_single(residuo, f_3rp, MCSA_FS, w)
    
    # 9. Niveles relativos y SNR
    if state.enable_ema:
        a = state.alpha_ema
        om_a = 1.0 - a
        p2sm = (A_2sm / A0)**2
        p2sp = (A_2sp / A0)**2
        prm  = (A_rm  / A0)**2
        prp  = (A_rp  / A0)**2
        p3   = (A_3   / A0)**2
        p3rm = (A_3rm / A0)**2
        p3rp = (A_3rp / A0)**2
        
        state.P_2sm = p2sm if state.P_2sm <= 0 else (om_a * state.P_2sm + a * p2sm)
        state.P_2sp = p2sp if state.P_2sp <= 0 else (om_a * state.P_2sp + a * p2sp)
        state.P_rm  = prm  if state.P_rm  <= 0 else (om_a * state.P_rm  + a * prm)
        state.P_rp  = prp  if state.P_rp  <= 0 else (om_a * state.P_rp  + a * prp)
        state.P_3   = p3   if state.P_3   <= 0 else (om_a * state.P_3   + a * p3)
        state.P_3rm = p3rm if state.P_3rm <= 0 else (om_a * state.P_3rm + a * p3rm)
        state.P_3rp = p3rp if state.P_3rp <= 0 else (om_a * state.P_3rp + a * p3rp)
        
        L_2sm = 10.0 * np.log10(max(state.P_2sm, 1e-12))
        L_2sp = 10.0 * np.log10(max(state.P_2sp, 1e-12))
        L_rm  = 10.0 * np.log10(max(state.P_rm,  1e-12))
        L_rp  = 10.0 * np.log10(max(state.P_rp,  1e-12))
        L_3   = 10.0 * np.log10(max(state.P_3,   1e-12))
        L_3rm = 10.0 * np.log10(max(state.P_3rm, 1e-12))
        L_3rp = 10.0 * np.log10(max(state.P_3rp, 1e-12))
    else:
        L_2sm = 20.0 * np.log10(max(A_2sm, 1e-7) / A0)
        L_2sp = 20.0 * np.log10(max(A_2sp, 1e-7) / A0)
        L_rm  = 20.0 * np.log10(max(A_rm,  1e-7) / A0)
        L_rp  = 20.0 * np.log10(max(A_rp,  1e-7) / A0)
        L_3   = 20.0 * np.log10(max(A_3,   1e-7) / A0)
        L_3rm = 20.0 * np.log10(max(A_3rm, 1e-7) / A0)
        L_3rp = 20.0 * np.log10(max(A_3rp, 1e-7) / A0)
        
    SNR_2sm = 20.0 * np.log10(max(A_2sm, 1e-7) / fl_2sm)
    SNR_2sp = 20.0 * np.log10(max(A_2sp, 1e-7) / fl_2sp)
    SNR_2s  = max(SNR_2sm, SNR_2sp)
    SNR_rm  = 20.0 * np.log10(max(A_rm,  1e-7) / fl_rm)
    SNR_rp  = 20.0 * np.log10(max(A_rp,  1e-7) / fl_rp)
    SNR_3   = 20.0 * np.log10(max(A_3,   1e-7) / fl_3)
    SNR_3rm = 20.0 * np.log10(max(A_3rm, 1e-7) / fl_3rm)
    SNR_3rp = 20.0 * np.log10(max(A_3rp, 1e-7) / fl_3rp)
    
    return McsaHrResultados(
        f0=float(f0), A0=float(A0), s=float(s_final), slip_ok=slip_ok, fr=float(fr_final),
        L_2sm=float(L_2sm), L_2sp=float(L_2sp), L_rm=float(L_rm), L_rp=float(L_rp),
        L_3=float(L_3), L_3rm=float(L_3rm), L_3rp=float(L_3rp),
        SNR_2sm=float(SNR_2sm), SNR_2sp=float(SNR_2sp), SNR_2s=float(SNR_2s),
        SNR_rm=float(SNR_rm), SNR_rp=float(SNR_rp),
        SNR_3=float(SNR_3), SNR_3rm=float(SNR_3rm), SNR_3rp=float(SNR_3rp),
        floor_2sm=float(fl_2sm), floor_2sp=float(fl_2sp), floor_rm=float(fl_rm), floor_rp=float(fl_rp),
        floor_3=float(fl_3), floor_3rm=float(fl_3rm), floor_3rp=float(fl_3rp),
        A_2sm=float(A_2sm), A_2sp=float(A_2sp), A_rm=float(A_rm), A_rp=float(A_rp),
        A_3=float(A_3), A_3rm=float(A_3rm), A_3rp=float(A_3rp)
    )
