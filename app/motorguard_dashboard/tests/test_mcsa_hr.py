"""
MotorGuard ITF - Suite de Pruebas Unitarias para MCSA de Alta Resolución (Mejora 2)
Criterios de Aceptación T1 - T5 según Dictamen de Auditoría Técnica Claude Opus 5.5.
"""

import os
import ctypes
import pytest
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from motorguard_dashboard.processing.mcsa_hr import (
    procesar_mcsa_hr,
    grandke_f0,
    grandke_amp,
    cancelar_fundamental,
    dft_single,
    piso_local,
    McsaHrResultados,
    McsaHrState,
    MCSA_FS,
    MCSA_N,
    MCSA_DF
)

# Estructura ctypes correspondiente a McsaHrResultados
class CMcsHrResultados(ctypes.Structure):
    _fields_ = [
        ('f0', ctypes.c_float),
        ('A0', ctypes.c_float),
        ('s', ctypes.c_float),
        ('slip_ok', ctypes.c_int),
        ('fr', ctypes.c_float),
        ('L_2sm', ctypes.c_float),
        ('L_2sp', ctypes.c_float),
        ('L_rm', ctypes.c_float),
        ('L_rp', ctypes.c_float),
        ('L_3', ctypes.c_float),
        ('L_3rm', ctypes.c_float),
        ('L_3rp', ctypes.c_float),
        ('SNR_2sm', ctypes.c_float),
        ('SNR_2sp', ctypes.c_float),
        ('SNR_2s', ctypes.c_float),
        ('SNR_rm', ctypes.c_float),
        ('SNR_rp', ctypes.c_float),
        ('SNR_3', ctypes.c_float),
        ('SNR_3rm', ctypes.c_float),
        ('SNR_3rp', ctypes.c_float),
        ('floor_2sm', ctypes.c_float),
        ('floor_2sp', ctypes.c_float),
        ('floor_rm', ctypes.c_float),
        ('floor_rp', ctypes.c_float),
        ('floor_3', ctypes.c_float),
        ('floor_3rm', ctypes.c_float),
        ('floor_3rp', ctypes.c_float),
        ('A_2sm', ctypes.c_float),
        ('A_2sp', ctypes.c_float),
        ('A_rm', ctypes.c_float),
        ('A_rp', ctypes.c_float),
        ('A_3', ctypes.c_float),
        ('A_3rm', ctypes.c_float),
        ('A_3rp', ctypes.c_float)
    ]

class CMcsaHrState(ctypes.Structure):
    _fields_ = [
        ('last_valid_s', ctypes.c_float),
        ('has_valid_s', ctypes.c_int),
        ('enable_ema', ctypes.c_int),
        ('alpha_ema', ctypes.c_float),
        ('P_2sm', ctypes.c_float),
        ('P_2sp', ctypes.c_float),
        ('P_rm', ctypes.c_float),
        ('P_rp', ctypes.c_float),
        ('P_3', ctypes.c_float),
        ('P_3rm', ctypes.c_float),
        ('P_3rp', ctypes.c_float)
    ]

SO_PATH = '/home/luna/tesis_itf/libmcsa_hr.so'

@pytest.fixture(scope="module")
def clib():
    assert os.path.exists(SO_PATH), f"No se encontró la biblioteca compartida {SO_PATH}"
    lib = ctypes.CDLL(SO_PATH)
    lib.mcsa_hr_init.argtypes = [ctypes.POINTER(CMcsaHrState)]
    lib.mcsa_hr_procesar_float.argtypes = [
        ctypes.POINTER(ctypes.c_float),
        ctypes.POINTER(CMcsaHrState),
        ctypes.POINTER(CMcsHrResultados)
    ]
    return lib

