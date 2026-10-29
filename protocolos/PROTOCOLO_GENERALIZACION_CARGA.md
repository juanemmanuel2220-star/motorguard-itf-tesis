# Generalización entre cargas: regla de Fortescue frente a Random Forest (declarado 14-oct-2026)

**Tipo:** estudio fuera de línea. Queda declarado con el commit de este archivo, antes de correr el script.
El firmware `299a943`, los scripts de validación existentes y los datos no se modifican.
Script: `~/analisis_generalizacion_carga.py` (solo lee). Salida: `~/tesis_itf/generalizacion_carga/`.

## Pregunta
Un Random Forest entrenado con fallas a ciertas cargas, ¿detecta las fallas a una carga que no vio
con la misma sensibilidad y especificidad que la regla de Fortescue (P ≥ 0.40 pp)?

## Antecedente (declararlo)
La exploración NO declarada `~/exploracion_rf_cargas_pares.py` ya usó **los mismos pulsos**. El RF
del estudio 1, entrenado con fallas solo al 75 %, detectó:
- con scikit-learn 1.7.2 (Python del sistema, el del estudio 1): LEVE 0 % en 17/50 y LEVE 25 % en 39/51;
- con scikit-learn 1.9.0 (venv): 24/50 y 42/51.

La regla da lo mismo en los dos entornos. El atajo se ve en ambos, pero su magnitud depende de la
versión, porque la probabilidad del RF queda cerca del umbral (mediana 0.56–0.60 en LEVE 0 %).
La exploración contó pulsos del log, incluidos los que la captura descartó (LEVE 25 %: 51 pulsos
frente a 50 pares); no son exactamente las mismas filas de este estudio.

Este estudio **no es evidencia independiente**. Formaliza esa observación con:
- métricas fijadas de antemano;
- dos esquemas de entrenamiento;
- un control con la regla reentrenada;
- un RF con características MCSA.

## Datos (solo lectura)
`~/tesis_itf/dataset/cap_ENTRELAZADA_{LEVE,INTER,SEVERA}_*_2026100[678]_*.csv`. Se excluyen
`*_descartes.csv`, `.bak` y los de septiembre. Son 13 archivos con 607 pares (1214 filas). Cada archivo
alterna una fila SANO y una de falla.

| Carga | LEVE | INTER | SEVERA |
|---|---|---|---|
| 0 % | 50 (06-oct) | 50 (07-oct) | 50 (08-oct) |
| 25 % | 50 | 50 | 50 |
| 50 % | 50 | 50 | 50 |
| 75 % | 50 (06-oct) + 10 (07-oct) | 50 | 47 |

## Significado verificado de las columnas (14-oct)
Fuentes: `captura_dataset_multiclase.py` v4.2, `PRUEBA_MODELO_1.ino` y `detector_dir.h`.
- **`r2_re`, `r2_im` e `i1`:** los fasores crudos (`RAW:`) con los que el firmware alimenta `dir_step()`.
  - R2 = I2 − Y2·V2 − I2_0, rotado a arg(V1), en A pico; `i1` = |I1|.
  - Con ellos, z = R2/|I1|·100 (pp).
- **`de2_fw` y `ang_de2`: NO son el Δz del detector final.** Son |R2 − R2_base|/|I1| y su ángulo, donde
  R2_base es una EMA (α = 0.05, τ ≈ 34 s) del detector CUSUM anterior. En las filas de falla, su
  correlación con el Δz por par va de 0.20 a 0.94. **No se usan.**
- **`delta_e2`:** copia de `de2_fw` en las filas de falla; 0 en las SANO. No se usa.
- **`pred_fw`:** decisión del firmware que corría en la captura:
  - LEVE 06-oct (`2dff915`): CUSUM anterior;
  - INTER, SEVERA y LEVE 07-oct (`81657f4`/`e4922bd`): `dir_step` con persistencia de 3 bloques y referencia móvil.
  
  No se puede reproducir con una sola fila y no se usa como referencia.
- **`A_fund`, `A_55`, `A_65` y `hr_*`:** se calculan sobre la "fase crítica", que el firmware elige en
  cada bloque (máx. (A55 + A65)/Afund). En el dataset sale A, B o C casi al azar (≈ 1/3 cada una, en
  SANO y en falla).
- **`V_rms` e `I_rms`:** fase C (`vc`, `ic`). `va`, `vb`, `ia` e `ib`: las otras fases.
- **Columnas sin uso:**
  - **`A_50`, `A_70` y `THD`:** escritas como 0.0 constante (el script no las registra);
  - **`dom`:** constante;
  - **`p_cal` y `cusum_s`:** salidas del detector anterior (fuga de la decisión).

