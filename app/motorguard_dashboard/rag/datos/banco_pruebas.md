# Documento técnico del banco de pruebas MotorGuard-ITF: comportamiento, mediciones y teoría de funcionamiento

Documento de referencia para el asistente de la aplicación MotorGuard-ITF. Describe el banco de pruebas de la tesis "Detección de Fallas de Cortocircuito en Devanados de Motores de Inducción mediante Análisis de Firma de Corriente (MCSA) e Inteligencia Artificial" (Juan Emmanuel Luna Velázquez, UASLP-UAMRA, 2026): el equipo, la instrumentación, la teoría con que funciona el detector, cómo se comporta el sistema y todas las mediciones disponibles al 16-oct-2026. Fuentes: capítulos 2 y 3 de la tesis, `resultados_oct_2026.md` (revisado el 16-oct-2026), el firmware `299a943` (`~/Arduino/PRUEBA_MODELO_1/`), las bitácoras de banco y los registros de `~/tesis_itf/`.

## 1. Propósito, alcance y advertencia de uso

- Este documento describe el banco de pruebas de la tesis: un solo motor ABB de 1.5 kW con fallas entre espiras emuladas de forma controlada en la fase C. NO describe el motor que vigila el usuario de la aplicación. Las cifras del banco (porcentajes de espiras, corrientes del lazo de falla, fase con falla, tasas de falsas alarmas) no deben aplicarse a otro motor.
- Sirve para responder cómo funciona el detector, qué significa cada variable de la telemetría, de dónde salen los umbrales, cómo se comportó el sistema en el banco y cuáles son sus limitaciones.
- Convención de estados: VALIDADO = medido con el sistema final y con evidencia en archivo; PRELIMINAR = medido con una versión anterior, de forma incompleta o con una limitación declarada; PENDIENTE = no realizado. Lo marcado como "post hoc" o "derivado" es un análisis hecho después de ver los datos o un cálculo propio de este documento: orienta, pero no es un resultado declarado.
- Los procedimientos de mantenimiento (pruebas de aislamiento, secado, reparación) no están aquí: están en los manuales del fabricante y en las guías de mantenimiento indexadas en la aplicación.

## 2. Motor bajo prueba

- Modelo ABB M1AA 145T-D4, motor de inducción trifásico de jaula de ardilla, 4 polos.
- Datos de placa: 1.5 kW (2 HP), 220 V entre líneas en estrella (127 V de fase nominal), 5.8 A nominales, 1725 rpm, 60 Hz. Eficiencia de 0.81 según el dato del autor. Los documentos antiguos que dicen "1 HP" o "123 V nominales" están equivocados.
- Velocidad síncrona con 4 polos a 60 Hz: 1800 rpm. Deslizamiento nominal a 1725 rpm: (1800 − 1725)/1800 ≈ 4.2 %.
- La caja de bornes tiene 12 terminales con derivaciones (taps) de los devanados: terminales 1 a 4 en la fase C, 5 a 8 en la fase A y 9 a 12 en la fase B. Estas derivaciones permiten emular cortocircuitos entre espiras sin dañar el aislamiento.
- Conexión del estator en estrella sin neutro, por lo que la corriente de secuencia cero es nula.
- El motor y el generador de carga son préstamo del Laboratorio de Mecatrónica de la UAMRA.

## 3. Carga mecánica y niveles de carga

- El motor acciona un generador de corriente directa Baldor CDP3585 de imán permanente (tipo PM3548P según su placa; 2 HP, 180 V, 9.6 A, 1750 rpm, eficiencia 0.86) acoplado al eje. La potencia del generador se disipa en resistencias de potencia conectadas a su salida; el par que demanda al motor se fija con el valor de la resistencia. El número CDP9580 que aparecía en documentos anteriores se leyó mal de una foto borrosa; el autor confirmó CDP3585 el 27-oct-2026.
- Niveles nominales de carga: 0 % = generador sin resistencia (en vacío); 25 % = 75 Ω; 50 % = 33 Ω; 75 % = dos resistencias de 50 Ω en paralelo (25 Ω).
- Los porcentajes son nominales: el par en el eje no se midió. La potencia real depende del voltaje del generador, que varía con el ajuste del variac y la velocidad.
- El nivel de 100 % se excluyó. En la preparación, una sola resistencia de 25 Ω y 700 W se puso al rojo vivo y el variac se sobrecargó; con 163.5 V en el generador disipaba unos 1.07 kW. Operar a 1.5 kW requeriría disipar del orden de 1.29 kW, por encima de lo que el banco soporta con seguridad.
- La carga NO se cambia con el motor girando: el banco no lo permite con seguridad. Para cambiarla se apaga el motor y se corta la alimentación. Por eso los escalones de carga en caliente nunca se evaluaron.
- Error de montaje registrado el 15-oct-2026: un primer encendido "al 75 %" tenía las dos resistencias de 50 Ω en serie (100 Ω) en lugar de en paralelo; se detectó por las corrientes y se corrigió antes de capturar. Verificar las corrientes por carga (sección 24) evita este error.

## 4. Alimentación eléctrica

- El motor se alimenta de la red de la unidad académica a través de un variac trifásico (autotransformador variable) de 3.5 kVA, que permite energizar el banco de forma gradual.
- La red entrega aproximadamente 123 V por fase (el motor es de 127 V de fase nominales).
- El desbalance de voltaje medido por el sistema (U2V = |V2|/|V1|) fue de 0.6–1.1 % (mediana) en la mayoría de las sesiones, pero llegó a 3.6 % de mediana y 6.0 % de máximo en el tramo de motor sano al 75 % del 15-oct-2026, y subió de ~1 % a 2–4 % durante la tarde del 12-oct-2026. La causa externa no se identificó.
- Cautela: los canales de voltaje no siempre son confiables (sección 9). El 06-oct-2026 el sistema leía VA −5 % y VB +3 % respecto al multímetro, cuando el desbalance real era ~0.6 %. El 15-oct, al 25 % y al 75 %, VA marcó 113.6–116.9 V mientras VB y VC marcaban 126–129 V. Por eso parte del desbalance de voltaje reportado puede ser de la instrumentación y no de la red.
- El análisis del 12-oct descartó que las falsas alarmas vengan principalmente del desbalance de la red: en los bloques que suman racha, el cambio de V2 está en el percentil 48, igual que en cualquier bloque, y compensar con V2 no redujo las falsas alarmas.

## 5. Derivaciones del devanado y definición de las clases de falla

