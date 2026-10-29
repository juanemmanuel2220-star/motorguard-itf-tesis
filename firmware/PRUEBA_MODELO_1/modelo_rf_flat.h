#ifndef MODELO_RF_FLAT_H
#define MODELO_RF_FLAT_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define RF_FLAT_N_TREES 45
#define RF_FLAT_TOTAL_NODES 3195
#define RF_FLAT_N_FEATURES 5

// Nodo compacto de 12 bytes alineado en Flash (PROGMEM)
typedef struct {
    int16_t feat;           // Feature index (0..4), o -1 para nodo hoja
    int16_t left;           // Índice absoluto hijo izquierdo (o -1 si hoja)
    int16_t right;          // Índice absoluto hijo derecho (o -1 si hoja)
    int16_t pad;            // Relleno de alineación a 32 bits
    float thr_or_value;     // Umbral de corte en nodo split, o P(LEVE) en hoja
} RfNode;

extern const RfNode g_rf_flat_nodes[RF_FLAT_TOTAL_NODES];
extern const int16_t g_rf_flat_offsets[RF_FLAT_N_TREES];

// Inferencia iterativa en float puro (sin recursión ni emulación double)
float rf_flat_predict_proba(const float* features);
int rf_flat_predict_clase(const float* features, float threshold, float* out_proba);

#ifdef __cplusplus
}
#endif

#endif // MODELO_RF_FLAT_H
