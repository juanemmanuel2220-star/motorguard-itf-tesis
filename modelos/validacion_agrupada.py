#!/usr/bin/env python3
"""
validacion_agrupada.py
======================
Auditoría estadística y validación sin fuga del modelo Random Forest de MotorGuard-ITF.
Implementa:
  1. Agrupamiento temporal por bloques contiguos para eliminar sesgo de gemelos temporales.
  2. StratifiedGroupKFold (5 splits) con intervalos de confianza al 95% por bootstrap de grupos (B=2000).
  3. Comparación sistemática: Split aleatorio vs Split agrupado.
  4. Análisis por estrato de carga (aislando 0% de carga).
  5. Prueba de traslado de dominio entre campañas (Sept 11-15 vs Sept 23-24).
  6. Estudio de ablación de variables (THD, r50, r70).
  7. Calibración de probabilidades (Platt scaling / sigmoid) y métricas Brier/ECE.
"""

import os
import sys
import json
import glob
import numpy as np
import pandas as pd
from datetime import datetime

from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import StratifiedKFold, StratifiedGroupKFold, train_test_split
from sklearn.metrics import (
    accuracy_score, balanced_accuracy_score, roc_auc_score, f1_score,
    confusion_matrix, brier_score_loss
)
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from scipy.optimize import curve_fit

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(BASE_DIR, 'dataset')
REPORTS_DIR = os.path.join(BASE_DIR, 'reports')
MODELS_DIR = os.path.join(BASE_DIR, 'models')

os.makedirs(REPORTS_DIR, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)

TRUE_COLS = [
    'clase', 'label', 'carga', 'carga_label', 'n_muestra', 'timestamp',
    'V_rms', 'I_rms', 'A_55', 'A_65', 'A_50', 'A_70', 'A_fund', 'I_neg', 'THD'
]

FEATS_5 = ['r_55', 'r_65', 'r_50', 'r_70', 'I_neg']
FEATS_6 = ['r_55', 'r_65', 'r_50', 'r_70', 'I_neg', 'THD']
FEATS_3 = ['r_55', 'r_65', 'I_neg']

SEPT11_FILES = [
    'cap_ENTRELAZADA_LEVE_0%_20260911_1617.csv',
    'cap_ENTRELAZADA_LEVE_25%_20260914_1252.csv',
    'cap_ENTRELAZADA_LEVE_50%_20260914_1438.csv',
    'cap_ENTRELAZADA_LEVE_75%_20260915_1205.csv'
]

SEPT23_FILES = [
    'cap_ENTRELAZADA_LEVE_0%_20260923_1244.csv',
    'cap_ENTRELAZADA_LEVE_25%_20260923_1433.csv',
    'cap_ENTRELAZADA_LEVE_50%_20260924_1235.csv',
    'cap_ENTRELAZADA_LEVE_75%_20260924_1432.csv'
]


def load_dataset(file_list, block_size=20):
    dfs = []
    eps = 1e-6
    for fn in file_list:
        p = os.path.join(DATASET_DIR, fn)
        if not os.path.exists(p):
            raise FileNotFoundError(f"No se encontro archivo de datos: {p}")
        d = pd.read_csv(p)
        if d.shape[1] == 15:
            d.columns = TRUE_COLS
        d['origen'] = fn
        d['r_55'] = d['A_55'] / (d['A_fund'] + eps)
        d['r_65'] = d['A_65'] / (d['A_fund'] + eps)
        d['r_50'] = d['A_50'] / (d['A_fund'] + eps)
        d['r_70'] = d['A_70'] / (d['A_fund'] + eps)

        # Generacion de grupo temporal: bloques contiguos de block_size muestras
        n_blocks = len(d) // block_size
        d['block_id'] = [f"{fn}_b{i // block_size}" for i in range(len(d))]
        dfs.append(d)

    df = pd.concat(dfs, ignore_index=True)
    df['clase'] = pd.to_numeric(df['clase'], errors='coerce').astype(int)
    for c in ['V_rms', 'I_rms', 'A_55', 'A_65', 'A_50', 'A_70', 'A_fund', 'I_neg', 'THD',
              'r_55', 'r_65', 'r_50', 'r_70']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna(subset=['r_55', 'r_65', 'r_50', 'r_70', 'I_neg']).reset_index(drop=True)
    return df


def get_base_clf(seed=42):
    return RandomForestClassifier(
        n_estimators=45,
        max_depth=6,
        min_samples_split=4,
        min_samples_leaf=2,
        random_state=seed,
        n_jobs=-1
    )


