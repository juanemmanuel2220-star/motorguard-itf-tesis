/* ==============================================================================
   FIRMWARE FASE 3.25 - MotorGuard ITF + IA (pipeline FFT restaurado a 3.18)
   Cambios vs 3.24:
     - NBLK 4096 -> 1024 y NAVG 1 -> 4 : se restaura el pipeline probado en
       septiembre (ratios LEVE 10-30 en todo el rango de voltaje)
     - FFT_SCALE -> 1.0 : sin inflado artificial; las features quedan en las
       MISMAS unidades que el dataset de entrenamiento (modelo desplegado)
     - Ventanas originales: A_55 (55.0-58.5 Hz), A_65 (61.5-65.0 Hz)
     - inferir_modelo(): sin divisiones (el modelo ya espera unidades crudas)
     - Modelo RF 40x6 (modelo_rf_m2c.cpp + modelo_rf_esp32.h) sin cambios
   ============================================================================== */
#include <SPI.h>
#include <math.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ILI9341.h>
#include <WiFi.h>
#include <WebServer.h>
// VA (A4=GPIO11) y VC (A5=GPIO12) estan en el ADC2 del ESP32-S3, que comparte hardware con el radio WiFi.
// Con el AP activo, el ruido de esos canales entra a la referencia angular de Fortescue (arg V1).
// 1 = AP "ITF_Banco" + dashboard web; 0 = radio apagado (adquisicion limpia).
#define HABILITAR_WIFI 0
#include <esp_timer.h>
#include <driver/gpio.h>
#define N_FEATURES_MODELO 5
float prob_rf_raw = 0.0f;
float prob_e2 = 0.0f;
float ultima_prob_leve = 0.0f;
#include "modelo_rf_flat.h"
#include "detector.h"
#include "detector_dir.h"
#include "secuencia.h"
#include "mcsa_hr.h"

// ==================== PINES TFT (SPI) ====================
#define TFT_CS 21
#define TFT_DC 17
#define TFT_RST 18
#define TFT_MOSI 38
#define TFT_MISO 47
#define TFT_SCLK 48

// ============ CANALES: INDICES DE ARREGLO (0..5) ============
#define CH_VA 0
#define CH_VB 1
#define CH_VC 2
#define CH_IA 3
#define CH_IB 4
#define CH_IC 5

// Mapeo fisico exacto validado en banco (Nano ESP32 serigrafiado):
// Sensores de VOLTAJE (ZMPT101B):
// CH_VA (0) -> Pin A4 (Voltaje Fase A)
// CH_VB (1) -> Pin A3 (Voltaje Fase B)
// CH_VC (2) -> Pin A5 (Voltaje Fase C)
// Sensores de CORRIENTE (ACS712):
// CH_IA (3) -> Pin A1 (Corriente Fase A)
// CH_IB (4) -> Pin A0 (Corriente Fase B)
// CH_IC (5) -> Pin A2 (Corriente Fase C a la FFT)
const uint8_t APIN[6] = {A4, A3, A5, A1, A0, A2};

// ============ SSR ============
// Pines fisicos (GPIO nativo ESP32-S3 correspondiente a la serigrafia):
// Pin D5 serigrafiado = GPIO 8 (F1 LEVE Fase C)
// Pin D4 serigrafiado = GPIO 7 (F2 INTERMEDIA Fase A)
// Pin D6 serigrafiado = GPIO 9 (F3 SEVERA Fase C)
#define SSR_F1 8
#define SSR_F2 7
#define SSR_F3 9

// ==================== POLARIDAD DE RELEVADORES ====================
// Modulos Songle SRD-05VDC-SL-C (+, -, S): comunmente ACTIVE-LOW (0V energiza bobina)
// o ACTIVE-HIGH si usan transistor NPN en la entrada.
// Relevadores Fotek SSR-40DA: ACTIVE-HIGH (3.3V enciende optoacoplador)
// Ahora se pueden alternar dinamicamente en tiempo real enviando 'p' por Serial.
bool f1_active_low = false;  // false = ACTIVE-HIGH (3.3V activa); true = ACTIVE-LOW (0V activa)
bool f2_active_low = false;
bool f3_active_low = false;

inline int relayActiveLevel(int n) {
  if (n == 0) return f1_active_low ? 0 : 1;
  if (n == 1) return f2_active_low ? 0 : 1;
  if (n == 2) return f3_active_low ? 0 : 1;
  return 0;
}
inline int relayInactiveLevel(int n) {
  return relayActiveLevel(n) == 1 ? 0 : 1;
}

// ===== CALIBRACION VALIDADA (123V equilibrados / 5.0A equilibrados) =====
float CAL_V[3] = {0.5503f, 0.5400f, 0.6624f};
float CAL_I[3] = {0.0181f, 0.0195f, 0.0179f};  // Recalibrado 06-oct-2026 contra pinza (A 5.0, B 5.5, C 5.1 A); IC corregido tras rehacer su divisor y alimentacion
float offset[6];
float offDyn[6];

// ==================== ADQUISICIÓN / FFT ====================
#define FS 2403.846f       // Exacto para timer de 416 us (1e6 / 416)
#define NBLK 4096          // 1 bloque de 4096 para maxima resolucion MCSA
#define NBIG 4096
#define NAVG 1             // Sin promedios incoherentes, maximo detalle frecuencial
#define MAG_BINS 683
#define BINHZ (FS / NFFT)
#define NFFT 4096
#define DISP_N 144
#define WBUF_N 480

const float FFT_SCALE = 1.0f;

// Doble buffer (Ping-Pong) para desacoplar el muestreo ADC del cálculo FFT y sincronizar por evento
int16_t samp_buf[2][6][NBIG];
volatile uint8_t active_bank = 0;
volatile uint8_t ready_bank = 0;
volatile bool new_bank_ready = false;
volatile uint16_t widx = 0;
int16_t disp[6][DISP_N];
int16_t wbuf[6][WBUF_N];
uint16_t didx = 0, wbidx = 0;
float fft_re[NFFT], fft_im[NFFT];
float hann[NBLK];
float rms[6];
float fft_mag_hz[MAG_BINS];
float fft_mag_ph[3][MAG_BINS];
float A_fund_ph[3], A_55_ph[3], A_65_ph[3], A_50_ph[3], A_70_ph[3];
float f55p_ph[3], f65p_ph[3];
float THD_ph[3], Ineg_ph[3];
uint8_t fase_critica = 2; // 0=A, 1=B, 2=C (fase con mayor distorsión/falla)
float A_55, A_65, A_50, A_70, A_fund, THD, I_neg, I_rms, V_rms;
float f55p, f65p;
float base55 = 0, base65 = 0, baseI = 0;
float base_e2 = -1.0f;
float delta_e2 = 0.0f;
float e2_max_falla = 0.0f;
bool drenando_retorno = false;

// Residuo vectorial dinamico: delta_e2 = |R2 - R2_base| / |I1| (%).
// La linea base es un FASOR (no un escalar): cualquier desplazamiento de I2 por falla
// cuenta como positivo, sin importar su direccion respecto a I2_0 comisionada.
#define E2_CENTRO    0.60f   // Centro de la sigmoide de prob_e2 (pp). PROVISIONAL: ajustar con base sana medida
#define E2_PENDIENTE 20.0f   // Pendiente de la sigmoide (1/pp)
#define E2_RETORNO   (0.6f * E2_CENTRO)  // delta_e2 bajo el cual se considera retorno a la base
#define E2_ALPHA     0.05f   // EMA de la base fasorial (tau ~ 34 s)
#define DV2_MAX      2.0f    // |V2 - V2_base|/|V1| (%) por encima del cual el bloque es un evento de alimentacion
bool evento_red = false;     // Bloque contaminado por evento de red: no se actualiza la base ni el CUSUM
ComplexFloat r2_base = {0.0f, 0.0f};
ComplexFloat v2_base = {0.0f, 0.0f};
bool r2_base_ok = false;
float ang_de2 = 0.0f;        // Angulo de R2 - R2_base respecto a V1 (grados)
float dv2_pct = 0.0f;        // |V2 - V2_base| / |V1| (%): separa eventos de red de fallas

void resetBaseResiduo() {
  r2_base_ok = false;
  base_e2 = -1.0f;
  delta_e2 = 0.0f;
  ang_de2 = 0.0f;
  dv2_pct = 0.0f;
}
uint16_t fft_disp[300];
bool motor_on = false;
float I_fast = 0;

// ==================== COMPONENTES SIMÉTRICAS / DESBALANCE ====================
SecuenciaResultados sec_res;
ComplexFloat Y2_comisionada = {0.0f, 0.0f};
ComplexFloat I2_0_comisionada = {0.0f, 0.0f};
ComisionamientoState com_state = {.M = 0, .sum_V2_sq = 0, .sum_V2 = {0,0}, .sum_I2 = {0,0}, .sum_conjV2_I2 = {0,0}, .sum_V1_sq = 0};
bool comisionando = false;
const int COM_BLOQUES_REQ = 30;

// ==================== ALMACENAMIENTO NO VOLÁTIL (NVS FLASH) ====================
#include <Preferences.h>
Preferences prefs;

void guardarComisionamientoNVS(ComplexFloat Y2, ComplexFloat I2_0, float cond) {
  prefs.begin("mg_com", false);
  prefs.putFloat("y2_re", Y2.re);
  prefs.putFloat("y2_im", Y2.im);
  prefs.putFloat("i20_re", I2_0.re);
  prefs.putFloat("i20_im", I2_0.im);
  prefs.putFloat("cond", cond);
  prefs.putBool("valid", true);
  prefs.end();
  Serial.printf(">>> [NVS FLASH] Calibracion guardada en Flash NVS: Y2=(%.4f, %.4f) | I2_0=(%.4f, %.4f) | Cond=%.1f\n",
                Y2.re, Y2.im, I2_0.re, I2_0.im, cond);
  addLog("NVS: Calibracion guardada");
}

bool cargarComisionamientoNVS(ComplexFloat* Y2, ComplexFloat* I2_0, float* cond) {
  prefs.begin("mg_com", true);
  if (!prefs.isKey("valid") || !prefs.getBool("valid", false)) {
    prefs.end();
    Serial.println(">>> [NVS FLASH] No se encontro calibracion previa en Flash NVS.");
    return false;
  }
  Y2->re = prefs.getFloat("y2_re", 0.0f);
  Y2->im = prefs.getFloat("y2_im", 0.0f);
  I2_0->re = prefs.getFloat("i20_re", 0.0f);
  I2_0->im = prefs.getFloat("i20_im", 0.0f);
  if (cond) *cond = prefs.getFloat("cond", 1.0f);
  prefs.end();
  Serial.printf(">>> [NVS FLASH] Calibracion restaurada de Flash NVS: Y2=(%.4f, %.4f) | I2_0=(%.4f, %.4f) | Cond=%.1f\n",
                Y2->re, Y2->im, I2_0->re, I2_0->im, cond ? *cond : 1.0f);
  return true;
}

void borrarComisionamientoNVS() {
  prefs.begin("mg_com", false);
  prefs.clear();
  prefs.end();
  Serial.println(">>> [NVS FLASH] Calibracion borrada de Flash NVS.");
  addLog("NVS: Calibracion borrada");
}

// ==================== MCSA DE ALTA RESOLUCIÓN ====================
McsaHrResultados mcsa_hr_res;
McsaHrState mcsa_hr_state;
int64_t hr_calc_time_us = 0;

// ==================== DETECTOR CUSUM SECUENCIAL ====================
DetectorState det_state;
int pred_cusum = 0;   // Decision del CUSUM heredado: solo telemetria y comparacion

// ==================== DETECTOR DIRECCIONAL (DECISION PRINCIPAL) ====================
// Validado en vivo el 07-oct-2026 (40 pruebas ciegas, LEVE 75 %): sens 0.95, espec 1.00.
// Desde el 08-oct-2026 enclava la alarma y clasifica la severidad (umbrales de entrenar_severidad.py).
DetectorDir det_dir;

