"""
Lectura del Arduino por USB serie con reconexión automática.

Reglas (encargo de la app, sección 4):
- Solo un programa puede tener el puerto. Si otro proceso lo tiene abierto (por ejemplo un script
  de validación), la app NO se conecta ni lo mata: avisa y vuelve a intentar.
- Mientras la app tiene el puerto lo marca exclusivo (TIOCEXCL), así un script lanzado por error
  falla al abrirlo en lugar de repartirse las líneas con la app.
- Se abre igual que en ~/validacion_vivo_direccional.py: 115200 baud, sin tocar DTR/RTS, y al conectar
  se envía '0' (apaga el SSR por si quedó encendido).
- Solo se pueden enviar '1' y '0' (segunda barrera; la primera es inyeccion/control.py) y, aparte, las
  consultas de solo lectura 'W', 'f' y 's' (telemetry/consultas.py). Cada comando enviado queda en el
  registro crudo como "<t> >> TX <c>" (el parser ignora esas líneas).
"""

import dataclasses
import errno
import fcntl
import glob
import os
import termios
import threading
import time
from typing import List, Optional, Tuple

import serial
from PySide6.QtCore import QThread, Signal

from motorguard_dashboard.inyeccion.control import COMANDOS_PERMITIDOS
from motorguard_dashboard.telemetry.consultas import CONSULTAS_LECTURA, AcumuladorRespuestas
from motorguard_dashboard.sistema.bitacora import LOG
from motorguard_dashboard.telemetry.parser import parsear_linea
from motorguard_dashboard.telemetry.registro_crudo import RegistroCrudo

BAUD = 115200
REINTENTO_S = 2.0


def detectar_puerto() -> Optional[str]:
    """Primer /dev/ttyACM* (USB nativo del ESP32-S3)."""
    puertos = sorted(glob.glob("/dev/ttyACM*"))
    return puertos[0] if puertos else None


def procesos_con_puerto(ruta: str) -> List[Tuple[int, str]]:
    """Procesos (distintos de este) que tienen abierto el dispositivo. Solo lee /proc."""
    try:
        destino = os.path.realpath(ruta)
    except OSError:
        return []
    propios = os.getpid()
    encontrados = []
    for dir_fd in glob.glob("/proc/[0-9]*/fd"):
        pid = int(dir_fd.split("/")[2])
        if pid == propios:
            continue
        try:
            for fd in os.listdir(dir_fd):
                if os.path.realpath(os.path.join(dir_fd, fd)) == destino:
                    with open(f"/proc/{pid}/cmdline", "rb") as f:
                        cmd = f.read().replace(b"\0", b" ").decode(errors="ignore").strip()
                    encontrados.append((pid, cmd))
                    break
        except OSError:
            continue  # proceso de otro usuario o que ya terminó
    return encontrados


