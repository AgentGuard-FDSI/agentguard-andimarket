"""Bucle del agente: instrucción -> modelo -> herramienta -> resultado -> modelo, hasta que no pida más.

El bucle no valida nada: ejecuta la herramienta que el modelo pida con los argumentos que pida. La
Config. A lo usa tal cual; la Config. B lo usa con una caja de herramientas envuelta por AgentGuard.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from models.base import Modelo, mensaje_asistente, mensaje_sistema, mensaje_tool_result, mensaje_usuario
from andimarket.session import Session

MAX_ITERACIONES = 8


class Toolbox(Protocol):
    def definitions(self) -> list[dict]: ...

    def execute(self, name: str, arguments: dict) -> dict[str, Any]: ...


@dataclass
class ToolRecord:
    """Una llamada a herramienta que el agente efectivamente ejecutó."""

    name: str
    arguments: dict
    result: dict[str, Any]

    @property
    def ok(self) -> bool:
        return bool(self.result.get("ok"))


@dataclass
class AgentResult:
    final_text: str
    trace: list[ToolRecord] = field(default_factory=list)
    iterations: int = 0


def run_agent(
    instruction: str,
    model: Modelo,
    toolbox: Toolbox,
    session: Session | None = None,
    emit: Callable[[str], None] = print,
    sistema: str | None = None,
) -> AgentResult:
    historial: list[dict] = ([mensaje_sistema(sistema)] if sistema else []) + [mensaje_usuario(instruction)]
    trace: list[ToolRecord] = []
    definitions = toolbox.definitions()
    if session is not None:
        emit(f"[agent] sesión: {session.usuario} ({session.area}, {session.nivel})")
    emit(f"[agent] instrucción: {instruction!r}")

    for iteration in range(1, MAX_ITERACIONES + 1):
        respuesta = model.generar(historial, definitions)
        emit(f"[agent] --- iteración {iteration} ---")
        if respuesta.texto:
            emit(f"[agent] modelo dice: {respuesta.texto}")
        historial.append(mensaje_asistente(respuesta))

        if respuesta.es_final:
            emit("[agent] respuesta final, fin del bucle")
            return AgentResult(respuesta.texto or "", trace, iteration)

        for call in respuesta.tool_calls:
            emit(f"[agent] herramienta solicitada: {call.name} {call.input}")
            result = toolbox.execute(call.name, call.input)
            trace.append(ToolRecord(call.name, dict(call.input), result))
            emit(f"[agent] resultado de {call.name}: {result!r}")
            historial.append(mensaje_tool_result(call.id, call.name, json.dumps(result, ensure_ascii=False)))

    emit("[agent] se alcanzó el máximo de iteraciones")
    return AgentResult("(máximo de iteraciones alcanzado)", trace, MAX_ITERACIONES)
