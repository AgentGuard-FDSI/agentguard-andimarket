"""Adaptador de las herramientas simuladas (paquete `tools`) a la interfaz que espera el bucle del agente."""

from typing import Any

from tools import TOOL_DEFINITIONS, execute_tool


class RegistryToolbox:
    """Caja de herramientas de la Config. A: pasa cada llamada a execute_tool sin validar permisos."""

    def definitions(self) -> list[dict]:
        return list(TOOL_DEFINITIONS)

    def execute(self, name: str, arguments: dict) -> dict[str, Any]:
        return execute_tool(name, arguments)
