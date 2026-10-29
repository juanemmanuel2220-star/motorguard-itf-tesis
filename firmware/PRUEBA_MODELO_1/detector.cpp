#include "detector.h"

void detector_init(DetectorState* st) {
    if (!st) return;
    st->S = 0.0f;
    st->p_cal = 0.0f;
    st->z = 0.0f;
    st->consecutive_low = 0;
    st->current_decision = DETECTOR_SANO;
    st->is_warmup = 0;
}

void detector_set_warmup(DetectorState* st, int warmup) {
    if (!st) return;
    st->is_warmup = warmup ? 1 : 0;
    if (warmup) {
        st->S = 0.0f;
        st->consecutive_low = 0;
    }
}

DetectorDecision detector_step(float p_raw, DetectorState* st) {
    if (!st) return DETECTOR_SANO;

    // Período de estabilización térmica/eléctrica tras arranque
    if (st->is_warmup) {
        st->S = 0.0f;
        st->consecutive_low = 0;
        st->current_decision = DETECTOR_SANO;
        return DETECTOR_WARMUP;
    }

    // 1. Calibración de probabilidad de Platt
    // P_cal = 1 / (1 + exp(CAL_A * p_raw + CAL_B))
    float exponente = CAL_A * p_raw + CAL_B;
    if (exponente > 20.0f) exponente = 20.0f;
    if (exponente < -20.0f) exponente = -20.0f;
    float p_cal = 1.0f / (1.0f + expf(exponente));
    st->p_cal = p_cal;

    // 2. Log-odds z_t con acotación de seguridad
    // z_t = logit(p_cal) = -CAL_A * p_raw - CAL_B
    float z_t = -exponente;
    st->z = z_t;

    // 3. Acumulador CUSUM: S_t = max(0, min(S_MAX, S_{t-1} + z_t - K))
    float s_next = st->S + z_t - CUSUM_K;
    if (s_next < 0.0f) {
        s_next = 0.0f;
    } else if (s_next > CUSUM_S_MAX) {
        s_next = CUSUM_S_MAX;
    }
    st->S = s_next;

    // 4. Regla de decisión secuencial con histéresis y persistencia de retorno
    if (st->current_decision == DETECTOR_ALARMA) {
        if (st->S < CUSUM_HOFF) {
            st->consecutive_low++;
            if (st->consecutive_low >= CUSUM_M) {
                st->current_decision = DETECTOR_SANO;
                st->consecutive_low = 0;
            }
        } else {
            st->consecutive_low = 0;
        }
    } else {
        if (st->S >= CUSUM_H) {
            st->current_decision = DETECTOR_ALARMA;
            st->consecutive_low = 0;
        }
    }

    return (DetectorDecision)st->current_decision;
}
