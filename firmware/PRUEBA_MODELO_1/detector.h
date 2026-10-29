#ifndef DETECTOR_H
#define DETECTOR_H

#include <stdint.h>
#include <math.h>

#ifdef __cplusplus
extern "C" {
#endif

// ==================== CALIBRACIÓN DE PROBABILIDAD (PLATT) ====================
// P_cal = 1 / (1 + exp(CAL_A * p_raw + CAL_B))
// logit(P_cal) = -CAL_A * p_raw - CAL_B
constexpr float CAL_A = -7.0648f;
constexpr float CAL_B = 3.4930f;

// ==================== PARÁMETROS CUSUM (DISEÑADOS ARL0 >= 3600) ====================
constexpr float CUSUM_K = 0.50f;      // Deriva / drift por muestra
constexpr float CUSUM_H = 5.00f;      // Umbral de disparo de alarma
constexpr float CUSUM_HOFF = 1.25f;   // Umbral de retorno (0.25 * H)
constexpr float CUSUM_S_MAX = 8.00f;   // Techo anti-windup optimizado (1.6x H) para retorno rapido (< 4 s)
constexpr int CUSUM_M = 2;            // 2 ventanas consecutivas < HOFF (3.4 s) para confirmar retorno

typedef enum {
    DETECTOR_SANO = 0,
    DETECTOR_ALARMA = 1,
    DETECTOR_WARMUP = -1
} DetectorDecision;

typedef struct {
    float S;               // Acumulador de Page-Hinkley / CUSUM
    float p_cal;           // Probabilidad calibrada por regresión sigmoide
    float z;               // Log-odds normalizado
    int consecutive_low;   // Contador para confirmación de retorno a estado sano
    int current_decision;  // Estado lógico actual (0: SANO, 1: ALARMA)
    int is_warmup;         // Indicador de período de estabilización de arranque
} DetectorState;

void detector_init(DetectorState* st);
DetectorDecision detector_step(float p_raw, DetectorState* st);
void detector_set_warmup(DetectorState* st, int warmup);

#ifdef __cplusplus
}
#endif

#endif // DETECTOR_H
