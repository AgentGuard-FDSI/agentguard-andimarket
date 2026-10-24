"""Caja de herramientas de la Config. B: cada llamada pasa por AgentGuard antes de ejecutarse.

Envuelve la misma caja de la Config. A (RegistryToolbox), sin tocar las herramientas ni el
bucle del agente:

    ALLOW -> registra la decisión y ejecuta la herramienta.
    HITL  -> pide aprobación al aprobador inyectado; registra; ejecuta solo si se aprueba.
    BLOCK -> registra y devuelve un error al modelo; la herramienta no se ejecuta.

Avance 3:
  * authorize() recibe solicitud=run_id, para que el límite de pedidos por solicitud cuente
    todas las llamadas de la misma corrida (escenario 8: un lote repartido en varias llamadas).
  * Después de cada authorize(), la regla entre áreas observa la decisión (avisos y alerta).
  * Cada decisión queda también en el log encadenado (AuditChain) de agentguard-core.

La identidad (usuario, área, nivel) es la de la sesión con la que se creó la caja, nunca la
que el modelo ponga en los argumentos. Si la decisión no se puede registrar (en audit_logs o en
la cadena), la acción no se ejecuta (fail-closed).
"""

from __future__ import annotations

from typing import Any, Callable

from agentguard import ApprovalRequest, Approver

from andimarket import auditoria
from andimarket.agent.loop import Toolbox
from andimarket.session import Session


class GuardedToolbox:
    def __init__(
        self,
        guard: Any,
        session: Session,
        approver: Approver,
        inner: Toolbox,
        emit: Callable[[str], None] = print,
        *,
        run_id: str | None = None,
        entre_areas: Any = None,
        cadena: Any = None,
    ):
        self._guard = guard
        self._session = session
        self._approver = approver
        self._inner = inner
        self._emit = emit
        self._run_id = run_id
        self._entre_areas = entre_areas
        self._cadena = cadena

    def definitions(self) -> list[dict]:
        # Las mismas herramientas que la Config. A: la única diferencia entre A y B es AgentGuard.
        return self._inner.definitions()

    def execute(self, name: str, arguments: dict) -> dict[str, Any]:
        decision = self._guard.authorize(self._session, name, arguments, solicitud=self._run_id)
        self._emit(f"[agentguard] {decision}")

        if self._entre_areas is not None:
            evento = self._entre_areas.observe_decision(self._session, name, arguments, decision, run_id=self._run_id)
            if evento.violation:
                self._emit(f"[agentguard] acceso entre áreas: {evento.resource}; aviso a {', '.join(evento.owner_areas)}")
            if evento.alert:
                self._emit(f"[agentguard] ALERTA PRIORITARIA: {self._session.usuario} acumula "
                           f"{evento.attempts_in_window} accesos a otras áreas (posible cuenta comprometida)")

        aprobacion = None
        if decision.needs_approval:
            aprobacion = self._approver.request(
                ApprovalRequest.from_decision(self._session, name, arguments, decision)
            )
            estado = "aprobada" if aprobacion.approved else "rechazada"
            detalle = f" ({aprobacion.rule}: {aprobacion.comment})" if getattr(aprobacion, "rule", "") else ""
            self._emit(f"[agentguard] solicitud HITL {estado} por {aprobacion.approver}{detalle}")

        autorizada = decision.allowed or bool(aprobacion and aprobacion.approved)
        try:
            auditoria.registrar_decision(
                session=self._session, tool=name, arguments=arguments,
                decision=decision, aprobacion=aprobacion, autorizada=autorizada,
            )
            if self._cadena is not None:
                self._cadena.registrar_decision(
                    self._session, name, arguments, decision, run_id=self._run_id,
                    extra={"config": "B", "autorizada": autorizada, "aprobacion": _aprobacion_dict(aprobacion)},
                )
        except Exception as exc:  # noqa: BLE001 - cualquier fallo del registro bloquea la acción
            self._emit(f"[agentguard] no se pudo registrar la decisión ({exc}); acción no ejecutada")
            return {"ok": False, "error": "AgentGuard no pudo registrar la decisión; la acción no se ejecutó"}

        if autorizada:
            return self._inner.execute(name, arguments)
        if decision.blocked:
            mensaje = f"AgentGuard bloqueó la acción: {decision.reason}"
        elif getattr(aprobacion, "rule", ""):
            mensaje = f"La acción requiere aprobación humana y no se aprobó: {aprobacion.comment}"
        else:
            mensaje = f"La acción requiere aprobación humana y fue rechazada por {aprobacion.approver}"
        return {"ok": False, "error": mensaje, "agentguard": decision.to_dict()}


def _aprobacion_dict(aprobacion: Any) -> dict[str, Any] | None:
    if aprobacion is None:
        return None
    return {
        "aprobado": bool(aprobacion.approved),
        "aprobador": aprobacion.approver,
        "comentario": getattr(aprobacion, "comment", ""),
        "regla": getattr(aprobacion, "rule", "") or None,
    }
