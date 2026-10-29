"""
Prueba de integración End-to-End (E2E) para la estación MotorGuard-ITF.
Simula la secuencia experimental completa sin UI gráfica (modo headless / Qt Core):
"Sano L0 -> Captura Baseline -> Cambio Carga L2 -> Inyección Falla Leve -> Severidad -> Falla OFF -> Sano"
Verifica la consistencia matemática, la sincronía de eventos y la generación del CSV.
"""

import os
import csv
import time
import tempfile
import numpy as np
from PySide6.QtCore import QCoreApplication

from motorguard_dashboard.core.config import FS, WINDOW_SIZE, HOP_SIZE, RING_BUFFER_CAPACITY
from motorguard_dashboard.core.ring_buffer import NumPyRingBuffer
from motorguard_dashboard.acquisition.worker import AcquisitionWorker
from motorguard_dashboard.processing.sliding_window import SlidingWindowProcessor
from motorguard_dashboard.processing.baseline_manager import BaselineManager
from motorguard_dashboard.core.events import EventRecorder

def test_full_experimental_sequence():
    # Asegurar que existe instancia de QCoreApplication para señales de Qt
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])

    with tempfile.TemporaryDirectory() as tmpdir:
        ring_buffer = NumPyRingBuffer(capacity=RING_BUFFER_CAPACITY)
        acq_worker = AcquisitionWorker(ring_buffer=ring_buffer, mode="EMULATOR")
        proc_worker = SlidingWindowProcessor(
            ring_buffer=ring_buffer,
            window_size=WINDOW_SIZE,
            hop_size=HOP_SIZE
        )
        baseline_mgr = BaselineManager(persistence_path=os.path.join(tmpdir, "baselines.json"))
        event_recorder = EventRecorder(output_dir=tmpdir)

        # Conectar señales
        acq_worker.sig_data_ready.connect(proc_worker.on_samples_accumulated)
        
        windows_received = []
        deviations_received = []
        
        def on_window(feat):
            windows_received.append(feat)
            devs = baseline_mgr.process_window(feat)
            if devs:
                deviations_received.append(devs)
            if event_recorder.is_recording:
                event_recorder.record_features(feat, devs)
                
        proc_worker.sig_window_processed.connect(on_window)

        def ventanas_nuevas(n=4, limite=20.0):
            """Espera n ventanas procesadas DESPUÉS del cambio (la primera puede mezclar datos de antes) y devuelve
            la última. Antes se dormía 1.6 s fijos: con la CPU cargada la última ventana todavía era del estado
            anterior y la prueba fallaba sin que el código tuviera error (16-oct)."""
            n0 = len(windows_received)
            fin = time.time() + limite
            while len(windows_received) < n0 + n and time.time() < fin:
                app.processEvents()
                time.sleep(0.02)
            assert len(windows_received) >= n0 + n, f"solo llegaron {len(windows_received) - n0} ventanas en {limite} s"
            return windows_received[-1]

        # 1. Iniciar sesión y workers
        csv_path = event_recorder.start_session(session_name="e2e_test_session")
        acq_worker.start()
        proc_worker.start()

        print("\n--- PASO 1: Régimen Sano L0 (0%) y Captura de Baseline (5s) ---")
        baseline_mgr.start_capture(load_level=0, target_windows=10)
        
        # Esperar hasta que se capture el baseline (10 ventanas * 500ms = ~5s)
        t_start = time.time()
        while baseline_mgr.is_capturing and (time.time() - t_start < 30.0):
            app.processEvents()
            time.sleep(0.05)
            
        assert not baseline_mgr.is_capturing, "La captura de baseline debió completarse"
        assert 0 in baseline_mgr.profiles, "Perfil L0 debe existir"
        prof_l0 = baseline_mgr.profiles[0]
        print(f"✓ Baseline L0 capturado: I_prom={prof_l0.means['I_prom']:.2f}A, I_unb={prof_l0.means['I_unb']:.2f}%")

        print("\n--- PASO 2: Cambio de Carga a L2 (50% Media) ---")
        acq_worker.set_load(2)
        event_recorder.record_event("CAMBIO_CARGA", "Aumento de carga a L2 (50%)", ring_buffer._total_samples, load_level=2)
        
        # Verificar que I_prom subió hacia ~5.6 A pero I_unb se mantiene bajo
        latest_feat = ventanas_nuevas()
        print(f"✓ Post-carga: I_prom={latest_feat.I_prom:.2f}A (esperado ~5.6A), I_unb={latest_feat.I_unb:.2f}%")
        assert latest_feat.I_prom > 5.2, f"I_prom debió aumentar, dio {latest_feat.I_prom}"
        assert latest_feat.I_unb < 2.5, f"I_unb debió mantenerse bajo, dio {latest_feat.I_unb}"

        print("\n--- PASO 3: Inyección de Falla ITF Leve ---")
        acq_worker.set_fault(1)
        event_recorder.record_event("INYECCION_FALLA", "Falla ITF Leve inyectada", ring_buffer._total_samples, fault_class=1)
        
        latest_fault_feat = ventanas_nuevas()
        print(f"✓ Con Falla Leve: I_unb={latest_fault_feat.I_unb:.2f}%, A65={latest_fault_feat.A_65:.3f}A")
        assert latest_fault_feat.I_unb > 4.0, f"I_unb debe superar 4% ante falla, dio {latest_fault_feat.I_unb}"
        assert latest_fault_feat.A_65 > 0.08, f"A65 debe aumentar ante falla, dio {latest_fault_feat.A_65}"

        print("\n--- PASO 4: Aumento de Severidad a Severa ---")
        acq_worker.set_fault(3)
        event_recorder.record_event("AUMENTO_SEVERIDAD", "Severidad elevada a SEVERA (Tap 1-4)", ring_buffer._total_samples, fault_class=3)
        
        latest_severe = ventanas_nuevas()
        print(f"✓ Con Falla Severa: I_unb={latest_severe.I_unb:.2f}%, A65={latest_severe.A_65:.3f}A")
        assert latest_severe.I_unb > latest_fault_feat.I_unb, "Falla severa debe inducir mayor desbalance"

        print("\n--- PASO 5: Retiro de Falla (Falla OFF / Sano) ---")
        acq_worker.set_fault(0)
        event_recorder.record_event("FALLA_OFF", "Retiro de falla, motor sano", ring_buffer._total_samples, fault_class=0)
        
        recovered = ventanas_nuevas()
        print(f"✓ Recuperado: I_unb={recovered.I_unb:.2f}%, A65={recovered.A_65:.3f}A")
        assert recovered.I_unb < 2.5, f"I_unb debió normalizarse a < 2.5%, dio {recovered.I_unb}"

        # 6. Detener workers y cerrar sesión
        acq_worker.stop()
        proc_worker.stop()
        saved_csv = event_recorder.stop_session()

        # 7. Validar el archivo CSV generado
        assert os.path.exists(saved_csv)
        with open(saved_csv, "r", encoding="utf-8") as f:
            lines = list(csv.reader(f))
            header = lines[0]
            data_rows = lines[1:]
            
        print(f"✓ CSV validado: {len(data_rows)} filas grabadas sincronizadamente.")
        assert len(data_rows) >= 20, f"Debe haber al menos 20 filas registradas, hay {len(data_rows)}"
        assert header[0] == "clase"
        assert header[1] == "label"
        assert header[7] == "I_rms"
        assert header[9] == "A_65"
        assert header[15] == "I_unb"
        assert header[-1] == "active_event"

        print("\n=======================================================")
        print("🎉 TEST E2E PIPELINE COMPLETO Y EXITOSO AL 100%")
        print("=======================================================")

if __name__ == "__main__":
    test_full_experimental_sequence()
