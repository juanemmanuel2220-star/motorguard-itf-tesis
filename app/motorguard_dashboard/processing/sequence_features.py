"""
sequence_features.py
====================
Implementación de referencia en Python (NumPy) para el cálculo de componentes
simétricas (Transformación de Fortescue), compensación de retardo de muestreo (skew),
referenciación angular a V1, desacople del desbalance de red (V2/Y2) y comisionamiento.

Equivalente matemático exacto de secuencia.h y secuencia.cpp del firmware ESP32-S3.
"""

import numpy as np
from typing import Dict, Any, Tuple, Optional, List
from dataclasses import dataclass

SEC_FS = 2400.0
SEC_NBIG = 4096
SEC_VUF_MAX = 0.02
DEFAULT_SKEW_US = np.array([0.0, 30.0, 60.0, 90.0, 120.0, 150.0], dtype=np.float32)


@dataclass
class SecuenciaResultadosPy:
    f0: float
    V1: complex
    V2: complex
    I1: complex
    I2: complex
    u_V: float
    u_I: float
    e_2: float
    dom: int


def estimar_f0_grandke(samp: np.ndarray, fs: float = SEC_FS, n: int = SEC_NBIG) -> float:
    """
    Estima la frecuencia fundamental f0 en [58.5, 61.5] Hz usando la interpolación
    de Grandke para una ventana periódica de Hann.
    """
    df = fs / n
    k_min = int(np.floor(58.5 / df)) - 1
    k_max = int(np.ceil(61.5 / df)) + 1

    x = np.asarray(samp, dtype=np.float64)[:n]
    x = x - np.mean(x)

    # Ventana Hann periódica: w[n] = 0.5 - 0.5 * cos(2*pi*n / N)
    w = 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(n) / n)
    xw = x * w

    bins = np.arange(k_min, k_max + 1)
    X = np.array([
        np.sum(xw * np.exp(-2j * np.pi * k * np.arange(n) / n))
        for k in bins
    ])
    mags = np.abs(X)
    idx_star = int(np.argmax(mags))
    k_star = bins[idx_star]

    if idx_star == 0 or idx_star == len(bins) - 1:
        return float(k_star * df)

    mag_left = mags[idx_star - 1]
    mag_center = mags[idx_star]
    mag_right = mags[idx_star + 1]

    if mag_right >= mag_left:
        alpha = mag_right / mag_center if mag_center > 1e-12 else 0.0
        delta = (2.0 * alpha - 1.0) / (1.0 + alpha)
        k_est = k_star + delta
    else:
        alpha = mag_left / mag_center if mag_center > 1e-12 else 0.0
        delta = (2.0 * alpha - 1.0) / (1.0 + alpha)
        k_est = k_star - delta

    return float(k_est * df)


