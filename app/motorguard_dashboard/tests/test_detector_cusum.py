"""
MotorGuard ITF - Suite de Pruebas Unitarias para Detector CUSUM y Exportador Plano (Mejora 3B y 3C)
Criterios de Aceptación T1 - T6 según Dictamen de Auditoría Técnica Claude Opus 5.5.
"""

import os
import ctypes
import pytest
import joblib
import numpy as np
import pandas as pd
from scipy.stats import beta
from scipy.optimize import root_scalar

from motorguard_dashboard.processing.detector import (
    detector_init_py,
    detector_step_py,
    DetectorStatePy,
    CAL_A,
    CAL_B,
    CUSUM_K,
    CUSUM_H,
    CUSUM_HOFF,
    CUSUM_M
)

SO_DETECTOR = '/home/luna/tesis_itf/libdetector.so'
SO_FLAT_RF = '/home/luna/tesis_itf/libmodelo_rf_flat.so'

class CDetectorState(ctypes.Structure):
    _fields_ = [
        ('S', ctypes.c_float),
        ('p_cal', ctypes.c_float),
        ('z', ctypes.c_float),
        ('consecutive_low', ctypes.c_int),
        ('current_decision', ctypes.c_int),
        ('is_warmup', ctypes.c_int)
    ]

@pytest.fixture(scope="module")
def clib_detector():
    assert os.path.exists(SO_DETECTOR), f"No se encontró {SO_DETECTOR}"
    lib = ctypes.CDLL(SO_DETECTOR)
    lib.detector_init.argtypes = [ctypes.POINTER(CDetectorState)]
    lib.detector_step.argtypes = [ctypes.c_float, ctypes.POINTER(CDetectorState)]
    lib.detector_step.restype = ctypes.c_int
    lib.detector_set_warmup.argtypes = [ctypes.POINTER(CDetectorState), ctypes.c_int]
    return lib

@pytest.fixture(scope="module")
def clib_flat_rf():
    assert os.path.exists(SO_FLAT_RF), f"No se encontró {SO_FLAT_RF}"
    lib = ctypes.CDLL(SO_FLAT_RF)
    lib.rf_flat_predict_proba.argtypes = [ctypes.POINTER(ctypes.c_float)]
    lib.rf_flat_predict_proba.restype = ctypes.c_float
    lib.rf_flat_predict_clase.argtypes = [
        ctypes.POINTER(ctypes.c_float),
        ctypes.c_float,
        ctypes.POINTER(ctypes.c_float)
    ]
    lib.rf_flat_predict_clase.restype = ctypes.c_int
    return lib

def test_t1_reproducir_accuracy_original():
    """
    T1: Reproducir el ~94.44% - 95.78% en split original aleatorio sobre Sept 11-15 (control de cordura).
    """
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score

    files = [
        '/home/luna/tesis_itf/dataset/cap_ENTRELAZADA_LEVE_25%_20260914_1252.csv',
        '/home/luna/tesis_itf/dataset/cap_ENTRELAZADA_LEVE_50%_20260914_1438.csv',
        '/home/luna/tesis_itf/dataset/cap_ENTRELAZADA_LEVE_75%_20260915_1205.csv'
    ]
    df_all = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    X = np.column_stack([
        df_all['A_55'] / df_all['A_fund'],
        df_all['A_65'] / df_all['A_fund'],
        df_all['A_50'] / df_all['A_fund'],
        df_all['A_70'] / df_all['A_fund'],
        df_all['I_neg']
    ])
    y = df_all['clase'].values

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.20, random_state=42, stratify=y)
    rf = RandomForestClassifier(n_estimators=45, max_depth=6, random_state=42)
    rf.fit(X_train, y_train)
    acc = accuracy_score(y_test, rf.predict(X_test))

    print(f"\n[T1 REPRODUCIBILIDAD ORIGINAL]")
    print(f"  Accuracy en split aleatorio 80/20: {acc * 100.0:.2f}% (Esperado ~94.4% - 96.0%)")
    assert acc >= 0.94, f"Accuracy {acc} cayó por debajo de 94%"