// ==================== CLASIFICACIÓN / HISTORIAL ====================
int pred = 0; float conf = 0.95f;
uint32_t motor_on_since = 0;
const uint32_t WARMUP_MS = 60000; // 60s de bloqueo de arranque: la deriva termica/electrica del residuo I2 dura ~45 s tras el encendido
int stabCand = -1, stabCount = 0;
const int DEB_N = 3;              // Filtro de persistencia ANSI 51: 3s consecutivos para confirmar falla sostenida (100% inmutable)
#define HIST_SIZE 50
struct PredRec { float conf; int pred; uint32_t t; };
PredRec hist[HIST_SIZE]; int hist_idx = 0, hist_count = 0;

// ==================== SSR / WATCHDOG ====================
bool ssr[3] = {false, false, false};
uint32_t t_on_ini = 0, t_last_off = 0, t_on_ms = 0, act_count = 0;
const uint32_t T_MAX_ON = 12000, T_COOLDOWN = 2000;
const float I_UMBRAL = 8.0f;
const uint32_t INRUSH_BLANK_MS = 600;

// ==================== UI ====================
#define UI_MS 1000
#define PHASE_ROT_MS 5000
int view = 0;
uint8_t monPhase = 0; uint32_t lastPhase = 0;
uint32_t lastCalc = 0;
String logBuf[8]; int logIdx = 0;

#define C_SANO 0x07E0
#define C_LEVE 0xFFE0
#define C_SEV 0xF800
#define C_INT 0xFD20
#define C_BG 0x18E3
#define C_PANEL 0x2104
#define C_GRID 0x39E7
#define C_BORDER 0x4A49
#define C_WHITE 0xFFFF
#define C_DIM 0xB5B6
#define C_CYAN 0x07FF
#define C_ORANGE 0xFD20
#define C_GREEN 0x07E0

Adafruit_ILI9341 tft = Adafruit_ILI9341(TFT_CS, TFT_DC, TFT_RST);
WebServer server(80);

// ==================== PUENTE AL MODELO DE IA (NORMALIZADO) ====================
int inferir_modelo() {
  // Candado de seguridad: si el motor se esta apagando o no hay corriente/voltaje real, forzar SANO
  if (A_fund < 600.0f || I_fast < 1.5f || rms[CH_VA] < 60.0f) {
    conf = 0.99f;
    detector_init(&det_state);
    ultima_prob_leve = 0.0f;
    e2_max_falla = 0.0f;
    drenando_retorno = false;
    return 0;
  }

  float f[N_FEATURES_MODELO];
  float a_ref = (A_fund > 0.001f) ? A_fund : 1.0f;

  // Features espectrales normalizadas (invariantes a escala de corriente, carga y temperatura)
  f[0] = A_55 / a_ref;  // r_55
  f[1] = A_65 / a_ref;  // r_65
  f[2] = A_50 / a_ref;  // r_50
  f[3] = A_70 / a_ref;  // r_70
  f[4] = I_neg;         // Desbalance armónico relativo

  for (int i = 0; i < N_FEATURES_MODELO; i++) {
    if (isnan(f[i]) || isinf(f[i])) {
      f[i] = 0.0f;
    }
  }

  // Inferencia con Random Forest plano (Flash PROGMEM, float puro, sin emulación double)
  float p_leve = rf_flat_predict_proba(f);
  prob_rf_raw = p_leve;
  ultima_prob_leve = p_leve;
  conf = p_leve;
  return (p_leve >= 0.50f) ? 1 : 0;
}

// ==================== MUESTREO 2400 Hz + OFFSET DINAMICO ====================
TaskHandle_t sampTask;
esp_timer_handle_t sampTimer;
void sampTimerCb(void* arg) { xTaskNotifyGive(sampTask); }
void taskMuestreo(void*) {
  static float sm[6] = {0,0,0,0,0,0};
  static bool init = false;
  for (;;) {
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
    uint8_t cur_b = active_bank;
    for (int c = 0; c < 6; c++) {
      int16_t v = analogRead(APIN[c]);
      if (!init) { sm[c] = v; offDyn[c] = offset[c]; }
      else offDyn[c] += 0.001f * ((float)v - offDyn[c]);
      samp_buf[cur_b][c][widx] = v;
      sm[c] += 0.40f * ((float)v - sm[c]);
      disp[c][didx] = (int16_t)sm[c];
      wbuf[c][wbidx] = (int16_t)sm[c];
    }
    init = true;
    didx = (didx+1) % DISP_N; 
    wbidx = (wbidx+1) % WBUF_N;
    widx++;
    if (widx >= NBIG) {
      widx = 0;
      ready_bank = cur_b;
      active_bank = cur_b ^ 1;
      new_bank_ready = true;
    }
  }
}

// ==================== UTILIDADES ====================
void addLog(const char* m) {
  char b[64];
  snprintf(b, sizeof(b), "[%02d:%02d:%02d] %s", (int)(millis()/3600000)%24, (int)(millis()/60000)%60, (int)(millis()/1000)%60, m);
  logBuf[logIdx] = String(b); logIdx = (logIdx+1) % 8;
  Serial.println(b);
}
uint16_t colorPred(int p) { return p==-1?C_CYAN : p==0?C_SANO : p==1?C_LEVE : p==2?C_INT : C_SEV; }
// pred = severidad enclavada del detector direccional (detector_dir): 1 LEVE, 2 INTER, 3 SEVERA
const char* namePred(int p) { return p==-1?"WARMUP": p==0?"SANO": p==1?"LEVE": p==2?"INTER":"SEVERA"; }

// ==================== FFT radix-2 ====================
void fft_run(float* re, float* im, int n) {
  for (int i = 1, j = 0; i < n; i++) {
    int bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) { float t=re[i]; re[i]=re[j]; re[j]=t; t=im[i]; im[i]=im[j]; im[j]=t; }
  }
  for (int len = 2; len <= n; len <<= 1) {
    float ang = -2.0f*3.14159265f/len, wr = cosf(ang), wi = sinf(ang);
    for (int i = 0; i < n; i += len) {
      float cr = 1, ci = 0;
      for (int k = 0; k < len/2; k++) {
        int i0 = i+k, i1 = i+k+len/2;
        float tr = re[i1]*cr - im[i1]*ci, ti = re[i1]*ci + im[i1]*cr;
        re[i1] = re[i0]-tr; im[i1] = im[i0]-ti; re[i0] += tr; im[i0] += ti;
        float nr = cr*wr - ci*wi; ci = cr*wi + ci*wr; cr = nr;
      }
    }
  }
}
float peakWin(float fmin, float fmax, float* fpeak = nullptr) {
  int a = (int)(fmin/BINHZ), b = (int)(fmax/BINHZ);
  if (b > MAG_BINS-1) b = MAG_BINS-1;
  float m = 0; int mi = a;
  for (int i = a; i <= b; i++) if (fft_mag_hz[i] > m) { m = fft_mag_hz[i]; mi = i; }
  if (fpeak) *fpeak = mi*BINHZ;
  return m;
}

