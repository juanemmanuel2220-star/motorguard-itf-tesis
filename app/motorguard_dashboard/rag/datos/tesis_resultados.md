# Resultados validados de la tesis MotorGuard-ITF (extracto para el asistente)

Extracto de la tesis "Detección de Fallas de Cortocircuito en Devanados de Motores de Inducción mediante Análisis de Firma de Corriente (MCSA) e Inteligencia Artificial" (Juan Emmanuel Luna Velázquez, UASLP-UAMRA, octubre de 2026). Resume qué significa una alarma del detector, cómo se validó y sus limitaciones. Las cifras salen de `~/Documents/TESIS/redaccion/resultados_oct_2026.md` (revisado el 16-oct-2026), de `~/tesis_itf/prueba_larga/` (12, 15 y 16-oct-2026) y de `~/tesis_itf/validacion_ciega2/` (15 y 16-oct-2026). Este extracto no contiene procedimientos de mantenimiento: esos están en los manuales y guías del fabricante y de mantenimiento.

## 1. Sistema y alcance

- Motor de inducción trifásico ABB M1AA 145T-D4: 1.5 kW (2 HP), 220 V en estrella (127 V de fase), 5.8 A nominales, 60 Hz. Carga: generador Baldor con bancos de resistencias (0, 25, 50 y 75 %).
- Falla estudiada: cortocircuito entre espiras del devanado del estator, provocado de forma controlada en la fase C a través de taps del devanado, con una resistencia limitadora de 5 Ω y un relé de estado sólido (SSR).
- Severidades definidas por los taps de la fase C: LEVE ≈ 7.0 % de las espiras de la fase (corriente del lazo de falla ≈ 1.7 A), INTER ≈ 14.3 % (3.3–3.7 A) y SEVERA ≈ 21.6 % (4.8–5.2 A).
- Alcance: un solo motor y un solo banco de pruebas; la validación en vivo con fallas se hizo al 0, 25 y 75 % de carga (al 50 % solo hay pruebas con el motor sano). Los resultados no se han verificado en otros motores, otras potencias ni en motores alimentados por variador de frecuencia.

## 2. Qué mide el detector (firma de secuencia negativa)

- El detector usa la corriente de secuencia negativa que no explica el desbalance de voltaje de la red (residuo R2), normalizada por la corriente de secuencia positiva |I1|. La firma se expresa en puntos porcentuales (pp) de |I1|.
- Un cortocircuito entre espiras desplaza la firma en una dirección estable: las medianas medidas van de −75.9° a −85.1° en las tres severidades y las cuatro cargas. El detector usa la dirección −81.4°.
- La magnitud de la firma crece con la severidad y baja con la carga. Medianas de 0 a 75 % de carga: LEVE 0.95 → 0.65 pp; INTER 3.71 → 2.14 pp; SEVERA 7.10 → 5.21 pp. En el conjunto de datos, las clases no se traslapan en ninguna carga.

## 3. Cuándo se confirma una alarma y qué significa la severidad

- Cada bloque de medición dura 1.70 s (4096 muestras). El detector proyecta el cambio de la firma (contra una referencia móvil de los bloques entre 11 y 6 s antes) sobre la dirección de falla.
- Umbral: 0.40 pp. La alarma se confirma cuando 3 bloques consecutivos superan el umbral (unos 5 s).
- Al confirmar, se congela la referencia previa a la falla (enclavamiento). La alarma se libera cuando la proyección contra esa base congelada cae por debajo de max(0.20 pp; 0.35 × proyección de confirmación) durante 3 bloques.
- La severidad embebida se calcula con la magnitud de la firma (ML) frente a dos umbrales: LEVE si ML < 1.626 pp; INTER si 1.626 ≤ ML < 4.471 pp; SEVERA si ML ≥ 4.471 pp. Mientras la alarma sigue enclavada, la severidad solo puede escalar.
- La severidad indica el tamaño relativo de la firma (qué tanto se parece a los casos LEVE, INTER o SEVERA del banco), no el número real de espiras dañadas en un motor distinto.
- La firma crece con la corriente que circula por las espiras en cortocircuito, no solo con el número de espiras. En el banco, cuando el lazo de falla condujo más corriente que en el conjunto de datos, la severidad reportada subió un nivel: al 0 % de carga, 4 de 9 fallas INTER se reportaron como SEVERA. La severidad es una indicación de orden de magnitud, no una medida exacta.

## 4. Validación del clasificador de severidad

- Conjunto de datos: 597 pares sano/falla (200 LEVE, 200 INTER, 197 SEVERA) en las cuatro cargas.
- Validación dejando una carga fuera: 596 de 597 pares clasificados correctamente (exactitud 0.998; IC95 0.991–1.000). Único error: un par INTER al 0 % de carga con 4.28 pp, clasificado como SEVERA.
- Limitación: cada severidad se capturó en un día distinto, por lo que la clase está confundida con la sesión de captura (la repetición en otra sesión solo descarta ese efecto para LEVE).

