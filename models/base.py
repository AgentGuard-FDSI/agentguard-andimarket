"""Interfaz común de modelo para el agent_loop (secciones 5.1 y 8.2 de la propuesta).

El agente llama siempre a un objeto que cumple el protocolo `Modelo`, obtenido con `models.get_model()`. Así
el mismo agent_loop funciona igual con cualquier backend, incluido el modo simulado (sin
llave, determinista) que se usa en la demostración en vivo (sección 4 de la propuesta).

    from models import get_model
    modelo = get_model()  # lee MODEL_BACKEND del entorno; "simulado" si no hay ninguno
    respuesta = modelo.generar(historial, TOOL_DEFINITIONS)

`historial` es una lista de mensajes, con el mismo formato de entrada y de salida:

    {"role": "system", "content": "instrucciones del agente"}      (opcional, al inicio)
    {"role": "user", "content": "texto"}
    {"role": "assistant", "content": "texto" | None, "tool_calls": [ToolCall-dict, ...] | None}
    {"role": "tool", "tool_call_id": "...", "name": "...", "content": "texto (normalmente JSON)"}

`TOOL_DEFINITIONS` es el formato que ya expone `tools.registry` (name, description,
input_schema en JSON Schema): cada adaptador lo traduce al formato propio de su proveedor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolCall:
    """Una llamada a herramienta que pide el modelo, con un id para emparejar su resultado."""

    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class RespuestaModelo:
    """Lo que devuelve Modelo.generar(): o texto final, o una o más llamadas a herramienta.

    Nunca las dos cosas a la vez: si `tool_calls` no está vacío, el agent_loop debe ejecutarlas
    (con `execute_tool`, sin decidir nada por su cuenta) y volver a llamar a generar() con el
    resultado añadido al historial; si está vacío, `texto` es la respuesta final.
    """

    texto: str | None = None
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)

    @property
    def es_final(self) -> bool:
        return not self.tool_calls


class Modelo(Protocol):
    """Todo backend implementa esto. `nombre` es informativo (bitácora, reportes, informe)."""

    nombre: str

    def generar(
        self, historial: list[dict[str, Any]], tool_definitions: list[dict[str, Any]]
    ) -> RespuestaModelo: ...


class ModeloError(Exception):
    """Error al invocar el backend del modelo: red, autenticación o respuesta inesperada.

    El agent_loop la deja propagar (no la convierte en una decisión de política; eso no es
    responsabilidad de la interfaz de modelo).
    """


# ---------------------------------------------------------------------------
# Helpers para construir mensajes del historial en el formato canónico
# ---------------------------------------------------------------------------
def mensaje_sistema(texto: str) -> dict[str, Any]:
    return {"role": "system", "content": texto}


def mensaje_usuario(texto: str) -> dict[str, Any]:
    return {"role": "user", "content": texto}


def mensaje_asistente(respuesta: RespuestaModelo) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": respuesta.texto,
        "tool_calls": [
            {"id": tc.id, "name": tc.name, "input": tc.input} for tc in respuesta.tool_calls
        ]
        or None,
    }


def mensaje_tool_result(tool_call_id: str, name: str, resultado_json: str) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": tool_call_id, "name": name, "content": resultado_json}


def texto_de_mensaje(mensaje: dict[str, Any]) -> str:
    """Texto plano de un mensaje del historial, para que los backends por reglas (simulado)
    o basados en texto puedan inspeccionar el contenido sin conocer la forma exacta.
    """
    return str(mensaje.get("content") or "")