// ==================== CÁLCULO MCSA + motor_on CON HISTÉRESIS ====================
void calcFeatures() {
  uint8_t rb = ready_bank;
  for (int c = 0; c < 6; c++) {
    double s = 0;
    for (int i = 0; i < NBIG; i++) { 
      float d = ((float)samp_buf[rb][c][i] - offDyn[c]); 
      s += d*d; 
    }
    rms[c] = sqrtf(s/NBIG) * (c < 3 ? CAL_V[c] : CAL_I[c-3]);
  }
  float v_max = fmaxf(rms[CH_VA], fmaxf(rms[CH_VB], rms[CH_VC]));
  float v_min = fminf(rms[CH_VA], fminf(rms[CH_VB], rms[CH_VC]));
  float i_max = fmaxf(rms[CH_IA], fmaxf(rms[CH_IB], rms[CH_IC]));
  float irms_raw[3] = {rms[CH_IA], rms[CH_IB], rms[CH_IC]};
  float vrms_raw[3] = {rms[CH_VA], rms[CH_VB], rms[CH_VC]};
  for (int c = 0; c < 3; c++) if (rms[c] < 30.0f) rms[c] = 0;
  for (int c = 3; c < 6; c++) if (rms[c] < 0.30f) rms[c] = 0;

  // ================= BARRIDO FFT MULTIFASE (FASES A, B, C) =================
  for (int p = 0; p < 3; p++) {
    uint8_t chI = CH_IA + p;
    for (int i = 0; i < MAG_BINS; i++) fft_mag_hz[i] = 0;
    for (int k = 0; k < NAVG; k++) {
      int base_i = k * NBLK;
      for (int i = 0; i < NBLK; i++) {
        int16_t r = samp_buf[rb][chI][base_i + i];
        fft_re[i] = (r - offDyn[chI]) * CAL_I[p] * hann[i];
        fft_im[i] = 0;
      }
      for (int i = NBLK; i < NFFT; i++) { fft_re[i] = 0; fft_im[i] = 0; }
      fft_run(fft_re, fft_im, NFFT);
      for (int i = 0; i < MAG_BINS; i++) fft_mag_hz[i] += hypotf(fft_re[i], fft_im[i]);
    }
    for (int i = 0; i < MAG_BINS; i++) {
      fft_mag_hz[i] = (fft_mag_hz[i] / NAVG) * FFT_SCALE;
      fft_mag_ph[p][i] = fft_mag_hz[i];
    }

    float f0 = 60.0f;
    A_fund_ph[p] = peakWin(58.5f, 61.5f, &f0);
    A_55_ph[p]   = peakWin(53.5f, 57.8f, &f55p_ph[p]);
    A_65_ph[p]   = peakWin(62.4f, 66.5f, &f65p_ph[p]);
    A_50_ph[p]   = peakWin(47.0f, 53.0f);
    A_70_ph[p]   = peakWin(67.0f, 73.0f);
    float th = 0;
    const float harm[5] = {120,180,240,300,360};
    for (int h = 0; h < 5; h++) { float a = peakWin(harm[h]-2, harm[h]+2); th += a*a; }
    THD_ph[p] = (A_fund_ph[p] > 0) ? sqrtf(th)/A_fund_ph[p] : 0;
    Ineg_ph[p] = ((A_55_ph[p]+A_65_ph[p]) > 0) ? fabsf(A_55_ph[p]-A_65_ph[p])/(A_55_ph[p]+A_65_ph[p]) : 0;
  }

  // ================= DETECCIÓN DE MOTOR ENCENDIDO =================
  // Exige corriente de 60 Hz real (FFT), no solo RMS: una entrada flotante o un sensor con mal
  // contacto produce RMS alto sin fundamental y antes mantenía "Motor:ON" sin motor.
  // Amplitud Hann (suma de ventana N/2): A_fund = I_pico * 1024  ->  I_rms = A_fund / 1448.2
  // Un motor trifásico real tiene corriente de 60 Hz en las TRES fases y voltaje en las TRES;
  // una sola entrada flotante que capta zumbido de la red no basta para encenderlo.
  float i_fund = 0.0f;
  int fases_on = 0, fases_min = 0;
  for (int p = 0; p < 3; p++) {
    float f = A_fund_ph[p] / 1448.2f;
    if (f > i_fund) i_fund = f;
    bool sen = f > 0.6f * irms_raw[p];
    if (sen && f > 1.0f) fases_on++;
    if (sen && f > 0.5f) fases_min++;
  }
  bool senoidal = fases_on == 3;
  bool senal = motor_on ? (fases_min >= 2) : (v_min > 60.0f && fases_on == 3);
  static uint8_t cntOn = 0, cntOff = 0;
  if (senal) { if (cntOn<250) cntOn++; cntOff=0; } else { if (cntOff<250) cntOff++; cntOn=0; }
  if (!motor_on) {
    Serial.printf("[MOTOR_DET] V=%.1f/%.1f/%.1f I=%.2f/%.2f/%.2f I60max=%.2f fases60Hz=%d/3 cntOn=%u off=%.0f/%.0f/%.0f/%.0f/%.0f/%.0f\n",
                  vrms_raw[0], vrms_raw[1], vrms_raw[2], irms_raw[0], irms_raw[1], irms_raw[2], i_fund, fases_on, cntOn,
                  offDyn[CH_VA], offDyn[CH_VB], offDyn[CH_VC], offDyn[CH_IA], offDyn[CH_IB], offDyn[CH_IC]);
  }
  if (!motor_on && cntOn >= 3) motor_on = true;
  if ( motor_on && cntOff >= 3) motor_on = false;

  // Identificación de la fase con mayor evidencia de falla (máximo ratio de armónicos respecto a fundamental)
  float max_ind = -1.0f;
  uint8_t best_p = 2; // Por defecto Fase C
  for (int p = 0; p < 3; p++) {
    float a_ref = (A_fund_ph[p] > 10.0f) ? A_fund_ph[p] : 1.0f;
    float ind = (A_65_ph[p] + A_55_ph[p]) / a_ref;
    if (ind > max_ind) {
      max_ind = ind;
      best_p = p;
    }
  }
  fase_critica = best_p;

  // Asignar variables del sistema a la fase crítica
  A_fund = A_fund_ph[fase_critica];
  A_55   = A_55_ph[fase_critica];
  A_65   = A_65_ph[fase_critica];
  A_50   = A_50_ph[fase_critica];
  A_70   = A_70_ph[fase_critica];
  f55p   = f55p_ph[fase_critica];
  f65p   = f65p_ph[fase_critica];
  THD    = THD_ph[fase_critica];
  I_neg  = Ineg_ph[fase_critica];

  if (!motor_on) {
    for (int c = 0; c < 6; c++) rms[c] = 0.0f;
    I_fast = 0.0f;
    I_rms = 0.0f;
    V_rms = 0.0f;
    A_55 = A_65 = A_50 = A_70 = A_fund = THD = I_neg = 0; f55p = f65p = 60;
    for (int p = 0; p < 3; p++) {
      A_fund_ph[p] = A_55_ph[p] = A_65_ph[p] = A_50_ph[p] = A_70_ph[p] = 0;
      THD_ph[p] = Ineg_ph[p] = 0;
    }
    for (int i = 0; i < 300; i++) fft_disp[i] = 0;
    resetBaseResiduo();
    e2_max_falla = 0.0f;
    drenando_retorno = false;
  } else {
    // Restaurar fft_mag_hz con el espectro de la fase crítica para el display gráfico
    for (int i = 0; i < MAG_BINS; i++) fft_mag_hz[i] = fft_mag_ph[fase_critica][i];

    // Líneas base: inicializar en WARMUP o primer bloque sano.
    // Desacoplado 100% del estado del relé (sin condicional ssr_off).
    if (pred == -1 || base65 <= 0.0f) {
      base55 = A_55; base65 = A_65; baseI = I_rms;
      resetBaseResiduo();
      e2_max_falla = 0.0f;
      drenando_retorno = false;
    }
    for (int i = 0; i < 300; i++) {
      int a = i*342/300, b = (i+1)*342/300; if (b <= a) b = a+1;
      uint16_t m = 0;
      for (int j = a; j < b && j < MAG_BINS; j++) if (fft_mag_hz[j] > m) m = fft_mag_hz[j];
      fft_disp[i] = m;
    }
    I_rms = rms[CH_IA + fase_critica];
    V_rms = rms[CH_VA + fase_critica];
  }

  // ==================== CÁLCULO MCSA DE ALTA RESOLUCIÓN Y FORTESCUE ====================
  if (motor_on) {
    // 1. Cálculo MCSA de alta resolución (HR-MCSA): Grandke f0, deslizamiento y Goertzel
    int64_t t_hr_start = esp_timer_get_time();
    uint8_t ch_i_crit = CH_IA + fase_critica;
    mcsa_hr_procesar_canal(
      (const int16_t*)samp_buf[rb][ch_i_crit],
      CAL_I[fase_critica],
      &mcsa_hr_state,
      &mcsa_hr_res
    );
    hr_calc_time_us = esp_timer_get_time() - t_hr_start;

    // 2. Frecuencia fundamental f0 exacta estimada por Grandke en rango físico [58.0, 62.0] Hz
    float f0_calc = (mcsa_hr_res.f0 > 58.0f && mcsa_hr_res.f0 < 62.0f) ? mcsa_hr_res.f0 : 60.0f;

    // 3. Componentes Simétricas (Fortescue) calculadas con la f0 real medida
    calcular_secuencia(
      (const int16_t (*)[SEC_NBIG])samp_buf[rb],
      f0_calc,
      CAL_V,
      CAL_I,
      DEFAULT_SKEW_US,
      Y2_comisionada,
      I2_0_comisionada,
      &sec_res
    );

    // Acumulación de comisionamiento de motor sano si fue solicitado por comando 'k'
    if (comisionando && !ssr[0] && !ssr[1] && !ssr[2]) {
      comisionamiento_acumular(&com_state, sec_res.V2, sec_res.I2, sec_res.V1);
      if (com_state.M >= COM_BLOQUES_REQ) {
        float cond_num = 1.0f;
        if (comisionamiento_resolver(&com_state, &Y2_comisionada, &I2_0_comisionada, &cond_num)) {
          Serial.printf(">>> [COMISIONAMIENTO COMPLETADO] M=%d | Y2=(%.4f, %.4f) | I2_0=(%.4f, %.4f) | Cond=%.2f\n",
                        com_state.M, Y2_comisionada.re, Y2_comisionada.im,
                        I2_0_comisionada.re, I2_0_comisionada.im, cond_num);
          guardarComisionamientoNVS(Y2_comisionada, I2_0_comisionada, cond_num);
          char b[64];
          snprintf(b, sizeof(b), "Comisionado: Cond=%.1f", cond_num);
          addLog(b);
          base55 = A_55; base65 = A_65; baseI = I_rms;
          // Recalcular secuencia inmediatamente con los parámetros comisionados
          calcular_secuencia(
            (const int16_t (*)[SEC_NBIG])samp_buf[rb],
            f0_calc,
            CAL_V,
            CAL_I,
            DEFAULT_SKEW_US,
            Y2_comisionada,
            I2_0_comisionada,
            &sec_res
          );
          resetBaseResiduo();  // La base fasorial se re-inicializa en el siguiente bloque sano
          Serial.printf(">>> [LINEA BASE e2] e2 comisionado = %.3f%% (base fasorial se reinicia)\n", sec_res.e_2 * 100.0f);
        }
        detector_init(&det_state); dir_init(&det_dir);
        pred = 0;
        comisionando = false;
      }
    }
  } else {
    memset(&sec_res, 0, sizeof(SecuenciaResultados));
    sec_res.dom = 1;
    memset(&mcsa_hr_res, 0, sizeof(McsaHrResultados));
    mcsa_hr_res.f0 = 60.0f;
    mcsa_hr_res.s = 0.012f;
    hr_calc_time_us = 0;
  }
}

// ==================== INFERENCIA CON RANDOM FOREST Y DETECTOR CUSUM ====================
void clasificar() {
  static bool prev_motor = false;
  if (motor_on && !prev_motor) { 
    motor_on_since = millis(); 
    addLog("Motor ON: warmup 60s"); 
  }
  prev_motor = motor_on;
  bool warmup = motor_on && (millis() - motor_on_since < WARMUP_MS);

  int pred_prev = pred;

  if (!motor_on) {
    pred = 0;
    pred_cusum = 0;
    conf = 0.0f;
    detector_init(&det_state);
    dir_init(&det_dir);
    ultima_prob_leve = 0.0f;
    prob_rf_raw = 0.0f;
    prob_e2 = 0.0f;
    e2_max_falla = 0.0f;
    drenando_retorno = false;
  } else if (warmup) {
    pred = -1; // -1 = WARMUP explícito
    pred_cusum = 0;
    conf = 0.0f;
    detector_set_warmup(&det_state, 1);
    dir_init(&det_dir);
    ultima_prob_leve = 0.0f;
    prob_rf_raw = 0.0f;
    prob_e2 = 0.0f;
    e2_max_falla = 0.0f;
    drenando_retorno = false;
  } else {
    detector_set_warmup(&det_state, 0);
    // 1. Inferencia del modelo Random Forest plano (Flash PROGMEM)
    inferir_modelo(); // Actualiza prob_rf_raw y ultima_prob_leve

    // 2. Probabilidad basada en el residuo VECTORIAL de secuencia negativa (Fortescue)
    //    delta_e2 = |R2 - R2_base| / |I1|, con R2 = I2 - Y2*V2 - I2_0 y R2_base un fasor
    //    seguido por EMA en reposo sano. A diferencia de |R2| - base escalar, no depende de
    //    la direccion del desplazamiento de I2 respecto a I2_0 (comisionada con Y2 = 0).
    prob_e2 = 0.0f;
    delta_e2 = 0.0f;
    evento_red = false;
    if (com_state.M >= COM_BLOQUES_REQ && sec_res.dom == 1) {
      float i1_mag = sqrtf(sec_res.I1.re * sec_res.I1.re + sec_res.I1.im * sec_res.I1.im);
      float v1_mag = sqrtf(sec_res.V1.re * sec_res.V1.re + sec_res.V1.im * sec_res.V1.im);
      // Inicialización y seguimiento adaptativo de la base fasorial (tau ~ 34 s, alpha = 0.05)
      // La base SOLO se actualiza cuando el detector está en reposo sano (S < H_off = 1.25 y pred == 0)
      // Guardia de red: el desbalance de tensión cambió respecto a la base (corte, transitorio, maniobra)
      if (r2_base_ok && v1_mag > 1e-6f) {
        float pv_re = sec_res.V2.re - v2_base.re, pv_im = sec_res.V2.im - v2_base.im;
        evento_red = (100.0f * sqrtf(pv_re * pv_re + pv_im * pv_im) / v1_mag) > DV2_MAX;
      }
      if (!r2_base_ok) {
        r2_base = sec_res.R2;
        v2_base = sec_res.V2;
        r2_base_ok = true;
      } else if (!evento_red && pred_cusum == 0 && det_state.S < CUSUM_HOFF) {
        r2_base.re += E2_ALPHA * (sec_res.R2.re - r2_base.re);
        r2_base.im += E2_ALPHA * (sec_res.R2.im - r2_base.im);
        v2_base.re += E2_ALPHA * (sec_res.V2.re - v2_base.re);
        v2_base.im += E2_ALPHA * (sec_res.V2.im - v2_base.im);
      }
      float d_re = sec_res.R2.re - r2_base.re;
      float d_im = sec_res.R2.im - r2_base.im;
      float dv_re = sec_res.V2.re - v2_base.re;
      float dv_im = sec_res.V2.im - v2_base.im;
      if (i1_mag > 1e-6f) {
        delta_e2 = 100.0f * sqrtf(d_re * d_re + d_im * d_im) / i1_mag;
        base_e2  = 100.0f * sqrtf(r2_base.re * r2_base.re + r2_base.im * r2_base.im) / i1_mag;
      }
      if (v1_mag > 1e-6f) dv2_pct = 100.0f * sqrtf(dv_re * dv_re + dv_im * dv_im) / v1_mag;
      ang_de2 = atan2f(d_im, d_re) * 57.29578f;

      // Sigmoide sobre la magnitud del desplazamiento fasorial
      float z_e2 = -E2_PENDIENTE * (delta_e2 - E2_CENTRO);
      if (z_e2 > 20.0f) z_e2 = 20.0f;
      if (z_e2 < -20.0f) z_e2 = -20.0f;
      prob_e2 = 1.0f / (1.0f + expf(z_e2));
    }

    // 3. Detector secuencial CUSUM: Fusión multimodal desacoplada térmicamente (Zero SSR)
    // - Durante falla activa: e2 sube hasta e2_max_falla y MCSA activa (L_2sm > 0 dB, P_RF > 50%).
    // - Al separar los lazos (puente manual o SSR abierto):
    //   La corriente de espira cesa de inmediato. e2 cae respecto al pico
    //   (caída >= 0.15%), y el espectro MCSA se desploma (L_2sm < -20 dB, r_55/r_65 limpios).
    // - ENCLAVAMIENTO (LATCH) DE DRENADO: Al detectar la separación física de los cables,
    //   el sistema enclava `drenando_retorno = true` y fuerza prob_entrada_cusum = 0.02f
    //   hasta que CUSUM confirma el retorno a SANO (pred == 0).
    //   Esto previene el bloqueo térmico por re-cebado debido al calentamiento residual del cobre.
    // - Si ocurre un re-contacto accidental durante el drenado, el rebrote de e2 y MCSA
    //   desenclava de inmediato `drenando_retorno = false` y reactiva la alarma en < 2.8 s.
    float prob_entrada_cusum = prob_rf_raw;
    if (com_state.M >= COM_BLOQUES_REQ && sec_res.dom == 1) {
      // El seguimiento de pico/caída opera sobre el desplazamiento fasorial (siempre >= 0)
      float e2_pct = delta_e2;
      if (det_state.current_decision == DETECTOR_ALARMA) {
        if (!drenando_retorno) {
          // Fase 1: En alarma activa, registrar pico máximo de e2
          if (e2_pct > e2_max_falla) e2_max_falla = e2_pct;
          float caida_pico = e2_max_falla - e2_pct;

          // Criterios multimodales de separación física de espiras:
          bool caida_e2_ok = (caida_pico >= 0.15f) && (prob_rf_raw < 0.60f);
          bool desplome_mcsa = (mcsa_hr_res.L_2sm < -20.0f) && (caida_pico >= 0.10f);
          bool retorno_base = (delta_e2 < E2_RETORNO);

          if (caida_e2_ok || desplome_mcsa || retorno_base) {
            drenando_retorno = true;
            Serial.printf("[Zero SSR] Separacion detectada (caida=%.2f%%, L2s=%.1fdB, delta=%.2f%%). Enclavando drenado...\n",
                          caida_pico, mcsa_hr_res.L_2sm, delta_e2);
          }
        } else {
          // Fase 2: Enclava en drenado. Verificar si hay re-inyección / re-contacto
          float rebrote_e2 = e2_pct - (e2_max_falla - 0.10f);
          bool recontacto = (rebrote_e2 > 0.0f && prob_rf_raw > 0.60f) || (mcsa_hr_res.L_2sm > -15.0f && mcsa_hr_res.slip_ok);
          if (recontacto) {
            drenando_retorno = false;
            if (e2_pct > e2_max_falla) e2_max_falla = e2_pct;
            Serial.println("[Zero SSR] Re-contacto detectado durante drenado. Reactivando alarma.");
          }
        }

        if (drenando_retorno) {
          prob_entrada_cusum = 0.02f; // Forzar drenado acelerado (-3.85 / bloque, retorno en ~3.2 s)
        } else {
          prob_entrada_cusum = prob_e2; // Falla física sostenida
        }
      } else {
        // En reposo sano
        e2_max_falla = 0.0f;
        drenando_retorno = false;
        prob_entrada_cusum = prob_e2;
      }
    }
    DetectorDecision decision;
    if (evento_red) {
      // Bloque descartado: se mantiene el estado del CUSUM sin acumular evidencia
      decision = (DetectorDecision)det_state.current_decision;
      Serial.printf("[RED] Evento de alimentacion (dV2=%.2f%% > %.1f%%): bloque excluido del CUSUM\n", dv2_pct, DV2_MAX);
    } else {
      decision = detector_step(prob_entrada_cusum, &det_state);
    }
    int pred_cusum_prev = pred_cusum;
    pred_cusum = (decision == DETECTOR_ALARMA) ? 1 : 0;

    // Al confirmar retorno de ALARMA -> SANO del CUSUM, reajustar su base fasorial al residuo térmico actual
    if (pred_cusum_prev == 1 && pred_cusum == 0) {
      r2_base = sec_res.R2;
      v2_base = sec_res.V2;
      r2_base_ok = true;
      delta_e2 = 0.0f;
      e2_max_falla = 0.0f;
      drenando_retorno = false;
      Serial.printf("[Zero SSR] Retorno a SANO confirmado. Base fasorial resincronizada (|R2|/|I1| = %.3f%%)\n", sec_res.e_2 * 100.0f);
    }

    // 4. Decision principal: detector direccional sobre el residuo crudo R2 (independiente del CUSUM).
    //    Devuelve la severidad enclavada: 0 sano, 1 LEVE, 2 INTER, 3 SEVERA.
    float i1_dir = sqrtf(sec_res.I1.re * sec_res.I1.re + sec_res.I1.im * sec_res.I1.im);
    pred = dir_step(&det_dir, millis(), sec_res.R2.re, sec_res.R2.im, i1_dir);
    // Confianza = 1 con la alarma enclavada; si no, avance de la persistencia (0, 1/3, 2/3)
    conf = det_dir.confirmada ? 1.0f
         : (float)(det_dir.racha < DIR_PERSISTENCIA ? det_dir.racha : DIR_PERSISTENCIA) / (float)DIR_PERSISTENCIA;
  }

  if (pred != pred_prev) {
    char b[48]; 
    if (pred == -1) snprintf(b, sizeof(b), "Estado -> WARMUP");
    else if (!motor_on) snprintf(b, sizeof(b), "Motor apagado -> SANO");
    else snprintf(b, sizeof(b), "IA -> %s (|dR2|=%.2fpp)", namePred(pred), det_dir.mag_lat);
    addLog(b);
  }

  hist[hist_idx].conf = conf; hist[hist_idx].pred = pred; hist[hist_idx].t = millis();
  hist_idx = (hist_idx+1) % HIST_SIZE; if (hist_count < HIST_SIZE) hist_count++;
}