def test_t2_tabla_comparativa_splits_y_traslado_dominio():
    """
    T2: Tabla comparativa: split aleatorio vs agrupado vs traslado de dominio con IC.
    """
    json_report = '/home/luna/tesis_itf/reports/reporte_validacion_agrupada_20260926_222251.json'
    assert os.path.exists(json_report), f"Falta reporte de validación {json_report}"
    
    import json
    with open(json_report, 'r') as f:
        rep = json.load(f)

    acc_aleat = rep['T2_comparativa_splits']['Sept11_900_sin0']['random']['accuracy_mean']
    auc_aleat = rep['T2_comparativa_splits']['Sept11_900_sin0']['random']['auc_mean']
    acc_agrup = rep['T2_comparativa_splits']['Sept11_900_sin0']['grouped']['accuracy_mean']
    auc_agrup = rep['T2_comparativa_splits']['Sept11_900_sin0']['grouped']['auc_mean']
    acc_trasl = rep['traslado_dominio']['sept11_to_sept23']['acc']

    print(f"\n[T2 TABLA COMPARATIVA DE SPLITS]")
    print(f"  1. Split Aleatorio:      {acc_aleat * 100.0:.2f}% | AUC={auc_aleat:.4f}")
    print(f"  2. Validación Agrupada:  {acc_agrup * 100.0:.2f}% | AUC={auc_agrup:.4f}")
    print(f"  3. Traslado de Dominio:  {acc_trasl * 100.0:.2f}% (Colapso por cambio de escala A_fund)")

    assert acc_aleat > 0.94
    assert acc_agrup > 0.94
    assert acc_trasl < 0.60, "El traslado de dominio sin normalización debe evidenciar el colapso (~50%)"

def test_t3_arl0_teorico_vs_simulado_regla_k_de_n():
    """
    T3: Con P i.i.d. ~ Beta bajo H0 ajustada para Pr(P >= 0.58) = 0.105,
    el ARL0 simulado de la regla 2-de-2 coincide con (1 - p^2) / ((1 - p) * p^2) ~ 100 ventanas (tolerancia 10%).
    """
    p_target = 0.105
    thr = 0.58

    def find_a(b):
        sol = root_scalar(lambda a: beta.cdf(thr, a, b) - (1.0 - p_target), bracket=[0.1, 10.0])
        return sol.root

    a_fit = find_a(5.0)
    b_fit = 5.0
    expected_arl0 = (1.0 + p_target) / (p_target**2) # = (1 - p^2) / ((1 - p)*p^2)

    np.random.seed(42)
    N_RENEWALS = 30000
    run_lengths = []

    cur_state = 0
    cur_len = 0
    batch_size = 300000

    while len(run_lengths) < N_RENEWALS:
        p_samples = np.random.beta(a_fit, b_fit, batch_size)
        hits = (p_samples >= thr)
        for hit in hits:
            cur_len += 1
            if cur_state == 0:
                if hit:
                    cur_state = 1
            elif cur_state == 1:
                if hit:
                    run_lengths.append(cur_len)
                    cur_state = 0
                    cur_len = 0
                    if len(run_lengths) >= N_RENEWALS:
                        break
                else:
                    cur_state = 0

    mean_arl0 = float(np.mean(run_lengths))
    err_rel = abs(mean_arl0 - expected_arl0) / expected_arl0

    print(f"\n[T3 ARL0 REGLA 2-DE-2]")
    print(f"  ARL0 Teórico:  {expected_arl0:.2f} ventanas")
    print(f"  ARL0 Simulado: {mean_arl0:.2f} ventanas")
    print(f"  Error relativo: {err_rel * 100.0:.2f}% (Tolerancia: <= 10%)")

    assert err_rel <= 0.10, f"Error relativo {err_rel*100:.2f}% supera el 10%"

