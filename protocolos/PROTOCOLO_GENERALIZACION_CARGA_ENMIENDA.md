# Enmienda al estudio 2: RF-MCSA con características espectrales relativas (declarada 14-oct-2026)

**Tipo:** enmienda al estudio fuera de línea de `PROTOCOLO_GENERALIZACION_CARGA.md` (commit `61c09f1`). Se
declara con el commit de este archivo, **después** de conocer los resultados del estudio 2 (commit
`7719748`) y antes de correr esta enmienda.
- Script nuevo, que solo lee: `~/analisis_generalizacion_carga_enmienda.py`. Reutiliza las funciones de
  `~/analisis_generalizacion_carga.py` sin modificarlo.
- Salida: `~/tesis_itf/generalizacion_carga/enmienda_mcsa_relativo/`.

## Por qué
En el estudio 2, el RF-MCSA (c) usó niveles **absolutos**: RMS, A_fund y amplitudes de bandas. Sus
importancias (I_rms 0.30, `ia` 0.29) muestran que aprendió la carga, y falló por completo entre cargas.
Un revisor podría objetar con razón que es un "hombre de paja": el MCSA convencional normaliza las
bandas a la fundamental. Esta enmienda evalúa esa versión.

## Método nuevo (c′): RF-MCSA relativo
Mismas filas, esquemas (E0, E1, E2), hiperparámetros, umbral 0.5, semillas 0–9, métricas y entorno
(`/usr/bin/python3`, scikit-learn 1.7.2) que el estudio 2. Robustez con el venv, como en el estudio 2.

**Características**, todas de cada bloque (sin referencia):
- A_55/A_fund y A_65/A_fund (amplitud de los picos en las bandas de 55 y 65 Hz, normalizada a la fundamental);
- hr_l2sm, hr_l2sp, hr_lrm, hr_lrp, hr_l3, hr_l3rm, hr_l3rp: niveles en dB relativos a la fundamental
  estimada (`mcsa_hr.h`: L_x = 20·log10(A_x/A_0));
- hr_snr2s: dB sobre el piso local;
- la fase crítica en *one-hot*, como en (c).

**Se excluyen**, con su motivo:
- RMS, A_fund, `va`, `vb` y V_rms: niveles absolutos;
- hr_s: deslizamiento estimado, que depende de la carga; además, en el dataset casi siempre viene del respaldo (`hr_sok` = 0 en 2/3 de las filas);
- hr_f0: frecuencia de la red, propia de la sesión;
- hr_sok, `p_cal` y `cusum_s`.

## Qué se reporta
- Las mismas tablas del estudio 2 para (c′), junto a (a), (b) y (c) ya publicados.
- McNemar exacto (a) frente a (c′) en las mismas filas, con Holm dentro de cada esquema.
- Importancias del RF (c′), semilla 0.

**Sin hipótesis con criterio:** es descriptivo y secundario. Lectura fijada de antemano:

| Resultado | Lectura |
|---|---|
| (c′) generaliza como (a) y (b) | El fallo de (c) se debe a los niveles absolutos, no al enfoque espectral |
| (c′) tampoco generaliza | Las características espectrales de un bloque, aun relativas, no separan bien las fallas de este banco entre cargas |
| Intermedio | Se reporta tal cual, por carga y severidad |

## Limitaciones (además de las del estudio 2)
- Declarada después de ver el resultado de (c); no es un análisis ciego.
- Las bandas vienen de una fase que cambia en cada bloque (≈ 1/3 A/B/C) y no hay THD.
- hr_l3 tiene valores positivos (mediana +4 a +12 dB respecto a la "fundamental" estimada). Se usa
  como viene del firmware, sin corregirlo.
