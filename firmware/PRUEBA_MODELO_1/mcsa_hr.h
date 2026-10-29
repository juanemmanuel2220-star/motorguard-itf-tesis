#ifndef MCSA_HR_H
#define MCSA_HR_H

#include <stdint.h>
#include <math.h>

#ifdef __cplusplus
extern "C" {
#endif

// ==================== CONSTANTES DEL MOTOR Y ADQUISICIÓN ====================
#define MCSA_FS 2403.846f
#define MCSA_N 4096
#define MCSA_DF (MCSA_FS / (float)MCSA_N)  // 0.5859375 Hz
#define MCSA_P_PARES 2
#define MCSA_S_MIN 0.002f
#define MCSA_S_MAX 0.06f

// ==================== ESTRUCTURAS DE DATOS ====================
typedef struct {
    // Estimación de fundamental
    float f0;          // Fundamental estimada f^0 (Hz)
    float A0;          // Amplitud fundamental corregida A^0 (unidades físicas)
    
    // Estimación de deslizamiento y velocidad
    float s;           // Deslizamiento estimado s^ (adimensional)
    int slip_ok;       // 1 si el pico fr superó prominencia >= 6 dB sobre piso, 0 si se usó fallback
    float fr;          // Frecuencia rotórica estimada f^_r (Hz)

    // Amplitudes en dB relativas a la fundamental: Lx = 20*log10(Ax / A^0)
    float L_2sm;       // Banda inferior de deslizamiento: f0*(1 - 2s) (dB)
    float L_2sp;       // Banda superior de deslizamiento: f0*(1 + 2s) (dB)
    float L_rm;        // Banda rotórica inferior: f0 - fr (dB)
    float L_rp;        // Banda rotórica superior: f0 + fr (dB)
    float L_3;         // Tercer armónico: 3*f0 (dB)
    float L_3rm;       // Banda 3*f0 - fr (dB)
    float L_3rp;       // Banda 3*f0 + fr (dB)

    // Relación señal-a-ruido respecto al piso espectral local (dB)
    float SNR_2sm;     // SNR banda f0*(1 - 2s) (dB)
    float SNR_2sp;     // SNR banda f0*(1 + 2s) (dB)
    float SNR_2s;      // max(SNR_2sm, SNR_2sp) (dB)
    float SNR_rm;      // SNR banda f0 - fr (dB)
    float SNR_rp;      // SNR banda f0 + fr (dB)
    float SNR_3;       // SNR tercer armónico (dB)
    float SNR_3rm;     // SNR banda 3*f0 - fr (dB)
    float SNR_3rp;     // SNR banda 3*f0 + fr (dB)

    // Pisos de ruido locales (unidades físicas)
    float floor_2sm;
    float floor_2sp;
    float floor_rm;
    float floor_rp;
    float floor_3;
    float floor_3rm;
    float floor_3rp;

    // Amplitudes lineales estimadas por Goertzel exacto (unidades físicas)
    float A_2sm;
    float A_2sp;
    float A_rm;
    float A_rp;
    float A_3;
    float A_3rm;
    float A_3rp;
} McsaHrResultados;

typedef struct {
    float last_valid_s;    // Último deslizamiento válido retenido
    int has_valid_s;       // Bandera de inicialización de deslizamiento
    int enable_ema;        // 1 para activar filtrado exponencial en potencias (default 0)
    float alpha_ema;       // Coeficiente EMA (default 0.3f)
    
    // Potencias lineales filtradas por EMA para cada armónico
    float P_2sm;
    float P_2sp;
    float P_rm;
    float P_rp;
    float P_3;
    float P_3rm;
    float P_3rp;
} McsaHrState;

// ==================== FUNCIONES PÚBLICAS ====================
void mcsa_hr_init(McsaHrState* state);
void mcsa_hr_set_work_buffers(float* buf_re, float* buf_im);

void mcsa_hr_procesar_canal(
    const int16_t* adc_raw, // Bloque contiguo de 4096 muestras crudas del ADC
    float cal_i,            // Factor de escala físico A/LSB (p.ej. CAL_I[p])
    McsaHrState* state,     // Estado del estimador
    McsaHrResultados* res   // Resultados calculados
);

void mcsa_hr_procesar_float(
    const float* x_in,      // Bloque contiguo de 4096 muestras en unidades físicas
    McsaHrState* state,
    McsaHrResultados* res
);

// Funciones individuales expuestas para tests y benchmarking
float mcsa_hr_grandke_f0(const float* mag_X, float df, int k_min, int k_max, int* out_k, float* out_delta);
float mcsa_hr_grandke_amp(float mag_k, float delta, float sum_w);
void mcsa_hr_cancelar_fundamental(const float* x, int n, float f0, float fs, float* out_residuo, float* out_a, float* out_b);
float mcsa_hr_dft_single(const float* y, const float* w, int n, float freq, float fs);
float mcsa_hr_piso_local(const float* mag_R, int n_bins, float df, float f_target, const float* target_freqs, int n_targets);

#ifdef __cplusplus
}
#endif

#endif // MCSA_HR_H
