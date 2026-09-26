"""Bucle del agente: instrucción -> modelo -> herramienta -> resultado -> modelo, hasta que no pida más.

El bucle no valida nada: ejecuta la herramienta que el modelo pida con los argumentos que pida. La
Config. A lo usa tal cual; la Config. B lo usa con una caja de herramientas envuelta por AgentGuard.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from andimarket.models.base import ModelClient
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
    model: ModelClient,
    toolbox: Toolbox,
    session: Session | None = None,
    emit: Callable[[str], None] = print,
) -> AgentResult:
    messages: list[dict] = [{"role": "user", "content": instruction}]
    trace: list[ToolRecord] = []
    definitions = toolbox.definitions()
    if session is not None:
        emit(f"[agent] sesión: {session.usuario} ({session.area}, {session.nivel})")
    emit(f"[agent] instrucción: {instruction!r}")

    for iteration in range(1, MAX_ITERACIONES + 1):
        response = model.next(messages, definitions)
        emit(f"[agent] --- iteración {iteration} ---")
        if response.text:
            emit(f"[agent] modelo dice: {response.text}")
        messages.append({"role": "assistant", "content": response.text, "tool_calls": response.tool_calls})

        if not response.tool_calls:
            emit("[agent] respuesta final, fin del bucle")
            return AgentResult(response.text, trace, iteration)

        for call in response.tool_calls:
            emit(f"[agent] herramienta solicitada: {call.name} {call.arguments}")
            result = toolbox.execute(call.name, call.arguments)
            trace.append(ToolRecord(call.name, dict(call.arguments), result))
            emit(f"[agent] resultado de {call.name}: {result!r}")
            messages.append({"role": "tool", "name": call.name, "content": json.dumps(result, ensure_ascii=False)})

    emit("[agent] se alcanzó el máximo de iteraciones")
    return AgentResult("(máximo de iteraciones alcanzado)", trace, MAX_ITERACIONES)
