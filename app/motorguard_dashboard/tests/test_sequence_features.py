"""
test_sequence_features.py
=========================
Suite de pruebas unitarias y de validación para componentes simétricas (Fortescue),
desacople de desbalance y equivalencia entre firmware C++ (libsecuencia.so) y Python.

Cumple rigurosamente con los Criterios de Aceptación T1 a T6 especificados en la auditoría.
"""

import os
import ctypes
import pytest
import numpy as np

from motorguard_dashboard.processing.sequence_features import (
    estimar_f0_grandke,
    calcular_secuencia,
    comisionamiento_resolver,
    SEC_FS,
    SEC_NBIG
)

LIB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'libsecuencia.so')

class ComplexFloatC(ctypes.Structure):
    _fields_ = [("re", ctypes.c_float), ("im", ctypes.c_float)]

class SecuenciaResultadosC(ctypes.Structure):
    _fields_ = [
        ("f0", ctypes.c_float),
        ("V1", ComplexFloatC),
        ("V2", ComplexFloatC),
        ("I1", ComplexFloatC),
        ("I2", ComplexFloatC),
        ("u_V", ctypes.c_float),
        ("u_I", ctypes.c_float),
        ("e_2", ctypes.c_float),
        ("dom", ctypes.c_int)
    ]

class ComisionamientoStateC(ctypes.Structure):
    _fields_ = [
        ("M", ctypes.c_int),
        ("sum_V2_sq", ctypes.c_float),
        ("sum_V2", ComplexFloatC),
        ("sum_I2", ComplexFloatC),
        ("sum_conjV2_I2", ComplexFloatC),
        ("sum_V1_sq", ctypes.c_float)
    ]

# Cargar la librería C++
lib = ctypes.CDLL(LIB_PATH)

lib.estimar_f0_grandke.argtypes = [ctypes.POINTER(ctypes.c_int16), ctypes.c_float, ctypes.c_int]
lib.estimar_f0_grandke.restype = ctypes.c_float

lib.calcular_secuencia.argtypes = [
    ctypes.POINTER(ctypes.c_int16),
    ctypes.c_float,
    ctypes.POINTER(ctypes.c_float),
    ctypes.POINTER(ctypes.c_float),
    ctypes.POINTER(ctypes.c_float),
    ComplexFloatC,
    ComplexFloatC,
    ctypes.POINTER(SecuenciaResultadosC)
]
lib.calcular_secuencia.restype = None

lib.comisionamiento_reset.argtypes = [ctypes.POINTER(ComisionamientoStateC)]
lib.comisionamiento_reset.restype = None

lib.comisionamiento_acumular.argtypes = [
    ctypes.POINTER(ComisionamientoStateC),
    ComplexFloatC,
    ComplexFloatC,
    ComplexFloatC
]
lib.comisionamiento_acumular.restype = None

lib.comisionamiento_resolver.argtypes = [
    ctypes.POINTER(ComisionamientoStateC),
    ctypes.POINTER(ComplexFloatC),
    ctypes.POINTER(ComplexFloatC),
    ctypes.POINTER(ctypes.c_float)
]
lib.comisionamiento_resolver.restype = ctypes.c_bool

# Factores de conversión ADC típicos del banco experimental (counts/Volt y counts/Ampere)
SCALE_V = 10.0   # 179.6 Vpk -> ~1796 cuentas ADC
SCALE_I = 200.0  # 6.22 Apk -> ~1244 cuentas ADC
CAL_V_TEST = np.array([1.0 / SCALE_V] * 3, dtype=np.float32)
CAL_I_TEST = np.array([1.0 / SCALE_I] * 3, dtype=np.float32)