## 5. Validación ciega en vivo con el firmware final (0, 25 y 75 % de carga)

- SEVERA (08-oct-2026): 10 de 10 fallas reales detectadas, 10 de 10 pruebas simuladas sin alarma, severidad correcta 10 de 10, enclavamiento 10 de 10 y liberación en 5.1–6.1 s.
- INTER (09-oct-2026): 10 de 10 fallas reales detectadas, 10 de 10 simuladas sin alarma, severidad correcta 10 de 10, enclavamiento 10 de 10 y liberación en 5.1–6.1 s.
- LEVE: la detección está validada con versiones anteriores del detector (19 de 20 y 9 de 10 fallas reales detectadas; 20 de 20 y 10 de 10 simuladas sin alarma). Al 75 % falta un bloque LEVE completo con el firmware final, por fallas del lazo de inyección, no del detector.
- Cargas ligeras (15-oct-2026), con el firmware final: LEVE al 0 % 20 de 20 fallas reales detectadas y LEVE al 25 % 20 de 20; INTER al 0 % 9 de 10 (la que faltó fue un pulso en el que el lazo de falla no condujo) e INTER al 25 % 10 de 10. Al 25 % no hubo alarmas en las pruebas simuladas y la severidad fue correcta en todas (20 de 20 LEVE y 10 de 10 INTER).
- Al 0 % hubo 3 alarmas en 20 pruebas simuladas y 7 fallas LEVE reportadas como INTER. Todas se debieron a un mismo escalón espontáneo de corriente con el motor sano, que dejó una alarma enclavada (ver §7).

## 6. Falsas alarmas en operación continua sin falla (prueba larga)

- Prueba del 12-oct-2026: 90 minutos con el motor sano (4 tramos de 22.5 min a 25, 50, 75 y 0 % de carga), sin inyección de falla.
- Resultado: 11 falsas alarmas, es decir, 7.3 por hora (intervalo de confianza del 95 %: 3.7 a 13.1 por hora). El criterio declarado (como máximo 1 falsa alarma por hora) NO se cumplió.
- Segunda medición (15 y 16-oct-2026, firmware final): 4.9 horas de operación sin falla (60 min con el motor sano en cada carga, más los periodos sin pulso de las sesiones con falla), con 20 falsas alarmas: 4.1 por hora (intervalo de confianza del 95 %: 2.5 a 6.3 por hora). Tampoco cumple el criterio. Por carga, con el motor sano: 1 al 25 %, 0 al 50 %, 5 al 75 % y 12 al 0 % (en vacío), en 60 min cada una.
- En las dos mediciones casi todas fueron alarmas LEVE y la mayoría se liberaron solas en menos de 20 s. El 12-oct, una alarma quedó enclavada 972.6 s, hasta el final del tramo, y escaló a INTER; otra duró 63.3 s y se liberó con un reinicio manual del detector.
- Causa analizada: la proyección del motor sano tiene una desviación estándar de 0.256 pp, así que el umbral de 0.40 pp queda a unas 1.6 desviaciones, y los bloques consecutivos están correlacionados. El análisis descartó que se deban principalmente al desbalance de voltaje de la red.
- Consecuencia práctica: una alarma LEVE breve que se libera sola es compatible con una falsa alarma del motor sano. Una alarma INTER o SEVERA, o una alarma que persiste, tiene más peso, pero el detector es una herramienta de vigilancia: la condición del aislamiento debe confirmarse con las pruebas que indican los documentos de mantenimiento.

## 7. Otras limitaciones conocidas

- Falsa alarma al arrancar: con el motor recién encendido puede confirmarse una alarma LEVE. Medida operativa usada en la tesis: esperar unos 5 minutos después del arranque antes de interpretar las alarmas (el firmware tiene 60 s de calentamiento).
- Alarma enclavada ante un escalón del motor sano: un cambio sano y persistente en la dirección de falla puede dejar una alarma enclavada que no se libera sola; se libera con un reinicio manual. En el banco se observaron escalones espontáneos de corriente de alrededor de 2 % en una fase con el motor sano. Mientras la alarma sigue enclavada, una falla real que llegue después se suma a esa base y puede reportarse con una severidad mayor. En las pruebas largas, las alarmas que siguieron enclavadas más de 60 s se reiniciaron (6 de 31 falsas alarmas en las dos mediciones).
- Los cambios de carga en caliente no se evaluaron, porque el banco no permite cambiar la carga con el motor girando.
- El sistema es un apoyo para el mantenimiento basado en condición; no sustituye las pruebas eléctricas fuera de línea ni el criterio del personal calificado.
