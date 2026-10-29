"""
SIMULADOR DEL FIRMWARE — SOLO PARA PRUEBAS. No es evidencia experimental.

Imita el manejo del SSR de PRUEBA_MODELO_1.ino (ssrOn/ssrOff, l. 770-818): mismos mensajes
[DEBUG SSR], rechazo con el motor apagado (en WARMUP el firmware SÍ acepta '1'), cooldown de 2 s y
watchdog de 12 s. Las tramas son líneas reales (test_telemetry_parser) con Motor y SSR cambiados;
con el SSR encendido, a partir del segundo bloque se emite la trama real con alarma INTER.
Consultas de lectura: 'W' responde con el volcado REAL del log del 06-oct; 'f' y 's' con texto derivado
de los printf del firmware (tests/test_consultas.py).
"""

import os
import select
import threading
import time

from motorguard_dashboard.tests.test_telemetry_parser import L_SANO, L_INTER

T_MAX_ON = 12.0
T_COOLDOWN = 2.0


class SimuladorFirmware(threading.Thread):
    def __init__(self, maestro: int, periodo: float = 0.3):
        super().__init__(daemon=True)
        self.maestro = maestro
        self.periodo = periodo
        self.motor = "ON"
        self.ssr = False
        self.t_on = 0.0
        self.t_off = -1e9
        self.recibidos = []          # todo lo que llegó por el puerto (caracteres)
        self._bloques_on = 0
        self.atascada = False        # alarma enclavada sin SSR (como tras un escalón del motor sano); 'r' la libera
        self._parar = False

    def detener(self):
        self._parar = True
        self.join(2)

    def cambiar_puerto(self, maestro: int):
        """Tras una desconexión simulada, seguir en el puerto virtual nuevo."""
        self.maestro = maestro

    def _tx(self, linea):
        try:
            os.write(self.maestro, (linea + "\n").encode())
        except OSError:
            pass  # nadie tiene abierto el puerto todavía: la línea se pierde, como con el Arduino real

    def _ssr_off(self, forzado):
        if self.ssr:
            self.ssr = False
            t_on_ms = int((time.monotonic() - self.t_on) * 1000)
            self.t_off = time.monotonic()
            self._tx(f"[DEBUG SSR] Apagado. Forzado: {int(forzado)} | T_ON: {t_on_ms} ms")

    def _ssr_on(self):
        ahora = time.monotonic()
        self._tx(f"[DEBUG SSR] Solicitud F1 | I_rms=5.83A | Cooldown={int((ahora - self.t_off) * 1000)} ms")
        if self.motor == "OFF":
            self._tx("[DEBUG SSR] Rechazado: Motor apagado. Peligro de Inrush.")
        elif self.ssr:
            self._tx("[DEBUG SSR] Rechazado: Ya hay un SSR activo.")
        elif ahora - self.t_off < T_COOLDOWN:
            self._tx(f"[DEBUG SSR] Rechazado: Cooldown activo ({int((ahora - self.t_off) * 1000)}/2000 ms).")
        else:
            self.ssr, self.t_on, self._bloques_on = True, ahora, 0
            self._tx("[DEBUG SSR] Exito: GPIO 8 puesto en HIGH (3V)")

    def _responder(self, c):
        from motorguard_dashboard.tests.test_consultas import TEXTO_F, TEXTO_S, lineas_wave_reales
        lineas = {"W": lineas_wave_reales, "f": lambda: TEXTO_F.splitlines(), "s": lambda: [TEXTO_S]}[c]()
        self._tx("\n".join(lineas))

    def _trama(self):
        base = L_INTER if ((self.ssr and self._bloques_on >= 2) or self.atascada) else L_SANO
        linea = base[15:].replace("Motor:ON", f"Motor:{self.motor}")
        linea = linea.replace("SSR:F1(LEVE)", "SSR:OFF").replace("SSR:OFF", "SSR:F1(LEVE)" if self.ssr else "SSR:OFF")
        if self.motor == "WARMUP":
            linea = linea.replace("| SANO |", "| WARMUP |").replace("| INTER |", "| WARMUP |")
        self._tx(linea)
        if self.ssr:
            self._bloques_on += 1

    def run(self):
        proxima = time.monotonic()
        while not self._parar:
            try:
                listo, _, _ = select.select([self.maestro], [], [], 0.02)
            except (OSError, ValueError):
                time.sleep(0.05)   # el puerto virtual se está reemplazando (desconexión simulada)
                continue
            if listo:
                try:
                    datos = os.read(self.maestro, 64).decode(errors="ignore")
                except OSError:
                    time.sleep(0.05)  # el lado de la app está cerrado (EIO): esperar a que lo abra
                    continue
                for c in datos:
                    if c in "\r\n":
                        continue
                    self.recibidos.append(c)
                    if c == "1":
                        self._ssr_on()
                    elif c == "0":
                        self._ssr_off(False)
                    elif c in "Wfs":
                        self._responder(c)
                    elif c == "r":           # PRUEBA_MODELO_1.ino l. 1547: detector_init + dir_init
                        self.atascada = False
                        self._tx("\n>>> [CUSUM RESET] Acumulador CUSUM reiniciado a S=0.00. Pantalla en SANO.")
            if self.ssr and time.monotonic() - self.t_on >= T_MAX_ON:
                self._ssr_off(True)
            if time.monotonic() >= proxima:
                self._trama()
                proxima += self.periodo