class FuenteSerie(QThread):
    """Hilo que lee el puerto serie y emite las líneas parseadas (misma interfaz que FuenteReplay)."""
    sig_dato = Signal(object)          # Trama | EventoSSR | MensajeFirmware (t = hora de recepción)
    sig_descartada = Signal(str)       # trama [MCSA] incompleta
    sig_estado = Signal(bool, str)     # (conectado, mensaje)
    sig_respuesta = Signal(object)     # FormaOnda | EspectroCritico | Indicadores (consultas a petición)

    def __init__(self, puerto: Optional[str] = None, ruta_crudo: Optional[str] = None):
        super().__init__()
        self.puerto_preferido = puerto
        self.ruta_crudo = ruta_crudo
        self._detener = False
        self.puerto_actual = ""          # puerto abierto (para los metadatos de la adquisición)
        self.detenida = False            # True solo si se pidió detener (distingue una muerte inesperada)
        self.reinicios = 0
        self._ser: Optional[serial.Serial] = None
        self._f_crudo: Optional[RegistroCrudo] = None
        self._lock = threading.Lock()   # el hilo de lectura y la interfaz comparten el puerto y el registro
        self._acum = AcumuladorRespuestas()

    def detener(self):
        self.detenida = True
        self._detener = True
        self.wait(3000)

    def reiniciar(self):
        """Vuelve a arrancar el hilo si terminó sin que se pidiera (lo usa el vigilante de la ventana)."""
        if self.detenida or self.isRunning():
            return False
        self.reinicios += 1
        self._detener = False
        self._acum = AcumuladorRespuestas()
        LOG.warning("Reiniciando la lectura del puerto (reinicio %d)", self.reinicios)
        self.start()
        return True

    # ---------------------------------------------------------------- conexión
    def _abrir(self) -> Tuple[bool, str]:
        puerto = self.puerto_preferido or detectar_puerto()
        if not puerto or not os.path.exists(puerto):
            return False, f"Esperando el Arduino ({puerto or '/dev/ttyACM*'} no existe)"
        otros = procesos_con_puerto(puerto)
        if otros:
            pid, cmd = otros[0]
            return False, f"{puerto} ocupado por PID {pid} ({cmd[:60]}). Cierra ese programa; no se interrumpe"
        try:
            ser = serial.Serial(puerto, BAUD, timeout=0.5)
            with self._lock:
                self._ser = ser
            fcntl.ioctl(ser.fileno(), termios.TIOCEXCL)
            time.sleep(0.5)
            ser.reset_input_buffer()
        except (serial.SerialException, OSError, termios.error) as e:
            # termios.error no hereda de OSError: sale de reset_input_buffer (tcflush) si el Arduino todavía se está
            # enumerando al reconectar el USB (banco, 13-oct: quedaba como "Error inesperado" con traza)
            self._cerrar()
            if getattr(e, "errno", None) == errno.EACCES or "Errno 13" in str(e) or "Permission denied" in str(e):
                return False, (f"Sin permiso para {puerto}: agrega tu usuario al grupo dialout "
                               "(sudo usermod -aG dialout $USER) y vuelve a iniciar sesión")
            return False, f"No se pudo abrir {puerto}: {e}"
        if not self.enviar("0"):
            self._cerrar()
            return False, f"No se pudo enviar '0' al conectar en {puerto}"
        self.puerto_actual = puerto
        return True, f"CONECTADO {puerto} @ {BAUD}"

    def _cerrar(self):
        with self._lock:
            if self._ser is not None:
                try:
                    # Quitar la exclusividad antes de cerrar: si no, el dispositivo puede quedar marcado y ni
                    # la propia app podría reabrirlo al recuperarse de un error
                    fcntl.ioctl(self._ser.fileno(), termios.TIOCNXCL)
                except (serial.SerialException, OSError, ValueError, AttributeError):
                    pass
                try:
                    self._ser.close()
                except (serial.SerialException, OSError):
                    pass
            self._ser = None

    def conectado(self) -> bool:
        return self._ser is not None

    def enviar(self, cmd: str) -> bool:
        """Envía '1' o '0' al firmware. Devuelve False si no hay conexión o falla la escritura."""
        if cmd not in COMANDOS_PERMITIDOS:
            raise ValueError(f"comando no permitido: {cmd!r}")
        return self._escribir(cmd)

    def reiniciar_detector(self) -> bool:
        """Envía 'r' (PRUEBA_MODELO_1.ino l. 1547: detector_init + dir_init) para liberar una alarma atascada. No toca
        el SSR. Solo desde el botón "Liberar alarma", con la confirmación del usuario (aprobado por el autor, 16-oct)."""
        return self._escribir("r")

    def consultar(self, cmd: str) -> bool:
        """Consulta de solo lectura ('W', 'f', 's'); la respuesta llega por sig_respuesta."""
        if cmd not in CONSULTAS_LECTURA:
            raise ValueError(f"consulta no permitida: {cmd!r}")
        return self._escribir(cmd)

    def _escribir(self, cmd: str) -> bool:
        with self._lock:
            if self._ser is None:
                return False
            try:
                self._ser.write(f"{cmd}\n".encode())
                self._ser.flush()
            except (serial.SerialException, OSError):
                return False
            if self._f_crudo:
                self._f_crudo.escribir(time.time(), f">> TX {cmd}")
        return True

    def _esperar(self, segundos: float):
        fin = time.monotonic() + segundos
        while not self._detener and time.monotonic() < fin:
            time.sleep(0.1)

    # ---------------------------------------------------------------- bucle
    def run(self):
        if self.ruta_crudo and self._f_crudo is None:
            self._f_crudo = RegistroCrudo(self.ruta_crudo)
        ultimo_msg = None
        try:
            while not self._detener:
                try:
                    ultimo_msg = self._iteracion(ultimo_msg)
                except Exception as e:  # noqa: BLE001 - un error inesperado no debe matar la lectura
                    LOG.exception("Error inesperado en la lectura del puerto; se cierra y se reintenta")
                    self._cerrar()
                    ultimo_msg = f"Error interno en la lectura ({type(e).__name__}); reintentando"
                    self.sig_estado.emit(False, ultimo_msg)
                    self._esperar(REINTENTO_S)
        finally:
            self._cerrar()
            if self.detenida:
                with self._lock:
                    if self._f_crudo:
                        self._f_crudo.cerrar()
                        self._f_crudo = None
            self.sig_estado.emit(False, "Lectura detenida")

    def _iteracion(self, ultimo_msg):
        """Una vuelta del bucle: conectar si hace falta, leer una línea y emitirla. Devuelve el último mensaje."""
        if self._ser is None:
            ok, msg = self._abrir()
            if msg != ultimo_msg:
                (LOG.info if ok else LOG.warning)("Puerto: %s", msg)
                self.sig_estado.emit(ok, msg)
                ultimo_msg = msg
            if not ok:
                self._esperar(REINTENTO_S)
            return ultimo_msg
        try:
            crudo = self._ser.readline()
        except (serial.SerialException, OSError, TypeError) as e:
            # Cable desconectado o dispositivo reiniciado: cerrar y reintentar
            self._cerrar()
            ultimo_msg = f"Conexión perdida: {e}"
            LOG.warning("Puerto: %s", ultimo_msg)
            self.sig_estado.emit(False, ultimo_msg)
            self._esperar(REINTENTO_S)
            return ultimo_msg
        if not crudo:
            return ultimo_msg
        linea = crudo.decode("utf-8", errors="ignore").strip()
        if not linea:
            return ultimo_msg
        t = time.time()
        with self._lock:
            if self._f_crudo:
                self._f_crudo.escribir(t, linea)
        consumida, resp = self._acum.alimentar(linea, t)
        if resp is not None:
            self.sig_respuesta.emit(resp)
        if consumida:
            return ultimo_msg
        obj = parsear_linea(linea)
        if obj is not None:
            self.sig_dato.emit(dataclasses.replace(obj, t=t))
        elif "[MCSA]" in linea:
            self.sig_descartada.emit(linea)
        return ultimo_msg