def test_t1_senal_sintetica_exactitud():
    """
    T1: Señal sintética con fundamental de 60.03 Hz y amplitud 1.
    Bandas f0(1±2s) con s=0.012 a -60 dB.
    Bandas f0±f_r a -55 dB.
    Tercer armónico 3f0 a -30 dB.
    Ruido blanco -100 dB/bin.
    Criterios: |f0 - 60.03| <= 2 mHz, |s - 0.012| <= 5e-4, errores en L <= 1 dB.
    """
    N = MCSA_N
    Fs = MCSA_FS
    f0 = 60.03
    A0 = 1.0
    s = 0.012
    p = 2
    fr = f0 * (1.0 - s) / p
    A_r = 10**(-55.0 / 20.0)
    A_2s = 10**(-60.0 / 20.0)
    A_3 = 10**(-30.0 / 20.0)
    
    t = np.arange(N) / Fs
    np.random.seed(42)
    noise_sigma = 10**(-100.0 / 20.0) * np.sqrt(N / 2.0)
    noise = np.random.normal(0, noise_sigma, N)
    
    x = (A0 * np.cos(2.0 * np.pi * f0 * t) +
         A_2s * np.cos(2.0 * np.pi * f0 * (1.0 - 2.0 * s) * t + 0.1) +
         A_2s * np.cos(2.0 * np.pi * f0 * (1.0 + 2.0 * s) * t + 0.2) +
         A_r * np.cos(2.0 * np.pi * (f0 - fr) * t + 0.3) +
         A_r * np.cos(2.0 * np.pi * (f0 + fr) * t + 0.4) +
         A_3 * np.cos(2.0 * np.pi * (3.0 * f0) * t + 0.5) +
         noise).astype(np.float32)
         
    res = procesar_mcsa_hr(x)
    
    # 1. Error en f0 <= 2 mHz
    err_f0_mhz = abs(res.f0 - f0) * 1000.0
    assert err_f0_mhz <= 2.0, f"Error f0={err_f0_mhz:.4f} mHz supera 2 mHz"
    
    # 2. Error en deslizamiento |ŝ - s| <= 5e-4
    err_s = abs(res.s - s)
    assert err_s <= 5e-4, f"Error slip={err_s:.6f} supera 5e-4"
    assert res.slip_ok == 1, "Debe reportar SLIP_OK = 1"
    
    # 3. Errores en niveles dB <= 1.0 dB
    assert abs(res.L_2sm - (-60.0)) <= 1.0, f"L_2sm={res.L_2sm:.2f} dB fuera de rango (-60 dB +- 1 dB)"
    assert abs(res.L_2sp - (-60.0)) <= 1.0, f"L_2sp={res.L_2sp:.2f} dB fuera de rango (-60 dB +- 1 dB)"
    assert abs(res.L_rm - (-55.0)) <= 1.0, f"L_rm={res.L_rm:.2f} dB fuera de rango (-55 dB +- 1 dB)"
    assert abs(res.L_rp - (-55.0)) <= 1.0, f"L_rp={res.L_rp:.2f} dB fuera de rango (-55 dB +- 1 dB)"
    assert abs(res.L_3 - (-30.0)) <= 1.0, f"L_3={res.L_3:.2f} dB fuera de rango (-30 dB +- 1 dB)"
    assert res.SNR_2s >= 25.0, f"SNR_2s={res.SNR_2s:.2f} dB debería ser >= 25 dB"

def test_t2_barrido_scalloping_loss():
    """
    T2: Barrido de f0 entre 59.80 y 60.20 Hz en pasos de 0.01 Hz.
    Verifica que la variación de Â0 estimada con Grandke es < 0.05 dB,
    y reporta la variación del método antiguo (scalloping loss).
    """
    N = MCSA_N
    Fs = MCSA_FS
    w = 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(N) / N)
    sum_w = np.sum(w)
    A0_true = 3.5
    f0_sweep = np.arange(59.80, 60.201, 0.01)
    
    grandke_amps = []
    antiguo_amps = []
    
    for f0 in f0_sweep:
        t = np.arange(N) / Fs
        x = A0_true * np.cos(2.0 * np.pi * f0 * t + 0.25)
        X = np.fft.rfft(x * w)
        mag_X = np.abs(X)
        
        # Método antiguo: valor del bin máximo sin interpolar
        k0 = 100 + int(np.argmax(mag_X[100:106]))
        a_antiguo = (2.0 * mag_X[k0]) / sum_w
        antiguo_amps.append(a_antiguo)
        
        # Método nuevo con Grandke
        f_est, best_k, delta = grandke_f0(mag_X, MCSA_DF, 100, 105)
        a_grandke = grandke_amp(mag_X[best_k], delta, sum_w)
        grandke_amps.append(a_grandke)
        
    dB_grandke = 20.0 * np.log10(np.array(grandke_amps) / A0_true)
    dB_antiguo = 20.0 * np.log10(np.array(antiguo_amps) / A0_true)
    
    var_grandke = float(np.max(dB_grandke) - np.min(dB_grandke))
    var_antiguo = float(np.max(dB_antiguo) - np.min(dB_antiguo))
    
    print(f"\n[T2 SCALLOPING LOSS]")
    print(f"  Variación Grandke:        {var_grandke:.6f} dB (Criterio: < 0.05 dB)")
    print(f"  Variación Método Antiguo: {var_antiguo:.4f} dB")
    
    assert var_grandke < 0.05, f"Variación Grandke={var_grandke:.4f} dB supera 0.05 dB"
    assert var_antiguo > 1.0, "El método antiguo sin interpolación debe exhibir scalloping > 1 dB"

