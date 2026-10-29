#include "secuencia.h"
#include <string.h>

#define PI_F 3.14159265358979323846f
#define TWO_PI_F (2.0f * PI_F)
#define SQRT3_DIV_2 0.8660254037844386f

// Operaciones complejas auxiliares en float puro
static inline ComplexFloat c_add(ComplexFloat a, ComplexFloat b) {
    ComplexFloat r = {a.re + b.re, a.im + b.im};
    return r;
}

static inline ComplexFloat c_sub(ComplexFloat a, ComplexFloat b) {
    ComplexFloat r = {a.re - b.re, a.im - b.im};
    return r;
}

static inline ComplexFloat c_mul(ComplexFloat a, ComplexFloat b) {
    ComplexFloat r = {
        a.re * b.re - a.im * b.im,
        a.re * b.im + a.im * b.re
    };
    return r;
}

static inline ComplexFloat c_scale(ComplexFloat a, float s) {
    ComplexFloat r = {a.re * s, a.im * s};
    return r;
}

static inline ComplexFloat c_conj(ComplexFloat a) {
    ComplexFloat r = {a.re, -a.im};
    return r;
}

static inline float c_abs_sq(ComplexFloat a) {
    return a.re * a.re + a.im * a.im;
}

static inline float c_abs(ComplexFloat a) {
    return sqrtf(c_abs_sq(a));
}

float estimar_f0_grandke(const int16_t* samp, float fs, int n) {
    if (!samp || n <= 0 || fs <= 0.0f) return 60.0f;

    float df = fs / (float)n;
    // Bins correspondientes a [58.5, 61.5] Hz
    int k_min = (int)floorf(58.5f / df) - 1;
    int k_max = (int)ceilf(61.5f / df) + 1;
    if (k_min < 1) k_min = 1;
    if (k_max >= n / 2) k_max = n / 2 - 1;

    // Calcular media de la señal
    float mean = 0.0f;
    for (int i = 0; i < n; i++) mean += (float)samp[i];
    mean /= (float)n;

    // Búsqueda de los bins con DFT directa aplicando ventana Hann periódica
    float max_mag = -1.0f;
    int k_star = k_min;
    float mags[256];
    int num_bins = k_max - k_min + 1;
    if (num_bins > 256) num_bins = 256;

    for (int b = 0; b < num_bins; b++) {
        int k = k_min + b;
        float dtheta = TWO_PI_F * (float)k / (float)n;
        float step_re = cosf(-dtheta);
        float step_im = sinf(-dtheta);
        float z_re = 1.0f, z_im = 0.0f;

        float dphi = TWO_PI_F / (float)n;
        float wstep_re = cosf(dphi);
        float wstep_im = sinf(dphi);
        float wz_re = 1.0f, wz_im = 0.0f;

        float acc_re = 0.0f, acc_im = 0.0f;

        for (int i = 0; i < n; i++) {
            float w = 0.5f - 0.5f * wz_re;
            float val = ((float)samp[i] - mean) * w;

            acc_re += val * z_re;
            acc_im += val * z_im;

            float nz_re = z_re * step_re - z_im * step_im;
            float nz_im = z_re * step_im + z_im * step_re;
            z_re = nz_re; z_im = nz_im;

            float nwz_re = wz_re * wstep_re - wz_im * wstep_im;
            float nwz_im = wz_re * wstep_im + wz_im * wstep_re;
            wz_re = nwz_re; wz_im = nwz_im;

            if ((i & 255) == 255) {
                float norm_z = 1.0f / sqrtf(z_re * z_re + z_im * z_im);
                z_re *= norm_z; z_im *= norm_z;
                float norm_w = 1.0f / sqrtf(wz_re * wz_re + wz_im * wz_im);
                wz_re *= norm_w; wz_im *= norm_w;
            }
        }

        float mag = sqrtf(acc_re * acc_re + acc_im * acc_im);
        mags[b] = mag;
        if (mag > max_mag) {
            max_mag = mag;
            k_star = k;
        }
    }

    int idx_star = k_star - k_min;
    if (idx_star <= 0 || idx_star >= num_bins - 1) {
        return (float)k_star * df;
    }

    float mag_left = mags[idx_star - 1];
    float mag_center = mags[idx_star];
    float mag_right = mags[idx_star + 1];

    float k_est;
    if (mag_right >= mag_left) {
        float alpha = (mag_center > 1e-12f) ? (mag_right / mag_center) : 0.0f;
        float delta = (2.0f * alpha - 1.0f) / (1.0f + alpha);
        k_est = (float)k_star + delta;
    } else {
        float alpha = (mag_center > 1e-12f) ? (mag_left / mag_center) : 0.0f;
        float delta = (2.0f * alpha - 1.0f) / (1.0f + alpha);
        k_est = (float)k_star - delta;
    }

    return k_est * df;
}

