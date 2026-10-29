# PROTOCOLO DE VALIDACIÓN FÍSICA E INSTRUMENTACIÓN EN LABORATORIO
## Proyecto MotorGuard-ITF (Revisión Experimental Previa a Ensayos)

**Documento:** Protocolo Técnico de Verificación Instrumental  
**Destinatario:** Responsable del Laboratorio de Máquinas Eléctricas / Sínodo Evaluador  
**Fecha:** 26 de Septiembre de 2026  
**Carácter:** **PROCEDIMIENTO PENDIENTE DE EJECUCIÓN HUMANA (NO EJECUTAR DE FORMA AUTOMATIZADA)**  
**Objetivo:** Establecer los pasos metrológicos obligatorios para verificar el estado electromecánico del banco, resolver las discrepancias de instrumentación y caracterizar eléctricamente el circuito de falla antes de emitir conclusiones definitivas.

---

## 1. VERIFICACIÓN DE MOTOR Y CONDICIONES DE ALIMENTACIÓN

### 1.1 Datos de Placa y Configuración del Devanado
- [ ] **Inspección Visual y Fotográfica de la Placa de Bornes:**
  - Registrar fotografía de alta resolución de la placa del motor ABB M1AA 145T-D4.
  - Anotar valores nominales reales: Potencia ($P_n$), Tensión nominal ($V_n$), Corriente nominal ($I_n$), Frecuencia ($f_0$), Velocidad nominal ($n_r$), Factor de potencia ($\cos\varphi$) y Clase de Aislamiento.
  - Registrar el tipo de conexión física activa en la caja de bornes: **Estrella ($Y$)** o **Delta ($\Delta$)**.
- [ ] **Verificación de Alimentación Trifásica:**
  - Medir con multímetro digital calibrado True-RMS las tensiones de línea en bornes del motor en vacío:
    - $V_{AB} = \underline{\hspace{2cm}}\,\text{V}_{\text{RMS}}$
    - $V_{BC} = \underline{\hspace{2cm}}\,\text{V}_{\text{RMS}}$
    - $V_{CA} = \underline{\hspace{2cm}}\,\text{V}_{\text{RMS}}$
  - Medir las tensiones de fase respecto a neutro: $V_{AN}, V_{BN}, V_{CN}$.
  - Calcular el desbalance de tensión de red según estándar NEMA MG-1:
    $$\% \text{Desbalance} = \frac{\max |V_i - V_{\text{prom}}|}{V_{\text{prom}}} \times 100 \le 1.0\%$$

---

## 2. CARACTERIZACIÓN DEL CIRCUITO DE INYECCIÓN DE FALLA (FASE C)

### 2.1 Identificación Física del Devanado Modificado
- [ ] **Recuento de Espiras:**
  - Confirmar el número total de espiras por fase en el estator del motor: $N_{\text{fase}} = \underline{\hspace{1.5cm}}$ espiras.
  - Confirmar el número exacto de espiras comprendidas entre las dos derivaciones (*taps*) extraídas en la Fase C: $N_{\text{falla}} = \underline{\hspace{1.5cm}}$ espiras (declarada como 1 espira).
  - Calcular la fracción de devanado intervenido: $\mu = \frac{N_{\text{falla}}}{N_{\text{fase}}} \times 100\,\%$.
- [ ] **Medición de Tensión a Circuito Abierto ($V_{\text{tap}}$):**
  - Con el motor operando al 25% de carga y el relé SSR desconectado, medir con voltímetro True-RMS o sonda de osciloscopio la tensión inducida en circuito abierto entre los dos bornes de inyección:
    $$V_{\text{tap (abierto)}} = \underline{\hspace{2cm}}\,\text{V}_{\text{AC RMS}}$$
  *(Nota crítica: Verificar si $V_{\text{tap}}$ supera los 24 VAC requeridos para la conducción garantizada del TRIAC del Fotek SSR-25DA).*

### 2.2 Medición de Impedancia y Resistencia Limitadora
- [ ] **Inspección de la Resistencia de Potencia:**
  - Inspeccionar el encapsulado de la resistencia conectada en serie con el SSR.
  - Registrar valor nominal serigrafiado y potencia de disipación: $R_{\text{nom}} = \underline{\hspace{1.5cm}}\,\Omega$, $P_{\text{nom}} = \underline{\hspace{1.5cm}}\,\text{W}$.
  - Medir con puente LCR o miliohmímetro digital en frío:
    - Resistencia del devanado de la espira sola: $R_{\text{espira}} = \underline{\hspace{2cm}}\,\Omega$.
    - Resistencia de la carga limitadora externa: $R_{\text{ext}} = \underline{\hspace{2cm}}\,\Omega$.
    - Resistencia total del bucle cerrado: $R_{\text{loop}} = R_{\text{espira}} + R_{\text{ext}} = \underline{\hspace{2cm}}\,\Omega$.