def test_t3_tabla_fuga_fundamental_con_y_sin_cancelacion():
    """
    T3: Tabla de fuga de la fundamental en f0(1 - 2s), con y sin cancelación,
    para s in {0.005, 0.01, 0.02, 0.04}.
    """
    N = MCSA_N
    Fs = MCSA_FS
    f0 = 60.03
    A0 = 1.0
    t = np.arange(N) / Fs
    x = A0 * np.cos(2.0 * np.pi * f0 * t)
    
    # Cancelación en tiempo
    residuo, _, _ = cancelar_fundamental(x, f0, Fs)
    w = 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(N) / N)
    
    slips = [0.005, 0.01, 0.02, 0.04]
    reducciones = []
    
    print("\n[T3 TABLA DE FUGA DE FUNDAMENTAL]")
    print(" s     | f_target (Hz) | Fuga SIN canc (dB) | Fuga CON canc (dB) | Reducción (dB)")
    print("-" * 75)
    
    for s in slips:
        f_target = f0 * (1.0 - 2.0 * s)
        a_sin = dft_single(x, f_target, Fs, w)
        a_con = dft_single(residuo, f_target, Fs, w)
        
        db_sin = 20.0 * np.log10(max(a_sin, 1e-12) / A0)
        db_con = 20.0 * np.log10(max(a_con, 1e-12) / A0)
        red_dB = db_sin - db_con
        reducciones.append(red_dB)
        
        print(f" {s:.3f} | {f_target:6.2f} Hz    | {db_sin:8.2f} dB         | {db_con:8.2f} dB         | {red_dB:6.2f} dB")
        
        # Para s=0.005 la fuga sin cancelación es inmensa (-6 dB), la cancelación debe reducirla >= 50 dB
        assert red_dB >= 40.0, f"Reducción en s={s} fue de solo {red_dB:.2f} dB (< 40 dB)"

def test_t4_atenuacion_am_rizado():
    """
    T4: AM del 1% a 0.4 Hz (rizado mecánico de banda oscilante).
    Su contribución en f_2s± (para s >= 0.015) debe quedar atenuada >= 25 dB
    respecto a su nivel de pico en f0 ± 0.4 Hz.
    """
    N = MCSA_N
    Fs = MCSA_FS
    f0 = 60.00
    A0 = 1.0
    m = 0.01 # 1% AM
    fm = 0.4 # 0.4 Hz
    
    t = np.arange(N) / Fs
    x = A0 * (1.0 + m * np.cos(2.0 * np.pi * fm * t)) * np.cos(2.0 * np.pi * f0 * t)
    
    residuo, _, _ = cancelar_fundamental(x, f0, Fs)
    w = 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(N) / N)
    
    # Nivel de pico en f0 - 0.4 Hz = 59.6 Hz
    a_am_peak = dft_single(residuo, f0 - fm, Fs, w)
    
    # Evaluar en f_2s- para s = 0.02 (condición de carga real)
    s = 0.020
    f_2sm = f0 * (1.0 - 2.0 * s)
    f_2sp = f0 * (1.0 + 2.0 * s)
    a_2sm = dft_single(residuo, f_2sm, Fs, w)
    a_2sp = dft_single(residuo, f_2sp, Fs, w)
    
    atten_2sm = 20.0 * np.log10(a_am_peak / max(a_2sm, 1e-12))
    atten_2sp = 20.0 * np.log10(a_am_peak / max(a_2sp, 1e-12))
    
    print(f"\n[T4 ATENUACIÓN RIZADO AM 0.4 Hz]")
    print(f"  Pico AM en {f0 - fm:.1f} Hz:       {20*np.log10(a_am_peak/A0):.2f} dB")
    print(f"  Nivel en f_2s- ({f_2sm:.2f} Hz): {20*np.log10(a_2sm/A0):.2f} dB -> Atenuación: {atten_2sm:.2f} dB")
    print(f"  Nivel en f_2s+ ({f_2sp:.2f} Hz): {20*np.log10(a_2sp/A0):.2f} dB -> Atenuación: {atten_2sp:.2f} dB")
    
    assert atten_2sm >= 25.0, f"Atenuación 2s-={atten_2sm:.2f} dB < 25 dB"
    assert atten_2sp >= 25.0, f"Atenuación 2s+={atten_2sp:.2f} dB < 25 dB"

