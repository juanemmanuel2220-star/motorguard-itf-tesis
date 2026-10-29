"""
Control de pulsos de inyección por el SSR con bloqueos de seguridad.

Es lógica pura (sin Qt ni puerto): recibe las líneas parseadas, el estado de la conexión y la hora,
y devuelve la lista de comandos a enviar. Así cada bloqueo se prueba con un reloj simulado.

Reglas (encargo, etapa 2):
- Solo existen los comandos '1' y '0'. Cualquier otro se rechaza aquí, antes de llegar al puerto.
- Nunca se envía '1' sin una confirmación humana emitida para ese plan (un uso, caduca en 60 s).
- Pulso de 1 a 11 s (el firmware corta a los 12 s); enfriamiento >= 15 s (>= 20 s con taps SEVERA);
  máximo 10 pulsos por serie.
- Bloqueo si no hay conexión, si la última trama es vieja, si el motor no está en ON (OFF o WARMUP)
  o si el firmware reporta el SSR encendido.
- '0' ante PARO, al cerrar, si el firmware no confirma el encendido o el apagado, si el motor se
  apaga durante el pulso. Al reconectar, la fuente serie envía '0' (como los scripts de validación).

Serie con disparo externo (sección Adquisición): la confirmación humana arma una serie de hasta 10 pulsos,
pero cada '1' lo pide la adquisición con disparar(), después de aceptar una trama SANO. Valen los mismos
bloqueos; si en 60 s no se dispara ningún pulso, la serie armada se cancela.

Registro: un CSV por sesión con cada pulso, la confirmación del firmware y la firma observada.
"""

import csv
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from motorguard_dashboard.telemetry.parser import NOMBRES_SEV, EventoSSR, Trama

COMANDOS_PERMITIDOS = ("1", "0")
TAPS = ("LEVE", "INTER", "SEVERA")

PULSO_MIN_S = 1.0
PULSO_MAX_S = 11.0
ENFRIAMIENTO_MIN_S = 15.0
ENFRIAMIENTO_SEVERA_S = 20.0
MAX_PULSOS_SERIE = 10
TRAMA_RECIENTE_S = 5.0        # el firmware manda una trama cada ~1.7 s
ESPERA_FIRMWARE_S = 3.0       # tiempo para que el firmware confirme el encendido o el apagado
VENTANA_FIRMA_S = 8.0         # tras el apagado se siguen mirando tramas para registrar la firma
VIGENCIA_CONFIRMACION_S = 60.0
VIGENCIA_ARMADA_S = 60.0      # una serie con disparo externo se cancela si pasa este tiempo sin pulsos
MAX_PULSOS_MEMORIA = 1000     # en memoria; el CSV guarda todos
ESPERA_ARRANQUE_S = 300.0     # tras encender el motor, el detector dio una falsa alarma (09-oct 15:01): se
                              # recomienda esperar ~5 min. Es un AVISO; el bloqueo duro sigue siendo WARMUP.

COLUMNAS_CSV = [
    "n", "serie", "pulso_en_serie", "taps_declarados", "solicitud", "t_solicitud", "duracion_pedida_s",
    "confirmacion_fw", "motivo_rechazo_fw", "t_encendido", "t_apagado", "t_on_ms_fw", "forzado_fw",
    "resultado", "alarma_confirmada", "latencia_alarma_s", "sev_max", "ml_max_pp", "p_max_pp", "i1_A",
]


def enfriamiento_minimo(taps: str) -> float:
    return ENFRIAMIENTO_SEVERA_S if taps == "SEVERA" else ENFRIAMIENTO_MIN_S


@dataclass(frozen=True)
class PlanSerie:
    taps: str            # taps conectados, declarados por el usuario
    duracion_s: float
    n_pulsos: int
    pausa_s: float       # entre el apagado de un pulso y el encendido del siguiente
    externo: bool = False  # True: cada pulso lo dispara la adquisición (disparar), no el temporizador