void calcular_secuencia(
    const int16_t samp_buf[6][SEC_NBIG],
    float f0,
    const float cal_v[3],
    const float cal_i[3],
    const float skew_us[6],
    ComplexFloat Y2_comp,
    ComplexFloat I2_0,
    SecuenciaResultados* res
) {
    if (!samp_buf || !res) return;
    memset(res, 0, sizeof(SecuenciaResultados));
    res->f0 = f0;

    // 1. Calcular media (offset DC) de cada uno de los 6 canales
    float mean[6];
    for (int c = 0; c < 6; c++) {
        double s = 0.0;
        for (int i = 0; i < SEC_NBIG; i++) {
            s += (double)samp_buf[c][i];
        }
        mean[c] = (float)(s / (double)SEC_NBIG);
    }

    // 2. Oscilador para carrier e^(-j * 2pi * f0 * n / Fs)
    float dtheta = TWO_PI_F * f0 / SEC_FS;
    float step_re = cosf(-dtheta);
    float step_im = sinf(-dtheta);
    float z_re = 1.0f, z_im = 0.0f;

    // Oscilador para ventana Hann periódica: w[n] = 0.5 - 0.5*cos(2pi*n / N)
    float dphi = TWO_PI_F / (float)SEC_NBIG;
    float wstep_re = cosf(dphi);
    float wstep_im = sinf(dphi);
    float wz_re = 1.0f, wz_im = 0.0f;

    // Acumuladores de fasores para los 6 canales
    float acc_re[6] = {0}, acc_im[6] = {0};

    for (int i = 0; i < SEC_NBIG; i++) {
        float w = 0.5f - 0.5f * wz_re;
        float wz_real = w * z_re;
        float wz_imag = w * z_im;

        for (int c = 0; c < 6; c++) {
            float val = (float)samp_buf[c][i] - mean[c];
            acc_re[c] += val * wz_real;
            acc_im[c] += val * wz_imag;
        }

        // Paso del oscilador carrier
        float nz_re = z_re * step_re - z_im * step_im;
        float nz_im = z_re * step_im + z_im * step_re;
        z_re = nz_re; z_im = nz_im;

        // Paso del oscilador Hann
        float nwz_re = wz_re * wstep_re - wz_im * wstep_im;
        float nwz_im = wz_re * wstep_im + wz_im * wstep_re;
        wz_re = nwz_re; wz_im = nwz_im;

        // Renormalización cada 256 muestras para prevenir deriva numérica
        if ((i & 255) == 255) {
            float norm_z = 1.0f / sqrtf(z_re * z_re + z_im * z_im);
            z_re *= norm_z; z_im *= norm_z;
            float norm_w = 1.0f / sqrtf(wz_re * wz_re + wz_im * wz_im);
            wz_re *= norm_w; wz_im *= norm_w;
        }
    }

    // Normalización: factor 2 / sum(w) = 2 / (SEC_NBIG / 2) = 4 / SEC_NBIG = 1 / 1024
    float scale_factor = 4.0f / (float)SEC_NBIG;
    ComplexFloat X[6];
    for (int c = 0; c < 6; c++) {
        X[c].re = acc_re[c] * scale_factor;
        X[c].im = acc_im[c] * scale_factor;
    }

    // 3. Compensación de retardo de muestreo secuencial (SKEW_US)
    // Para muestras tomadas en t + tau, se retarda la fase multiplicando por exp(-j * 2pi * f0 * tau)
    const float* skew = skew_us ? skew_us : DEFAULT_SKEW_US;
    for (int c = 0; c < 6; c++) {
        float tau = skew[c] * 1e-6f;
        float angle = -TWO_PI_F * f0 * tau;
        ComplexFloat rot = {cosf(angle), sinf(angle)};
        X[c] = c_mul(X[c], rot);
    }

    // 4. Aplicación de factores de calibración física
    ComplexFloat Va = c_scale(X[0], cal_v ? cal_v[0] : 1.0f);
    ComplexFloat Vb = c_scale(X[1], cal_v ? cal_v[1] : 1.0f);
    ComplexFloat Vc = c_scale(X[2], cal_v ? cal_v[2] : 1.0f);

    ComplexFloat Ia = c_scale(X[3], cal_i ? cal_i[0] : 1.0f);
    ComplexFloat Ib = c_scale(X[4], cal_i ? cal_i[1] : 1.0f);
    ComplexFloat Ic = c_scale(X[5], cal_i ? cal_i[2] : 1.0f);

    // 5 y 6. Operador de Fortescue: a = exp(j * 2pi/3) = -0.5 + j * sqrt(3)/2
    ComplexFloat a_op   = {-0.5f,  SQRT3_DIV_2};
    ComplexFloat a2_op  = {-0.5f, -SQRT3_DIV_2};

    // V1 = (Va + a*Vb + a^2*Vc) / 3
    ComplexFloat V1_raw = c_scale(c_add(Va, c_add(c_mul(a_op, Vb), c_mul(a2_op, Vc))), 1.0f / 3.0f);

    // Referencia angular respecto a V1 (phi_ref = arg(V1))
    float phi_ref = atan2f(V1_raw.im, V1_raw.re);
    ComplexFloat rot_ref = {cosf(-phi_ref), sinf(-phi_ref)};

    Va = c_mul(Va, rot_ref);
    Vb = c_mul(Vb, rot_ref);
    Vc = c_mul(Vc, rot_ref);
    Ia = c_mul(Ia, rot_ref);
    Ib = c_mul(Ib, rot_ref);
    Ic = c_mul(Ic, rot_ref);

    // Diagnóstico por fase: ángulo de cada corriente respecto a su voltaje (≈ -30..-50° en un motor)
    {
        ComplexFloat Vk[3] = {Va, Vb, Vc}, Ik[3] = {Ia, Ib, Ic};
        for (int k = 0; k < 3; k++) {
            ComplexFloat z = c_mul(Ik[k], c_conj(Vk[k]));
            res->ang_iv[k] = atan2f(z.im, z.re) * 57.29578f;
            res->mag_i[k] = c_abs(Ik[k]);
        }
    }

    // Recalcular componentes simétricas referenciadas
    ComplexFloat V1 = c_scale(c_add(Va, c_add(c_mul(a_op, Vb), c_mul(a2_op, Vc))), 1.0f / 3.0f);
    ComplexFloat V2 = c_scale(c_add(Va, c_add(c_mul(a2_op, Vb), c_mul(a_op, Vc))), 1.0f / 3.0f);

    ComplexFloat I1 = c_scale(c_add(Ia, c_add(c_mul(a_op, Ib), c_mul(a2_op, Ic))), 1.0f / 3.0f);
    ComplexFloat I2 = c_scale(c_add(Ia, c_add(c_mul(a2_op, Ib), c_mul(a_op, Ic))), 1.0f / 3.0f);

    res->V1 = V1;
    res->V2 = V2;
    res->I1 = I1;
    res->I2 = I2;

    float mag_V1 = c_abs(V1);
    float mag_V2 = c_abs(V2);
    float mag_I1 = c_abs(I1);
    float mag_I2 = c_abs(I2);

    res->u_V = (mag_V1 > 1e-6f) ? (mag_V2 / mag_V1) : 0.0f;
    res->u_I = (mag_I1 > 1e-6f) ? (mag_I2 / mag_I1) : 0.0f;

    // 7. Residuo compensado: e_2 = |I2 - Y2*V2 - I2_0| / |I1|
    ComplexFloat Y2_V2 = c_mul(Y2_comp, V2);
    ComplexFloat diff = c_sub(c_sub(I2, Y2_V2), I2_0);
    res->R2 = diff;
    float mag_diff = c_abs(diff);
    res->e_2 = (mag_I1 > 1e-6f) ? (mag_diff / mag_I1) : 0.0f;

    // 8. Guardia de dominio (NEMA MG-1: u_V <= 0.02)
    res->dom = (res->u_V <= SEC_VUF_MAX) ? 1 : 0;
}

