#ifndef SECUENCIA_H
#define SECUENCIA_H

#include <stdint.h>
#include <stdbool.h>
#include <math.h>

#ifdef __cplusplus
extern "C" {
#endif

#define SEC_FS 2403.846f
#define SEC_NBIG 4096
#define SEC_VUF_MAX 0.06f       // Límite de desbalance de tensión admisible (6% IEEE 1159 / Redes Reales)

// Retardos temporales de muestreo secuencial por canal en microsegundos (ISR ADC)
// Orden: VA (c=0), VB (c=1), VC (c=2), IA (c=3), IB (c=4), IC (c=5)
static const float DEFAULT_SKEW_US[6] = {0.0f, 30.0f, 60.0f, 90.0f, 120.0f, 150.0f};

typedef struct {
    float re;
    float im;
} ComplexFloat;

typedef struct {
    float f0;              // Frecuencia fundamental estimada con Grandke (Hz)
    ComplexFloat V1;       // Fasor tensión secuencia positiva (V)
    ComplexFloat V2;       // Fasor tensión secuencia negativa (V)
    ComplexFloat I1;       // Fasor corriente secuencia positiva (A)
    ComplexFloat I2;       // Fasor corriente secuencia negativa (A)
    float u_V;             // Factor de desbalance de tensión (VUF = |V2|/|V1|)
    float u_I;             // Asimetría de corriente (|I2|/|I1|)
    ComplexFloat R2;       // Fasor residual compensado I2 - Y2*V2 - I2_0 (A, referido a arg(V1))
    float e_2;             // Residuo de secuencia negativa compensado (|I2 - Y2*V2 - I2_0| / |I1|)
    float ang_iv[3];       // Ángulo de I_k respecto a V_k por fase (grados): diagnóstico de polaridad y orden de sensores
    float mag_i[3];        // Magnitud pico de I_k por fase (A)
    int dom;               // Guardia de dominio: 1 si u_V <= SEC_VUF_MAX (0.02), 0 si fuera de dominio
} SecuenciaResultados;

typedef struct {
    int M;                      // Número de bloques acumulados
    float sum_V2_sq;            // Suma de |V2|^2
    ComplexFloat sum_V2;        // Suma de V2
    ComplexFloat sum_I2;        // Suma de I2
    ComplexFloat sum_conjV2_I2; // Suma de conj(V2) * I2
    float sum_V1_sq;            // Suma de |V1|^2
} ComisionamientoState;

/**
 * Estima f0 en la banda [58.5, 61.5] Hz mediante interpolación de Grandke sobre ventana Hann periódica.
 */
float estimar_f0_grandke(const int16_t* samp, float fs, int n);

/**
 * Calcula componentes simétricas (Fortescue) con compensación de skew y referencia angular a V1.
 * Opera sobre el bloque completo de 4096 muestras de los 6 canales.
 */
void calcular_secuencia(
    const int16_t samp_buf[6][SEC_NBIG],
    float f0,
    const float cal_v[3],
    const float cal_i[3],
    const float skew_us[6],
    ComplexFloat Y2_comp,
    ComplexFloat I2_0,
    SecuenciaResultados* res
);

/**
 * Reinicia la estructura de comisionamiento.
 */
void comisionamiento_reset(ComisionamientoState* st);

/**
 * Acumula un bloque de datos para comisionamiento del motor sano.
 */
void comisionamiento_acumular(
    ComisionamientoState* st,
    ComplexFloat V2,
    ComplexFloat I2,
    ComplexFloat V1
);

/**
 * Resuelve el sistema normal 2x2 para determinar Y2 e I2_0 de compensación.
 * Devuelve true si la solución es válida, o false si no hubo suficiente diversidad de tensión.
 */
bool comisionamiento_resolver(
    const ComisionamientoState* st,
    ComplexFloat* Y2_out,
    ComplexFloat* I2_0_out,
    float* cond_num
);

#ifdef __cplusplus
}
#endif

#endif // SECUENCIA_H