def validar_plan(plan: PlanSerie) -> Optional[str]:
    """Motivo por el que el plan no es válido, o None."""
    if plan.taps not in TAPS:
        return "elige qué taps están conectados"
    if not PULSO_MIN_S <= plan.duracion_s <= PULSO_MAX_S:
        return f"la duración debe estar entre {PULSO_MIN_S:g} y {PULSO_MAX_S:g} s"
    if not 1 <= plan.n_pulsos <= MAX_PULSOS_SERIE:
        return f"la serie debe tener entre 1 y {MAX_PULSOS_SERIE} pulsos"
    if plan.pausa_s < enfriamiento_minimo(plan.taps):
        return f"la pausa con taps {plan.taps} debe ser de al menos {enfriamiento_minimo(plan.taps):g} s"
    return None


@dataclass(frozen=True)
class Confirmacion:
    """Comprobante de que una persona confirmó el plan en el diálogo de seguridad."""
    id: int
    plan: PlanSerie
    t: float


@dataclass
class Pulso:
    n: int
    serie: int
    pulso_en_serie: int
    taps: str
    t_solicitud: float
    duracion: float
    confirmacion_fw: str = "pendiente"      # pendiente / encendido / rechazado / sin respuesta
    motivo_rechazo: str = ""
    t_encendido: Optional[float] = None
    t_apagado: Optional[float] = None
    t_on_ms: Optional[int] = None
    forzado: Optional[bool] = None
    resultado: str = ""
    alarma: bool = False
    t_alarma: Optional[float] = None
    sev_max: int = 0
    ml_max: float = 0.0
    p_max: Optional[float] = None
    i1: Optional[float] = None
    t_fin_ventana: Optional[float] = None


