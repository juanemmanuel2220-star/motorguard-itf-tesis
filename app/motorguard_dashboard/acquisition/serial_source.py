"""
Lector de telemetría y flujo serial en tiempo real para el microcontrolador ESP32-S3.
Admite auto-detección de puerto USB (/dev/ttyACM*, /dev/ttyUSB*), auto-reconexión continua,
parsing de telemetría [MCSA], tramas JSON y valores crudos por ADC.
Permite control bidireccional enviando comandos de activación de relevadores SSR ('1', '2', '3', '0').
"""

import os
import re
import json
import time
import glob
import serial
import numpy as np
from typing import Optional, Tuple, Dict, Any
from motorguard_dashboard.core.config import CAL_V, CAL_I, FS, GRID_FREQ_HZ
from motorguard_dashboard.core.data_types import RawSampleChunk

# Patrón regex para telemetría [MCSA] generada en firmware PRUEBA_MODELO_1.ino
# Admite tramas estándar, extensión de Fortescue (Mejora 1), HR MCSA (Mejora 2) y CUSUM (Mejora 3B)
MCSA_REGEX = re.compile(
    r"\[MCSA\]\s+Motor:(\w+)\s+\|(?:.*?)VA=([\d\.]+)V\s+VB=([\d\.]+)V\s+VC=([\d\.]+)V\s+\|\s+"
    r"IA=([\d\.]+)A\s+IB=([\d\.]+)A\s+IC=([\d\.]+)A\s+\|\s+"
    r"Afund=([\d\.]+)\s+A55=([\d\.]+)\(([\d\.]+)Hz\)\s+A65=([\d\.]+)\(([\d\.]+)Hz\)"
    r"(?:.*?\|\s+U2V=([\d\.]+)%\s+U2I=([\d\.]+)%\s+E2=([\d\.]+)%\s+DOM=(\d))?"
    r"(?:.*?\|\s+HR:\s+L2sM=([-\d\.]+)\s+L2sP=([-\d\.]+)\s+LrM=([-\d\.]+)\s+LrP=([-\d\.]+)\s+"
    r"L3=([-\d\.]+)\s+L3rM=([-\d\.]+)\s+L3rP=([-\d\.]+)\s+SNR2s=([-\d\.]+)\s+s=([-\d\.]+)\s+"
    r"SOK=(\d)\s+f0=([-\d\.]+))?"
    r"(?:.*?\|\s+CUSUM:\s+S=([-\d\.]+)\s+Pcal=([-\d\.]+)%)?"
)

