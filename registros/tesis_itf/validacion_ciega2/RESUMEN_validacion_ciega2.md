# Resumen: validación ciega 2 (regla de Fortescue frente al RF congelado)

- **Protocolo:** `~/PROTOCOLO_VALIDACION_CIEGA_2.md`, declarado en `54ecef3` (14-oct) con la enmienda 1 en `769cce9` (15-oct, antes del tramo del 0 %).
- **Análisis:** `/usr/bin/python3 ~/analisis_validacion_ciega2.py` (scikit-learn 1.7.2), corrido el 16-oct a las 13:17, tras terminar el último registro. Hashes del RF y de la variante verificados por el script.
- **Salida:** `resultado_validacion_ciega2_20261015_20261016.json`.
- **Bitácoras:** `bitacora_20261015.md` y `bitacora_20261016.md`.
- **Exclusiones:** ninguna (todas las lecturas de la pinza por encima de los umbrales; no hay `exclusiones.json`).

## Datos
- **Sesiones con falla (15-oct, en vivo, decisión del firmware):** LEVE 0 % (20 pulsos), INTER 0 % (10), LEVE 25 % (20) e INTER 25 % (10).
- **Motor sano, lazo desconectado, 60 min cada uno:** 25 %, 50 % y 75 % (15-oct), y 0 % (16-oct).
- **Exposición sana total:** 4.906 h (tramos de motor sano más los periodos sin pulso de las sesiones con falla).

## Resultados primarios (declarados)

### H1: falsas alarmas — CONFIRMADA
| Detector | FA | FA/h | IC 95 % |
|---|---|---|---|
| Regla, lógica del estudio 1 (P ≥ 0.40 pp, k = 3) | 21 | 4.28 | 2.65–6.54 |
| **RF congelado** (s = 0.55, k = 3) | **2** | **0.41** | 0.05–1.47 |

Prueba condicional exacta, binomial(2; 23; 0.5), unilateral: **p = 3.3 × 10⁻⁵ < 0.05.**

### H2: detección LEVE a baja carga — el RF PIERDE
| Carga | n | Regla | RF | Solo regla | Solo RF | McNemar exacto (bilateral) |
|---|---|---|---|---|---|---|
| 0 % | 20 | 20 | **4** | 16 | 0 | p = 3.1 × 10⁻⁵ |
| 25 % | 20 | 20 | **1** | 19 | 0 | p = 3.8 × 10⁻⁶ |

### Lectura según la tabla de interpretación fijada
**"H1 sí y H2 con pérdida del RF": el RF mejora la especificidad, pero no generaliza a baja carga; se confirma el atajo.**
- El RF entrenado solo con fallas al 75 % casi no detecta LEVE al 0 y 25 % en operación continua (5/40), mientras la regla detecta 40/40.
- Esto reproduce, con datos nuevos, ciegos y declarados, la caída que la exploración del 12-oct (no declarada) había sugerido (17/50) y que el estudio 2 por pares no reprodujo.
- Para la tesis: la regla de Fortescue sigue siendo el detector; el RF no es candidato para la detección en el firmware ni como segunda opinión sin reentrenar con fallas a varias cargas.

## Resultados secundarios (descriptivos)

### Detección por clase y carga (pulsos reales)
| Sesión | n | Regla | RF | Regla completa (enclavamiento) | Variante ángulo ≤ 35° + LEVE 4 bloques |
|---|---|---|---|---|---|
| LEVE 0 % | 20 | 20 | 4 | 12 | 20 |
| LEVE 25 % | 20 | 20 | 1 | 20 | 20 |
| INTER 0 % | 10 | 8 | 8 | 8 | 9 |
| INTER 25 % | 10 | 10 | 9 | 10 | 10 |

- La regla completa pierde 8 pulsos LEVE al 0 % porque la alarma quedó enclavada desde el escalón de IA de las 11:59:38 (en el replay no hay `r`).
- INTER 0 %: uno de los pulsos no condujo (prueba 12, ver bitácora del 15-oct).

### Falsas alarmas por tramo
| Registro | Regla | RF | Regla completa | Variante | Firmware en vivo |
|---|---|---|---|---|---|
| LEVE 0 % (periodos sin pulso) | 1 | 1 | 1 | 0 | 1 |
| INTER 0 % | 1 | 0 | 1 | 0 | 1 |
| LEVE 25 % | 0 | 0 | 0 | 0 | 0 |
| INTER 25 % | 0 | 0 | 0 | 0 | 0 |
| Sano 25 % | 1 | 0 | 1 | 0 | 1 |
| Sano 50 % | 0 | 0 | 0 | 0 | 0 |
| Sano 75 % | 5 | 0 | 5 | 3 | 5 |
| **Sano 0 % (16-oct)** | **13** | 1 | 3 | 4 | **12** |
| **Total (4.906 h)** | **21** | **2** | **11** | **7** | **20** |

| Detector | FA/h | IC 95 % |
|---|---|---|
| Regla completa | 2.24 | 1.12–4.01 |
| Variante de ángulo | 1.43 | 0.57–2.94 |
| Firmware en vivo (con `r`) | 4.08 | 2.49–6.30 |

- **Observación (no declarada):** 13 de las 21 FA de la regla salen del tramo sano al 0 %. Ahí P oscila entre −0.8 y +1.3 pp. Es la misma carga donde el RF casi no detecta LEVE, así que buena parte de su ventaja en H1 es la otra cara de su insensibilidad a baja carga: no es una reducción de FA "gratis". Sin el tramo del 0 %, la regla da 8 FA y el RF 1.
- **Regla completa frente al firmware al 0 %:** 3 frente a 12, porque en el replay sin `r` la alarma queda enclavada y no se cuentan inicios nuevos; en vivo, el `r` automático la rearma.
- **Variante de ángulo** (elegida post hoc el 13-oct, validada aquí por primera vez): 7 FA frente a 11 de la regla completa, con la misma detección o mejor (LEVE 40/40, INTER 19/20). Los IC se traslapan; es un indicio, no una confirmación.
- **Criterio del firmware ≤ 1 FA/h:** no se cumple (4.08/h; con el 12-oct, también 7.3/h). Las FA se concentran al 0 % (12/h) y al 75 % (5/h); al 25–50 % hay 1 en 2 h.

### Decisión del firmware en vivo (primera validación fuera del 75 %)
| Sesión | TP | FN | FP | TN |
|---|---|---|---|---|
| LEVE 0 % | 20 | 0 | 3 | 17 |
| INTER 0 % | 9 | 1 | 0 | 10 |
| LEVE 25 % | 20 | 0 | 0 | 20 |
| INTER 25 % | 10 | 0 | 0 | 10 |

- **Severidad:** LEVE 0 % 13/20 (las 7 INTER salen del escalón de las 11:59:38); INTER 0 % 5 INTER y 4 SEVERA; LEVE 25 % 20/20; INTER 25 % 10/10.
- **Alarmas atascadas (> 60 s, reinicio con `r`):** 1 al 75 % (15-oct) y 4 al 0 % (16-oct).

## Limitaciones
- Un solo motor, falla limitada con 5 Ω, fase C; dos días de captura.
- La corriente del lazo fue mayor que en el dataset (LEVE 1.7–2.0 A; INTER 3.7–4.4 A).
- El RF y su punto de operación vienen del estudio 1 (datos del 75 %); la variante de ángulo se eligió post hoc.
- El análisis por tramo y la observación sobre el 0 % son descriptivos, no declarados.
