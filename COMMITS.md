# Commits citados en la tesis

La tesis cita estos identificadores de commit como evidencia de fecha. Pertenecen al repositorio de trabajo del autor, que no se publica porque contiene archivos personales. Esta tabla se generó con `git show --name-status` sobre ese repositorio el 29-10-2026. Si el comité lo pide, el historial completo se entrega por un medio privado como *bundle* de git (`git clone motorguard_todo.bundle`).

## `299a943` — 2026-10-08 15:57 -0600

**Hash completo:** `299a94361306ecfac383124a64d7a1c3b46cdcfd`  
**Mensaje:** feat(firmware): enclavamiento de la alarma y clasificacion de severidad embebida

**Archivos:**

- M `Arduino/PRUEBA_MODELO_1/PRUEBA_MODELO_1.ino`
- M `Arduino/PRUEBA_MODELO_1/detector_dir.cpp`
- M `Arduino/PRUEBA_MODELO_1/detector_dir.h`

## `2dff915` — 2026-10-06 14:54 -0600

**Hash completo:** `2dff9154bdff07bb9db157a592e8034a9d277c5c`  
**Mensaje:** fix(banco): recalibracion de corrientes y comandos de diagnostico por fase

**Archivos:**

- M `Arduino/PRUEBA_MODELO_1/PRUEBA_MODELO_1.ino`
- M `Arduino/PRUEBA_MODELO_1/secuencia.cpp`
- M `Arduino/PRUEBA_MODELO_1/secuencia.h`

## `81657f4` — 2026-10-07 14:33 -0600

**Hash completo:** `81657f413c537814e449477533ea1ce04abbe2bf`  
**Mensaje:** feat(firmware): detector direccional embebido como decision principal

**Archivos:**

- M `Arduino/PRUEBA_MODELO_1/PRUEBA_MODELO_1.ino`
- A `Arduino/PRUEBA_MODELO_1/detector_dir.cpp`
- A `Arduino/PRUEBA_MODELO_1/detector_dir.h`
- M `validacion_vivo_direccional.py`

## `dcff8fe` — 2026-10-08 15:51 -0600

**Hash completo:** `dcff8fe8810d7f9a04be0120ad74782bd1311b43`  
**Mensaje:** feat(severidad): diseno de entrenamiento y validacion del clasificador de severidad

**Archivos:**

- A `entrenar_severidad.py`

## `7c5707f` — 2026-10-08 16:08 -0600

**Hash completo:** `7c5707f532741ccd30626d005d92eaaab7346b8a`  
**Mensaje:** feat(validacion): v5 puntua severidad, enclavamiento y liberacion del firmware

**Archivos:**

- M `validacion_vivo_direccional.py`

## `9e2968d` — 2026-10-10 17:17 -0600

**Hash completo:** `9e2968dbfdc835d6f01353953969b1fb9765de42`  
**Mensaje:** feat(validacion): prueba larga sin falla para medir falsas alarmas del detector embebido

**Archivos:**

- A `prueba_larga_sin_falla.py`

## `5227223` — 2026-10-11 22:39 -0600

**Hash completo:** `5227223f0723fbd8375b9e984435a341e9e9b83a`  
**Mensaje:** feat(app): preparacion de la prueba en vivo (protocolo, resumen de sesion, aviso de arranque)

**Archivos:**

- A `tesis_itf/motorguard_dashboard/herramientas/resumen_sesion.py`
- M `tesis_itf/motorguard_dashboard/inyeccion/control.py`
- M `tesis_itf/motorguard_dashboard/tests/run_all_tests.py`
- M `tesis_itf/motorguard_dashboard/tests/test_inyeccion.py`
- M `tesis_itf/motorguard_dashboard/ui/monitor_window.py`
- M `tesis_itf/motorguard_dashboard/ui/panel_inyeccion.py`
- M `tesis_itf/motorguard_dashboard/ui/tema.py`
- A `tesis_itf/protocolos/prueba_en_vivo_app.md`

## `f8699ee` — 2026-10-12 13:16 -0600

**Hash completo:** `f8699ee2ed55c17e9cfe78c0d514098308bb064e`  
**Mensaje:** docs(validacion): enmienda al protocolo de la prueba larga (carga no conmutable en caliente)