def generar_sistema_sintetico(
    f0=60.0,
    V_rms=127.0,
    I_rms=4.4,
    phi_I=-0.5,
    I2_ratio=0.0,
    I2_phase=0.0,
    delays_us=None,
    snr_db=None,
    seed=42
):
    """Genera señales de 6 canales (VA, VB, VC, IA, IB, IC) en cuentas ADC (int16)."""
    N = SEC_NBIG
    t = np.arange(N) / SEC_FS

    if delays_us is None:
        delays_us = [0.0] * 6

    # Amplitudes pico en unidades de ingeniería
    V_pk = V_rms * np.sqrt(2.0)
    I1_pk = I_rms * np.sqrt(2.0)
    I2_pk = I1_pk * I2_ratio

    phases_V = [0.0, -2.0 * np.pi / 3.0, 2.0 * np.pi / 3.0]
    phases_I1 = [phi_I, phi_I - 2.0 * np.pi / 3.0, phi_I + 2.0 * np.pi / 3.0]
    phases_I2 = [I2_phase, I2_phase + 2.0 * np.pi / 3.0, I2_phase - 2.0 * np.pi / 3.0]

    signals = np.zeros((6, N), dtype=np.float32)

    # Tensiones convertidas a cuentas ADC
    for c in range(3):
        tau = delays_us[c] * 1e-6
        v_phys = V_pk * np.cos(2.0 * np.pi * f0 * (t + tau) + phases_V[c])
        signals[c] = v_phys * SCALE_V

    # Corrientes convertidas a cuentas ADC
    for c in range(3):
        tau = delays_us[3 + c] * 1e-6
        sig_pos = I1_pk * np.cos(2.0 * np.pi * f0 * (t + tau) + phases_I1[c])
        sig_neg = I2_pk * np.cos(2.0 * np.pi * f0 * (t + tau) + phases_I2[c])
        i_phys = sig_pos + sig_neg
        signals[3 + c] = i_phys * SCALE_I

    if snr_db is not None:
        rng = np.random.default_rng(seed)
        for c in range(6):
            p_sig = np.mean(signals[c]**2)
            p_noise = p_sig / (10.0**(snr_db / 10.0))
            signals[c] += rng.normal(0.0, np.sqrt(p_noise), size=N).astype(np.float32)

    samp_int16 = np.clip(np.round(signals), -32768, 32767).astype(np.int16)
    return samp_int16, signals


def test_t1_sistema_balanceado():
    """T1: Sistema balanceado 127 V / 4.4 A, f0=60.00 Hz, sin ruido -> u_V < 1e-4 y u_I < 1e-4."""
    samp_int16, _ = generar_sistema_sintetico(f0=60.0, V_rms=127.0, I_rms=4.4, I2_ratio=0.0)

    res_py = calcular_secuencia(samp_int16, f0=60.0, cal_v=CAL_V_TEST, cal_i=CAL_I_TEST, skew_us=np.zeros(6))
    assert res_py.u_V < 1e-4, f"u_V = {res_py.u_V} supera 1e-4"
    assert res_py.u_I < 1e-4, f"u_I = {res_py.u_I} supera 1e-4"
    assert res_py.dom == 1, "Sistema balanceado debe estar dentro de dominio (DOM=1)"


@pytest.mark.parametrize("f0_val", [59.80, 60.00, 60.20])
def test_t2_frecuencias_y_desbalance_inyectado(f0_val):
    """T2: f0 en {59.80, 60.00, 60.20} Hz con I2 = 1.00% y fase aleatoria -> |u_I - 0.0100| < 2e-4."""
    rng = np.random.default_rng(int(f0_val * 100))
    rand_phase = rng.uniform(0.0, 2.0 * np.pi)

    samp_int16, _ = generar_sistema_sintetico(
        f0=f0_val,
        V_rms=127.0,
        I_rms=4.4,
        I2_ratio=0.0100,
        I2_phase=rand_phase
    )

    f0_est = estimar_f0_grandke(samp_int16[5], fs=SEC_FS, n=SEC_NBIG)
    assert abs(f0_est - f0_val) < 0.005, f"Error en estimación f0: {f0_est} vs {f0_val}"

    res = calcular_secuencia(samp_int16, f0=f0_est, cal_v=CAL_V_TEST, cal_i=CAL_I_TEST, skew_us=np.zeros(6))
    err = abs(res.u_I - 0.0100)
    assert err < 2e-4, f"Para f0={f0_val} Hz: u_I={res.u_I:.6f}, err={err:.6f} >= 2e-4"