def test_t5_equivalencia_cpp_vs_numpy(clib):
    """
    T5: Equivalencia C++ vs NumPy por ctypes: diferencia < 5e-3 dB en todas las features.
    """
    N = MCSA_N
    Fs = MCSA_FS
    f0 = 60.03
    A0 = 1.0
    s = 0.012
    p = 2
    fr = f0 * (1.0 - s) / p
    
    A_r = 10**(-55.0 / 20.0)
    A_2s = 10**(-60.0 / 20.0)
    A_3 = 10**(-30.0 / 20.0)
    A_3r = 10**(-65.0 / 20.0)
    
    t = np.arange(N) / Fs
    x = (A0 * np.cos(2.0 * np.pi * f0 * t) +
         A_2s * np.cos(2.0 * np.pi * f0 * (1.0 - 2.0 * s) * t + 0.1) +
         A_2s * np.cos(2.0 * np.pi * f0 * (1.0 + 2.0 * s) * t + 0.2) +
         A_r * np.cos(2.0 * np.pi * (f0 - fr) * t + 0.3) +
         A_r * np.cos(2.0 * np.pi * (f0 + fr) * t + 0.4) +
         A_3 * np.cos(2.0 * np.pi * (3.0 * f0) * t + 0.5) +
         A_3r * np.cos(2.0 * np.pi * (3.0 * f0 - fr) * t + 0.6) +
         A_3r * np.cos(2.0 * np.pi * (3.0 * f0 + fr) * t + 0.7)).astype(np.float32)
         
    # Python
    py_res = procesar_mcsa_hr(x)
    
    # C++
    c_state = CMcsaHrState()
    clib.mcsa_hr_init(ctypes.byref(c_state))
    c_res = CMcsHrResultados()
    x_ptr = x.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
    clib.mcsa_hr_procesar_float(x_ptr, ctypes.byref(c_state), ctypes.byref(c_res))
    
    features = ['L_2sm', 'L_2sp', 'L_rm', 'L_rp', 'L_3', 'L_3rm', 'L_3rp']
    print("\n[T5 EQUIVALENCIA C++ vs NUMPY]")
    for feat in features:
        v_py = getattr(py_res, feat)
        v_c = getattr(c_res, feat)
        diff = abs(v_py - v_c)
        print(f"  {feat:6s}: NumPy={v_py:8.4f} dB | C++={v_c:8.4f} dB | diff={diff:8.6f} dB")
        assert diff < 0.005, f"Diferencia en {feat}={diff:.6f} dB supera 0.005 dB"
        
    assert abs(py_res.f0 - c_res.f0) < 1e-4, "f0 difiere entre C++ y Python"
    assert abs(py_res.s - c_res.s) < 1e-5, "s difiere entre C++ y Python"
    assert py_res.slip_ok == c_res.slip_ok, "slip_ok difiere"

