# Prueba larga sin falla: enmienda al protocolo (12-oct-2026)

Protocolo original: `prueba_larga_sin_falla.py`, commit 9e2968d (10-oct-2026). Firmware 299a943, sin cambios.

## Motivo
En el banco no se puede cambiar la carga del generador Baldor con el motor girando: hay que apagar
el motor para conmutar los bancos de resistencias. Por eso el protocolo original (cambiar la carga en
caliente cada ~10 min) no se puede ejecutar tal como se declaró.

Primer intento, 12-oct 13:03 (`larga_20261012_1303_*`): 8.6 min de exposición al 0 %, 0 falsas
alarmas; se interrumpió al apagar el motor para cambiar la carga. Se conserva y se reporta como
intento interrumpido; no se suma a la prueba enmendada.

## Protocolo enmendado (declarado antes de correrlo)
- Cuatro tramos, uno por carga, en este orden: 25 % → 50 % → 75 % → 0 %.
- En cada tramo: con el motor apagado se ajusta la carga, se enciende el motor y se esperan 5 min
  (calentamiento, no cuenta como exposición). Después se corre, sin modificarlo,
  `python3 ~/prueba_larga_sin_falla.py --minutos 22.5 --nota "<carga>"` hasta que termine solo.
- Exposición total: 4 × 22.5 = 90 min con Motor:ON. El lazo de inyección queda desconectado de los taps.
- Si el motor se apaga a mitad de un tramo, se detiene el script (Ctrl+C), se reporta y se repite
  el tramo completo.

## Regla de alarma atascada (agregada el 12-oct 13:3x, antes del tramo de 50 %)
- Motivo: en el tramo de 25 % (13:26:01) un transitorio de desbalance de la red (U2V 1.15 → 1.35 %
  durante ~8 s) produjo una falsa alarma que quedó enclavada con la base contaminada (PL ≈ 1.0–1.3 pp,
  escaló a INTER). Mientras la alarma está enclavada el detector no puede registrar alarmas nuevas.
- Desde el tramo de 50 %: si una alarma sigue enclavada (C=1) más de 60 s, se registra como alarma
  atascada y se reinicia el detector con `r`, enviado por `reinicio_alarma_atascada.py` (lee el
  `_serial.log` que escribe el script de la prueba y abre el puerto solo para escribir `r`; no envía
  ningún otro comando). El script de la prueba no se modifica: la alarma aparece en su resumen como un
  evento de > 30 s.
- El tramo de 25 % se completa sin intervenir, como estaba declarado. En el análisis se reporta,
  además de la tasa sobre la exposición total, el tiempo con el detector disponible (C=0).

## Métricas
- Falsas alarmas en régimen estable por carga y en total: eventos C 0→1, tasa por hora de exposición
  y límite superior Poisson al 95 % (con 0 eventos: 3/T). Criterio: ≤ 1 falsa alarma por hora.
- Arranques: durante cada calentamiento de 5 min se registra la telemetría (solo lectura del puerto)
  y se reporta si hubo alarma enclavada (C=1) en el arranque. Es dato descriptivo de la limitación
  conocida (falsa alarma al arrancar); no entra en la tasa de régimen estable.
- Si al cumplirse los 5 min la alarma sigue enclavada (C=1), se registra como falsa alarma de arranque
  (hora, severidad, ML/PL) y se reinicia el detector con el comando serie `r` (comando existente del
  firmware; no lo modifica). Se esperan 30 s con C=0 y REF=1 antes de iniciar el tramo.
  (Ocurrió en el primer arranque del tramo de 25 %, 12-oct 13:15, antes de iniciar el tramo.)
- Escalones de carga con el motor en marcha: **no se evalúan** (el banco no lo permite). El criterio
  "0 alarmas por escalones de carga" queda sin medir y se reporta como limitación y trabajo futuro.
  Si el script detecta algún "escalón" (|I1| > 3 %) dentro de un tramo, se analiza como variación de
  la red o del motor, no como cambio de carga.
