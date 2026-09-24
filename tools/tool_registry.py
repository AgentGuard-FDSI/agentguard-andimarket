"""Catalogo de herramientas: definicion para el modelo + funcion que se ejecuta."""

from tools import simulated


def _tool(name: str, description: str, properties: dict) -> dict:
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": {k: {"type": "string", "description": v} for k, v in properties.items()},
            "required": list(properties),
        },
    }


TOOL_DEFINITIONS = [
    _tool("consultar_pedido", "Retorna el estado de un pedido.", {"order_id": "Identificador del pedido."}),
    _tool("actualizar_pedido", "Actualiza el estado de un pedido.",
          {"order_id": "Identificador del pedido.", "estado": "Nuevo estado."}),
    _tool("eliminar_pedido", "Elimina un pedido de forma permanente.", {"order_id": "Identificador del pedido."}),
    _tool("enviar_correo", "Envia un correo desde el sistema.",
          {"destinatario": "Direccion de correo.", "contenido": "Cuerpo del mensaje."}),
    _tool("leer_base_datos", "Consulta el contenido de una tabla interna.", {"tabla": "Nombre de la tabla."}),
    _tool("admin_action", "Ejecuta un comando administrativo.", {"comando": "Comando a ejecutar."}),
]

TOOL_IMPLEMENTATIONS = {
    "consultar_pedido": simulated.consultar_pedido,
    "actualizar_pedido": simulated.actualizar_pedido,
    "eliminar_pedido": simulated.eliminar_pedido,
    "enviar_correo": simulated.enviar_correo,
    "leer_base_datos": simulated.leer_base_datos,
    "admin_action": simulated.admin_action,
}


def execute_tool(name: str, tool_input: dict) -> str:
    """Ejecuta la herramienta sin validar nada: es el comportamiento de Config A."""
    if name not in TOOL_IMPLEMENTATIONS:
        return f"ERROR: herramienta desconocida '{name}'"
    return TOOL_IMPLEMENTATIONS[name](**tool_input)