def test_t3_compensacion_retardo_muestreo():
    """
    T3: Retardos de 0, 30 y 60 us en IA, IB, IC:
    Sin compensar: u_I ≈ 0.65% (documentado exactamente en ~0.65%).
    Con compensación SKEW_US: u_I < 1e-4.
    """
    delays_us = [0.0, 30.0, 60.0, 90.0, 120.0, 150.0]

    samp_int16, _ = generar_sistema_sintetico(
        f0=60.0,
        V_rms=127.0,
        I_rms=4.4,
        I2_ratio=0.0,
        delays_us=delays_us
    )

    # 1. Sin compensación (skew = 0)
    zero_skew = np.zeros(6, dtype=np.float32)
    res_sin_comp = calcular_secuencia(samp_int16, f0=60.0, cal_v=CAL_V_TEST, cal_i=CAL_I_TEST, skew_us=zero_skew)
    u_I_sin = res_sin_comp.u_I
    # Comprobar que sin compensar el desfase artificial ronda 0.65% (0.0065)
    assert 0.0055 <= u_I_sin <= 0.0075, f"u_I sin compensar={u_I_sin*100:.3f}% no coincide con ~0.65%"

    # 2. Con compensación adecuada
    correct_skew = np.array(delays_us, dtype=np.float32)
    res_con_comp = calcular_secuencia(samp_int16, f0=60.0, cal_v=CAL_V_TEST, cal_i=CAL_I_TEST, skew_us=correct_skew)
    assert res_con_comp.u_I < 1e-4, f"u_I con compensacion={res_con_comp.u_I:.6f} supera 1e-4"


def test_t4_inmunidad_al_ruido():
    """T4: Ruido blanco con SNR de 40 dB por muestra -> sesgo medio de u_I < 5e-4 sobre 200 realizaciones."""
    u_I_list = []
    for r in range(200):
        samp_int16, _ = generar_sistema_sintetico(
            f0=60.0,
            V_rms=127.0,
            I_rms=4.4,
            I2_ratio=0.0,
            snr_db=40.0,
            seed=1000 + r
        )
        res = calcular_secuencia(samp_int16, f0=60.0, cal_v=CAL_V_TEST, cal_i=CAL_I_TEST, skew_us=np.zeros(6))
        u_I_list.append(res.u_I)

    mean_bias = float(np.mean(u_I_list))
    assert mean_bias < 5e-4, f"Sesgo medio u_I = {mean_bias:.6f} supera 5e-4"


def test_t5_comisionamiento_sintetico():
    """T5: Comisionamiento con Y2 e I2_0 sintéticos conocidos y 5 niveles de desbalance -> error < 1%."""
    true_Y2 = 0.05 + 0.02j
    true_I2_0 = 0.03 - 0.015j
    V1_mag = 127.0

    u_levels = [0.005, 0.010, 0.015, 0.018, 0.020]
    V2_list, I2_list, V1_list = [], [], []

    rng = np.random.default_rng(42)
    for k in range(50):
        u = u_levels[k % len(u_levels)]
        ang = 2.0 * np.pi * k / 50.0
        V1 = V1_mag + 0j
        V2 = V1_mag * u * np.exp(1j * ang)
        noise = 1e-5 * (rng.normal() + 1j * rng.normal())
        I2 = true_Y2 * V2 + true_I2_0 + noise

        V1_list.append(V1)
        V2_list.append(V2)
        I2_list.append(I2)

    Y2_est, I2_0_est, cond_num = comisionamiento_resolver(V2_list, I2_list, V1_list)

    err_Y2 = abs(Y2_est - true_Y2) / abs(true_Y2)
    err_I2_0 = abs(I2_0_est - true_I2_0) / abs(true_I2_0)

    assert err_Y2 < 0.01, f"Error relativo Y2={err_Y2*100:.3f}% >= 1%"
    assert err_I2_0 < 0.01, f"Error relativo I2_0={err_I2_0*100:.3f}% >= 1%"
    assert cond_num < 1e6, f"Número de condición={cond_num} es inestable"


