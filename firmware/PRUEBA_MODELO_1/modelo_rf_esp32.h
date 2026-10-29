#ifndef MODELO_RF_ESP32_H
#define MODELO_RF_ESP32_H

// Declaración de función exportada por m2cgen
void score(double *input, double *output);

#define N_FEATURES_MODELO 5
#define THR_FALLA_ON   0.60f   // Umbral calibrado anti-perturbación mecánica (100% inmutable)
#define THR_FALLA_OFF  0.45f   // Umbral de retorno a SANO

static int estado_itf_mem = 0; // 0=SANO, 1=LEVE
static float ultima_prob_leve = 0.0f;

static inline void modelo_reset() {
  estado_itf_mem = 0;
  ultima_prob_leve = 0.0f;
}

static inline int modelo_clase(const float features[N_FEATURES_MODELO], float *conf_out = nullptr) {
  double x[N_FEATURES_MODELO];
  double out[2] = {0.0, 0.0};

  for (int i = 0; i < N_FEATURES_MODELO; i++) {
    x[i] = (double)features[i];
  }

  score(x, out);

  double p_sano = out[0];
  double p_leve = out[1];

  double p_tot = p_sano + p_leve;
  if (p_tot > 0.0001) {
    p_sano /= p_tot;
    p_leve /= p_tot;
  }
  ultima_prob_leve = (float)p_leve;

  // Decisión instantánea: delega la persistencia temporal al filtro antirrebote DEB_N en PRUEBA_MODELO_1.ino
  int decision = (p_leve >= THR_FALLA_ON) ? 1 : 0;
  estado_itf_mem = decision;

  if (conf_out) {
    *conf_out = (float)(decision == 1 ? p_leve : p_sano);
  }

  return decision;
}

#endif