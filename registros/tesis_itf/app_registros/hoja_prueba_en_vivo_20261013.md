# Hoja de la prueba en vivo de la app (protocolo `protocolos/prueba_en_vivo_app.md`, declarado el 12-oct)

13-oct-2026. Firmware `299a943`. App 1.0.0, código de la rama `feat/app-escritorio`. Desde las 13:46 se usa el
.deb instalado (`/usr/lib/motorguard-itf`, construido de 00977d0); la sesión de las 13:23 se abrió con la copia del
repositorio (`venv/bin/python …/app.py`, según el proceso). Nota: el Python del sistema carga PySide6 6.11.2 de
`~/.local/lib/python3.14` (instalación con pip del usuario) en lugar del paquete de Ubuntu (6.10.2).
Llenada por Claude Code a partir de los registros y de lo que reporta el autor en el banco.

## Antes de la sesión guiada (el autor operó la app por su cuenta)

- **13:08–13:10** (`sesion_20261013_130805`): motor OFF todo el tiempo; `>> TX 0` al conectar y al cerrar;
  CONECTADO a 1.9 s de abrir; 93 tramas. Cierre normal.
- **13:23** (`sesion_20261013_132326`): se abrió con el motor ya en ON (condición previa del paso 1 no cumplida;
  no es falla de la app). `>> TX 0` al conectar.
- **13:25 — serie de 3 pulsos INTER de 5 s** (equivale al paso 7, hecha fuera del orden del protocolo):

| Pulso | Respuesta del firmware | T_ON (fw) | `0` de la app | Alarma | ML | Liberada en |
|---|---|---|---|---|---|---|
| 1 (13:25:02) | Exito a 0.44 s | 5265 ms | sí | INTER | 4.085 pp | 7.1 s |
| 2 (13:25:28) | Exito a 0.16 s | 5221 ms | sí | INTER | 4.205 pp | 7.1 s |
| 3 (13:25:54) | Exito a 0.01 s | 5087 ms | sí | **SEVERA** | 4.915 pp | 5.2 s |

  - Pausa entre pulsos ≈ 26 s (pedida 20 s): respetada. Los 3 pulsos y las 3 alarmas están en el CSV.
  - Corrientes de fase ≈ 3.4–3.8 A, **0 % de carga** (autor).
  - **Criterio del paso 7 "3 alarmas INTER": NO se cumple** (la tercera se clasificó SEVERA, ML 4.915 > 4.471).
    Es una decisión del firmware que la app registró tal cual. Las ML de 4.1–4.9 pp están por encima de las
    medianas INTER del dataset (3.71 pp a 0 % de carga); la severidad se validó en vivo solo al 75 % de carga.
  - Pinza: **no se midió** (autor). Minutos desde el arranque: "pocos minutos" (autor; el motor pasó a ON entre
    las 13:10:45 y las 13:23:28), posiblemente menos de los 5 min que pide el protocolo antes de inyectar.
  - La SEVERA a 0 % de carga es coherente con el dataset: a 0 % la mediana INTER es 3.71 pp y el único error de la
    validación dejando una carga fuera fue un par INTER al 0 % (4.28 pp) clasificado como SEVERA.
  - El firmware imprime "SSR F1 ACTIVADO (LEVE)" con los taps INTER: es el texto fijo del firmware; no se cambia.

## Pasos del protocolo

