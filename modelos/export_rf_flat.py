#!/usr/bin/env python3
"""
MotorGuard ITF - Exportador de Random Forest a Tablas Planas en Flash (Mejora 3C)
Elimina el desbordamiento de literales L32R y la emulación software de double generada por m2cgen.
Genera estructuras compactas 'RfNode' en float con recorrido iterativo de árboles.
"""

import os
import sys
import joblib
import numpy as np
import pandas as pd

MODEL_PATH = '/home/luna/tesis_itf/modelo_rf_itf_sept23_24_900.joblib'
OUT_H = '/home/luna/Arduino/PRUEBA_MODELO_1/modelo_rf_flat.h'
OUT_CPP = '/home/luna/Arduino/PRUEBA_MODELO_1/modelo_rf_flat.cpp'

def export_flat_trees():
    print(f"[EXPORTADOR] Cargando modelo: {MODEL_PATH}")
    rf = joblib.load(MODEL_PATH)
    n_trees = len(rf.estimators_)
    print(f"[EXPORTADOR] Número de estimadores: {n_trees}")

    all_nodes = []
    tree_offsets = []

    for t_idx, estimator in enumerate(rf.estimators_):
        tree = estimator.tree_
        offset = len(all_nodes)
        tree_offsets.append(offset)
        
        for i in range(tree.node_count):
            feat = tree.feature[i]
            if feat >= 0:
                left = offset + tree.children_left[i]
                right = offset + tree.children_right[i]
                thr = np.float32(tree.threshold[i])
            else:
                left = -1
                right = -1
                val = tree.value[i][0]
                thr = np.float32(val[1] / np.sum(val)) # Fracción de clase 1 (LEVE)
            all_nodes.append((feat, left, right, thr))

    total_nodes = len(all_nodes)
    print(f"[EXPORTADOR] Total de nodos exportados: {total_nodes}")
    bytes_nodes = total_nodes * 12 # 2 + 2 + 2 + 2(pad) + 4
    print(f"[EXPORTADOR] Tamaño estimado en Flash: {bytes_nodes} bytes ({bytes_nodes / 1024:.2f} KB)")

    # 1. Generar modelo_rf_flat.h
    h_code = f"""#ifndef MODELO_RF_FLAT_H
#define MODELO_RF_FLAT_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {{
#endif

#define RF_FLAT_N_TREES {n_trees}
#define RF_FLAT_TOTAL_NODES {total_nodes}
#define RF_FLAT_N_FEATURES 5

// Nodo compacto de 12 bytes alineado en Flash (PROGMEM)
typedef struct {{
    int16_t feat;           // Feature index (0..4), o -1 para nodo hoja
    int16_t left;           // Índice absoluto hijo izquierdo (o -1 si hoja)
    int16_t right;          // Índice absoluto hijo derecho (o -1 si hoja)
    int16_t pad;            // Relleno de alineación a 32 bits
    float thr_or_value;     // Umbral de corte en nodo split, o P(LEVE) en hoja
}} RfNode;

extern const RfNode g_rf_flat_nodes[RF_FLAT_TOTAL_NODES];
extern const int16_t g_rf_flat_offsets[RF_FLAT_N_TREES];

// Inferencia iterativa en float puro (sin recursión ni emulación double)
float rf_flat_predict_proba(const float* features);
int rf_flat_predict_clase(const float* features, float threshold, float* out_proba);

#ifdef __cplusplus
}}
#endif

#endif // MODELO_RF_FLAT_H
"""
    with open(OUT_H, 'w') as f:
        f.write(h_code)
    print(f"[EXPORTADOR] Guardado header: {OUT_H}")

    # 2. Generar modelo_rf_flat.cpp
    cpp_lines = [
        '#include "modelo_rf_flat.h"',
        '',
        f'const int16_t g_rf_flat_offsets[RF_FLAT_N_TREES] = {{',
        '    ' + ', '.join(str(o) for o in tree_offsets),
        '};',
        '',
        f'const RfNode g_rf_flat_nodes[RF_FLAT_TOTAL_NODES] = {{'
    ]

    for feat, left, right, thr in all_nodes:
        # Formatear float asegurando sufijo 'f'
        thr_str = f"{thr:.9g}f" if '.' in f"{thr:.9g}" or 'e' in f"{thr:.9g}" else f"{thr:.1f}f"
        cpp_lines.append(f'    {{{feat}, {left}, {right}, 0, {thr_str}}},')

    cpp_lines.append('};')
    cpp_lines.append('')
    cpp_lines.append("""float rf_flat_predict_proba(const float* features) {
    if (!features) return 0.0f;
    float sum_p = 0.0f;
    for (int t = 0; t < RF_FLAT_N_TREES; t++) {
        int idx = g_rf_flat_offsets[t];
        while (g_rf_flat_nodes[idx].feat >= 0) {
            int feat_idx = g_rf_flat_nodes[idx].feat;
            if (features[feat_idx] <= g_rf_flat_nodes[idx].thr_or_value) {
                idx = g_rf_flat_nodes[idx].left;
            } else {
                idx = g_rf_flat_nodes[idx].right;
            }
        }
        sum_p += g_rf_flat_nodes[idx].thr_or_value;
    }
    return sum_p * (1.0f / (float)RF_FLAT_N_TREES);
}

int rf_flat_predict_clase(const float* features, float threshold, float* out_proba) {
    float p = rf_flat_predict_proba(features);
    if (out_proba) *out_proba = p;
    return (p >= threshold) ? 1 : 0;
}
""")

    with open(OUT_CPP, 'w') as f:
        f.write('\n'.join(cpp_lines))
    print(f"[EXPORTADOR] Guardado fuente: {OUT_CPP}")

    # 3. Validación de equivalencia con predict_proba en todo el dataset de entrenamiento
    files = [
        '/home/luna/tesis_itf/dataset/cap_ENTRELAZADA_LEVE_25%_20260914_1252.csv',
        '/home/luna/tesis_itf/dataset/cap_ENTRELAZADA_LEVE_50%_20260914_1438.csv',
        '/home/luna/tesis_itf/dataset/cap_ENTRELAZADA_LEVE_75%_20260915_1205.csv'
    ]
    dfs = [pd.read_csv(f) for f in files]
    df_all = pd.concat(dfs, ignore_index=True)
    X = np.column_stack([
        df_all['A_55'] / df_all['A_fund'],
        df_all['A_65'] / df_all['A_fund'],
        df_all['A_50'] / df_all['A_fund'],
        df_all['A_70'] / df_all['A_fund'],
        df_all['I_neg']
    ]).astype(np.float32)

    y_sk = rf.predict_proba(X)[:, 1]

    def predict_sim(x_row):
        s = 0.0
        for off in tree_offsets:
            cur = off
            while all_nodes[cur][0] >= 0:
                ft = all_nodes[cur][0]
                cur = all_nodes[cur][1] if x_row[ft] <= all_nodes[cur][3] else all_nodes[cur][2]
            s += float(all_nodes[cur][3])
        return s / n_trees

    y_flat = np.array([predict_sim(row) for row in X])
    diff = np.abs(y_sk - y_flat)
    max_d = np.max(diff)
    print(f"[EXPORTADOR] Verificación de equivalencia sobre {len(X)} muestras:")
    print(f"             Máxima diferencia absoluta: {max_d:.2e} (Criterio: < 1e-6)")
    assert max_d < 1e-6, f"Diferencia {max_d} supera 1e-6"
    print("[EXPORTADOR] Éxito: 100% de muestras verificadas con equivalencia estricta.")

if __name__ == '__main__':
    export_flat_trees()
