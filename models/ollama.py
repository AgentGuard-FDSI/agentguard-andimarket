"""Backend Ollama (modelo local, sin llave ni cuota).

Requiere Ollama corriendo (https://ollama.com) y un modelo con soporte de herramientas
descargado, por ejemplo: `ollama pull llama3.1`.

Variables: OLLAMA_HOST (por defecto http://localhost:11434), OLLAMA_MODEL, MODEL_TEMPERATURE.
"""

from __future__ import annotations

from itertools import count
from typing import Any

from . import _config
from ._formatos import mensajes_openai, respuesta_desde_openai, tools_openai
from ._http import post_json
from .base import ModeloError, RespuestaModelo

HOST_POR_DEFECTO = "http://localhost:11434"
MODELO_POR_DEFECTO = "llama3.1"


class ModeloOllama:
    def __init__(self) -> None:
        self.host = _config.opcional("OLLAMA_HOST", HOST_POR_DEFECTO).rstrip("/")
        self.modelo = _config.opcional("OLLAMA_MODEL", MODELO_POR_DEFECTO)
        self.temperatura = _config.temperatura()
        self.nombre = f"ollama:{self.modelo}"
        self._turno = count(1)

    def generar(self, historial: list[dict[str, Any]], tool_definitions: list[dict[str, Any]]) -> RespuestaModelo:
        body: dict[str, Any] = {
            "model": self.modelo,
            "messages": mensajes_openai(historial, argumentos_como_texto=False),
            "stream": False,
            "options": {"temperature": self.temperatura},
        }
        if tool_definitions:
            body["tools"] = tools_openai(tool_definitions)
        # Un modelo local puede tardar en cargar la primera vez: timeout más largo y sin
        # esperas largas entre reintentos.
        data = post_json(f"{self.host}/api/chat", body, timeout=300.0, espera_base=1.0, proveedor="Ollama")
        mensaje = data.get("message")
        if not isinstance(mensaje, dict):
            raise ModeloError("Ollama devolvió una respuesta sin 'message'")
        return respuesta_desde_openai(mensaje, prefijo_id=f"oll-{next(self._turno)}")
