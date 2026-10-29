# Validación ciega 2: regla de Fortescue frente al Random Forest congelado (declarado 14-oct-2026)

**Tipo:** validación ciega con datos NUEVOS del banco (15-oct-2026), declarada antes de capturarlos.
- **El firmware 299a943 no se modifica:** el RF y la variante se evalúan fuera de línea sobre los registros.
- **Modelos congelados el 14-oct** en `~/tesis_itf/validacion_ciega2/modelos/`, todos en este commit:
  - RF: `rf_estudio1_13grupos.joblib`, SHA-256 `302d9d9a…db246`;
  - variante: `variante_angulo35_leve4.py`, SHA-256 `a99f8448…dfd2f`.
- **Análisis:** `~/analisis_validacion_ciega2.py`, con `/usr/bin/python3` (scikit-learn 1.7.2, la misma versión del estudio 1 y del estudio 2). Verifica los hashes antes de correr.
- **Salida:** `~/tesis_itf/validacion_ciega2/`.

## Por qué
1. **Estudio 1** (`459bee9`, 13 grupos al 75 %): el RF dio 5 FA frente a 14 de la regla, con IC traslapados (criterio no cumplido). En una prueba condicional exacta post hoc, p = 0.032 unilateral, con el punto de operación elegido sobre los mismos datos.
2. **Exploración del 12-oct** (no declarada, aproximada): el RF detectó LEVE 0 % 17/50 frente a 50/50 de la regla.
3. **Estudio 2** (`61c09f1`, por pares): no reprodujo esa caída.

**Quedan dos preguntas** que solo responden datos nuevos, ciegos y continuos:
- ¿la reducción de falsas alarmas es real?
- ¿el RF entrenado con fallas solo al 75 % detecta LEVE a baja carga en operación continua?

## Detectores (los mismos registros para todos)
- **Regla de Fortescue, lógica del estudio 1:** P ≥ 0.40 pp durante 3 bloques, con `comparacion_ml_deteccion.eventos`. Comparador primario.
- **RF congelado:**
  - probabilidad ≥ 0.55 durante 3 bloques, con la misma lógica de eventos;
  - entrenado con los 13 grupos del estudio 1 (6300 bloques, 463 con falla, todas al 75 %);
  - mismas características: P, Q, |Δz|, ΔI1, ΔV1, |ΔV2| × 5 rezagos y dispersión de 30 s.
- **Secundarios:**
  - regla con el detector completo (enclavamiento, replay sin `r`);
  - variante congelada "ángulo ≤ 35° + LEVE en 4 bloques" (elegida post hoc el 13-oct; aquí se valida por primera vez);
  - decisión del propio firmware: el campo C y los `_resumen.json` del script en vivo.

## Datos nuevos (15-oct; scripts existentes, sin modificarlos)
**Fallas en registro continuo:**
- `~/validacion_vivo_direccional.py --decision firmware --t-pulso 11.2` en estas sesiones:
  - LEVE al 0 % (`--pruebas 40`, 20 reales);
  - INTER al 0 % (`--pruebas 20`);
  - LEVE al 25 % (`--pruebas 40`);
  - INTER al 25 % (`--pruebas 20`).
- Plan aleatorio y semilla del propio script.
- La carga y los taps solo se cambian con el motor apagado y la alimentación cortada. Se esperan 5 min después de encender.

**Motor sano:**
- `~/prueba_larga_sin_falla.py --minutos 60` al 25, 50, 75 y 0 %, con el **lazo de inyección desconectado**;
- `~/reinicio_alarma_atascada.py` en paralelo (regla del 12-oct: `r` si C = 1 más de 60 s). El `r` solo afecta la decisión del firmware, no los fasores que usa este análisis.

**Orden:** LEVE 0 % → INTER 0 % → LEVE 25 % → INTER 25 % → motor sano 25 / 50 / 75 / 0 %. Si falta tiempo, se recorta primero el motor sano de 50 y 75 %.

**Pinza:** corriente del lazo al inicio, a la mitad y al final de cada sesión con falla, registrada en `~/tesis_itf/validacion_ciega2/pinza_20261015.csv`.

**Pulso de prueba aislado antes de cada sesión con falla** (lección del 09-oct, cuando unos taps mal conectados dieron 1.3 A sin firma):
- se hace con la app MotorGuard-ITF (panel de inyección) o como se hizo el 09-oct, y luego se cierra la app (un solo programa en el puerto);
- se registran la pinza y que la TFT o la app confirmen la clase esperada;
- si no la confirman, se revisan los taps antes de empezar;
- estos pulsos no forman parte del análisis.

