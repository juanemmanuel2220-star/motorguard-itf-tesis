# Estudio 2: generalización entre cargas, regla de Fortescue frente a Random Forest (14-oct-2026)

Protocolo declarado antes de correr: `~/PROTOCOLO_GENERALIZACION_CARGA.md` (commit `61c09f1`).
Script: `~/analisis_generalizacion_carga.py`.
Detalle en `resultado_generalizacion_carga.json` y `predicciones_por_fila.csv`. La robustez con el
venv está en los mismos archivos con el sufijo `_venv`.

**Entorno principal:** `/usr/bin/python3` (Python 3.14.4, scikit-learn 1.7.2), el mismo del estudio 1.
**Robustez:** venv (scikit-learn 1.9.0). Da las mismas conclusiones; las diferencias son de 1–2 filas en algunas celdas.

## Controles internos (cumplidos)
- 607 pares; 607 filas de falla; 588/607 filas SANO utilizables (intervalo ≤ 60 s).
- Mediana de |Δz| por celda igual a la de la verificación previa (LEVE 0 % 0.947, SEVERA 75 % 5.323 pp).
- La regla (a) reproduce la verificación: LEVE 0 % 50/50, 50 % 48/50, 75 % 59/60.

## Hipótesis primaria: NO CONFIRMADA
En E1 (entrenamiento solo al 75 %), con LEVE 0 %:

| Método | LEVE 0 % detectadas |
|---|---|
| Regla (a) | 50/50 |
| RF de Fortescue (b) | 50/50, igual con las 10 semillas y en los dos entornos |

McNemar: 0 discordantes, p = 1.0. **Con esta evaluación por pares, el RF de Fortescue no muestra el atajo de carga.**

Esto contradice la exploración previa (17/50 o 24/50, según la versión). Diferencias entre las dos:
- La exploración usó el RF del estudio 1, entrenado con **operación continua** (2.76 h de motor sano ruidoso), con rezagos y con la regla de alarma s ≥ 0.55 × 3 bloques.
- Aquí el RF se entrena con **pares**. Al 75 %, P separa casi por completo SANO de LEVE (E0: regla 59/60 con 0/150 FP), así que el árbol se apoya en P y |Δz|.

ΔI1 tiene importancia 0.33 en E1, pero no cambia las decisiones en las cargas bajas. **Interpretación (post hoc, no declarada):** el atajo ΔI1 aparece cuando P sola no basta, como con el ruido de la operación continua, y no con pares limpios. Para confirmarlo hace falta un análisis aparte.

## Resultados principales (semilla 0, umbral 0.5, un bloque)

**E1: entrenamiento al 75 %, prueba en cargas no vistas**

| Carga | Método | LEVE | INTER | SEVERA | FP SANO | Exactitud bal. |
|---|---|---|---|---|---|---|
| 0 % | Regla (a) | 50/50 | 50/50 | 50/50 | 4/145 | 0.986 |
| 0 % | RF de Fortescue (b) | 50/50 | 50/50 | 50/50 | 4/145 | 0.986 |
| 0 % | **RF-MCSA (c)** | **0/50** | **0/50** | **0/50** | 0/145 | **0.500** |
| 25 % | Regla (a) | 50/50 | 50/50 | 50/50 | 4/146 | 0.986 |
| 25 % | RF de Fortescue (b) | 50/50 | 50/50 | 50/50 | 4/146 | 0.986 |
| 25 % | **RF-MCSA (c)** | **0/50** | **0/50** | **0/50** | 0/146 | **0.500** |
| 50 % | Regla (a) | 48/50 | 50/50 | 50/50 | 5/147 | 0.976 |
| 50 % | RF de Fortescue (b) | 48/50 | 50/50 | 50/50 | 4/147 | 0.980 |
| 50 % | **RF-MCSA (c)** | **0/50** | **0/50** | **0/50** | 0/147 | **0.500** |

**E2: dejar una carga fuera**

| Carga de prueba | Regla (a) LEVE / FP | RF (b) LEVE / FP | RF-MCSA (c) |
|---|---|---|---|
| 0 % | 50/50 / 4/145 | 50/50 / 2/145 | LEVE 0/50, INTER 49/50, SEVERA 0/50; BA 0.663 |
| 25 % | 50/50 / 4/146 | 50/50 / 1/146 | 0 detecciones; BA 0.500 |
| 50 % | 48/50 / 5/147 | 45/50 / 2/147 | 0 detecciones; BA 0.500 |
| 75 % | 59/60 / 0/150 | 55/60 / 0/150 | **150/150 FP**; BA 0.500 |

- **E0** (dentro del 75 %, descriptivo): regla 59/60 LEVE con 0 FP; RF (b) 58/60 con 0 FP; RF-MCSA 45/60 con 4 FP.
- **McNemar (a) frente a (b):** no hay diferencias significativas en ninguna celda. La p mínima es 0.125 (E2 75 %, LEVE: la regla detecta 4 que el RF no). Con Holm, todas las p valen 1.0.
- **Semillas 0–9:** el RF (b) da los mismos resultados en E1. En E2 hay ±1–2 filas (LEVE 50 %: 45–46/50; 75 %: 55–57/60).
- **Regla reentrenada (a′):**
  - dirección de −79.9° a −82.1° y umbral 0.40 en casi todos los pliegues, con resultados iguales a los de (a);
  - excepción: E2 con prueba al 75 %, donde elige 0.55 y detecta LEVE 46/60.

## RF-MCSA: falla completa entre cargas (atajo de nivel absoluto)
- Importancias en E1: I_rms 0.30, `ia` 0.29, A_fund 0.09. **Aprende el nivel de corriente, es decir, la carga.**
- Entrenado al 75 %, en cargas menores clasifica todo como SANO (0 detecciones de 450 fallas).
- Entrenado sin el 75 %, clasifica todo el 75 % como falla (150/150 FP).
- **Este es el atajo de carga que sí se confirma**, y con características MCSA absolutas, el enfoque convencional.

## Indicadores del artículo (menor es mejor)

| Indicador | Regla (a) | RF de Fortescue (b) |
|---|---|---|
| e_FA (FA/h, estudio 1) | 5.08 | 1.81 |
| e_L75 (estudio 1) | 0.20 | 0.20 |
| e_L0 (E1) | 0.00 | 0.00 |
| e_FP (E2, media) | 0.022 | 0.009 (venv: 0.010) |
| e_BA (E2, media) | 0.0136 | 0.0124 |
| Área del radar | 1.43 | 0.49 (venv: 0.53) |

Con los indicadores declarados, **el RF de Fortescue es igual o mejor que la regla en todos los ejes**. La diferencia en los ejes del estudio 2 es pequeña y no significativa.

## Qué se puede afirmar
1. **Con características relativas de Fortescue,** la regla y el RF generalizan entre cargas en la evaluación por pares. Las dos detectan LEVE al 0 % sin haber visto esa carga.
2. **Con características MCSA absolutas,** el RF no generaliza en absoluto. Es el resultado más claro del estudio.
3. **El atajo ΔI1 del RF de Fortescue no se confirma** con la evaluación declarada. La afirmación "el RF aprendió un atajo que depende de la carga" (tesis §9.2, §11; encargo del artículo) **queda como observación exploratoria no confirmada**.
4. **Las limitaciones del protocolo siguen vigentes:**
   - severidad confundida con la sesión;
   - un bloque, sin FA/h;
   - pares filtrados por calidad;
   - un solo motor;
   - parámetros de captura distintos entre clases.