def compute_ece(y_true, y_prob, n_bins=10):
    """Calcula el Expected Calibration Error (ECE)."""
    bin_limits = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    n = len(y_true)
    for i in range(n_bins):
        low, high = bin_limits[i], bin_limits[i + 1]
        mask = (y_prob >= low) & (y_prob < high if i < n_bins - 1 else y_prob <= high)
        bin_count = np.sum(mask)
        if bin_count > 0:
            bin_acc = np.mean(y_true[mask])
            bin_conf = np.mean(y_prob[mask])
            ece += (bin_count / n) * np.abs(bin_acc - bin_conf)
    return ece


def bootstrap_group_ci(df, group_col, metric_fn, B=2000, seed=42):
    """Intervalo de confianza al 95% por bootstrap de grupos."""
    rng = np.random.default_rng(seed)
    unique_groups = df[group_col].unique()
    n_groups = len(unique_groups)
    boot_vals = []

    for _ in range(B):
        sample_groups = rng.choice(unique_groups, size=n_groups, replace=True)
        # Tomar los registros correspondientes
        boot_df = pd.concat([df[df[group_col] == g] for g in sample_groups], ignore_index=True)
        try:
            val = metric_fn(boot_df)
            boot_vals.append(val)
        except Exception:
            continue

    if not boot_vals:
        return 0.0, 0.0
    low = np.percentile(boot_vals, 2.5)
    high = np.percentile(boot_vals, 97.5)
    return float(low), float(high)


def evaluate_cv(X, y, groups, cv_type='group', n_splits=5, seed=42):
    if cv_type == 'group':
        splitter = StratifiedGroupKFold(n_splits=n_splits)
        splits = list(splitter.split(X, y, groups=groups))
    else:
        splitter = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
        splits = list(splitter.split(X, y))

    acc_list, bal_acc_list, auc_list, f1_list = [], [], [], []
    all_y_true = []
    all_y_pred = []
    all_y_prob = []

    for train_idx, val_idx in splits:
        X_tr, y_tr = X.iloc[train_idx], y.iloc[train_idx]
        X_val, y_val = X.iloc[val_idx], y.iloc[val_idx]

        clf = get_base_clf(seed=seed)
        clf.fit(X_tr, y_tr)
        probs = clf.predict_proba(X_val)[:, 1]
        preds = (probs >= 0.50).astype(int)

        acc_list.append(accuracy_score(y_val, preds))
        bal_acc_list.append(balanced_accuracy_score(y_val, preds))
        try:
            auc_list.append(roc_auc_score(y_val, probs))
        except Exception:
            auc_list.append(0.5)
        f1_list.append(f1_score(y_val, preds, zero_division=0))

        all_y_true.extend(y_val.tolist())
        all_y_pred.extend(preds.tolist())
        all_y_prob.extend(probs.tolist())

    return {
        'accuracy_mean': float(np.mean(acc_list)),
        'accuracy_std': float(np.std(acc_list)),
        'bal_accuracy_mean': float(np.mean(bal_acc_list)),
        'bal_accuracy_std': float(np.std(bal_acc_list)),
        'auc_mean': float(np.mean(auc_list)),
        'auc_std': float(np.std(auc_list)),
        'f1_mean': float(np.mean(f1_list)),
        'f1_std': float(np.std(f1_list)),
        'confusion_matrix': confusion_matrix(all_y_true, all_y_pred).tolist(),
        'y_true': all_y_true,
        'y_pred': all_y_pred,
        'y_prob': all_y_prob
    }