| # | Hora | ✓ / ✗ | Observaciones |
|---|---|---|---|
| 1 | 13:46 | ✓ | `>> TX 0` primera línea; CONECTADO a 2.0 s de abrir; chip Motor OFF y "Hace 0 s · 9 tramas" (captura del autor 13-46-44); tramas cada 1.70 s (máx. 1.88 s, n = 27) |
| 2 | 13:49 | ✓ | Aviso "Ya hay una ventana de MotorGuard-ITF usando el Arduino (proceso 224046)" (captura 13-49-49; app.log 13:49:39 WARNING); la segunda no se abrió y la primera siguió recibiendo tramas. Nota: la ventana abierta (PID 224046, 13:48:36) es la copia del repositorio (venv), no el .deb; la del .deb (13:46) se cerró a las 13:48:31 |
| 3 | 14:34 | (1.er intento) | `sesion_20261013_142900`: "Conexión perdida" 14:34:26.2; el cable estuvo fuera ~2–3 s (no 10 s); 1.er intento de reabrir a las 14:34:28.8 falló con `termios.error (5, Input/output error)` en `reset_input_buffer` (el Arduino aún enumerándose) y quedó como **ERROR "Error inesperado" con traza en app.log**; reintento CONECTADO 14:34:31.4 con nuevo `>> TX 0`. Reconexión correcta y sin tocar la app; el ERROR hará fallar el criterio del paso 9. Chip rojo: [PENDIENTE: confirmación del autor] |
| 3 | 14:41 | ✓ (2.º intento) | Desconexión 14:35:39.7 ("Conexión perdida", luego "Esperando el Arduino") durante 6 min 19 s; `/dev/ttyACM0` reapareció 14:41:56 y CONECTADO a las 14:41:58.95 (~3 s) con nuevo `>> TX 0`; **sin ERROR esta vez**. El mismo ERROR del 1.er intento aparece también el 12-oct a las 16:19:04 (reconexión): es recurrente |
| 4 | 14:46 | ✓ | Firmware: "Motor ON: warmup 60s" 14:45:44 → ON 14:46:45 (61 s). Autor: Inyectar bloqueado durante WARMUP con el motivo, chip con minutos encendido y aviso de ~5 min: sí. **Antes, a las 14:44:56, el ESP32 se reinició solo** (kernel: USB disconnect y dos re-enumeraciones; firmware "IA listo" con 00:00:04 a las 14:45:06); el autor no tocó el cable y cree que coincidió con el encendido del motor/generador ("probablemente"). La app se reconectó a las 14:45:05.5 con `>> TX 0`. En el arranque de las 14:09 no hubo reinicio. Posible problema de alimentación o ruido del banco al conmutar: [VERIFICAR repitiendo un arranque con el registro abierto] |
| 5 | 14:56–14:58 | parcial | Hecho a mano por el autor: `W` a las 14:56:25 y 14:56:39 → `[WAVE] begin n=2048 canales=IA,IB,IC` … `end` (2048 muestras ✓), tramas vecinas a 2.59 y 2.84 s ✓; `s` a las 14:56:34 y 14:58:10 → JSON con THD e I_neg ✓, tramas a 2.00 y 1.80 s ✓. **`f` (Espectro) no se envió**: falta esa parte. App cerrada por el autor a las 14:58:41 (`>> TX 0`) |
| 5 | 15:22 | ✓ (2.º intento) | Prueba guiada (`herramientas/prueba_guiada_banco.py`, `sesion_20261013_152202`, 75 % de carga, motor ON desde 15:16:49): `W` → 2048 muestras por fase; `f` → barrido de las 3 fases con FASE CRITICA (A) y espectro de 21 puntos (50–70 Hz); `s` → JSON con THD e I_neg; tramas vecinas a 1.78, 1.98 y 1.30 s (≤ 3.4 s) |
| 6 | 15:09:58 | ✗ (pinza) | Lanzado por el autor desde la ventana de la prueba guiada (`sesion_20261013_150851`), 75 % de carga (I_rms 5.84 A; motor encendido ~15:00, según el autor). Exito a 0.01 s ✓; T_ON 5086 ms ✓; alarma **INTER** ML 2.730 pp a los 6.3 s y liberada ✓. **Pinza: 4.0 A** (autor), fuera del criterio 3.3–3.7 A ✗ |
| 7 | 13:25 | ✗ (severidad) | Ver arriba: pulsos y app correctos; 3.ª alarma SEVERA (0 % de carga) |
| 7 | 15:22:36 | ✓ (repetido a 75 %) | Prueba guiada; diálogo confirmado por el autor. 3 pulsos: respuesta 0.26/0.34/0.40 s, T_ON 5123/5118/5126 ms, pausas respetadas; 3 alarmas **INTER** (ML 2.254, 2.214, 2.539 pp) liberadas en 7.1/5.1/7.1 s; las 3 en el CSV |
| 8a | 15:25:43 | ✓ | Prueba guiada; diálogo confirmado por el autor. PARO por código a los 3 s: `>> TX 0` 15:25:46.489 → "Apagado" 15:25:46.532 (0.04 s); T_ON 2988 ms; registrado "PARO manual" |
| 8b | 15:26:32 | ✓ | **El autor confirmó que el SSR se apagó** al cerrarse la app. | Prueba guiada; diálogo confirmado por el autor. Cierre de la app por código 3.4 s después del encendido; el log termina con `>> TX 0` (15:26:35.916) ✓; registrado "app cerrada durante el pulso". El firmware respondió "Apagado" después de cerrarse el puerto, así que no quedó en el log |
| 8c | — | no se hizo | Opcional |
| 9 | 15:30 | ✗ (2 comprobaciones) | `resumen_sesion.py` en las 8 sesiones del día: 6 con 6/6 ✅. `sesion_20261013_142900`: ❌ "Sin errores en app.log" (el ERROR de la reconexión de las 14:34:28, paso 3). `sesion_20261013_152202`: ❌ "Todo pulso confirmado se apagó (mensaje 'Apagado')": es el pulso del paso 8b, cuyo "Apagado" no puede quedar en el log porque la app ya cerró el puerto (el criterio del paso 8b se verifica con la pinza/TFT) |

