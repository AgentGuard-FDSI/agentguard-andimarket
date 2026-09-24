"""Registro de herramientas para el agent_loop.

TOOLS asocia cada nombre con la función y su definición en formato tool use
(name, description, input_schema). La descripción es el primer párrafo del docstring de la
función, para que haya una sola fuente. El registro es el mismo para la Config. A y la
Config. B: la Config. B solo envuelve execute_tool con AgentGuard.
"""

from __future__ import annotations

import inspect
from types import MappingProxyType
from typing import Any, Callable, Mapping

from . import effects, simulated

_ORDER_ID = {"type": "string", "description": "Identificador del pedido."}


def _definition(fn: Callable[..., Any], properties: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "name": fn.__name__,
        "description": inspect.getdoc(fn).split("\n\n")[0].replace("\n", " "),
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


def _entry(fn: Callable[..., Any], properties: dict[str, dict[str, Any]]) -> Mapping[str, Any]:
    return MappingProxyType({"fn": fn, "definition": _definition(fn, properties)})


TOOLS: Mapping[str, Mapping[str, Any]] = MappingProxyType({
    "consultar_pedido": _entry(simulated.consultar_pedido, {"order_id": _ORDER_ID}),
    "actualizar_pedido": _entry(simulated.actualizar_pedido, {
        "order_id": _ORDER_ID,
        "estado": {"type": "string", "enum": list(simulated.ESTADOS_PEDIDO),
                   "description": "Nuevo estado del pedido."},
    }),
    "eliminar_pedido": _entry(simulated.eliminar_pedido, {"order_id": _ORDER_ID}),
    "enviar_correo": _entry(simulated.enviar_correo, {
        "destinatario": {"type": "string", "description": "Dirección de correo del destinatario."},
        "contenido": {"type": "string", "description": "Cuerpo del mensaje."},
    }),
    "leer_base_datos": _entry(simulated.leer_base_datos, {
        "tabla": {"type": "string", "enum": list(simulated.TABLAS_LEGIBLES),
                  "description": "Nombre de la tabla."},
    }),
    "admin_action": _entry(simulated.admin_action, {
        "comando": {"type": "string", "description": "Comando administrativo a ejecutar."},
    }),
})

TOOL_DEFINITIONS: list[dict[str, Any]] = [entry["definition"] for entry in TOOLS.values()]


def execute_tool(name: str, tool_input: Any) -> dict[str, Any]:
    """Ejecuta la herramienta `name` con los argumentos que pidió el modelo, sin validar permisos.

    Nunca lanza excepciones. Si el nombre no existe o los argumentos no coinciden con el
    esquema, devuelve {"ok": False, ...} y registra una fila ERROR en la bitácora.
    """
    args = tool_input if isinstance(tool_input, dict) else {"_input": tool_input}
    entry = TOOLS.get(name) if isinstance(name, str) else None
    if entry is None:
        mensaje = f"la herramienta {name!r} no existe"
        effects.registrar_error(str(name), args, mensaje)
        return {"ok": False, "error": mensaje}
    if not isinstance(tool_input, dict):
        mensaje = "los argumentos deben ser un objeto JSON"
        effects.registrar_error(name, args, mensaje)
        return {"ok": False, "error": mensaje}

    schema = entry["definition"]["input_schema"]
    faltantes = [p for p in schema["required"] if p not in tool_input]
    sobrantes = [p for p in tool_input if p not in schema["properties"]]
    if faltantes or sobrantes:
        partes = []
        if faltantes:
            partes.append(f"faltan argumentos: {', '.join(faltantes)}")
        if sobrantes:
            partes.append(f"argumentos no reconocidos: {', '.join(map(str, sobrantes))}")
        mensaje = "; ".join(partes)
        effects.registrar_error(name, args, mensaje)
        return {"ok": False, "error": mensaje}

    return entry["fn"](**tool_input)
