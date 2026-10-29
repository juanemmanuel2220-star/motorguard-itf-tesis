# PROTOCOLO Y DISEÑO EXPERIMENTAL PARA LA NUEVA CAMPAÑA DE DATOS
## Proyecto MotorGuard-ITF

**Fecha:** 26 de Septiembre de 2026  
**Rama de Trabajo:** `v2_reproducible`  
**Objetivo:** Diseño de una campaña experimental rigurosa, estadísticamente válida e independiente, que elimine sesgos por autocorrelación temporal, solapamiento de ventanas y variaciones de temperatura.

---

## 1. PRINCIPIOS METODOLÓGICOS DEL DISEÑO EXPERIMENTAL

Para que los resultados de la tesis sean científicamente inobjetables, la nueva campaña de datos debe sustentarse en cuatro principios fundamentales:

1. **Jerarquía Clara de Datos:**
   - **Muestra puntual:** Cada vector digitalizado por el ADC a $F_s = 2400\,\text{Hz}$ ($t_s = 416.7\,\mu\text{s}$).
   - **Ventana de análisis:** Bloque de $N = 4096$ muestras continuas ($1.706\,\text{s}$) sobre el cual se calcula una FFT.
   - **Evento:** Un pulso continuo de inyección de falla o un intervalo continuo de operación sana de duración fija ($10 - 30\,\text{s}$).
   - **Sesión experimental:** Un ciclo completo de encendido del motor, estabilización térmica, ejecución de ensayos y apagado con reposo térmico intermedio.
   > [!WARNING]
   > **Principio de No Contaminación:** Jamás deben presentarse múltiples ventanas solapadas provenientes de un mismo evento como si fueran experimentos independientes. La partición Train/Validation/Test debe realizarse a nivel de **sesiones o eventos independientes**, nunca mezclando ventanas temporales adyacentes del mismo bloque.

2. **Control y Registro de Variables Exógenas:**
   - Registro de temperatura de la carcasa del estator mediante termómetro infrarrojo o termopar tipo K antes y después de cada bloque.
   - Medición de la tensión de alimentación de red en cada sesión para monitorear fluctuaciones diurnas de la compañía eléctrica.
   - Medición de la velocidad mecánica real con tacómetro óptico para computar el deslizamiento real $s = (n_s - n_r)/n_s$ y la posición teórica exacta de las bandas $f_0(1 \pm 2s)$.

3. **Aleatorización y Contrabalanceo:**
   - En lugar de ejecutar siempre SANO seguido de FALLA, alternar el orden o aleatorizar la secuencia de cargas mecánicas para cancelar el efecto sistemático del calentamiento progresivo del cobre.

---

## 2. CAMPAÑA PILOTO (FASE PRELIMINAR DE CALIBRACIÓN)

Antes de ejecutar una campaña masiva de cientos de muestras, se ejecutará una **campaña piloto** de 2 sesiones independientes en días distintos con el fin de estimar la varianza intra-sesión e inter-sesión del banco:

### Matriz de la Campaña Piloto
- **Sesiones:** 2 sesiones independientes (Día 1 y Día 2), con motor partiendo de temperatura ambiente ($25^\circ\text{C}$).
- **Niveles de Carga:** 25%, 50% y 75% de carga nominal (se recomienda excluir el 0% para el detector en el rango 53.5–57.8 Hz, o ampliar las ventanas espectrales dinámicamente según la velocidad).
- **Eventos por Nivel de Carga en cada Sesión:**
  - 3 Eventos SANO (duración: 20 segundos cada uno).
  - 3 Eventos FALLA LEVE (duración: 8 segundos cada uno, con intervalo de enfriamiento de 60 segundos entre eventos para proteger la resistencia de $5\,\Omega$).
- **Métricas a Estimar en el Piloto:**
  - Desviación estándar del cociente $r_{65} = A_{65}/A_{\text{fund}}$ en estado sano a lo largo de 20 segundos (variabilidad del rizado de banda).
  - Magnitud del incremento de $r_{65}$ durante inyección ($\Delta r_{65} = r_{65,\text{falla}} - r_{65,\text{sano}}$).
  - Si $\Delta r_{65} < 2 \times \sigma_{\text{sano}}$, el clasificador no podrá discriminar de forma estadísticamente robusta sin filtrado temporal prolongado.

---

## 3. DISEÑO DE LA CAMPAÑA DEFINITIVA

Una vez confirmada la separabilidad en el piloto, se procederá con la campaña principal:

| Parámetro | Especificación Formal | Justificación Metodológica |
|:---|:---|:---|
| **Número de Sesiones Independientes** | **4 sesiones** en horarios y días diferentes | Permite evaluar la variabilidad de la tensión de red y condiciones ambientales. |
| **Niveles de Carga** | 25%, 50%, 75% nominal | Régimen operativo representativo de motores industriales bajo carga. |
| **Tiempo de Warmup Previo** | **3 minutos continuos** antes de capturar | Garantiza que el motor supere el régimen de inrush y comience a estabilizar térmicamente. |
| **Duración de Eventos SANO** | 30 segundos continuos | Permite registrar múltiples ciclos completos de la oscilación de la banda mecánica. |
| **Duración de Eventos FALLA** | 8 segundos continuos | Suficiente para capturar 4 ventanas completas sin sobrecalentar el lazo de 1 espira. |
| **Pausa de Descanso Térmico** | **45 segundos** con SSR OFF entre inyecciones | Evita el daño acumulativo de la resistencia de potencia y el barniz del devanado. |
| **Protocolo de Validación Cruzada** | **GroupKFold** agrupando por `id_sesion` | Garantiza que el conjunto de prueba contenga sesiones completas no vistas durante el entrenamiento. |

---

## 4. CRITERIOS DE DESEMPEÑO Y DEFINICIÓN DE ÉXITO

En lugar de imponer metas arbitrarias de "100% de precisión", la evaluación formal se sustentará en dos niveles claramente diferenciados:

### Nivel 1: Rendimiento por Ventana (Clasificador de IA puro)
- Se evaluará sobre el conjunto de prueba reservado (*holdout* de sesiones no vistas).
- Métrica objetivo:
  - Área bajo la curva ROC ($\text{AUC-ROC}$) $\ge 0.75$.
  - Exactitud balanceada ($\text{Balanced Accuracy}$) $\ge 70.0\%$.

### Nivel 2: Rendimiento por Evento (Sistema Completo con Filtro Temporal)
- Se evaluará la capacidad de la máquina de estados y el filtro ANSI 51 para alertar al operador:
  - **Tasa de Falsas Alarmas en Reposo:** $\le 1$ falsa alarma por cada 60 minutos de operación continua sana.
  - **Tasa de Detección de Falla (Recall por Evento):** $\ge 90.0\%$ de los eventos de falla física confirmados deben ser detectados.
  - **Latencia Máxima Admisible:** Disparo consolidado en $\le 5.0\,\text{s}$ desde la confirmación de conducción eléctrica del lazo.
  - **Tiempo de Despeje Post-Corte:** Retorno a estado sano en $\le 3.0\,\text{s}$ tras la apertura del relé.