**Control de la definición de Δz.** Las sesiones con firmware ≥ `81657f4` traen el campo `DIR: P` en
`_serial.log`. Cada fila del CSV se emparejó con su línea del log por los valores RAW (806/814 filas).
En las 407 filas de falla, todas emparejadas, la P del firmware (referencia móvil de 6–11 s) y la P por par de abajo
difieren en una mediana de 0.02–0.07 pp por sesión (p95 ≤ 0.33 pp).

## Unidad de análisis y características
**Fila de falla k:** Δz_k = z(falla_k) − z(SANO_k), con el SANO del mismo par, tomado justo antes del pulso.
Equivale a la referencia del firmware (6–11 s antes).
Es la definición del firmware (cada bloque normalizado por su propio |I1|). La Tabla A de la tesis
usa (R2_F − R2_S)/|I1_F|; las medianas por celda difieren hasta 0.11 pp (SEVERA 75 %: 5.32 frente a
5.21 pp). El texto lo dirá.

**Fila SANO k (control nulo):** Δz_k = z(SANO_k) − z(SANO_{k−1}), con el SANO del par anterior del mismo
archivo.
- Solo si el intervalo es ≤ 60 s. Así quedan 588 de 607; se excluyen la primera fila de cada archivo y
  las reanudaciones.
- El intervalo típico es de 15–29 s, más largo que la referencia del firmware. Es conservador para
  la especificidad de **ambos** métodos por igual.

**Por qué no se usa la P del firmware en las SANO:** con 8 s de enfriamiento, la ventana de referencia
contiene el pulso anterior y P sale muy negativa (sd 0.47–0.53 pp en INTER 0 y 25 %).

**Características de Fortescue, relativas** (las del estudio 1 sin rezagos ni dispersión de 30 s, que
no existen en pares):
- P = Re{Δz·e^{+j81.4°}} y Q = Im{Δz·e^{+j81.4°}};
- |Δz|;
- ΔI1 = (|I1| − |I1|_ref)/|I1|_ref·100;
- ΔV1, el equivalente para |V1|;
- |ΔV2|/|V1|·100.

No incluyen niveles absolutos ni la carga.

**Características MCSA convencionales, absolutas:**
- RMS: I_rms (fase C), `ia`, `ib`, V_rms, `va` y `vb`;
- espectro de la fase crítica: A_fund, A_55, A_65, hr_l2sm, hr_l2sp, hr_lrm, hr_lrp, hr_l3, hr_l3rm,
  hr_l3rp, hr_snr2s, hr_s y hr_f0;
- la fase crítica en *one-hot*.

Limitación: no hay THD ni espectro fijo en la fase C.

## Métodos (todos sobre las mismas filas)
- **(a) Regla del firmware:** falla si P ≥ 0.40 pp, con dirección −81.4°. Es de un bloque y no se entrena.
  **Ojo:** la dirección −81.4° y el umbral se ajustaron con el bloque LEVE 06-oct de este mismo dataset
  (4 cargas), así que la regla no está fuera de muestra.
- **(a′) Regla reentrenada (control de equidad):**
  - dirección = media circular de arg(Δz) de las filas de falla de entrenamiento;
  - umbral elegido en entrenamiento en {0.20, 0.25, …, 1.00} por exactitud balanceada (empates: el más cercano a 0.40).
- **(b) RF-Fortescue:** las 6 características relativas.
- **(b′) RF-Fortescue sin ΔI1:** prueba directa del mecanismo del atajo.
- **(c) RF-MCSA:** características absolutas.

Hiperparámetros de los RF (los del estudio 1):
- 300 árboles, `max_depth=6`, `min_samples_leaf=5`, `class_weight='balanced'`, `random_state=0`;
- **umbral de probabilidad fijo en 0.5**;
- objetivo binario: SANO frente a falla (las tres severidades).

**Entorno:** `/usr/bin/python3 -I` (Python 3.14.4, scikit-learn 1.7.2, numpy 2.3.5, scipy 1.16.3,
matplotlib 3.10.7), el mismo con el que se corrió el estudio 1. Las versiones se guardan en el JSON.
Como robustez, los RF también se corren con el venv (`~/tesis_itf/venv`, scikit-learn 1.9.0) y se
reportan aparte.

