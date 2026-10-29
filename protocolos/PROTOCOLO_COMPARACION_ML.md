# Comparación fuera de línea: regla del firmware contra aprendizaje automático (declarado 12-oct-2026)

**Tipo:** estudio fuera de línea, declarado antes de correr. El firmware 299a943 no se modifica.
Script: `~/comparacion_ml_deteccion.py`. Salida: `~/tesis_itf/comparacion_ml/`.

## Pregunta
¿Un modelo de aprendizaje automático que usa el contexto de varios bloques (Random Forest y
gradient boosting) reduce las falsas alarmas en operación continua sin perder detecciones, frente a
(A) la regla del firmware y (B) la misma regla con el umbral y la persistencia reajustados?

## Datos (solo lectura)
- **Motor sano continuo:** prueba larga del 12-oct, tramos 25/50/75/0 % (`larga_20261012_1319/1350/
  1422/1457`), 90 min.
- **Sesiones en vivo al 75 %:** `~/tesis_itf/validacion_vivo/vivo_*_serial.log`
  - LEVE 06-oct 17:53; 07-oct 14:04, 14:50, 15:29.
  - INTER 08-oct 16:28; 09-oct 15:01, 15:13.
  - SEVERA 08-oct 16:12, 16:37.
  - Cada pulso real se identifica por los mensajes `[DEBUG SSR] Exito` / `Apagado` del propio log.
  - Los periodos sin pulso de estas sesiones también cuentan como motor sano.
- **Excluidas del análisis principal** (lazo degradado, anuladas en su momento): LEVE 09-oct 15:26 y
  15:46. Se reportan aparte.
- **No se usan:**
  - los pares del dataset (sus logs no tienen secuencias continuas de bloques);
  - los calentamientos (régimen distinto; se reportan aparte si hace falta).

## Etiquetas por bloque (Motor:ON y con referencia disponible)
- **Falla (1):** bloque recibido entre t_on + 1.0 s y t_off del SSR.
- **Excluido:**
  - entre t_on y t_on + 1.0 s (bloque parcial);
  - desde t_off hasta t_off + 12 s (la referencia móvil aún contiene la falla).
- **Sano (0):** todos los demás.

## Características (solo relativas, sin niveles absolutos, para no aprender "carga" ni "sesión")
Para el bloque t y los 4 anteriores:
- proyección P y componente perpendicular Q de Δz;
- |Δz|;
- cambio relativo de |I1| y de |V1| respecto a la referencia;
- |ΔV2|/|V1|.

Además, la dispersión de z en los últimos 30 s. Todas se calculan con los mismos fasores RAW y la misma
referencia móvil del firmware (mediana entre 11 y 6 s antes), de forma causal.

## Detectores
- **A. Regla del firmware:** P ≥ 0.40 pp durante 3 bloques.
- **B. Regla reajustada:** P ≥ u durante k bloques, con u ∈ {0.40, 0.45, …, 1.00} y k ∈ {3, 4, 5, 6}.
- **C1. Random Forest** (300 árboles, profundidad máx. 6, `class_weight=balanced`).
- **C2. Gradient boosting** (`HistGradientBoostingClassifier`, profundidad máx. 4).

C produce una probabilidad por bloque. La alarma se dispara con probabilidad ≥ s durante k bloques
(k ∈ {1, 2, 3}).

## Validación
- **Dejando un grupo fuera:** cada tramo de la prueba larga y cada sesión en vivo es un grupo. El
  modelo nunca ve el grupo con el que se evalúa. Las probabilidades fuera de muestra se juntan y
  sobre ellas se aplica la lógica de alarma.
- **Eventos:**
  - una alarma nueva requiere que la condición haya estado apagada al menos 3 bloques;
  - **detección** = alarma que empieza entre t_on y t_off + 2 s de un pulso real;
  - **falsa alarma** = alarma que empieza en un periodo sano;
  - la exposición sana es la suma del tiempo de bloques sanos.

## Métricas y criterio de decisión (fijados antes de correr)
- Por detector y punto de operación:
  - falsas alarmas por hora, con IC 95 % Poisson;
  - detección por severidad (LEVE / INTER / SEVERA);
  - retardo mediano de detección.
- **Punto de comparación principal:** el de menos falsas alarmas por hora que conserve la detección
  de la regla A en cada severidad (mismo número de pulsos detectados o más).
- **C se considera mejor que B** solo si, en ese punto, tiene menos falsas alarmas por hora y los IC 95 %
  no se traslapan. Si no, la conclusión es que el aprendizaje automático no supera a la regla física
  reajustada con estos datos.

## Limitaciones declaradas
- Todos los positivos son al 75 %, y los negativos continuos son de un solo día.
- Los puntos de operación de B y C se eligen sobre los mismos datos agrupados. El resultado indica qué
  justifica una validación ciega nueva; no la sustituye.