- La documentación disponible del motor indicaba derivaciones al 5, 11 y 20 % del devanado, pero las primeras inyecciones no producían los cambios esperados. Se caracterizaron experimentalmente.
- Resistencia entre terminales de la fase C medida con el LCR-819: 1↔2 = 0.193 Ω; 2↔4 = 0.452 Ω; 1↔4 = 0.795 Ω; 2↔3 = 1.045 Ω; 3↔4 = 1.600 Ω; 1↔3 = 1.660 Ω. Algunas no son aditivas (hay conexiones internas), así que la resistencia no basta para conocer la fracción de espiras.
- Método definitivo, voltaje inducido con el motor en marcha (proporcional al número de espiras). Fase C: 1↔2, 2↔3 y 3↔4 = 8.6 V cada una (7.0 % de 123 V); 1↔3 y 2↔4 = 17.6 V (14.3 %); 1↔4 = 26.6 V (21.6 %). Fase A: 5↔6 = 9.4 V (7.6 %), 6↔7 = 8.5 V (6.9 %), 7↔8 = 8.5 V (6.9 %), 5↔7 = 18.2 V (14.8 %), 6↔8 = 17.4 V (14.1 %), 5↔8 = 27.0 V (22.0 %).
- Clases de falla, todas en la fase C para tener una progresión anidada: LEVE = terminales 1↔2 (≈ 7.0 % de las espiras de la fase); INTERMEDIA o INTER = 2↔4 (≈ 14.3 %); SEVERA = 1↔4 (≈ 21.6 %).
- Supuesto: el voltaje inducido es proporcional al número de espiras. Estado: VALIDADO con ese supuesto. Las derivaciones de la fase A quedaron caracterizadas pero nunca se usaron para inyectar.

## 6. Lazo de inyección de falla

- El lazo conecta en serie: dos derivaciones de la fase C (según la clase), una resistencia limitadora, un relevador de estado sólido (SSR) y un fusible. Al cerrar el SSR se crea un camino de baja impedancia en paralelo con las espiras seleccionadas, que emula el cortocircuito entre ellas.
- SSR: Fotek SSR-25DA (control en CD, conmuta CA). Se activa desde el pin D5 de la tarjeta (GPIO 8) a través de un transistor NPN 2N2222 con resistencia de base de 1 kΩ. Desde el bloque SEVERA va montado sobre disipador y con ventilador.
- Resistencia limitadora: 5 Ω / ≈150 W en la configuración actual (dato confirmado por el autor el 17-oct-2026; los 700 W que aparecían en documentos anteriores son de la resistencia de carga de 25 Ω). Historia: 15 Ω / 20 W en el diseño inicial y 10 Ω / 20 W en las campañas de julio a septiembre de 2026.
- Fusible: 5 A hasta el bloque INTER; 10 A rápido desde el bloque SEVERA (08-oct-2026). El fusible protege el cableado, no el devanado: al devanado lo protegen la resistencia, el límite de 12 s del firmware y los pulsos cortos.
- Corriente del lazo medida con pinza (RMS), con 5 Ω: LEVE ≈ 1.7 A en el dataset (1.7–2.0 A el 15-oct); INTER 3.6–3.7 A al 0 y 25 % y 3.3 A al 50 y 75 % en el dataset (3.7–4.4 A el 15-oct; 4.0 A el 13-oct); SEVERA 4.8–5.2 A.
- Una falla entre espiras real tiene una impedancia de lazo mucho menor y una corriente de lazo mucho mayor: el banco emula una falla limitada por la resistencia de 5 Ω, no una falla franca.
- Solo un SSR (GPIO 8) está conectado al lazo. El firmware define también salidas en GPIO 7 y GPIO 9, pero la clase de falla se elige cambiando a mano las derivaciones, con el motor apagado y la alimentación cortada.

## 7. Incidentes del lazo de inyección y prácticas que dejaron

- Puesta en marcha: el primer SSR estaba dañado; su lado de control respondía pero el de potencia no conducía (solo ~30 mA por la red de protección interna). Se confirmó con multímetro, osciloscopio y la resistencia fría, y se sustituyó.
- 07-oct-2026: el lazo dejó de conducir en las últimas 5 pruebas de una validación LEVE pese a "GPIO 8 HIGH"; se repararon los bornes de la resistencia.
- 07-oct-2026, bloque INTER: la corriente cayó de forma progresiva 3.7 → 3.4 → 3.3 → 3.2 → 3.1 A en ~1 h y no se recuperaba en frío ni cambiando la resistencia. El SSR original se degradó (operaba sin disipador); se reemplazó por el de repuesto y la corriente quedó estable en 3.3 A.
- 08-oct-2026, bloque SEVERA: la resistencia limitadora se soltó cuatro veces; los pares sin inyección se excluyeron. Práctica derivada: terminales de ojillo en la resistencia.
- 09-oct-2026: un bloque LEVE se anuló porque los taps quedaron mal conectados al cambiar desde INTER (la pinza marcaba 1.3 A, pero sin cortocircuitar espiras: no había firma). Otro bloque se degradó a mitad (1.7 → 1.3 A y luego sin firma).
- 15-oct-2026: en INTER al 0 % hubo un pulso en que el lazo no condujo (prueba 12, 12:23:57).
- Prácticas adoptadas: medir el lazo con pinza al inicio, a la mitad y al final de cada sesión; hacer un pulso de prueba aislado antes de cada sesión y comprobar que el sistema reporta la clase esperada; SSR sobre disipador; ventilador en la resistencia; enfriamiento de 15–20 s entre pulsos; terminales de ojillo.

## 8. Protecciones del lazo en el firmware y reglas de seguridad del banco

- Protecciones del firmware `299a943`: el SSR no puede seguir encendido más de 12 s continuos (se apaga solo); deben pasar al menos 2 s entre una desactivación y la siguiente activación; se rechaza la activación si la corriente eficaz supera 8 A; durante la inyección, si la corriente rápida de la fase C supera 8 A en 3 lecturas seguidas (cada 100 ms, después de 600 ms de cegado por el arranque del lazo), el SSR se apaga.
- El firmware rechaza encender el SSR con el motor apagado y no permite dos SSR a la vez. Sí acepta encenderlo durante el calentamiento (WARMUP); el bloqueo durante el calentamiento lo hace la aplicación.
- Reglas de operación del banco: confirmar que nadie toca el lazo antes de cada pulso; motor apagado y alimentación cortada para tocar taps, resistencia, SSR o carga; USB desconectado para recablear la instrumentación; esperar ~5 min después de encender el motor antes de pulsos o pruebas; solo un programa puede usar el puerto serie a la vez.
- El firmware nunca se modifica sin repetir la validación ciega.

## 9. Instrumentación y adquisición: hardware

