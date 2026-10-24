"""Ejecuciones en segundo plano y aprobación HITL desde la web.

El agente corre en un hilo aparte para que la petición HTTP responda de inmediato. El frontend
consulta los eventos con polling (GET /api/ejecuciones/{id}?desde=N) hasta que la ejecución
termina. Cada línea que el agente emite (lo mismo que se ve en consola) es un evento numerado.

HITL: cuando authorize() responde HITL, AprobadorWeb deja la solicitud PENDING en la cola de
agentguard-core (ApprovalService) y el hilo espera. Quien aprueba la decide desde su sesión
(POST /api/aprobaciones/{id}); ApprovalService valida la separación de funciones (no el
solicitante; solo el jefe del área o gerencia). Si nadie responde en el tiempo límite, la
solicitud se anula y la acción no se ejecuta (fail-closed).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from agentguard import ApprovalRequest, ApprovalResult, ApprovalService
from agentguard.hitl import APPROVED, PENDING, REJECTED

from andimarket.directorio import aprobador_para
from andimarket.session import Session

EN_CURSO, ESPERANDO_APROBACION, TERMINADA, ERROR = "en_curso", "esperando_aprobacion", "terminada", "error"
PREFIJOS = (("[agentguard]", "agentguard"), ("[agent]", "agente"), ("[modelo]", "modelo"))


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class Evento:
    seq: int
    ts: str
    tipo: str        # agente | agentguard | modelo | hitl_pendiente | hitl_resuelta | seccion | info
    texto: str
    datos: dict[str, Any] = field(default_factory=dict)

    def a_dict(self) -> dict[str, Any]:
        return {"seq": self.seq, "ts": self.ts, "tipo": self.tipo, "texto": self.texto, **self.datos}


class Ejecucion:
    """Una corrida del agente (chat) o de la comparación, con sus eventos y su resultado."""

    def __init__(self, tipo: str, sesion: Session, entrada: str):
        self.id = uuid4().hex[:16]
        self.tipo = tipo                  # chat | comparacion | experimento
        self.sesion = sesion
        self.entrada = entrada
        self.run_id: str | None = None
        self.estado = EN_CURSO
        self.creada = _ahora()
        self.terminada: str | None = None
        self.resultado: dict[str, Any] | None = None
        self.error: str | None = None
        self.solicitud_pendiente: dict[str, Any] | None = None
        self._eventos: list[Evento] = []
        self._lock = threading.Lock()

    # -- lo que llama el hilo del agente -----------------------------------
    def emitir(self, texto: str, tipo: str | None = None, **datos: Any) -> None:
        if tipo is None:
            tipo = next((t for prefijo, t in PREFIJOS if texto.startswith(prefijo)), "info")
        with self._lock:
            self._eventos.append(Evento(len(self._eventos) + 1, _ahora(), tipo, texto, datos))

    def esperando(self, solicitud: dict[str, Any]) -> None:
        with self._lock:
            self.estado = ESPERANDO_APROBACION
            self.solicitud_pendiente = solicitud

    def reanudar(self) -> None:
        with self._lock:
            self.estado = EN_CURSO
            self.solicitud_pendiente = None

    def terminar(self, resultado: dict[str, Any]) -> None:
        with self._lock:
            self.resultado = resultado
            self.estado = TERMINADA
            self.terminada = _ahora()

    def fallar(self, error: str) -> None:
        with self._lock:
            self.error = error
            self.estado = ERROR
            self.terminada = _ahora()

    # -- lo que lee la API --------------------------------------------------
    @property
    def activa(self) -> bool:
        return self.estado in (EN_CURSO, ESPERANDO_APROBACION)

    def a_dict(self, desde: int = 0) -> dict[str, Any]:
        with self._lock:
            return {
                "id": self.id,
                "tipo": self.tipo,
                "run_id": self.run_id,
                "estado": self.estado,
                "entrada": self.entrada,
                "creada": self.creada,
                "terminada": self.terminada,
                "solicitud_pendiente": self.solicitud_pendiente,
                "eventos": [e.a_dict() for e in self._eventos if e.seq > desde],
                "ultimo_evento": len(self._eventos),
                "resultado": self.resultado,
                "error": self.error,
            }

    def resumen(self) -> dict[str, Any]:
        with self._lock:
            respuesta = (self.resultado or {}).get("respuesta_final")
            return {
                "id": self.id, "tipo": self.tipo, "run_id": self.run_id, "estado": self.estado,
                "entrada": self.entrada, "creada": self.creada, "respuesta": respuesta,
            }


class AprobadorWeb:
    """Aprobador HITL de la API: deja la solicitud en la cola y espera a que la decida otra persona.

    `aplica_separacion_de_funciones` le indica a run_config_b que no lo envuelva en ValidatingApprover:
    aquí la validación la hace ApprovalService.decidir() cuando el aprobador responde desde su sesión.
    """

    aplica_separacion_de_funciones = True

    def __init__(
        self,
        servicio: ApprovalService,
        ejecucion: Ejecucion,
        aviso: threading.Condition,
        *,
        run_id: str | None,
        espera_segundos: float,
    ):
        self._servicio = servicio
        self._ejecucion = ejecucion
        self._aviso = aviso
        self._run_id = run_id
        self._espera = espera_segundos

    def request(self, req: ApprovalRequest) -> ApprovalResult:
        try:
            solicitud_id = self._servicio.solicitar(req, run_id=self._run_id)
        except Exception as exc:  # noqa: BLE001 - si no se puede registrar la solicitud, no se aprueba
            return ApprovalResult(False, "sistema", f"no se pudo registrar la solicitud ({type(exc).__name__})")

        sugerido = _aprobador_sugerido(req)
        pendiente = {
            "solicitud": solicitud_id, "herramienta": req.tool, "argumentos": dict(req.arguments),
            "motivo": req.reason, "aprobador_sugerido": sugerido, "espera_segundos": self._espera,
        }
        self._ejecucion.esperando(pendiente)
        self._ejecucion.emitir(
            f"[hitl] solicitud {solicitud_id} pendiente: {req.tool} espera la aprobación de "
            f"{sugerido or 'el jefe del área'} (máximo {self._espera:.0f} s)",
            tipo="hitl_pendiente", **pendiente,
        )
        try:
            return self._esperar(solicitud_id)
        finally:
            self._ejecucion.reanudar()

    def _esperar(self, solicitud_id: int) -> ApprovalResult:
        limite = time.monotonic() + self._espera
        with self._aviso:
            while True:
                solicitud = self._servicio.obtener(solicitud_id)
                restante = limite - time.monotonic()
                if solicitud is None or solicitud.estado != PENDING or restante <= 0:
                    break
                self._aviso.wait(min(restante, 0.5))

        if solicitud is not None and solicitud.estado == PENDING:
            self._servicio.anular(solicitud_id, "sin respuesta del aprobador en el tiempo límite")
            solicitud = self._servicio.obtener(solicitud_id)  # pudo decidirse justo antes de anular

        if solicitud is not None and solicitud.estado in (APPROVED, REJECTED):
            aprobada = solicitud.estado == APPROVED
            self._ejecucion.emitir(
                f"[hitl] solicitud {solicitud_id} {'aprobada' if aprobada else 'rechazada'} por {solicitud.aprobador}",
                tipo="hitl_resuelta", solicitud=solicitud_id, aprobada=aprobada, aprobador=solicitud.aprobador,
            )
            return ApprovalResult(aprobada, solicitud.aprobador or "", solicitud.comentario or "")

        self._ejecucion.emitir(
            f"[hitl] solicitud {solicitud_id} anulada: nadie respondió a tiempo; la acción no se ejecuta",
            tipo="hitl_resuelta", solicitud=solicitud_id, aprobada=False, aprobador=None,
        )
        return ApprovalResult(False, "sin_respuesta", "sin respuesta del aprobador en el tiempo límite")


def _aprobador_sugerido(req: ApprovalRequest) -> str | None:
    try:
        return aprobador_para(Session(req.usuario, req.area, req.nivel)).usuario
    except LookupError:
        return None
