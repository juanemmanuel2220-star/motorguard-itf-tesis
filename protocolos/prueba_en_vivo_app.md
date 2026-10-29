# Protocolo: prueba en vivo de la app MotorGuard-ITF con el banco

**Declarado el 12-oct-2026, antes de la sesión** (los criterios no se cambian después de ver resultados).
App: rama `feat/app-escritorio`, versión 1.0.0. Firmware: `299a943`, sin cambios.

**Objetivo:** verificar con el Arduino y el motor reales lo que hasta ahora solo se probó con logs reproducidos y
con el simulador del firmware: lectura y reconexión del puerto, estados del motor, capturas a petición,
inyección con bloqueos, PARO y cierre seguro.

**Evidencia:** lo que la app graba en `~/tesis_itf/app_registros/` (`sesion_<sello>_serial.log`, `_eventos.csv`,
`_pulsos.csv`) y `~/.local/share/MotorGuard-ITF/logs/app.log`. Al final se corre `resumen_sesion.py` (paso 9).

## Orden del día de banco

1. **Primero la prueba larga sin falla** (`~/prueba_larga_sin_falla.py`, ≈ 1.5 h, protocolo del commit `9e2968d`).
   **La app cerrada:** el puerto solo lo puede tener un programa. Motor encendido ≥ 5 min antes de iniciar.
2. Después, este protocolo (≈ 1 h).

## Seguridad (antes de los pasos con inyección)

- **Alimentación cortada para tocar el lazo**; taps **INTER** conectados (lazo probado a 3.3 A con 5 Ω); fusible
  10 A rápido, resistencia con ventilador y terminales de ojillo, SSR sobre disipador.
- **Nadie toca el lazo** mientras el motor esté encendido. La pinza se coloca con el motor apagado.
- No usar taps SEVERA en esta prueba.

## Pasos y criterios

| # | Paso | Criterio de aprobado |
|---|---|---|
| 1 | Con el motor **apagado**, abrir la app (`motorguard-itf` o `python -m motorguard_dashboard.app`). | Chip "CONECTADO /dev/ttyACM0" en ≤ 5 s; chip **Motor OFF**; tramas cada ~1.7 s (chip "Hace N s"); el log crudo empieza con `>> TX 0`. |
| 2 | Abrir una **segunda** ventana con el Arduino. | Aviso "Ya hay una ventana… usando el Arduino" y no se abre. |
| 3 | **Desconectar** el cable USB 10 s y volver a conectarlo (motor apagado). | Chip rojo "Conexión perdida"; al reconectar, "CONECTADO" en ≤ 5 s sin tocar la app y un nuevo `>> TX 0` en el log. |
| 4 | **Encender el motor** y esperar a ON. | Se ve OFF → WARMUP → ON; durante WARMUP el botón Inyectar está **bloqueado** con el motivo "motor en WARMUP"; el chip muestra los minutos encendido y aparece el **aviso de ~5 min**. |
| 5 | Con el motor en ON y el SSR apagado, pedir **Osciloscopio**, **Espectro** y **THD/I_neg** en Dashboard (una vez cada uno, separados ≥ 5 s). | Osciloscopio con 2048 muestras por fase; espectro con 21 puntos y fase crítica; THD e I_neg con valor; la trama siguiente llega en ≤ 3.4 s (no se pierde un bloque). |
| 6 | Pasados ≥ 5 min de encendido: **un pulso de prueba** INTER de 5 s desde la app, con la pinza en el lazo. | Diálogo con las 3 casillas obligatorias; firmware responde "Exito" en ≤ 1 s; pinza 3.3–3.7 A; T_ON del firmware 5.0 ± 0.3 s; alarma **INTER enclavada** y luego liberada. |
| 7 | **Serie de 3 pulsos** INTER de 5 s con pausa de 20 s. | Los 3 confirmados; pausa respetada (el botón queda bloqueado por enfriamiento); 3 alarmas INTER en la tabla y en el CSV de pulsos. |
| 8a | Pulso de 11 s y **PARO** (barra superior) a los ~3 s. | El firmware reporta "Apagado" en ≤ 1 s tras el clic; T_ON < 5 s; pulso registrado como "PARO manual". |
| 8b | Pulso de 11 s y **cerrar la app** a los ~3 s. | El SSR se apaga en ≤ 1 s (TFT/pinza en 0); el log crudo de esa sesión termina con `>> TX 0`. |
| 8c *(opcional)* | Pulso de 5 s y **desconectar el USB** a los ~2 s. | El firmware corta por su protección a los 12 s (pinza a 0 ≤ 12 s); al reconectar la app envía `0` y marca el pulso "conexión perdida". |
| 9 | Cerrar la app y correr `python -m motorguard_dashboard.herramientas.resumen_sesion ~/tesis_itf/app_registros` sobre cada sesión. | Todas las comprobaciones automáticas en ✅ (respuesta del firmware ≤ 1 s, todo pulso apagado, T_ON ≤ 12 s, `0` al conectar, solo comandos permitidos, 0 errores en app.log). |

**La prueba se aprueba** si todos los pasos 1–9 cumplen su criterio (8c es opcional). Cualquier falla se
anota con su hora para buscarla en los registros; no se repite un paso para "hacerlo pasar" sin anotar la
primera vez.

## Hoja para llenar en el banco

| # | Hora | ✓ / ✗ | Observaciones (pinza, mensajes, lo que se vio) |
|---|---|---|---|
| 1 | | | |
| 2 | | | |
| 3 | | | |
| 4 | | | |
| 5 | | | |
| 6 | | | |
| 7 | | | |
| 8a | | | |
| 8b | | | |
| 8c | | | |
| 9 | | | |