class ControlInyeccion:
    LIBRE, ESPERA_ENCENDIDO, ENCENDIDO, ESPERA_APAGADO, PAUSA = (
        "LIBRE", "ESPERA_ENCENDIDO", "ENCENDIDO", "ESPERA_APAGADO", "PAUSA")

    def __init__(self, ruta_csv: Optional[str] = None):
        self.estado = self.LIBRE
        self.conectado = False
        self.ultima_trama: Optional[Trama] = None
        self.t_motor_encendido: Optional[float] = None   # hora (de la trama) en que el motor pasó de OFF a encendido
        self._motor_visto_apagado = False
        self.t_ultimo_apagado: Optional[float] = None
        self.taps_ultimo: Optional[str] = None
        self.pulsos: List[Pulso] = []
        self._n_pulsos = 0
        self.mensaje = ""                      # último aviso para la interfaz
        self._pulso: Optional[Pulso] = None    # pulso con el SSR pedido/encendido
        self._en_ventana: List[Pulso] = []     # pulsos apagados cuya firma se sigue registrando
        self._plan: Optional[PlanSerie] = None
        self._restantes = 0
        self._serie = 0
        self._t_cmd = 0.0
        self._reintento_cero = False
        self._t_armada = 0.0
        self._conf_emitidas = {}
        self._conf_id = 0
        self._f = self._w = None
        if ruta_csv:
            os.makedirs(os.path.dirname(ruta_csv), exist_ok=True)
            self._f = open(ruta_csv, "w", newline="", encoding="utf-8")
            self._w = csv.writer(self._f)
            self._w.writerow(COLUMNAS_CSV)
            self._f.flush()

    # ================================================================ consultas
    @property
    def en_curso(self) -> bool:
        return self.estado != self.LIBRE

    @property
    def armada(self) -> bool:
        """Serie con disparo externo esperando su pulso siguiente."""
        return self.estado == self.PAUSA and self._plan is not None and self._plan.externo and self._restantes > 0

    @property
    def restantes(self) -> int:
        return self._restantes if self.en_curso else 0

    @property
    def pulso_actual(self) -> Optional[Pulso]:
        """Pulso con el SSR pedido o encendido (None si no hay)."""
        return self._pulso

    @property
    def pulsos_abiertos(self) -> List[Pulso]:
        """Pulsos que todavía pueden cambiar: el actual y los apagados cuya firma se sigue registrando."""
        return ([self._pulso] if self._pulso else []) + self._en_ventana

    def enfriamiento_restante(self, ahora: float, taps: Optional[str] = None) -> float:
        if self.t_ultimo_apagado is None:
            return 0.0
        # Se respeta el enfriamiento más largo entre los taps del último pulso y los del nuevo
        minimo = max(enfriamiento_minimo(taps or ""), enfriamiento_minimo(self.taps_ultimo or ""))
        return max(0.0, self.t_ultimo_apagado + minimo - ahora)

    def aviso_arranque(self, ahora: float) -> Optional[str]:
        """Aviso (no bloqueo) si el motor lleva menos de ~5 min encendido o no se sabe desde cuándo."""
        t = self.ultima_trama
        if t is None or t.motor == "OFF":
            return None
        if self.t_motor_encendido is None:
            return ("el motor ya estaba encendido al abrir la app: si lo acabas de encender, espera ~5 min "
                    "(el detector puede dar una falsa alarma al arrancar)")
        transcurrido = ahora - self.t_motor_encendido
        if transcurrido < ESPERA_ARRANQUE_S:
            return (f"motor encendido hace {transcurrido / 60:.1f} min: espera hasta ~5 min "
                    "(el detector puede dar una falsa alarma al arrancar)")
        return None

    def minutos_encendido(self, ahora: float) -> Optional[float]:
        return None if self.t_motor_encendido is None else (ahora - self.t_motor_encendido) / 60.0

    def bloqueo(self, ahora: float, taps: Optional[str] = None, con_enfriamiento: bool = True) -> Optional[str]:
        """Motivo por el que no se puede encender el SSR ahora, o None."""
        if not self.conectado:
            return "sin conexión con el Arduino"
        t = self.ultima_trama
        if t is None or t.t is None or ahora - t.t > TRAMA_RECIENTE_S:
            return f"sin telemetría reciente (> {TRAMA_RECIENTE_S:g} s)"
        if t.motor != "ON":
            return f"motor en {t.motor}: solo se inyecta con el motor en ON (fuera de WARMUP)"
        if t.ssr != "OFF":
            return f"el firmware reporta el SSR encendido ({t.ssr})"
        if self.estado in (self.ESPERA_ENCENDIDO, self.ENCENDIDO, self.ESPERA_APAGADO):
            return "hay un pulso en curso"
        resta = self.enfriamiento_restante(ahora, taps) if con_enfriamiento else 0.0
        if resta > 0:
            return f"enfriamiento: faltan {resta:.0f} s"
        return None

    # ================================================================ confirmación humana
    def emitir_confirmacion(self, plan: PlanSerie, ahora: float) -> Confirmacion:
        """Lo llama la interfaz SOLO después de que la persona aceptó el diálogo de seguridad."""
        self._conf_id += 1
        conf = Confirmacion(self._conf_id, plan, ahora)
        self._conf_emitidas[conf.id] = conf
        return conf

    # ================================================================ órdenes
    def iniciar_serie(self, conf: Confirmacion, ahora: float) -> List[str]:
        emitida = self._conf_emitidas.pop(getattr(conf, "id", None), None)
        if emitida is None or emitida != conf:
            return self._aviso("confirmación inválida o ya usada: no se envía nada")
        if ahora - conf.t > VIGENCIA_CONFIRMACION_S:
            return self._aviso("la confirmación caducó: vuelve a confirmar")
        error = validar_plan(conf.plan)
        if error:
            return self._aviso(f"plan inválido: {error}")
        if self.en_curso:
            return self._aviso("ya hay una serie en curso")
        # Una serie externa se puede armar durante el enfriamiento: disparar() lo vuelve a exigir
        motivo = self.bloqueo(ahora, conf.plan.taps, con_enfriamiento=not conf.plan.externo)
        if motivo:
            return self._aviso(f"bloqueado: {motivo}")
        self._plan = conf.plan
        self._restantes = conf.plan.n_pulsos
        self._serie += 1
        if conf.plan.externo:
            self.estado = self.PAUSA
            self._t_armada = ahora
            self.mensaje = f"serie armada: {conf.plan.n_pulsos} pulso(s) a pedido de la adquisición"
            return []
        return self._encender(ahora)

    def disparar(self, ahora: float) -> List[str]:
        """Pulso siguiente de una serie armada con disparo externo (lo pide la adquisición)."""
        if not self.armada:
            return self._aviso("no hay una serie armada: no se envía nada")
        if self.t_ultimo_apagado is not None and ahora < self.t_ultimo_apagado + self._plan.pausa_s:
            return self._aviso(f"pausa: faltan {self.t_ultimo_apagado + self._plan.pausa_s - ahora:.0f} s")
        motivo = self.bloqueo(ahora, self._plan.taps)
        if motivo:
            return self._aviso(f"pulso no disparado: {motivo}")
        return self._encender(ahora)

    def cancelar_armada(self, motivo: str = "serie armada cancelada"):
        """Cancela una serie armada sin pulso en curso (el SSR ya está apagado: no hace falta enviar nada)."""
        if self.armada:
            self._restantes = 0
            self.estado = self.LIBRE
            self.mensaje = motivo

    def paro(self, ahora: float) -> List[str]:
        """PARO: siempre devuelve '0'; cancela la serie y el pulso en curso."""
        self._restantes = 0
        if self._pulso is not None and self.estado in (self.ESPERA_ENCENDIDO, self.ENCENDIDO):
            self._pulso.resultado = self._pulso.resultado or "PARO manual"
            self.estado = self.ESPERA_APAGADO
            self._t_cmd = ahora
        elif self.estado == self.PAUSA:
            self.estado = self.LIBRE
        self.mensaje = "PARO: SSR apagado y serie cancelada"
        return self._cmd("0")

    def cerrar(self, ahora: float) -> List[str]:
        """Al cerrar la app: '0' y se cierra el registro."""
        if self._pulso is not None:
            self._pulso.resultado = self._pulso.resultado or "app cerrada durante el pulso"
        cmds = self.paro(ahora)
        if self._pulso is not None:
            self._terminar_pulso(self._pulso, ahora, inmediato=True)
        for p in list(self._en_ventana):
            self._escribir(p)
        self._en_ventana.clear()
        if self._f:
            self._f.close()
            self._f = self._w = None
        return cmds

    # ================================================================ entradas
    def conexion(self, conectado: bool, ahora: float) -> List[str]:
        anterior, self.conectado = self.conectado, conectado
        if anterior and not conectado:
            self._restantes = 0
            if self._pulso is not None:
                self._pulso.resultado = "conexión perdida durante el pulso (el firmware corta a los 12 s)"
                self._terminar_pulso(self._pulso, ahora)
            self.estado = self.LIBRE
            # Sin confirmación del apagado: el enfriamiento cuenta desde la pérdida de conexión
            self.t_ultimo_apagado = ahora
            self.mensaje = "conexión perdida: serie cancelada; al reconectar se envía '0'"
        return []

    def procesar(self, obj, ahora: float) -> List[str]:
        if isinstance(obj, Trama):
            return self._procesar_trama(obj, ahora)
        if isinstance(obj, EventoSSR):
            return self._procesar_ssr(obj, ahora)
        return []

    def tic(self, ahora: float) -> List[str]:
        cmds: List[str] = []
        p = self._pulso
        if self.estado == self.ESPERA_ENCENDIDO and ahora - self._t_cmd > ESPERA_FIRMWARE_S:
            p.confirmacion_fw = "sin respuesta"
            p.resultado = "el firmware no confirmó el encendido"
            cmds += self._cmd("0")
            self._restantes = 0
            self._terminar_pulso(p, ahora)
            self.estado = self.LIBRE
            self.mensaje = "el firmware no confirmó el encendido: se envió '0' y se canceló la serie"
        elif self.estado == self.ENCENDIDO and ahora - p.t_encendido >= p.duracion:
            cmds += self._apagar(ahora)
        elif self.estado == self.ESPERA_APAGADO and ahora - self._t_cmd > ESPERA_FIRMWARE_S:
            if not self._reintento_cero:
                self._reintento_cero = True
                self._t_cmd = ahora
                cmds += self._cmd("0")
                self.mensaje = "el firmware no confirmó el apagado: se reenvía '0'"
            else:
                p.resultado = (p.resultado + "; " if p.resultado else "") + "apagado sin confirmar por el firmware"
                self._restantes = 0
                self._terminar_pulso(p, ahora)
                self.estado = self.LIBRE
                self.mensaje = "⚠ el firmware no confirmó el apagado: revisa el SSR (el firmware corta a los 12 s)"
        elif self.estado == self.PAUSA and self._plan.externo:
            if ahora - max(self._t_armada, self.t_ultimo_apagado or 0.0) > VIGENCIA_ARMADA_S:
                self._restantes = 0
                self.estado = self.LIBRE
                self.mensaje = f"serie armada cancelada: ningún pulso en {VIGENCIA_ARMADA_S:g} s"
        elif self.estado == self.PAUSA and self.t_ultimo_apagado is not None \
                and ahora >= self.t_ultimo_apagado + self._plan.pausa_s:
            motivo = self.bloqueo(ahora, self._plan.taps)
            if motivo:
                self._restantes = 0
                self.estado = self.LIBRE
                self.mensaje = f"serie detenida antes del pulso siguiente: {motivo}"
            else:
                cmds += self._encender(ahora)
        for q in list(self._en_ventana):
            if ahora >= q.t_fin_ventana:
                self._en_ventana.remove(q)
                self._escribir(q)
        return cmds

    # ================================================================ interno
    def _procesar_trama(self, t: Trama, ahora: float) -> List[str]:
        self.ultima_trama = t
        if t.motor == "OFF":
            self._motor_visto_apagado = True
            self.t_motor_encendido = None
        elif self._motor_visto_apagado and self.t_motor_encendido is None:
            self.t_motor_encendido = t.t
        cmds: List[str] = []
        for p in ([self._pulso] if self._pulso else []) + self._en_ventana:
            if p.t_encendido is not None and t.t >= p.t_encendido:
                self._anotar_firma(p, t)
        p = self._pulso
        if p is not None and self.estado in (self.ESPERA_ENCENDIDO, self.ENCENDIDO) and t.motor != "ON":
            p.resultado = f"motor en {t.motor} durante el pulso"
            self._restantes = 0
            cmds += self._apagar(ahora)
        elif p is not None and self.estado == self.ESPERA_APAGADO and t.ssr == "OFF" and t.t > self._t_cmd + 0.3:
            # La telemetría ya muestra el SSR apagado aunque se haya perdido el mensaje [DEBUG SSR]
            self._confirmar_apagado(ahora, t_on_ms=None, forzado=None)
        return cmds

    def _procesar_ssr(self, e: EventoSSR, ahora: float) -> List[str]:
        p = self._pulso
        if p is None:
            return []
        if e.tipo == "encendido" and self.estado == self.ESPERA_ENCENDIDO:
            p.confirmacion_fw = "encendido"
            p.t_encendido = ahora
            self.estado = self.ENCENDIDO
            self.mensaje = f"pulso {p.pulso_en_serie}/{self._plan.n_pulsos} encendido"
        elif e.tipo == "rechazado" and self.estado == self.ESPERA_ENCENDIDO:
            p.confirmacion_fw = "rechazado"
            p.motivo_rechazo = e.motivo or ""
            p.resultado = "rechazado por el firmware"
            self._restantes = 0
            self._terminar_pulso(p, ahora)
            self.estado = self.LIBRE
            self.mensaje = f"el firmware rechazó el pulso: {e.motivo}"
            return self._cmd("0")
        elif e.tipo == "apagado" and self.estado in (self.ENCENDIDO, self.ESPERA_APAGADO):
            if self.estado == self.ENCENDIDO and not p.resultado:
                p.resultado = ("cortado por el firmware (protección)" if e.forzado
                               else "apagado antes de tiempo por el firmware")
                self._restantes = 0
            self._confirmar_apagado(ahora, e.t_on_ms, e.forzado)
        return []

    def _encender(self, ahora: float) -> List[str]:
        self._restantes -= 1
        self._n_pulsos += 1
        self._pulso = Pulso(
            n=self._n_pulsos, serie=self._serie,
            pulso_en_serie=self._plan.n_pulsos - self._restantes, taps=self._plan.taps,
            t_solicitud=ahora, duracion=self._plan.duracion_s)
        self.pulsos.append(self._pulso)
        if len(self.pulsos) > MAX_PULSOS_MEMORIA:
            del self.pulsos[:-MAX_PULSOS_MEMORIA]
        self.estado = self.ESPERA_ENCENDIDO
        self._t_cmd = ahora
        self.mensaje = f"pulso {self._pulso.pulso_en_serie}/{self._plan.n_pulsos}: esperando confirmación del firmware"
        return self._cmd("1")

    def _apagar(self, ahora: float) -> List[str]:
        self.estado = self.ESPERA_APAGADO
        self._t_cmd = ahora
        self._reintento_cero = False
        return self._cmd("0")

    def _confirmar_apagado(self, ahora: float, t_on_ms, forzado):
        p = self._pulso
        p.t_on_ms, p.forzado = t_on_ms, forzado
        p.resultado = p.resultado or "completo"
        self._terminar_pulso(p, ahora)
        if self._restantes > 0:
            self.estado = self.PAUSA
            self.mensaje = f"pausa antes del pulso {p.pulso_en_serie + 1}/{self._plan.n_pulsos}"
        else:
            self.estado = self.LIBRE
            self.mensaje = f"serie terminada ({p.pulso_en_serie} pulso(s)); último: {p.resultado}"

    def _terminar_pulso(self, p: Pulso, ahora: float, inmediato: bool = False):
        p.t_apagado = ahora
        self.t_ultimo_apagado = ahora
        self.taps_ultimo = p.taps
        self._pulso = None
        self._reintento_cero = False
        if inmediato or p.t_encendido is None:
            self._escribir(p)
        else:
            p.t_fin_ventana = ahora + VENTANA_FIRMA_S
            self._en_ventana.append(p)

    def _anotar_firma(self, p: Pulso, t: Trama):
        if p.i1 is None:
            p.i1 = t.i1
        p.p_max = t.dir.p if p.p_max is None else max(p.p_max, t.dir.p)
        if t.dir.enclavada:
            if not p.alarma:
                p.alarma, p.t_alarma = True, t.t
            p.sev_max = max(p.sev_max, t.dir.sev)
            p.ml_max = max(p.ml_max, t.dir.ml)

    def _escribir(self, p: Pulso):
        if not self._w:
            return

        def iso(x):
            return datetime.fromtimestamp(x).strftime("%Y-%m-%d %H:%M:%S") if x is not None else ""

        def num(x, fmt):
            return format(x, fmt) if x is not None else ""

        self._w.writerow([
            p.n, p.serie, p.pulso_en_serie, p.taps, iso(p.t_solicitud), f"{p.t_solicitud:.3f}",
            f"{p.duracion:g}", p.confirmacion_fw, p.motivo_rechazo, num(p.t_encendido, ".3f"),
            num(p.t_apagado, ".3f"), num(p.t_on_ms, "d"), "" if p.forzado is None else int(p.forzado),
            p.resultado, int(p.alarma),
            num(p.t_alarma - p.t_encendido if p.alarma and p.t_encendido else None, ".1f"),
            NOMBRES_SEV[p.sev_max] if p.alarma else "", f"{p.ml_max:.3f}" if p.alarma else "",
            num(p.p_max, ".3f"), num(p.i1, ".4f"),
        ])
        self._f.flush()

    def _aviso(self, texto: str) -> List[str]:
        self.mensaje = texto
        return []

    @staticmethod
    def _cmd(c: str) -> List[str]:
        if c not in COMANDOS_PERMITIDOS:
            raise ValueError(f"comando no permitido: {c!r}")
        return [c]
