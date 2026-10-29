"""
Ejecutor de la suite completa de pruebas para MotorGuard-ITF.
"""

import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from motorguard_dashboard.tests.test_ring_buffer import (
    test_ring_buffer_basic, test_ring_buffer_wrap_around, test_ring_buffer_performance
)
from motorguard_dashboard.tests.test_processor import (
    test_pure_sinusoid_fft_accuracy, test_three_phase_unbalance,
    test_mcsa_sidebands_detection, test_computation_latency
)
from motorguard_dashboard.tests.test_baseline import test_baseline_capture_and_zscore
from motorguard_dashboard.tests.test_event_recorder import test_event_recorder_lifecycle
from motorguard_dashboard.tests.test_e2e_pipeline import test_full_experimental_sequence
from motorguard_dashboard.tests import test_telemetry_parser, test_fuente_replay, test_fuente_serie, test_alarmas, test_monitor_window, test_inyeccion, test_panel_inyeccion, test_consultas, test_dashboard, test_tema, test_estabilidad, test_adquisicion, test_adquisicion_tab, test_plano_firma, test_rag, test_asistente_tab, test_demo

def run_all():
    # Una sola aplicación Qt (sin pantalla) para todas las pruebas: la ventana necesita QApplication
    from motorguard_dashboard.tests import qt_util
    qt_util.app()
    print("==================================================")
    print("🚀 EJECUTANDO SUITE COMPLETA DE PRUEBAS MOTORGUARD")
    print("==================================================")
    
    print("\n[1/5] Probando Buffer Circular (NumPyRingBuffer)...")
    test_ring_buffer_basic()
    test_ring_buffer_wrap_around()
    test_ring_buffer_performance()
    
    print("\n[2/5] Probando Procesador MCSA (FFT, Bandas, Desbalance)...")
    test_pure_sinusoid_fft_accuracy()
    test_three_phase_unbalance()
    test_mcsa_sidebands_detection()
    test_computation_latency()
    
    print("\n[3/5] Probando Gestor de Referencias Sanas (BaselineManager)...")
    test_baseline_capture_and_zscore()
    
    print("\n[4/5] Probando Registro de Eventos y Streaming CSV (EventRecorder)...")
    test_event_recorder_lifecycle()
    
    print("\n[5/5] Probando Integración E2E (Secuencia Experimental Completa)...")
    test_full_experimental_sequence()

    print("\n[6/6] Probando Telemetría del firmware 299a943 (parser, reproducción, puerto serie, alarmas y ventana)...")
    test_telemetry_parser.run()
    test_fuente_replay.run()
    test_fuente_serie.run()
    test_alarmas.run()
    test_monitor_window.run()

    print("\n[7/7] Probando Inyección (etapa 2): bloqueos y panel con simulador del firmware...")
    test_inyeccion.run()
    test_panel_inyeccion.run()

    print("\n[8/8] Probando Dashboard (trama, consultas a petición W/f/s)...")
    test_consultas.run()
    test_dashboard.run()

    print("\n[9/9] Probando Tema claro/oscuro (modos, sistema, contraste)...")
    test_tema.run()

    print("\n[10/10] Probando Estabilidad (app.log, rotación, recuperación, instancia, rutas, topes)...")
    test_estabilidad.run()

    print("\n[11/11] Probando Adquisición (pares SANO/FALLA, base sin falla, equivalencia con el dataset real)...")
    test_adquisicion.run()
    test_adquisicion_tab.run()

    print("\n[12/12] Probando Plano de la firma (método del detector, contra logs reales)...")
    test_plano_firma.run()

    print("\n[13/13] Probando Asistente RAG (ingesta, índice, citas, llama-server falso, proveedor externo)...")
    test_rag.run()
    test_asistente_tab.run()

    print("\n[14/14] Probando el modo demo (simulador con tramas reales, solo capturas)...")
    test_demo.run()
    
    print("\n==================================================")
    print("✅ TODAS LAS PRUEBAS (99/99) COMPLETADAS CON ÉXITO")
    print("==================================================")

if __name__ == "__main__":
    run_all()