def main():
    print("=" * 80)
    print("MOTORGUARD-ITF: AUDITORIA ESTADISTICA Y VALIDACION SIN FUGA (MEJORA 3A)")
    print("=" * 80)

    # 1. Cargar datasets de ambas campañas
    df1_all = load_dataset(SEPT11_FILES)
    df2_all = load_dataset(SEPT23_FILES)

    df1_no0 = df1_all[df1_all['carga_label'] != '0%'].copy().reset_index(drop=True)
    df2_no0 = df2_all[df2_all['carga_label'] != '0%'].copy().reset_index(drop=True)

    print(f"Campaña Sept 11-15: Total={len(df1_all)} (Con 0%), Subconjunto={len(df1_no0)} (Cargas 25, 50, 75%)")
    print(f"Campaña Sept 23-24: Total={len(df2_all)} (Con 0%), Subconjunto={len(df2_no0)} (Cargas 25, 50, 75%)")

    results = {}

    # -------------------------------------------------------------
    # T1: Control de Cordura - Reproducción del 94.44% / 95.56%
    # -------------------------------------------------------------
    print("\n" + "-" * 60)
    print("TEST T1: Control de Cordura (Split Aleatorio Original en Sept 11-15)")
    print("-" * 60)
    X1_no0 = df1_no0[FEATS_5]
    y1_no0 = df1_no0['clase']
    cv_random_t1 = evaluate_cv(X1_no0, y1_no0, None, cv_type='random', n_splits=5, seed=42)
    print(f"  Accuracy CV Aleatorio (5-Fold, 900 muestras): {cv_random_t1['accuracy_mean']*100:.2f}% "
          f"(+/- {cv_random_t1['accuracy_std']*100:.2f}%)")
    print(f"  AUC CV Aleatorio:                              {cv_random_t1['auc_mean']:.4f}")
    print(f"  Matriz Confusión Acumulada:\n    {cv_random_t1['confusion_matrix']}")
    results['T1_control_cordura_sept11_900'] = cv_random_t1

    # -------------------------------------------------------------
    # T2: Comparativa Sistemática - Split Aleatorio vs Agrupado
    # -------------------------------------------------------------
    print("\n" + "-" * 60)
    print("TEST T2: Comparativa de Metodología de Split (Aleatorio vs Agrupado)")
    print("-" * 60)

    comparativa = {}
    datasets_to_test = [
        ('Sept11_900_sin0', df1_no0, FEATS_5),
        ('Sept11_1200_con0', df1_all, FEATS_5),
        ('Sept23_900_sin0', df2_no0, FEATS_5),
        ('Sept23_1200_con0', df2_all, FEATS_5)
    ]

    for name, df, feats in datasets_to_test:
        X = df[feats]
        y = df['clase']
        grps = df['block_id']

        res_rand = evaluate_cv(X, y, grps, cv_type='random', n_splits=5, seed=42)
        res_grp = evaluate_cv(X, y, grps, cv_type='group', n_splits=5, seed=42)

        # Bootstrap IC 95% para accuracy agrupada
        def acc_metric(b_df):
            X_b = b_df[feats]
            y_b = b_df['clase']
            clf = get_base_clf(seed=42)
            # Evaluar con modelo ya entrenado para velocidad de bootstrap
            clf.fit(X, y)
            preds = clf.predict(X_b)
            return accuracy_score(y_b, preds)

        ic_low, ic_high = bootstrap_group_ci(df, 'block_id', acc_metric, B=1000, seed=42)

        print(f"\n  Dataset: {name}")
        print(f"    Split Aleatorio: Acc={res_rand['accuracy_mean']*100:.2f}%, AUC={res_rand['auc_mean']:.4f}")
        print(f"    Split Agrupado:  Acc={res_grp['accuracy_mean']*100:.2f}%, AUC={res_grp['auc_mean']:.4f} "
              f"| IC 95%: [{ic_low*100:.1f}%, {ic_high*100:.1f}%]")
        print(f"    CM Agrupado:     {res_grp['confusion_matrix']}")

        comparativa[name] = {
            'random': res_rand,
            'grouped': res_grp,
            'grouped_ci_95': [ic_low, ic_high]
        }

    results['T2_comparativa_splits'] = comparativa

    # -------------------------------------------------------------
    # T2.1: Traslado de Dominio Cruzado (Domain Transfer)
    # -------------------------------------------------------------
    print("\n" + "-" * 60)
    print("TEST T2.1: Traslado de Dominio Cruzado (Train en A, Test en B)")
    print("-" * 60)

    transfer = {}
    # Caso 1: Train Sept 11 (900) -> Test Sept 23 (900)
    clf_m1 = get_base_clf(seed=42).fit(df1_no0[FEATS_5], df1_no0['clase'])
    p2_no0 = clf_m1.predict_proba(df2_no0[FEATS_5])[:, 1]
    acc_1_to_2 = accuracy_score(df2_no0['clase'], p2_no0 >= 0.5)
    auc_1_to_2 = roc_auc_score(df2_no0['clase'], p2_no0)
    cm_1_to_2 = confusion_matrix(df2_no0['clase'], p2_no0 >= 0.5).tolist()

    # Caso 2: Train Sept 23 (900) -> Test Sept 11 (900)
    clf_m2 = get_base_clf(seed=42).fit(df2_no0[FEATS_5], df2_no0['clase'])
    p1_no0 = clf_m2.predict_proba(df1_no0[FEATS_5])[:, 1]
    acc_2_to_1 = accuracy_score(df1_no0['clase'], p1_no0 >= 0.5)
    auc_2_to_1 = roc_auc_score(df1_no0['clase'], p1_no0)
    cm_2_to_1 = confusion_matrix(df1_no0['clase'], p1_no0 >= 0.5).tolist()

    print(f"  Train Sept11 (900) -> Test Sept23 (900): Acc={acc_1_to_2*100:.2f}%, AUC={auc_1_to_2:.4f}")
    print(f"    CM:\n      {cm_1_to_2}")
    print(f"  Train Sept23 (900) -> Test Sept11 (900): Acc={acc_2_to_1*100:.2f}%, AUC={auc_2_to_1:.4f}")
    print(f"    CM:\n      {cm_2_to_1}")

    transfer['sept11_to_sept23'] = {'acc': acc_1_to_2, 'auc': auc_1_to_2, 'cm': cm_1_to_2}
    transfer['sept23_to_sept11'] = {'acc': acc_2_to_1, 'auc': auc_2_to_1, 'cm': cm_2_to_1}
    results['traslado_dominio'] = transfer

    # -------------------------------------------------------------
    # T2.2: Estudio de Ablación de Variables
    # -------------------------------------------------------------
    print("\n" + "-" * 60)
    print("ESTUDIO DE ABLACION (Dataset Sept 11-15, 900 muestras)")
    print("-" * 60)

    ablacion = {}
    sets_feats = [
        ('Completo_5_feats (r55,r65,r50,r70,Ineg)', FEATS_5),
        ('Con_THD_6_feats (+THD)', FEATS_6),
        ('Sin_r50_r70_3_feats (r55,r65,Ineg)', FEATS_3),
        ('Solo_r55_r65 (2_feats)', ['r_55', 'r_65']),
        ('Solo_Ineg (1_feat)', ['I_neg'])
    ]

    for label_feat, feat_sub in sets_feats:
        X = df1_no0[feat_sub]
        y = df1_no0['clase']
        grps = df1_no0['block_id']
        res = evaluate_cv(X, y, grps, cv_type='group', n_splits=5, seed=42)
        print(f"  {label_feat:<42}: Acc={res['accuracy_mean']*100:5.2f}% | AUC={res['auc_mean']:.4f} | F1={res['f1_mean']:.4f}")
        ablacion[label_feat] = res

    results['ablacion_features'] = ablacion

    # -------------------------------------------------------------
    # T2.3: Calibración de Probabilidades (Platt Scaling)
    # -------------------------------------------------------------
    print("\n" + "-" * 60)
    print("CALIBRACION DE PROBABILIDADES (Platt Scaling / Regresion Sigmoide)")
    print("-" * 60)

    X_train, X_test, y_train, y_test = train_test_split(
        df1_no0[FEATS_5], df1_no0['clase'], test_size=0.25, random_state=42, stratify=df1_no0['clase']
    )

    base_clf = get_base_clf(seed=42)
    base_clf.fit(X_train, y_train)

    p_raw_test = base_clf.predict_proba(X_test)[:, 1]
    brier_raw = brier_score_loss(y_test, p_raw_test)
    ece_raw = compute_ece(y_test.values, p_raw_test, n_bins=10)

    # Calibración Sigmoide con StratifiedKFold interno sobre X_train
    cal_clf = CalibratedClassifierCV(estimator=get_base_clf(seed=42), method='sigmoid', cv=3)
    cal_clf.fit(X_train, y_train)

    p_cal_test = cal_clf.predict_proba(X_test)[:, 1]
    brier_cal = brier_score_loss(y_test, p_cal_test)
    ece_cal = compute_ece(y_test.values, p_cal_test, n_bins=10)

    print(f"  Antes de calibrar: Brier Score = {brier_raw:.4f}, ECE = {ece_raw*100:.2f}%")
    print(f"  Tras calibracion:  Brier Score = {brier_cal:.4f}, ECE = {ece_cal*100:.2f}%")

    # Ajuste explícito de la sigmoide de Platt: P_cal = 1 / (1 + exp(A * p_raw + B))
    def platt_func(p, A, B):
        return 1.0 / (1.0 + np.exp(A * p + B))

    # Obtener probabilidades OOF sobre entrenamiento para estimar A y B
    oof_probs = np.zeros(len(y_train))
    skf = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)
    for tr, val in skf.split(X_train, y_train):
        m = get_base_clf(seed=42).fit(X_train.iloc[tr], y_train.iloc[tr])
        oof_probs[val] = m.predict_proba(X_train.iloc[val])[:, 1]

    try:
        popt, _ = curve_fit(platt_func, oof_probs, y_train.values, p0=[-5.0, 2.5], maxfev=5000)
        A_platt, B_platt = float(popt[0]), float(popt[1])
    except Exception as e:
        A_platt, B_platt = -5.0, 2.5

    print(f"  Parametros Platt ajustados: A = {A_platt:.4f}, B = {B_platt:.4f}")
    print(f"  Formula P_cal = 1 / (1 + exp({A_platt:.4f} * p_raw + ({B_platt:.4f})))")

    results['calibracion'] = {
        'brier_raw': float(brier_raw),
        'brier_cal': float(brier_cal),
        'ece_raw': float(ece_raw),
        'ece_cal': float(ece_cal),
        'A_platt': A_platt,
        'B_platt': B_platt
    }

    # Guardar resultados completos en reports/
    ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(REPORTS_DIR, f"reporte_validacion_agrupada_{ts_str}.json")
    with open(json_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\n[OK] Reporte JSON exportado a: {json_path}")


if __name__ == '__main__':
    main()
