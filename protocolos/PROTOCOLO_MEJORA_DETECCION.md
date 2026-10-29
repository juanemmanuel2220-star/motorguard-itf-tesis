# Análisis fuera de línea del ruido y de variantes del detector (declarado 13-oct-2026)

**Tipo:** estudio fuera de línea, declarado antes de correr. El firmware 299a943 no se modifica.
Script: `~/analisis_mejora_deteccion.py`. Salida: `~/tesis_itf/mejora_deteccion/`.

## Preguntas
1. **Naturaleza del ruido.** ¿El ruido de la firma con motor sano es blanco (promediar ayuda) o es una
   deriva lenta (promediar no ayuda y conviene cambiar la referencia)?
2. **Variantes del detector.** ¿Alguna variante del detector direccional reduce las falsas alarmas sin
   perder detecciones frente a la regla del firmware (A)? Las variantes usan solo P y Q, es decir, la
   geometría de la firma, sin características de nivel como |I1|.

## Datos (solo lectura; los mismos 13 grupos de `PROTOCOLO_COMPARACION_ML.md`)
- **Motor sano continuo:** tramos 25/50/75/0 % de la prueba larga del 12-oct, 4 × 22.5 min.
- **Sesiones en vivo al 75 %:**
  - LEVE 06-oct 17:53; 07-oct 14:04, 14:50, 15:29;
  - INTER 08-oct 16:28; 09-oct 15:01, 15:13;
  - SEVERA 08-oct 16:12, 16:37.
  - Pulsos identificados por `[DEBUG SSR] Exito` / `Apagado`.
- **Excluidas:** LEVE 09-oct 15:26 y 15:46 (lazo degradado).
- **Verificación por carga (aproximada):** pares del dataset multiclase a 0/25/50/75 %, con la misma
  aproximación de `~/exploracion_rf_cargas_pares.py` (referencia = bloque sano previo al pulso).

**Restricciones conocidas antes de correr:**
- En 3 de las 4 sesiones LEVE en vivo los pulsos duran ~7.1 s (3–4 bloques con falla). En la de las
  15:29 duran 11.2 s, y en INTER y SEVERA 10.5–12.1 s.
- Los pares del dataset tienen 3–4 bloques con falla.
- Por lo tanto, una variante que necesite más de 4 bloques para confirmar no puede detectar los pulsos
  LEVE de 7 s. Ese costo se reporta tal cual.
- En LEVE 07-oct 14:50 el lazo dejó de conducir en parte de los pulsos reales. Ningún detector los
  puede detectar, y cuentan igual para todas las variantes.

## Parte 1. Ruido (descriptivo)
En cada tramo de la prueba larga, sin falla y con carga constante:
- **Desviación de Allan solapada** de la proyección de z = R2/|I1| sobre −81.4° (zP) y de su
  perpendicular (zQ), con τ = m × 1.7 s y m ∈ {1, 2, 4, 8, 16, 32, 64, 128}. Lo mismo para
  V2/|V1| proyectado, como comparación del canal de voltaje.
- **Regla de interpretación, fijada de antemano** (pendiente local de log σ contra log τ):
  - cerca de −0.5: ruido blanco;
  - cerca de 0: ruido de parpadeo;
  - cerca de +0.5: deriva o caminata aleatoria.
- σ y autocorrelación de lag 1 de P (Δz proyectado) para cada longitud de referencia de la Parte 2.

## Parte 2. Variantes del detector
**Simulación:** port del detector de `analisis_compensacion_v2.py` (fiel al firmware: C coincide
99.6–100 %), generalizado. Se conservan:
- el enclavamiento con base congelada;
- la severidad por mediana de |Δz| de los 3 últimos bloques (umbrales 1.626 / 4.471);
- el escalamiento de severidad;
- la liberación.

**Ingredientes** (rejilla completa):
- **Referencia:** mediana entre t−D y t−6 s, con D ∈ {11 (firmware), 20, 30, 60} s.
- **Estadístico de confirmación:**
  - **F1 racha:** P ≥ u durante k bloques; u ∈ {0.30, 0.35, …, 0.80}, k ∈ {2, 3, 4, 5}.
  - **F2 media móvil:** media de P en los últimos n bloques ≥ u; n ∈ {2, 3, 4}, u igual que en F1.
  - **F3 CUSUM:** S = max(0, S + P − κ), alarma si S ≥ h; κ ∈ {0.10, 0.15, 0.20, 0.25, 0.30, 0.40},
    h ∈ {0.4, 0.6, 0.8, 1.0, 1.2, 1.5, 2.0}.