- Unidad de procesamiento: Arduino Nano ESP32 (ESP32-S3, dos núcleos Xtensa LX7 a 240 MHz, 512 KB de SRAM). Se compila con la opción de numeración de pines por GPIO (`PinNumbers=byGPIONumber`); con la numeración por defecto la pantalla queda en blanco y el SSR cambia de pin.
- Corriente: un ACS712-30A por fase (efecto Hall, 66 mV/A a 5 V, reposo en 2.5 V, salida ratiométrica). Como el ADC admite 3.3 V, cada salida pasa por un divisor de 10 kΩ y 20 kΩ (2/3). El ACS712-30A usa aproximadamente 1/6 de su rango con estas corrientes.
- Voltaje: un ZMPT101B por fase, alimentado a 3.3 V, conectado directo al ADC; su ganancia se ajusta con un potenciómetro.
- Entradas analógicas: VA = A4, VB = A3, VC = A5, IA = A1, IB = A0, IC = A2. ADC de 12 bits con atenuación de 11 dB.
- El Wi-Fi está deshabilitado: VA y VC están en el ADC2, que no puede usarse con el radio encendido. La telemetría sale por USB serie a 115200 baud.
- Pantalla local TFT ILI9341 de 2.8 in (240 × 320) por SPI; el comando 'D' lee sus registros (ID esperado 00 93 41).
- Calibración vigente: CAL_V = (0.5503, 0.5400, 0.6624) V/cuenta y CAL_I = (0.0181, 0.0195, 0.0179) A/cuenta para las fases A, B y C. Las corrientes se recalibraron el 06-oct-2026 contra la pinza (A 5.0 A, B 5.5 A, C 5.1 A); los voltajes, por igualación a 123 V. No hay tabla de verificación de los seis canales contra osciloscopio con el firmware final (PENDIENTE).
- Calibración de julio (canal de la fase C contra osciloscopio MSO 2014B, sonda P5200A y pinza A622): voltaje +3.9 % y corriente +2.1 % de error.
- Equipo de laboratorio: osciloscopios Tektronix TDS-1002CEDU y MSO 2014B, sonda diferencial P5200A, pinza de corriente A622, medidor LCR GW Instek LCR-819, multímetro de verdadero valor eficaz y pinza amperimétrica.

## 10. Conexionado e integridad de la señal

- La instrumentación está en protoboard. El hallazgo principal de octubre de 2026 fue que la calidad de las conexiones (cables dupont, contactos de protoboard) era la mayor fuente de ruido de la firma de falla.
- Mecanismo: el ACS712 es ratiométrico, así que una resistencia de contacto variable en su alimentación o en su tierra cambia su ganancia y su cero; eso aparece como una variación de corriente en una sola fase, que la descomposición de Fortescue convierte en una falsa corriente de secuencia negativa, indistinguible de una falla pequeña.
- Evidencia: con conexiones degradadas hubo 28 falsas alarmas en 30 min y las fluctuaciones de las corrientes B y C eran de 1.5–2.0 %; al rehacer las conexiones bajaron a 0.2–0.4 % y la desviación estándar de la proyección de la firma bajó de 0.58 a 0.22 pp.
- Incidentes de ganancia: 06-oct ~16:40, el canal IC perdió 16 % de ganancia por una conexión de protoboard (corregido a las 16:57 sin recalibrar); 08-oct ~13:25, IC perdió ~12 % por el contacto del divisor (se soldó y volvió a coincidir con la pinza sin recalibrar).
- Medidas: protoboard mejorada con cable rígido y rieles de tierra separados, prueba de provocación antes de cada sesión (perturbar a propósito las conexiones y ver que las lecturas no cambien) y una placa soldada diseñada (construcción PENDIENTE).
- Escalones espontáneos: el 15-oct-2026 a las 11:59:38, con el motor sano al 0 %, la corriente IA saltó de 3.71 a 3.79 A (+2 %) y dejó una alarma enclavada. Se sospecha un contacto de la cadena de medición, sin confirmar.

## 11. Adquisición: muestreo, bloques y tiempos

- Un temporizador de hardware dispara el muestreo cada 416 µs: 2403.846 Hz por canal. Una tarea de FreeRTOS fijada a un núcleo lee los seis canales en cada disparo, uno tras otro.
- Búfer doble de 4096 muestras por canal: mientras uno se llena, el otro se procesa. Cada bloque dura 4096/2403.846 ≈ 1.70 s y la resolución espectral es 2403.846/4096 ≈ 0.586 Hz.
- Por cada bloque se calcula todo el procesamiento y se envía una línea de telemetría `[MCSA]`, es decir, una decisión cada ~1.7 s.
- Como los canales se leen en secuencia, cada uno tiene un retardo respecto al primero; el firmware lo compensa en fase con valores fijos de 0, 30, 60, 90, 120 y 150 µs para VA, VB, VC, IA, IB e IC (rotación de −2π·f0·τ en cada fasor).
- El cero (offset) de cada canal se estima al arrancar con 128 lecturas y luego se sigue lentamente; para los fasores se resta además la media del bloque.

## 12. Teoría: motor de inducción, deslizamiento y espectro

- El estator trifásico crea un campo giratorio a la velocidad síncrona n_s = 120·f1/P (1800 rpm para P = 4 polos y f1 = 60 Hz). El rotor gira a n < n_s; el deslizamiento es s = (n_s − n)/n_s y crece con la carga.
- El análisis de firma de corriente (MCSA) busca en el espectro de la corriente componentes asociadas a fallas, por ejemplo bandas laterales en f1·(1 ± 2ks) para asimetrías del rotor. En vacío s es muy pequeño y esas bandas quedan pegadas a la fundamental.
- El firmware calcula también características MCSA de la fase con mayor contenido de bandas laterales: amplitud fundamental (ventana 58.5–61.5 Hz), picos en 53.5–57.8 Hz y 62.4–66.5 Hz, distorsión armónica total con los armónicos 2 a 6, y un módulo de alta resolución (bandas f0(1 ± 2s), f0 ± fr, 3f0 y sus bandas, en dB respecto a la fundamental, con relación señal/ruido).
- La estimación del deslizamiento no es confiable en este banco: el indicador SOK (pico rotórico con prominencia ≥ 6 dB) solo se cumplió en 32–36 % de los bloques el 15–16 oct, y la s reportada (≈ 0.026–0.031) casi no cambia entre 0 y 75 % de carga.
- Las características MCSA no participan en la detección: no distinguieron la falla en este banco (sección 30).

## 13. Teoría: el cortocircuito entre espiras y su emulación

