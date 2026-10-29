"""
Pruebas para EventRecorder: Creación de sesión, marcas de eventos y compatibilidad de CSV.
"""

import os
import csv
import tempfile
import time
import numpy as np
from motorguard_dashboard.core.events import EventRecorder, SESSION_CSV_COLUMNS
from motorguard_dashboard.processing.mcsa_features import compute_window_features
from motorguard_dashboard.core.config import WINDOW_SIZE

def test_event_recorder_lifecycle():
    with tempfile.TemporaryDirectory() as tmpdir:
        recorder = EventRecorder(output_dir=tmpdir)
        csv_path = recorder.start_session(session_name="test_run")
        
        assert os.path.exists(csv_path)
        assert recorder.is_recording
        
        # Inyectar eventos
        e1 = recorder.record_event("CAMBIO_CARGA", "Aumento a L1 25%", sample_index=1200, load_level=1)
        assert e1.load_level == 1
        assert e1.event_type == "CAMBIO_CARGA"
        
        e2 = recorder.record_event("INYECCION_FALLA", "Falla Leve Tap 1-2", sample_index=3600, fault_class=1)
        assert e2.fault_class == 1
        assert e2.event_type == "INYECCION_FALLA"
        
        # Registrar 5 ventanas
        curr = np.ones((3, WINDOW_SIZE), dtype=np.float32) * 4.5
        volt = np.ones((2, WINDOW_SIZE), dtype=np.float32) * 123.0
        
        for i in range(5):
            feat = compute_window_features(curr, volt, i, time.time(), (i + 1) * 1200)
            recorder.record_features(feat)
            
        saved_csv = recorder.stop_session()
        assert not recorder.is_recording
        assert os.path.exists(saved_csv)
        
        # Verificar contenido del CSV
        with open(saved_csv, "r", encoding="utf-8") as f:
            reader = list(csv.reader(f))
            header = reader[0]
            assert header == SESSION_CSV_COLUMNS
            assert len(reader) == 6  # Header + 5 ventanas
            # Verificar primera fila de datos
            row1 = reader[1]
            assert row1[1] == "LEVE"  # Clase activa
            assert row1[2] == "1"     # Carga activa
            assert row1[3] == "25%"   # Carga label
            assert row1[-1] == "INYECCION_FALLA"  # Evento activo
            
        # Verificar archivo JSON de eventos
        json_path = os.path.join(tmpdir, "test_run_events.json")
        assert os.path.exists(json_path)
        print("test_event_recorder_lifecycle PASSED")

if __name__ == "__main__":
    test_event_recorder_lifecycle()
