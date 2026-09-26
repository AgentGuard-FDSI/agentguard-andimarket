"""Sesión de la persona que usa el asistente: su identidad viene de aquí, no del prompt."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Session:
    usuario: str
    area: str
    nivel: str  # "empleado" o "jefe"