- Un cortocircuito entre espiras ocurre cuando se pierde el aislamiento entre vueltas de una misma bobina. El grupo de espiras en corto se comporta como el secundario de un autotransformador cuyo primario es el resto de la fase: el flujo induce en él un voltaje proporcional al número de espiras afectadas y, como el lazo tiene impedancia muy baja, circula una corriente que puede superar varias veces la nominal.
- Consecuencias: térmica (el calor local degrada el aislamiento vecino y la falla se propaga, a veces en poco tiempo) y electromagnética (el lazo produce una fuerza magnetomotriz opuesta a la de su fase, el devanado deja de ser simétrico y aparece corriente de secuencia negativa en los terminales).
- En el banco la falla se emula uniendo dos derivaciones a través de la resistencia de 5 Ω y el SSR. La fracción de espiras μ es la de la sección elegida (0.070, 0.143 o 0.216) y la corriente del lazo I_f queda limitada por la resistencia (1.7–5.2 A RMS). Es reversible y repetible, pero no reproduce la evolución térmica ni la corriente de una falla franca.

## 14. Teoría: componentes simétricas de Fortescue

- Cualquier terna de fasores desbalanceados se descompone de forma única en tres ternas balanceadas: secuencia positiva (mismo orden de fases), secuencia negativa (orden invertido) y secuencia cero (tres fasores iguales).
- Con el operador a = e^{j120°} = −0.5 + j0.866: I0 = (Ia + Ib + Ic)/3; I1 = (Ia + a·Ib + a²·Ic)/3; I2 = (Ia + a²·Ib + a·Ic)/3. Igual para los voltajes V0, V1 y V2.
- En un motor en estrella sin neutro, I0 = 0. En un motor sano con red simétrica solo existe secuencia positiva.
- Fuentes de corriente de secuencia negativa en un motor real: (1) desbalance de la red, V2 por la admitancia de secuencia negativa del motor Y2; (2) asimetría constructiva del motor sano, I2,0; (3) diferencias de ganancia o de fase entre los sensores, que aparecen como una I2 aparente; (4) una falla en el devanado, que agrega una I2 que crece con la severidad.
- Indicadores derivados en la telemetría: U2V = |V2|/|V1| (desbalance de voltaje) y U2I = |I2|/|I1| (asimetría de corriente), en %.

## 15. Cálculo de fasores en el firmware

- La frecuencia fundamental f0 se estima en cada bloque en la banda 58.5–61.5 Hz con interpolación espectral de Grandke sobre una ventana de Hann; si sale de 58–62 Hz se usa 60 Hz. En el banco, f0 estuvo entre 59.96 y 60.05 Hz (percentiles 1 y 99).
- El fasor de cada canal se calcula con una DFT de una sola frecuencia en f0: se resta la media del bloque, se multiplica por la ventana de Hann y por e^{−j2π·f0·n/fs}, se suma y se escala por 4/N (2 dividido entre la suma de la ventana), lo que da la amplitud pico.
- A cada fasor se le compensa el retardo de muestreo de su canal y se le aplica su factor de calibración.
- Referencia angular: se calcula V1 y se rotan todos los fasores para que arg(V1) = 0. Todas las direcciones del detector (por ejemplo −81.4°) están medidas respecto al voltaje de secuencia positiva.
- Diagnóstico por fase: el ángulo de cada corriente respecto a su voltaje (comando 'P'); en un motor debería quedar aproximadamente entre −30° y −50°. Sirve para detectar sensores con polaridad u orden de fases equivocados.

## 16. Residuo de secuencia negativa y firma z

- Residuo compensado: R2 = I2 − Y2·V2 − I2,0 (fasor, A pico). Y2 e I2,0 se obtienen de un comisionamiento con el motor sano (30 bloques, mínimos cuadrados) y se guardan en la memoria no volátil. Según el capítulo 3, el comisionamiento vigente tiene Y2 = 0 e I2,0 fijo.
- Firma normalizada: z = 100·R2/|I1|, en puntos porcentuales (pp) de la corriente de secuencia positiva. Normalizar por |I1| la expresa como fracción de la corriente del motor.
- El detector usa solo CAMBIOS de z (dz), no su valor absoluto. Por eso cualquier término constante (asimetría propia del motor, desbalance fijo de la red, diferencias fijas de ganancia de los sensores, el I2,0 comisionado) se cancela, y el valor absoluto de |z| (≈ 1 % al 25–75 % y ≈ 3.6 % al 0 % en el motor sano, 15–16 oct) no importa.
- Lo que no se cancela es lo que cambia en segundos: la falla, pero también los cambios de ganancia de un sensor (mal contacto), los escalones de corriente de una fase y las variaciones lentas de la red o del motor. Ese es el ruido de la firma (sección 25).

## 17. Modelo simplificado de la magnitud de la firma (cálculo derivado)

- Aproximación: si las espiras en corto se tratan como una perturbación de corriente en una sola fase igual a μ·I_f (fracción de espiras por corriente del lazo), la descomposición de Fortescue da |ΔI2| ≈ μ·I_f/3. En pp de |I1|: firma ≈ 100·μ·I_f,pico/(3·|I1|).
- Comparación con las medianas medidas (Tabla A, sección 26) y la corriente del lazo de cada bloque: el cociente medido/modelo fue 0.87–0.96 en LEVE, 0.74–0.86 en INTER y 0.75–0.83 en SEVERA, en las cuatro cargas. El modelo explica el orden de magnitud y sobreestima entre 4 y 26 %; no se investigó por qué (acoplamiento imperfecto de las espiras, distribución en las ranuras, exactitud de la pinza).
- Consecuencia 1: en amperes, |ΔI2| casi no cambia con la carga (LEVE ≈ 0.049–0.054 A pico en las cuatro cargas; SEVERA ≈ 0.39–0.43 A pico). La firma en pp baja con la carga sobre todo porque |I1| sube (de ≈ 5.6 A pico en vacío a ≈ 7.7 A pico al 75 %).
- Consecuencia 2: la firma depende de la corriente del lazo, no solo del número de espiras. Por eso, cuando el lazo condujo más que en el dataset (15-oct), la severidad reportada subió un nivel en algunos pulsos.
- Consecuencia 3 (estimación orientativa, no validada): con el umbral de 0.40 pp, el detector necesita del orden de μ·I_f,pico ≥ 0.012·|I1| en la dirección de falla. Al 75 % (|I1| ≈ 7.7 A pico) eso es μ·I_f ≈ 0.07 A RMS: para μ = 0.07 corresponde a I_f ≈ 1 A RMS. Es solo una extrapolación del modelo simplificado.
- Estado: cálculo propio de este documento a partir de datos VALIDADOS; el modelo no se declaró ni se validó.

## 18. Dirección de la firma y fase con falla