- **Compuerta de dirección:** un bloque solo aporta evidencia (P se toma como min(P, 0)) si |Q| ≤ g;
  g ∈ {sin compuerta, 0.6, 0.45, 0.3} pp.
- **Liberación** en la rejilla: la del firmware, max(0.20, 0.35·P_conf) durante 3 bloques.

**Línea base A:** F1, u = 0.40, k = 3, D = 11, sin compuerta (el firmware).

**Reinicios `r`:**
- Los `r` reales de la prueba larga solo se aplican en la verificación de fidelidad (el replay de A
  debe dar los 11 eventos registrados).
- En la comparación ninguna variante recibe `r`, tampoco A. Las alarmas atascadas cuentan con su
  duración real simulada.

**Eventos y métricas** (definiciones de `PROTOCOLO_COMPARACION_ML.md`, con el detector completo):
- **Inicio de alarma:** C pasa de 0 a 1.
- **Detección:** inicio entre t_on y t_off + 2 s de un pulso.
- **Falsa alarma:** inicio en un bloque sano. Los inicios en el drenado (t_off + 2 s a t_off + 12 s) se
  reportan aparte.
- **Exposición sana:** la de la regla A, igual para todas las variantes.
- **Métricas:**
  - FA/h con IC 95 % Poisson;
  - detecciones por severidad;
  - severidad correcta;
  - retardo mediano;
  - tiempo en falsa alarma (s/h).

**Selección honesta (LOGO anidado), resultado principal:**
1. Para cada grupo dejado fuera, se elige en los otros 12 la configuración con menos FA/h entre las
   que detectan al menos lo mismo que A en cada severidad (en esos 12 grupos).
2. Desempates: más detecciones, menor retardo mediano y, por último, la más simple (F1 < F2 < F3,
   D menor, sin compuerta).
3. Se evalúa en el grupo dejado fuera y se suman los 13 resultados.

Se repite restringiendo la rejilla para ver qué aporta cada ingrediente:
- (a) solo umbral y persistencia (D = 11, sin compuerta);
- (b) + referencia;
- (c) + compuerta;
- (d) F2;
- (e) F3;
- (f) todo.

**Configuración final:** la que elige la misma regla con los 13 grupos. Es la que se llevaría a la
validación en el banco.

**Análisis complementarios** (descriptivos, sobre la configuración final, la de mayor reducción de
falsas alarmas y A):
- **Liberación:** nivel mínimo L ∈ {0.20, 0.30, 0.40}. Se mide la duración de las alarmas atascadas
  con motor sano y las liberaciones antes de t_off en pulsos reales.
- **Persistencia extra solo para LEVE:** confirmar INTER y SEVERA como siempre, y LEVE con e ∈
  {2, 4, 6} bloques adicionales.
  - Solo se mide la reducción de falsas alarmas.
  - La detección LEVE no se puede medir con pulsos de 7–11 s, y se reporta como no medible.

**Verificación por carga (aproximada):**
- La configuración final y A se evalúan sobre los pares del dataset a 0/25/50/75 %.
- La referencia de la aproximación es la misma para ambas, así que se verifica solo el estadístico y
  la compuerta, no la longitud de la referencia.
- La CUSUM arranca en S = 0 en cada pulso.
- Si la configuración final necesita más bloques de los que tienen los pares, la verificación se
  declara no realizable.

## Criterio para pasar a la validación en el banco (fijado antes de correr)
Se recomienda la validación ciega en el banco (paso B: capa de confirmación en la app) solo si se
cumplen las tres condiciones:
1. **FA/h fuera de muestra** (LOGO, todo) **≤ 50 % de las de A**.
2. Detecciones fuera de muestra **≥ las de A** en cada severidad.
3. La configuración final no pierde más de 2 pulsos LEVE por carga frente a A en la verificación
   aproximada, o la verificación es no realizable y así se declara.

La significancia estadística se decide en la validación ciega, no aquí. Si no se cumple, la conclusión
es que, con estos sensores, la regla actual está cerca del límite de la relación señal/ruido, y que la
mejora requiere hardware o más datos.

## Limitaciones declaradas
- Mismos datos que motivaron las variantes; la selección LOGO reduce, pero no elimina, el optimismo.
- Positivos solo al 75 % en vivo; negativos continuos de un solo día.
- Los pulsos LEVE cortos (7 s) castigan las variantes lentas.