### 2.3 Medición Directa de la Corriente del Lazo de Cortocircuito ($I_{\text{loop}}$)
- [x] **Comprobación Preliminar en Banco (COMPROBADO):**
  - La corriente física circulante por el lazo de 1 espira con la resistencia limitadora ante falla LEVE ha sido validada en banco: **$1.6\,\text{A} - 1.8\,\text{A}_{\text{RMS}}$ (valor típico: $1.7\,\text{A}_{\text{RMS}}$)**.
  - La etapa de excitación del SSR está alimentada con los **$5\,\text{V}$ del pin VBUS del Arduino Nano ESP32** (directos de la conexión USB), garantizando el nivel de tensión requerido para la conmutación del optoacoplador.
- [ ] **Registro Formal para Anexos de Tesis:**
  - Capturar oscilograma simultáneo en osciloscopio digital (sonda de corriente):
    - Canal 1: Corriente de estátor Fase C ($I_C$).
    - Canal 2: Corriente de lazo de cortocircuito ($I_{\text{loop}} = 1.7\,\text{A}_{\text{RMS}}$).
    - Verificar senoidalidad limpia y simetría de conmutación.
    - Exportar captura `.png` y `.csv` para el cuerpo del documento de tesis.

---

## 3. VERIFICACIÓN Y CALIBRACIÓN DE SENSORES DE ESTÁTOR

### 3.1 Sensores de Corriente (ACS712)
- [ ] **Confirmación del Modelo Exacto:**
  - Inspeccionar visualmente la serigrafía de los 3 módulos de corriente:
    - [ ] ACS712ELCTR-05B-T (Sensibilidad: 185 mV/A)
    - [ ] ACS712ELCTR-20A-T (Sensibilidad: 100 mV/A)
    - [ ] ACS712ELCTR-30A-T (Sensibilidad: 66 mV/A)
- [ ] **Comprobación de Divisores Resistivos:**
  - Verificar si la salida de 5V del ACS712 se conecta directamente al ESP32 o si utiliza divisor resistivo 2:1 ($10\,\text{k}\Omega / 10\,\text{k}\Omega$) para adecuar la señal a los $3.3\,\text{V}$ tolerados por el ADC.
- [ ] **Curva de Calibración Cruzada:**
  - Medir simultáneamente con analizador de calidad de energía o multímetro patrón True-RMS en serie con la línea:
    | Fase | Corriente Multímetro ($I_{\text{patron}}$) | Cuentas ADC ESP32 | Corriente Reportada Firmware | Error Relativo (%) |
    |:---:|:---:|:---:|:---:|:---:|
    | A | | | | |
    | B | | | | |
    | C | | | | |

### 3.2 Sensores de Tensión (ZMPT101B)
- [ ] **Comprobación de Ganancia de Fase B:**
  - Conectar las entradas de los 3 módulos ZMPT101B a la misma fase de 127 VAC en paralelo.
  - Ajustar los potenciómetros multivuelta de las placas para que las amplitudes de salida pico a pico en el osciloscopio sean idénticas ($V_{\text{pp}} \approx 2.5\,\text{V}$ centrada en $1.65\,\text{V}$).
  - Actualizar los factores `CAL_V` en firmware para que las tres fases empleen escalas homogéneas.

---

## 4. METROLOGÍA DE MUESTREO Y ADQUISICIÓN DIGITAL

- [ ] **Medición del Periodo de Muestreo Real en GPIO:**
  - Configurar un pin libre del ESP32-S3 (ejemplo: GPIO 10) para conmutar (`digitalWrite`) en cada entrada a la rutina `sampTimerCb`.
  - Conectar un osciloscopio digital o analizador lógico y medir durante 10 segundos:
    - Periodo medio: $T_s = \underline{\hspace{2cm}}\,\mu\text{s}$ (Nominal esperado: $416.67\,\mu\text{s}$).
    - Frecuencia media efectiva: $F_s = \frac{1}{T_s} = \underline{\hspace{2cm}}\,\text{Hz}$.
    - Desviación máxima (*Jitter* pico a pico): $\Delta T = \underline{\hspace{2cm}}\,\mu\text{s}$.
- [ ] **Comprobación del Desfase Intercanal del Multiplexor:**
  - Medir el tiempo total que consume la ejecución secuencial de las 6 conversiones `analogRead()` dentro de `taskMuestreo`.
  - Asegurar que el tiempo total de conversión de los 6 canales sea estrictamente menor que $T_s / 2 \approx 208\,\mu\text{s}$ para evitar solapamiento entre periodos.

---

## 5. LISTA DE ELEMENTOS Y FOTOGRAFÍAS REQUERIDAS PARA LA MEMORIA DE TESIS

1. **Fotografía 1:** Placa de características del motor ABB M1AA 145T-D4 legible al 100%.
2. **Fotografía 2:** Caja de bornes con las conexiones de alimentación y las derivaciones de falla salientes.
3. **Fotografía 3:** Montaje del relé Fotek SSR y la resistencia limitadora montada en su disipador térmico.
4. **Fotografía 4:** Placa de acondicionamiento de sensores (ACS712 y ZMPT101B) cableada al ESP32-S3 y la pantalla TFT.
5. **Captura de Osciloscopio 1:** Formas de onda simultáneas de corriente de línea ($I_C$) y corriente del lazo de falla ($I_{\text{loop}}$) durante un pulso de inyección.
6. **Captura de Osciloscopio 2:** Señal de interrupción del timer en GPIO demostrando la estabilidad temporal del muestreo a 2400 Hz.