- La falla desplaza z en una dirección estable. Con las fallas en la fase C, las medianas por clase y carga van de −75.9° a −85.1° respecto a arg(V1); el detector usa −81.4°, la dirección media de LEVE en el dataset del 06-oct-2026.
- La dirección no cambia con la severidad ni con la carga en el banco. La magnitud sí cambia (sección 26).
- Predicción teórica no verificada en el banco: por la simetría de Fortescue, la misma falla en la fase A o en la fase B produciría una firma rotada ±120°. Su proyección sobre −81.4° sería negativa (cos 120° = −0.5), de modo que el detector, tal como está configurado, NO confirmaría una falla en las fases A o B. Solo se ensayaron fallas en la fase C.
- La dirección también depende del orden de fases de la alimentación y del orden y la polaridad de los sensores: si se invierte la secuencia de fases, los papeles de las secuencias positiva y negativa se intercambian. En otro motor o en otra instalación la dirección tendría que volver a medirse.

## 19. Detector direccional: referencia móvil, proyección y persistencia

- Es el detector que decide en el firmware `299a943` (archivo `detector_dir.cpp`). Pasos en cada bloque t:
- 1) z(t) = 100·R2(t)/|I1(t)| en pp.
- 2) Referencia: mediana, por componente real e imaginaria, de los z de los bloques con edad entre 6 y 11 s (normalmente 3 bloques). Si hay menos de 2 bloques, no se decide (REF = 0).
- 3) dz = z(t) − referencia.
- 4) Proyección sobre la dirección de falla: P = Re{dz·e^{+j81.4°}} = dz_re·cos(−81.4°) + dz_im·sin(−81.4°). Una falla en la fase C da P positiva; un cambio en otra dirección da P pequeña o negativa.
- 5) Racha: número de bloques consecutivos con P ≥ 0.40 pp. Cuando la racha llega a 3 bloques (~5 s), la alarma se confirma.
- El retardo típico de confirmación es de ~5.4 s (reanálisis del 13-oct).
- La referencia de 6 a 11 s se eligió para que la falla recién iniciada no entre todavía en la referencia. Con una falla sostenida, la referencia móvil se contamina a los ~8 s; por eso hace falta el enclavamiento (sección 20). Una persistencia más larga que 3–4 bloques es insegura: ni una falla permanente se confirmaría.
- Parámetros (−81.4°, 0.40 pp, 3 bloques, 6–11 s) ajustados con los 200 pares LEVE del 06-oct-2026 en las 4 cargas. El análisis del 13-oct mostró que, dentro de la familia umbral × persistencia, ya están en el óptimo.

## 20. Enclavamiento y liberación de la alarma

- Al confirmarse la alarma se congela la referencia previa a la falla (base). Mientras dura la alarma, la firma se mide contra esa base congelada: proyección PL y magnitud ML (campos de la telemetría). Así una falla sostenida no se "absorbe" en la referencia móvil.
- Liberación: la alarma se apaga cuando PL cae por debajo de max(0.20 pp; 0.35 × la proyección del bloque de confirmación) durante 3 bloques seguidos. Al liberarse se reinicia la racha para no volver a disparar en el mismo evento.
- En vivo, con pulsos de falla de ~11 s, la liberación tardó 5.1–6.1 s después de abrir el lazo.
- Debilidad conocida: si el cambio que disparó la alarma es un escalón sano persistente (un cambio de ganancia de un sensor, un escalón de corriente), la firma contra la base nunca baja y la alarma queda enclavada indefinidamente. Se libera con el comando 'r' (reinicio del detector), que en la aplicación es el botón «Liberar alarma» (sección 32). En las pruebas largas, un script mandaba 'r' cuando una alarma seguía enclavada más de 60 s; el firmware no lo hace solo.

## 21. Severidad embebida

- Al confirmar, la severidad se calcula con la mediana de |dz| de los 3 bloques de confirmación: LEVE si es menor que 1.626 pp; INTER si está entre 1.626 y 4.471 pp; SEVERA si es de 4.471 pp o más. Campo SEV de la telemetría: 0 sin alarma, 1 LEVE, 2 INTER, 3 SEVERA.
- Mientras la alarma sigue enclavada, la severidad se recalcula con la mediana de ML de los últimos 3 bloques, pero solo puede subir, nunca bajar.
- Los umbrales salen del clasificador M1 entrenado con 597 pares (200 LEVE, 200 INTER, 197 SEVERA) en las cuatro cargas, con diseño declarado antes de ver resultados. Validación dejando una carga fuera: 596/597 = 99.8 % (IC 95 % 0.991–1.000); el único error fue un par INTER al 0 % de 4.28 pp clasificado como SEVERA. Se compararon una regresión logística (597/597) y un árbol (596/597); se eligió M1 por ser el más simple de embeber.
- Limitación 1: cada severidad se capturó en un día distinto, así que la clase está confundida con la sesión.
- Limitación 2: los umbrales valen para la corriente del lazo con que se capturó el dataset. Con más corriente la firma crece (sección 17): el 15-oct, al 0 %, 4 de 9 pulsos INTER se reportaron SEVERA (lazo de 3.7–4.0 A frente a 3.6–3.7 A del dataset).
- Limitación 3: con una alarma falsa enclavada, una falla real posterior se suma a esa base y puede reportarse con una severidad mayor (15-oct: 7 pulsos LEVE reportados como INTER).

## 22. Estados del motor, arranque y calentamiento

- El firmware considera el motor encendido cuando, durante 3 bloques seguidos, las tres fases tienen corriente de 60 Hz mayor de 1 A con forma senoidal y los voltajes superan 60 V. Lo considera apagado cuando menos de 2 fases tienen corriente de 60 Hz mayor de 0.5 A durante 3 bloques. Exigir corriente de 60 Hz evita que una entrada flotante o un sensor con mal contacto simule un motor encendido.
- Estados en la telemetría: OFF, WARMUP y ON. Al encender, el firmware espera 60 s (WARMUP) sin decidir, por la deriva térmica y eléctrica del residuo en el arranque.
- Aun así, con el motor recién encendido puede confirmarse una falsa alarma LEVE (09-oct 15:01; arranques del 12-oct al 25 % y al 75 %). Regla de operación: esperar ~5 min después de encender antes de interpretar alarmas o inyectar. Un calentamiento de ~3 min en el firmware queda como trabajo futuro.
- El 13-oct-2026 el ESP32 se reinició espontáneamente a las 14:44:56, posiblemente al encender el motor (sin confirmar).

## 23. Detectores heredados que no deciden: CUSUM y Random Forest espectral

- El firmware conserva un detector secuencial CUSUM sobre el cambio del residuo escalar: S_t = max(0, S_{t−1} + z_t − K), con K = 0.5, techo 8, alarma con S_t ≥ 5.0 y retorno con S_t < 1.25 durante 2 bloques. La evidencia z_t sale de una sigmoide centrada en 0.60 pp con pendiente 20/pp y de una calibración de Platt (7.0648, −3.4930) ajustada originalmente para otro modelo, así que no es una razón de verosimilitudes calibrada y su ARL0 de diseño nunca se verificó. Su decisión solo se informa (campo CUSUM del DIR).
- También conserva un Random Forest de 45 árboles (profundidad 6) sobre cinco características espectrales normalizadas (A55/A_fund, A65/A_fund, A50/A_fund, A70/A_fund y un índice de bandas laterales). Su probabilidad (P_RF) se queda en ~40–50 % tanto con el motor sano como con falla: no aporta información y no participa en la decisión.
- Los bloques con un cambio de V2 mayor del 2 % de |V1| se marcan como evento de red ([RED]) y se excluyen del CUSUM heredado; el detector direccional no usa esa exclusión.

