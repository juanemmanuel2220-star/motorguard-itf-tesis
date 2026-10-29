"""
SIMULADOR DEL MODO DEMO (app.py --demo) — SOLO PARA CAPTURAS DE PANTALLA. No es evidencia experimental.

Igual que SimuladorFirmware (manejo del SSR, consultas W/f/s y 'r'), pero las tramas son las líneas REALES de un
log del banco, en su orden y a su ritmo (un bloque cada 1.70 s):
- con el SSR apagado se repiten en bucle las tramas sanas del log (SANO y SSR:OFF);
- al aceptar un '1' se reproduce el siguiente episodio real de inyección: las líneas que siguen al "Exito" del
  log hasta la primera trama SANO después de apagarse el SSR (alarma, enclavamiento y liberación reales).
El campo SSR de cada trama y los mensajes [DEBUG SSR] los pone el simulador según los comandos recibidos, no el
log. 'f' y 's' responden con texto de ejemplo con el formato del firmware (tests/test_consultas.py).
Con enclavada=True la última trama con alarma se repite hasta recibir 'r', como la alarma enclavada de 567 s del
16-oct (app_registros/sesion_20261016_134802_eventos.csv), para poder capturar «Liberar alarma».
"""

import os

from motorguard_dashboard.tests.simulador_firmware import SimuladorFirmware

LOG_DEMO = os.path.expanduser("~/tesis_itf/validacion_vivo/vivo_INTER_75%_20261009_1513_serial.log")
PERIODO_BLOQUE = 1.70


def _sin_marca(linea: str) -> str:
    """'1791580418.950 [MCSA] ...' -> '[MCSA] ...'"""
    partes = linea.rstrip("\n").split(" ", 1)
    try:
        float(partes[0])
        return partes[1] if len(partes) == 2 else ""
    except ValueError:
        return linea.rstrip("\n")


def _es_trama(linea: str) -> bool:
    return linea.startswith("[MCSA]")


def episodios_y_reposo(ruta: str):
    """Separa el log en tramas de reposo (SANO, SSR:OFF) y episodios de inyección."""
    with open(ruta, encoding="utf-8", errors="replace") as f:
        lineas = [x for x in (_sin_marca(l) for l in f) if x]
    episodios, reposo = [], []
    i = 0
    while i < len(lineas):
        l = lineas[i]
        if l.startswith("[DEBUG SSR] Exito"):
            ep, apagado = [], False
            i += 1
            while i < len(lineas) and not lineas[i].startswith("[DEBUG SSR] Solicitud"):
                x = lineas[i]
                if _es_trama(x) and "SSR:OFF" in x:
                    apagado = True
                if not x.startswith("[DEBUG SSR]"):      # los mensajes del SSR los genera el simulador
                    ep.append(x)
                i += 1
                if apagado and _es_trama(x) and "| SANO |" in x:
                    break
            episodios.append(ep)
            continue
        if _es_trama(l) and "| SANO |" in l and "SSR:OFF" in l and "Motor:ON" in l:
            reposo.append(l)
        i += 1
    return episodios, reposo


class SimuladorDemo(SimuladorFirmware):
    def __init__(self, maestro: int, log: str = LOG_DEMO, enclavada: bool = False, periodo: float = PERIODO_BLOQUE):
        super().__init__(maestro, periodo)
        self.episodios, self.reposo = episodios_y_reposo(log)
        if not self.episodios or not self.reposo:
            raise ValueError(f"{log}: sin episodios de inyección o sin tramas de reposo")
        self.enclavada = enclavada
        self._k_reposo = 0
        self._k_ep = 0
        self._ep = None          # líneas pendientes del episodio en curso
        self._ultima_alarma = None
        self._n_vistos = 0

    def _ssr_on(self):
        antes = self.ssr
        super()._ssr_on()
        if self.ssr and not antes:
            self._ep = list(self.episodios[self._k_ep % len(self.episodios)])
            self._k_ep += 1
            self._ultima_alarma = None
            self.atascada = False

    def _con_ssr(self, linea: str) -> str:
        return linea.replace("SSR:F1(LEVE)", "SSR:OFF").replace(
            "SSR:OFF", "SSR:F1(LEVE)" if self.ssr else "SSR:OFF")

    def _r_recibida(self) -> bool:
        """'r' nueva desde la última trama (detector_init + dir_init: el detector vuelve a SANO)."""
        nuevos = self.recibidos[self._n_vistos:]
        self._n_vistos = len(self.recibidos)
        return "r" in nuevos

    def _enclavar(self):
        self.atascada = True
        self._ep = None
        self._tx(self._con_ssr(self._ultima_alarma))

    def _trama(self):
        if self._r_recibida() and not self.ssr:
            self.atascada, self._ep, self._ultima_alarma = False, None, None
        if self.atascada:                      # alarma enclavada hasta 'r' (solo con enclavada=True)
            self._tx(self._con_ssr(self._ultima_alarma))
            return
        while self._ep:                        # líneas del episodio real hasta su siguiente trama
            x = self._ep.pop(0)
            if not _es_trama(x):
                self._tx(x)
                continue
            if "| SANO |" not in x:
                self._ultima_alarma = x
            elif self.enclavada and self._ultima_alarma is not None and not self.ssr:
                return self._enclavar()        # en vez de liberarse, queda enclavada
            self._tx(self._con_ssr(x))
            return
        if self.enclavada and self._ultima_alarma is not None and not self.ssr:
            return self._enclavar()
        self._ep = None
        self._ultima_alarma = None
        self._tx(self.reposo[self._k_reposo % len(self.reposo)])
        self._k_reposo += 1
