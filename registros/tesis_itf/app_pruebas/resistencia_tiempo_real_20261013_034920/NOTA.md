# Notas de la prueba de resistencia de 4 h (13-oct-2026)

Agregadas por Claude Code después de la prueba; los archivos de resultados no se modificaron.

## Resultado del script
`resumen.json`: APROBADA. 8400 de 8405 tramas (99.93 %), 479 pulsos (0 sin terminar), 466 alarmas, 11
desconexiones de 10 s, SSR apagado al final, 0 errores en `app.log`, CPU media 17.75 %.

## Condiciones que hay que reportar con el resultado
1. **Suspensión del equipo.** La laptop se suspendió al cerrar la tapa de 05:29:58 a 08:31:05
   (`journalctl`: "Lid closed" / "Lid opened"). Las horas de la prueba se miden con el reloj monótono, que no
   avanza durante la suspensión, así que las 4.0 h son de ejecución real (03:49–05:30 y 08:31–11:04).
2. **Memoria.** El criterio usa "RSS final − RSS de la hora 1". El script da −67.0 MB, pero esa cifra no
   sirve: a las 3.22 h el RSS cayó de 171.7 a 93.9 MB porque la evaluación del asistente (Qwen3.5-4B, ~6 GB)
   corría en paralelo y el kernel recuperó páginas del proceso que se pueden releer del disco (bibliotecas).
   No faltó memoria (6.5 GB disponibles, swap 256 MB de 4 GB). **Crecimiento real comparable: de la hora 1
   (169.9 MB) a la hora 3.20 (171.7 MB) = +1.8 MB** (`muestras.csv`), dentro del criterio de ≤ 30 MB.
3. **CPU.** Subió de ~9 % a ~20 % en las primeras ~1.7 h y luego se estabilizó. La causa era el panel de
   inyección, que revisaba hasta 200 filas de pulsos 10 veces por segundo (4.45 ms por refresco con 200 pulsos).
   Se corrigió después de lanzar la prueba (commit `8f184b4`, 0.05 ms por refresco); **esta prueba corrió con
   el código anterior**. La CPU no es criterio de la prueba.
4. **Carga en paralelo durante la prueba:** pruebas de paquetes en Docker (madrugada), indexado de dos
   documentos, la evaluación final del asistente, la construcción y prueba de los .deb. Aun así se
   recibió el 99.93 % de las tramas.
5. Simulador del firmware (`tests/simulador_firmware.py`): solo pruebas; no es evidencia experimental del banco.