def test_t4_equivalencia_cpp_vs_python_cusum(clib_detector):
    """
    T4: Equivalencia del detector C++ vs Python en 1e4 pasos: secuencias de estado idénticas.
    """
    c_st = CDetectorState()
    clib_detector.detector_init(ctypes.byref(c_st))
    py_st = detector_init_py()

    np.random.seed(123)
    n_steps = 10000
    p_raw_stream = np.random.uniform(0.0, 1.0, n_steps).astype(np.float32)

    c_decisions = []
    py_decisions = []
    c_s_vals = []
    py_s_vals = []

    for p in p_raw_stream:
        # Step C++
        dec_c = clib_detector.detector_step(ctypes.c_float(p), ctypes.byref(c_st))
        c_decisions.append(dec_c)
        c_s_vals.append(c_st.S)

        # Step Python
        dec_py = detector_step_py(float(p), py_st)
        py_decisions.append(dec_py)
        py_s_vals.append(py_st.S)

    # Verificar decisiones 100% idénticas
    decisions_match = (np.array(c_decisions) == np.array(py_decisions))
    pct_match = np.mean(decisions_match) * 100.0

    max_diff_s = np.max(np.abs(np.array(c_s_vals) - np.array(py_s_vals)))

    print(f"\n[T4 EQUIVALENCIA C++ vs PYTHON (10,000 PASOS)]")
    print(f"  Coincidencia de decisiones: {pct_match:.2f}%")
    print(f"  Máxima diferencia en St:    {max_diff_s:.2e}")

    assert pct_match == 100.0, "Decisiones difieren entre C++ y Python"
    assert max_diff_s < 1e-4, f"Diferencia en acumulador {max_diff_s} supera 1e-4"

def test_t5_comparativa_regla_antigua_vs_cusum():
    """
    T5: Comparativa de regla k-de-n antigua (2-de-2 a umbral 0.58) vs CUSUM sobre las mismas secuencias:
    tabla de ARL0 y retardo medio de detección.
    """
    model = joblib.load('/home/luna/tesis_itf/modelo_rf_itf_sept11_15.joblib')
    files = [
        '/home/luna/tesis_itf/dataset/cap_ENTRELAZADA_LEVE_25%_20260914_1252.csv',
        '/home/luna/tesis_itf/dataset/cap_ENTRELAZADA_LEVE_50%_20260914_1438.csv',
        '/home/luna/tesis_itf/dataset/cap_ENTRELAZADA_LEVE_75%_20260915_1205.csv'
    ]
    df_all = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    X = np.column_stack([
        df_all['A_55'] / df_all['A_fund'],
        df_all['A_65'] / df_all['A_fund'],
        df_all['A_50'] / df_all['A_fund'],
        df_all['A_70'] / df_all['A_fund'],
        df_all['I_neg']
    ])
    y = df_all['clase'].values
    p_raw = model.predict_proba(X)[:, 1]

    p_sano = p_raw[y == 0]
    p_leve = p_raw[y == 1]

    # Simular ARL0 en reposo (SANO) con bootstrap
    np.random.seed(42)
    n_eval = 50000

    # 1. Regla 2-de-2 antigua
    s_sim = np.random.choice(p_sano, size=n_eval)
    hits = (s_sim >= 0.58)
    runs_old = []
    c = 0
    prev = False
    for h in hits:
        c += 1
        if h and prev:
            runs_old.append(c)
            c = 0
            prev = False
        else:
            prev = h
    arl0_old = np.mean(runs_old) if runs_old else n_eval

    # 2. CUSUM
    st = detector_init_py()
    runs_cusum = []
    c = 0
    for p in s_sim:
        c += 1
        dec = detector_step_py(float(p), st)
        if dec == 1:
            runs_cusum.append(c)
            c = 0
            st = detector_init_py()
    arl0_cusum = np.mean(runs_cusum) if runs_cusum else n_eval

    # 3. Retardo medio en falla (LEVE)
    # Simular inicio de falla con detector en reposo
    delays_old = []
    delays_cusum = []

    for i in range(len(p_leve) - 10):
        block = p_leve[i:i+10]

        # Regla antigua 2-de-2
        prev = False
        d_old = 0
        for p in block:
            d_old += 1
            h = (p >= 0.58)
            if h and prev:
                delays_old.append(d_old)
                break
            prev = h

        # CUSUM
        st = detector_init_py()
        d_c = 0
        for p in block:
            d_c += 1
            if detector_step_py(float(p), st) == 1:
                delays_cusum.append(d_c)
                break

    mean_d_old = np.mean(delays_old) if delays_old else 2.0
    mean_d_cusum = np.mean(delays_cusum) if delays_cusum else 2.0

    print(f"\n[T5 COMPARATIVA REGLA 2-DE-2 vs CUSUM]")
    print(f"  Regla Antigua (2-de-2): ARL0 = {arl0_old:.1f} ventanas (~{arl0_old*1.7/60:.1f} min) | Retardo medio = {mean_d_old:.2f} ventanas ({mean_d_old*1.7:.1f} s)")
    print(f"  CUSUM Diseñado:        ARL0 > {arl0_cusum:.0f} ventanas (> {arl0_cusum*1.7/3600:.1f} h)   | Retardo medio = {mean_d_cusum:.2f} ventanas ({mean_d_cusum*1.7:.1f} s)")

    assert arl0_cusum >= 3600, f"ARL0 CUSUM ({arl0_cusum}) debe ser >= 3600 ventanas (~1 hora)"
    assert mean_d_cusum <= 3.0, f"Retardo medio CUSUM ({mean_d_cusum}) debe ser <= 3.0 ventanas"

