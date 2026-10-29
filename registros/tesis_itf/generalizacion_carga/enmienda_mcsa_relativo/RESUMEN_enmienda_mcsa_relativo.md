# Enmienda al estudio 2: RF-MCSA con características espectrales relativas (14-oct-2026)

- **Protocolo:** `~/PROTOCOLO_GENERALIZACION_CARGA_ENMIENDA.md` (commit `dd93b67`), declarado antes de correr y después de conocer el estudio 2.
- **Script:** `~/analisis_generalizacion_carga_enmienda.py`.
- **Resultados:** `resultado_enmienda_mcsa_relativo.json`; con el sufijo `_venv`, la robustez.
- **Entorno:** `/usr/bin/python3` (scikit-learn 1.7.2); robustez con el venv (1.9.0), con las mismas conclusiones.

**Características (c′):**
- A_55/A_fund y A_65/A_fund;
- hr_l2sm, hr_l2sp, hr_lrm, hr_lrp, hr_l3, hr_l3rm, hr_l3rp y hr_snr2s (dB relativos);
- la fase crítica en *one-hot*.

Sin RMS, A_fund, deslizamiento ni f0.

## Resultado: al nivel del azar en todos los esquemas, incluso dentro de la distribución

| Esquema | Carga de prueba | LEVE (rango con 10 semillas) | INTER | SEVERA | FP SANO | Exactitud bal. | AUC SANO/LEVE |
|---|---|---|---|---|---|---|---|
| E0 (dentro del 75 %) | 75 % | 31/60 (29–32) | 28/50 | 34/47 | 78/150 | 0.536 | 0.50 |
| E1 | 0 % | 15/50 (13–22) | 18/50 | 18/50 | 41/145 | 0.529 | 0.51 |
| E1 | 25 % | 20/50 (18–23) | 23/50 | 19/50 | 61/146 | 0.498 | 0.50 |
| E1 | 50 % | 20/50 (19–25) | 26/50 | 18/50 | 54/147 | 0.530 | 0.54 |
| E2 | 0 % | 19/50 (17–22) | 25/50 | 20/50 | 64/145 | 0.493 | 0.48 |
| E2 | 25 % | 24/50 (22–24) | 37/50 | 35/50 | 80/146 | 0.546 | 0.45 |
| E2 | 50 % | 29/50 (27–30) | 32/50 | 39/50 | 83/147 | 0.551 | 0.46 |
| E2 | 75 % | 34/60 (29–35) | 24/50 | 25/47 | 73/150 | 0.521 | 0.53 |

Las importancias quedan repartidas de forma casi uniforme (0.07–0.13 cada una), sin ninguna característica dominante.

## Lectura (la fijada en el protocolo)
- **"(c′) tampoco generaliza":** con un solo bloque de 1.70 s, las características espectrales relativas que registra el firmware no separan las fallas de este banco ni siquiera dentro del 75 %.
- **No es un problema de generalización** (E0 ya está al azar). Es que esas características **no contienen la firma** en este banco y con esta adquisición.

**Causas posibles (no probadas):**
- la fase analizada cambia en cada bloque (≈ 1/3 A/B/C);
- la falla está limitada a 5 Ω;
- la resolución espectral es de 0.59 Hz.

**Para el artículo:**
- el RF-MCSA absoluto (c) fallaba entre cargas porque aprendía la carga;
- el relativo (c′) no aprende nada útil;
- en ningún caso las MCSA convencionales registradas igualan a las características de secuencia negativa.

Esto **no** demuestra que el MCSA no sirva en general: es un resultado con las características y la adquisición de este sistema.
