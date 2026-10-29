#ifndef MODELO_RF_ESP32_H
#define MODELO_RF_ESP32_H
void score(double *input, double *output);
static inline int modelo_clase(const float features[9]) {
  double x[9]; double out[4] = {0,0,0,0};
  for (int i = 0; i < 9; i++) x[i] = (double)features[i];
  score(x, out);
  int max_idx = 0; double max_val = out[0];
  for (int i = 1; i < 4; i++) if (out[i] > max_val) { max_val = out[i]; max_idx = i; }
  return max_idx;
}
#endif