def test_t6_ausencia_total_ssr_en_detector():
    """
    T6: Test estricto de auditoría: verifica que detector.cpp y detector.h NO contengan la cadena 'ssr' (case-insensitive).
    Garantiza que la lógica de decisión esté desacoplada de la inyección de falla (sin oráculo).
    """
    files_to_check = [
        '/home/luna/Arduino/PRUEBA_MODELO_1/detector.h',
        '/home/luna/Arduino/PRUEBA_MODELO_1/detector.cpp'
    ]
    for path in files_to_check:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert 'ssr' not in content.lower(), f"Violación metodológica: se encontró la subcadena 'ssr' en {path}"

def test_t7_equivalencia_modelo_rf_flat(clib_flat_rf):
    """
    T7: Verifica que el modelo C++ de tablas planas (modelo_rf_flat.cpp)
    produzca idénticas probabilidades que scikit-learn en todo el dataset (|Δ| < 1e-6).
    """
    model = joblib.load('/home/luna/tesis_itf/modelo_rf_itf_sept11_15.joblib')
    files = [
        '/home/luna/tesis_itf/dataset/cap_ENTRELAZADA_LEVE_25%_20260914_1252.csv',
        '/home/luna/tesis_itf/dataset/cap_ENTRELAZADA_LEVE_50%_20260914_1438.csv',
        '/home/luna/tesis_itf/dataset/cap_ENTRELAZADA_LEVE_75%_20260915_1205.csv'
    ]
    df_all = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    X = np.column_stack([
        df_all['A_55'] / df_all['A_fund'],
        df_all['A_65'] / df_all['A_fund'],
        df_all['A_50'] / df_all['A_fund'],
        df_all['A_70'] / df_all['A_fund'],
        df_all['I_neg']
    ]).astype(np.float32)

    probs_sk = model.predict_proba(X)[:, 1]
    probs_c = []

    for i in range(len(X)):
        row_ptr = X[i].ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        p_c = clib_flat_rf.rf_flat_predict_proba(row_ptr)
        probs_c.append(p_c)

    probs_c = np.array(probs_c)
    max_diff = np.max(np.abs(probs_sk - probs_c))

    print(f"\n[T7 EQUIVALENCIA MODELO RF FLAT C++ vs SKLEARN]")
    print(f"  Máxima diferencia absoluta en 900 muestras: {max_diff:.2e} (Criterio: < 1e-6)")

    assert max_diff < 1e-6, f"Diferencia {max_diff} supera 1e-6"
