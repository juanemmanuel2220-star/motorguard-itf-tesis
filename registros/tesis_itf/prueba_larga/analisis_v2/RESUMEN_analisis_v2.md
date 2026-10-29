# Análisis fuera de línea: compensación con V2 (12-oct-2026)

**Tipo:** post hoc, exploratorio. Firmware 299a943 sin cambios; solo se leen los `_serial.log`.
Script: `~/analisis_compensacion_v2.py`. Resultado completo: `resultado_compensacion_v2.json`.

## Pregunta
¿Las falsas alarmas de la prueba larga sin falla (90 min, 11 eventos) se deben a cambios del
desbalance de voltaje de la red, y desaparecen si se resta la corriente de secuencia negativa que
el motor sano toma por ese desbalance (R2c = R2 − Y2·V2)?

## Verificación del port del detector
El detector de `detector_dir.cpp` se replicó en Python y se corrió sobre los mismos logs:
- Prueba larga: la proyección P difiere del firmware en una mediana de 0.0002–0.0003 pp, y el estado
  de alarma C coincide en el 99.6–100 % de los bloques.
- Validaciones en vivo: el replay reproduce los TP/FN/FP reportados en su momento en las 7 sesiones.
- Diferencia esperada: en el tramo de 25 % el replay no reproduce la alarma de 13:19:47, porque arranca
  sin el historial que el firmware ya tenía tras el `r` de 13:19:01. Por eso el replay da 10 eventos, no 11.

## Resultados
**Ajuste de Y2** (cambios ΔR2 frente a ΔV2, contra la misma referencia móvil del detector):
Y2 = −0.0075 − j0.0049 A/V (|Y2| = 0.009 A/V). **V2 explica solo el 3.9 % de la varianza de la
firma** (R² = 0.04; con validación cruzada por tramo: R² entre −0.03 y 0.05).

**Falsas alarmas** (Y2 estimado dejando fuera el tramo evaluado):

| Tramo | Firmware (replay) | Compensado con V2 |
|---|---|---|
| 25 % | 1 (972.6 s) | 1 (972.6 s) |
| 50 % | 2 | 3 |
| 75 % | 4 | 3 (una de 75.4 s) |
| 0 % | 3 | 3 (dos de 54 y 215 s) |
| **Total** | **10 (6.7/h)** | **10 (6.7/h)** |

**Validaciones con falla real** (75 %, Y2 de los 4 tramos):
- SEVERA: sin cambios (10/10 y 2/2, todas SEVERA).
- INTER 09-oct 15:13: los TP no cambian (10/10), pero **los FP suben de 0 a 4**.
- LEVE 09-oct 15:46: **los TP bajan de 2 a 1**.

**Bloques que suman racha (P ≥ 0.40 pp) frente a todos los bloques:**

| Variable | Percentil |
|---|---|
| \|ΔV2\| | 48 (igual que cualquier bloque) |
| \|ΔV1\| | 57 |
| \|ΔI1\| | 63 |

## Conclusión
1. **La compensación lineal con V2 no reduce las falsas alarmas** y empeora la especificidad de INTER
   y la sensibilidad de LEVE. **No se recomienda.**
2. **La hipótesis "las falsas alarmas se deben al desbalance de voltaje de la red" no se sostiene**:
   los bloques que suman racha no tienen cambios de V2 mayores que los demás. La coincidencia que se
   observó en vivo con las subidas de U2V (tramos de 25 % y 50 %) fue de casos aislados, no un patrón.
   Hay una asociación débil con cambios de magnitud del voltaje y de la carga (|ΔV1|, |ΔI1|).
3. **Mecanismo que sí explican los datos:**
   - La proyección del motor sano tiene una desviación de 0.256 pp, así que el umbral de 0.40 pp
     queda a ~1.6 σ. El 4.8 % de los bloques lo pasa.
   - La proyección está **correlacionada entre bloques consecutivos** (autocorrelación 0.53 a 1
     bloque, 0.21 a 2). Hay dos causas posibles: los bloques vecinos comparten casi toda la
     referencia móvil, y las fluctuaciones del motor sano duran varios segundos. No se separó cuánto
     aporta cada una.
   - Si los bloques fueran independientes, la persistencia de 3 dejaría ~0.35 eventos en 90 min;
     con la correlación se observan 10–11.
4. **Trabajo futuro con evidencia:**
   - Subir el umbral o la persistencia (la validación al 75 % mostró firmas LEVE de ~0.65 pp, así que
     el margen es estrecho).
   - Usar una referencia que no comparta bloques con la evaluación.
   - Promediar más bloques.

   Todo requiere repetir la validación ciega; no se modifica el firmware antes de entregar.
