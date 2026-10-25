"""Controles de la Config. B: las piezas de agentguard-core, creadas una sola vez por proceso.

    verificador de entrada (InputGuard)   revisa el prompt ANTES de llamar al modelo
    authorize() (AgentGuard)              decide ALLOW, BLOCK o HITL por cada herramienta
    regla entre áreas (CrossAreaMonitor)  observa los BLOCK y alerta si se repiten
    aprobaciones (ApprovalService)        cola HITL con separación de funciones
    log encadenado (AuditChain)           cada decisión y aviso, con hash SHA-256 encadenado
    avisos (InMemoryNotifier)             lo que la API mostrará en las alertas del frontend

Deben crearse una sola vez (por proceso o por experimento): si se crean por corrida, la regla
entre áreas nunca acumula los 3 intentos en 10 minutos.

La política se lee de ../agentguard-core/config/policies.yaml (o --politica o AGENTGUARD_POLICY).
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from agentguard import (
    AgentGuard, ApprovalService, AuditChain, AuditNotifier, CrossAreaMonitor, InMemoryDirectory,
    InMemoryNotifier, InputGuard, MultiNotifier,
)

from andimarket.directorio import crear_directorio
from tools import db

POLITICA_POR_DEFECTO = Path(__file__).resolve().parents[2] / "agentguard-core" / "config" / "policies.yaml"


def ruta_politica(explicita: str | Path | None = None) -> Path:
    """--politica, luego AGENTGUARD_POLICY, luego el repositorio agentguard-core vecino."""
    return Path(explicita or os.environ.get("AGENTGUARD_POLICY") or POLITICA_POR_DEFECTO)


def es_cliente_registrado(correo: str) -> bool:
    """True si el correo pertenece a un cliente de la base de trabajo (restricción recipient_in)."""
    conn = sqlite3.connect(db.settings().ruta_trabajo)
    try:
        fila = conn.execute(
            "SELECT 1 FROM clientes WHERE lower(correo) = lower(?) LIMIT 1", (str(correo).strip(),)
        ).fetchone()
        return fila is not None
    finally:
        conn.close()


def crear_guard(politica: str | Path | None = None) -> AgentGuard:
    """Carga la política una sola vez (fail-closed: PolicyError si es inválida o no existe)."""
    return AgentGuard.from_file(ruta_politica(politica), es_cliente=es_cliente_registrado)


@dataclass
class ControlesB:
    guard: Any                      # AgentGuard, o un envoltorio con authorize() y policy (p. ej. cronometrado)
    entrada: InputGuard
    entre_areas: CrossAreaMonitor
    cadena: AuditChain
    avisos: InMemoryNotifier
    aprobaciones: ApprovalService
    directorio: InMemoryDirectory
    verificador_activo: bool = True

    @property
    def policy(self):
        return self.guard.policy

    def avisos_de(self, run_id: str) -> list[dict[str, Any]]:
        """Notificaciones (verificador, entre áreas, alertas) que produjo una corrida."""
        return [n.to_dict() for n in self.avisos.items if n.detalle.get("run_id") == run_id]

    def cerrar(self) -> None:
        self.aprobaciones.close()
        self.cadena.close()


def crear_controles(
    guard: Any = None,
    *,
    politica: str | Path | None = None,
    carpeta: str | Path | None = None,
    verificador: bool = True,
    reloj: Callable[[], float] | None = None,
) -> ControlesB:
    """Arma los controles de la Config. B.

    carpeta: dónde guardar el log encadenado (audit_chain.db) y la cola HITL (hitl.db). Sin carpeta,
             todo queda en memoria (pruebas).
    verificador: False para medir la Config. B sin el verificador de entrada (escenario 6 en authorize()).
    reloj: segundos (time.monotonic por defecto); se inyecta para simular la ventana de 10 minutos.
    """
    guard = guard if guard is not None else crear_guard(politica)
    policy = guard.policy
    carpeta = Path(carpeta) if carpeta is not None else None
    cadena = AuditChain(carpeta / "audit_chain.db" if carpeta else ":memory:")
    avisos = InMemoryNotifier()
    notificador = MultiNotifier([avisos, AuditNotifier(cadena)])
    entre_areas = (
        CrossAreaMonitor(policy, notifier=notificador, clock=reloj) if reloj
        else CrossAreaMonitor(policy, notifier=notificador)
    )
    directorio = crear_directorio()
    return ControlesB(
        guard=guard,
        entrada=InputGuard(policy, notifier=notificador, chain=cadena),
        entre_areas=entre_areas,
        cadena=cadena,
        avisos=avisos,
        aprobaciones=ApprovalService(policy, directorio, carpeta / "hitl.db" if carpeta else ":memory:", chain=cadena),
        directorio=directorio,
        verificador_activo=verificador,
    )


def como_controles(obj: Any) -> ControlesB:
    """Acepta ControlesB o un AgentGuard suelto (compatibilidad con el Avance 2: controles en memoria)."""
    return obj if isinstance(obj, ControlesB) else crear_controles(obj)