def test_t6_equivalencia_c_vs_numpy():
    """T6: Equivalencia C++ vs NumPy: error absoluto < 1e-5 en todas las métricas adimensionales y < 1e-3 en fasores."""
    delays_us = [0.0, 30.0, 60.0, 90.0, 120.0, 150.0]

    samp_int16, _ = generar_sistema_sintetico(
        f0=60.05,
        V_rms=125.0,
        I_rms=4.2,
        I2_ratio=0.015,
        delays_us=delays_us,
        seed=123
    )

    # 1. Versión NumPy
    f0_py = estimar_f0_grandke(samp_int16[5], fs=SEC_FS, n=SEC_NBIG)
    Y2_comp = 0.04 + 0.01j
    I2_0 = 0.02 - 0.01j
    res_py = calcular_secuencia(
        samp_int16,
        f0=f0_py,
        cal_v=CAL_V_TEST,
        cal_i=CAL_I_TEST,
        skew_us=np.array(delays_us, dtype=np.float32),
        Y2_comp=Y2_comp,
        I2_0=I2_0
    )

    # 2. Versión C++ (libsecuencia.so)
    c_samp = samp_int16.ctypes.data_as(ctypes.POINTER(ctypes.c_int16))
    f0_c = lib.estimar_f0_grandke(samp_int16[5].ctypes.data_as(ctypes.POINTER(ctypes.c_int16)), SEC_FS, SEC_NBIG)
    assert abs(f0_py - f0_c) < 1e-4, f"f0_py={f0_py} vs f0_c={f0_c}"

    c_cal_v = CAL_V_TEST.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
    c_cal_i = CAL_I_TEST.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
    c_skew = (ctypes.c_float * 6)(*delays_us)

    cY2 = ComplexFloatC(re=Y2_comp.real, im=Y2_comp.imag)
    cI2_0 = ComplexFloatC(re=I2_0.real, im=I2_0.imag)
    res_c = SecuenciaResultadosC()

    lib.calcular_secuencia(
        c_samp,
        ctypes.c_float(f0_c),
        c_cal_v,
        c_cal_i,
        c_skew,
        cY2,
        cI2_0,
        ctypes.byref(res_c)
    )

    # Comparar métricas adimensionales clave
    assert abs(res_py.u_V - res_c.u_V) < 1e-5, f"u_V: {res_py.u_V} vs {res_c.u_V}"
    assert abs(res_py.u_I - res_c.u_I) < 1e-5, f"u_I: {res_py.u_I} vs {res_c.u_I}"
    assert abs(res_py.e_2 - res_c.e_2) < 1e-5, f"e_2: {res_py.e_2} vs {res_c.e_2}"
    assert res_py.dom == res_c.dom, f"dom: {res_py.dom} vs {res_c.dom}"

    # Comparar fasores
    assert abs(res_py.V1.real - res_c.V1.re) < 1e-3
    assert abs(res_py.V1.imag - res_c.V1.im) < 1e-3
    assert abs(res_py.V2.real - res_c.V2.re) < 1e-3
    assert abs(res_py.V2.imag - res_c.V2.im) < 1e-3
    assert abs(res_py.I1.real - res_c.I1.re) < 1e-4
    assert abs(res_py.I1.imag - res_c.I1.im) < 1e-4
    assert abs(res_py.I2.real - res_c.I2.re) < 1e-4
    assert abs(res_py.I2.imag - res_c.I2.im) < 1e-4
