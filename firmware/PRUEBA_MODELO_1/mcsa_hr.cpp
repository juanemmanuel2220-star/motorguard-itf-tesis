#include "mcsa_hr.h"
#include <string.h>
#include <stdlib.h>

// ==================== TRABAJO ESTÁTICO (COMPARTIDO O POR DEFECTO) ====================
// En ESP32 reutiliza los buffers de PRUEBA_MODELO_1.ino para ahorrar 32 KB de DRAM.
#ifdef ARDUINO
static float* s_fft_re = nullptr;
static float* s_fft_im = nullptr;
#else
static float s_default_fft_re[MCSA_N];
static float s_default_fft_im[MCSA_N];
static float* s_fft_re = s_default_fft_re;
static float* s_fft_im = s_default_fft_im;
#endif

void mcsa_hr_set_work_buffers(float* buf_re, float* buf_im) {
    s_fft_re = buf_re;
    s_fft_im = buf_im;
}

// ==================== INICIALIZACIÓN ====================
void mcsa_hr_init(McsaHrState* state) {
    if (!state) return;
#ifndef ARDUINO
    if (!s_fft_re) s_fft_re = s_default_fft_re;
    if (!s_fft_im) s_fft_im = s_default_fft_im;
#endif
    state->last_valid_s = 0.012f; // Deslizamiento nominal típico ~1735-1780 RPM
    state->has_valid_s = 0;
    state->enable_ema = 0;
    state->alpha_ema = 0.3f;
    state->P_2sm = 0.0f;
    state->P_2sp = 0.0f;
    state->P_rm = 0.0f;
    state->P_rp = 0.0f;
    state->P_3 = 0.0f;
    state->P_3rm = 0.0f;
    state->P_3rp = 0.0f;
}

// ==================== FFT RADIX-2 IN-PLACE (FLOAT) ====================
// Implementación Cooley-Tukey DIT en float puro sin memoria dinámica ni tablas gigantes
static void fft_radix2(float* re, float* im, int n) {
    // 1. Inversión de bits (Bit-reversal permutation)
    for (int i = 1, j = 0; i < n; i++) {
        int bit = n >> 1;
        for (; j & bit; bit >>= 1) {
            j ^= bit;
        }
        j ^= bit;
        if (i < j) {
            float tr = re[i]; re[i] = re[j]; re[j] = tr;
            float ti = im[i]; im[i] = im[j]; im[j] = ti;
        }
    }

    // 2. Mariposas Cooley-Tukey
    for (int len = 2; len <= n; len <<= 1) {
        float ang = -2.0f * 3.14159265358979323846f / (float)len;
        float wr = cosf(ang);
        float wi = sinf(ang);
        int half = len >> 1;
        for (int i = 0; i < n; i += len) {
            float cr = 1.0f, ci = 0.0f;
            for (int k = 0; k < half; k++) {
                int i0 = i + k;
                int i1 = i0 + half;
                float tr = re[i1] * cr - im[i1] * ci;
                float ti = re[i1] * ci + im[i1] * cr;
                re[i1] = re[i0] - tr;
                im[i1] = im[i0] - ti;
                re[i0] += tr;
                im[i0] += ti;
                float nr = cr * wr - ci * wi;
                ci = cr * wi + ci * wr;
                cr = nr;
            }
        }
    }
}

