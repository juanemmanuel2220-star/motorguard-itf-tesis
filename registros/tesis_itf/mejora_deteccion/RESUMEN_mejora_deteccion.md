# Ruido de la firma y variantes del detector (13-oct-2026)

- Protocolo declarado antes de correr: `~/PROTOCOLO_MEJORA_DETECCION.md` (commit `0518dd4`).
- Script: `~/analisis_mejora_deteccion.py`. Detalle: `resultado_mejora_deteccion.json`, `salida_consola.txt`.
- Exploración **post hoc** (no declarada; posterior a ver los resultados): `explora_post_hoc.py`,
  `explora_post_hoc2.py` y `pares_ang.py`. Salida en `exploracion_post_hoc_consola.txt`.
  `explora_post_hoc2.py` se recortó entre corridas; la consola guarda las dos salidas.

## 0. Fidelidad del simulador
- El simulador generalizado, configurado como el firmware, coincide al 100 % (C y SEV, bloque a bloque)
  con el port de `analisis_compensacion_v2.py`.
- El port reproduce 10 de los 11 eventos registrados en la prueba larga (C coincide 99.6 % en el tramo
  de 25 %; ya se sabía).
- **Sin reinicios `r`**, la regla del firmware (A) da en los 13 grupos:
  - **12 FA en 2.78 h (4.3/h, IC 2.2–7.5)**;
  - LEVE 47/60, INTER 20/22, SEVERA 12/12;
  - severidad correcta en todas las detecciones.

  El estudio de ML daba 14 FA porque usaba una lógica de eventos sin enclavamiento.

## 1. Naturaleza del ruido (declarado)
Desviación de Allan de zP, la proyección de R2/|I1| sobre −81.4°, con motor sano y carga constante:

| τ (s) | 1.7 | 3.4 | 6.8 | 13.6 | 27.2 | 54.4 | 108.8 | 217.6 |
|---|---|---|---|---|---|---|---|---|
| 25 % | 0.179 | 0.172 | 0.137 | 0.115 | 0.081 | 0.065 | 0.067 | 0.083 |
| 50 % | 0.141 | 0.139 | 0.118 | 0.098 | 0.089 | 0.075 | 0.066 | 0.069 |
| 75 % | 0.159 | 0.145 | 0.123 | 0.110 | 0.097 | 0.078 | 0.081 | 0.109 |
| 0 % | 0.156 | 0.152 | 0.124 | 0.115 | 0.130 | 0.171 | 0.229 | 0.281 |

**Lectura con la regla declarada:**
- Primera octava (1.7 → 3.4 s): pendiente ≈ 0 (−0.02 a −0.13). **Promediar 2 bloques no reduce el
  ruido:** los bloques vecinos están correlacionados (lag 1 = 0.53).
- De 3.4 a ~50 s: pendiente media ≈ −0.25, entre ruido blanco (−0.5) y de parpadeo (0). Promediar
  ayuda, pero poco: de 1.7 a 54 s el ruido baja ×2.3, cuando con ruido blanco bajaría ×5.7.
- Más allá de ~50–100 s, deriva (pendiente positiva). Al 0 % la deriva aparece ya desde ~14 s.

**Referencia más larga** (σ de P con motor sano):

| Referencia | σ de P | Bloques con P ≥ 0.40 | Autocorrelación lag 1 |
|---|---|---|---|
| 11 s | 0.256 | 4.7 % | 0.53 |
| 20 s | 0.238 | 4.0 % | 0.55 |
| 30 s | 0.233 | 3.7 % | 0.53 |
| 60 s | 0.237 | 3.3 % | 0.52 |

Solo baja ~9 %, y la autocorrelación no cambia.

**Conclusión:** el ruido no es blanco. Por eso, promediar o alargar la referencia da mejoras pequeñas;
la relación señal/ruido está limitada por fluctuaciones lentas. No se separó si vienen de los sensores,
del motor o de la red. El canal de voltaje (V2/V1) muestra deriva al 50 % desde ~27 s.

## 2. Variantes del detector (declarado)
Rejilla de 1904 configuraciones (referencia, racha / media móvil / CUSUM, compuerta |Q|).
Resultados LOGO **fuera de muestra**:

| Ingredientes permitidos | FA | FA/h | LEVE | INTER | SEVERA | Configuración elegida con los 13 grupos |
|---|---|---|---|---|---|---|
| A (firmware) | 12 | 4.31 | 47 | 20 | 12 | racha 0.40 × 3, ref 11 s |
| (a) umbral y persistencia | 12 | 4.31 | 47 | 20 | 12 | la misma que A |
| (b) + referencia | 10 | 3.59 | 45 | 20 | 12 | racha 0.35 × 4, ref 20 s |
| (c) + compuerta \|Q\| | 11 | 3.95 | 45 | 19 | 12 | racha 0.35 × 4, ref 20 s |
| (d) media móvil | 2 | 0.72 | 48 | 20 | 12 | media de 4 ≥ 0.5, ref 20 s, \|Q\| ≤ 0.3 |
| (e) CUSUM | 9 | 3.23 | 42 | 21 | 12 | CUSUM κ = 0.25, h = 1.0, ref 20 s, \|Q\| ≤ 0.45 |
| (f) todo | **2** | **0.72** | 48 | 20 | 12 | media de 4 ≥ 0.5, ref 20 s, \|Q\| ≤ 0.3 |

