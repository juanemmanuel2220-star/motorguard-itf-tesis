#ifndef DETECTOR_DIR_H
#define DETECTOR_DIR_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// ==================== DETECTOR DIRECCIONAL DE FALLA ENTRE ESPIRAS ====================
// Port del detector validado en vivo el 07-oct-2026 (validacion_vivo_direccional.py, commit 39d45ed):
//   z(t)   = R2(t) / |I1(t)| * 100                      (pp de |I1|)
//   dz(t)  = z(t) - mediana(z en [t - 11 s, t - 6 s])     (referencia por componente)
//   proy   = Re{ dz * exp(-j*DIR_ANG_FALLA) }
//   alarma confirmada cuando DIR_PERSISTENCIA bloques seguidos tienen proy >= DIR_UMBRAL
// Parametros ajustados con el bloque LEVE del 06-oct-2026 (200 pares, 4 cargas). No modificar sin
// repetir la validacion ciega.
constexpr float DIR_ANG_FALLA = -81.4f;      // grados, direccion de la firma respecto a arg(V1)
constexpr float DIR_UMBRAL = 0.40f;          // pp de |I1|
constexpr uint32_t DIR_REF_DESDE_MS = 11000; // la referencia usa bloques entre t-11 s ...
constexpr uint32_t DIR_REF_HASTA_MS = 6000;  // ... y t-6 s
constexpr uint32_t DIR_HIST_MS = 30000;      // historial conservado
constexpr int DIR_PERSISTENCIA = 3;          // bloques consecutivos sobre el umbral (~5 s)
#define DIR_HIST_N 32                        // capacidad del historial (~1.7 s por bloque)

// ==================== ENCLAVAMIENTO Y SEVERIDAD (08-oct-2026) ====================
// Al confirmar la alarma se congela la referencia pre-falla (z_base). Mientras dura la alarma, la
// firma se mide contra esa base, asi una falla sostenida no se "absorbe" en la referencia movil.
// La alarma se libera cuando la proyeccion contra la base cae por debajo de
// max(DIR_UMBRAL/2, DIR_LIBERA_FRAC * proyeccion de confirmacion) durante DIR_PERSISTENCIA bloques.
constexpr float DIR_LIBERA_FRAC = 0.35f;
// Severidad = umbrales sobre |dz| (pp), entrenados con 597 pares el 08-oct-2026
// (entrenar_severidad.py, modelo M1: 0.998 dejando una carga fuera). Se clasifica con la mediana
// de los 3 bloques de confirmacion y solo puede escalar mientras la alarma siga enclavada.
constexpr float DIR_SEV_U1 = 1.626f;         // LEVE < U1 <= INTER
constexpr float DIR_SEV_U2 = 4.471f;         // INTER < U2 <= SEVERA

typedef struct {
    uint32_t t_ms[DIR_HIST_N];
    float z_re[DIR_HIST_N];
    float z_im[DIR_HIST_N];
    int n;              // bloques validos en el historial (ordenados por tiempo)
    int racha;          // bloques consecutivos con proy >= DIR_UMBRAL (referencia movil)
    int ref_ok;         // 1 si el ultimo bloque tuvo referencia suficiente (>= 2 bloques)
    float d_re, d_im;   // dz del ultimo bloque contra la referencia movil (pp)
    float proy;         // proyeccion del ultimo bloque sobre la direccion de falla (pp)
    float mag3[DIR_PERSISTENCIA];  // |dz| de los ultimos bloques (para la severidad al confirmar)
    int confirmada;     // 1 mientras la alarma esta enclavada
    // Estado enclavado
    float base_re, base_im;  // referencia pre-falla congelada al confirmar (pp)
    float proy_conf;    // proyeccion en el bloque de confirmacion (pp)
    float proy_lat;     // proyeccion contra la base congelada (pp)
    float mag_lat;      // |z - base| (pp): magnitud de la firma mientras dura la alarma
    float maglat3[DIR_PERSISTENCIA];
    int nlat;           // bloques transcurridos desde la confirmacion
    int bajos;          // bloques consecutivos bajo el nivel de liberacion
    int sev;            // 0 sin alarma, 1 LEVE, 2 INTER, 3 SEVERA
} DetectorDir;

void dir_init(DetectorDir* st);

// Procesa un bloque y devuelve la severidad enclavada (0 = sin alarma, 1..3). r2_re/r2_im en A pico,
// i1_mag = |I1| en A pico (los mismos fasores de la telemetria RAW).
int dir_step(DetectorDir* st, uint32_t t_ms, float r2_re, float r2_im, float i1_mag);

#ifdef __cplusplus
}
#endif

#endif // DETECTOR_DIR_H