// ==================== ESTIMACIÓN DE FUNDAMENTAL (GRANDKE) ====================
float mcsa_hr_grandke_f0(const float* mag_X, float df, int k_min, int k_max, int* out_k, float* out_delta) {
    if (!mag_X || k_min < 1 || k_max >= (MCSA_N / 2)) {
        if (out_k) *out_k = 102;
        if (out_delta) *out_delta = 0.0f;
        return 60.0f;
    }

    int best_k = k_min;
    float max_mag = mag_X[k_min];
    for (int k = k_min + 1; k <= k_max; k++) {
        if (mag_X[k] > max_mag) {
            max_mag = mag_X[k];
            best_k = k;
        }
    }

    // Comparar vecinos k-1 y k+1
    int sign = 1;
    float mag_neighbor = mag_X[best_k + 1];
    if (mag_X[best_k - 1] > mag_neighbor) {
        mag_neighbor = mag_X[best_k - 1];
        sign = -1;
    }

    float alpha = (max_mag > 1e-12f) ? (mag_neighbor / max_mag) : 0.5f;
    if (alpha > 1.0f) alpha = 1.0f;
    if (alpha < 0.0f) alpha = 0.0f;

    // Fórmula de interpolación de Grandke para ventana Hann
    float delta = (2.0f * alpha - 1.0f) / (1.0f + alpha);
    if (delta < 0.0f) delta = 0.0f;
    if (delta > 0.5f) delta = 0.5f;

    float f0 = ((float)best_k + (float)sign * delta) * df;

    if (out_k) *out_k = best_k;
    if (out_delta) *out_delta = (float)sign * delta;
    return f0;
}

// Amplitud corregida por Grandke para eliminar scalloping loss
float mcsa_hr_grandke_amp(float mag_k, float delta, float sum_w) {
    float abs_delta = fabsf(delta);
    float sinc_d = 1.0f;
    if (abs_delta > 1e-6f) {
        float pid = 3.14159265358979323846f * abs_delta;
        sinc_d = sinf(pid) / pid;
    }
    float denom = (1.0f - abs_delta * abs_delta);
    if (denom < 1e-6f) denom = 1e-6f;
    float W_delta = sinc_d / denom;
    return (2.0f * mag_k) / (sum_w * W_delta);
}

// ==================== CANCELACIÓN DE FUNDAMENTAL EN TIEMPO ====================
void mcsa_hr_cancelar_fundamental(
    const float* x, int n, float f0, float fs, float* out_residuo, float* out_a, float* out_b
) {
    float omega = 2.0f * 3.14159265358979323846f * f0 / fs;
    float w_cos = cosf(omega);
    float w_sin = sinf(omega);

    float z_re = 1.0f;
    float z_im = 0.0f;

    float Ccc = 0.0f, Css = 0.0f, Ccs = 0.0f;
    float Cxc = 0.0f, Cxs = 0.0f;

    // Paso 1: cálculo de términos normales
    for (int i = 0; i < n; i++) {
        if ((i & 255) == 0 && i > 0) {
            float inv_norm = 1.0f / sqrtf(z_re * z_re + z_im * z_im);
            z_re *= inv_norm;
            z_im *= inv_norm;
        }

        float c = z_re;
        float s = z_im;
        float xi = x[i];

        Ccc += c * c;
        Css += s * s;
        Ccs += c * s;
        Cxc += xi * c;
        Cxs += xi * s;

        float n_re = z_re * w_cos - z_im * w_sin;
        z_im = z_re * w_sin + z_im * w_cos;
        z_re = n_re;
    }

    float D = Ccc * Css - Ccs * Ccs;
    float a = 0.0f, b = 0.0f;
    if (fabsf(D) > 1e-9f) {
        a = (Css * Cxc - Ccs * Cxs) / D;
        b = (Ccc * Cxs - Ccs * Cxc) / D;
    }

    if (out_a) *out_a = a;
    if (out_b) *out_b = b;

    // Paso 2: sustracción de la fundamental estimada
    z_re = 1.0f;
    z_im = 0.0f;
    for (int i = 0; i < n; i++) {
        if ((i & 255) == 0 && i > 0) {
            float inv_norm = 1.0f / sqrtf(z_re * z_re + z_im * z_im);
            z_re *= inv_norm;
            z_im *= inv_norm;
        }

        float c = z_re;
        float s = z_im;
        out_residuo[i] = x[i] - (a * c + b * s);

        float n_re = z_re * w_cos - z_im * w_sin;
        z_im = z_re * w_sin + z_im * w_cos;
        z_re = n_re;
    }
}