- **Ajustar solo el umbral y la persistencia no mejora nada:** el firmware ya está en el óptimo de su
  familia.
- **Criterio formal** (protocolo): c1 (FA ≤ 50 % de A) ✔ y c2 (detecciones ≥ A) ✔. Para c3, la
  verificación por carga se declaró "no realizable", porque la configuración pide 4 bloques y algunos
  pares tienen 3. **Por la letra del protocolo, se recomendaría validar en el banco.**

**PERO la verificación por carga, en los pares que sí tienen ≥ 4 bloques, invalida esa configuración:**

| Pares con ≥ 4 bloques | A | Media de 4 ≥ 0.5 + \|Q\| ≤ 0.3 | Media de 4 ≥ 0.5 sin compuerta |
|---|---|---|---|
| SEVERA 0 % | 42/43 | **23/43** | 42/43 |
| SEVERA 25 % | 44/46 | **36/46** | 45/46 |
| LEVE 75 % | 48/50 | 40/50 | 45/50 |

- **Causa:** la compuerta es **absoluta**. A baja carga, la firma SEVERA está rotada −3.8° y mide
  7 pp, así que |Q| ≈ 0.47 > 0.3 y la compuerta la anula.
- Con la compuerta en A sola es peor todavía: SEVERA 0 % 2/43.
- En el banco no se vio porque todas las fallas en vivo son al 75 %, donde la firma está alineada.
  **Es otro atajo dependiente de la carga, igual que el del RF.**
- **Decisión: no se recomienda validar esa configuración**, aunque cumpla el criterio por la letra. Es
  una desviación del protocolo, declarada aquí: el criterio c3 solo contemplaba pérdidas de LEVE y no
  previó que la compuerta absoluta pudiera anular firmas grandes.

**Complementarios declarados:**
- **Nivel de liberación** (0.20 / 0.30 / 0.40): efecto pequeño. El tiempo en falsa alarma baja de
  429 a 399 s/h, y la alarma atascada de 973 s sigue en los tres casos.
- **Persistencia extra solo para LEVE, sobre A:** +2 bloques → 2 FA y +4 → 0 FA, con INTER 21 y
  SEVERA 12. La detección LEVE no es medible con pulsos de 7–11 s (13/60 y 0/60).

## 3. Exploración post hoc (NO declarada; orientativa)
1. **Compuerta por ángulo** en vez de absoluta: |Q| ≤ tan(θ)·P, que no depende de la magnitud.
   - En los pares, INTER y SEVERA quedan intactos a todas las cargas.
   - θ = 35°: LEVE 25 % 48/51 y 50 % 50/51, frente a 50/51 y 51/51 de A.
   - En vivo: FA 12 → 9 (35°) y 12 → 6 (30°).
2. **La persistencia extra choca con la referencia móvil.** Con la falla presente, la referencia (6–11 s
   atrás) se contamina a los ~8 s, P cae y la racha se rompe. Con pulsos de 11.2 s, la detección LEVE
   cae de 9/10 a 8 (+1), 6 (+2) y 0 (+3). **Una falla LEVE permanente tampoco se confirmaría con +3:**
   solo +1 (4 bloques, ~6.8 s) es seguro.
3. **Congelar la referencia en el primer bloque sospechoso:** peor. Llega a 19 FA y más alarmas
   atascadas, porque un pico de ruido congela una referencia mala.
4. **Mejor combinación encontrada: compuerta de ángulo ≤ 35° + LEVE con 4 bloques.**
   - **3 FA (1.1/h)**, frente a 12;
   - INTER 21/22 y SEVERA 12/12;
   - **LEVE 43/60**, frente a 47;
   - retardo de 6.4 s, frente a 5.4.

   Es post hoc, se eligió mirando estos mismos datos y no tiene LOGO. **Solo es una hipótesis para una
   validación ciega.**

## 4. Conclusiones para la tesis
1. La regla del firmware ya está en el óptimo de su familia (umbral × persistencia). Las mejoras
   requieren otro estadístico o una información adicional.
2. **El ruido de la firma no es blanco** (Allan): promediar y alargar la referencia dan poco. Esto
   cuantifica el límite de la relación señal/ruido del sistema actual, ~0.07–0.08 pp como mejor
   desviación de Allan a ~50–100 s, y justifica la mejora de hardware como trabajo futuro.
3. **La verificación por carga volvió a detectar un atajo.** La configuración que formalmente "ganaba"
   anula SEVERA a baja carga. La lección se repite con el RF: validar solo al 75 % no basta.
4. Hay una mejora plausible y físicamente motivada (dirección por ángulo + persistencia moderada para
   LEVE) que reduciría las FA ~4 veces a costa de ~7 % de detecciones LEVE. Está **pendiente de una
   validación ciega**:
   - captura continua con pulsos a varias cargas;
   - pulsos LEVE ≥ 11 s;
   - ≥ 1.5 h de motor sano.
5. **Estructural (firmware v2 / trabajo futuro):** la referencia móvil de 6–11 s limita cuánto tiempo
   se puede acumular evidencia. Una referencia de dos velocidades, o congelada al confirmar un
   candidato con más contexto, es la vía para persistencias largas sin perder fallas permanentes.