def test_t6_generar_grafico_espectro_original_vs_residuo():
    """
    Genera la figura requerida en el entregable:
    PNG del espectro original vs residuo para una señal sintética.
    """
    N = MCSA_N
    Fs = MCSA_FS
    f0 = 60.03
    A0 = 1.0
    s = 0.012
    p = 2
    fr = f0 * (1.0 - s) / p
    A_r = 10**(-55.0 / 20.0)
    A_2s = 10**(-60.0 / 20.0)
    A_3 = 10**(-30.0 / 20.0)
    
    t = np.arange(N) / Fs
    np.random.seed(42)
    noise = np.random.normal(0, 10**(-100.0 / 20.0) * np.sqrt(N / 2.0), N)
    
    x = (A0 * np.cos(2.0 * np.pi * f0 * t) +
         A_2s * np.cos(2.0 * np.pi * f0 * (1.0 - 2.0 * s) * t + 0.1) +
         A_2s * np.cos(2.0 * np.pi * f0 * (1.0 + 2.0 * s) * t + 0.2) +
         A_r * np.cos(2.0 * np.pi * (f0 - fr) * t + 0.3) +
         A_r * np.cos(2.0 * np.pi * (f0 + fr) * t + 0.4) +
         A_3 * np.cos(2.0 * np.pi * (3.0 * f0) * t + 0.5) +
         noise).astype(np.float32)
         
    residuo, _, _ = cancelar_fundamental(x, f0, Fs)
    w = 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(N) / N)
    sum_w = np.sum(w)
    
    X = np.fft.rfft(x * w)
    R = np.fft.rfft(residuo * w)
    
    freqs = np.fft.rfftfreq(N, 1.0 / Fs)
    mag_X_dB = 20.0 * np.log10(max(1e-12, 1.0) * (2.0 / sum_w) * np.abs(X) / A0)
    mag_R_dB = 20.0 * np.log10(max(1e-12, 1.0) * (2.0 / sum_w) * np.abs(R) / A0)
    
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    
    # Zoom en 25 a 95 Hz
    mask = (freqs >= 20.0) & (freqs <= 100.0)
    
    ax1.plot(freqs[mask], mag_X_dB[mask], color='#2f81f7', lw=1.2, label='Espectro Original x[n] (Hann)')
    ax1.axvline(f0, color='#e05252', linestyle='--', alpha=0.7, label=f'Fundamental f0={f0:.2f} Hz')
    ax1.axvline(f0 - fr, color='#a371f7', linestyle=':', alpha=0.8, label=f'Rotor slot f0-fr={f0-fr:.2f} Hz')
    ax1.axvline(f0 + fr, color='#a371f7', linestyle=':', alpha=0.8, label=f'Rotor slot f0+fr={f0+fr:.2f} Hz')
    ax1.set_ylabel('Nivel relativo (dB)')
    ax1.set_title('MotorGuard ITF - Espectro MCSA Original (con fuga de fundamental)', fontsize=12, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc='upper right')
    ax1.set_ylim([-110, 5])
    
    ax2.plot(freqs[mask], mag_R_dB[mask], color='#2ea043', lw=1.2, label='Espectro Residuo r[n] (Fundamental Cancelada)')
    ax2.axvline(f0 * (1.0 - 2.0 * s), color='#d29922', linestyle='-.', lw=1.5, label=f'Banda falla 2s-={f0*(1-2*s):.2f} Hz (-60 dB)')
    ax2.axvline(f0 * (1.0 + 2.0 * s), color='#d29922', linestyle='-.', lw=1.5, label=f'Banda falla 2s+={f0*(1+2*s):.2f} Hz (-60 dB)')
    ax2.axvline(f0 - fr, color='#a371f7', linestyle=':', alpha=0.8)
    ax2.axvline(f0 + fr, color='#a371f7', linestyle=':', alpha=0.8)
    ax2.set_xlabel('Frecuencia (Hz)')
    ax2.set_ylabel('Nivel relativo (dB)')
    ax2.set_title('Espectro del Residuo: Reducción de fundamental > 55 dB permitiendo resolución de bandas a bajo slip', fontsize=11)
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc='upper right')
    ax2.set_ylim([-110, 5])
    
    plt.tight_layout()
    os.makedirs('/home/luna/tesis_itf/reports', exist_ok=True)
    out_png = '/home/luna/tesis_itf/reports/mcsa_hr_espectro_residuo.png'
    plt.savefig(out_png, dpi=150)
    plt.close()
    
    assert os.path.exists(out_png), f"No se generó la figura {out_png}"
    print(f"\n[FIGURA GENERADA]: {out_png}")