// ==================== DFT DE UN SOLO BIN (GOERTZEL GENERALIZADO) ====================
float mcsa_hr_dft_single(const float* y, const float* w, int n, float freq, float fs) {
    float theta = 2.0f * 3.14159265358979323846f * freq / fs;
    float w_cos = cosf(theta);
    float w_sin = sinf(theta);

    float z_re = 1.0f;
    float z_im = 0.0f;

    float acc_re = 0.0f;
    float acc_im = 0.0f;
    float sum_w = (float)n * 0.5f; // Para Hann periódica sum(w) = N/2

    for (int i = 0; i < n; i++) {
        if ((i & 255) == 0 && i > 0) {
            float inv_norm = 1.0f / sqrtf(z_re * z_re + z_im * z_im);
            z_re *= inv_norm;
            z_im *= inv_norm;
        }

        float c = z_re;
        float s = z_im;
        float yw = w ? (y[i] * w[i]) : y[i];

        acc_re += yw * c;
        acc_im -= yw * s;

        float n_re = z_re * w_cos - z_im * w_sin;
        z_im = z_re * w_sin + z_im * w_cos;
        z_re = n_re;
    }

    float mag = sqrtf(acc_re * acc_re + acc_im * acc_im);
    return (2.0f / sum_w) * mag;
}

// ==================== ESTIMACIÓN DE PISO ESPECTRAL LOCAL ====================
// Mediana de |R| en bins a +-3 Hz excluyendo +-3 bins de armónicos objetivo
float mcsa_hr_piso_local(
    const float* mag_R, int n_bins, float df, float f_target, const float* target_freqs, int n_targets
) {
    if (!mag_R || n_bins <= 0) return 1e-7f;

    float vals[64];
    int count = 0;
    float sum_w = (float)MCSA_N * 0.5f;

    float spans[2] = {3.0f, 5.0f}; // Si faltan bins a +-3Hz, expandir a +-5Hz
    for (int s_idx = 0; s_idx < 2 && count < 5; s_idx++) {
        float span = spans[s_idx];
        count = 0;
        int k_start = (int)roundf((f_target - span) / df);
        int k_end   = (int)roundf((f_target + span) / df);
        if (k_start < 1) k_start = 1;
        if (k_end >= n_bins) k_end = n_bins - 1;

        for (int k = k_start; k <= k_end && count < 64; k++) {
            float f_k = (float)k * df;
            if (fabsf(f_k - f_target) > span) continue;

            // Exclusión de +-3 bins alrededor de f_target
            if (fabsf(f_k - f_target) <= 3.0f * df) continue;

            // Exclusión de +-3 bins alrededor de cualquier otro objetivo
            int clash = 0;
            if (target_freqs) {
                for (int t = 0; t < n_targets; t++) {
                    if (fabsf(f_k - target_freqs[t]) <= 3.0f * df) {
                        clash = 1;
                        break;
                    }
                }
            }
            if (!clash) {
                vals[count++] = mag_R[k];
            }
        }
    }

    if (count == 0) return 1e-7f;

    // Insertion sort para mediana exacta
    for (int i = 1; i < count; i++) {
        float key = vals[i];
        int j = i - 1;
        while (j >= 0 && vals[j] > key) {
            vals[j + 1] = vals[j];
            j--;
        }
        vals[j + 1] = key;
    }

    float median_mag = vals[count / 2];
    float floor_amp = (2.0f / sum_w) * median_mag;
    return (floor_amp > 1e-7f) ? floor_amp : 1e-7f;
}