**Todo registro nuevo se usa.** Única exclusión permitida, fijada aquí:
- una sesión con alguna lectura de la pinza por debajo de 1.5 A en LEVE (normal: 1.7 A) o de 3.0 A en INTER (normal: 3.3–3.7 A; degradado: 3.1 A el 07-oct), por falla del lazo;
- se anota con su motivo en `exclusiones.json` antes de correr el análisis.

Las sesiones incompletas se usan y se reportan.

## Definiciones (las de `PROTOCOLO_COMPARACION_ML.md`)
- **Etiquetas por bloque:**
  - falla: t_on + 1 s a t_off;
  - excluido: t_on a t_on + 1 s, y t_off a t_off + 12 s;
  - sano: el resto.
- **Inicio de alarma:** k bloques seguidos sobre el umbral; una nueva requiere ≥ 3 bloques apagada.
- **Detección:** un inicio entre t_on y t_off + 2 s.
- **Falsa alarma:** un inicio en un bloque sano.
- **Exposición:** la suma del tiempo de los bloques sanos.

## Hipótesis y criterios (fijados antes de capturar)
- **H1, falsas alarmas.** En toda la exposición sana nueva (bloques de motor sano más los periodos sin pulso de las sesiones con falla), el RF congelado tiene menos falsas alarmas que la regla.
  - Prueba condicional exacta para dos conteos con la misma exposición: binomial(k_RF; k_RF + k_regla; 0.5), **unilateral, α = 0.05**.
  - Se reportan FA/h con IC de Poisson para todos los detectores.
- **H2, generalización.** Detección LEVE a 0 % y a 25 %: RF frente a regla sobre los mismos pulsos reales.
  - McNemar exacto, **bilateral, α = 0.05**, por carga.
  - La hipótesis previa (12-oct) es RF < regla; se reporta en cualquier dirección.
- **Secundarias** (descriptivas):
  - INTER a 0 y 25 %;
  - variante de ángulo (FA y detección);
  - decisión del firmware en vivo a 0 y 25 % (TP/FN/FP/TN, severidad correcta, enclavamiento, liberación), que es la primera validación en vivo del firmware final fuera del 75 %;
  - alarmas atascadas;
  - retardo.

## Interpretación fijada
| Resultado | Lectura |
|---|---|
| H1 sí y H2 sin pérdida del RF | El RF de Fortescue mejora la especificidad y generaliza: es candidato fuerte para la detección (segunda opinión en la app o firmware v2) |
| H1 sí y H2 con pérdida del RF | Mejora la especificidad, pero no generaliza a baja carga: se confirma el atajo |
| H1 no | Con estos datos, no se demuestra que el RF reduzca las falsas alarmas |

## Limitaciones declaradas
- Un solo motor; falla limitada con 5 Ω; fase C.
- Un solo día de capturas.
- El RF y el punto de operación vienen del estudio 1, elegidos con datos del 75 %.
- La variante de ángulo se eligió post hoc el 13-oct sobre los datos del estudio 1.

## Enmienda 1 (15-oct-2026, 17:35, antes de capturar el tramo del 0 %)
- **Datos del 15-oct** (todos se usan):
  - sesiones con falla: LEVE 0 %, INTER 0 %, LEVE 25 % e INTER 25 %;
  - motor sano: 25 %, 50 % y 75 %, de 60 min cada uno.
- **El tramo de motor sano al 0 %** no alcanzó el 15-oct y se captura el **16-oct** con el mismo procedimiento: lazo desconectado, `prueba_larga_sin_falla.py --minutos 60`, `reinicio_alarma_atascada.py` y 5 min de calentamiento.
- **El análisis usa los registros de ambas fechas.** `analisis_validacion_ciega2.py` acepta ahora varias fechas (`--fecha 20261015 20261016`, por defecto). Solo cambia la búsqueda de archivos, no la lógica: el ensayo en seco con el 12-oct da los mismos conteos.
- **Incidencias del 15-oct** (detalle en `~/tesis_itf/validacion_ciega2/bitacora_20261015.md`):
  - escalón de IA a las 11:59:38 en la sesión LEVE 0 %, que dejó una alarma enclavada;
  - un pulso sin conducción del lazo en INTER 0 % (prueba 12);
  - suspensión de la laptop de 15:11 a 15:16 (hueco de 257 s en el motor sano al 50 %);
  - un primer encendido "al 75 %" con las resistencias en serie, corregido antes de capturar.
  
  Ninguna cumple el criterio de exclusión: todas las lecturas de la pinza están por encima de los umbrales.