## 24. Comportamiento del motor sano por nivel de carga

- Medianas de los registros de 60 min con el motor sano y el lazo desconectado (15-oct-2026 al 25, 50 y 75 %; 16-oct-2026 al 0 %), firmware final. Corrientes RMS por fase IA/IB/IC: 0 % = 3.94/4.12/3.75 A; 25 % = 4.18/4.40/4.16 A; 50 % = 4.66/4.98/4.82 A; 75 % = 5.34/5.81/5.27 A.
- |I1| (secuencia positiva, A pico): 0 % = 5.55; 25 % = 5.99; 50 % = 6.80; 75 % = 7.73.
- Voltajes VA/VB/VC: 0 % = 124.0/123.7/124.9 V; 25 % = 116.9/127.0/129.4 V; 50 % = 122.9/122.7/123.3 V; 75 % = 113.6/128.3/126.3 V (ver la cautela sobre los voltajes, sección 4).
- Desbalance de voltaje U2V (mediana): 0 % = 1.13 %; 25 % = 0.61 %; 50 % = 1.00 %; 75 % = 3.65 % (máximo 5.97 %). Asimetría de corriente U2I (mediana): 0 % = 0.38 %; 25 % = 2.59 %; 50 % = 3.96 %; 75 % = 2.68 %.
- Ruido de la proyección P del motor sano (desviación estándar): 0 % = 0.249 pp; 25 % = 0.128 pp; 50 % = 0.126 pp; 75 % = 0.134 pp. Bloques sueltos con P ≥ 0.40 pp: 5.6 % al 0 %, 0.6 % al 25 %, 0.5 % al 50 % y 1.2 % al 75 %. En vacío el ruido es casi el doble que con carga.
- Corrientes típicas al 0 % en otros días: 3.86/4.03/3.66 A durante el calentamiento del 16-oct; 3.71–3.79 A en IA el 15-oct. Al 75 %, ≈ 5.1/5.7/5.1 A.

## 25. Ruido de la firma y su mecanismo

- Con los datos de motor sano del 12-oct-2026 en las 4 cargas, la proyección P tiene σ = 0.256 pp: el umbral de 0.40 pp queda a solo ~1.6 σ.
- Los bloques consecutivos están correlacionados (autocorrelación 0.53 a 1 bloque y 0.21 a 2 bloques). Con bloques independientes, la persistencia de 3 dejaría ~0.35 eventos en 90 min; se observaron 10–11.
- Desviación de Allan de P (pp) a τ = 1.7, 3.4, 6.8, 13.6, 27.2, 54.4 y 108.8 s: al 25 % 0.179, 0.172, 0.137, 0.115, 0.081, 0.065, 0.067; al 50 % 0.141, 0.139, 0.118, 0.098, 0.089, 0.075, 0.066; al 75 % 0.159, 0.145, 0.123, 0.110, 0.097, 0.078, 0.081; al 0 % 0.156, 0.152, 0.124, 0.115, 0.130, 0.171, 0.229.
- Lectura: el ruido no es blanco. Promediar 2 bloques no lo reduce; de 3.4 a ~50 s baja con pendiente ≈ −0.25 (de 1.7 a 54 s baja ×2.3, cuando con ruido blanco bajaría ×5.7); más allá aparece deriva, y al 0 % ya desde ~14 s. Alargar la referencia de 11 a 30 s solo baja σ de 0.256 a 0.233 pp. La mejor desviación alcanzable es ~0.07–0.08 pp a 50–100 s.
- Origen: fluctuaciones lentas; no se separó si vienen de los sensores, del motor o de la red. La conexión de la instrumentación es la causa más documentada (sección 10). Compensar con V2 no ayuda (V2 explica el 3.9 % de la varianza).

## 26. Firma de falla medida por clase y carga (Tabla A)

- Dataset de pares entrelazados SANO/FALLA (un bloque sano seguido de uno con el SSR encendido), calibración del 06-oct-2026, 597 pares, capturados el 06, 07 y 08-oct-2026. Firma = |ΔR2|/|I1| en pp, dirección respecto a arg(V1).
- LEVE (≈ 7.0 %), mediana y rango: 0 % 0.95 pp (0.77–1.11), −80.4°; 25 % 0.82 (0.48–1.32), −80.7°; 50 % 0.69 (0.25–1.17), −81.6°; 75 % 0.65 (0.31–0.88), −75.9°.
- INTER (≈ 14.3 %): 0 % 3.71 pp (3.35–4.28), −82.4°; 25 % 3.16 (2.70–3.41), −81.3°; 50 % 2.38 (2.04–2.86), −78.6°; 75 % 2.14 (1.93–2.45), −80.7°.
- SEVERA (≈ 21.6 %): 0 % 7.10 pp (6.00–7.74), −85.1°; 25 % 6.99 (6.44–7.38), −83.6°; 50 % 5.57 (4.80–6.10), −83.8°; 75 % 5.21 (4.66–5.49), −82.7°.
- |I1| mediana (A pico): ≈ 5.5–5.7 al 0 %, 6.0–6.1 al 25 %, 7.0–7.1 al 50 % y 7.7–7.8 al 75 %.
- Lo que muestran: la dirección es estable; la magnitud crece con la severidad y baja con la carga; las clases no se traslapan en ninguna carga (máximo LEVE 1.32 < mínimo INTER 1.93; máximo INTER 4.28 < mínimo SEVERA 4.66).
- Repetición LEVE 75 % en otra sesión (07-oct, 10 pares): 0.67 pp a −74°, coincide con 0.65 pp del 06-oct.
- La LEVE más pequeña al 75 % (0.65 pp) queda a ~2.5 σ del ruido del motor sano: por eso la detección de LEVE con carga alta es la más difícil.

## 27. Efecto de la falla en la corriente de secuencia positiva

- Durante la falla, |I1| sube ligeramente. Medianas en los datos continuos al 75 % (estudio 1): LEVE +0.29 %, INTER +1.90 %, SEVERA +5.05 %. En vacío, la falla LEVE no sube |I1| (+0.00 %, pares del dataset).
- Este efecto depende de la resistencia limitadora del banco (la potencia que disipa el lazo) y se confunde con un aumento de carga. Por eso no se usa para detectar: un modelo que lo aprendió falló a baja carga (sección 30).