void comisionamiento_reset(ComisionamientoState* st) {
    if (!st) return;
    memset(st, 0, sizeof(ComisionamientoState));
}

void comisionamiento_acumular(
    ComisionamientoState* st,
    ComplexFloat V2,
    ComplexFloat I2,
    ComplexFloat V1
) {
    if (!st) return;
    st->M++;
    st->sum_V2_sq += c_abs_sq(V2);
    st->sum_V2 = c_add(st->sum_V2, V2);
    st->sum_I2 = c_add(st->sum_I2, I2);
    st->sum_conjV2_I2 = c_add(st->sum_conjV2_I2, c_mul(c_conj(V2), I2));
    st->sum_V1_sq += c_abs_sq(V1);
}

bool comisionamiento_resolver(
    const ComisionamientoState* st,
    ComplexFloat* Y2_out,
    ComplexFloat* I2_0_out,
    float* cond_num
) {
    if (!st || !Y2_out || !I2_0_out || st->M < 2) return false;

    float M_f = (float)st->M;
    float S_V2sq = st->sum_V2_sq;
    ComplexFloat S_V2 = st->sum_V2;
    ComplexFloat S_I2 = st->sum_I2;
    ComplexFloat S_conjV2_I2 = st->sum_conjV2_I2;

    float D = M_f * S_V2sq - c_abs_sq(S_V2);
    float mean_V1_sq = st->sum_V1_sq / M_f;

    // Número de condición de la matriz 2x2
    float trace = S_V2sq + M_f;
    float disc = sqrtf(fmaxf(0.0f, trace * trace - 4.0f * D));
    float l_max = 0.5f * (trace + disc);
    float l_min = 0.5f * (trace - disc);
    float cn = (l_min > 1e-12f) ? (l_max / l_min) : 1e12f;
    if (cond_num) *cond_num = cn;

    // Verificar si hay diversidad de desbalance de tensión (Var(V2) >= 1e-4 * |V1|^2)
    // y si la matriz 2x2 está bien condicionada (cn <= 250).
    // Si la condición es deficiente o la red no varía de desbalance en los 30 bloques,
    // desacoplar Y2 e I2_0 conjuntas amplifica el ruido numérico.
    // La solución óptima regularizada es fijar Y2 = 0 y sustraer el desbalance base I2_0 = media(I2).
    float var_V2 = D / (M_f * M_f);
    if (cn > 250.0f || var_V2 < 1e-4f * mean_V1_sq || fabsf(D) < 1e-10f) {
        ComplexFloat zero = {0.0f, 0.0f};
        *Y2_out = zero;
        *I2_0_out = c_scale(S_I2, 1.0f / M_f);
        if (cond_num) *cond_num = 1.0f;
        return true;
    }

    // Resolver sistema normal 2x2 complejo
    // Y2 = (M * S_conjV2_I2 - conj(S_V2) * S_I2) / D
    ComplexFloat term1 = c_scale(S_conjV2_I2, M_f);
    ComplexFloat term2 = c_mul(c_conj(S_V2), S_I2);
    *Y2_out = c_scale(c_sub(term1, term2), 1.0f / D);

    // I2_0 = (-S_V2 * S_conjV2_I2 + S_V2sq * S_I2) / D
    ComplexFloat term3 = c_mul(S_V2, S_conjV2_I2);
    ComplexFloat term4 = c_scale(S_I2, S_V2sq);
    *I2_0_out = c_scale(c_sub(term4, term3), 1.0f / D);

    return true;
}