// ==================== SSR ====================
void ssrOff(bool forzado) {
  bool alguno = false;
  for (int i = 0; i < 3; i++) {
    if (ssr[i]) { ssr[i] = false; alguno = true; }
    uint8_t pin = (i == 0) ? SSR_F1 : (i == 1) ? SSR_F2 : SSR_F3;
    gpio_num_t gpio = (gpio_num_t)((i == 0) ? 8 : (i == 1) ? 7 : 9);
    digitalWrite(pin, relayInactiveLevel(i));
    gpio_set_level(gpio, relayInactiveLevel(i));
  }
  if (alguno) { 
    t_on_ms = millis()-t_on_ini; 
    t_last_off = millis(); 
    Serial.printf("[DEBUG SSR] Apagado. Forzado: %d | T_ON: %lu ms\n", forzado, t_on_ms);
    addLog(forzado ? "SSR OFF forzado (watchdog)" : "SSR DESACTIVADO"); 
  }
}
bool ssrOn(int n) {
  Serial.printf("[DEBUG SSR] Solicitud F%d | I_rms=%.2fA | Cooldown=%lu ms\n", 
                n+1, I_rms, (millis() - t_last_off));
  if (n < 0 || n > 2) return false;
  if (!motor_on) {
    Serial.println("[DEBUG SSR] Rechazado: Motor apagado. Peligro de Inrush.");
    addLog("Motor off: aborta SSR");
    return false;
  }
  if (ssr[0] || ssr[1] || ssr[2]) { 
    Serial.println("[DEBUG SSR] Rechazado: Ya hay un SSR activo.");
    addLog("SSR ya activo"); 
    return false; 
  }
  if (millis()-t_last_off < T_COOLDOWN) { 
    Serial.printf("[DEBUG SSR] Rechazado: Cooldown activo (%lu/%lu ms).\n", (millis()-t_last_off), T_COOLDOWN);
    addLog("Cooldown activo, ignora /on"); 
    return false; 
  }
  if (I_rms > I_UMBRAL) { 
    Serial.printf("[DEBUG SSR] Rechazado: I_rms=%.2fA supera umbral %.1fA\n", I_rms, I_UMBRAL);
    char b[40]; snprintf(b, sizeof(b), "Aborto: I_rms=%.1fA", I_rms); 
    addLog(b); 
    return false; 
  }
  ssr[n] = true; t_on_ini = millis(); act_count++;
  uint8_t pin = (n == 0) ? SSR_F1 : (n == 1) ? SSR_F2 : SSR_F3;
  gpio_num_t gpio = (gpio_num_t)((n == 0) ? 8 : (n == 1) ? 7 : 9);
  digitalWrite(pin, relayActiveLevel(n));
  gpio_set_level(gpio, relayActiveLevel(n));
  Serial.printf("[DEBUG SSR] Exito: GPIO %d puesto en %s (%dV)\n", 
                gpio, relayActiveLevel(n) ? "HIGH" : "LOW", relayActiveLevel(n) ? 3 : 0);
  char b[40]; snprintf(b, sizeof(b), "SSR F%d ACTIVADO (%s)", n+1, namePred(n+1)); 
  addLog(b);
  return true;
}

