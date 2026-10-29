# Diagnóstico del LEVE 0 % = 17/50 (14-oct-2026; POST HOC, no declarado)

- **Script:** `diagnostico_17de50.py`.
- **Salidas:** `diagnostico_17de50_sklearn172.txt` y `diagnostico_17de50_sklearn190.txt`.
- **Método:** el RF del estudio 1 (13 grupos continuos, fallas solo al 75 %) se aplica a los pares del dataset con la aproximación de `exploracion_rf_cargas_pares.py`, con 10 semillas.

**LEVE detectadas por carga** (rango entre las 10 semillas; scikit-learn 1.7.2 / 1.9.0):

| Variante del RF | LEVE 0 % | LEVE 25 % | LEVE 50 % | LEVE 75 % |
|---|---|---|---|---|
| (a) como el 12-oct | 15–20 / 19–24 | 34–39 / 37–43 | 51 / 51 | 49 / 49 |
| (b) sin las columnas ΔI1 | **50 / 50** | 49–50 / 50 | 49–50 / 50 | 48 / 48 |
| (c) solo el bloque actual, con ΔI1 | **8–9 / 9** | 28 / 31–35 | 50 / 51 | 48–49 / 49 |
| (d) solo el bloque actual, sin ΔI1 | 50 / 50 | 46 / 47 | 50 / 50 | 44 / 45–46 |
| Regla P ≥ 0.40 × 3 | 50 | 50 | 51 | 48 |

INTER y SEVERA: iguales en todas las variantes (detalle en los `.txt`).

## Lectura (orientativa)
- **La caída se debe a ΔI1, no al relleno de rezagos de la aproximación:**
  - quitar ΔI1 la elimina por completo, en (b) y en (d);
  - quitar los rezagos y dejar ΔI1 la empeora, en (c).
- **El RF entrenado con datos continuos al 75 %** usa "|I1| sube" como evidencia de falla, y en vacío la falla LEVE no sube |I1| (+0.00 %).
- **Por qué el estudio 2 no lo reprodujo:** su RF se entrena con pares filtrados por calidad, donde P sola separa todo y el RF no necesita ΔI1. **El atajo depende de con qué datos se entrena el modelo.**
- **Sigue siendo una aproximación por pares, no declarada.** La prueba ciega es la H2 de `PROTOCOLO_VALIDACION_CIEGA_2.md` (commit `54ecef3`): LEVE en continuo a 0 y 25 %, con el RF congelado.