## Observaciones del autor durante la sesión

- **Casillas del diálogo de confirmación ilegibles** (captura `Screenshot From 2026-10-13 13-24-57.png`): las tres
  casillas se veían como cuadros negros, sin distinguir marcada de sin marcar. Corregido en `5fc7ab9` (indicador
  definido en la hoja de estilos, con prueba automática). El botón Inyectar ya se habilitaba solo con las tres
  marcadas; el problema era de legibilidad. La corrección entra en la app la próxima vez que se abra desde el
  repositorio; en el .deb, al reconstruirlo después de la sesión.
- **Listas desplegables negras** en la sección Asistente y en el diálogo del modelo externo (capturas
  `14-10-02` y `14-11-20`): corregido en `a6cabfe`.

## Sesión de las 14:07 (`sesion_20261013_140758`, copia del repositorio; el autor usó el asistente)

- Motor OFF → WARMUP → ON → OFF (42 / 36 / 215 / 301 tramas). El paso 3 (desconexión del USB) no se hizo en esta
  sesión: `app.log` no registra "Conexión perdida".
- **14:11:22, alarma LEVE de 64.7 s** (ML 0.61–0.85 pp) a ~2 min del arranque, liberada sola: coincide con la falsa
  alarma de arranque documentada (tesis §7, esperar ~5 min). El asistente respondió solo en **82.3 s**.
- **14:16:12, alarma al apagar el motor**: abrió LEVE (ML 1.10) y en 6.8 s escaló a **SEVERA con ML 223.6 pp**,
  cerrada por "motor apagado". Es el transitorio de la parada visto por el firmware; la app lo registró tal cual. El
  asistente respondió a la alarma (con el contexto LEVE de la confirmación) en **82.4 s**.
- Pregunta libre del autor ("como se encuentra en motor?"): 144.4 s.
- `asistente_20261013.jsonl` registró en esas dos respuestas el contexto de la trama al terminar ("Sin alarma",
  |I1| = 0 A en la segunda), no el que recibió el modelo: error del registro, corregido en `ca12600`.

## Pulsos extra del autor en `sesion_20261013_142900` (fuera del protocolo, 0 % de carga)

- 14:52:10: 1 pulso de 5 s, INTER (ML 4.363). 14:54:16–14:55:14: serie de 3 pulsos de 8 s, INTER, INTER y **SEVERA**
  (ML 4.382, 4.286, 4.786). Todos con respuesta del firmware, T_ON correcto y `0` de la app. La SEVERA a 0 % de
  carga se repite (ver el paso 7 de las 13:25).

## Veredicto (criterios del protocolo, sin cambios)

**No aprobada completa.** Pasos ✓: 1, 2, 3 (2.º intento), 4, 5 (2.º intento), 7 (repetido a 75 %), 8a, 8b. Pasos ✗:
- **6**: pinza 4.0 A, fuera de 3.3–3.7 A (lo demás del pulso cumplió);
- **9**: ERROR en app.log por la reconexión del paso 3 (`sesion_20261013_142900`) y falta del "Apagado" del pulso
  del paso 8b en el log (`sesion_20261013_152202`; el apagado se verificó en el banco).
- Primer intento del paso 7 (13:25, 0 % de carga): 3.ª alarma SEVERA (limitación del detector, no de la app).
8c (opcional) no se hizo. Hallazgo aparte: reinicio espontáneo del ESP32 a las 14:44:56, posiblemente al
encender el motor.