// ==================== RENDER TFT ====================
void drawHeader() {
  bool warmup = motor_on && (millis() - motor_on_since < WARMUP_MS);
  uint16_t bg = !motor_on ? C_PANEL : (warmup ? 0x03E0 : (pred > 0 ? colorPred(pred) : 0x04E0));
  tft.fillRect(0, 0, 320, 24, bg);
  uint32_t per = (pred == 3) ? 500 : ((pred >= 1) ? 1000 : 0);
  bool brillo = (per == 0) || ((millis() / per) % 2 == 0);
  tft.fillCircle(10, 12, 6, motor_on ? (brillo ? (pred > 0 ? C_WHITE : (warmup ? C_CYAN : colorPred(pred))) : C_PANEL) : C_DIM);
  uint16_t txtCol = (motor_on && !warmup && (pred == 1 || pred == 2)) ? 0x0000 : C_WHITE;
  tft.setTextColor(txtCol, bg); tft.setTextSize(2); tft.setCursor(24, 5);
  if (!motor_on) {
    tft.print("MOTOR APAGADO");
  } else if (warmup) {
    int rem = (int)((WARMUP_MS - (millis() - motor_on_since)) / 1000) + 1;
    tft.printf("[WARMUP %ds]", rem);
  } else if (pred > 0) {
    tft.printf("[%s %c] Conf:%.0f%%", namePred(pred), (char)('A' + fase_critica), conf*100.0f);
  } else {
    tft.printf("[%s] Conf:%.0f%%", namePred(pred), conf*100.0f);
  }
  char clk[9]; snprintf(clk, sizeof(clk), "%02d:%02d:%02d", (int)(millis()/3600000)%24, (int)(millis()/60000)%60, (int)(millis()/1000)%60);
  tft.setCursor(224, 5); tft.print(clk);
}
void drawTabBar() {
  tft.fillRect(0, 216, 320, 24, C_PANEL);
  tft.drawFastHLine(0, 216, 320, C_BORDER);
  const char* names[4] = {"Mon", "FFT", "Hist", "Cfg"};
  for (int i = 0; i < 4; i++) {
    if (i == view) { tft.fillRect(i*80, 217, 80, 23, C_BORDER); tft.setTextColor(C_WHITE, C_BORDER); tft.setTextSize(2); tft.setCursor(i*80+30, 221); }
    else { tft.setTextColor(C_DIM, C_PANEL); tft.setTextSize(1); tft.setCursor(i*80+34, 225); }
    tft.print(names[i]);
  }
}
void wavePanel(int x, int y, int ch, uint16_t col, const char* lbl, float val, const char* unit, bool alert) {
  tft.drawRect(x, y, 152, 72, C_BORDER);
  tft.fillRect(x+1, y+1, 150, 70, C_BG);
  tft.setTextColor(C_DIM, C_BG); tft.setTextSize(1); tft.setCursor(x+4, y+2); tft.print(lbl);
  tft.drawFastHLine(x+4, y+30, 144, C_GRID);
  if (!motor_on || val <= 0.05f) {
    // Motor apagado o canal sin señal: linea plana en reposo sobre el eje central
    tft.drawFastHLine(x+4, y+48, 144, col);
  } else {
    float mn = 32000, mx = -32000;
    for (int i = 0; i < DISP_N; i++) { int16_t v = disp[ch][(didx+i)%DISP_N]; if (v<mn)mn=v; if (v>mx)mx=v; }
    float rng = (mx-mn) > 40 ? (mx-mn) : 40;
    int16_t py[DISP_N];
    for (int i = 0; i < DISP_N; i++) {
      int16_t v = disp[ch][(didx+i)%DISP_N];
      py[i] = (int16_t)(y+38 + 21 - (v-mn)*42.0f/rng);
    }
    for (int i = 1; i < DISP_N; i++) tft.drawLine(x+4+i-1, py[i-1], x+4+i, py[i], col);
  }
  tft.setTextColor(alert?0xFFE0:col, C_BG); tft.setTextSize(2); tft.setCursor(x+4, y+56);
  tft.printf("%.1f %s RMS", val, unit);
}
void drawFFTpanel(int x, int y, int w, int h, bool grande) {
  tft.drawRect(x, y, w, h, C_BORDER);
  tft.fillRect(x+1, y+1, w-2, h-2, C_BG);
  tft.setTextColor(C_DIM, C_BG); tft.setTextSize(1); tft.setCursor(x+4, y+2); tft.print("FFT");
  int gy = y+h-14, gh = h-24;
  float maxm = 1; for (int i = 0; i < 300; i++) if (fft_disp[i] > maxm) maxm = fft_disp[i];
  int x55 = x+4+(int)(55.0f/100*(w-8)), x60 = x+4+(int)(60.0f/100*(w-8)), x65 = x+4+(int)(65.0f/100*(w-8));
  for (int i = 0; i < 300; i++) {
    int bx = x+4+i*(w-8)/300;
    int bh = (int)(sqrtf(fft_disp[i]/maxm)*gh);
    uint16_t c = C_CYAN;
    if (abs(bx-x55) <= 2 || abs(bx-x65) <= 2) c = C_SEV;
    else if (abs(bx-x60) <= 2) c = C_GREEN;
    if (bh > 0) tft.drawFastVLine(bx, gy-bh, bh, c);
  }
  if (grande) {
    tft.setTextColor(C_DIM, C_BG);
    for (int f = 0; f <= 100; f += 20) { tft.setCursor(x+4+f*(w-8)/100-4, y+h-10); tft.print(f); }
  }
  tft.setTextColor(C_SEV, C_BG); tft.setCursor(x55-8, y+h-10); tft.print("55");
  tft.setCursor(x65-8, y+h-10); tft.print("65");
}
void drawStatusBar() {
  bool warmup = motor_on && (millis() - motor_on_since < WARMUP_MS);
  bool ssrAct = ssr[0] || ssr[1] || ssr[2];
  uint16_t c = !motor_on ? C_DIM : (warmup ? C_CYAN : (pred > 0 ? colorPred(pred) : (ssrAct ? C_ORANGE : C_SANO)));
  tft.fillRoundRect(10, 184, 300, 28, 6, c);
  tft.fillCircle(30, 198, 8, C_WHITE);
  tft.fillCircle(30, 198, 5, c);
  // Texto con alto contraste segun el fondo
  uint16_t txtCol = (motor_on && !warmup && (pred == 1 || pred == 2)) ? 0x0000 : C_WHITE;
  tft.setTextColor(txtCol, c); tft.setTextSize(3); tft.setCursor(48, 187);
  if (!motor_on) {
    tft.print("OFF");
  } else if (warmup) {
    tft.print("WARMUP");
  } else if (pred > 0) {
    tft.print(namePred(pred));
  } else {
    tft.print("SANO");
  }
  tft.setTextSize(2); tft.setCursor(180, 190);
  if (warmup) {
    int rem = (int)((WARMUP_MS - (millis() - motor_on_since)) / 1000) + 1;
    tft.printf("Espere %ds", rem);
  } else {
    tft.printf("Conf:%.0f%%", conf*100.0f);
  }
}
void drawMon() {
  if (millis()-lastPhase > PHASE_ROT_MS) { lastPhase = millis(); monPhase = (monPhase+1) % 3; }
  tft.fillRect(0, 24, 320, 192, C_BG);
  char li[10], lv[10];
  snprintf(li, sizeof(li), "I_%c (A)", 'A'+monPhase);
  snprintf(lv, sizeof(lv), "V_%c (V)", 'A'+monPhase);
  wavePanel(4, 28, CH_IA+monPhase, C_CYAN, li, rms[CH_IA+monPhase], "A", rms[CH_IA+monPhase] > 6.5f);
  wavePanel(164, 28, CH_VA+monPhase, C_ORANGE, lv, rms[CH_VA+monPhase], "V", rms[CH_VA+monPhase] > 0 && (rms[CH_VA+monPhase] < 100 || rms[CH_VA+monPhase] > 140));
  drawFFTpanel(4, 104, 312, 76, false);
  drawStatusBar();
}
void drawFFTview() {
  tft.fillRect(0, 24, 320, 192, C_BG);
  drawFFTpanel(4, 28, 312, 130, true);
  float slip = (f65p-f55p)/240.0f;
  tft.setTextSize(1);
  tft.setTextColor(C_CYAN, C_BG);  tft.setCursor(8, 164);  tft.printf("F1=60.0Hz Slip=%.3f", slip);
  tft.setTextColor(C_SEV, C_BG);   tft.setCursor(8, 178);  tft.printf("f1-2sf1=%.1fHz A55=%.1f", f55p, A_55);
  tft.setCursor(8, 192);           tft.printf("f1+2sf1=%.1fHz A65=%.1f", f65p, A_65);
  tft.setTextColor(C_DIM, C_BG);   tft.setCursor(8, 206);  tft.printf("THD=%.3f Ineg=%.3f Irms=%.2fA", THD, I_neg, I_rms);

  // Badge de diagnostico IA en vista FFT (visible en todo momento)
  bool warmup = motor_on && (millis() - motor_on_since < WARMUP_MS);
  uint16_t bc = !motor_on ? C_DIM : (warmup ? C_CYAN : colorPred(pred));
  uint16_t btc = (motor_on && !warmup && (pred == 1 || pred == 2)) ? 0x0000 : C_WHITE;
  tft.fillRoundRect(200, 164, 114, 46, 5, bc);
  tft.setTextColor(btc, bc);
  tft.setTextSize(2);
  tft.setCursor(212, 170);
  if (!motor_on) tft.print("OFF");
  else if (warmup) tft.print("WARMUP");
  else tft.print(namePred(pred));
  tft.setTextSize(1);
  tft.setCursor(212, 194);
  if (warmup) {
    int rem = (int)((WARMUP_MS - (millis() - motor_on_since)) / 1000) + 1;
    tft.printf("Espere %ds", rem);
  } else {
    tft.printf("Conf: %.0f%%", conf*100.0f);
  }
}
void drawHist() {
  tft.fillRect(0, 24, 320, 192, C_BG);
  tft.setTextColor(C_DIM, C_BG); tft.setTextSize(1); tft.setCursor(4, 26); tft.print("Confianza (ultimas 50 predicciones)");
  int n = hist_count;
  for (int i = 0; i < n; i++) {
    PredRec& r = hist[(hist_idx - n + i + HIST_SIZE*2) % HIST_SIZE];
    int bx = 30 + i*5;
    int bh = (int)(r.conf*110);
    tft.drawFastVLine(bx, 150-bh, bh, colorPred(r.pred));
  }
  tft.drawLine(28, 150, 312, 150, C_BORDER);
  int cS=0, cL=0, cX=0; char ult[40] = "Sin fallas detectadas"; uint16_t ultC = C_GREEN;
  for (int i = 0; i < n; i++) {
    PredRec& r = hist[(hist_idx - n + i + HIST_SIZE*2) % HIST_SIZE];
    if (r.pred==0) cS++; else if (r.pred==1) cL++; else cX++;
    if (r.pred != 0) {
      snprintf(ult, sizeof(ult), "Ultima falla: %s conf %.0f%%", namePred(r.pred), r.conf*100);
      ultC = colorPred(r.pred);
    }
  }
  tft.setTextSize(1);
  tft.setTextColor(C_GREEN, C_BG); tft.setCursor(8, 164); tft.printf("SANO:%d", cS);
  tft.setTextColor(C_LEVE, C_BG);  tft.setCursor(80, 164); tft.printf("LEVE:%d", cL);
  tft.setTextColor(C_SEV, C_BG);   tft.setCursor(150, 164); tft.printf("SEV/INT:%d", cX);
  tft.setTextColor(ultC, C_BG);    tft.setCursor(8, 182); tft.print(ult);
  tft.setTextColor(C_DIM, C_BG);   tft.setCursor(8, 198);
  tft.print((cL+cX) > cS/3 ? "Tendencia: degradando" : "Tendencia: estable");
}
void drawCfg() {
  tft.fillRect(0, 24, 320, 192, C_BG);
  tft.setTextSize(2); tft.setTextColor(C_WHITE, C_BG);
  tft.setCursor(8, 34);  tft.printf("CUSUM K:%.2f H:%.2f", CUSUM_K, CUSUM_H);
  tft.setCursor(8, 58);  tft.printf("CUSUM Smax:%.1f", CUSUM_S_MAX);
  bool on = ssr[0]||ssr[1]||ssr[2];
  tft.setCursor(8, 88); tft.print("SSR Inyeccion:");
  tft.fillRoundRect(200, 84, 60, 22, 4, on ? C_SEV : C_PANEL);
  tft.setTextColor(on ? C_WHITE : C_GREEN, on ? C_SEV : C_PANEL); tft.setCursor(218, 88);
  tft.print(on ? "ON" : "OFF");
  tft.setTextSize(1); tft.setTextColor(C_DIM, C_BG);
  tft.setCursor(8, 112); tft.print("Watchdog: 12s  Cooldown: 2s  I>8A aborto");
  tft.setCursor(8, 126); tft.print(HABILITAR_WIFI ? "WiFi AP: ITF_Banco   IP: 192.168.4.1" : "WiFi: deshabilitado (ADC2 limpio)");
  tft.setCursor(8, 140); tft.print("FFT 4096 (HR-MCSA + Grandke f0)");
  tft.setTextColor(C_CYAN, C_BG);   tft.setCursor(8, 156); tft.printf("CAL_I: %.4f %.4f %.4f", CAL_I[0], CAL_I[1], CAL_I[2]);
  tft.setTextColor(C_ORANGE, C_BG); tft.setCursor(8, 168); tft.printf("CAL_V: %.4f %.4f %.4f", CAL_V[0], CAL_V[1], CAL_V[2]);
  tft.setTextColor(C_WHITE, C_BG);  tft.setCursor(8, 182); tft.print("Modelo: RF Plano 45x6 (Flash PROGMEM)");
}
void render() {
  drawHeader();
  if (view == 0) drawMon();
  else if (view == 1) drawFFTview();
  else if (view == 2) drawHist();
  else drawCfg();
  drawTabBar();
}

