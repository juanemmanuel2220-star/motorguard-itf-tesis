#include "detector_dir.h"
#include <math.h>
#include <string.h>

void dir_init(DetectorDir* st) {
    memset(st, 0, sizeof(DetectorDir));
}

// Mediana como statistics.median de Python: promedio de los dos centrales si n es par
static float mediana(float* v, int n) {
    for (int i = 1; i < n; i++) {
        float x = v[i];
        int j = i - 1;
        while (j >= 0 && v[j] > x) { v[j + 1] = v[j]; j--; }
        v[j + 1] = x;
    }
    return (n % 2) ? v[n / 2] : 0.5f * (v[n / 2 - 1] + v[n / 2]);
}

static int clasificar_sev(float mag) {
    return (mag >= DIR_SEV_U2) ? 3 : (mag >= DIR_SEV_U1) ? 2 : 1;
}

static float proyectar(float re, float im) {
    const float a = DIR_ANG_FALLA * 0.017453293f;
    return re * cosf(a) + im * sinf(a);
}

static void empujar(float* v, float x) {
    for (int i = 0; i < DIR_PERSISTENCIA - 1; i++) v[i] = v[i + 1];
    v[DIR_PERSISTENCIA - 1] = x;
}

int dir_step(DetectorDir* st, uint32_t t_ms, float r2_re, float r2_im, float i1_mag) {
    if (i1_mag < 1e-6f) return st->sev;
    float z_re = r2_re / i1_mag * 100.0f;
    float z_im = r2_im / i1_mag * 100.0f;

    // Referencia con los bloques previos dentro de [t - 11 s, t - 6 s]
    float ref_re[DIR_HIST_N], ref_im[DIR_HIST_N];
    int m = 0;
    for (int i = 0; i < st->n; i++) {
        uint32_t edad = t_ms - st->t_ms[i];
        if (edad <= DIR_REF_DESDE_MS && edad >= DIR_REF_HASTA_MS) {
            ref_re[m] = st->z_re[i];
            ref_im[m] = st->z_im[i];
            m++;
        }
    }

    // Agregar el bloque actual y descartar los de mas de 30 s
    int k = 0;
    for (int i = 0; i < st->n; i++) {
        if (t_ms - st->t_ms[i] <= DIR_HIST_MS) {
            st->t_ms[k] = st->t_ms[i]; st->z_re[k] = st->z_re[i]; st->z_im[k] = st->z_im[i]; k++;
        }
    }
    if (k == DIR_HIST_N) {  // historial lleno: se descarta el mas antiguo
        memmove(st->t_ms, st->t_ms + 1, (k - 1) * sizeof(uint32_t));
        memmove(st->z_re, st->z_re + 1, (k - 1) * sizeof(float));
        memmove(st->z_im, st->z_im + 1, (k - 1) * sizeof(float));
        k--;
    }
    st->t_ms[k] = t_ms; st->z_re[k] = z_re; st->z_im[k] = z_im;
    st->n = k + 1;

    // Detector con referencia movil (sin referencia suficiente no se modifica la racha)
    st->ref_ok = (m >= 2);
    float rre = 0.0f, rim = 0.0f;
    if (st->ref_ok) {
        rre = mediana(ref_re, m);
        rim = mediana(ref_im, m);
        st->d_re = z_re - rre;
        st->d_im = z_im - rim;
        st->proy = proyectar(st->d_re, st->d_im);
        st->racha = (st->proy >= DIR_UMBRAL) ? st->racha + 1 : 0;
        empujar(st->mag3, sqrtf(st->d_re * st->d_re + st->d_im * st->d_im));
    }

    if (!st->confirmada) {
        // Confirmacion: se congela la referencia pre-falla y se clasifica la severidad
        if (st->ref_ok && st->racha >= DIR_PERSISTENCIA) {
            float tmp[DIR_PERSISTENCIA];
            memcpy(tmp, st->mag3, sizeof(tmp));
            st->confirmada = 1;
            st->base_re = rre;
            st->base_im = rim;
            st->proy_conf = st->proy;
            st->proy_lat = st->proy;
            st->mag_lat = mediana(tmp, DIR_PERSISTENCIA);
            st->sev = clasificar_sev(st->mag_lat);
            memset(st->maglat3, 0, sizeof(st->maglat3));
            st->nlat = 0;
            st->bajos = 0;
        }
        return st->sev;
    }

    // Alarma enclavada: firma contra la base congelada
    float dl_re = z_re - st->base_re, dl_im = z_im - st->base_im;
    st->proy_lat = proyectar(dl_re, dl_im);
    st->mag_lat = sqrtf(dl_re * dl_re + dl_im * dl_im);
    empujar(st->maglat3, st->mag_lat);
    if (++st->nlat >= DIR_PERSISTENCIA) {
        // La severidad solo escala (una falla entre espiras no se repara sola)
        float tmp[DIR_PERSISTENCIA];
        memcpy(tmp, st->maglat3, sizeof(tmp));
        int s = clasificar_sev(mediana(tmp, DIR_PERSISTENCIA));
        if (s > st->sev) st->sev = s;
    }

    float nivel = DIR_LIBERA_FRAC * st->proy_conf;
    if (nivel < 0.5f * DIR_UMBRAL) nivel = 0.5f * DIR_UMBRAL;
    st->bajos = (st->proy_lat < nivel) ? st->bajos + 1 : 0;
    if (st->bajos >= DIR_PERSISTENCIA) {
        // Falla retirada: se libera la alarma; la racha se reinicia para no re-disparar
        st->confirmada = 0;
        st->sev = 0;
        st->racha = 0;
        st->bajos = 0;
    }
    return st->sev;
}
