#!/usr/bin/env python3
"""
Congela los modelos de la validacion ciega 2 ANTES de capturar los datos nuevos (14-oct-2026).
- RF del estudio 1 (PROTOCOLO_COMPARACION_ML.md, 459bee9): mismos hiperparametros y caracteristicas,
  entrenado con los 13 grupos completos; punto de operacion s = 0.55, k = 3 (el elegido en el estudio 1).
- Se corre con /usr/bin/python3 (scikit-learn 1.7.2), igual que el estudio 1 y el estudio 2.
"""
import hashlib, json, os, sys
from datetime import datetime
import joblib, numpy as np, sklearn
from sklearn.ensemble import RandomForestClassifier
sys.path.insert(0, os.path.expanduser('~'))
import comparacion_ml_deteccion as C

D = os.path.dirname(os.path.abspath(__file__))
datos = C.construir(C.GRUPOS)
X = np.array([f['x'] for d in datos.values() for f in d['filas'] if f['y'] is not None])
y = np.array([f['y'] for d in datos.values() for f in d['filas'] if f['y'] is not None])
rf = RandomForestClassifier(n_estimators=300, max_depth=6, class_weight='balanced', min_samples_leaf=5,
                            n_jobs=-1, random_state=0).fit(X, y)
ruta = os.path.join(D, 'rf_estudio1_13grupos.joblib')
joblib.dump(rf, ruta)
sha = hashlib.sha256(open(ruta, 'rb').read()).hexdigest()
meta = dict(fecha=datetime.now().isoformat(timespec='seconds'), python=sys.version.split()[0],
            sklearn=sklearn.__version__, numpy=np.__version__, archivo=os.path.basename(ruta), sha256=sha,
            umbral_s=0.55, persistencia_k=3, caracteristicas=C.nombres(), n_filas=int(len(y)), n_falla=int(y.sum()),
            grupos=[g[0] for g in C.GRUPOS], hiperparametros=rf.get_params())
json.dump(meta, open(os.path.join(D, 'rf_estudio1_13grupos.json'), 'w'), indent=1, default=str)
print(json.dumps({k: meta[k] for k in ('python', 'sklearn', 'sha256', 'n_filas', 'n_falla')}))
