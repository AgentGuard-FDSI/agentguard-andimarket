"""Caja de herramientas de la Config. B: cada llamada pasa por AgentGuard antes de ejecutarse.

Envuelve la misma caja de la Config. A (RegistryToolbox), sin tocar las herramientas ni el
bucle del agente:

    ALLOW -> registra la decisión y ejecuta la herramienta.
    HITL  -> pide aprobación al aprobador inyectado; registra; ejecuta solo si se aprueba.
    BLOCK -> registra y devuelve un error al modelo; la herramienta no se ejecuta.

La identidad (usuario, área, nivel) es la de la sesión con la que se creó la caja, nunca la
que el modelo ponga en los argumentos. Si la decisión no se puede registrar en el audit log,
la acción no se ejecuta (fail-closed).
"""

from __future__ import annotations

from typing import Any, Callable

from agentguard import AgentGuard, ApprovalRequest, Approver

from andimarket import auditoria
from andimarket.agent.loop import Toolbox
from andimarket.session import Session


class GuardedToolbox:
    def __init__(
        self,
        guard: AgentGuard,
        session: Session,
        approver: Approver,
        inner: Toolbox,
        emit: Callable[[str], None] = print,
    ):
        self._guard = guard
        self._session = session
        self._approver = approver
        self._inner = inner
        self._emit = emit

    def definitions(self) -> list[dict]:
        # Las mismas herramientas que la Config. A: la única diferencia entre A y B es AgentGuard.
        return self._inner.definitions()

    def execute(self, name: str, arguments: dict) -> dict[str, Any]:
        decision = self._guard.authorize(self._session, name, arguments)
        self._emit(f"[agentguard] {decision}")

        aprobacion = None
        if decision.needs_approval:
            aprobacion = self._approver.request(
                ApprovalRequest.from_decision(self._session, name, arguments, decision)
            )
            estado = "aprobada" if aprobacion.approved else "rechazada"
            self._emit(f"[agentguard] solicitud HITL {estado} por {aprobacion.approver}")

        autorizada = decision.allowed or bool(aprobacion and aprobacion.approved)
        try:
            auditoria.registrar_decision(
                session=self._session, tool=name, arguments=arguments,
                decision=decision, aprobacion=aprobacion, autorizada=autorizada,
            )
        except Exception as exc:  # noqa: BLE001 - cualquier fallo del registro bloquea la acción
            self._emit(f"[agentguard] no se pudo registrar la decisión ({exc}); acción no ejecutada")
            return {"ok": False, "error": "AgentGuard no pudo registrar la decisión; la acción no se ejecutó"}

        if autorizada:
            return self._inner.execute(name, arguments)
        if decision.blocked:
            mensaje = f"AgentGuard bloqueó la acción: {decision.reason}"
        else:
            mensaje = f"La acción requiere aprobación humana y fue rechazada por {aprobacion.approver}"
        return {"ok": False, "error": mensaje, "agentguard": decision.to_dict()}
