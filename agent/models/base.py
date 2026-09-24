"""Interfaz comun de los modelos (simulado, Gemini, Groq, Ollama).

complete() recibe el historial y las definiciones de herramientas y devuelve
(stop_reason, content): stop_reason es "tool_use" o "end_turn", y content es una
lista de bloques {"type": "text", "text": ...} o
{"type": "tool_use", "id": ..., "name": ..., "input": {...}}.
"""

from typing import Protocol


class ModelBackend(Protocol):
    def complete(self, messages: list[dict], tools: list[dict]) -> tuple[str, list[dict]]: ...
