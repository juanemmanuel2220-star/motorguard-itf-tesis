"""
Sistema de registro sincronizado de eventos experimentales y streaming CSV continuo.
Garantiza que cada evento ("Cambio de Carga", "Inyección Falla", "Aumento Severidad", "Falla Off")
quede indexado con timestamp UNIX, formato legible ISO 8601 y el índice exacto de muestra (uint64).
Preserva las 15 columnas auditadas para interoperabilidad total con la tesis.
"""

import os
import csv
import json
import time
from datetime import datetime
from typing import List, Optional, Dict, Any
from PySide6.QtCore import QObject, Signal, Slot

from motorguard_dashboard.core.config import CARGAS
from motorguard_dashboard.core.data_types import WindowFeatures, DeviationMetrics, ExperimentalEvent

# Diccionario de clases auditado con nombres canónicos
CLASES_CANONICAS = {0: "SANO", 1: "LEVE", 2: "INTER", 3: "SEVERA"}

# Encabezados del archivo CSV de sesión experimental
SESSION_CSV_COLUMNS = [
    # 15 Columnas Estándar Auditadas (compatibilidad histórica estricta)
    'clase', 'label', 'carga', 'carga_label', 'n_muestra', 'timestamp',
    'V_rms', 'I_rms', 'A_55', 'A_65', 'A_50', 'A_70', 'A_fund', 'I_neg', 'THD',
    # Columnas Extendidas de Diagnóstico en Tiempo Real
    'I_unb', 'I_prom', 'Z_A65', 'Z_unb', 'sample_index', 'active_event'
]


class EventRecorder(QObject):
    """
    Gestor de persistencia de experimentos y trazabilidad de eventos en tiempo real.
    """
    sig_session_started = Signal(str)           # filepath
    sig_session_stopped = Signal(str, int)      # filepath, total_records
    sig_event_logged = Signal(object)           # ExperimentalEvent

    def __init__(self, output_dir: Optional[str] = None):
        super().__init__()
        self.output_dir = output_dir or os.path.expanduser("~/tesis_itf/dataset/sesiones")
        self.is_recording: bool = False
        self.current_csv_path: Optional[str] = None
        self.current_events_json_path: Optional[str] = None
        
        self._file = None
        self._writer = None
        self._record_count: int = 0
        self._event_counter: int = 0
        self.events_log: List[ExperimentalEvent] = []
        
        # Estado experimental actual
        self.active_load_level: int = 0
        self.active_fault_class: int = 0
        self._latest_event_marker: str = "ESTABLE_SANO"

    def start_session(self, session_name: Optional[str] = None) -> str:
        """Inicia una nueva sesión de grabación experimental."""
        if self.is_recording:
            self.stop_session()

        os.makedirs(self.output_dir, exist_ok=True)
        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = session_name or f"sesion_{now_str}"
        self.current_csv_path = os.path.join(self.output_dir, f"{prefix}.csv")
        self.current_events_json_path = os.path.join(self.output_dir, f"{prefix}_events.json")
        
        self._file = open(self.current_csv_path, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow(SESSION_CSV_COLUMNS)
        self._file.flush()
        
        self.is_recording = True
        self._record_count = 0
        self._event_counter = 0
        self.events_log.clear()
        
        # Registrar evento inicial
        self.record_event(
            event_type="INICIO_SESION",
            description=f"Inicio de sesión {prefix}",
            sample_index=0,
            load_level=self.active_load_level,
            fault_class=self.active_fault_class
        )
        
        self.sig_session_started.emit(self.current_csv_path)
        return self.current_csv_path

    def stop_session(self) -> Optional[str]:
        """Detiene y cierra los archivos de la sesión actual."""
        if not self.is_recording:
            return None

        # Registrar evento de cierre
        self.record_event(
            event_type="FIN_SESION",
            description="Cierre formal de sesión",
            sample_index=0,
            load_level=self.active_load_level,
            fault_class=self.active_fault_class
        )

        if self._file:
            self._file.flush()
            self._file.close()
            self._file = None
            self._writer = None

        # Guardar sidecar JSON de eventos
        if self.current_events_json_path and len(self.events_log) > 0:
            events_data = [
                {
                    "event_id": e.event_id,
                    "timestamp": e.timestamp,
                    "sample_index": int(e.sample_index),
                    "event_type": e.event_type,
                    "description": e.description,
                    "load_level": e.load_level,
                    "fault_class": e.fault_class
                }
                for e in self.events_log
            ]
            try:
                with open(self.current_events_json_path, "w", encoding="utf-8") as f:
                    json.dump(events_data, f, indent=2)
            except Exception as ex:
                print(f"[WARN] Error al guardar eventos JSON: {ex}")

        saved_path = self.current_csv_path
        rec_count = self._record_count
        self.is_recording = False
        self.sig_session_stopped.emit(saved_path, rec_count)
        return saved_path

    def record_event(
        self,
        event_type: str,
        description: str,
        sample_index: int,
        load_level: Optional[int] = None,
        fault_class: Optional[int] = None
    ) -> ExperimentalEvent:
        """Registra una marca de evento con tiempo e índice exacto de muestra."""
        if load_level is not None:
            self.active_load_level = load_level
        if fault_class is not None:
            self.active_fault_class = fault_class

        self._event_counter += 1
        now_ts = time.time()
        self._latest_event_marker = event_type
        
        event = ExperimentalEvent(
            event_id=self._event_counter,
            timestamp=now_ts,
            sample_index=sample_index,
            event_type=event_type,
            description=description,
            load_level=self.active_load_level,
            fault_class=self.active_fault_class
        )
        
        self.events_log.append(event)
        self.sig_event_logged.emit(event)
        return event

    @Slot(object)
    def record_features(
        self,
        features: WindowFeatures,
        deviations: Optional[List[DeviationMetrics]] = None
    ):
        """Escribe una fila de ventana en el CSV de sesión si la grabación está activa."""
        if not self.is_recording or self._writer is None:
            return

        self._record_count += 1
        
        # Extraer Z-scores si están disponibles
        z_a65 = 0.0
        z_unb = 0.0
        if deviations:
            for d in deviations:
                if "A_65" in d.feature_name:
                    z_a65 = d.z_score
                elif "I_unb" in d.feature_name:
                    z_unb = d.z_score

        # Mapear etiquetas
        carga_label = CARGAS.get(self.active_load_level, f"{self.active_load_level * 25}%")
        # En la convención auditada, carga_label es '0%', '25%', etc.
        carga_label_clean = f"{self.active_load_level * 25}%"
        label_falla = CLASES_CANONICAS.get(self.active_fault_class, "SANO")
        
        # En el dataset auditado, I_rms es la corriente de la fase C
        i_rms_c = float(features.I_rms[2])
        v_rms_val = float(features.V_rms)
        t_iso = datetime.fromtimestamp(features.timestamp).strftime("%Y-%m-%d %H:%M:%S")

        row = [
            self.active_fault_class,
            label_falla,
            self.active_load_level,
            carga_label_clean,
            self._record_count,
            t_iso,
            round(v_rms_val, 2),
            round(i_rms_c, 4),
            round(features.A_55, 4),
            round(features.A_65, 4),
            round(features.A_50, 4),
            round(features.A_70, 4),
            round(features.A_fund, 4),
            round(features.I_neg, 5),
            round(features.THD, 5),
            round(features.I_unb, 3),
            round(features.I_prom, 4),
            round(z_a65, 2),
            round(z_unb, 2),
            features.sample_index,
            self._latest_event_marker
        ]

        self._writer.writerow(row)
        self._file.flush()