// ==================== PROCESAMIENTO MCSA COMPLETO ====================
void mcsa_hr_procesar_float(const float* x_in, McsaHrState* state, McsaHrResultados* res) {
    if (!x_in || !res) return;

    memset(res, 0, sizeof(McsaHrResultados));
    const float sum_w = (float)MCSA_N * 0.5f; // sum(Hann) = 2048
    const float df = MCSA_DF;

    // 1. Ventana de Hann y copia a buffer de trabajo
    // Oscilador complejo para Hann w[n] = 0.5 - 0.5*cos(2*pi*n/N)
    float h_ang = 2.0f * 3.14159265358979323846f / (float)MCSA_N;
    float h_cos = cosf(h_ang);
    float h_sin = sinf(h_ang);
    float hz_re = 1.0f, hz_im = 0.0f;

    for (int n = 0; n < MCSA_N; n++) {
        if ((n & 255) == 0 && n > 0) {
            float inv_norm = 1.0f / sqrtf(hz_re * hz_re + hz_im * hz_im);
            hz_re *= inv_norm;
            hz_im *= inv_norm;
        }
        float w_val = 0.5f - 0.5f * hz_re;
        s_fft_re[n] = x_in[n] * w_val;
        s_fft_im[n] = 0.0f;

        float n_re = hz_re * h_cos - hz_im * h_sin;
        hz_im = hz_re * h_sin + hz_im * h_cos;
        hz_re = n_re;
    }

    // 2. Primera FFT: espectro de la señal original
    fft_radix2(s_fft_re, s_fft_im, MCSA_N);

    // Magnitudes en s_fft_re[0..MCSA_N/2]
    for (int k = 0; k <= (MCSA_N / 2); k++) {
        s_fft_re[k] = sqrtf(s_fft_re[k] * s_fft_re[k] + s_fft_im[k] * s_fft_im[k]);
    }

    // 3. Estimación de Fundamental en [58.5, 61.5] Hz con Grandke
    int k_min = (int)roundf(58.5f / df);
    int k_max = (int)roundf(61.5f / df);
    int best_k0 = 102;
    float delta0 = 0.0f;
    float f0 = mcsa_hr_grandke_f0(s_fft_re, df, k_min, k_max, &best_k0, &delta0);
    float A0 = mcsa_hr_grandke_amp(s_fft_re[best_k0], delta0, sum_w);
    if (A0 < 1e-6f) A0 = 1e-6f;

    res->f0 = f0;
    res->A0 = A0;

    // 4. Cancelación de fundamental en el tiempo sobre buffer residual
    // Reutilizamos s_fft_im para guardar temporalmente el residuo r[n] sin ventana
    float a_ls = 0.0f, b_ls = 0.0f;
    mcsa_hr_cancelar_fundamental(x_in, MCSA_N, f0, MCSA_FS, s_fft_im, &a_ls, &b_ls);

    // 5. Segunda FFT: espectro del residuo r[n]
    // Ventana Hann aplicada directamente sobre r[n] en s_fft_re
    hz_re = 1.0f; hz_im = 0.0f;
    for (int n = 0; n < MCSA_N; n++) {
        if ((n & 255) == 0 && n > 0) {
            float inv_norm = 1.0f / sqrtf(hz_re * hz_re + hz_im * hz_im);
            hz_re *= inv_norm;
            hz_im *= inv_norm;
        }
        float w_val = 0.5f - 0.5f * hz_re;
        s_fft_re[n] = s_fft_im[n] * w_val; // r[n] * w[n]
        // Guardamos r[n] en s_fft_im para uso posterior en Goertzel
        // (s_fft_im temporalmente sobrescrito con 0 para la FFT en el siguiente loop)

        float n_re = hz_re * h_cos - hz_im * h_sin;
        hz_im = hz_re * h_sin + hz_im * h_cos;
        hz_re = n_re;
    }

    // Para la FFT ponemos parte imaginaria en ceros usando un loop corto
    // Pero necesitamos conservar r[n]... ¡espera! Podemos calcular r[n] al vuelo
    // con cos/sin durante Goertzel o almacenar magnitudes.
    for (int n = 0; n < MCSA_N; n++) {
        s_fft_im[n] = 0.0f;
    }
    fft_radix2(s_fft_re, s_fft_im, MCSA_N);

    // Magnitudes del residuo |R_k| en s_fft_re[0..MCSA_N/2]
    for (int k = 0; k <= (MCSA_N / 2); k++) {
        s_fft_re[k] = sqrtf(s_fft_re[k] * s_fft_re[k] + s_fft_im[k] * s_fft_im[k]);
    }

    // 6. Búsqueda de deslizamiento y frecuencia rotórica fr
    float fr_min = f0 * (1.0f - MCSA_S_MAX) / (float)MCSA_P_PARES;
    float fr_max = f0 * (1.0f - MCSA_S_MIN) / (float)MCSA_P_PARES;
    int k_up_min = (int)roundf((f0 + fr_min) / df);
    int k_up_max = (int)roundf((f0 + fr_max) / df);

    int best_k_up = k_up_min;
    float max_metric = -1.0f;
    for (int k_up = k_up_min; k_up <= k_up_max; k_up++) {
        float f_up = (float)k_up * df;
        float curr_fr = f_up - f0;
        float f_low = fabsf(f0 - curr_fr);
        int k_low = (int)roundf(f_low / df);
        if (k_low < 1) k_low = 1;
        float metric = s_fft_re[k_up] * s_fft_re[k_up] + s_fft_re[k_low] * s_fft_re[k_low];
        if (metric > max_metric) {
            max_metric = metric;
            best_k_up = k_up;
        }
    }

    // Interpolación de Grandke dual sobre bandas f0 + fr y f0 - fr
    float f_up = (float)best_k_up * df;
    float cand_fr = f_up - f0;
    int best_k_low = (int)roundf(fabsf(f0 - cand_fr) / df);
    if (best_k_low < 1) best_k_low = 1;

    // Grandke upper
    int sign_u = (s_fft_re[best_k_up + 1] >= s_fft_re[best_k_up - 1]) ? 1 : -1;
    float alpha_u = s_fft_re[best_k_up + sign_u] / (s_fft_re[best_k_up] > 1e-12f ? s_fft_re[best_k_up] : 1e-12f);
    if (alpha_u > 1.0f) alpha_u = 1.0f;
    float delta_u = (2.0f * alpha_u - 1.0f) / (1.0f + alpha_u);
    if (delta_u < 0.0f) delta_u = 0.0f;
    float f_up_est = ((float)best_k_up + (float)sign_u * delta_u) * df;
    float fr_up = f_up_est - f0;

    // Grandke lower
    int sign_l = (s_fft_re[best_k_low + 1] >= s_fft_re[best_k_low - 1]) ? 1 : -1;
    float alpha_l = s_fft_re[best_k_low + sign_l] / (s_fft_re[best_k_low] > 1e-12f ? s_fft_re[best_k_low] : 1e-12f);
    if (alpha_l > 1.0f) alpha_l = 1.0f;
    float delta_l = (2.0f * alpha_l - 1.0f) / (1.0f + alpha_l);
    if (delta_l < 0.0f) delta_l = 0.0f;
    float f_low_est = ((float)best_k_low + (float)sign_l * delta_l) * df;
    float fr_low = f0 - f_low_est;

    float fr_est = 0.5f * (fr_up + fr_low);
    float s_est = 1.0f - (float)MCSA_P_PARES * fr_est / f0;

    // Verificación de prominencia >= 6 dB sobre piso local
    float targets_slip[2] = {f0, f_up_est};
    float floor_up = mcsa_hr_piso_local(s_fft_re, (MCSA_N / 2) + 1, df, f_up_est, targets_slip, 2);
    float amp_up = (2.0f / sum_w) * s_fft_re[best_k_up];
    float prom_dB = 20.0f * log10f(amp_up / (floor_up > 1e-7f ? floor_up : 1e-7f));

    if (prom_dB >= 6.0f && s_est >= MCSA_S_MIN && s_est <= MCSA_S_MAX) {
        res->slip_ok = 1;
        res->s = s_est;
        res->fr = fr_est;
        if (state) {
            state->last_valid_s = s_est;
            state->has_valid_s = 1;
        }
    } else {
        res->slip_ok = 0;
        if (state && state->has_valid_s) {
            res->s = state->last_valid_s;
        } else {
            res->s = 0.012f; // Fallback razonable al 25% de carga
        }
        res->fr = f0 * (1.0f - res->s) / (float)MCSA_P_PARES;
    }

    // 7. Frecuencias exactas para DFT
    float f_2sm  = f0 * (1.0f - 2.0f * res->s);
    float f_2sp  = f0 * (1.0f + 2.0f * res->s);
    float f_rm   = f0 - res->fr;
    float f_rp   = f0 + res->fr;
    float f_3    = 3.0f * f0;
    float f_3rm  = 3.0f * f0 - res->fr;
    float f_3rp  = 3.0f * f0 + res->fr;

    // Lista de objetivos para exclusión en cálculo de pisos
    float all_targets[8] = {f0, f_2sm, f_2sp, f_rm, f_rp, f_3, f_3rm, f_3rp};

    // 8. Pisos locales a partir de magnitudes |R_k| almacenadas en s_fft_re
    res->floor_2sm = mcsa_hr_piso_local(s_fft_re, (MCSA_N / 2) + 1, df, f_2sm, all_targets, 8);
    res->floor_2sp = mcsa_hr_piso_local(s_fft_re, (MCSA_N / 2) + 1, df, f_2sp, all_targets, 8);
    res->floor_rm  = mcsa_hr_piso_local(s_fft_re, (MCSA_N / 2) + 1, df, f_rm,  all_targets, 8);
    res->floor_rp  = mcsa_hr_piso_local(s_fft_re, (MCSA_N / 2) + 1, df, f_rp,  all_targets, 8);
    res->floor_3   = mcsa_hr_piso_local(s_fft_re, (MCSA_N / 2) + 1, df, f_3,   all_targets, 8);
    res->floor_3rm = mcsa_hr_piso_local(s_fft_re, (MCSA_N / 2) + 1, df, f_3rm, all_targets, 8);
    res->floor_3rp = mcsa_hr_piso_local(s_fft_re, (MCSA_N / 2) + 1, df, f_3rp, all_targets, 8);

    // 9. Amplitudes a frecuencia exacta con DFT de un solo bin en una sola pasada
    // Preparamos oscilador de Hann y osciladores para las 7 frecuencias
    float th_step[7] = {
        2.0f * 3.14159265358979323846f * f_2sm / MCSA_FS,
        2.0f * 3.14159265358979323846f * f_2sp / MCSA_FS,
        2.0f * 3.14159265358979323846f * f_rm  / MCSA_FS,
        2.0f * 3.14159265358979323846f * f_rp  / MCSA_FS,
        2.0f * 3.14159265358979323846f * f_3   / MCSA_FS,
        2.0f * 3.14159265358979323846f * f_3rm / MCSA_FS,
        2.0f * 3.14159265358979323846f * f_3rp / MCSA_FS
    };

    float c_step[7], s_step[7];
    float oz_re[7], oz_im[7];
    float acc_re[7], acc_im[7];
    for (int i = 0; i < 7; i++) {
        c_step[i] = cosf(th_step[i]);
        s_step[i] = sinf(th_step[i]);
        oz_re[i] = 1.0f; oz_im[i] = 0.0f;
        acc_re[i] = 0.0f; acc_im[i] = 0.0f;
    }

    // Oscilador de fundamental para residuo al vuelo
    float w0_step = 2.0f * 3.14159265358979323846f * f0 / MCSA_FS;
    float w0_cos = cosf(w0_step);
    float w0_sin = sinf(w0_step);
    float fz_re = 1.0f, fz_im = 0.0f;

    // Oscilador Hann
    hz_re = 1.0f; hz_im = 0.0f;

    for (int n = 0; n < MCSA_N; n++) {
        // Renormalización periódica cada 256 muestras
        if ((n & 255) == 0 && n > 0) {
            float in_h = 1.0f / sqrtf(hz_re * hz_re + hz_im * hz_im);
            hz_re *= in_h; hz_im *= in_h;

            float in_f = 1.0f / sqrtf(fz_re * fz_re + fz_im * fz_im);
            fz_re *= in_f; fz_im *= in_f;

            for (int i = 0; i < 7; i++) {
                float in_o = 1.0f / sqrtf(oz_re[i] * oz_re[i] + oz_im[i] * oz_im[i]);
                oz_re[i] *= in_o; oz_im[i] *= in_o;
            }
        }

        float w_val = 0.5f - 0.5f * hz_re;
        float x_val = x_in[n];
        float r_val = x_val - (a_ls * fz_re + b_ls * fz_im);

        // Canales 0..3 y 5..6 operan sobre r, canal 4 (f_3) opera sobre x
        for (int i = 0; i < 7; i++) {
            float y_val = (i == 4) ? x_val : r_val;
            float yw = y_val * w_val;
            acc_re[i] += yw * oz_re[i];
            acc_im[i] -= yw * oz_im[i];

            float n_re = oz_re[i] * c_step[i] - oz_im[i] * s_step[i];
            oz_im[i]   = oz_re[i] * s_step[i] + oz_im[i] * c_step[i];
            oz_re[i]   = n_re;
        }

        // Avance de osciladores Hann y f0
        float hn_re = hz_re * h_cos - hz_im * h_sin;
        hz_im = hz_re * h_sin + hz_im * h_cos;
        hz_re = hn_re;

        float fn_re = fz_re * w0_cos - fz_im * w0_sin;
        fz_im = fz_re * w0_sin + fz_im * w0_cos;
        fz_re = fn_re;
    }

    res->A_2sm = (2.0f / sum_w) * sqrtf(acc_re[0] * acc_re[0] + acc_im[0] * acc_im[0]);
    res->A_2sp = (2.0f / sum_w) * sqrtf(acc_re[1] * acc_re[1] + acc_im[1] * acc_im[1]);
    res->A_rm  = (2.0f / sum_w) * sqrtf(acc_re[2] * acc_re[2] + acc_im[2] * acc_im[2]);
    res->A_rp  = (2.0f / sum_w) * sqrtf(acc_re[3] * acc_re[3] + acc_im[3] * acc_im[3]);
    res->A_3   = (2.0f / sum_w) * sqrtf(acc_re[4] * acc_re[4] + acc_im[4] * acc_im[4]);
    res->A_3rm = (2.0f / sum_w) * sqrtf(acc_re[5] * acc_re[5] + acc_im[5] * acc_im[5]);
    res->A_3rp = (2.0f / sum_w) * sqrtf(acc_re[6] * acc_re[6] + acc_im[6] * acc_im[6]);

    // 10. Cálculo de features (dB) relativas a A0 y SNR respecto a piso
    if (state && state->enable_ema) {
        float a = state->alpha_ema;
        float om_a = 1.0f - a;
        float p2sm = (res->A_2sm / A0) * (res->A_2sm / A0);
        float p2sp = (res->A_2sp / A0) * (res->A_2sp / A0);
        float prm  = (res->A_rm  / A0) * (res->A_rm  / A0);
        float prp  = (res->A_rp  / A0) * (res->A_rp  / A0);
        float p3   = (res->A_3   / A0) * (res->A_3   / A0);
        float p3rm = (res->A_3rm / A0) * (res->A_3rm / A0);
        float p3rp = (res->A_3rp / A0) * (res->A_3rp / A0);

        state->P_2sm = (state->P_2sm <= 0.0f) ? p2sm : (om_a * state->P_2sm + a * p2sm);
        state->P_2sp = (state->P_2sp <= 0.0f) ? p2sp : (om_a * state->P_2sp + a * p2sp);
        state->P_rm  = (state->P_rm  <= 0.0f) ? prm  : (om_a * state->P_rm  + a * prm);
        state->P_rp  = (state->P_rp  <= 0.0f) ? prp  : (om_a * state->P_rp  + a * prp);
        state->P_3   = (state->P_3   <= 0.0f) ? p3   : (om_a * state->P_3   + a * p3);
        state->P_3rm = (state->P_3rm <= 0.0f) ? p3rm : (om_a * state->P_3rm + a * p3rm);
        state->P_3rp = (state->P_3rp <= 0.0f) ? p3rp : (om_a * state->P_3rp + a * p3rp);

        res->L_2sm = 10.0f * log10f(fmaxf(state->P_2sm, 1e-12f));
        res->L_2sp = 10.0f * log10f(fmaxf(state->P_2sp, 1e-12f));
        res->L_rm  = 10.0f * log10f(fmaxf(state->P_rm,  1e-12f));
        res->L_rp  = 10.0f * log10f(fmaxf(state->P_rp,  1e-12f));
        res->L_3   = 10.0f * log10f(fmaxf(state->P_3,   1e-12f));
        res->L_3rm = 10.0f * log10f(fmaxf(state->P_3rm, 1e-12f));
        res->L_3rp = 10.0f * log10f(fmaxf(state->P_3rp, 1e-12f));
    } else {
        res->L_2sm = 20.0f * log10f(fmaxf(res->A_2sm, 1e-7f) / A0);
        res->L_2sp = 20.0f * log10f(fmaxf(res->A_2sp, 1e-7f) / A0);
        res->L_rm  = 20.0f * log10f(fmaxf(res->A_rm,  1e-7f) / A0);
        res->L_rp  = 20.0f * log10f(fmaxf(res->A_rp,  1e-7f) / A0);
        res->L_3   = 20.0f * log10f(fmaxf(res->A_3,   1e-7f) / A0);
        res->L_3rm = 20.0f * log10f(fmaxf(res->A_3rm, 1e-7f) / A0);
        res->L_3rp = 20.0f * log10f(fmaxf(res->A_3rp, 1e-7f) / A0);
    }

    res->SNR_2sm = 20.0f * log10f(fmaxf(res->A_2sm, 1e-7f) / res->floor_2sm);
    res->SNR_2sp = 20.0f * log10f(fmaxf(res->A_2sp, 1e-7f) / res->floor_2sp);
    res->SNR_2s  = fmaxf(res->SNR_2sm, res->SNR_2sp);
    res->SNR_rm  = 20.0f * log10f(fmaxf(res->A_rm,  1e-7f) / res->floor_rm);
    res->SNR_rp  = 20.0f * log10f(fmaxf(res->A_rp,  1e-7f) / res->floor_rp);
    res->SNR_3   = 20.0f * log10f(fmaxf(res->A_3,   1e-7f) / res->floor_3);
    res->SNR_3rm = 20.0f * log10f(fmaxf(res->A_3rm, 1e-7f) / res->floor_3rm);
    res->SNR_3rp = 20.0f * log10f(fmaxf(res->A_3rp, 1e-7f) / res->floor_3rp);
}

// ==================== WRAPPER PARA SAMPLES CRUDOS DE ADC ====================
void mcsa_hr_procesar_canal(
    const int16_t* adc_raw, float cal_i, McsaHrState* state, McsaHrResultados* res
) {
    if (!adc_raw || !res) return;

    // Calcular media en s_fft_re temporalmente
    float sum_adc = 0.0f;
    for (int n = 0; n < MCSA_N; n++) {
        sum_adc += (float)adc_raw[n];
    }
    float mean_adc = sum_adc / (float)MCSA_N;

    // Preprocesar x[n] = cal_i * (adc[n] - mean_adc) en s_fft_im (buffer temporal de 4096 floats)
    for (int n = 0; n < MCSA_N; n++) {
        s_fft_im[n] = cal_i * ((float)adc_raw[n] - mean_adc);
    }

    // Llamar al procesador de float
    mcsa_hr_procesar_float(s_fft_im, state, res);
}