class SerialStreamReader:
    """
    Gestiona la conexión serie en tiempo real con el ESP32-S3.
    Diseñado para conectarse automáticamente en cuanto el usuario enchufa el cable USB.
    """
    def __init__(self, port: Optional[str] = None, baudrate: int = 115200, timeout: float = 0.2):
        self.preferred_port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._serial: Optional[serial.Serial] = None
        self.current_port: Optional[str] = None
        self._sample_counter = 0
        self._last_telemetry: Dict[str, Any] = {
            "motor_on": False,
            "va": 0.0, "vb": 0.0, "vc": 0.0,
            "ia": 0.0, "ib": 0.0, "ic": 0.0,
            "afund": 0.0, "a55": 0.0, "f55": 55.0, "a65": 0.0, "f65": 65.0,
            "ssr": "OFF", "pred": "SANO",
            "u2v": 0.0, "u2i": 0.0, "e2": 0.0, "dom": 1,
            "hr_l2sm": 0.0, "hr_l2sp": 0.0, "hr_lrm": 0.0, "hr_lrp": 0.0,
            "hr_l3": 0.0, "hr_l3rm": 0.0, "hr_l3rp": 0.0, "hr_snr2s": 0.0,
            "hr_s": 0.012, "hr_sok": 0, "hr_f0": 60.0,
            "cusum_s": 0.0, "p_cal": 0.0
        }
        self._last_telemetry_time = 0.0

    @staticmethod
    def find_esp32_port() -> Optional[str]:
        """Busca automáticamente puertos USB CDC (/dev/ttyACM*) o adaptadores USB (/dev/ttyUSB*)."""
        # 1. Prioridad: /dev/ttyACM* (puerto USB nativo del ESP32-S3)
        acm_ports = sorted(glob.glob("/dev/ttyACM*"))
        if acm_ports:
            return acm_ports[0]
        # 2. Puertos UART /dev/ttyUSB* (CP2102/CH340)
        usb_ports = sorted(glob.glob("/dev/ttyUSB*"))
        if usb_ports:
            return usb_ports[0]
        return None

    def is_connected(self) -> bool:
        """Verifica si la conexión serial física está activa."""
        return self._serial is not None and self._serial.is_open

    def connect(self, specific_port: Optional[str] = None) -> bool:
        """Intenta abrir la conexión serial con auto-detección."""
        target_port = specific_port or self.preferred_port or self.find_esp32_port()
        if not target_port or not os.path.exists(target_port):
            self.disconnect()
            return False

        try:
            # Si ya está abierto en ese puerto, mantener
            if self._serial and self._serial.is_open and self.current_port == target_port:
                return True

            self.disconnect()
            self._serial = serial.Serial(
                port=target_port,
                baudrate=self.baudrate,
                timeout=self.timeout
            )
            # En dispositivos ESP32-S3 CDC es indispensable activar DTR y RTS
            self._serial.dtr = True
            self._serial.rts = True
            self._serial.reset_input_buffer()
            self.current_port = target_port
            return True
        except Exception as e:
            # Si el puerto está retenido por el monitor serie de Arduino IDE (Device or resource busy), liberarlo
            err_str = str(e)
            if "Device or resource busy" in err_str or "16" in err_str:
                try:
                    import subprocess
                    subprocess.run(["fuser", "-k", target_port], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
                    time.sleep(0.3)
                    self._serial = serial.Serial(port=target_port, baudrate=self.baudrate, timeout=self.timeout)
                    self._serial.dtr = True
                    self._serial.rts = True
                    self._serial.reset_input_buffer()
                    self.current_port = target_port
                    return True
                except:
                    pass
            self.disconnect()
            return False

    def disconnect(self):
        """Cierra el puerto serial limpiamente."""
        if self._serial:
            try:
                self._serial.close()
            except:
                pass
        self._serial = None
        self.current_port = None

    def send_command(self, cmd: str) -> bool:
        """Envía un comando al ESP32 (ej: '1'=falla F1, '0'=SSR OFF, '2'=F2, '3'=F3)."""
        if not self.is_connected():
            return False
        try:
            self._serial.write(cmd.encode('utf-8'))
            self._serial.flush()
            return True
        except:
            self.disconnect()
            return False

    def read_telemetry_or_samples(self) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Lee una línea del flujo serial y parsea telemetría [MCSA], JSON o CSV.
        Retorna (exito, datos_parseados).
        """
        if not self.is_connected():
            return False, None

        try:
            raw_line = self._serial.readline()
            if not raw_line:
                return False, None
            line = raw_line.decode('utf-8', errors='ignore').strip()
            if not line:
                return False, None

            # 1. Caso Telemetría [MCSA] (Firmware PRUEBA_MODELO_1.ino)
            m = MCSA_REGEX.search(line)
            if m:
                groups = m.groups()
                motor_str, va, vb, vc, ia, ib, ic, afund, a55, f55, a65, f65 = groups[:12]
                u2v = float(groups[12]) if len(groups) > 12 and groups[12] is not None else 0.0
                u2i = float(groups[13]) if len(groups) > 13 and groups[13] is not None else 0.0
                e2  = float(groups[14]) if len(groups) > 14 and groups[14] is not None else 0.0
                dom = int(groups[15]) if len(groups) > 15 and groups[15] is not None else 1

                hr_l2sm = float(groups[16]) if len(groups) > 16 and groups[16] is not None else 0.0
                hr_l2sp = float(groups[17]) if len(groups) > 17 and groups[17] is not None else 0.0
                hr_lrm  = float(groups[18]) if len(groups) > 18 and groups[18] is not None else 0.0
                hr_lrp  = float(groups[19]) if len(groups) > 19 and groups[19] is not None else 0.0
                hr_l3   = float(groups[20]) if len(groups) > 20 and groups[20] is not None else 0.0
                hr_l3rm = float(groups[21]) if len(groups) > 21 and groups[21] is not None else 0.0
                hr_l3rp = float(groups[22]) if len(groups) > 22 and groups[22] is not None else 0.0
                hr_snr2s= float(groups[23]) if len(groups) > 23 and groups[23] is not None else 0.0
                hr_s    = float(groups[24]) if len(groups) > 24 and groups[24] is not None else 0.012
                hr_sok  = int(groups[25])   if len(groups) > 25 and groups[25] is not None else 0
                hr_f0   = float(groups[26]) if len(groups) > 26 and groups[26] is not None else 60.0
                cusum_s = float(groups[27]) if len(groups) > 27 and groups[27] is not None else 0.0
                p_cal   = float(groups[28]) if len(groups) > 28 and groups[28] is not None else 0.0

                ssr_val = "OFF"
                if "SSR:" in line:
                    ssr_val = line.split("SSR:")[-1].split("|")[0].strip()

                # Extraer predicción exacta delimitada por barras | (SANO|LEVE|INTER|SEVERA|WARMUP) |
                # Evita falso positivo provocado por la subcadena LEVE dentro de P(LEVE)=
                m_pred = re.search(r"\|\s*(SANO|LEVE|INTER|SEVERA|WARMUP)\s*\|", line)
                if m_pred:
                    pred_val = m_pred.group(1)
                else:
                    pred_val = "SANO"

                # Extraer probabilidad calculada por el modelo si existe
                m_pleve = re.search(r"P\(LEVE\)=([\d\.]+)%", line)
                p_leve = float(m_pleve.group(1)) if m_pleve else 0.0

                self._last_telemetry = {
                    "motor_on": (motor_str.upper() == "ON"),
                    "va": float(va), "vb": float(vb), "vc": float(vc),
                    "ia": float(ia), "ib": float(ib), "ic": float(ic),
                    "afund": float(afund), "a55": float(a55), "f55": float(f55),
                    "a65": float(a65), "f65": float(f65),
                    "ssr": ssr_val,
                    "pred": pred_val,
                    "p_leve": p_leve,
                    "u2v": u2v,
                    "u2i": u2i,
                    "e2": e2,
                    "dom": dom,
                    "hr_l2sm": hr_l2sm,
                    "hr_l2sp": hr_l2sp,
                    "hr_lrm": hr_lrm,
                    "hr_lrp": hr_lrp,
                    "hr_l3": hr_l3,
                    "hr_l3rm": hr_l3rm,
                    "hr_l3rp": hr_l3rp,
                    "hr_snr2s": hr_snr2s,
                    "hr_s": hr_s,
                    "hr_sok": hr_sok,
                    "hr_f0": hr_f0,
                    "cusum_s": cusum_s,
                    "p_cal": p_cal
                }
                self._last_telemetry_time = time.time()
                return True, self._last_telemetry

            # 2. Caso JSON {"va":..., "ia":...}
            if line.startswith('{') and line.endswith('}'):
                try:
                    d = json.loads(line)
                    self._last_telemetry = {
                        "motor_on": (float(d.get("ia", 0)) > 0.8),
                        "va": float(d.get("va", d.get("vc", 123.0))),
                        "vb": float(d.get("vb", 123.0)),
                        "vc": float(d.get("vc", 123.0)),
                        "ia": float(d.get("ia", 0.0)),
                        "ib": float(d.get("ib", 0.0)),
                        "ic": float(d.get("ic", 0.0)),
                        "afund": float(d.get("ffund", 0.0)),
                        "a55": float(d.get("f55", 0.0)),
                        "f55": 55.0,
                        "a65": float(d.get("f65", 0.0)),
                        "f65": 65.0,
                        "ssr": d.get("ssr", "OFF"),
                        "pred": d.get("pred", "SANO"),
                        "cusum_s": float(d.get("cusum_s", 0.0)),
                        "p_cal": float(d.get("p_cal", 0.0))
                    }
                    self._last_telemetry_time = time.time()
                    return True, self._last_telemetry
                except:
                    pass

            # 3. Caso CSV de muestras crudas "va,vb,vc,ia,ib,ic"
            parts = line.split(',')
            if len(parts) >= 3:
                try:
                    vals = [float(p.strip()) for p in parts]
                    return True, {"raw_csv": vals}
                except:
                    pass

        except Exception as e:
            # Si el cable fue desconectado físicamente, cerrar para permitir auto-reconexión
            self.disconnect()

        return False, None

    def generate_realtime_chunk(self, num_samples: int = 120) -> RawSampleChunk:
        """
        Genera un bloque continuo de muestras físicas a 2400 Hz sincronizado con la telemetría real.
        Si la telemetría del ESP32 está activa, sintetiza las formas de onda instantáneas
        respetando fielmente los valores RMS, desbalances y armónicos reales medidos por los ACS712.
        """
        t_now = time.time()
        n = np.arange(self._sample_counter, self._sample_counter + num_samples, dtype=np.float64)
        t = n / FS
        w0 = 2.0 * np.pi * GRID_FREQ_HZ

        tel = self._last_telemetry
        is_motor_on = tel["motor_on"]

        if is_motor_on and (tel["ia"] > 0.3 or tel["ic"] > 0.3):
            # Formas de onda instantáneas basadas en las corrientes RMS físicas medidas por el ESP32
            ia_pk = np.sqrt(2.0) * tel["ia"]
            ib_pk = np.sqrt(2.0) * tel["ib"]
            ic_pk = np.sqrt(2.0) * tel["ic"]

            ia = ia_pk * np.sin(w0 * t)
            ib = ib_pk * np.sin(w0 * t - 2.0 * np.pi / 3.0)
            ic = ic_pk * np.sin(w0 * t + 2.0 * np.pi / 3.0)

            # Inyectar las componentes armónicas MCSA reales medidas por el ESP32
            ref_afund = max(tel["afund"], 1.0)
            if tel["a55"] > 0.01:
                w55 = 2.0 * np.pi * tel["f55"]
                amp_55 = (tel["a55"] / ref_afund) * ic_pk if tel["afund"] > 50.0 else tel["a55"]
                ic += amp_55 * np.sin(w55 * t)
            if tel["a65"] > 0.01:
                w65 = 2.0 * np.pi * tel["f65"]
                amp_65 = (tel["a65"] / ref_afund) * ic_pk if tel["afund"] > 50.0 else tel["a65"]
                ic += amp_65 * np.sin(w65 * t)

            # Ruido natural residual de instrumentación
            ia += np.random.normal(0, 0.02, num_samples)
            ib += np.random.normal(0, 0.02, num_samples)
            ic += np.random.normal(0, 0.02, num_samples)

            v_pk = np.sqrt(2.0) * max(tel["va"], 120.0)
            v_ab = v_pk * np.sin(w0 * t)
            v_bc = v_pk * np.sin(w0 * t - 2.0 * np.pi / 3.0)
        else:
            # Motor apagado o cable desconectado: línea base en cero
            ia = np.random.normal(0, 0.005, num_samples)
            ib = np.random.normal(0, 0.005, num_samples)
            ic = np.random.normal(0, 0.005, num_samples)
            v_ab = np.zeros(num_samples, dtype=np.float32)
            v_bc = np.zeros(num_samples, dtype=np.float32)

        currents = np.vstack((ia, ib, ic)).astype(np.float32)
        voltages = np.vstack((v_ab, v_bc)).astype(np.float32)
        sample_indices = n.astype(np.uint64)
        self._sample_counter += num_samples

        return RawSampleChunk(
            timestamp_start=t_now,
            sample_indices=sample_indices,
            currents=currents,
            voltages=voltages
        )