**Archivos:**

- A `PROTOCOLO_PRUEBA_LARGA_ENMIENDA.md`

## `4f08c86` — 2026-10-12 13:33 -0600

**Hash completo:** `4f08c861f8a4799c002b2cfe4d88edd02bcc18a9`  
**Mensaje:** docs(validacion): regla de alarma atascada (> 60 s -> reinicio con r) para la prueba larga

**Archivos:**

- M `PROTOCOLO_PRUEBA_LARGA_ENMIENDA.md`
- A `reinicio_alarma_atascada.py`

## `459bee9` — 2026-10-12 16:45 -0600

**Hash completo:** `459bee911d06ef084083888e1d29104cddebf2bd`  
**Mensaje:** docs(validacion): protocolo de comparacion regla vs aprendizaje automatico y analisis post hoc con V2

**Archivos:**

- A `PROTOCOLO_COMPARACION_ML.md`
- A `analisis_compensacion_v2.py`
- A `comparacion_ml_deteccion.py`

## `0518dd4` — 2026-10-13 13:42 -0600

**Hash completo:** `0518dd452df030354845cb2e7cc478552fe8282e`  
**Mensaje:** docs(validacion): protocolo del analisis de ruido y variantes del detector (fuera de linea)

**Archivos:**

- A `PROTOCOLO_MEJORA_DETECCION.md`

## `54ecef3` — 2026-10-14 21:34 -0600

**Hash completo:** `54ecef38047e8d5e7c1ee5b9bf5526a137fa1d99`  
**Mensaje:** docs(validacion): protocolo de la validacion ciega 2 (RF congelado frente a la regla de Fortescue)

**Archivos:**

- A `PROTOCOLO_VALIDACION_CIEGA_2.md`
- A `analisis_mejora_deteccion.py`
- A `analisis_validacion_ciega2.py`
- A `tesis_itf/validacion_ciega2/modelos/congelar_modelos.py`
- A `tesis_itf/validacion_ciega2/modelos/rf_estudio1_13grupos.joblib`
- A `tesis_itf/validacion_ciega2/modelos/rf_estudio1_13grupos.json`
- A `tesis_itf/validacion_ciega2/modelos/variante_angulo35_leve4.py`

## `61c09f1` — 2026-10-14 20:50 -0600

**Hash completo:** `61c09f1f0071cccc0eb455bd5a6e2ed12b637908`  
**Mensaje:** docs(validacion): protocolo del estudio 2, generalizacion entre cargas de la regla de Fortescue frente al Random Forest

**Archivos:**

- A `PROTOCOLO_GENERALIZACION_CARGA.md`

## `dd93b67` — 2026-10-14 21:58 -0600

**Hash completo:** `dd93b67e6b30166aef1ce25644d2974f9ec9e879`  
**Mensaje:** docs(validacion): enmienda del estudio 2, RF-MCSA con caracteristicas espectrales relativas

**Archivos:**

- A `PROTOCOLO_GENERALIZACION_CARGA_ENMIENDA.md`

## `769cce9` — 2026-10-15 18:32 -0600

**Hash completo:** `769cce96c52b7fdcb04ceb4324286dbea9f6d092`  
**Mensaje:** docs(validacion): enmienda 1 de la validacion ciega 2 (tramo del 0 % el 16-oct)

**Archivos:**

- M `PROTOCOLO_VALIDACION_CIEGA_2.md`
- M `analisis_validacion_ciega2.py`

## `a0072b8` — 2026-10-29 11:27 -0600

**Hash completo:** `a0072b80c3da1e7a388204b7acf23bb8d9431084`  
**Mensaje:** feat(app): modo demo (--demo) para capturas de la tesis, con tramas reales y etiqueta DEMO

**Archivos:**

- M `tesis_itf/motorguard_dashboard/app.py`
- M `tesis_itf/motorguard_dashboard/tests/run_all_tests.py`
- A `tesis_itf/motorguard_dashboard/tests/simulador_demo.py`
- A `tesis_itf/motorguard_dashboard/tests/test_demo.py`
- M `tesis_itf/motorguard_dashboard/ui/monitor_window.py`