// ==================== WEB DASHBOARD ====================
void handleRoot() {
  String h = R"rawliteral(
<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Banco ITF - Dashboard 3F</title><style>
body{font-family:Arial;background:#1e2a35;color:#e6edf3;margin:0;padding:16px}
h1{color:#A8C5DA;border-bottom:2px solid #A8C5DA;padding-bottom:6px;font-size:22px}
#banner{padding:8px;border-radius:6px;text-align:center;font-weight:bold;margin:10px 0;background:#243447}
.cards{display:flex;flex-wrap:wrap;gap:10px}
.card{background:#243447;border-radius:8px;padding:10px 14px;flex:1;min-width:90px;text-align:center}
.card b{font-size:20px;color:#E8B86D;display:block}.card span{font-size:10px;color:#8fa3b5}
.panel{background:#243447;border-radius:8px;padding:10px;margin:12px 0}
button{padding:12px 18px;margin:4px;border:none;border-radius:6px;cursor:pointer;color:#fff;font-size:14px}
.b1{background:#E8B86D;color:#000}.b2{background:#7BA098}.b3{background:#A8C5DA;color:#000}.b4{background:#b48ead}
canvas{width:100%;background:#0d141b;border-radius:6px}
#log{background:#101820;font-family:monospace;font-size:11px;padding:8px;height:110px;overflow:auto;border-radius:6px}
.sel{background:#243447;border:1px solid #A8C5DA;color:#e6edf3;padding:6px}
table{font-size:12px;border-collapse:collapse}td{padding:2px 8px}
.lg{display:inline-block;margin-right:18px;font-size:13px;font-weight:bold}
.lg i{display:inline-block;width:22px;height:4px;border-radius:2px;vertical-align:middle;margin-right:6px}
</style></head><body>
<h1>Banco ITF - Dashboard 3F</h1>
<div id="banner">SISTEMA SANO</div>
<div class="cards">
<div class="card"><b id="va">--</b><span>V_A (V)</span></div><div class="card"><b id="vb">--</b><span>V_B (V)</span></div>
<div class="card"><b id="vc">--</b><span>V_C (V)</span></div><div class="card"><b id="ia">--</b><span>I_A (A)</span></div>
<div class="card"><b id="ib">--</b><span>I_B (A)</span></div><div class="card"><b id="ic">--</b><span>I_C (A)</span></div>
<div class="card"><b id="ssr">--</b><span>SSR</span></div><div class="card"><b id="ton">0</b><span>T_ON (ms)</span></div>
<div class="card"><b id="act">0</b><span>ACTIVACIONES</span></div></div>
<div class="panel"><b>OSCILOSCOPIO (fase:</b><select class="sel" id="ph" onchange="updLegend();fetchScope()"><option value="0">A</option><option value="1">B</option><option value="2" selected>C</option></select><b>)</b>
<div style="margin:8px 0 4px 0">
<span class="lg" style="color:#E8B86D"><i style="background:#E8B86D"></i>CH1 · VOLTAJE <span id="lgV">V_C</span></span>
<span class="lg" style="color:#7fd4ff"><i style="background:#7fd4ff"></i>CH2 · CORRIENTE <span id="lgI">I_C</span></span>
<span style="color:#8fa3b5;font-size:11px">· cada traza se auto-escala a su propio pico ·</span>
</div>
<canvas id="wave" height="260"></canvas></div>
<div class="panel"><b>Espectro I_C (0-100 Hz) + Diagnóstico:</b> <span id="diag"></span><canvas id="spec" height="140"></canvas>
<table id="feat"></table></div>
<div class="panel">
<button class="b1" onclick="cmd('/on?n=1')">ACTIVAR LEVE (F1)</button>
<button class="b1" onclick="cmd('/on?n=2')">INTERMEDIA (F2)</button>
<button class="b1" onclick="cmd('/on?n=3')">SEVERA (F3)</button>
<button class="b2" onclick="cmd('/off')">DESACTIVAR</button>
<button class="b3" onclick="cmd('/test')">TEST AUTO</button>
<button class="b4" onclick="cmd('/acquire')">ACQUIRE</button>
<b style="margin-left:12px">TFT:</b>
<button class="b3" onclick="cmd('/view?n=0')">Mon</button><button class="b3" onclick="cmd('/view?n=1')">FFT</button>
<button class="b3" onclick="cmd('/view?n=2')">Hist</button><button class="b3" onclick="cmd('/view?n=3')">Cfg</button></div>
<div class="panel"><b>LOG:</b><div id="log"></div></div>
<script>
let logs=[];
const SCOPE_N=200;
function cmd(u){fetch(u).then(r=>r.text()).then(t=>{logs.push(t);drawLog();poll();}).catch(e=>{logs.push("ERR: "+e);drawLog();});}
function drawLog(){document.getElementById('log').innerHTML=logs.slice(-10).join('<br>');}
function updLegend(){
 const L='ABC'[+document.getElementById('ph').value];
 document.getElementById('lgV').textContent='V_'+L+' (traza ambar, eje propio)';
 document.getElementById('lgI').textContent='I_'+L+' (traza azul, eje propio)';
}
function fetchScope(){fetch('/wave?ph='+document.getElementById('ph').value).then(r=>r.json()).then(drawScope).catch(e=>{});}
function drawScope(d){
 const cv=document.getElementById('wave'),cx=cv.getContext('2d');
 if(cv.width!==cv.clientWidth)cv.width=cv.clientWidth;
 const W=cv.width,H=cv.height;cx.clearRect(0,0,W,H);
 const V=d.v,I=d.i,N=V.length;
 let mv=0,mi=0;for(let k=0;k<N;k++){mv+=V[k];mi+=I[k];}mv/=N;mi/=N;
 let t0=0;for(let k=1;k<N-SCOPE_N;k++){if(V[k-1]<mv&&V[k]>=mv){t0=k;break;}}
 let vmax=10,imax=10;
 for(let k=0;k<SCOPE_N;k++){const a=Math.abs(V[t0+k]-mv);if(a>vmax)vmax=a;const b=Math.abs(I[t0+k]-mi);if(b>imax)imax=b;}
 cx.lineWidth=1;cx.strokeStyle='#1c2a36';
 for(let g=1;g<10;g++){cx.beginPath();cx.moveTo(g*W/10,0);cx.lineTo(g*W/10,H);cx.stroke();}
 for(let g=1;g<8;g++){cx.beginPath();cx.moveTo(0,g*H/8);cx.lineTo(W,g*H/8);cx.stroke();}
 cx.strokeStyle='#39424e';cx.setLineDash([4,4]);cx.beginPath();cx.moveTo(0,H/2);cx.lineTo(W,H/2);cx.stroke();cx.setLineDash([]);
 function trace(arr,mean,scale,color){
  cx.strokeStyle=color;cx.lineWidth=2;cx.shadowColor=color;cx.shadowBlur=8;cx.beginPath();
  let px=0,py=H/2;
  for(let k=0;k<SCOPE_N;k++){
   const x=k*W/SCOPE_N, y=H/2-(arr[t0+k]-mean)/scale*(H/2-16);
   if(k==0){cx.moveTo(x,y);}else{cx.quadraticCurveTo(px,py,(px+x)/2,(py+y)/2);}
   px=x;py=y;
  }
  cx.lineTo(px,py);cx.stroke();cx.shadowBlur=0;cx.lineWidth=1;
 }
 trace(V,mv,vmax,'#E8B86D');
 trace(I,mi,imax,'#7fd4ff');
 cx.shadowBlur=0;cx.font='bold 12px Arial';
 cx.fillStyle='#E8B86D';cx.fillRect(8,8,14,4);cx.fillText('VOLTAJE (V)',28,14);
 cx.fillStyle='#7fd4ff';cx.fillRect(8,24,14,4);cx.fillText('CORRIENTE (I)',28,30);
 cx.fillStyle='#52e07a';cx.beginPath();cx.moveTo(0,H/2-7);cx.lineTo(7,H/2);cx.lineTo(0,H/2+7);cx.fill();
 cx.fillStyle='#8fa3b5';cx.font='11px Arial';
 cx.fillText('83 ms (5 ciclos @60Hz) | trig: flanco asc. V | linea punteada = cero',8,H-8);
}
setInterval(fetchScope,1000);
function poll(){fetch('/status').then(r=>r.json()).then(d=>{
 document.getElementById('va').textContent=d.va.toFixed(1);document.getElementById('vb').textContent=d.vb.toFixed(1);
 document.getElementById('vc').textContent=d.vc.toFixed(1);document.getElementById('ia').textContent=d.ia.toFixed(2);
 document.getElementById('ib').textContent=d.ib.toFixed(2);document.getElementById('ic').textContent=d.ic.toFixed(2);
 document.getElementById('ssr').textContent=d.ssr;document.getElementById('ton').textContent=d.ton;
 document.getElementById('act').textContent=d.act;
 let bn=document.getElementById('banner');
 if(d.va<1&&d.vb<1&&d.vc<1){bn.textContent='MOTOR APAGADO / SIN SEÑAL';bn.style.background='#444c56';}
 else{bn.textContent='ESTADO: '+d.pred+' | Conf '+(d.conf*100).toFixed(1)+'%';
 bn.style.background=(d.pred=='SANO')?'#2e5d43':(d.pred=='LEVE')?'#8a7a2a':(d.pred=='SEVERA')?'#a05252':'#7a5a2a';}
 document.getElementById('diag').innerHTML=' <b style="color:#E8B86D">'+d.pred+'</b> conf '+(d.conf*100).toFixed(1)+'%';
 document.getElementById('feat').innerHTML='<tr><td>A55</td><td>'+d.f55.toFixed(1)+'</td><td>A65</td><td>'+d.f65.toFixed(1)+'</td><td>THD</td><td>'+d.thd.toFixed(3)+'</td><td>I_neg</td><td>'+d.ineg.toFixed(3)+'</td><td>I_fast</td><td>'+d.ifast.toFixed(2)+'A</td></tr>';
 logs=d.log;drawLog();drawSpec(d);});}
let fftSm=null, specMax=0;
function drawSpec(d){let cv=document.getElementById('spec'),cx=cv.getContext('2d');if(cv.width!==cv.clientWidth)cv.width=cv.clientWidth;let W=cv.width,H=140;cx.clearRect(0,0,W,H);
 if(!fftSm||fftSm.length!==d.fft.length){fftSm=d.fft.slice();}
 else{for(let i=0;i<d.fft.length;i++){fftSm[i]=0.7*fftSm[i]+0.3*d.fft[i];}}
 let mx=Math.max(...fftSm); specMax=specMax?0.8*specMax+0.2*mx:mx;
 for(let i=0;i<fftSm.length;i++){let h=Math.sqrt(fftSm[i]/specMax)*(H-20);let x=i*W/fftSm.length;
 cx.strokeStyle=(Math.abs(i-165)<6||Math.abs(i-195)<6)?'#e05252':(Math.abs(i-180)<6)?'#52e07a':'#2f81f7';
 cx.beginPath();cx.moveTo(x,H-15);cx.lineTo(x,H-15-h);cx.stroke();}
 cx.fillStyle='#8fa3b5';cx.font='10px Arial';for(let f=0;f<=100;f+=20)cx.fillText(f,f*W/100-4,H-4);
 cx.font='bold 11px Arial';cx.fillStyle='#52e07a';cx.fillText('verde = fundamental 60 Hz',W-190,14);
 cx.fillStyle='#e05252';cx.fillText('rojo = sidebands 55/65 Hz',W-190,28);}
poll();setInterval(poll,1000);updLegend();fetchScope();</script></body></html>)rawliteral";
  server.send(200, "text/html", h);
}

void handleStatus() {
  String j = "{";
  j += "\"va\":" + String(rms[0],1);
  j += ",\"vb\":" + String(rms[1],1);
  j += ",\"vc\":" + String(rms[2],1);
  j += ",\"ia\":" + String(rms[3],2);
  j += ",\"ib\":" + String(rms[4],2);
  j += ",\"ic\":" + String(rms[5],2);
  j += ",\"ifast\":" + String(I_fast,2);
  j += ",\"ssr\":\"";
  if (ssr[0]) j += "F1 ";
  if (ssr[1]) j += "F2 ";
  if (ssr[2]) j += "F3 ";
  if (!ssr[0] && !ssr[1] && !ssr[2]) j += "OFF";
  j += "\"";
  j += ",\"ton\":" + String((ssr[0]||ssr[1]||ssr[2]) ? millis()-t_on_ini : t_on_ms);
  j += ",\"act\":" + String(act_count);
  j += ",\"pred\":\"" + String(namePred(pred)) + "\"";
  j += ",\"clase\":" + String(pred);
  j += ",\"conf\":" + String(conf,3);
  j += ",\"modelo\":\"RF\"";
  j += ",\"f55\":" + String(A_55,1);
  j += ",\"f65\":" + String(A_65,1);
  j += ",\"f50\":" + String(A_50,1);
  j += ",\"f70\":" + String(A_70,1);
  j += ",\"ffund\":" + String(A_fund,1);
  j += ",\"thd\":" + String(THD,4);
  j += ",\"ineg\":" + String(I_neg,4);
  j += ",\"fase_critica\":\"" + String((char)('A' + fase_critica)) + "\"";
  j += ",\"p_rf\":"    + String(prob_rf_raw,4);
  j += ",\"p_e2\":"    + String(prob_e2,4);
  j += ",\"e2\":"      + String(sec_res.e_2 * 100.0f,3);
  j += ",\"u2v\":"     + String(sec_res.u_V * 100.0f,3);
  j += ",\"u2i\":"     + String(sec_res.u_I * 100.0f,3);
  j += ",\"dom\":"     + String(sec_res.dom);
  j += ",\"base_e2\":" + String(base_e2,3);
  j += ",\"delta_e2\":"+ String(delta_e2,3);
  j += ",\"dv2\":"     + String(dv2_pct,3);
  j += ",\"ang_de2\":" + String(ang_de2,1);
  j += ",\"cusum_s\":" + String(det_state.S,2);
  j += ",\"p_cal\":"   + String(det_state.p_cal,4);
  j += ",\"hr_l2sm\":" + String(mcsa_hr_res.L_2sm,2);
  j += ",\"hr_l2sp\":" + String(mcsa_hr_res.L_2sp,2);
  j += ",\"hr_lrm\":"  + String(mcsa_hr_res.L_rm,2);
  j += ",\"hr_lrp\":"  + String(mcsa_hr_res.L_rp,2);
  j += ",\"hr_l3\":"   + String(mcsa_hr_res.L_3,2);
  j += ",\"hr_l3rm\":" + String(mcsa_hr_res.L_3rm,2);
  j += ",\"hr_l3rp\":" + String(mcsa_hr_res.L_3rp,2);
  j += ",\"hr_snr2s\":"+ String(mcsa_hr_res.SNR_2s,2);
  j += ",\"hr_s\":"    + String(mcsa_hr_res.s,4);
  j += ",\"hr_sok\":"  + String(mcsa_hr_res.slip_ok);
  j += ",\"hr_f0\":"   + String(mcsa_hr_res.f0,3);
  j += ",\"hr_us\":"   + String((int)hr_calc_time_us);
  j += ",\"fft\":[";
  for (int i = 0; i < 300; i++) { if (i) j += ","; j += String(fft_disp[i]); }
  j += "],\"log\":[";
  for (int i = 0; i < 8; i++) {
    String s = logBuf[(logIdx+i)%8];
    if (s.length()) { s.replace("\"", "'"); j += "\"" + s + "\","; }
  }
  if (j.charAt(j.length()-1) == ',') j.remove(j.length()-1);
  j += "]}";
  server.send(200, "application/json", j);
}
void handleWave() {
  int ph = server.hasArg("ph") ? server.arg("ph").toInt() : 2;
  if (ph < 0 || ph > 2) ph = 2;
  int chV = CH_VA + ph, chI = CH_IA + ph;
  String j = "{\"v\":[";
  for (int i = 0; i < WBUF_N; i++) { if (i) j += ","; j += String(wbuf[chV][(wbidx+i)%WBUF_N]); }
  j += "],\"i\":[";
  for (int i = 0; i < WBUF_N; i++) { if (i) j += ","; j += String(wbuf[chI][(wbidx+i)%WBUF_N]); }
  j += "]}";
  server.send(200, "application/json", j);
}
void handleOn()  { 
  int n = server.hasArg("n") ? server.arg("n").toInt() : 1; 
  if (n < 1 || n > 3) { server.send(400, "text/plain", "ERR: n invalido"); return; }
  bool ok = ssrOn(n - 1); 
  if (ok) {
    server.send(200, "text/plain", "OK: F" + String(n) + " ACTIVADO");
  } else {
    server.send(429, "text/plain", "RECHAZADO: Cooldown o proteccion activa");
  }
}
void handleOff() { ssrOff(false); server.send(200, "text/plain", "OK: SSR DESACTIVADO"); }
void handleView(){ view = server.arg("n").toInt() & 3; server.send(200, "text/plain", "OK vista"); }
void handleTest(){
  float b65 = A_65;
  ssrOn(0); uint32_t t0 = millis();
  while (millis()-t0 < 700) { server.handleClient(); delay(10); }
  calcFeatures(); float l65 = A_65;
  ssrOff(false);
  char b[64]; snprintf(b, sizeof(b), "TEST: A65 SANO=%.1f LEVE=%.1f ratio=%.2f %s", b65, l65, l65/(b65>0?b65:1), (l65 > b65*1.15f) ? "PASS" : "FAIL");
  addLog(b);
  server.send(200, "text/plain", b);
}
void handleAcquire() {
  int ph = server.hasArg("ph") ? server.arg("ph").toInt() : 2;
  if (ph < 0 || ph > 2) ph = 2;
  int chV = CH_VA + ph, chI = CH_IA + ph;
  String j = "{\"v_raw\":[";
  j.reserve(52000);
  uint8_t rb = ready_bank;
  for (int i = 0; i < NBIG; i++) { if (i) j += ","; j += String(samp_buf[rb][chV][i]); }
  j += "],\"i_raw\":[";
  for (int i = 0; i < NBIG; i++) { if (i) j += ","; j += String(samp_buf[rb][chI][i]); }
  j += "],\"offset_V\":" + String((int)offDyn[chV]) + ",\"offset_I\":" + String((int)offDyn[chI]);
  j += ",\"CAL_V\":" + String(CAL_V[ph],4) + ",\"CAL_I\":" + String(CAL_I[ph],5) + "}";
  server.send(200, "application/json", j);
  addLog("ACQUIRE servido (4096@2400Hz)");
}
void printSpectrum() {
  const char* pNames[3] = {"FASE A (Pin A1)", "FASE B (Pin A0)", "FASE C (Pin A2)"};
  Serial.println("\n================ BARRIDO FFT MULTIFASE (A, B, C) ================");
  for (int p = 0; p < 3; p++) {
    float a_ref = (A_fund_ph[p] > 0.001f) ? A_fund_ph[p] : 1.0f;
    float r55 = A_55_ph[p] / a_ref;
    float r65 = A_65_ph[p] / a_ref;
    Serial.printf("  [%s] Irms=%.2fA | Afund=%.1f | A55=%.1f(%.1fHz)[r55=%.3f] | A65=%.1f(%.1fHz)[r65=%.3f]%s\n",
                  pNames[p], rms[CH_IA + p], A_fund_ph[p], A_55_ph[p], f55p_ph[p], r55, A_65_ph[p], f65p_ph[p], r65,
                  (p == fase_critica) ? "  <-- FASE CRITICA" : "");
  }
  Serial.printf(">>> Fase Critica: FASE %c | P(LEVE)=%.1f%% | Diagnostico IA: %s\n",
                (char)('A' + fase_critica), ultima_prob_leve * 100.0f, namePred(pred));
  Serial.println("-----------------------------------------------------------------");
  Serial.printf("========== ESPECTRO DETALLADO FASE %c (50 Hz - 70 Hz) ==========\n", (char)('A' + fase_critica));
  Serial.printf("Fundamental: A_fund = %.1f (f0 = 60.0 Hz)\n", A_fund);
  Serial.printf("Picos: f55p = %.1f Hz (A55 = %.1f) | f65p = %.1f Hz (A65 = %.1f)\n", f55p, A_55, f65p, A_65);
  Serial.println(" Freq (Hz) | Amplitud | Grafica");
  Serial.println("-----------+----------+-----------------------------------");
  for (float f = 50.0f; f <= 70.0f; f += 1.0f) {
    float a = peakWin(f - 0.5f, f + 0.5f);
    int bar = (int)(a / 5.0f);
    if (bar > 35) bar = 35;
    char b[36];
    for (int k = 0; k < bar; k++) b[k] = '#';
    b[bar] = '\0';
    Serial.printf("  %4.1f Hz | %8.1f | %s\n", f, a, b);
  }
  Serial.println("=================================================================\n");
}
void handleTestSerial() {
  float b65 = A_65; ssrOn(0); delay(700); calcFeatures(); float l65 = A_65; ssrOff(false);
  char b[64]; snprintf(b, sizeof(b), "TEST: ratio=%.2f %s", l65/(b65>0?b65:1), (l65>b65*1.15f)?"PASS":"FAIL");
  addLog(b);
}


// ==================== DIAGNÓSTICO DE LA PANTALLA (comando 'D') ====================
// Lee registros del ILI9341 por SPI (requiere SDO/MISO conectado). Valores esperados tras tft.begin()
// con setRotation(1): modo 0x94, MADCTL 0x28, formato de pixel 0x05, autodiagnóstico 0xC0, ID 00 93 41.
void diagnosticoTFT() {
  tft.begin(4000000);  // el ILI9341 solo admite lectura serie a ~6.6 MHz
  tft.setRotation(1);
  uint8_t pm = tft.readcommand8(ILI9341_RDMODE);
  uint8_t md = tft.readcommand8(ILI9341_RDMADCTL);
  uint8_t pf = tft.readcommand8(ILI9341_RDPIXFMT);
  uint8_t sd = tft.readcommand8(ILI9341_RDSELFDIAG);
  uint8_t id1 = tft.readcommand8(0xD3, 1), id2 = tft.readcommand8(0xD3, 2), id3 = tft.readcommand8(0xD3, 3);
  Serial.printf("[TFT] RDMODE=0x%02X RDMADCTL=0x%02X RDPIXFMT=0x%02X RDSELFDIAG=0x%02X ID4=%02X %02X %02X\n", pm, md, pf, sd, id1, id2, id3);
  // Prueba del cable RESET: tras un reset por hardware el modo vuelve a 0x08 (sleep in, display off)
  digitalWrite(TFT_RST, LOW); delay(20); digitalWrite(TFT_RST, HIGH); delay(150);
  uint8_t pm_rst = tft.readcommand8(ILI9341_RDMODE);
  Serial.printf("[TFT] RDMODE tras pulso en RESET=0x%02X\n", pm_rst);
  tft.begin(); tft.setRotation(1); tft.fillScreen(C_BG); render();
}

// ==================== SETUP / LOOP ====================
void setup() {
  Serial.begin(115200);
  uint32_t t_ser = millis();
  while (!Serial && (millis() - t_ser < 2500)) { delay(10); }
  delay(300);
  Serial.println("\n=== MotorGuard ITF FASE 3.25 + IA (pipeline 3.18) ===");
  Serial.println("[COMANDOS SERIAL]");
  Serial.println("  '1' -> Inyectar Falla F1 (LEVE)");
  Serial.println("  '0' -> Apagar SSR");
  Serial.println("  'k' -> Iniciar comisionamiento (Y2 e I2_0 motor sano -> Flash NVS)");
  Serial.println("  'K' -> Borrar comisionamiento de Flash NVS");
  Serial.println("  'f' -> Ver Espectro FFT detallado (50 a 70 Hz)");
  Serial.println("  'p' -> Alternar Polaridad F1 (ACTIVE-HIGH <-> ACTIVE-LOW)");
  Serial.println("  'h' -> Forzar GPIO 8 a HIGH (3.3V) [Test Relevador]");
  Serial.println("  'l' -> Forzar GPIO 8 a LOW (0V) [Test Relevador]");
  mcsa_hr_set_work_buffers(fft_re, fft_im);
  mcsa_hr_init(&mcsa_hr_state);
  detector_init(&det_state); dir_init(&det_dir);

  // Restaurar comisionamiento persistente de Flash NVS si existe
  float cond_guardada = 1.0f;
  if (cargarComisionamientoNVS(&Y2_comisionada, &I2_0_comisionada, &cond_guardada)) {
    com_state.M = COM_BLOQUES_REQ;
    char b[48]; snprintf(b, sizeof(b), "NVS: Calibrado Cond=%.1f", cond_guardada);
    addLog(b);
  } else {
    // Si no hay NVS previo, usar valores nominales iniciales del banco al 75%
    Y2_comisionada = {0.0f, 0.0f};
    I2_0_comisionada = {0.2304f, 0.4952f};
    com_state.M = COM_BLOQUES_REQ;
    addLog("Comisionado: Nominal banco");
  }
  // Inicializacion segura de relevadores segun su polaridad
  for (int i = 0; i < 3; i++) {
    uint8_t pin = (i == 0) ? SSR_F1 : (i == 1) ? SSR_F2 : SSR_F3;
    gpio_num_t gpio = (gpio_num_t)((i == 0) ? 8 : (i == 1) ? 7 : 9);
    pinMode(pin, OUTPUT);
    digitalWrite(pin, relayInactiveLevel(i));
    gpio_set_direction(gpio, GPIO_MODE_OUTPUT);
    gpio_set_level(gpio, relayInactiveLevel(i));
    gpio_set_drive_capability(gpio, GPIO_DRIVE_CAP_3);
  }
  analogReadResolution(12); analogSetAttenuation(ADC_11db);
  for (int c = 0; c < 6; c++) {
    long s = 0; for (int i = 0; i < 128; i++) s += analogRead(APIN[c]);
    offset[c] = s/128.0f; offDyn[c] = offset[c];
  }
  for (int i = 0; i < NBLK; i++) hann[i] = 0.5f - 0.5f*cosf(2.0f*3.14159265f*i/(NBLK-1));

  SPI.begin(TFT_SCLK, TFT_MISO, TFT_MOSI, TFT_CS);
  tft.begin(); tft.setRotation(1); tft.fillScreen(C_BG);

#if HABILITAR_WIFI
  WiFi.mode(WIFI_AP); WiFi.softAP("ITF_Banco", "CAMBIAR_CLAVE");
  server.on("/", handleRoot); server.on("/status", handleStatus);
  server.on("/wave", handleWave);
  server.on("/on", handleOn); server.on("/off", handleOff);
  server.on("/view", handleView); server.on("/test", handleTest);
  server.on("/acquire", handleAcquire);
  server.begin();
#else
  WiFi.mode(WIFI_OFF);
#endif
  addLog("MotorGuard v3.25 + IA listo");
#if HABILITAR_WIFI
  char b[32]; snprintf(b, sizeof(b), "IP: %s", WiFi.softAPIP().toString().c_str()); addLog(b);
#else
  addLog("WiFi deshabilitado (ADC2 limpio)");
#endif

  xTaskCreatePinnedToCore(taskMuestreo, "samp", 4096, NULL, 5, &sampTask, 1);
  esp_timer_create_args_t args = { .callback = sampTimerCb, .arg = NULL, .dispatch_method = ESP_TIMER_TASK, .name = "samp" };
  esp_timer_create(&args, &sampTimer);
  esp_timer_start_periodic(sampTimer, 416);
  render();
}

void loop() {
#if HABILITAR_WIFI
  server.handleClient();
#endif
  static uint32_t lastFast = 0;
  if (millis()-lastFast >= 100) {
    lastFast = millis();
    double s = 0;
    uint8_t cur_b = active_bank;
    uint16_t cur_w = widx;
    for (int i = 0; i < 256; i++) {
      uint16_t idx = (cur_w + NBIG - 256 + i) % NBIG;
      float d = (float)samp_buf[cur_b][CH_IC][idx] - offDyn[CH_IC];
      s += (double)d*d;
    }
    I_fast = sqrtf((float)(s/256.0)) * CAL_I[2];
    if (!motor_on || I_fast < 0.30f) I_fast = 0.0f;
  }
  static uint8_t ovCnt = 0;
  if (ssr[0]||ssr[1]||ssr[2]) {
    uint32_t ton = millis()-t_on_ini;
    if (ton >= T_MAX_ON) ssrOff(true);
    else if (ton > INRUSH_BLANK_MS && I_fast > I_UMBRAL) { if (++ovCnt >= 3) { ovCnt = 0; ssrOff(true); } }
    else ovCnt = 0;
  } else ovCnt = 0;
  // Ejecutar DSP e inferencia ÚNICAMENTE cuando un bloque completo de 4096 muestras está listo
  if (new_bank_ready) {
    new_bank_ready = false;
    calcFeatures(); 
    clasificar();
    Serial.printf("[MCSA] Motor:%s | FallaMax:Fase %c | VA=%.1fV VB=%.1fV VC=%.1fV | IA=%.2fA IB=%.2fA IC=%.2fA | Afund=%.1f A55=%.1f(%.1fHz) A65=%.1f(%.1fHz) | P_RF=%.1f%% P_E2=%.1f%% | %s | SSR:%s | U2V=%.2f%% U2I=%.2f%% E2=%.2f%% DOM=%d | HR: L2sM=%.2f L2sP=%.2f LrM=%.2f LrP=%.2f L3=%.2f L3rM=%.2f L3rP=%.2f SNR2s=%.2f s=%.4f SOK=%d f0=%.3f | CUSUM: S=%.2f Pcal=%.1f%% | DE2=%.2f%% dV2=%.2f%% ANG=%.1f | RAW: R2=%.5f,%.5f I1=%.4f V2=%.4f,%.4f V1=%.3f | DIR: P=%.3f R=%d C=%d REF=%d CUSUM=%d SEV=%d ML=%.3f PL=%.3f\n",
                  motor_on ? (pred == -1 ? "WARMUP" : "ON") : "OFF",
                  (char)('A' + fase_critica),
                  rms[CH_VA], rms[CH_VB], rms[CH_VC], rms[CH_IA], rms[CH_IB], rms[CH_IC],
                  A_fund, A_55, f55p, A_65, f65p, 
                  (pred == -1 ? 0.0f : prob_rf_raw * 100.0f), 
                  (pred == -1 ? 0.0f : prob_e2 * 100.0f),
                  namePred(pred), 
                  (ssr[0] ? "F1(LEVE)" : (ssr[1] ? "F2(INTER)" : (ssr[2] ? "F3(SEV)" : "OFF"))),
                  sec_res.u_V * 100.0f,
                  sec_res.u_I * 100.0f,
                  sec_res.e_2 * 100.0f,
                  sec_res.dom,
                  mcsa_hr_res.L_2sm,
                  mcsa_hr_res.L_2sp,
                  mcsa_hr_res.L_rm,
                  mcsa_hr_res.L_rp,
                  mcsa_hr_res.L_3,
                  mcsa_hr_res.L_3rm,
                  mcsa_hr_res.L_3rp,
                  mcsa_hr_res.SNR_2s,
                  mcsa_hr_res.s,
                  mcsa_hr_res.slip_ok,
                  mcsa_hr_res.f0,
                  det_state.S,
                  det_state.p_cal * 100.0f,
                  delta_e2, dv2_pct, ang_de2,
                  // Fasores crudos (pico, A/V, referidos a arg(V1)) para re-simulacion offline exacta
                  sec_res.R2.re, sec_res.R2.im,
                  sqrtf(sec_res.I1.re * sec_res.I1.re + sec_res.I1.im * sec_res.I1.im),
                  sec_res.V2.re, sec_res.V2.im,
                  sqrtf(sec_res.V1.re * sec_res.V1.re + sec_res.V1.im * sec_res.V1.im),
                  det_dir.proy, det_dir.racha, det_dir.confirmada, det_dir.ref_ok, pred_cusum,
                  det_dir.sev, det_dir.mag_lat, det_dir.proy_lat);
  }

  // Refrescar pantalla TFT a cadencia fija de interfaz
  static uint32_t lastRender = 0;
  if (millis() - lastRender >= UI_MS) {
    lastRender = millis();
    render();
  }
  if (Serial.available()) {
    char c = Serial.read();
    if (c=='1') ssrOn(0); else if (c=='2') ssrOn(1); else if (c=='3') ssrOn(2);
    else if (c=='0') ssrOff(false); else if (c=='t') handleTestSerial();
    else if (c=='k') {
      if (!motor_on) {
        Serial.println("[COMISIONAMIENTO] Error: el motor debe estar encendido");
      } else if (ssr[0] || ssr[1] || ssr[2]) {
        Serial.println("[COMISIONAMIENTO] Error: los SSR deben estar apagados");
      } else {
        comisionamiento_reset(&com_state);
        comisionando = true;
        base55 = 0.0f; base65 = 0.0f;
        Serial.println("[COMISIONAMIENTO] Iniciado: acumulando 30 bloques de motor sano...");
        addLog("Comisionamiento INICIADO");
      }
    }
    else if (c=='K') {
      borrarComisionamientoNVS();
      Y2_comisionada = {0.0f, 0.0f};
      I2_0_comisionada = {0.0f, 0.0f};
      com_state.M = 0;
      detector_init(&det_state); dir_init(&det_dir);
      pred = 0;
      Serial.println(">>> [COMISIONAMIENTO] Calibracion NVS borrada y reiniciada a cero.");
    }
    else if (c=='n') {
      ComplexFloat y2_nom = {0.0f, 0.0f};
      ComplexFloat i20_nom = {0.2304f, 0.4952f};
      guardarComisionamientoNVS(y2_nom, i20_nom, 1.0f);
      Y2_comisionada = y2_nom;
      I2_0_comisionada = i20_nom;
      com_state.M = COM_BLOQUES_REQ;
      Serial.println(">>> [NVS FLASH] Calibracion nominal de 75% guardada en Flash NVS.");
    }
    else if (c=='b') {
      Serial.println(">>> [RESTART] Reiniciando ESP32 por comando serial...");
      delay(150);
      ESP.restart();
    }
    else if (c=='D') diagnosticoTFT();
    else if (c=='W') {
      // Volcado crudo del último bloque completo (cuentas ADC) de IA, IB e IC: diagnóstico de forma de onda
      uint8_t rbw = ready_bank;
      Serial.println("[WAVE] begin n=2048 canales=IA,IB,IC");
      for (int i = 0; i < 2048; i++) {
        Serial.printf("%d,%d,%d\n", samp_buf[rbw][CH_IA][i], samp_buf[rbw][CH_IB][i], samp_buf[rbw][CH_IC][i]);
      }
      Serial.println("[WAVE] end");
    }
    else if (c=='P') {
      Serial.printf("[FASES] I-V angulo A=%.1f B=%.1f C=%.1f grados | Ipico A=%.2f B=%.2f C=%.2f | U2I=%.1f%%\n",
                    sec_res.ang_iv[0], sec_res.ang_iv[1], sec_res.ang_iv[2],
                    sec_res.mag_i[0], sec_res.mag_i[1], sec_res.mag_i[2], sec_res.u_I * 100.0f);
    }
    else if (c=='f' || c=='m') printSpectrum();
    else if (c=='s' || c=='j') {
      Serial.printf("{\"vc\":%.1f,\"ic\":%.2f,\"f55\":%.1f,\"f65\":%.1f,\"f50\":%.1f,\"f70\":%.1f,\"ffund\":%.1f,\"ineg\":%.4f,\"thd\":%.4f,\"motor\":%d,\"ssr\":\"%s\"}\n",
                    rms[CH_VC], rms[CH_IC], A_55, A_65, A_50, A_70, A_fund, I_neg, THD,
                    motor_on ? 1 : 0,
                    (ssr[0] ? "F1" : (ssr[1] ? "F2" : (ssr[2] ? "F3" : "OFF"))));
    }
    else if (c=='p') {
      f1_active_low = !f1_active_low;
      digitalWrite(SSR_F1, relayInactiveLevel(0));
      gpio_set_level((gpio_num_t)8, relayInactiveLevel(0));
      Serial.printf("\n>>> [POLARIDAD F1] Cambiada a: %s\n", f1_active_low ? "ACTIVE-LOW (0V activa bobina)" : "ACTIVE-HIGH (3.3V activa bobina)");
      Serial.printf(">>> Reposo(OFF) = GPIO 8 en %s (%dV) | Disparo(ON) = GPIO 8 en %s (%dV)\n",
                    relayInactiveLevel(0) ? "HIGH" : "LOW", relayInactiveLevel(0) ? 3 : 0,
                    relayActiveLevel(0) ? "HIGH" : "LOW", relayActiveLevel(0) ? 3 : 0);
    }
    else if (c=='h') {
      Serial.println("\n>>> [TEST MANUAL] GPIO 8 puesto en HIGH (3.3V). ¿Se escucho CLICK y encendio el LED del relay?");
      digitalWrite(SSR_F1, HIGH);
      gpio_set_level((gpio_num_t)8, 1);
      ssr[0] = (relayActiveLevel(0) == HIGH);
      if (ssr[0]) t_on_ini = millis();
    }
    else if (c=='l') {
      Serial.println("\n>>> [TEST MANUAL] GPIO 8 puesto en LOW (0V). ¿Se escucho CLICK y encendio el LED del relay?");
      digitalWrite(SSR_F1, LOW);
      gpio_set_level((gpio_num_t)8, 0);
      ssr[0] = (relayActiveLevel(0) == LOW);
      if (ssr[0]) t_on_ini = millis();
      else ssrOff(false);
    }
    else if (c=='r') {
      detector_init(&det_state); dir_init(&det_dir);
      pred = 0;
      base55 = 0.0f; base65 = 0.0f;
      resetBaseResiduo();
      e2_max_falla = 0.0f;
      drenando_retorno = false;
      Serial.println("\n>>> [CUSUM RESET] Acumulador CUSUM reiniciado a S=0.00. Pantalla en SANO.");
    }
    else if (c>='a'&&c<='d') view = c-'a';
  }
}