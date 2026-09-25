"""Interfaz común de los modelos del agente.

Cualquier modelo (simulado, Gemini, Groq u Ollama) se adapta a esta interfaz: recibe el historial y las
definiciones de herramientas y devuelve texto y, opcionalmente, llamadas a herramientas.
"""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ToolCall:
    name: str
    arguments: dict


@dataclass
class ModelResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class ModelClient(Protocol):
    def next(self, messages: list[dict], tool_definitions: list[dict]) -> ModelResponse:
        """Devuelve el siguiente paso del modelo. Sin tool_calls, el agente termina."""
        ...
