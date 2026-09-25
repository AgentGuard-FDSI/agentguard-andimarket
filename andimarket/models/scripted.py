"""Modelo simulado y determinista: reproduce un guion fijo de pasos, sin red ni claves."""

from andimarket.models.base import ModelResponse, ToolCall


class ScriptedModel:
    """Devuelve un paso del guion por llamada; agotado el guion, cierra con el texto final."""

    def __init__(self, pasos: list[tuple[str, list[ToolCall]]], texto_final: str):
        self._pasos = pasos
        self._texto_final = texto_final
        self._indice = 0

    def next(self, messages: list[dict], tool_definitions: list[dict]) -> ModelResponse:
        if self._indice < len(self._pasos):
            texto, llamadas = self._pasos[self._indice]
            self._indice += 1
            return ModelResponse(text=texto, tool_calls=list(llamadas))
        return ModelResponse(text=self._texto_final)