## 28. Validación ciega en vivo del detector

- Método: plan aleatorio de pruebas reales (pulso de ~11 s con el SSR) y simuladas (sin pulso), con semilla registrada; la decisión la toma el firmware; una prueba cuenta como detectada si hay alarma confirmada entre el inicio y el fin del pulso más 2 s. Concordancia PC/firmware de 100 % de los bloques en todas las sesiones con el firmware final (salvo 3 bloques de arranque el 09-oct).
- 75 % de carga, firmware final: SEVERA (08-oct) 10/10 detectadas, 10/10 simuladas sin alarma, 10/10 severidad correcta, 10/10 enclavadas, liberación 5.1–6.1 s. INTER (09-oct) igual: 10/10, 10/10, 10/10, 10/10, 5.1–6.1 s.
- 75 %, LEVE: validada con versiones anteriores del detector (07-oct: 19/20 reales y 20/20 simuladas con el detector en la PC; 9/10 y 10/10 con el detector embebido sin enclavamiento). Falta un bloque LEVE completo al 75 % con el firmware final por fallas del lazo.
- 0 y 25 % de carga, firmware final (15-oct, validación ciega 2): LEVE 0 % 20/20 detectadas (3 alarmas en 20 simuladas y 13/20 severidad correcta, por el escalón de IA de las 11:59:38); INTER 0 % 9/10 (la que faltó no condujo; 5 INTER y 4 SEVERA); LEVE 25 % 20/20, 20/20 simuladas sin alarma, 20/20 LEVE; INTER 25 % 10/10, 10/10, 10/10 INTER.
- Lectura: la detección del firmware final funciona a 0, 25 y 75 % con los mismos parámetros; al 50 % solo hay datos de motor sano.

## 29. Falsas alarmas en operación continua

- Criterio declarado: como máximo 1 falsa alarma por hora. NO se cumple.
- 12-oct-2026: 90 min de motor sano (22.5 min a 25, 50, 75 y 0 %): 11 falsas alarmas, 7.3/h (IC 95 % 3.7–13.1/h); por tramo 2/2/4/3. Una quedó enclavada 972.6 s y escaló a INTER; otra se liberó con 'r' a los 63.3 s.
- 15 y 16-oct-2026: 4.9 h (60 min en cada carga más los periodos sin pulso de las sesiones con falla): 20 falsas alarmas del firmware, 4.1/h (IC 95 % 2.5–6.3/h). Por carga con el motor sano: 25 % = 1; 50 % = 0; 75 % = 5; 0 % = 12 (12/h, todas LEVE, 4 enclavadas más de 60 s).
- Casi todas son LEVE y se liberan solas en menos de 20 s. En total hubo 6 reinicios con 'r' en 31 falsas alarmas.
- Para demostrar ≤ 1 FA/h con 95 % de confianza harían falta 3.0 h sin eventos (4.7 h con 1 evento, 6.3 h con 2); un sistema desatendido necesitaría del orden de ≤ 1 por semana.
- Variantes evaluadas fuera de línea: subir el umbral o la persistencia no mejora (el firmware ya está en el óptimo de su familia). Una compuerta por ángulo (|Q| ≤ tan 35°·P) más 4 bloques para LEVE redujo las falsas alarmas de 12 a 3 (post hoc) y de 11 a 7 en datos nuevos, sin perder detección; es un indicio, no una confirmación.

## 30. Aprendizaje automático para detectar: por qué la detección es una regla física

- Julio–septiembre de 2026: XGBoost y Random Forest con características MCSA llegaron a 96.68 % con partición aleatoria, pero no se transfirieron entre campañas independientes. Las condiciones de captura (cada clase en un día distinto, voltajes distintos por carga, ventanas consecutivas repartidas) les permitían reconocer la sesión.
- Estudio 2 (14-oct, protocolo declarado): un Random Forest con características MCSA absolutas, entrenado al 75 %, detectó 0 de 450 fallas en las otras cargas, porque aprendió el nivel de corriente, es decir, la carga. Con características espectrales relativas quedó al nivel del azar incluso dentro del 75 %. Con características de Fortescue y pares limpios, el Random Forest generalizó igual que la regla.
- Validación ciega 2 (15–16 oct, protocolo declarado): un Random Forest con características de Fortescue, entrenado con datos continuos con fallas solo al 75 %, dio menos falsas alarmas que la regla (2 frente a 21 en 4.9 h), pero detectó solo 4/20 LEVE al 0 % y 1/20 al 25 %, frente a 20/20 y 20/20 de la regla. Aprendió a usar el aumento de |I1| (sección 27), que no existe en vacío.
- Conclusión del proyecto: la detección usa la regla física de secuencia negativa (dos parámetros con significado físico, dirección estable en todas las cargas). El aprendizaje automático se usa en la severidad (umbrales aprendidos) y la IA generativa en las recomendaciones del asistente.

## 31. Telemetría serie del firmware

- Una línea `[MCSA]` por bloque (~1.7 s) a 115200 baud. Campos principales: Motor (OFF/WARMUP/ON); voltajes VA, VB, VC y corrientes IA, IB, IC en RMS; amplitudes espectrales (Afund, A55, A65); P_RF y P_E2 (detectores heredados); SSR (OFF o F1(LEVE)); U2V, U2I, E2 (residuo escalar en %), DOM (1 si U2V ≤ 6 %); bloque HR (bandas MCSA en dB, SNR, s, SOK, f0); CUSUM (S, Pcal); DE2, dV2, ANG (residuo vectorial heredado).
- Bloque RAW: R2 (parte real e imaginaria, A pico, referido a arg(V1)), |I1| (A pico), V2 (V pico) y |V1| (V pico). Son los fasores crudos que permiten recalcular el detector fuera de línea.
- Bloque DIR del detector que decide: P (proyección contra la referencia móvil, pp), R (racha), C (1 = alarma confirmada y enclavada), REF (1 = hay referencia), CUSUM (decisión heredada, informativa), SEV (0–3), ML (magnitud contra la base congelada, pp) y PL (proyección contra la base congelada, pp).
- Otros mensajes: `[DEBUG SSR]` (solicitudes, rechazos y apagados del SSR), `[MOTOR_DET]` (detección de motor encendido), `[RED]` (evento de red), `[Zero SSR]` (lógica del CUSUM heredado).
- Comandos de un carácter: '1' enciende el SSR del lazo; '0' lo apaga; 'r' reinicia el detector (libera una alarma enclavada); 'P' ángulos corriente-voltaje por fase; 'W' volcado de 2048 muestras crudas de IA, IB e IC; 'f' espectro; 's' resumen JSON; 'D' diagnóstico de la pantalla; 'a'–'d' vistas de la pantalla.
- Comandos que no deben usarse en operación normal: 'k' (comisionamiento) y 'K' (borra el comisionamiento), 'n' (guarda una calibración nominal), 'b' (reinicia el ESP32), 'h'/'l' (fuerzan el GPIO 8 sin las protecciones), 'p' (invierte la polaridad del relevador), '2' y '3' (salidas sin lazo conectado).