## `d265bc9` — 2026-10-29 12:15 -0600

**Hash completo:** `d265bc991001a8d3b49245dc470d62552d1458d5`  
**Mensaje:** fix(asistente): la conversación vacía ya no dice «todavía no está listo» con el modelo listo

**Archivos:**

- M `tesis_itf/motorguard_dashboard/tests/test_asistente_tab.py`
- M `tesis_itf/motorguard_dashboard/ui/asistente_tab.py`


## Cómo comprobar que los archivos publicados son los de esos commits

Cada archivo de `firmware/` y `app/` es idéntico al del commit indicado. Su identificador de objeto de git (`git hash-object <archivo>`) debe coincidir con el de esta lista, que se tomó del árbol de ese commit.

| Archivo publicado | Commit | Objeto git (SHA-1) |
|---|---|---|
| `firmware/PRUEBA_MODELO_1/PRUEBA_MODELO_1.ino` | `299a943` | `40a785aa7f58bba5e57b93bbce1fc382c949a04b` (original; ver nota) |
| `firmware/PRUEBA_MODELO_1/detector.cpp` | `299a943` | `0f2c6198ca9828468a432b339205bbf3126020c9` |
| `firmware/PRUEBA_MODELO_1/detector.h` | `299a943` | `1ddfc938cface737306d21bce6f977dce380fffb` |
| `firmware/PRUEBA_MODELO_1/detector_dir.cpp` | `299a943` | `0d38f065d01153ac3d665cfa638f48b8e1f1b89f` |
| `firmware/PRUEBA_MODELO_1/detector_dir.h` | `299a943` | `a43992976dbfdf579f1959d32ad010d696a25e7e` |
| `firmware/PRUEBA_MODELO_1/mcsa_hr.cpp` | `299a943` | `9d3df2ff4e46010208b8017a25882b07bb72149d` |
| `firmware/PRUEBA_MODELO_1/mcsa_hr.h` | `299a943` | `c11c3fa7a145a2adef171f97551afd1a8d71ee10` |
| `firmware/PRUEBA_MODELO_1/modelo_rf_esp32.h` | `299a943` | `7fb0bbde65181caa657816408b2adc94a2e7901d` |
| `firmware/PRUEBA_MODELO_1/modelo_rf_flat.cpp` | `299a943` | `58e91d7c4edb3939300fe325c68411b772077880` |
| `firmware/PRUEBA_MODELO_1/modelo_rf_flat.h` | `299a943` | `ad2b810ed331cf3802aceb3666ccd4f47c54672f` |
| `firmware/PRUEBA_MODELO_1/modelo_rf_m2c.cpp` | `299a943` | `4302d7bd92ee04877111c0a101589df01439926b` |
| `firmware/PRUEBA_MODELO_1/secuencia.cpp` | `299a943` | `c83c5cf1da54a8b2665b409f3f3d421a2b4bb68e` |
| `firmware/PRUEBA_MODELO_1/secuencia.h` | `299a943` | `533ad852f00def61615f6af5ed3d1c450256f4e3` |
| `firmware/PRUEBA_MODELO_1/sketch.yaml` | `299a943` | `419374ee4cf8f89d9ee471395468c0644afe74eb` |
| `app/motorguard_dashboard/rag/indice.py` | `d265bc9` | `a33131f7b3ab1670b31e0ecef496e5204bd24b47` |
| `app/motorguard_dashboard/telemetry/alarmas.py` | `d265bc9` | `2db8b4d8c1deaa022ae355c2f73703b1e2005ca0` |

**Nota sobre `PRUEBA_MODELO_1.ino`:** es idéntico al de `299a943` salvo la línea 1365, donde la contraseña del punto de acceso Wi-Fi se reemplazó por `"CAMBIAR_CLAVE"`. El archivo conserva sus 1557 líneas, así que los números de línea citados en el Anexo A no cambian. Por ese cambio, su `git hash-object` no coincide con el objeto original; los otros 13 archivos del firmware sí. El punto de acceso está desactivado en el firmware validado (`HABILITAR_WIFI 0`).
