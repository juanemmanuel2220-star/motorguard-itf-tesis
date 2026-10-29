# Comparación regla del firmware frente a aprendizaje automático (12-oct-2026)

Protocolo declarado antes de correr: `PROTOCOLO_COMPARACION_ML.md` (commit 459bee9).
Script: `~/comparacion_ml_deteccion.py`. Detalle: `resultado_comparacion_ml.json`.

## Datos
- 13 grupos: 4 tramos de la prueba larga y 9 sesiones en vivo al 75 %.
- 94 pulsos reales: 60 LEVE, 22 INTER, 12 SEVERA.
- 2.76 h de motor sano.
- Validación dejando un grupo fuera.

## Resultado principal (punto de operación declarado: menos FA/h sin perder detecciones de A)

| Detector | Falsas alarmas | FA/h (IC 95 %) | LEVE | INTER | SEVERA | Retardo mediano |
|---|---|---|---|---|---|---|
| A. Regla del firmware (0.40, 3 bloques) | 14 | 5.1 (2.8–8.5) | 48/60 | 21/22 | 12/12 | 5.4 s |
| B. Regla reajustada (mejor punto = A) | 14 | 5.1 (2.8–8.5) | 48/60 | 21/22 | 12/12 | 5.4 s |
| C1. Random Forest (s = 0.55, 3 bloques) | **5** | **1.8 (0.6–4.2)** | 48/60 | **22/22** | 12/12 | 5.8 s |
| C2. Gradient boosting (s = 0.85, 2 bloques) | 6 | 2.2 (0.8–4.7) | 48/60 | 22/22 | 12/12 | 4.1 s |

**Criterio declarado** (IC 95 % sin traslape): **no se cumple**. Los intervalos de A (2.8–8.5) y C1
(0.6–4.2) se traslapan. Con estos datos no se puede afirmar con 95 % de confianza que el aprendizaje
automático sea mejor.

**Curva de compromiso** (descriptivo):

| | Falsas alarmas | LEVE detectadas |
|---|---|---|
| Regla, umbral 0.40, k = 4 | 6 | 44 |
| Regla, umbral 0.45, k = 4 | 4 | 37 |
| Regla, umbral 0.60, k = 3 | 5 | 22 |
| Random Forest, s = 0.50 | 6 | 48 |
| Random Forest, s = 0.60 | 4 | 46 |

A igual número de falsas alarmas, el Random Forest detecta consistentemente más fallas LEVE que
cualquier ajuste de la regla.

**Por grupo** (A → RF):

| Tramo de la prueba larga | A | RF |
|---|---|---|
| 25 % | 3 | 3 |
| 50 % | 2 | 0 |
| 75 % | 4 | 0 |
| 0 % | 3 | 1 |

Las 2 FA de A en sesiones INTER bajan a 1.

## De dónde viene la mejora (importancias y prueba exploratoria NO declarada)
Las características más importantes del Random Forest son:

| Característica | Importancia |
|---|---|
| P actual | 0.24 |
| **ΔI1 actual** | **0.16** |
| \|Δz\| | 0.13 |
| P anterior | 0.12 |

Durante la falla, |I1| sube: el lazo de falla consume potencia.

| Condición | ΔI1 mediano |
|---|---|
| Sano | −0.01 % (p5–p95: −0.40 a +0.38) |
| LEVE | +0.29 % |
| INTER | +1.90 % |
| SEVERA | +5.05 % |

Exploratorio (no declarado): **sin las características ΔI1, el Random Forest pierde casi toda la
ventaja** (11 FA con LEVE 47/60, frente a 14 FA de la regla). La mejora viene principalmente de
combinar la firma direccional con el aumento de la corriente de secuencia positiva.

## Interpretación y cautelas
1. Físicamente tiene sentido: una falla entre espiras disipa energía en las espiras cortocircuitadas,
   y eso aumenta la potencia y |I1|. Un pico de ruido en P sin aumento de |I1| es probablemente ruido.
2. En el banco, la magnitud de ese aumento la fija la resistencia limitadora externa de 5 Ω. En un
   motor real con falla franca puede ser distinta. **Es un rasgo dependiente del banco.**
3. Un aumento de carga también sube |I1|. Los escalones de carga en caliente no se pudieron probar, y
   podrían generar falsas alarmas nuevas con el modelo. Hay que probarlo antes de usarlo.
4. Todos los positivos son al 75 %, y los puntos de operación se eligieron sobre los mismos datos
   (declarado).
5. Para afirmar la mejora hace falta una validación ciega nueva: más horas de motor sano, otras cargas
   y escalones de carga. El modelo se podría correr en la PC sin tocar el firmware.

## Exploración aproximada a otras cargas (12-oct; NO declarada, orientativa)
Script: `~/exploracion_rf_cargas_pares.py`.
- **Datos:** pulsos del dataset multiclase a 0/25/50/75 %. Esos registros no son continuos, así que la
  referencia es el bloque sano previo al pulso, en lugar de la mediana de 6–11 s.
- **Modelo:** el RF, entrenado con los 13 grupos (fallas solo al 75 %).
- **Comparación:** la regla se evalúa sobre las mismas características aproximadas.

| Sesión | Regla P ≥ 0.40 ×3 | RF p ≥ 0.55 ×3 | ΔI1 mediano |
|---|---|---|---|
| LEVE 0 % | 50/50 | **17/50 (34 %)** | +0.00 % |
| LEVE 25 % | 50/51 | **39/51 (76 %)** | +0.15 % |
| LEVE 50 % | 51/51 | 51/51 | +0.35 % |
| LEVE 75 % | 48/50 | 49/50 | +0.38 % |
| INTER 0–75 % | 100 % | 100 % | +0.75 a +1.73 % |
| SEVERA 0–75 % | 91–100 % | 91–100 % (igual que la regla) | +1.97 a +4.49 % |

**Nota del 14-oct:** 17/50 con scikit-learn 1.7.2 (Python del sistema, el del estudio 1); 24/50 con 1.9.0 (venv). El atajo se mantiene; la magnitud depende de la versión. Lo reemplaza el estudio 2 declarado (`PROTOCOLO_GENERALIZACION_CARGA.md`). LEVE 25 %: 39/51 con 1.7.2 y 42/51 con 1.9.0; la regla da lo mismo en los dos entornos.

**Conclusión:**
- El RF aprendió un atajo que depende de la carga: "durante la falla sube |I1|". A baja carga eso no
  ocurre, porque la corriente de la falla se suma en cuadratura con la corriente magnetizante. Por eso
  **pierde 2 de cada 3 fallas LEVE en vacío**, que la regla física sí detecta.
- La reducción de falsas alarmas del RF no se puede aprovechar con este modelo.

**Cautela:** las tasas absolutas de la aproximación son optimistas. La referencia de un solo bloque es
distinta, y la captura filtraba pares por calidad. La comparación entre la regla y el RF sí es justa,
porque usan las mismas características.

**Trabajo futuro:**
- Entrenar con fallas a todas las cargas, con captura continua.
- Usar características invariantes a la carga, por ejemplo el cambio de potencia activa (requiere enviar
  el fasor complejo de I1 en la telemetría).