## Esquemas
- **E0 (referencia dentro de la distribución, descriptivo):** 5 particiones estratificadas al azar
  solo con las filas al 75 %. Es optimista por diseño.
- **E1 (prueba del atajo):** entrenar con todas las filas al 75 % y probar en 0, 25 y 50 %.
- **E2 (dejar una carga fuera):** 4 pliegues; se entrena con 3 cargas y se prueba con la 4.ª.

## Métricas (por esquema, carga de prueba y método)
- Sensibilidad por severidad: detectadas/n, con IC de Wilson al 95 %.
- Falsos positivos en filas SANO: FP/n, con IC de Wilson.
- Exactitud balanceada.
- AUC de la puntuación continua: P para la regla y la probabilidad para el RF. Se calcula SANO frente
  a LEVE y frente a falla total (secundaria, independiente del umbral).
- **McNemar exacto** (binomial sobre los discordantes), (a) frente a (b) en las mismas filas:
  - por separado en filas de falla (detección) y SANO (FP);
  - p sin ajustar y p de Holm dentro de cada esquema.
- Robustez: (b), (b′) y (c) con las semillas 0–9; se reportan la mediana y el rango.

## Hipótesis y criterio
- **Primaria (E1):** en LEVE 0 %, la sensibilidad de (b) es menor que la de (a), con McNemar exacto
  p < 0.05 con la semilla 0, **y** la sensibilidad de (b) es menor que la de (a) con las 10 semillas.
  - Si no se cumplen las dos condiciones, el atajo no se confirma con esta evaluación y así se reporta.
- **Secundarias (sin criterio, se reportan todas):**
  - E2 para (a), (a′), (b), (b′) y (c);
  - FP por carga;
  - si (b′) recupera LEVE a baja carga, apoya que el atajo es ΔI1;
  - si (a′) ≈ (a), la ventaja de la regla no viene de haber visto las 4 cargas.

## Indicadores de comparación para el artículo (fijados antes de correr)
Todos orientados a "menor es mejor". Se calculan para (a) y (b):
- **e_FA:** FA/h del estudio 1. Ya existe: 5.1 frente a 1.8; se copia del JSON y no se recalcula.
- **e_L75:** 1 − sensibilidad LEVE del estudio 1. Ya existe.
- **e_L0:** 1 − sensibilidad LEVE al 0 % en E1.
- **e_FP:** tasa de FP en filas SANO, media de los 4 pliegues de E2.
- **e_BA:** 1 − exactitud balanceada, media de E2.

Se reportan en una tabla y en un gráfico de radar:
- cada eje normalizado al peor de los dos métodos;
- ejes en este orden fijo;
- con el área del polígono.

La tabla es el resultado; el radar es ilustrativo, porque su área depende del orden de los ejes.

## Limitaciones a declarar
1. Cada severidad se capturó en un día distinto (LEVE 06, INTER 07, SEVERA 08-oct), así que severidad
   y sesión están confundidas. Cada celda (severidad × carga) es una sola sesión. En E2, la carga de
   prueba aporta sesiones nunca vistas.
2. Evaluación por pares de un bloque, sin persistencia, enclavamiento ni FA/h. No sustituye al
   estudio 1 ni a la prueba larga (7.3 FA/h).
3. La captura descartaba los pares inestables (filtro de corrientes y DE2 dentro del pulso). Las
   tasas de descarte salen en `_meta.json`.
4. Un solo motor. Falla limitada por 5 Ω (LEVE 1.7 A en el lazo); en la fase C.
5. El ΔI1 de la falla depende del resistor limitador. El atajo puede ser propio de este banco.
6. Las características MCSA vienen de una fase que cambia en cada bloque, sin THD.
7. El control nulo SANO usa un intervalo de 15–29 s en lugar de 6–11 s.
8. Los parámetros de captura cambiaron entre clases (`_meta.json`): el filtro `tol_de2` fue 0.35 pp
   en LEVE e INTER y 1.0 pp en SEVERA, y el enfriamiento fue de 8 s (LEVE, INTER 0/25 %), 15 s (INTER 50/75 %)
   y 20 s (SEVERA). El intervalo del control nulo, y con él su ruido, depende de la sesión.
9. La cifra exploratoria previa (17/50) depende de la versión de la librería; este estudio la
   reemplaza.

## Salidas
- `resultado_generalizacion_carga.json`: todas las cifras y las predicciones por fila.
- `RESUMEN_generalizacion_carga.md`.
- Figuras PDF (3.5 in), cada una con su script.