def calcular_secuencia(
    samp_buf: np.ndarray,
    f0: float = 60.0,
    cal_v: Optional[np.ndarray] = None,
    cal_i: Optional[np.ndarray] = None,
    skew_us: Optional[np.ndarray] = None,
    Y2_comp: complex = 0.0 + 0.0j,
    I2_0: complex = 0.0 + 0.0j
) -> SecuenciaResultadosPy:
    """
    Calcula los fasores de tensión y corriente en componentes simétricas.
    samp_buf: matriz de dimensiones (6, SEC_NBIG) con canales [VA, VB, VC, IA, IB, IC].
    """
    samp = np.asarray(samp_buf, dtype=np.float64)
    if cal_v is None:
        cal_v = np.ones(3, dtype=np.float64)
    if cal_i is None:
        cal_i = np.ones(3, dtype=np.float64)
    if skew_us is None:
        skew_us = np.zeros(6, dtype=np.float64)

    N = SEC_NBIG
    # Ventana Hann periódica
    w = 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(N) / N)

    # Carrier e^(-j * 2*pi * f0 * n / Fs)
    carrier = np.exp(-1j * 2.0 * np.pi * f0 * np.arange(N) / SEC_FS)
    w_carrier = w * carrier

    # 1. Extracción de fasores por canal
    X = np.zeros(6, dtype=complex)
    scale_factor = 2.0 / np.sum(w)  # Equivalente a 4.0 / N

    for c in range(6):
        xc = samp[c, :N] - np.mean(samp[c, :N])
        X[c] = np.sum(xc * w_carrier) * scale_factor

    # 2. Compensación de retardo de muestreo secuencial (SKEW_US)
    for c in range(6):
        tau = skew_us[c] * 1e-6
        X[c] *= np.exp(-1j * 2.0 * np.pi * f0 * tau)

    # 3. Factores de calibración física
    Va = X[0] * cal_v[0]
    Vb = X[1] * cal_v[1]
    Vc = X[2] * cal_v[2]

    Ia = X[3] * cal_i[0]
    Ib = X[4] * cal_i[1]
    Ic = X[5] * cal_i[2]

    # 4. Operador Fortescue: a = exp(j * 2pi/3)
    a_op = -0.5 + 1j * np.sqrt(3.0) / 2.0
    a2_op = -0.5 - 1j * np.sqrt(3.0) / 2.0

    # 5. Referencia angular respecto a V1
    V1_raw = (Va + a_op * Vb + a2_op * Vc) / 3.0
    phi_ref = np.angle(V1_raw)
    rot_ref = np.exp(-1j * phi_ref)

    Va *= rot_ref
    Vb *= rot_ref
    Vc *= rot_ref
    Ia *= rot_ref
    Ib *= rot_ref
    Ic *= rot_ref

    V1 = (Va + a_op * Vb + a2_op * Vc) / 3.0
    V2 = (Va + a2_op * Vb + a_op * Vc) / 3.0
    I1 = (Ia + a_op * Ib + a2_op * Ic) / 3.0
    I2 = (Ia + a2_op * Ib + a_op * Ic) / 3.0

    mag_V1 = abs(V1)
    mag_V2 = abs(V2)
    mag_I1 = abs(I1)
    mag_I2 = abs(I2)

    u_V = float(mag_V2 / mag_V1) if mag_V1 > 1e-6 else 0.0
    u_I = float(mag_I2 / mag_I1) if mag_I1 > 1e-6 else 0.0

    diff = I2 - Y2_comp * V2 - I2_0
    e_2 = float(abs(diff) / mag_I1) if mag_I1 > 1e-6 else 0.0
    dom = 1 if u_V <= SEC_VUF_MAX else 0

    return SecuenciaResultadosPy(
        f0=float(f0),
        V1=V1,
        V2=V2,
        I1=I1,
        I2=I2,
        u_V=u_V,
        u_I=u_I,
        e_2=e_2,
        dom=dom
    )


def comisionamiento_resolver(
    V2_list: List[complex],
    I2_list: List[complex],
    V1_list: List[complex]
) -> Tuple[complex, complex, float]:
    """
    Resuelve el sistema normal 2x2 para determinar Y2 e I2_0 de compensación.
    """
    V2_arr = np.asarray(V2_list, dtype=complex)
    I2_arr = np.asarray(I2_list, dtype=complex)
    V1_arr = np.asarray(V1_list, dtype=complex)

    M = len(V2_arr)
    if M < 2:
        return 0j, 0j, 1.0

    S_V2sq = np.sum(np.abs(V2_arr)**2)
    S_V2 = np.sum(V2_arr)
    S_I2 = np.sum(I2_arr)
    S_conjV2_I2 = np.sum(np.conj(V2_arr) * I2_arr)
    mean_V1_sq = np.mean(np.abs(V1_arr)**2)

    D = M * S_V2sq - np.abs(S_V2)**2
    var_V2 = D / (M * M)

    if var_V2 < 1e-6 * mean_V1_sq or abs(D) < 1e-12:
        return 0j, complex(S_I2 / M), 1.0

    Y2 = (M * S_conjV2_I2 - np.conj(S_V2) * S_I2) / D
    I2_0 = (-S_V2 * S_conjV2_I2 + S_V2sq * S_I2) / D

    trace = S_V2sq + M
    disc = np.sqrt(max(0.0, trace * trace - 4.0 * D))
    l_max = 0.5 * (trace + disc)
    l_min = 0.5 * (trace - disc)
    cond_num = float(l_max / l_min) if l_min > 1e-12 else 1e12

    return complex(Y2), complex(I2_0), cond_num