## 32. Interacción con la aplicación MotorGuard-ITF

- La aplicación lee la telemetría por el puerto USB serie y solo envía tres comandos: '1' y '0' (encender y apagar el SSR del lazo) y 'r' (liberar una alarma enclavada). Al conectar y al cerrar envía '0'. Solo un programa puede tener abierto el puerto a la vez.
- Botón «Liberar alarma» (desde el 16-oct-2026): envía 'r', que reinicia el detector del firmware (desbloquea la alarma y recalcula la referencia; no toca el SSR). Solo se habilita con una alarma enclavada, el motor en ON y sin pulso, captura ni otra operación serie en curso, y pide confirmar con una casilla obligatoria. Advertencia del propio diálogo: si la falla es real y persiste, después de liberar el detector puede tardar en volver a alarmar o no volver a hacerlo, porque la nueva referencia ya incluye la falla. La alarma queda registrada como «liberada manualmente (r)». Está pensado para falsas alarmas enclavadas (sección 20), no para silenciar una alarma que no se ha investigado.
- Inyección desde la aplicación: pide una confirmación con tres casillas, bloquea la inyección con el motor apagado y durante el calentamiento (WARMUP), y tiene un botón PARO en la barra superior. En la prueba en el banco del 13-oct-2026 el PARO apagó el SSR en 0.04 s.
- La aplicación muestra las decisiones del firmware; no decide por su cuenta. El plano de la firma dibuja z, la referencia, dz, la dirección −81.4°, el umbral y la base congelada a partir del bloque RAW.
- El asistente (esta función de la aplicación) no diagnostica: da apoyo para la inspección y el mantenimiento con base en los documentos indexados.

## 33. Procedimiento de una sesión en el banco

- 1) Motor apagado y alimentación cortada: colocar la carga (resistencias del generador) y, si habrá inyección, los taps de la clase deseada, revisando el fusible y las terminales de la resistencia.
- 2) Conectar el USB, verificar el puerto (/dev/ttyACM0) y que ningún otro programa lo use. En pruebas largas, impedir que la computadora se suspenda.
- 3) Prueba de provocación de las conexiones de la instrumentación.
- 4) Encender el motor y esperar ~5 min (el firmware tiene 60 s de WARMUP, pero las falsas alarmas de arranque duran más). Verificar que las corrientes correspondan a la carga (sección 24).
- 5) Si hay inyección: confirmar que nadie toca el lazo; pulso de prueba aislado con la pinza; comprobar que el sistema confirma la clase esperada; si no, revisar los taps antes de empezar.
- 6) Durante la sesión: pinza al inicio, a la mitad y al final; enfriamiento entre pulsos; registrar incidencias en una bitácora con la hora.
- 7) Al terminar: SSR apagado ('0'), cerrar el puerto, apagar el motor.

## 34. Línea de tiempo del sistema

- Junio–julio 2026: verificación de los seis canales sobre una carga resistiva de 100 Ω (junio); calibración del canal de la fase C contra osciloscopio, caracterización de los taps con el LCR, sustitución del SSR dañado y un primer XGBoost SANO/LEVE con 199 muestras de un canal (julio).
- Agosto–septiembre 2026: XGBoost de 4 clases (3160 muestras), Random Forest binario embebido, validación agrupada y prueba de transferencia entre campañas (falló).
- Hasta el 01-oct-2026: componentes simétricas con detector CUSUM, luego residuo vectorial; hallazgo de las conexiones de la protoboard como fuente principal de ruido.
- 06–08 oct 2026: recalibración, dataset multiclase de 597 pares, detector direccional embebido (07-oct), clasificador de severidad y firmware final con enclavamiento y severidad (08-oct, `299a943`).
- 08–09 oct: validación ciega SEVERA e INTER al 75 %. 12-oct: prueba larga sin falla (7.3 FA/h). 13-oct: análisis del ruido, prueba de la aplicación en el banco. 14-oct: estudio 2 de generalización entre cargas. 15–16 oct: validación ciega 2 (detección a 0 y 25 %, 4.9 h de motor sano).

## 35. Limitaciones y lo que no se ha medido

- Un solo motor y un solo banco; fallas emuladas solo en la fase C, por taps fijos, con una resistencia de 5 Ω que limita la corriente del lazo. No se probaron otros motores, otras potencias, alimentación por variador de frecuencia ni fallas reales de aislamiento.
- Falsas alarmas: 4–7 por hora con el firmware actual, lejos del criterio de ≤ 1/h. Es la limitación principal.
- No evaluado: escalones de carga en caliente, fallas en las fases A o B, el 100 % de carga, operación de muchas horas sin supervisión, temperatura del motor.
- Severidad: depende de la corriente del lazo y está confundida con el día de captura.
- Voltajes: los canales ZMPT101B no están verificados contra instrumento con el firmware final; el desbalance de voltaje reportado puede incluir error de medición.
- Escalones espontáneos de corriente y alarmas atascadas sin liberación automática en el firmware.
- El deslizamiento estimado no es confiable y las características MCSA no detectan la falla en este banco.

## 36. Glosario de variables y unidades

- pp: puntos porcentuales de |I1|. Una firma de 1 pp equivale a una corriente de secuencia negativa igual al 1 % de la corriente de secuencia positiva.
- I1, V1: fasores de secuencia positiva de corriente y voltaje (A pico, V pico). I2, V2: secuencia negativa. arg(V1) es la referencia angular de todo el sistema.
- R2: residuo de secuencia negativa I2 − Y2·V2 − I2,0. z = 100·R2/|I1|. dz: cambio de z contra la referencia de 6–11 s.
- P: proyección de dz sobre −81.4°. R: racha de bloques con P ≥ 0.40 pp. C: alarma confirmada y enclavada. ML y PL: magnitud y proyección de la firma contra la base congelada. SEV: 1 LEVE, 2 INTER, 3 SEVERA.
- U2V = |V2|/|V1|, desbalance de voltaje (%). U2I = |I2|/|I1|, asimetría de corriente (%).
- μ: fracción de espiras en corto (0.070, 0.143, 0.216). I_f: corriente del lazo de falla medida con pinza (A RMS).
- Bloque: 4096 muestras por canal a 2403.846 Hz, 1.70 s. WARMUP: 60 s después de detectar el motor encendido. FA/h: falsas alarmas por hora de motor sano.
