"""Modelo de guion: cumple la interfaz `Modelo` de `models` y reproduce pasos fijos, sin red ni claves.

Sirve para los ataques que un modelo por reglas no reproduce (por ejemplo la inyección indirecta, donde
la instrucción viene escondida en un dato): el guion simula que el modelo obedece.
"""

from typing import Any

from models.base import RespuestaModelo, ToolCall

Paso = tuple[str, list[tuple[str, dict[str, Any]]]]  # (texto, [(herramienta, argumentos), ...])


class ModeloGuion:
    nombre = "guion"

    def __init__(self, pasos: list[Paso], texto_final: str):
        self._pasos = pasos
        self._texto_final = texto_final
        self._indice = 0

    def generar(self, historial: list[dict[str, Any]], tool_definitions: list[dict[str, Any]]) -> RespuestaModelo:
        if self._indice >= len(self._pasos):
            return RespuestaModelo(texto=self._texto_final)
        texto, llamadas = self._pasos[self._indice]
        self._indice += 1
        return RespuestaModelo(
            texto=texto,
            tool_calls=tuple(
                ToolCall(id=f"call_{self._indice}_{n}", name=nombre, input=dict(args))
                for n, (nombre, args) in enumerate(llamadas, start=1)
            ),
        )
