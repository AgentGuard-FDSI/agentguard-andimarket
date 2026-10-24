"""Directorio de personas de demostración de ANDIMARKET (área y nivel de cada usuario).

AgentGuard no administra usuarios: la organización le entrega un directorio para comprobar quién
puede aprobar una solicitud HITL (separación de funciones). Este es el de la demostración; en una
empresa real vendría de su sistema de identidad.

Los usuarios coinciden con los de las pruebas de agentguard-core y con las sesiones de los prompts.
"""

from __future__ import annotations

from agentguard import InMemoryDirectory

from andimarket.session import Session

USUARIOS: tuple[Session, ...] = (
    Session("ana.atencion", "atencion_cliente", "empleado"),
    Session("laura.atencion", "atencion_cliente", "jefe"),
    Session("luis.logistica", "logistica_operaciones", "empleado"),
    Session("lina.logistica", "logistica_operaciones", "jefe"),
    Session("mara.marketing", "marketing_comunicaciones", "empleado"),
    Session("maria.marketing", "marketing_comunicaciones", "jefe"),
    Session("fabio.finanzas", "finanzas", "empleado"),
    Session("felipe.finanzas", "finanzas", "jefe"),
    Session("tomas.ti", "tecnologia_ti", "jefe"),
    Session("gloria.gerencia", "gerencia", "gerente"),
)


def crear_directorio() -> InMemoryDirectory:
    return InMemoryDirectory(USUARIOS)


def buscar(usuario: str) -> Session | None:
    clave = str(usuario or "").strip().casefold()
    return next((s for s in USUARIOS if s.usuario == clave), None)


def jefe_de(area: str) -> Session:
    """El jefe del área (quien aprueba por defecto las solicitudes HITL de su equipo)."""
    for s in USUARIOS:
        if s.area == area and s.nivel in ("jefe", "gerente"):
            return s
    raise LookupError(f"no hay jefe registrado para el área {area!r}")


def aprobador_para(solicitante: Session) -> Session:
    """Quien aprueba por defecto: el jefe del área; si quien pide es ese jefe, gerencia (última instancia)."""
    jefe = jefe_de(solicitante.area)
    return jefe if jefe.usuario != solicitante.usuario else jefe_de("gerencia")
